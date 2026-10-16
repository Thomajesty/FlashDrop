# -*- coding: utf-8 -*-
"""v1.18.9 六项需求 —— 真实渲染离屏截图（验收对照用）

覆盖：
  A. 设备列表：名称 → 状态灯(绿/灰) → ✕ 删除        -> shots_v1189_devices_{light,dark}.png
  B. 设置页：新增「离线聊天」开关 + 保存聊天开关      -> shots_v1189_settings_{light,dark}.png
  C. 全部设备：纯群聊视图（只含发过消息的 group 项）   -> shots_v1189_group_{light,dark}.png
  D. 截图按钮：单一 ▾ 下箭头（回归，不重复）          -> shots_v1189_snip_{light,dark}.png

运行： <Python312> tests/shots_v1189.py <windows 根>
"""
import os, sys, time, tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.abspath(ROOT)
sys.path.insert(0, ROOT)

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QPainter, QColor, QFont, QPen
from PySide6.QtWidgets import (QApplication, QPushButton, QToolButton,
                               QCheckBox, QLabel)

app = QApplication.instance() or QApplication([])

tmp = tempfile.mkdtemp(prefix="fd_shot1189_")
os.environ["FLASHDROP_DATA_DIR"] = tmp

from app.config import Config
from app.node import FlashNode
from app.ui.main_window import (MainWindow, DeviceItemWidget, ALL_ID,
                                SettingsDialog)

OUT = os.path.dirname(os.path.abspath(__file__))

ANNOT = QColor("#ef4444")
OKC = QColor("#16a34a")
INFO = QColor("#2563eb")

PIDS = ["aaaa1111-2222-3333-4444-555566667777",
        "bbbb1111-2222-3333-4444-555566667777",
        "cccc1111-2222-3333-4444-555566667777"]


def _mark(p, rect, text, color=ANNOT):
    p.setPen(QPen(color, 2))
    p.drawRect(rect.adjusted(0, 0, -1, -1))
    f = QFont("Microsoft YaHei UI")
    f.setPixelSize(11)
    f.setBold(True)
    p.setFont(f)
    p.setPen(color)
    p.drawText(rect.left(), max(rect.top() - 3, 12), text)


def _banner(p, text):
    f = QFont("Microsoft YaHei UI")
    f.setPixelSize(12)
    f.setBold(True)
    p.setFont(f)
    p.setPen(INFO)
    p.drawText(8, 16, text)


def make_win(theme):
    cfg = Config()
    cfg["theme"] = theme
    cfg["save_dir"] = tmp
    win = MainWindow(cfg, FlashNode(cfg))
    win.resize(1180, 760)
    win.show()
    app.processEvents()
    app.processEvents()
    return win


def seed(win):
    """2 在线(1 已连接/1 可达未连接) + 1 离线；前三者都有会话内容"""
    now = int(time.time())
    live = [
        {"id": PIDS[0], "name": "张三的电脑", "platform": "windows",
         "ips": ["192.168.1.23"], "online": True, "connected": True},
        {"id": PIDS[1], "name": "办公室台式机", "platform": "android",
         "ips": ["192.168.1.88"], "online": True, "connected": False},
    ]
    kp = {}
    for p in live:
        kp[p["id"]] = {"id": p["id"], "name": p["name"],
                       "platform": p["platform"], "ips": p["ips"],
                       "last_seen": now}
    kp[PIDS[2]] = {"id": PIDS[2], "name": "家里的笔记本",
                   "platform": "windows", "ips": ["10.0.0.7"],
                   "last_seen": now - 86400}
    win.cfg["known_peers"] = kp
    win.cfg["offline_chat"] = True
    for p in live:
        win.msgs.setdefault(p["id"], [
            {"dir": "in", "text": "在吗？", "ts": now, "channel": "p2p"}])
    win.msgs[PIDS[2]] = [{"dir": "in", "text": "旧消息", "ts": now - 86400,
                          "channel": "group"}]
    win._on_peers(live)
    app.processEvents()


# ============================================================
# A. 设备列表：名称 -> 状态灯 -> ✕
# ============================================================
print("=== A. 设备列表（状态灯 + 删除 X 在名称之后）===")
for theme in ("light", "dark"):
    win = make_win(theme)
    seed(win)
    lst = win.device_list
    pm = lst.viewport().grab()
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    _banner(p, f"v1.18.9-A 设备列表 theme={theme}  行内: 名称 -> 状态灯 -> X")
    n = 0
    for i in range(lst.count()):
        it = lst.item(i)
        w = lst.itemWidget(it)
        if w is None:
            continue
        pid = it.data(Qt.UserRole)
        wr = lst.visualItemRect(it)
        nm, dot = "", "-"
        for lb in w.findChildren(QLabel):
            t = lb.text()
            ss = lb.styleSheet()
            if "border-radius:4px" in ss:
                dot = "GREEN(在线)" if ("#22c55e" in ss or "#16a34a" in ss
                                       or "34,197,94" in ss) else "GRAY(离线)"
            elif t and nm == "" and "font-weight: 600" in ss:
                nm = t
        xb = w.findChild(QToolButton, "PeerDelete")
        label = f"[{n}] {nm} | dot={dot}"
        label += "  [X 可删]" if xb is not None else "  [X 隐藏]"
        _mark(p, QRect(wr.left(), wr.top(), wr.width(), wr.height()), label)
        if xb is not None:
            xr = xb.mapTo(lst.viewport(), xb.rect().topLeft())
            _mark(p, QRect(xr, xb.size()), "X", OKC)
        print(f"  [{theme}] {str(pid)[:8]}  {label}  item_h={wr.height()}")
        n += 1
    p.end()
    out = os.path.join(OUT, f"shots_v1189_devices_{theme}.png")
    pm.save(out, "PNG")
    print(f"  -> {out} ({pm.width()}x{pm.height()})  行数={n}")
    win.close()


# ============================================================
# B. 设置页
# ============================================================
print("=== B. 设置页（离线聊天开关）===")
for theme in ("light", "dark"):
    win = make_win(theme)
    # 直接实例化（_open_settings 内部走 exec() 模态，离屏下会阻塞）
    dlg = SettingsDialog(win.cfg, win)
    dlg.resize(560, 620)
    dlg.show()
    app.processEvents()
    app.processEvents()
    pm = dlg.grab()
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    _banner(p, f"v1.18.9-B 设置页 theme={theme}  离线聊天 / 保存聊天 双开关")
    n = 0
    for cb in dlg.findChildren(QCheckBox):
        tl = cb.mapTo(dlg, cb.rect().topLeft())
        _mark(p, QRect(tl, cb.size()),
              f"{'ON' if cb.isChecked() else 'OFF'} {cb.text()[:24]}")
        print(f"  [{theme}] chk ON={cb.isChecked()}  '{cb.text()[:40]}'")
        n += 1
    p.end()
    out = os.path.join(OUT, f"shots_v1189_settings_{theme}.png")
    pm.save(out, "PNG")
    print(f"  -> {out} ({pm.width()}x{pm.height()})  开关数={n}")
    dlg.close()
    win.close()


# ============================================================
# C. 全部设备 = 纯群聊视图
# ============================================================
print("=== C. 全部设备纯群聊视图 ===")
for theme in ("light", "dark"):
    win = make_win(theme)
    now = int(time.time())
    # group 频道消息挂在「全部设备」这条虚拟会话上
    win.msgs[ALL_ID] = [
        {"dir": "in", "text": "大家好，这里是全部设备（群聊）",
         "ts": now, "channel": "group"},
        {"dir": "out", "text": "收到，我这边没问题",
         "ts": now + 1, "channel": "group", "mid": "g1"},
    ]
    # 一台设备的 p2p 私聊，不应出现在全部设备里
    win.msgs[PIDS[0]] = [
        {"dir": "in", "text": "这条是端到端私聊，不应出现在全部设备",
         "ts": now + 2, "channel": "p2p"}]
    try:
        # 选中「全部设备」
        if win.device_list.count():
            win.device_list.item(0).setSelected(True)
        win._on_target_changed()
        app.processEvents()
        app.processEvents()
        vis = win._visible_msgs()
        pm = win.chat_scroll.viewport().grab()
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        _banner(p, f"v1.18.9-C 全部设备 theme={theme}  "
                   f"可见消息 {len(vis)} 条（p2p 已过滤）")
        p.end()
        out = os.path.join(OUT, f"shots_v1189_group_{theme}.png")
        pm.save(out, "PNG")
        print(f"  -> {out} ({pm.width()}x{pm.height()})  可见={len(vis)}"
              f"  内容={[m.get('text')[:12] for m in vis]}")
    except Exception as e:
        import traceback
        print(f"  [warn] {theme}: {e}")
        traceback.print_exc()
    win.close()


# ============================================================
# D. 截图按钮单一 ▾
# ============================================================
print("=== D. 截图按钮下箭头（不重复）===")
for theme in ("light", "dark"):
    win = make_win(theme)
    panel = win.input_panel
    pm = panel.grab()
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    _banner(p, f"v1.18.9-D 底部工具行 theme={theme}  截图按钮仅 1 个 ▾")
    found = 0
    for b in panel.findChildren(QToolButton):
        txt = b.text()
        if "截图" in txt or "▾" in txt:
            tl = b.mapTo(panel, b.rect().topLeft())
            r = QRect(tl, b.size())
            cnt = txt.count("▾")
            _mark(p, r, f"{txt}  dx{cnt}")
            print(f"  [{theme}] toolbtn '{txt}'  ▾x{cnt}  w={r.width()}")
            found += 1
    for b in panel.findChildren(QPushButton):
        if "▾" in b.text():
            tl = b.mapTo(panel, b.rect().topLeft())
            _mark(p, QRect(tl, b.size()),
                  f"{b.text()}  dx{b.text().count('▾')}")
            print(f"  [{theme}] pushbtn '{b.text()}'  ▾x{b.text().count('▾')}")
            found += 1
    p.end()
    out = os.path.join(OUT, f"shots_v1189_snip_{theme}.png")
    pm.save(out, "PNG")
    print(f"  -> {out} ({pm.width()}x{pm.height()})  含箭头控件={found}")
    win.close()

print("done -> " + OUT)
