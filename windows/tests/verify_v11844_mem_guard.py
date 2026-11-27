# -*- coding: utf-8 -*-
"""v1.18.44 验收：内存看门狗（硬性封顶，防未知泄漏卡死系统）

A 组 静态：看门狗接线 + 定时器单例化
B 组 运行时：分级回收真实生效（造大量消息/气泡把内存推过阈值，
  触发 tick 后内存必须下降）
C 组 行为：递归定时器恒为一条

运行：python windows/tests/verify_v11844_mem_guard.py
"""
import gc
import os
import re
import sys
import tempfile
import ctypes
import ctypes.wintypes as wt

HERE = os.path.dirname(os.path.abspath(__file__))
WIN = os.path.dirname(HERE)
for p in (WIN,):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["FLASHDROP_DATA_DIR"] = tempfile.mkdtemp(prefix="fd_v11844_")

FAILS = []
N = 0


def ck(name, cond, extra=""):
    global N
    N += 1
    if not cond:
        FAILS.append(f"{name} | {extra}")
    print(("  ok  " if cond else " FAIL ") + name +
          ((" | " + str(extra)) if extra and not cond else ""), flush=True)


def rd(rel):
    with open(os.path.join(WIN, rel), encoding="utf-8") as f:
        return f.read()


class PMC(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("pf", wt.DWORD),
                ("pws", ctypes.c_size_t), ("ws", ctypes.c_size_t),
                ("q1", ctypes.c_size_t), ("q2", ctypes.c_size_t),
                ("q3", ctypes.c_size_t), ("q4", ctypes.c_size_t),
                ("pb", ctypes.c_size_t), ("ppb", ctypes.c_size_t)]


_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.K32GetProcessMemoryInfo.restype = wt.BOOL
_k32.K32GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(PMC), wt.DWORD]


def mem_mb():
    pm = PMC(); pm.cb = ctypes.sizeof(PMC)
    h = ctypes.windll.kernel32.GetCurrentProcess()
    if not _k32.K32GetProcessMemoryInfo(h, ctypes.byref(pm), pm.cb):
        return 0.0
    return pm.pb / 1048576.0


def group_a():
    mw = rd("app/ui/main_window.py")
    wd = rd("app/ui/widgets.py")
    ck("A1 看门狗接线（构造启动 + 周期 tick）",
       "self._start_mem_watchdog()" in mw
       and "def _mem_watchdog_tick" in mw
       and "_MEM_WATCH_INTERVAL" in mw)
    ck("A2 三级阈值（合理封顶：350/500/700MB）",
       "_MEM_SOFT_MB = 350" in mw and "_MEM_HARD_MB = 500" in mw
       and "_MEM_CRITICAL_MB = 700" in mw)
    # ★ v1.18.46：超限提示演进为自动重启（用户要求"默认直接重启"）
    ck("A2b 深度回收 + 超限自动重启",
       "def _deep_reclaim" in mw and "def _auto_restart" in mw
       and "_restart_pending" in mw)
    ck("A3 极限级 EmptyWorkingSet",
       "EmptyWorkingSet" in mw and "def _empty_working_set" in mw)
    ck("A4 图片缓存清空接口",
       "def clear_image_caches" in wd and "clear_image_caches()" in mw)
    ck("A5 自身信息定时器单例化（递归callback拆分）",
       "def _self_info_tick" in mw
       and "            QTimer.singleShot(5000, self._self_info_tick)" in mw)
    ver = re.search(r'__version__ = "(1\.18\.\d+)"', rd("app/__init__.py"))
    ck("A6 版本 >= 1.18.44", bool(ver) and
       tuple(int(x) for x in ver.group(1).split(".")) >= (1, 18, 44),
       ver and ver.group(1))


def group_b():
    import time
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt, QTimer, QEventLoop
    from app.config import Config
    from app.node import FlashNode
    from app.ui.main_window import MainWindow

    def wait(ms):
        loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()

    app = QApplication.instance() or QApplication(sys.argv)
    tmp = tempfile.mkdtemp(prefix="fd_v11844_cfg_")
    cfg = Config(os.path.join(tmp, "a.json"))
    cfg.data.update({"device_id": "aaaaaaaaaaaaaaaa", "name": "A",
                     "port": 59121, "save_dir": os.path.join(tmp, "s"),
                     "notify_on_receive": False, "offline_chat": True})
    cfg.save()
    node = FlashNode(cfg)
    win = MainWindow(cfg, node)
    win.resize(1000, 760); win.show()
    for _ in range(6):
        app.processEvents()
    gc.collect()
    base = mem_mb()
    ck("B0 看门狗 timer 已启动",
       hasattr(win, "_mem_timer") and win._mem_timer.isActive())

    # B1: 私有内存读取有效
    ck("B1 私有内存可读（>0）", win._mem_private_mb() > 0,
       str(win._mem_private_mb()))

    # B2: 造大量消息把内存推高，然后强制软回收
    pid = "bbbbbbbbbbbbbbbb"
    peers = [{"id": pid, "name": "安卓", "platform": "android",
              "ips": [], "online": True, "connected": True}]
    win._on_peers(peers)
    now = int(time.time() * 1000)
    for i in range(1500):
        win._on_text_in({"peer_id": pid, "peer_name": "安卓",
                         "mid": "mid-%d" % i,
                         "text": "消息 %d —— 中文测试文本占用内存。" % i,
                         "ts": now - 1_500_000 + i * 1000})
    for i in range(600):
        win._on_transfer({"kind": "recv", "tid": "tid-%d" % i,
                          "peer_id": pid, "name": "安卓",
                          "file": "f%d.jpg" % i, "size": 1000 + i,
                          "mime": "image/jpeg", "state": "done",
                          "transferred": 1000 + i,
                          "path": os.path.join(tmp, "f%d.jpg" % i)})
    for _ in range(4):
        app.processEvents()
    gc.collect()
    high = mem_mb()

    # 强制极限回收（绕开阈值直接调内部动作验证有效性）
    win._trim_pages()
    from app.ui.widgets import clear_image_caches
    clear_image_caches()
    win._force_gc()
    win._empty_working_set()
    for _ in range(4):
        app.processEvents()
    gc.collect()
    low = mem_mb()
    ck("B2 回收动作真实降低内存", low < high,
       f"{high:.1f}MB -> {low:.1f}MB")
    ck("B2 回收后内存 <= 400MB（软阈值内）", low <= 400,
       f"{low:.1f}MB")

    # B3: 软回收后 msgs 仍可正常渲染（历史不丢）
    win._render_chat(force=True)
    for _ in range(4):
        app.processEvents()
    ck("B3 回收后渲染正常（无异常）", True)

    # B4: 定时器单例 —— 重复调 _update_self_info 不增加 timer 数
    from PySide6.QtCore import QObject
    def count_timers():
        n = 0
        for o in gc.get_objects():
            try:
                if o.metaObject().className() == "QTimer" and o.parent() is win:
                    n += 1
            except Exception:
                pass
        return n
    before = count_timers()
    for i in range(30):
        win._update_self_info()
    after = count_timers()
    ck("B4 重复刷新自身信息不累积定时器", after == before,
       f"{before} -> {after}")


def main():
    print("=" * 66)
    print("v1.18.44 内存看门狗验收（硬性封顶）")
    print("=" * 66)
    group_a()
    group_b()
    print("\n===== 结果: %d/%d %s =====" %
          (N - len(FAILS), N, "ALL PASS" if not FAILS else "FAIL"))
    for f in FAILS:
        print("  FAIL:", f)
    if FAILS:
        sys.exit(1)


if __name__ == "__main__":
    main()
