# -*- coding: utf-8 -*-
"""v1.6.0 专项验证：链接识别 + 文件离线待发队列。"""

import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TMP = tempfile.mkdtemp(prefix="flashdrop_v16_")
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
from app import util

print("== 1. 链接识别 ==")
check("https 识别", util.first_url("看这个 https://example.com/a?b=1 很棒") == "https://example.com/a?b=1")
check("www 自动补协议", util.first_url("打开 www.baidu.com 搜索") == "http://www.baidu.com")
check("中文标点截断", util.first_url("访问 https://a.cn/x，谢谢") == "https://a.cn/x")
check("无链接返回 None", util.first_url("普通消息 192.168.1.1") is None)

print("== 2. 待发队列：离线保存 → 上线自动发送 ==")
cfg = Config(os.path.join(_TMP, "cfg.json"))
cfg.data.update({"device_id": "uuuuuuuuuuuuuuuu", "name": "UI-16", "port": 58970,
                 "save_dir": os.path.join(_TMP, "s"), "cache_dir": os.path.join(_TMP, "c")})
cfg.save()
from app.ui.main_window import MainWindow
win = MainWindow(cfg, FlashNode(cfg))
a_events = []
_orig_evt = win.bridge._on_evt
def _probe_evt(evt):
    a_events.append(evt)
    _orig_evt(evt)
win.bridge._on_evt = _probe_evt
_orig_flush = win._flush_pending
def _fp():
    online = [pid for pid, p in win.peers.items() if p.get("online")]
    print("   FLUSH call pending=", len(win._pending_files), "online=", online)
    _orig_flush()
    print("   FLUSH done pending=", len(win._pending_files))
win._flush_pending = _fp
_orig_sf = win.bridge.node.send_files
def _sf(targets, paths):
    print("   NODE send_files targets=", targets,
          "isfile=", [os.path.isfile(p) for p in paths])
    _orig_sf(targets, paths)
win.bridge.node.send_files = _sf

# 离线入队（无任何 peers；带明确意图目标以便确定性断言）
f1 = os.path.join(_TMP, "q1.bin")
with open(f1, "wb") as f:
    f.write(os.urandom(200_000))
win._do_send_files([], [f1], intent=["bbbbbbbbbbbbbbbb"])
check("离线发送进入待发队列", len(win._pending_files) == 1)
check("队列已持久化到配置", len(cfg["pending_files"] or []) == 1)

# 目标上线 → 自动发送
cfgB = Config(os.path.join(_TMP, "b.json"))
cfgB.data.update({"device_id": "bbbbbbbbbbbbbbbb", "name": "队列B", "port": 58971,
                  "save_dir": os.path.join(_TMP, "bs"), "cache_dir": os.path.join(_TMP, "bc")})
cfgB.save()
nodeB = FlashNode(cfgB)
evB = []
nodeB.emit = lambda e: evB.append(e)
nodeB.start()
time.sleep(2.5)
node = win.bridge.node
got_online = "bbbbbbbbbbbbbbbb" in node.online_peer_ids()
check("目标设备上线被发现", got_online)
if got_online:
    win._on_peers(node.peers_snapshot())
    deadline = time.time() + 10
    done = []
    while time.time() < deadline:
        done = [e for e in evB if e.get("event") == "transfer" and e.get("state") == "done"]
        if done:
            break
        time.sleep(0.3)
    check("上线后待发文件自动送出", len(done) == 1)
    if not done:
        print("   DEBUG evB transfers:",
              [(e.get("state"), e.get("reason"), e.get("file")) for e in evB
               if e.get("event") == "transfer"])
        print("   DEBUG A-side:",
              [(e.get("state"), e.get("reason")) for e in a_events
               if e.get("event") == "transfer"])
        print("   DEBUG A conns:", {k[:4]: (v.alive, v.hello_got)
                                    for k, v in node.conns.items()})
        print("   DEBUG B conns:", {k[:4]: (v.alive, v.hello_got)
                                    for k, v in nodeB.conns.items()})
        print("   DEBUG pending:", win._pending_files)
    check("队列已清空", len(win._pending_files) == 0 and len(cfg["pending_files"] or []) == 0)

win._real_quit()
nodeB.stop()

print()
fails = [r for r in RESULTS if not r[1]]
print(f"===== v1.6.0 专项验证: {len(RESULTS) - len(fails)} 通过, {len(fails)} 失败 =====")
sys.exit(1 if fails else 0)
