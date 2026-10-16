# -*- coding: utf-8 -*-
"""FlashDrop Windows 入口"""

import argparse
import os
import socket
import sys
import time

# 保证 PyInstaller --onefile 模式下能找到 app 包
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 单实例锁端口：绑定成功表示首个实例；占用则唤起已有实例后退出
LOCK_PORT = 58898


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


def _lock_is_alive(timeout=1.5):
    """向锁端口发 PING，若收到 PONG 说明**真有实例活着**。

    ★ 为什么需要它（v1.18.9）：
    原实现只要 `bind()` 失败就认定「已有实例」，直接退出。
    但 Windows 上 UDP 端口可能被**僵死的残留进程**或
    **其他程序**占用 —— 此时发 SHOW 无人应答，用户双击 EXE
    就得到「什么都不发生」= 打不开。
    改为：先 PING 探活，无应答则**抢占**（视为孤儿锁）。
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.settimeout(timeout)
        s.sendto(b"FlashDrop_PING", ("127.0.0.1", LOCK_PORT))
        data, _ = s.recvfrom(64)
        return b"PONG" in data
    except Exception:
        return False
    finally:
        s.close()


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
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
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
        return first

    # 端口被占：先确认对方是否真的活着
    if _lock_is_alive():
        if not allow_multi:
            _notify_instance_show()
            return None                      # 正常单实例：交给已有实例
        # 多开模式：已有实例活着 → 本实例不拿锁，但继续运行
        return None

    # 无人应答 = 孤儿锁（残留进程/他人占用）→ 抢占，保证用户能打开
    reclaimed = _try_bind(reuse=True)
    if reclaimed is not None:
        return reclaimed
    # 实在抢不到（被别的程序硬占）→ 不阻断启动，只是失去单实例保护
    return _try_bind() or socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def main():
    from app.config import Config
    from app.node import FlashNode
    from app.ui.main_window import MainWindow
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt

    args = parse_args(sys.argv[1:])

    ipc_sock = single_instance_lock()
    if ipc_sock is None:
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
