# -*- coding: utf-8 -*-
"""v1.18.18 行为测试 —— 设备备注 / 消息搜索 / 待发队列状态面板。

用户需求：
  · 设备备注（别名）：右键设备 → 起备注，仅本机显示，不影响对端自报名
  · 消息搜索：跨设备搜聊天内容与文件名，结果可跳转对应会话
  · 待发队列可视化面板：能看到失败原因 / 重试次数 / 重试中状态

★为什么必须真跑 GUI：
   静态断言只能证明"代码里有这些字"，证明不了"点下去真的生效"。
   项目里踩过 QSS 级联的坑（源码数值对、打包后渲染错），
   同理，"菜单项存在"也不等于"备注真的写进了配置并反映到列表"。

运行：python tests/verify_v11818_ui_features.py
"""
import os
import sys
import tempfile
import time

os.environ.pop("QT_QPA_PLATFORM", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QLabel

app = QApplication.instance() or QApplication([])

tmp = tempfile.mkdtemp(prefix="fd_v11818ui_")
SAVE = os.path.join(tmp, "save")
os.makedirs(SAVE, exist_ok=True)
os.environ["FLASHDROP_DATA_DIR"] = tmp

from app.config import Config
from app.node import FlashNode
from app.ui.main_window import MainWindow, SearchWindow, ALL_ID

P, F = [], []


def check(name, cond, detail=""):
    (P if cond else F).append(name)
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", name,
                          ("   " + detail) if (detail and not cond) else ""))


PEER_A = "aaaa111111111111"
PEER_B = "bbbb222222222222"


def pump(w, n=8):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.01)


def build():
    cfg = Config()
    cfg["theme"] = "light"
    cfg["save_dir"] = SAVE
    cfg["known_peers"] = {
        PEER_A: {"id": PEER_A, "name": "工作机", "platform": "windows",
                 "ips": ["192.168.1.2"], "last_seen": 0},
        PEER_B: {"id": PEER_B, "name": "PixelPhone", "platform": "android",
                 "ips": ["192.168.1.3"], "last_seen": 0},
    }
    cfg["pending_files"] = []
    cfg["peer_aliases"] = {}
    # ★ 必须开离线聊天：否则 known_peers 里的离线设备不会进列表，
    #   设备 A / B 根本不会有行（测试就会误报"设备不在列表中"）。
    cfg["offline_chat"] = True
    w = MainWindow(cfg, FlashNode(cfg))
    w.resize(1080, 720)
    w.show()
    pump(w)
    w._toast = lambda *a, **k: None          # 打桩 toast，避免模态提示
    # 设备列表靠节点推送刷新，测试里没有真实网络事件 -> 主动刷一次，
    # 否则 known_peers 里的设备不会变成列表行（会误报"设备不在列表中"）
    w._refresh_devices()
    pump(w, 4)
    return w, cfg


def select_peer(w, pid):
    """选中设备（不触发真实网络动作）"""
    w.device_list.blockSignals(True)
    w.device_list.clearSelection()
    for i in range(w.device_list.count()):
        it = w.device_list.item(i)
        if it.data(Qt.UserRole) == pid:
            it.setSelected(True)
            break
    w.device_list.blockSignals(False)
    w._on_target_changed()
    pump(w, 3)


def wait_search(dlg, timeout=8.0):
    """等搜索工作线程回填结果。

    ★ 不能只看 listw.count()：0 条结果也是"已完成"。
    可靠信号是 _loading 变 False（搜索结束）或出现结果条数。
    """
    t0 = time.time()
    while time.time() - t0 < timeout:
        app.processEvents()
        time.sleep(0.03)
        if not dlg._loading and "搜索中" not in (dlg.status.text() or ""):
            return True
    return False


def row_index(w, pid):
    for i in range(w.device_list.count()):
        if w.device_list.item(i).data(Qt.UserRole) == pid:
            return i
    return -1


# ============================ 1. 设备备注 ============================

def test_alias(w, cfg):
    print("\n[设备备注]")
    idx = row_index(w, PEER_A)
    check("设备 A 在列表中", idx >= 0)
    if idx < 0:
        return

    # --- 右键菜单里有备注入口 ---
    rect = w.device_list.visualItemRect(w.device_list.item(idx))
    menu = w._build_device_menu(rect.center())
    labels = [a.text() for a in menu.actions()] if menu else []
    check("右键菜单有备注入口",
          any("备注" in t for t in labels), str(labels))
    check("右键菜单有清除备注入口",
          any("清除备注" in t for t in labels), str(labels))

    # --- 起备注 ---
    w.bridge.node.set_alias(PEER_A, "主力机")
    check("备注写入配置", cfg["peer_aliases"].get(PEER_A) == "主力机",
          str(cfg["peer_aliases"]))
    check("display_name 优先备注",
          w._display_name(PEER_A) == "主力机", w._display_name(PEER_A))
    check("未备注设备用自报名",
          w._display_name(PEER_B) == "PixelPhone", w._display_name(PEER_B))

    # --- 列表刷新后显示备注 ---
    w._refresh_devices()
    pump(w, 3)
    texts = []
    for i in range(w.device_list.count()):
        wid = w.device_list.itemWidget(w.device_list.item(i))
        if wid is None:
            continue
        for lbl in wid.findChildren(QLabel):
            if lbl.text() == "主力机":
                texts.append(lbl.text())
    check("列表显示备注名", "主力机" in texts, str(texts))

    # --- 备注不改写自报名 ---
    snap = (w.peers.get(PEER_A) or {}).get("name")
    check("备注不改写自报名（不污染 peers）", snap == "工作机", str(snap))
    known = (cfg["known_peers"].get(PEER_A) or {}).get("name")
    check("备注不改写 known_peers 落盘值", known == "工作机", str(known))

    # --- 选为当前会话时顶栏标题用备注 ---
    select_peer(w, PEER_A)
    check("顶栏标题用备注", "主力机" in (w.header_title.text() or ""),
          w.header_title.text())

    # --- 清除备注 ---
    w._clear_peer_alias(PEER_A)
    pump(w, 2)
    check("清除备注后恢复自报名",
          w._display_name(PEER_A) == "工作机", w._display_name(PEER_A))
    check("清除后配置无残留", PEER_A not in (cfg["peer_aliases"] or {}),
          str(cfg["peer_aliases"]))

    # --- 删除设备会清掉备注（不留孤儿） ---
    w.bridge.node.set_alias(PEER_B, "临时代机")
    pump(w, 1)
    w._do_delete_peer(PEER_B)
    check("删设备同时清掉备注",
          PEER_B not in (cfg["peer_aliases"] or {}),
          str(cfg["peer_aliases"]))


# ============================ 2. 消息搜索 ============================

def test_search(w, cfg):
    print("\n[消息搜索]")
    w.history.clear(PEER_A)
    w.history.clear(PEER_B)
    now = int(time.time() * 1000)
    w.history.append(PEER_A, {"dir": "in", "text": "季度报表已经发你了",
                              "ts": now - 60000, "mid": "m1"})
    w.history.append(PEER_A, {"dir": "out", "text": "收到，我下午看",
                              "ts": now - 30000, "mid": "m2"})
    w.history.append(PEER_B, {"dir": "in", "text": "别忘了带发票",
                              "ts": now - 10000, "mid": "m3"})
    w.history.append(PEER_B, {"dir": "in", "file": "项目验收清单.xlsx",
                              "size": 1024, "ts": now - 5000, "mid": "m4"})
    time.sleep(0.2)

    dlg = SearchWindow(w, "")
    dlg.edit.setText("报表")
    dlg._do_search()
    wait_search(dlg)
    check("搜到文本命中", dlg.listw.count() == 1, f"count={dlg.listw.count()}")
    if dlg.listw.count():
        txt = dlg.listw.item(0).text()
        check("结果含命中片段", "报表" in txt, txt.replace("\n", " ")[:80])
        check("结果含设备名", "工作机" in txt, txt.replace("\n", " ")[:80])
        check("结果区分方向", "对方发来" in txt, txt.replace("\n", " ")[:80])
    check("状态栏显示条数", "1 条结果" in (dlg.status.text() or ""),
          dlg.status.text())

    # 文件名搜索
    dlg.edit.setText("验收清单")
    dlg._do_search()
    wait_search(dlg)
    check("可按文件名搜到", dlg.listw.count() == 1,
          f"count={dlg.listw.count()}")
    if dlg.listw.count():
        check("文件结果显示文件图标", "📎" in dlg.listw.item(0).text())

    # 跨设备（全部设备范围）
    dlg.edit.setText("我")
    dlg.scope_box.setCurrentIndex(0)
    dlg._do_search()
    wait_search(dlg)
    check("全部设备范围跨会话搜索", dlg.listw.count() >= 1,
          f"count={dlg.listw.count()}")

    # 无命中
    dlg.edit.setText("zzzz不存在")
    dlg._do_search()
    wait_search(dlg)
    check("无命中显示空态", dlg.listw.count() == 0
          and "没有找到" in (dlg.empty_lbl.text() or ""),
          dlg.empty_lbl.text())

    # 结果倒序（时间新→旧）
    dlg.edit.setText("e")             # 广撒网，制造多条命中
    dlg._do_search()
    wait_search(dlg)
    hits = dlg._hits
    ts = [h.get("ts") or 0 for h in hits]
    check("结果按时间倒序", ts == sorted(ts, reverse=True),
          str(ts[:6]))

    # 跳转：选第一条结果所在设备
    if dlg.listw.count():
        item = dlg.listw.item(0)
        pid = (item.data(Qt.UserRole) or ("", None))[0]
        ok = w._select_peer_by_id(pid)
        check("可跳转到结果所属设备", ok)
        sel = [i.data(Qt.UserRole) for i in w.device_list.selectedItems()]
        check("跳转后该设备被选中", sel == [pid], str(sel))
    dlg.close()

    # snippet 算法
    sn = w.history.snippet("前面很长的一段文字" * 5 + "关键词" + "后面很长" * 5,
                           "关键词")
    check("snippet 截取命中附近", "关键词" in sn and len(sn) < 80, sn)
    check("snippet 无命中时截断", w.history.snippet("abcdef", "zzz").startswith("abcdef"))

    # 空关键词不搜索
    check("空关键词返回空", w.history.search("  ") == [])


# ============================ 3. 待发队列状态面板 ============================

def test_pending_panel(w, cfg):
    print("\n[待发队列状态]")
    from app.ui.main_window import PendingWindow
    now = int(time.time() * 1000)
    w._pending_files = [
        {"type": "text", "text": "先看下这个方案", "paths": [],
         "targets": [PEER_B], "broadcast": False, "ts": now,
         "mid": "p1"},
        {"type": "file", "text": "", "paths": [os.path.join(SAVE, "a.bin")],
         "targets": [PEER_A], "broadcast": False, "ts": now - 1000,
         "mid": "p2", "attempt": 2,
         "last_error": "设备不在线"},
    ]
    dlg = PendingWindow(w)
    pump(dlg, 3)
    check("面板列出全部待发项", dlg.listw.count() == 2,
          f"count={dlg.listw.count()}")
    check("标题带计数", "2" in dlg.windowTitle(), dlg.windowTitle())

    joined = "\n".join(dlg.listw.item(i).text() for i in range(dlg.listw.count()))
    check("显示目标设备名（走备注）", "主力机" in joined or "工作机" in joined,
          joined.replace("\n", " ")[:120])

    # 有 last_error 的条目应能看到失败原因
    check("显示失败原因", "设备不在线" in joined,
          joined.replace("\n", " ")[:160])
    check("显示重试次数", "第 2 次" in joined or "2 次" in joined,
          joined.replace("\n", " ")[:160])
    dlg.close()


# ============================ 4. retrying / paused 状态文案 ============================

def test_resume_state_text(win):
    print("\n[重试/续传状态文案]")
    from app.ui.widgets import BubbleFrame
    # ★ 必须传窗口的真实 theme：BubbleFrame 渲染时要用 bubble_in 等键，
    #   传空 dict 会 KeyError（曾经在这里栽过）
    th = win.theme
    fb = BubbleFrame({"dir": "in", "file": "x.bin", "size": 1024,
                     "state": "retrying", "attempt": 2,
                     "reason": "连接中断"}, th)
    st = fb._status_text()
    check("retrying 显示重试次数", "第 2 次" in st, st)
    check("retrying 显示原因", "连接中断" in st, st)

    fb2 = BubbleFrame({"dir": "in", "file": "x.bin", "size": 1024,
                      "state": "paused", "have_chunks": 3, "total_chunks": 5},
                     th)
    st2 = fb2._status_text()
    check("paused 显示可续传", "续传" in st2, st2)
    check("paused 显示块进度", "3/5" in st2, st2)

    tb = BubbleFrame({"dir": "out", "text": "hi", "state": "retrying",
                     "attempt": 1}, th)
    txt = tb._status_text()
    check("文本 retrying 有文案", "重试" in txt, txt)


def main():
    print("=" * 70)
    print("v1.18.18 设备备注 / 消息搜索 / 待发队列状态（GUI 行为测试）")
    print("=" * 70)
    w = None
    try:
        w, cfg = build()
        test_alias(w, cfg)
        test_search(w, cfg)
        test_pending_panel(w, cfg)
        test_resume_state_text(w)
    except Exception:
        import traceback
        traceback.print_exc()
        F.append("异常")
    finally:
        try:
            os.environ["FLASHDROP_STOP"] = "1"
        except Exception:
            pass

    print("\n" + "=" * 70)
    print("结果：%d/%d 通过" % (len(P), len(P) + len(F)))
    if F:
        print("失败项：")
        for x in F:
            print("  - " + x)
    if F:
        # node 线程仍在跑，用 _exit 避免测试进程挂住
        os._exit(1)
    os._exit(0)


if __name__ == "__main__":
    main()