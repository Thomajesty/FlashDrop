# -*- coding: utf-8 -*-
"""v1.18.40 复现：聊天区不粘底 —— 新消息不滚到最底部，下面一大片空白

用户截图：与 SM-S9180 会话，聊天区大片空白，新内容没有显示在底部。

复现路径（源码级 UI，offscreen）：
  S1 灌历史消息渲染 → 应粘底
  S2 追加新消息（grew 分支）→ 应粘底且最后气泡在视口内
  S3 缓存命中切页路径 → 应粘底
  S4 建新页路径 → 应粘底
  S5 最小化 trim 后恢复 → 应粘底
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TMP = tempfile.mkdtemp(prefix="flashdrop_sb_data_")
os.environ["FLASHDROP_DATA_DIR"] = _TMP
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QEventLoop, Qt, QPoint

from app.config import Config
from app.node import FlashNode
from app.ui.main_window import MainWindow

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


def settle(rounds=6):
    for _ in range(rounds):
        app.processEvents()
        wait_ms(30)
        app.processEvents()


def stick_ok(win):
    sb = win.chat_scroll.verticalScrollBar()
    return sb.value() >= sb.maximum() - max(
        win.chat_scroll.viewport().height(), 1) - 60


def last_bubble_visible(win):
    """最后一个气泡是否整体/大部分在视口内"""
    n = win.chat_vbox.count()
    if n < 2:
        return False, "no bubbles"
    w = win.chat_vbox.itemAt(n - 2).widget()   # n-1 是弹簧
    if w is None:
        return False, "no widget"
    vp = win.chat_scroll.viewport()
    top = w.mapTo(vp, QPoint(0, 0)).y()
    bottom = top + w.height()
    vh = vp.height()
    # 气泡底部进入视口即算可见（允许差 40px 余量）
    return bottom <= vh + 40, f"bubble bottom={bottom} viewport_h={vh}"


def main():
    tmp = tempfile.mkdtemp(prefix="flashdrop_sb_")
    cfgA = Config(os.path.join(tmp, "a.json"))
    cfgA.data.update({"device_id": "aaaaaaaaaaaaaaaa", "name": "UI-A", "port": 58911,
                      "save_dir": os.path.join(tmp, "a_save"),
                      "cache_dir": os.path.join(tmp, "a_cache"),
                      "minimize_to_tray": False, "notify_on_receive": False})
    cfgA.save()

    global app
    app = QApplication(sys.argv)
    nodeA = FlashNode(cfgA)
    win = MainWindow(cfgA, nodeA)
    win.resize(1000, 760)
    win.show()
    wait_ms(300)

    pid = "bbbbbbbbbbbbbbbb"
    win._on_peers([{"id": pid, "name": "安卓手机", "platform": "android",
                    "ips": [], "online": False, "connected": False}])
    wait_ms(100)

    for i in range(win.device_list.count()):
        it = win.device_list.item(i)
        if it.data(Qt.UserRole) == pid:
            win.device_list.itemClicked.emit(it)
            it.setSelected(True)
            break
    wait_ms(200)

    import time
    base = int(time.time() * 1000) - 60_000
    for i in range(30):
        win.msgs.setdefault(pid, []).append({
            "kind": "text", "dir": "in", "peer_id": pid,
            "text": f"历史消息 {i}", "ts": base + i * 1000})

    # ---- S1: 首次渲染（建新页）----
    win._render_chat()
    settle()
    sb = win.chat_scroll.verticalScrollBar()
    ck("S1 建新页后粘底", stick_ok(win),
       f"value={sb.value()} max={sb.maximum()}")
    ok, why = last_bubble_visible(win)
    ck("S1 最后气泡在视口内", ok, why)
    ck("S1 _stick_bottom=True", win._stick_bottom is True)

    # ---- S2: 追加一条（grew 分支）----
    win.msgs[pid].append({
        "kind": "text", "dir": "out", "peer_id": pid,
        "text": "新发送的消息", "ts": base + 31_000})
    win._render_chat()
    settle()
    ck("S2 追加后粘底", stick_ok(win),
       f"value={sb.value()} max={sb.maximum()}")
    ok, why = last_bubble_visible(win)
    ck("S2 追加后最后气泡在视口内", ok, why)
    n_bubbles = win.chat_vbox.count() - 1
    ck("S2 气泡数 = 31", n_bubbles == 31, f"got {n_bubbles}")

    # ---- S3: 切到全部设备再切回（缓存命中路径）----
    from app.ui.main_window import ALL_ID
    for i in range(win.device_list.count()):
        it = win.device_list.item(i)
        if it.data(Qt.UserRole) == ALL_ID:
            win.device_list.itemClicked.emit(it)
            it.setSelected(True)
            break
    wait_ms(150)
    win._render_chat()
    settle()
    for i in range(win.device_list.count()):
        it = win.device_list.item(i)
        if it.data(Qt.UserRole) == pid:
            win.device_list.itemClicked.emit(it)
            it.setSelected(True)
            break
    wait_ms(150)
    win._render_chat()
    settle()
    ck("S3 缓存切回后粘底", stick_ok(win),
       f"value={sb.value()} max={sb.maximum()}")
    ok, why = last_bubble_visible(win)
    ck("S3 切回后最后气泡在视口内", ok, why)

    # ---- S4: 强制 force 建新页 ----
    win._render_chat(force=True)
    settle()
    ck("S4 force 建新页后粘底", stick_ok(win),
       f"value={sb.value()} max={sb.maximum()}")
    ok, why = last_bubble_visible(win)
    ck("S4 force 后最后气泡在视口内", ok, why)

    # ---- S5: 最小化触发 _trim_pages，恢复后渲染 ----
    win.showMinimized()
    settle()
    win.showNormal()
    settle()
    win._render_chat()
    settle()
    ck("S5 trim 恢复后粘底", stick_ok(win),
       f"value={sb.value()} max={sb.maximum()}")
    ok, why = last_bubble_visible(win)
    ck("S5 trim 恢复后最后气泡在视口内", ok, why)

    print(f"\n{N - len(FAILS)}/{N} passed")
    if FAILS:
        for f in FAILS:
            print("  FAIL:", f)
        sys.exit(1)


if __name__ == "__main__":
    main()
