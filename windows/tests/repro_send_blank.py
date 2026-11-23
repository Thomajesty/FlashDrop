# -*- coding: utf-8 -*-
"""复现：电脑端发完消息，聊天区底部空白 / 新消息不在最底部

与 repro_scroll_bottom.py 的区别：那份测试只走了「msgs.append + _render_chat」
纯渲染路径；真实发送走的是
    _send_input → bridge.send_text → _out_text_msg → _append_msg →
    _append_bubble（**直接插当前页，不经过 _render_chat 的页缓存记账**）
这条路径页缓存 mids 不更新，下一次任何 _render_chat 的 grew 分支会把同一条
消息再插一遍（重复卡片）。

场景：
  R1 真实发送（在线设备）→ 气泡数 +1、粘底、最后气泡可见
  R2 发送后触发一次普通 _render_chat（设备刷新/主题/合并等都会触发）
     → 气泡数必须不变（当前实现预期 FAIL：重复卡片）
  R3 用户往上翻历史后发送 → 自己发的消息必须强制回到最底部
  R4 收到新消息（在底部）→ 粘底
"""
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TMP = tempfile.mkdtemp(prefix="flashdrop_sendblank_data_")
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


def settle(rounds=8):
    for _ in range(rounds):
        app.processEvents()
        wait_ms(30)
        app.processEvents()


def stick_ok(win):
    sb = win.chat_scroll.verticalScrollBar()
    return sb.value() >= sb.maximum() - max(
        win.chat_scroll.viewport().height(), 1) - 60


def bubble_texts(win):
    """当前页全部气泡的文本（按布局顺序）"""
    out = []
    for i in range(win.chat_vbox.count()):
        it = win.chat_vbox.itemAt(i)
        w = it.widget() if it is not None else None
        if w is None:
            continue
        t = getattr(w, "msg", {}).get("text", None)
        out.append((id(w.msg) if hasattr(w, "msg") else 0, t))
    return out


def count_occurrences(win, text):
    return sum(1 for _id, t in bubble_texts(win) if t == text)


def last_bubble_visible(win):
    n = win.chat_vbox.count()
    if n < 1:
        return False, "no bubbles"
    # 找最后一个真正的气泡控件（跳过弹簧 spacer item）
    w = None
    for i in range(n - 1, -1, -1):
        it = win.chat_vbox.itemAt(i)
        if it is not None and it.widget() is not None:
            w = it.widget()
            break
    if w is None:
        return False, "no widget"
    vp = win.chat_scroll.viewport()
    top = w.mapTo(vp, QPoint(0, 0)).y()
    bottom = top + w.height()
    vh = vp.height()
    return bottom <= vh + 40, f"bubble bottom={bottom} viewport_h={vh}"


def main():
    tmp = tempfile.mkdtemp(prefix="flashdrop_sendblank_")
    cfgA = Config(os.path.join(tmp, "a.json"))
    cfgA.data.update({"device_id": "aaaaaaaaaaaaaaaa", "name": "UI-A", "port": 58921,
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
                    "ips": [], "online": True, "connected": True}])
    wait_ms(100)

    for i in range(win.device_list.count()):
        it = win.device_list.item(i)
        if it.data(Qt.UserRole) == pid:
            win.device_list.itemClicked.emit(it)
            it.setSelected(True)
            break
    wait_ms(200)

    import time
    base = int(time.time() * 1000) - 120_000
    for i in range(30):
        win.msgs.setdefault(pid, []).append({
            "kind": "text", "dir": "in", "peer_id": pid,
            "text": f"历史消息 {i}", "ts": base + i * 1000})
    win._render_chat()
    settle()
    sb = win.chat_scroll.verticalScrollBar()
    ck("R0 初始渲染粘底", stick_ok(win),
       f"value={sb.value()} max={sb.maximum()}")

    # ============ R1: 真实发送路径（在线设备） ============
    # 桩掉 node 发送（不建真实 TCP），只保留 mid 返回与 ack 事件流
    sent_mid = ["mid-test-001"]

    def fake_send_text(targets, text):
        # 模拟 node._send_text_task 的 ack 流：立即 ok
        QTimer.singleShot(0, lambda: win._on_ack(targets[0], sent_mid[0]))
        return sent_mid[0]

    win.bridge.send_text = fake_send_text
    win.input_edit.setPlainText("你好，这是刚发送的消息")
    win._send_input()
    settle()

    n_occ = count_occurrences(win, "你好，这是刚发送的消息")
    ck("R1 发送后该消息只出现一次", n_occ == 1, f"出现 {n_occ} 次")
    ck("R1 发送后粘底", stick_ok(win),
       f"value={sb.value()} max={sb.maximum()}")
    ok, why = last_bubble_visible(win)
    ck("R1 最后气泡（新消息）在视口内", ok, why)
    # 最后一个气泡就是新发的
    bt = bubble_texts(win)
    ck("R1 新消息是最后一个气泡", bool(bt) and bt[-1][1] == "你好，这是刚发送的消息",
       f"最后一个={bt[-1][1] if bt else None}")

    # ============ R2: 发送后再来一次普通 _render_chat ============
    # 真机里设备列表刷新/主题切换/peer 合并/补发提交等都会触发 _render_chat；
    # 若页缓存没同步 _append_msg 直接插的气泡，grew 分支会把它再插一遍
    win._render_chat()
    settle()
    n_occ2 = count_occurrences(win, "你好，这是刚发送的消息")
    ck("R2 后续渲染后仍只出现一次（不重复）", n_occ2 == 1, f"出现 {n_occ2} 次")
    ck("R2 渲染后仍粘底", stick_ok(win),
       f"value={sb.value()} max={sb.maximum()}")

    # ============ R3: 用户往上翻历史后发送 ============
    sb.setValue(max(0, sb.maximum() // 2))   # 翻到中间
    settle()
    win.input_edit.setPlainText("第二条：往上翻后发送")
    win._send_input()
    settle()
    n_occ3 = count_occurrences(win, "第二条：往上翻后发送")
    ck("R3 上翻后发送：消息只出现一次", n_occ3 == 1, f"出现 {n_occ3} 次")
    ck("R3 上翻后发送：自己发的消息强制回到最底部", stick_ok(win),
       f"value={sb.value()} max={sb.maximum()}")
    ok, why = last_bubble_visible(win)
    ck("R3 新消息气泡在视口内", ok, why)

    # ============ R4: 收到新消息（在底部） ============
    win._on_text_in({"peer_id": pid, "peer_name": "安卓手机", "mid": "in-001",
                     "text": "对方回复了", "ts": int(time.time() * 1000)})
    settle()
    ck("R4 收到消息后粘底", stick_ok(win),
       f"value={sb.value()} max={sb.maximum()}")
    ok, why = last_bubble_visible(win)
    ck("R4 收到的消息气泡在视口内", ok, why)

    # ============ R5: 长页缓存 → 切到短会话视图 → 底部不得有大片空白 ============
    # QStackedWidget 默认 sizeHint = 所有页最大值：缓存里有长会话页时，
    # 当前短页被整体撑高，气泡下面全是空白（v1.18.41 前实测容器 2408px
    # 而短页内容只有 128px）
    pid2 = "cccccccccccccccc"
    win._on_peers([
        {"id": pid, "name": "安卓手机", "platform": "android", "ips": [],
         "online": True, "connected": True},
        {"id": pid2, "name": "新手机", "platform": "android", "ips": [],
         "online": True, "connected": True},
    ])
    wait_ms(200)
    # 先确保当前在 pid 视图（长会话），再切到 pid2（空会话 = 短页）
    # 注意必须单选（clearSelection），叠选会把两个会话合到一个视图
    ck("R5 长会话页先建立", win._select_peer_by_id(pid), "select pid")
    settle()
    ck("R5 切到短会话页", win._select_peer_by_id(pid2), "select pid2")
    settle()
    ck("R5 切到短会话后粘底", stick_ok(win),
       f"value={sb.value()} max={sb.maximum()}")
    # 关键断言：滚动范围必须贴合当前页内容（不允许被长页撑出大片空白）
    sb2 = win.chat_scroll.verticalScrollBar()
    ck("R5 短会话滚动范围不为大片空白", sb2.maximum() < 400,
       f"max={sb2.maximum()}（被长页撑高则远超内容高度）")
    # 短会话里发送 → 必须出现在视口内（不落到撑出来的空白区）
    win.bridge.send_text = fake_send_text
    win.input_edit.setPlainText("短会话里的发送")
    win._send_input()
    settle()
    ok, why = last_bubble_visible(win)
    ck("R5 短会话发送后新气泡在视口内", ok, why)
    n5 = count_occurrences(win, "短会话里的发送")
    ck("R5 短会话发送只出现一次", n5 == 1, f"出现 {n5} 次")

    print(f"\n{N - len(FAILS)}/{N} passed")
    if FAILS:
        for f in FAILS:
            print("  FAIL:", f)
        sys.exit(1)


if __name__ == "__main__":
    main()
