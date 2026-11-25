# -*- coding: utf-8 -*-
"""v1.18.42 泄漏归因：模拟"挂一晚上"的高频事件流，量化内存与各容器增长。

不猜，量出来。逐个场景跑，记录 PagefileUsage（私有内存）与：
  - len(msgs)、in_by_tid/out_by_tid、widgets_by_msg 实际气泡数
  - _chat_pages / _chat_page_order 页数
  - QObject 存活数（shiboken6 可查）
  - ack_waiters / out_states / _send_info / _last_reply（node 层）

运行：python windows/tests/profile_longrun_v11842.py
"""
import ctypes
import ctypes.wintypes as wt
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TMP = tempfile.mkdtemp(prefix="fd_long_")
os.environ["FLASHDROP_DATA_DIR"] = _TMP
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _PMC(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.K32GetProcessMemoryInfo.restype = wt.BOOL
_k32.K32GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(_PMC), wt.DWORD]


def mem():
    pm = _PMC(); pm.cb = ctypes.sizeof(_PMC)
    h = ctypes.windll.kernel32.GetCurrentProcess()
    if not _k32.K32GetProcessMemoryInfo(h, ctypes.byref(pm), pm.cb):
        return 0.0
    return pm.PagefileUsage / 1048576.0


def dump(tag, win, node):
    import gc
    gc.collect()
    from PySide6.QtWidgets import QApplication
    QApplication.processEvents()
    wmap = sum(len(v) for v in win.widgets_by_msg.values())
    print("  %-34s 私有 %8.1f MB | msgs %6d | tid in/out %5d/%5d | 气泡 %6d "
          "| 页 %2d/%2d | ack %5d | outst %5d | last_reply %5d"
          % (tag, mem(),
             sum(len(v) for v in win.msgs.values()),
             len(win.in_by_tid), len(win.out_by_tid), wmap,
             len(win._chat_pages), len(win._chat_page_order),
             len(node.ack_waiters), len(node.out_states),
             len(node._last_reply)), flush=True)


def main():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    app = QApplication(sys.argv)

    from app.config import Config
    from app.node import FlashNode
    from app.ui.main_window import MainWindow

    tmp = tempfile.mkdtemp(prefix="fd_long_cfg_")
    cfg = Config(os.path.join(tmp, "a.json"))
    cfg.data.update({"device_id": "aaaaaaaaaaaaaaaa", "name": "LONG-A",
                     "port": 58971, "save_dir": os.path.join(tmp, "save"),
                     "minimize_to_tray": False, "notify_on_receive": False,
                     "offline_chat": True})
    cfg.save()
    node = FlashNode(cfg)
    win = MainWindow(cfg, node)
    win.resize(1000, 760)
    win.show()
    for _ in range(6):
        app.processEvents()
    dump("S0 启动", win, node)

    pid = "bbbbbbbbbbbbbbbb"
    peers = [{"id": pid, "name": "安卓手机", "platform": "android",
              "ips": [], "online": True, "connected": True}]

    # ---- S1: 高频设备刷新（模拟 UDP 广播/签名变化触发 _on_peers）----
    # 真实 node 侧签名节流后约每几秒一次；这里压到 1000 次看是否有累积。
    for i in range(1000):
        win._on_peers(peers)
        if i % 200 == 199:
            app.processEvents()
            dump("S1 _on_peers x%d" % (i + 1), win, node)

    # ---- S2: 收 500 条文本（带设备刷新穿插）----
    base = int(time.time() * 1000) - 500_000
    for i in range(500):
        win._on_text_in({"peer_id": pid, "peer_name": "安卓手机",
                         "mid": "in-mid-%d" % i,
                         "text": "消息 %d —— 一段用来量内存的中文文本。" % i,
                         "ts": base + i * 1000})
        if i % 100 == 99:
            win._on_peers(peers)
            app.processEvents()
            dump("S2 收消息 %d 条" % (i + 1), win, node)

    # ---- S3: 发 500 条文本（每条新 mid，模拟 ack 丢失）----
    for i in range(500):
        win._out_text_msg([pid], "out-mid-%d" % i, "发出消息 %d" % i)
        if i % 100 == 99:
            app.processEvents()
            dump("S3 发消息 %d 条" % (i + 1), win, node)

    # ---- S4: 500 个文件传输事件（不同 tid，走 done 终态）----
    for i in range(500):
        tid = "file-tid-%d" % i
        win._on_transfer({"kind": "recv", "tid": tid, "peer_id": pid,
                          "name": "安卓手机", "file": "f%d.jpg" % i,
                          "size": 1000 + i, "mime": "image/jpeg",
                          "state": "done", "transferred": 1000 + i,
                          "path": os.path.join(tmp, "f%d.jpg" % i)})
        if i % 100 == 99:
            win._on_peers(peers)
            app.processEvents()
            dump("S4 文件事件 %d 个" % (i + 1), win, node)

    # ---- S5: 2000 次 progress 刷新（同一 tid）----
    for i in range(2000):
        win._on_transfer({"kind": "recv", "tid": "file-tid-499", "peer_id": pid,
                          "name": "安卓手机", "file": "f499.jpg",
                          "size": 1499, "mime": "image/jpeg",
                          "state": "progress", "transferred": 100 + i % 1400,
                          "speed": 1024})
    dump("S5 progress x2000", win, node)

    # ---- S6: 反复切页（长会话 ↔ 空会话）----
    pid2 = "cccccccccccccccc"
    peers2 = peers + [{"id": pid2, "name": "新手机", "platform": "android",
                       "ips": [], "online": True, "connected": True}]
    win._on_peers(peers2)
    for i in range(200):
        win._select_peer_by_id(pid if i % 2 else pid2)
        win._render_chat()
    app.processEvents()
    dump("S6 切页 x200", win, node)

    # ---- S7: 最小化/恢复（trim）----
    from PySide6.QtCore import QEvent
    for i in range(50):
        win.changeEvent(QEvent(QEvent.WindowStateChange))
    dump("S7 trim x50", win, node)

    print("\nDONE", flush=True)


if __name__ == "__main__":
    main()
