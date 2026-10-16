# -*- coding: utf-8 -*-
"""v1.18.16 行为测试 —— 左侧设备列表「右键删除 + 多选全部删除」。

用户需求：
  · 左键点设备列表右击可以删除
  · 多选（Ctrl/Shift）时底部出现「全部删除」按钮
  · 删除时连带删掉 聊天记录 / 接收文件夹 / 设备档案(known_peers)
  · **「全部设备」是固定项，不可删除**

本测试真跑 MainWindow 的右键菜单、多选批量删除、全设备保护，
并校验三类数据（history jsonl / 保存目录下设备文件夹 / known_peers）真的被清掉。

运行：python tests/verify_v11816_device_delete.py
"""
import os
import shutil
import sys
import tempfile

os.environ.pop("QT_QPA_PLATFORM", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QAbstractItemView
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

tmp = tempfile.mkdtemp(prefix="fd_v11816_")
SAVE = os.path.join(tmp, "save")
os.makedirs(SAVE, exist_ok=True)
os.environ["FLASHDROP_DATA_DIR"] = tmp

from app.config import Config
from app.node import FlashNode
from app.ui import main_window as MW
from app.ui.main_window import MainWindow, ALL_ID

P, F = [], []


def check(name, cond, detail=""):
    (P if cond else F).append(name)
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", name,
                          ("   " + detail) if (detail and not cond) else ""))


PEERS = {
    "aaaa111111111111": "-windows-PC",
    "bbbb222222222222": "PixelPhone",
    "cccc333333333333": "iPad",
}


def build():
    """造一个含 3 台已知设备的窗口（离线，走 known_peers 路径）"""
    cfg = Config()
    cfg["theme"] = "light"
    cfg["save_dir"] = SAVE
    cfg["known_peers"] = {
        pid: {"id": pid, "name": name, "platform": "windows",
              "ips": ["192.168.1.%d" % (i + 2)], "last_seen": 0}
        for i, (pid, name) in enumerate(PEERS.items())
    }
    cfg["pending_files"] = []
    w = MainWindow(cfg, FlashNode(cfg))
    w.resize(1000, 700)
    w.show()
    for _ in range(6):
        app.processEvents()
    # 造三类数据：磁盘记录 / 接收文件夹 / 内存消息
    for pid, name in PEERS.items():
        w.history.append(pid, {"kind": "text", "dir": "in", "text": "hi",
                               "ts": 1, "mid": "x-" + pid})
        d = os.path.join(SAVE, name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "photo.jpg"), "wb") as f:
            f.write(b"x")
    w.msgs = {pid: [{"kind": "text", "dir": "in", "text": "hi", "ts": 1,
                     "mid": "m-" + pid}] for pid in PEERS}
    w._refresh_devices()
    for _ in range(6):
        app.processEvents()
    return w


def cur_view_sel(w):
    return [it.data(Qt.UserRole) for it in w.device_list.selectedItems()]


def item_rect(w, pid):
    """找到某设备在列表里的项"""
    for i in range(w.device_list.count()):
        it = w.device_list.item(i)
        if it.data(Qt.UserRole) == pid:
            return it
    return None


def select(w, pids):
    w.device_list.blockSignals(True)
    w.device_list.clearSelection()
    for pid in pids:
        it = item_rect(w, pid)
        if it is not None:
            it.setSelected(True)
    w.device_list.blockSignals(False)
    w._on_target_changed()


# 把确认框一律自动点"是"
MW.confirm = lambda *a, **k: True

print("=" * 70)
print("v1.18.16 设备列表删除功能验收")
print("=" * 70)

# ---------- §1 右键菜单已挂上 ----------
print("\n=== §1 右键菜单 ===")
w = build()
check("设备列表已启用自定义右键菜单",
      w.device_list.contextMenuPolicy() == Qt.CustomContextMenu)
check("列表支持多选（ExtendedSelection）",
      w.device_list.selectionMode() == QAbstractItemView.ExtendedSelection)

def menu_items(w, pid):
    """取右键菜单的 (文本, 是否可用) —— 不 exec，避免模态框卡住测试"""
    it = item_rect(w, pid)
    m = w._build_device_menu(w.device_list.visualItemRect(it).center())
    if m is None:
        return []
    return [(a.text(), a.isEnabled()) for a in m.actions()]


items = menu_items(w, "bbbb222222222222")
texts = [t for t, _ in items]
check("★ 右击设备出现「删除…的会话」",
      any("删除" in t and "PixelPhone" in t for t in texts), str(texts))
check("★ 右击菜单项可点击（enabled=True）",
      any("删除" in t and en for t, en in items), str(items))

# ---------- §2 「全部设备」不可删除 ----------
print("\n=== §2 「全部设备」是固定项，不可删除 ===")
items2 = menu_items(w, ALL_ID)
check("★ 右击「全部设备」提示不可删除",
      any("不可删除" in t for t, _ in items2), str(items2))
check("★「全部设备」菜单项被禁用",
      all(not en for t, en in items2 if "不可删除" in t), str(items2))
select(w, [ALL_ID])
check("★ 选中「全部设备」时视为「无可删除项」",
      w._deletable_selected_ids() == [],
      str(w._deletable_selected_ids()))
w._delete_selected_peers()          # 不应弹确认、不应删任何东西
check("★ 对「全部设备」调用删除不会误删设备",
      len(w.cfg["known_peers"]) == 3, str(len(w.cfg["known_peers"])))

# ---------- §3 多选 → 底部出现「删除选中」按钮 ----------
print("\n=== §3 多选时底部出现「删除选中」按钮 ===")
w = build()
btn = w.del_sel_btn
row = w.del_sel_row
cancel = w.del_cancel_btn
check("★ 底部存在「删除选中」按钮", btn is not None)
check("★ 底部存在「取消」按钮", cancel is not None)
check("初始为隐藏", not row.isVisible())
select(w, ["aaaa111111111111", "bbbb222222222222"])
check("★ 多选 2 个后操作行显示", row.isVisible())
check("★ 删除按钮文案带计数", "2" in btn.text(), btn.text())
select(w, ["aaaa111111111111"])
# ★ v1.18.17：单选不再显示删除按钮（用户反馈"单选底部就有删除"）
check("★ 单选时底部不显示（避免误触）", not row.isVisible())
select(w, [ALL_ID])
check("★ 只选「全部设备」时隐藏", not row.isVisible())
select(w, [])
check("未选中时隐藏", not row.isVisible())
select(w, ["aaaa111111111111", "bbbb222222222222", "cccc333333333333"])
check("★ 三选时文案为 3", "3" in btn.text(), btn.text())
# 「取消」应清空选择
w._cancel_multi_select()
check("★ 点「取消」后清空多选", len(w._deletable_selected_ids()) == 0,
      str(w._deletable_selected_ids()))
check("★ 点「取消」后回到「全部设备」视图",
      cur_view_sel(w) == [ALL_ID], str(cur_view_sel(w)))
check("★ 点「取消」后操作行隐藏", not row.isVisible())

# ---------- §4 批量删除：记录 + 文件夹 + 设备档案 ----------
print("\n=== §4 批量删除连带清理三类数据 ===")
w = build()
before_kp = set(w.cfg["known_peers"].keys())
check("前置：known_peers 有 3 台", len(before_kp) == 3)
check("前置：三台都有磁盘记录文件",
      all(os.path.exists(w.history._path(pid)) for pid in PEERS),
      str([os.path.exists(w.history._path(p)) for p in PEERS]))
check("前置：三个接收文件夹都在",
      all(os.path.isdir(os.path.join(SAVE, n)) for n in PEERS.values()))

targets = ["aaaa111111111111", "cccc333333333333"]
select(w, targets)
w._delete_selected_peers()

check("★ known_peers 剩下 1 台",
      set(w.cfg["known_peers"].keys()) == {"bbbb222222222222"},
      str(list(w.cfg["known_peers"].keys())))
check("★ 两台的磁盘记录已删",
      not os.path.exists(w.history._path(targets[0]))
      and not os.path.exists(w.history._path(targets[1])))
check("★ 未选中的那台记录仍在",
      os.path.exists(w.history._path("bbbb222222222222")))
check("★ 两个接收文件夹已删",
      not os.path.isdir(os.path.join(SAVE, PEERS[targets[0]]))
      and not os.path.isdir(os.path.join(SAVE, PEERS[targets[1]])))
check("★ 未选中的文件夹仍在",
      os.path.isdir(os.path.join(SAVE, PEERS["bbbb222222222222"])))
check("★ 内存消息已剔除",
      targets[0] not in w.msgs and targets[1] not in w.msgs)
check("★ 未选中设备的内存消息保留",
      "bbbb222222222222" in w.msgs)
check("★ 保存目录本身未被误删", os.path.isdir(SAVE))

# ---------- §5 单个删除（右键路径） ----------
print("\n=== §5 单设备删除 ===")
w = build()
w._delete_peer_conversation("bbbb222222222222")
check("★ 单删后 known_peers 剩 2 台", len(w.cfg["known_peers"]) == 2,
      str(len(w.cfg["known_peers"])))
check("★ 单删后该设备文件夹消失",
      not os.path.isdir(os.path.join(SAVE, PEERS["bbbb222222222222"])))
check("★ 其他设备文件夹仍在",
      os.path.isdir(os.path.join(SAVE, PEERS["aaaa111111111111"])))
w._delete_peer_conversation(ALL_ID)
check("★ 对「全部设备」单删被拒绝（仍 2 台）",
      len(w.cfg["known_peers"]) == 2, str(len(w.cfg["known_peers"])))

# ---------- §6 未选中任何设备时的提示 ----------
print("\n=== §6 未选中时的友好提示 ===")
w = build()
msgs = []
w._toast = lambda t: msgs.append(t)
w._delete_selected_peers()
check("★ 给出「请先选中」提示",
      any("请先" in m for m in msgs), str(msgs))
check("★ 未误删任何设备", len(w.cfg["known_peers"]) == 3)

shutil.rmtree(tmp, ignore_errors=True)

print()
print("=" * 70)
if F:
    print("失败项：")
    for f in F:
        print("  - %s" % f)
print("v1.18.16 设备删除验收：通过 %d 项，失败 %d 项" % (len(P), len(F)))
print("=" * 70)
# 多个 MainWindow 的 node 线程仍在跑，用 os._exit 硬退，避免测试进程挂住
import os as _os
_os._exit(1 if F else 0)