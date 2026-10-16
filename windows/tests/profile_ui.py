# -*- coding: utf-8 -*-
"""v1.18.17 —— 界面流畅度性能剖析（优化前的基线测量）。

"verify, don't guess"：先把常见交互路径的耗时量出来，再决定优化什么。

测量项：
  ① make_avatar / make_platform_badge 单次与批量耗时（无缓存？）
  ② _refresh_devices() 随设备数增长的耗时（每次 peers 事件都会调）
  ③ _render_chat() 随消息数增长的耗时（切设备 / 收到消息都会调）
  ④ peers 事件频率（决定 _refresh_devices 被调多频繁）

运行：python tests/profile_ui.py
"""
import os
import sys
import tempfile
import time

os.environ.pop("QT_QPA_PLATFORM", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

tmp = tempfile.mkdtemp(prefix="fd_profile_")
os.environ["FLASHDROP_DATA_DIR"] = tmp

from app.config import Config
from app.node import FlashNode
from app.ui.main_window import MainWindow, ALL_ID
from app.ui.widgets import make_avatar, make_platform_badge


def ms(t0):
    return (time.perf_counter() - t0) * 1000


def pump(n=3):
    for _ in range(n):
        app.processEvents()


print("=" * 70)
print("v1.18.17 界面流畅度剖析（优化前基线）")
print("=" * 70)

# ---------- ① 头像/徽标绘制 ----------
print("\n【① 头像与平台徽标绘制】")
N = 300
t0 = time.perf_counter()
for i in range(N):
    make_avatar("设备%d" % i, "seed%d" % i, 38)
a1 = ms(t0) / N
t0 = time.perf_counter()
for i in range(N):
    make_platform_badge("android" if i % 2 else "windows")
a2 = ms(t0) / N
print("  make_avatar        单次 %.3f ms  → 10 个设备每次重建 %.1f ms"
      % (a1, a1 * 10))
print("  make_platform_badge 单次 %.3f ms → 10 个设备每次重建 %.1f ms"
      % (a2, a2 * 10))
print("  合计：设备列表每次重建要多花 %.1f ms（10 设备）" % ((a1 + a2) * 10))

# ---------- ② _refresh_devices 随设备数增长 ----------
print("\n【② _refresh_devices() 随设备数增长】（每次 peers 事件都调）")
cfg = Config()
cfg["theme"] = "light"
cfg["save_dir"] = tmp
cfg["pending_files"] = []
win = MainWindow(cfg, FlashNode(cfg))
win.resize(1100, 740)
win.show()
pump(8)

import time as _t
for n in (5, 10, 20, 40):
    win.peers = {
        ("%016x" % i): {"id": "%016x" % i, "name": "设备%02d" % i,
                        "online": i % 2 == 0, "platform": "android",
                        "ips": ["192.168.1.%d" % (i % 250 + 2)],
                        "last_seen": _t.time()}
        for i in range(n)
    }
    t0 = time.perf_counter()
    win._refresh_devices()
    pump(2)
    el = ms(t0)
    print("  %2d 个设备 → %6.1f ms   %s"
          % (n, el, "⚠ 卡顿" if el > 100 else ("偏慢" if el > 50 else "OK")))

# ---------- ③ _render_chat 随消息数增长 ----------
print("\n【③ _render_chat() 随消息数增长】（切设备 / 收到消息都会调）")
PID = "%016x" % 0
win.peers = {PID: {"id": PID, "name": "测试机", "online": True,
                   "platform": "windows", "ips": ["192.168.1.9"],
                   "last_seen": _t.time()}}
win._refresh_devices()
pump(2)

for n in (20, 50, 100, 200, 400):
    win.msgs[PID] = [
        {"kind": "text", "dir": "out" if i % 2 else "in",
         "text": "测试消息 %d —— 这是一段用来测性能的中文文本" % i,
         "ts": 1700000000000 + i * 1000, "mid": "m%d" % i}
        for i in range(n)
    ]
    t0 = time.perf_counter()
    win._render_chat()
    pump(2)
    el = ms(t0)
    print("  %3d 条消息 → %6.1f ms   %s"
          % (n, el, "⚠ 明显卡顿" if el > 300 else ("偏慢" if el > 120 else "OK")))

# ---------- ④ 一次"切设备"的真实体感 ----------
print("\n【④ 切设备（选不同目标）端到端】")
win.peers = {}
for i in range(12):
    pid = "%016x" % i
    win.peers[pid] = {"id": pid, "name": "设备%02d" % i, "online": True,
                      "platform": "android", "ips": ["192.168.1.%d" % (i + 2)],
                      "last_seen": _t.time()}
    win.msgs[pid] = [
        {"kind": "text", "dir": "out" if k % 2 else "in",
         "text": "设备%02d 的第 %d 条消息" % (i, k), "ts": k * 1000,
         "mid": "d%dk%d" % (i, k)}
        for k in range(60)
    ]
win._refresh_devices()
pump(2)

t0 = time.perf_counter()
for i in range(12):
    for j in range(win.device_list.count()):
        it = win.device_list.item(j)
        if it.data(0x0100) == list(win.peers)[i]:   # Qt.UserRole
            it.setSelected(True)
            break
    pump(2)
el = ms(t0) / 12
print("  切换一次设备平均 %.1f ms   %s"
      % (el, "⚠ 卡顿" if el > 100 else ("偏慢" if el > 50 else "OK")))

print()
print("=" * 70)
print("结论：见上面各项耗时。阈值参考 —— 单次交互 >50ms 开始能被感知，")
print("      >100ms 明显卡顿，>300ms 会让人以为程序崩了。")
print("=" * 70)

import os as _os
_os._exit(0)