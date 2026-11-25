# -*- coding: utf-8 -*-
"""v1.18.42 验收：内存泄漏根治（挂一晚上 8.8GB）

A 组 静态：所有泄漏修复点在位
B 组 运行时：长时压力（设备刷新/收发消息/文件/progress/切页/trim）
   —— 内存必须收敛（不得持续上涨），Qt 对象存活数必须有上限

运行：python windows/tests/verify_v11842_memory_leaks.py
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
ROOT = os.path.dirname(WIN)
for p in (WIN,):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["FLASHDROP_DATA_DIR"] = tempfile.mkdtemp(prefix="fd_v11842_")

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
    node = rd("app/node.py")
    ck("A1 _dispose_item_widgets 用 shiboken6.delete",
       "def _dispose_item_widgets" in mw
       and "shiboken6.delete(w)" in mw
       and "_dispose_item_widgets(self.device_list)" in mw)
    ck("A2 dispose_widget 通用即时析构",
       "def dispose_widget" in wd and "shiboken6.delete(w)" in wd
       and "self._safe_dispose(it.widget())" in wd)
    ck("A3 气泡页硬上限 + 裁剪接线",
       "_BUBBLE_PAGE_CAP" in mw and "def _trim_bubbles" in mw
       and "self._trim_bubbles(rec[1], rec[2], rec[3])" in mw)
    ck("A4 msgs/tid 容器上限",
       "_MSG_LIST_CAP" in mw and "_TID_INDEX_CAP" in mw
       and "self._trim_msg_containers" in mw)
    ck("A5 页淘汰用即时析构",
       "dispose_widget(rec[0])" in mw)
    ck("A6 ack_waiters 超时清理",
       "self.ack_waiters.pop((pid, mid), None)" in node)
    ck("A7 _send_files_task finally 清理状态",
       "self.out_states.pop(tid, None)" in node
       and "self._send_info.pop(tid, None)" in node)
    ck("A8 _last_reply 过期淘汰 + ID 长度校验",
       "len(pid) > 64" in node
       and "self._last_reply.pop(k, None)" in node)
    ck("A9 Viewer 延迟即时析构",
       "QTimer.singleShot(0, lambda vv=vv: dispose_widget(vv))" in mw)
    # 版本（演进式）
    ver = re.search(r'__version__ = "(1\.18\.\d+)"', rd("app/__init__.py"))
    ck("A10 版本 >= 1.18.42", bool(ver) and
       tuple(int(x) for x in ver.group(1).split(".")) >= (1, 18, 42),
       ver and ver.group(1))


def group_b():
    import time
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt, QEvent, QTimer, QEventLoop
    import shiboken6
    from app.config import Config
    from app.node import FlashNode
    from app.ui.main_window import MainWindow

    def wait_ms(ms):
        loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()

    def settle():
        gc.collect()
        for _ in range(3):
            app.processEvents()
        gc.collect()

    def nvalid(class_name):
        n = 0
        for o in gc.get_objects():
            try:
                if shiboken6.isValid(o) and o.metaObject().className() == class_name:
                    n += 1
            except Exception:
                pass
        return n

    app = QApplication.instance() or QApplication(sys.argv)
    tmp = tempfile.mkdtemp(prefix="fd_v11842_cfg_")
    cfg = Config(os.path.join(tmp, "a.json"))
    cfg.data.update({"device_id": "aaaaaaaaaaaaaaaa", "name": "MEM-A",
                     "port": 59071, "save_dir": os.path.join(tmp, "save"),
                     "minimize_to_tray": False, "notify_on_receive": False,
                     "offline_chat": True})
    cfg.save()
    node = FlashNode(cfg)
    win = MainWindow(cfg, node)
    win.resize(1000, 760); win.show()
    for _ in range(6):
        app.processEvents()
    settle()
    base = mem_mb()
    ck("B0 基线内存合理（<120MB）", base < 120, f"{base:.1f}MB")

    pid = "bbbbbbbbbbbbbbbb"
    peers = [{"id": pid, "name": "安卓手机", "platform": "android",
              "ips": [], "online": True, "connected": True}]

    # B1：设备刷新 1000 次 —— 曾泄漏 203MB + 2000 widget
    for i in range(1000):
        win._on_peers(peers)
        if i % 20 == 0:
            app.processEvents()
    settle()
    after_peers = mem_mb()
    dev_widgets = nvalid("DeviceItemWidget")
    ck("B1 设备刷新 x1000 内存增量 < 15MB",
       after_peers - base < 15, f"+{after_peers - base:.1f}MB")
    ck("B1 设备 widget 不累积（<=4）", dev_widgets <= 4, str(dev_widgets))

    # B2：收 500 条文本
    now = int(time.time() * 1000)
    for i in range(500):
        win._on_text_in({"peer_id": pid, "peer_name": "安卓手机",
                         "mid": "in-mid-%d" % i,
                         "text": "消息 %d —— 一段中文测试文本。" % i,
                         "ts": now - 500_000 + i * 1000})
    settle()
    after_text = mem_mb()
    ck("B2 收 500 条文本后内存 < 110MB", after_text < 110,
       f"{after_text:.1f}MB")

    # B3：发 500 条文本 —— 曾累积 500 气泡
    for i in range(500):
        win._out_text_msg([pid], "out-mid-%d" % i, "发出消息 %d" % i)
    settle()
    bubbles = nvalid("BubbleFrame")
    ck("B3 发 500 条后气泡数 <= 240", bubbles <= 240, str(bubbles))
    after_send = mem_mb()
    ck("B3 发消息内存增量 < 90MB", after_send - after_text < 90,
       f"+{after_send - after_text:.1f}MB")

    # B4：500 个文件传输 —— 曾 +300MB
    for i in range(500):
        win._on_transfer({"kind": "recv", "tid": "file-tid-%d" % i,
                          "peer_id": pid, "name": "安卓手机",
                          "file": "f%d.jpg" % i, "size": 1000 + i,
                          "mime": "image/jpeg", "state": "done",
                          "transferred": 1000 + i,
                          "path": os.path.join(tmp, "f%d.jpg" % i)})
        if i % 50 == 49:
            win._on_peers(peers)
    settle()
    after_files = mem_mb()
    ck("B4 文件事件 x500 内存增量 < 100MB", after_files - after_send < 100,
       f"+{after_files - after_send:.1f}MB")
    ck("B4 in_by_tid 有上限（<=256）",
       len(win.in_by_tid) <= 256, str(len(win.in_by_tid)))
    ck("B4 msgs 有上限（<=1000/设备）",
       all(len(v) <= 1000 for v in win.msgs.values()))

    # B5：progress x2000 —— 曾残留 2017 个 QPushButton
    btn_before = nvalid("QPushButton")
    for i in range(2000):
        win._on_transfer({"kind": "recv", "tid": "file-tid-499",
                          "peer_id": pid, "name": "安卓手机",
                          "file": "f499.jpg", "size": 1499,
                          "mime": "image/jpeg", "state": "progress",
                          "transferred": 100 + i % 1400, "speed": 1024})
    settle()
    btn_after = nvalid("QPushButton")
    after_progress = mem_mb()
    ck("B5 progress x2000 按钮不累积（增量 <= 2）",
       btn_after - btn_before <= 2, f"{btn_before}->{btn_after}")
    ck("B5 progress x2000 内存增量 < 10MB",
       after_progress - after_files < 10,
       f"+{after_progress - after_files:.1f}MB")

    # B6：切页 x200 —— 曾 +48MB 且旧页气泡不析构
    pid2 = "cccccccccccccccc"
    win._on_peers(peers + [{"id": pid2, "name": "新手机", "platform": "android",
                            "ips": [], "online": True, "connected": True}])
    for i in range(200):
        win._select_peer_by_id(pid if i % 2 else pid2)
        win._render_chat()
    settle()
    after_switch = mem_mb()
    ck("B6 切页 x200 内存不增（<= +10MB）",
       after_switch - after_progress < 10,
       f"+{after_switch - after_progress:.1f}MB")
    ck("B6 气泡存活数 <= 500（3 页上限）",
       nvalid("BubbleFrame") <= 500, str(nvalid("BubbleFrame")))

    # B7：长期驻留总量必须远小于 8.8GB
    ck("B7 全程结束后内存 < 400MB", mem_mb() < 400, f"{mem_mb():.1f}MB")

    # B8：trim 幂等
    for i in range(50):
        win.changeEvent(QEvent(QEvent.WindowStateChange))
    settle()
    ck("B8 trim x50 内存稳定", mem_mb() < 400, f"{mem_mb():.1f}MB")


def main():
    print("=" * 66)
    print("v1.18.42 内存泄漏根治验收（8.8GB / 挂一晚上）")
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
