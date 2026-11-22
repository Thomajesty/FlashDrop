# -*- coding: utf-8 -*-
"""v1.18.36 复现：对离线设备发送 → 待发送卡片消失

用户反馈：新版 Windows 对离线设备发送，聊天区不再出现「待发送」卡片。

复现路径（源码级 UI，offscreen）：
  R1 直调 _queue_files（入队+显示）
  R2 走完整入口 _do_send_files（intent 含离线设备）
  R3 渲染后检查聊天区气泡数量
"""
import os
import re
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TMP = tempfile.mkdtemp(prefix="flashdrop_pd_data_")
os.environ["FLASHDROP_DATA_DIR"] = _TMP
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QEventLoop
from PySide6.QtCore import Qt

from app.config import Config
from app.node import FlashNode
from app.ui.main_window import MainWindow, ALL_ID

FAILS = []
N = 0


def ck(name, cond, extra=""):
    global N
    N += 1
    if not cond:
        FAILS.append(f"{name} | {extra}")
    print(("  ok  " if cond else " FAIL ") + name +
          ((" | " + str(extra)) if extra and not cond else ""))


def wait_ms(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main():
    tmp = tempfile.mkdtemp(prefix="flashdrop_pd_")
    cfgA = Config(os.path.join(tmp, "a.json"))
    cfgA.data.update({"device_id": "aaaaaaaaaaaaaaaa", "name": "UI-A", "port": 58910,
                      "save_dir": os.path.join(tmp, "a_save"),
                      "cache_dir": os.path.join(tmp, "a_cache"),
                      "minimize_to_tray": False, "notify_on_receive": False})
    cfgA.save()

    app = QApplication(sys.argv)
    nodeA = FlashNode(cfgA)
    win = MainWindow(cfgA, nodeA)
    win.show()
    wait_ms(300)

    # 模拟一台**离线**设备（在 peers 里、online=False）—— 走真实 _on_peers 注入
    pid = "bbbbbbbbbbbbbbbb"
    win._on_peers([{"id": pid, "name": "离线手机", "platform": "android",
                    "ips": [], "online": False, "connected": False}])
    wait_ms(100)

    # 选中该离线设备
    found = False
    for i in range(win.device_list.count()):
        it = win.device_list.item(i)
        if it.data(Qt.UserRole) == pid:
            win.device_list.itemClicked.emit(it)
            it.setSelected(True)
            found = True
            break
    ck("P0 离线设备已选中", found)
    wait_ms(200)

    src = os.path.join(tmp, "hello.txt")
    with open(src, "wb") as f:
        f.write(b"hello pending")

    # ---- R1: 直调 _queue_files ----
    win._queue_files([src], [pid])
    pend = win.msgs.get(win.PENDING_PEER, [])
    ck("R1 入队后 msgs[PENDING_PEER] 有 1 条", len(pend) == 1, f"got {len(pend)}")
    vis = [m for m in win._visible_msgs() if m.get("state") == "pending"]
    ck("R1 _visible_msgs 包含 pending", len(vis) == 1, f"got {len(vis)}")
    nb = win.chat_vbox.count()
    ck("R1 聊天区有气泡 (>0)", nb > 1, f"chat_vbox count={nb}")

    # ---- R2: 完整入口 _do_send_files（intent 含离线设备）----
    win._do_send_files([], [src], intent=[pid])
    pend2 = [m for m in win.msgs.get(win.PENDING_PEER, [])]
    ck("R2 再发一条后 pending 卡片 = 2", len(pend2) == 2, f"got {len(pend2)}")
    vis2 = [m for m in win._visible_msgs() if m.get("state") == "pending"]
    ck("R2 _visible_msgs pending = 2", len(vis2) == 2, f"got {len(vis2)}")

    # ---- R3: 队列持久化 ----
    ck("R3 cfg.pending_files 持久化 2 条", len(win.cfg["pending_files"]) == 2,
       f"got {len(win.cfg['pending_files'])}")

    # ---- R4: 切到「全部设备」视图再切回来（页缓存往返）----
    all_it = None
    for i in range(win.device_list.count()):
        it = win.device_list.item(i)
        if it.data(Qt.UserRole) == ALL_ID:
            all_it = it
            break
    if all_it is not None:
        win.device_list.itemClicked.emit(all_it)
        all_it.setSelected(True)
        wait_ms(150)
        vis_all = [m for m in win._visible_msgs() if m.get("state") == "pending"]
        ck("R4 全部设备视图 pending 可见", len(vis_all) == 2, f"got {len(vis_all)}")
        # 切回离线设备
        for i in range(win.device_list.count()):
            it = win.device_list.item(i)
            if it.data(Qt.UserRole) == pid:
                win.device_list.itemClicked.emit(it)
                it.setSelected(True)
                break
        wait_ms(150)
        vis_back = [m for m in win._visible_msgs() if m.get("state") == "pending"]
        ck("R4 切回离线设备 pending 仍可见", len(vis_back) == 2,
           f"got {len(vis_back)}")
        nb2 = win.chat_vbox.count()
        ck("R4 切回后聊天区气泡数 >1", nb2 > 1, f"count={nb2}")

    # ---- R5: 页缓存 key 稳定性（v1.18.37 id 复用撞车修复）----
    # 页 key 必须用 _msg_identity，不含 id(m)
    src2 = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "app", "ui", "main_window.py"),
        encoding="utf-8").read()
    ck("R5 页缓存 key 使用 _msg_identity（防 id 复用撞车）",
       "ids = [self._msg_identity(m) for m in msgs]" in src2
       and "[id(m) for m in msgs]" not in src2)
    ck("R5 存在待发送一致性自愈 _pending_self_heal",
       "def _pending_self_heal" in src2
       and "self._pending_self_heal()" in src2)
    ck("R5 pending 豁免尾部截断（窗口值随版本演进，v1.18.38 起 200）",
       re.search(r'rest\[-\d+:\] \+ pended', src2) is not None)

    win.close()
    print()
    if FAILS:
        print("FAILS:", len(FAILS))
        for f in FAILS:
            print(" -", f)
        sys.exit(1)
    print(f"ALL {N} PASS")


if __name__ == "__main__":
    main()
