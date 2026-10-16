# -*- coding: utf-8 -*-
"""第七轮优化专项验证：toast/扫描行/下拉QSS/关于页/配色生效/设备合并/历史迁移。"""

import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TMP = tempfile.mkdtemp(prefix="flashdrop_v7_")
os.environ["FLASHDROP_DATA_DIR"] = _TMP
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail and not cond else ""))


print("== 1. 配置：旧版随机 device_id 捕获为 legacy_ids ==")
import json
from app.config import Config, util
cfgp = os.path.join(_TMP, "legacy.json")
stable = util.stable_device_id()
with open(cfgp, "w", encoding="utf-8") as f:
    json.dump({"device_id": "deadbeefdeadbeef"}, f)
cfgL = Config(cfgp)
check("device_id 覆盖为稳定 ID", cfgL["device_id"] == stable)
check("旧 ID 进入 legacy_ids", "deadbeefdeadbeef" in (cfgL["legacy_ids"] or []),
      str(cfgL["legacy_ids"]))
cfgL2 = Config(cfgp)
check("再次加载不重复累积", (cfgL2["legacy_ids"] or []).count("deadbeefdeadbeef") == 1)

print("== 2. 节点：同机跨版本身份合并（host / alt / 在线保护） ==")
from app.node import FlashNode, Peer
cfgN = Config(os.path.join(_TMP, "node.json"))
node = FlashNode(cfgN)
events = []
node.emit = lambda e: events.append(e)

p_old = Peer("aaaaaaaaaaaaaaaa")
p_old.host = "HOST-MACHINE-1"
p_old.name = "旧版设备"
p_old.last_seen = 0.0          # 离线
node.peers[p_old.id] = p_old
cand = node._merge_candidate("bbbbbbbbbbbbbbbb", {"host": "HOST-MACHINE-1"})
check("host 相同的离线条目识别为同设备", cand == "aaaaaaaaaaaaaaaa", str(cand))

cand2 = node._merge_candidate("cccccccccccccccc", {"alt": ["aaaaaaaaaaaaaaaa"]})
check("id 命中 alt 列表识别为同设备", cand2 == "aaaaaaaaaaaaaaaa", str(cand2))

p_online = Peer("dddddddddddddddd")
p_online.host = "HOST-MACHINE-1"
import time as _t
p_online.last_seen = _t.time()  # 在线（UDP 可见窗口内）
node.peers[p_online.id] = p_online
del node.peers["aaaaaaaaaaaaaaaa"]  # 移除离线条目，仅剩在线条目
cand3 = node._merge_candidate("eeeeeeeeeeeeeeee", {"host": "HOST-MACHINE-1"})
check("在线条目不合并（保护同机多实例）", cand3 is None, str(cand3))
del node.peers["dddddddddddddddd"]

node.peers["aaaaaaaaaaaaaaaa"] = p_old
node._merge_peer("aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb")
check("合并后旧条目移除", "aaaaaaaaaaaaaaaa" not in node.peers)
check("合并后新条目继承 host/名称",
      node.peers["bbbbbbbbbbbbbbbb"].host == "HOST-MACHINE-1"
      and node.peers["bbbbbbbbbbbbbbbb"].name == "旧版设备")
check("发出 peer_merged 事件",
      any(e.get("event") == "peer_merged" and e.get("old") == "aaaaaaaaaaaaaaaa"
          and e.get("new") == "bbbbbbbbbbbbbbbb" for e in events))

print("== 3. 历史：merge 迁移与去重 ==")
from app.ui.history import History
hist = History(max_per_peer=100)
hist.append("aaaaaaaaaaaaaaaa", {"kind": "text", "dir": "in", "text": "旧消息甲", "ts": 1, "mid": "m1"})
hist.append("aaaaaaaaaaaaaaaa", {"kind": "text", "dir": "in", "text": "旧消息乙", "ts": 2, "mid": "m2"})
hist.append("bbbbbbbbbbbbbbbb", {"kind": "text", "dir": "in", "text": "旧消息甲", "ts": 1, "mid": "m1"})  # 重复
hist.merge("aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb")
new_msgs = hist.load("bbbbbbbbbbbbbbbb")
texts = [m.get("text") for m in new_msgs]
check("旧消息并入新条目", "旧消息乙" in texts)
check("重复消息不重复写入", texts.count("旧消息甲") == 1, str(texts))
check("旧历史文件删除", not os.path.exists(hist._path("aaaaaaaaaaaaaaaa")))

print("== 4. UI：主题/配色生效 + toast + 扫描行 + 下拉 QSS + 关于页 ==")
from PySide6.QtWidgets import QApplication, QLabel
app = QApplication.instance() or QApplication(sys.argv)
cfgU = Config(os.path.join(_TMP, "ui.json"))
cfgU.data.update({"device_id": "uuuuuuuuuuuuuuuu", "name": "UI-7", "port": 58920,
                  "save_dir": os.path.join(_TMP, "u_save"),
                  "cache_dir": os.path.join(_TMP, "u_cache")})
cfgU.save()
from app.ui.main_window import MainWindow, SettingsDialog
win = MainWindow(cfgU, FlashNode(cfgU))

# 4.1 配色经 SettingsDialog.apply() 后整体生效
dlg = SettingsDialog(cfgU, win)
idx = dlg.scheme_combo.findData("green")
dlg.scheme_combo.setCurrentIndex(idx)
dlg.apply()
check("apply() 写入 bubble_scheme", cfgU["bubble_scheme"] == "green")
win._apply_theme()
check("theme 注入方案色", win.theme["scheme_out"] == "#95EC69")
m = {"kind": "text", "dir": "out", "peer_id": "x", "peer_name": "我", "text": "t", "ts": 1}
from app.ui.widgets import BubbleFrame
bf = BubbleFrame(m, win.theme)
check("发送气泡样式应用微信绿", "#95EC69" in bf._text_lbl.styleSheet())
# 改回 blue 双向验证
dlg2 = SettingsDialog(cfgU, win)
dlg2.scheme_combo.setCurrentIndex(dlg2.scheme_combo.findData("blue"))
dlg2.apply()
win._apply_theme()
bf2 = BubbleFrame(m, win.theme)
check("切回闪传蓝双向生效", "#3B82F6" in bf2._text_lbl.styleSheet())

# 4.2 toast
win._toast("测试通知")
toasts = [w for w in win.findChildren(QLabel) if w.objectName() == "Toast"]
check("保存后屏幕中间出现 Toast", len(toasts) >= 1)

# 4.3 扫描行按需显示（窗口未 show，用 isHidden 判断显式隐藏状态）
check("初始隐藏（无空白行）", win.scan_lbl.isHidden())
win._set_scan_text("扫描中…")
check("有内容时显示", not win.scan_lbl.isHidden() and win.scan_lbl.text() == "扫描中…")
win._set_scan_text("")
check("清空后隐藏", win.scan_lbl.isHidden())

# 4.4 下拉框 QSS 显式颜色
qss = win.styleSheet()
check("下拉 item 显式前景色", "QComboBox QAbstractItemView::item" in qss
      and "color:" in qss.split("QComboBox QAbstractItemView::item")[1][:200])

# 4.5 关于页
sd = SettingsDialog(cfgU, win)
from PySide6.QtWidgets import QTabWidget
tw = sd.findChild(QTabWidget)
texts2 = [tw.tabText(i) for i in range(tw.count())]
check("设置含“关于”页", "关于" in texts2, str(texts2))
about_tab = tw.widget(tw.count() - 1)
qlabels = about_tab.findChildren(QLabel)
check("关于页含作者与邮箱",
      any("Thomajesty" in l.text() and "Thomajesty@163.com" in l.text() for l in qlabels))

win._real_quit()

print()
fails = [r for r in RESULTS if not r[1]]
print(f"===== 第七轮专项验证: {len(RESULTS) - len(fails)} 通过, {len(fails)} 失败 =====")
sys.exit(1 if fails else 0)
