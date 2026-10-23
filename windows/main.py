# -*- coding: utf-8 -*-
"""FlashDrop Windows 入口"""

import argparse
import ctypes
import os
import socket
import sys
import threading
import time

# 保证 PyInstaller --onefile 模式下能找到 app 包
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 单实例锁端口：绑定成功表示首个实例；占用则唤起已有实例后退出
# v1.18.35：支持 FLASHDROP_LOCK_PORT 环境变量覆盖（测试隔离，
# 不与本机真实例的 58898 相互干扰）
LOCK_PORT = int(os.environ.get("FLASHDROP_LOCK_PORT", "58898")) or 58898

# ★ v1.18.35（用户反馈"电脑端可以打开好多个客户端 需要限制一下"）：
#   旧实现有个致命启动窗口 —— PING 只由 MainWindow._start_ipc_listener
#   应答，而那要等 Config/FlashNode/MainWindow 全部构建完（PySide6 导入
#   + 建窗可达数秒）才开始。期间第二个实例 bind 失败 → PING 无人应答 →
#   误判「孤儿锁」→ 带 SO_REUSEADDR 抢占（Windows 上 REUSEADDR 可与
#   活实例共存绑定）→ 两个实例同时运行。用户双击后见窗口迟迟不出、
#   再点一次，正是这个场景。
#   修复 = 三道闸：
#     ① bind 成功后立即起 responder 线程应答 PING（不等 UI）——
#        「已 bind 未应答」窗口归零；
#     ② main() 最顶部（重导入之前）用 Windows 命名互斥量判重 ——
#        内核级互斥、进程死亡 OS 自动释放（无僵尸锁），覆盖
#        解包/导入窗口；互斥量已存在 ⇒ 必有实例在启动或运行；
#     ③ PING 探活支持快速重试，进一步压缩误判空间。


def parse_args(argv):
    ap = argparse.ArgumentParser(prog="FlashDrop", description="闪传 · 局域网互传")
    ap.add_argument("--port", type=int, default=None, help="服务端口（默认 58899）")
    ap.add_argument("--connect", metavar="HOST[:PORT]", default=None,
                    help="启动后立即连接指定设备，例如 192.168.1.101 或 192.168.1.101:58899")
    ap.add_argument("--hidden", action="store_true", help="启动后最小化到托盘")
    return ap.parse_args(argv)


def parse_connect(s):
    if not s:
        return None
    if ":" in s:
        host, _, port = s.rpartition(":")
        try:
            return host, int(port)
        except ValueError:
            return None
    return s, None


def _lock_is_alive(timeout=1.5, tries=1):
    """向锁端口发 PING，若收到 PONG 说明**真有实例活着**。

    ★ 为什么需要它（v1.18.9）：
    原实现只要 `bind()` 失败就认定「已有实例」，直接退出。
    但 Windows 上 UDP 端口可能被**僵死的残留进程**或
    **其他程序**占用 —— 此时发 SHOW 无人应答，用户双击 EXE
    就得到「什么都不发生」= 打不开。
    改为：先 PING 探活，无应答则**抢占**（视为孤儿锁）。
    v1.18.35：支持 tries 快速重试（配合提前 responder，活实例
    应答在 bind 后毫秒级；重试只为覆盖极端调度延迟）。
    """
    for i in range(max(1, tries)):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.settimeout(timeout)
            s.sendto(b"FlashDrop_PING", ("127.0.0.1", LOCK_PORT))
            data, _ = s.recvfrom(64)
            if b"PONG" in data:
                return True
        except Exception:
            pass
        finally:
            s.close()
        if i < tries - 1:
            time.sleep(0.4)
    return False


# 模块级持有互斥量句柄：句柄被 GC/关闭 = 释放互斥，等于没锁
_INSTANCE_MUTEX = None


class _LockSocket(socket.socket):
    """锁 socket：socket 有 __slots__ 挂不了自定义属性，
    responder 回调注册（fd_ipc_cb）需要一个无 __slots__ 的载体。
    ★ 默认必须是 SOCK_DGRAM（socket.socket 裸构造默认是 TCP！
    锁语义全程依赖 UDP PING/PONG，v1.18.35 验收 D1b~D5 抓出）。"""

    def __init__(self, family=socket.AF_INET, type=socket.SOCK_DGRAM,
                 proto=0):
        super().__init__(family, type, proto)


def _acquire_instance_mutex():
    """尝试创建单实例命名互斥量。返回 True 表示「已有实例」（获取失败）。

    内核命名互斥量是 Windows 单实例的标准做法：
    - 创建即原子判定，无任何竞态窗口；
    - 进程退出/崩溃时 OS 自动关闭句柄释放互斥 → **不存在僵尸锁**，
      天然没有 v1.18.9「孤儿锁」问题。
    Global 命名空间跨会话生效（与 UDP 端口的全局性一致）；
    创建失败（受限环境）时退化为仅 UDP 锁，不影响启动。
    """
    global _INSTANCE_MUTEX
    if os.name != "nt":
        return False
    kernel32 = ctypes.windll.kernel32
    for name in ("Global\\FlashDrop.SingleInstance",
                 "Local\\FlashDrop.SingleInstance"):
        try:
            h = kernel32.CreateMutexW(None, False, name)
        except Exception:
            return False
        if not h:
            continue                     # 该命名空间创建失败 → 试下一个
        _INSTANCE_MUTEX = h              # 保持引用，防 GC 释放
        # ERROR_ALREADY_EXISTS = 183
        return kernel32.GetLastError() == 183
    return False


def _start_lock_responder(sock):
    """★ v1.18.35：bind 成功后**立即**应答 PING，不等 UI 构建完成。

    旧时序：bind →(数秒的导入+建窗)→ _start_ipc_listener 才应答 PING。
    窗口期内的第二实例 PING 无人应答 → 误判孤儿锁 → REUSEADDR 抢占
    → 双实例。responder 把应答提前到 bind 后毫秒级，窗口归零。

    SHOW 的处理：注册到 sock.fd_ipc_cb["show"] 回调（初始 None）。
    MainWindow._start_ipc_listener 不再自己收包（两个 reader 会瓜分
    数据报），只把 ipcShow.emit 注册进来。
    （socket 有 __slots__ 挂不了属性 → 用无 __slots__ 的 LockSocket）
    """
    cb = {"show": None}

    def _loop():
        try:
            sock.settimeout(1.0)
            while True:
                try:
                    data, addr = sock.recvfrom(256)
                except socket.timeout:
                    continue
                except OSError:
                    return          # 套接字被关闭（退出流程）
                if b"PING" in data:
                    try:
                        sock.sendto(b"FlashDrop_PONG", addr)
                    except Exception:
                        pass
                elif b"SHOW" in data:
                    f = cb.get("show")
                    if f:
                        try:
                            f()
                        except Exception:
                            pass
        except Exception:
            pass

    threading.Thread(target=_loop,
                     name="flashdrop-lock-ipc", daemon=True).start()
    try:
        sock.fd_ipc_cb = cb
    except Exception:
        pass


def _notify_instance_show(tries=3):
    """请已有实例唤起窗口；重试几次提高送达率。"""
    for i in range(max(1, tries)):
        try:
            snd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            snd.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            snd.sendto(b"FlashDrop_SHOW", ("127.0.0.1", LOCK_PORT))
            snd.close()
            return True
        except Exception:
            time.sleep(0.15 * (i + 1))
    return False


def single_instance_lock():
    """返回锁 socket（首个实例）；已有实例时发送 SHOW 并返回 None。

    环境变量 FLASHDROP_ALLOW_MULTI=1 可解除限制（调试用）。

    ★ v1.18.9 修复「EXE 双击打不开」：
      1. 允许**抢占孤儿锁**：bind 失败但 PING 无人应答 → 说明前一个
         实例已死/端口被他人占，此时不能傻等，要清理后接管。
      2. SHOW 通知带重试，避免丢包导致唤不起来。
    """
    allow_multi = os.environ.get("FLASHDROP_ALLOW_MULTI") == "1"

    def _try_bind(reuse=False):
        s = _LockSocket()
        if reuse:
            # 仅用于「抢占孤儿锁」：允许与已失效的绑定共存
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            except Exception:
                pass
        try:
            s.bind(("127.0.0.1", LOCK_PORT))
            return s
        except OSError:
            s.close()
            return None

    first = _try_bind()
    if first is not None:
        # ★ v1.18.35：立即开始应答 PING（不等 UI），消灭启动窗口期
        _start_lock_responder(first)
        return first

    # 端口被占：先确认对方是否真的活着（带快速重试）
    if _lock_is_alive(tries=3):
        if not allow_multi:
            _notify_instance_show()
            return None                      # 正常单实例：交给已有实例
        # 多开模式：已有实例活着 → 本实例不拿锁，但继续运行
        return None

    # 无人应答 = 孤儿锁（残留进程/他人占用）→ 抢占，保证用户能打开
    reclaimed = _try_bind(reuse=True)
    if reclaimed is not None:
        _start_lock_responder(reclaimed)
        return reclaimed
    # 实在抢不到（被别的程序硬占）→ 不阻断启动，只是失去单实例保护
    fb = _try_bind() or _LockSocket()
    _start_lock_responder(fb)
    return fb


def main():
    # ★ v1.18.35 第一道闸：命名互斥量判重 —— 必须放在**一切重导入
    #   之前**（PySide6 导入 + 建窗可达数秒，这段窗口旧实现完全不设防：
    #   第二实例在此期间 bind 成功就多开了）。互斥量已存在 ⇒ 必有实例
    #   在启动或运行（进程死亡 OS 自动释放，无僵尸）→ PING 确认后退出。
    #   调试多开（FLASHDROP_ALLOW_MULTI=1）与非 Windows 跳过。
    if os.environ.get("FLASHDROP_ALLOW_MULTI") != "1" \
            and _acquire_instance_mutex():
        alive = _lock_is_alive(timeout=1.0, tries=6)
        if alive:
            _notify_instance_show()
        print("FlashDrop 已在运行，已唤起现有窗口")
        sys.exit(0)

    from app.config import Config
    from app.node import FlashNode
    from app.ui.main_window import MainWindow
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt

    args = parse_args(sys.argv[1:])

    ipc_sock = single_instance_lock()
    if ipc_sock is None:
        if os.environ.get("FLASHDROP_ALLOW_MULTI") == "1":
            # ★ v1.18.32 修复：多开调试模式此前是死路 —— single_instance_lock
            #   在「锁被活实例持有」时无论是否多开都返回 None，而这里对 None
            #   一律退出，注释承诺的"继续运行"从未生效（冒烟测试被真实例
            #   挡住就是它暴露的）。MainWindow 本就支持 ipc_sock=None（跳过
            #   IPC 监听），此处放行即可。
            print("FlashDrop 多开模式：已有实例在运行，本实例不接管单实例锁")
        else:
            # 已有实例在运行：已发送唤起请求，直接退出
            print("FlashDrop 已在运行，已唤起现有窗口")
            sys.exit(0)

    cfg = Config()
    if args.port:
        cfg["port"] = args.port
        cfg.save()

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    app.setApplicationName("FlashDrop")

    node = FlashNode(cfg)
    win = MainWindow(cfg, node, ipc_sock=ipc_sock)
    if args.hidden:
        win.hide()
    else:
        # ★ v1.18.13（用户第 6 条）：「有时打不开，且首次打开时直接在后台，
        #   界面不在前台出现」。
        #
        #   根因：PyInstaller onefile 启动时先解包到临时目录，过程中会短暂
        #   创建一个控制台/引导进程窗口。等 Qt 窗口创建出来时，前台资格已经
        #   被其他进程（或用户当前正在操作的窗口）占住。此时单纯 `show()`
        #   只能让窗口"存在"，无法抢到前台 —— 观感就是"打开了但界面没在
        #   前台出现"。
        #
        #   修法三步：
        #     ① show() 让窗口完成首次映射（必须，否则 hwnd 尚未建立）
        #     ② 在事件循环真正跑起来后（QTimer.singleShot 0）再抢前台 ——
        #        太早调用时窗口还没 map，SetForegroundWindow 会失败
        #     ③ 用 _force_foreground 的 AttachThreadInput 技巧兜底
        win.show()
        try:
            from PySide6.QtCore import QTimer
            from app.ui.main_window import _force_foreground

            def _bring_front():
                try:
                    win.showNormal()
                    win.raise_()
                    win.activateWindow()
                    _force_foreground(win)
                except Exception:
                    pass
            # 首帧之后再抢一次，并在 250ms 后补一次（覆盖引导进程窗口刚消失的时机）
            QTimer.singleShot(0, _bring_front)
            QTimer.singleShot(250, _bring_front)
        except Exception:
            pass

    # 启动后自动连接指定设备
    conn = parse_connect(args.connect)
    if conn:
        host, port = conn
        if not port:
            port = cfg["port"]
        node.connect_manual(host, port)

    app.aboutToQuit.connect(lambda: (node.stop(wait=False)))

    try:
        rc = app.exec()
    finally:
        node.stop()
    sys.exit(rc)


if __name__ == "__main__":
    main()
