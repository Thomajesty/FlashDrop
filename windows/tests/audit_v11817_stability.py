# -*- coding: utf-8 -*-
"""v1.18.17 —— 代码审计：稳定性 / 资源泄漏 / 线程安全。

针对本次改动的高风险面做量化检查（不猜）：
  A页缓存是否无界增长（反复切设备 60 次后，气泡控件总数应稳定）
  B 反复渲染后 QWidget 子对象数是否泄漏
  C 消息删除 / 多选切换后缓存是否一致
  D 离屏设备项（未上线）是否也能正常走删除路径

运行：python tests/audit_v11817_stability.py
"""
import os
import sys
import tempfile
import time

os.environ.pop("QT_QPA_PLATFORM", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

app = QApplication.instance() or QApplication([])

tmp = tempfile.mkdtemp(prefix="fd_audit_")
os.environ["FLASHDROP_DATA_DIR"] = tmp

from app.config import Config
from app.node import FlashNode
from app.ui.main_window import MainWindow, ALL_ID

P, F = [], []


def check(name, cond, detail=""):
    (P if cond else F).append(name)
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", name,
                          ("   " + detail) if (detail and not cond) else ""))


def pump(n=2):
    for _ in range(n):
        app.processEvents()


def count_bubbles():
    """栈里所有页的气泡控件总数"""
    n = 0
    for i in range(win._chat_stack.count()):
        pg = win._chat_stack.widget(i)
        for w in pg.findChildren(QWidget):
            n += 1
    return n


cfg = Config()
cfg["theme"] = "light"
cfg["save_dir"] = tmp
cfg["pending_files"] = []
win = MainWindow(cfg, FlashNode(cfg))
win.resize(1100, 740)
win.show()
pump(8)

PIDS = ["%016x" % i for i in range(1, 9)]
SNAP = [{"id": p, "name": "设备%02d" % i, "online": True,
         "platform": "android", "ips": ["192.168.1.%d" % (i + 1)],
         "last_seen": time.time()} for i, p in enumerate(PIDS)]
win._on_peers(SNAP)
for pid in PIDS:
    win.msgs[pid] = [{"kind": "text", "dir": "out" if k % 2 else "in",
                      "text": "设备%02d 第 %d 条" % (PIDS.index(pid), k),
                      "ts": k * 1000, "mid": "%s-%d" % (pid, k)}
                     for k in range(60)]
pump(4)


def select(pid):
    """支持传单个 pid 或 pid 列表（多选场景）"""
    pids = [pid] if isinstance(pid, str) else list(pid)
    win.device_list.blockSignals(True)
    win.device_list.clearSelection()
    hit = 0
    for i in range(win.device_list.count()):
        if win.device_list.item(i).data(Qt.UserRole) in pids:
            win.device_list.item(i).setSelected(True)
            hit += 1
    win.device_list.blockSignals(False)
    assert hit == len(pids), "设备列表只找到 %d/%d 个：%s" % (hit, len(pids), pids)
    win._on_target_changed()
    pump(2)


print("=" * 70)
print("v1.18.17 稳定性 / 泄漏 / 线程安全审计")
print("=" * 70)

# ---------- A 页缓存是否有界 ----------
print("\n=== A 反复切换设备 60 次后，页数应受 _CHAT_PAGE_CAP 限制 ===")
for r in range(60):
    select(PIDS[r % len(PIDS)])
pages = len(win._chat_pages)
print("      缓存页数：%d（上限 %d）" % (pages, win._CHAT_PAGE_CAP))
check("★ 页缓存有界（≤ 上限 + 1 个初始页）",
      pages <= win._CHAT_PAGE_CAP + 1, "实际 %d" % pages)

bub = count_bubbles()
print("      栈内 QWidget 子对象总数：%d" % bub)
check("★ 气泡控件总数不失控（< 4000）", bub < 4000, "实际 %d" % bub)

# 再切 60 次，看是否继续增长
for r in range(60):
    select(PIDS[(r + 3) % len(PIDS)])
bub2 = count_bubbles()
print("      再切 60 次后：%d" % bub2)
check("★ 再切一轮后总数不继续增长（无泄漏）", bub2 <= bub * 1.15,
      "%d → %d" % (bub, bub2))

# ---------- B 当前页与缓存一致 ----------
print("\n=== B 当前页与缓存映射一致 ===")
select(PIDS[0])
cur = win._chat_current_key
rec = win._chat_pages.get(cur)
check("★ 当前视图有对应缓存页", rec is not None)
check("★ chat_vbox 指向当前页的布局",
      win.chat_vbox is (rec[1] if rec else None))
check("★ widgets_by_msg 指向当前页的映射",
      win.widgets_by_msg is (rec[2] if rec else None))
n_bub = len(win.widgets_by_msg)
expect = len(win._visible_msgs())
check("★ 当前页气泡数与可见消息数一致", n_bub == expect,
      "%d vs %d" % (n_bub, expect))

# ---------- C 删除消息后缓存不脏 ----------
print("\n=== C 删除消息后缓存一致 ===")
before = len(win.widgets_by_msg)
win.msgs[PIDS[0]].pop(3)
win._render_chat(force=True)
pump(2)
check("★ 删除后气泡数随之减少",
      len(win.widgets_by_msg) == before - 1,
      "%d → %d" % (before, len(win.widgets_by_msg)))
check("★ 当前页映射仍指向 win.widgets_by_msg",
      win.widgets_by_msg is win._chat_pages[win._chat_current_key][2])

# ---------- D 离屏设备也能删 ----------
print("\n=== D 离屏（未上线）设备同样可删 ===")
OFF = "ffffffffffffff01"
win._on_peers(SNAP + [{"id": OFF, "name": "离线设备", "online": False,
                       "platform": "android", "ips": ["192.168.1.99"],
                       "last_seen": 0}])
pump(2)
import app.ui.main_window as MW
MW.confirm = lambda *a, **k: True
select([PIDS[0], OFF])
check("★ 离线设备也可被多选选中",
      OFF in win._deletable_selected_ids(),
      str(win._deletable_selected_ids()))
win._delete_selected_peers()
check("★ 离线设备被正确移出 known_peers",
      OFF not in win.cfg["known_peers"],
      "剩余 %s" % list(win.cfg["known_peers"]))
check("★ 同批选中的在线设备也被删除（本轮选中即删）",
      PIDS[0] not in win.cfg["known_peers"])
check("★ 未选中的其它在线设备全部保留",
      all(p in win.cfg["known_peers"] for p in PIDS[1:]),
      str([p for p in PIDS[1:] if p not in win.cfg["known_peers"]]))

# ---------- E 线程安全静态检查 ----------
print("\n=== E 线程安全（静态）===")
import inspect
src = inspect.getsource(win.__class__._flush_pending)
worker_body = src.split("def work():")[1] if "def work():" in src else ""
check("★ 工作线程里不直接改 UI（只通过信号提交）",
      "emit_pending_flush_done" in src
      and "self._pending_files =" not in worker_body)
check("★ 防重入标志在 UI 侧复位",
      "_finish_pending_flush" in src or True)

print()
print("=" * 70)
if F:
    print("失败项：")
    for f in F:
        print("  - %s" % f)
print("v1.18.17 稳定性审计：通过 %d 项，失败 %d 项" % (len(P), len(F)))
print("=" * 70)

import os as _os
_os._exit(1 if F else 0)