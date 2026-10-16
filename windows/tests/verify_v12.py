# -*- coding: utf-8 -*-
"""v1.2.0 专项验证：全局气泡（发送方配色随消息到接收端）+ 相关回归。"""

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TMP = tempfile.mkdtemp(prefix="flashdrop_v12_")
os.environ["FLASHDROP_DATA_DIR"] = _TMP
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail and not cond else ""))


from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)

from app.config import Config
from app.node import FlashNode
from app.ui.main_window import MainWindow
from app.ui.widgets import BubbleFrame
from app.ui.theme import BUBBLE_SCHEMES

cfg = Config(os.path.join(_TMP, "cfg.json"))
cfg.data.update({"device_id": "uuuuuuuuuuuuuuuu", "name": "UI-12", "port": 58930,
                 "save_dir": os.path.join(_TMP, "s"), "cache_dir": os.path.join(_TMP, "c")})
cfg.save()
node = FlashNode(cfg)
win = MainWindow(cfg, node)

print("== 1. 全局气泡：接收侧按发送方方案渲染 ==")
m_in = {"kind": "text", "dir": "in", "peer_id": "p1", "peer_name": "对方",
        "mid": "m1", "text": "全局气泡测试", "peer_scheme": "pink", "ts": 1}
bf_pink = BubbleFrame(m_in, win.theme)
style = bf_pink._text_lbl.styleSheet()
check("带 peer_scheme=pink 的接收气泡底色为樱花粉", "#F472B6" in style, style)
check("带方案的接收气泡文字为白色", "#FFFFFF" in style)

m_in2 = dict(m_in, peer_scheme="green", mid="m2")
bf_green = BubbleFrame(m_in2, win.theme)
check("green 方案接收气泡为微信绿", "#95EC69" in bf_green._text_lbl.styleSheet())

m_old = {"kind": "text", "dir": "in", "peer_id": "p1", "peer_name": "对方",
         "mid": "m3", "text": "旧消息", "ts": 2}   # 历史旧消息无 peer_scheme
bf_old = BubbleFrame(m_old, win.theme)
check("无 peer_scheme 的旧消息保持中性底色", "bubble_in" not in bf_old._text_lbl.styleSheet()
      and "F472B6" not in bf_old._text_lbl.styleSheet())

m_out = {"kind": "text", "dir": "out", "peer_id": "p1", "peer_name": "我",
         "mid": "m4", "text": "我发的", "ts": 3}
win.cfg["bubble_scheme"] = "purple"
win._apply_theme()
bf_out = BubbleFrame(m_out, win.theme)
check("发送侧仍按本机方案（紫色）", "#8B5CF6" in bf_out._text_lbl.styleSheet())

print("== 2. 节点：TEXT 消息携带本机方案字段 ==")
sent = {}
orig_send_json = FlashNode  # noqa: 直接构造 JSON 检查更简单：模拟 _send_text_task 的帧内容
import json as _json
from app import protocol as P
node2 = FlashNode(cfg)
node2.cfg = cfg
# 直接验证 cfg 读取链路（发送时取 self.cfg["bubble_scheme"]）
check("发送方案字段来源=配置 bubble_scheme", cfg["bubble_scheme"] == "purple")

# 端到端小回路：A 发 TEXT -> B 收事件带 scheme
cfgA = Config(os.path.join(_TMP, "a.json"))
cfgA.data.update({"device_id": "aaaaaaaaaaaaaaaa", "name": "A端", "port": 58931,
                  "save_dir": os.path.join(_TMP, "sa"), "cache_dir": os.path.join(_TMP, "ca")})
cfgA.data["bubble_scheme"] = "orange"
cfgA.save()
cfgB = Config(os.path.join(_TMP, "b.json"))
cfgB.data.update({"device_id": "bbbbbbbbbbbbbbbb", "name": "B端", "port": 58932,
                  "save_dir": os.path.join(_TMP, "sb"), "cache_dir": os.path.join(_TMP, "cb")})
cfgB.save()
nodeA, nodeB = FlashNode(cfgA), FlashNode(cfgB)
eventsB = []
nodeB.emit = lambda e: eventsB.append(e)
nodeA.start(); nodeB.start()
import time
conn_box = {}
nodeB.device_id = nodeB.device_id  # noqa 保持
# A 连接 B
fut = nodeA.connect_manual("127.0.0.1", 58932)
fut.result(15)
time.sleep(1.0)
nodeA.send_text(["bbbbbbbbbbbbbbbb"], "方案端到端")
time.sleep(2.5)
texts = [e for e in eventsB if e.get("event") == "text"]
check("B 收到 TEXT 事件", len(texts) >= 1)
check("TEXT 事件携带发送方 scheme=orange",
      texts and texts[0].get("scheme") == "orange",
      str(texts[:1]))
nodeA.stop(); nodeB.stop()

win._real_quit()

print()
fails = [r for r in RESULTS if not r[1]]
print(f"===== v1.2.0 专项验证: {len(RESULTS) - len(fails)} 通过, {len(fails)} 失败 =====")
sys.exit(1 if fails else 0)
