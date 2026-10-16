# -*- coding: utf-8 -*-
"""v1.18.9 需求 #5/#6 行为验证：「全部设备」纯群聊视图 + 频道标记

覆盖（全部真实驱动 MainWindow，非静态断言）：
  G1 群发（全部设备）发出的消息带 channel="group"
  G2 定向（单台设备）发出的消息带 channel="p2p"
  G3 全部设备视图下：只显示 group，p2p 被过滤
  G4 全部设备视图下：无 channel 的老数据仍然可见（向后兼容）
  G5 单设备视图下：该设备的 p2p 消息可见
  G6 单设备视图下：该设备的 group 消息可见（自己参与过的群聊）
  G7 待发送（PENDING_PEER）在全部设备视图下始终可见
  G8 _channel_for 语义正确
"""
import os, sys, time, tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.abspath(ROOT)
sys.path.insert(0, ROOT)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])
tmp = tempfile.mkdtemp(prefix="fd_v1189grp_")
os.environ["FLASHDROP_DATA_DIR"] = tmp

from app.config import Config
from app.node import FlashNode
from app.ui.main_window import MainWindow, ALL_ID

PASS = FAIL = 0
FAILS = []


def ck(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK] {name}")
    else:
        FAIL += 1
        FAILS.append(f"{name} {detail}")
        print(f"  [FAIL] {name} {detail}")


PA = "aaaa1111-2222-3333-4444-555566667777"
PB = "bbbb1111-2222-3333-4444-555566667777"

cfg = Config()
cfg["theme"] = "light"
cfg["save_dir"] = tmp
cfg["offline_chat"] = True
win = MainWindow(cfg, FlashNode(cfg))
win.resize(1180, 760)
win.show()
app.processEvents()
app.processEvents()

# 注入两台在线设备
now = int(time.time() * 1000)
peers = [{"id": PA, "name": "设备甲", "platform": "windows",
          "ips": ["192.168.1.10"], "online": True, "connected": True},
         {"id": PB, "name": "设备乙", "platform": "android",
          "ips": ["192.168.1.11"], "online": True, "connected": True}]
win._on_peers(peers)
app.processEvents()


def select(pid):
    win.device_list.clearSelection()
    for i in range(win.device_list.count()):
        if win.device_list.item(i).data(Qt.UserRole) == pid:
            win.device_list.item(i).setSelected(True)
            break
    win._on_target_changed()
    app.processEvents()


def visible_texts():
    return [m.get("text") for m in win._visible_msgs()]


print("== G8 _channel_for 语义 ==")
ck("G8a broadcast=True → group", win._channel_for([PA, PB], True) == "group")
ck("G8b broadcast=False → p2p", win._channel_for([PA], False) == "p2p")

print("== G1/G2 send 打标 ==")
select(ALL_ID)
win.input_edit.setPlainText("群发测试消息")
win._send_input()
app.processEvents()
select(PA)
win.input_edit.setPlainText("私聊测试消息")
win._send_input()
app.processEvents()

all_msgs = []
for lst in win.msgs.values():
    all_msgs.extend(lst)
grp = [m for m in all_msgs if m.get("text") == "群发测试消息"]
p2p = [m for m in all_msgs if m.get("text") == "私聊测试消息"]
ck("G1 群发消息带 channel=group",
   bool(grp) and all(m.get("channel") == "group" for m in grp),
   f"n={len(grp)} ch={[m.get('channel') for m in grp]}")
ck("G2 定向消息带 channel=p2p",
   bool(p2p) and all(m.get("channel") == "p2p" for m in p2p),
   f"n={len(p2p)} ch={[m.get('channel') for m in p2p]}")

print("== G3 全部设备视图：group 可见 / p2p 被过滤 ==")
select(ALL_ID)
txts = visible_texts()
ck("G3a 群发消息在全部设备可见", "群发测试消息" in txts, f"visible={txts}")
ck("G3b 定向私聊在全部设备被过滤", "私聊测试消息" not in txts,
   f"visible={txts}")

print("== G4 老数据（无 channel）向后兼容 ==")
legacy = {"kind": "text", "dir": "in", "peer_id": PB, "peer_name": "设备乙",
          "mid": "legacy000000000001", "text": "无频道老消息",
          "ts": now + 10}          # 注意：没有 channel 字段
win.msgs.setdefault(PB, []).append(legacy)
win._render_chat()
app.processEvents()
txts = visible_texts()
ck("G4 全部设备视图下无 channel 老数据仍可见",
   "无频道老消息" in txts, f"visible={txts}")

print("== G5/G6 单设备视图 ==")
select(PA)
txts = visible_texts()
ck("G5 单设备视图可见该设备的 p2p", "私聊测试消息" in txts, f"visible={txts}")
ck("G6 单设备视图可见该设备参与的 group", "群发测试消息" in txts,
   f"visible={txts}")

print("== G7 待发送项在全部设备视图可见 ==")
# 造一个待发送项
win._pending_files.append({
    "mid": "pend00000000000001", "type": "text", "text": "待发送文本",
    "paths": [], "targets": [PA], "broadcast": False, "ts": now + 20})
win.msgs.setdefault(win.PENDING_PEER, []).append({
    "kind": "text", "dir": "out", "peer_id": win.PENDING_PEER,
    "peer_name": "我", "mid": "pend00000000000001", "text": "待发送文本",
    "state": "pending", "ts": now + 20})
select(ALL_ID)
txts = visible_texts()
ck("G7 全部设备视图下待发送项可见", "待发送文本" in txts, f"visible={txts}")

print("\n" + "=" * 56)
print(f"需求 #5/#6 行为验证：{PASS}/{PASS + FAIL} 通过")
if FAILS:
    print("失败项：")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("结论：「全部设备」纯群聊视图语义正确 ✓")
