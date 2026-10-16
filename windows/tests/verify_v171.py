# -*- coding: utf-8 -*-
"""v1.7.1 修复回归验证：
1) 勾选离线设备发文件 → 显示"待发送"消息（原来走直接发送 → 失败·设备不在线）
2) 在线/离线混合勾选 → 在线立即发 + 离线入队
3) 单设备视图下待发送气泡可见
4) 待发目标正确记录（上线后发给原目标，而非任意设备）
5) 删除待发送消息后队列同步清理
6) 加密复选框在深/浅主题下均有足够对比度
"""
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["FLASHDROP_DATA_DIR"] = tempfile.mkdtemp(prefix="fd_v171_")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtWidgets import QApplication, QCheckBox, QWidget, QVBoxLayout

app = QApplication([])
from app.ui import main_window as mw
from app.ui import theme as th
from app.config import Config

ALL = mw.ALL_ID
OFF1, OFF2, ON1 = "offline-1", "offline-2", "online-1"
PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{('  ' + extra) if extra else ''}")


class FakeList:
    def __init__(self, ids):
        self._ids = ids

    def selectedItems(self):
        class It:
            def __init__(self, i):
                self._i = i

            def data(self, role):
                return self._i

        return [It(i) for i in self._ids]


def make_win():
    w = mw.MainWindow.__new__(mw.MainWindow)
    w.msgs = {}
    w.peers = {
        OFF1: {"id": OFF1, "name": "离线甲", "online": False},
        OFF2: {"id": OFF2, "name": "离线乙", "online": False},
        ON1: {"id": ON1, "name": "在线丙", "online": True},
    }
    w.unread = {}
    w._rebuilding = False
    w._stick_bottom = True
    w.in_by_tid = {}
    w.out_by_tid = {}
    w.widgets_by_msg = {}
    w._pending_files = []
    w.cfg = Config()
    w.cfg["name"] = "tester"
    w.cfg["device_id"] = "me"
    w._toast = lambda s: None
    w.bridge = type("B", (), {
        "send_files": staticmethod(lambda t, p: w.sent.append((list(t), list(p))))})()
    w.sent = []
    w._render_chat = lambda: None
    return w


def mkfile(d, n):
    p = os.path.join(d, n)
    with open(p, "w") as f:
        f.write("x")
    return p


d = tempfile.mkdtemp(prefix="fd_files_")

print("== 1. 勾选【离线】设备发文件 → 入队并显示待发送 ==")
w = make_win()
w.device_list = FakeList([OFF1])
f1 = mkfile(d, "a.txt")
w._do_send_files(w._targets(), [f1], intent=w._selected_ids_all())
check("离线目标不触发直接发送", len(w.sent) == 0, f"sent={len(w.sent)}")
check("离线目标进入待发队列", len(w._pending_files) == 1)
check("待发送消息已上屏", len(w.msgs.get(w.PENDING_PEER, [])) == 1)
if w.msgs.get(w.PENDING_PEER):
    pm = w.msgs[w.PENDING_PEER][0]
    check("占位消息 state=pending", pm.get("state") == "pending")
    check("占位消息显示文件名", pm.get("file") == "a.txt", f"file={pm.get('file')}")
    check("占位消息记录原目标", pm.get("targets") == [OFF1], f"targets={pm.get('targets')}")

print("\n== 2. 勾选【在线+离线】各一台 → 在线立即发 + 离线入队 ==")
w = make_win()
w.device_list = FakeList([ON1, OFF1])
f2 = mkfile(d, "b.txt")
tg = w._targets()
w._do_send_files(tg, [f2], intent=w._selected_ids_all())
check("在线目标立即发送", len(w.sent) == 1 and w.sent[0][0] == [ON1], f"sent={w.sent}")
check("离线目标同时入队", len(w._pending_files) == 1)
check("入队记录的是离线目标", w._pending_files[0]["targets"] == [OFF1],
      f"targets={w._pending_files[0]['targets']}")

print("\n== 3. 单设备视图下待发送气泡可见 ==")
w = make_win()
w.device_list = FakeList([ON1])
check("单设备视图包含 PENDING_PEER", w.PENDING_PEER in w._view_peer_ids(),
      f"view={w._view_peer_ids()}")

print("\n== 4. 上线后定向补发给原目标 ==")
w = make_win()
w.device_list = FakeList([OFF1])
f3 = mkfile(d, "c.txt")
w._do_send_files(w._targets(), [f3], intent=w._selected_ids_all())
check("入队 1 条", len(w._pending_files) == 1)
# 别的设备上线，不应触发
w.peers[ON1]["online"] = True
w._flush_pending()
check("非目标设备上线不误发", len(w.sent) == 0, f"sent={len(w.sent)}")
# 目标设备上线
w.peers[OFF1]["online"] = True
w._flush_pending()
check("目标上线后自动补发", len(w.sent) == 1 and w.sent[0][0] == [OFF1], f"sent={w.sent}")
check("队列已清空", len(w._pending_files) == 0)
check("待发送气泡已移除", len(w.msgs.get(w.PENDING_PEER, [])) == 0)

print("\n== 5. 删除待发送消息 → 队列同步清理 ==")
w = make_win()
w.device_list = FakeList([OFF1])
f4 = mkfile(d, "d.txt")
w._do_send_files(w._targets(), [f4], intent=w._selected_ids_all())
pm = w.msgs[w.PENDING_PEER][0]
ident = {w._msg_identity(pm)}
w._remove_msgs(ident)
check("待发队列已同步清理", len(w._pending_files) == 0,
      f"pending={len(w._pending_files)}")

print("\n== 6. 加密复选框对比度（深/浅主题） ==")


def lum(h):
    h = h.lstrip("#")
    r, g, b = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def cr(a, b):
    l1, l2 = lum(a), lum(b)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


for mode, pal in (("dark", th.DARK), ("light", th.LIGHT)):
    qss = th.build_qss(pal)
    seg = qss.split("QCheckBox::indicator {")[1].split("}")[0]
    border = seg.split("border: 1px solid")[1].split(";")[0].strip()
    # 可见性由边框承载（填充与页面底色同族是正常设计），故边框对比度必须够高
    check(f"{mode}: 复选框边框对比度 ≥ 3:1（保证方框可见）",
          cr(pal["window"], border) >= 3.0, f"{cr(pal['window'], border):.2f}:1 ({border})")
    # 真实渲染验证：未选中态方框必须渲染出高对比度边框环（可见）
    win = QWidget()
    win.setStyleSheet(qss)
    lay = QVBoxLayout(win)
    cb = QCheckBox("传输加密（TLS）")
    cb.setChecked(False)
    lay.addWidget(cb)
    win.resize(420, 120)
    win.show()
    app.processEvents()
    img = win.grab().toImage()
    # 在复选框左侧 40x40 内统计"与页面底色对比度 ≥ 3:1"的像素（= 边框环）
    tl = cb.mapTo(win, cb.rect().topLeft())
    strong = 0
    for y in range(max(0, tl.y() - 4), tl.y() + 32):
        for x in range(max(0, tl.x() - 4), tl.x() + 32):
            c = img.pixelColor(x, y).name()
            if cr(pal["window"], c) >= 3.0:
                strong += 1
    check(f"{mode}: 渲染后未选中方框边框可见（高对比像素 ≥ 20）", strong >= 20,
          f"高对比像素={strong}")
    win.close()

print(f"\n===== 结果: {len(PASS)} 通过, {len(FAIL)} 失败 =====")
if FAIL:
    print("失败项: " + "; ".join(FAIL))
sys.exit(1 if FAIL else 0)
