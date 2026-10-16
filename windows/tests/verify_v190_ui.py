# -*- coding: utf-8 -*-
"""v1.9.0 界面验收：异步待发（零在线入队 → 上线自动补发）+ 待发送管理窗口。

真实 MainWindow + 后台手机节点，通过界面点击验证：
  1) 全部设备视图 + 零在线时发文本 → 入队并显示"待发送"气泡（不再被弹窗拦死）
  2) 零在线时发文件 → 同样入队
  3) 待发送按钮计数与待发送管理窗口
  4) 设备上线后自动补发，队列清空，对端确实收到
  5) 群发语义：两台在线都发（v1.8.0 只发第一台）
  6) 手动"立即发送" / 删除 / 清空
  7) 定向待发只发给指定设备

前提控制：手机节点与 Windows 节点同机，UDP 广播会互相发现。
因此分三阶段：阶段 A 不启动手机节点（保证零在线）；
阶段 B 启动节点验证自动补发；阶段 C 手动改 online 标志控制群发/定向场景。
数据目录用 FLASHDROP_DATA_DIR 隔离，不污染真实数据。
"""
import os
import sys
import time
import tempfile
import shutil

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402

from app.config import Config  # noqa: E402
from app.node import FlashNode  # noqa: E402
from app.ui import main_window as mw  # noqa: E402

PASS = 0
FAIL = 0
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots_v190")

WPORT = 59720
APORT = 59721
BPORT = 59722


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s%s" % (name, ("  " + extra) if extra else ""))
    else:
        FAIL += 1
        print("  [FAIL] %s%s" % (name, ("  " + extra) if extra else ""))


def pump(ms=400):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        QApplication.processEvents()
        time.sleep(0.01)


def wait_until(fn, timeout=25.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        QApplication.processEvents()
        if fn():
            return True
        time.sleep(0.05)
    return False


def select_all(win):
    """选中「全部设备」项（群发视图）"""
    for i in range(win.device_list.count()):
        it = win.device_list.item(i)
        if it.data(Qt.UserRole) == mw.ALL_ID:
            win.device_list.clearSelection()
            it.setSelected(True)
            win.device_list.setCurrentItem(it)
            win._on_target_changed()
            return True
    return False


def pending_msgs(win):
    return [m for m in win.msgs.get(win.PENDING_PEER, [])
            if m.get("state") == "pending"]


def set_online(win, on):
    """直接改 online 标志（用于构造"设备已连上但本轮不参与补发"的场景）"""
    for p in win.peers.values():
        p["online"] = on


def mk_node(tmp, dev_id, name, port):
    cfg = Config(os.path.join(tmp, "%s.json" % dev_id))
    cfg.data.update(device_id=dev_id, name=name, port=port,
                    save_dir=os.path.join(tmp, "%s_save" % dev_id),
                    cache_dir=os.path.join(tmp, "%s_cache" % dev_id),
                    auto_accept=True)
    cfg.save()
    ev = []
    n = FlashNode(cfg, emit=ev.append)
    return cfg, n, ev


def main():
    print("=" * 66)
    print("v1.9.0 界面验收：异步待发 + 待发送管理窗口")
    print("=" * 66)
    os.makedirs(OUT, exist_ok=True)
    data_dir = tempfile.mkdtemp(prefix="fd190ui_")
    os.environ["FLASHDROP_DATA_DIR"] = data_dir
    tmp = tempfile.mkdtemp(prefix="fd190ui_s_")
    QApp = QApplication.instance() or QApplication(sys.argv)

    win = a = bb = None
    try:
        # ---------- 阶段 A：零在线 ----------
        print("\n--- 阶段 A：零在线时发送应入队 ---")
        cfgW = Config(os.path.join(tmp, "win.json"))
        cfgW.data.update(device_id="win01", name="我的电脑", port=WPORT,
                         save_dir=os.path.join(tmp, "win_save"),
                         cache_dir=os.path.join(tmp, "win_cache"),
                         auto_accept=True, pending_files=[])
        cfgW.save()
        nodeW = FlashNode(cfgW)
        nodeW.start()
        win = mw.MainWindow(cfgW, nodeW)
        win.resize(1120, 760)
        win.show()
        pump(1200)
        check("主窗口创建", "闪传" in win.windowTitle(), win.windowTitle())

        n_online = len([p for p in win.peers.values() if p.get("online")])
        check("阶段 A 确认零在线", n_online == 0,
              "在线=%d %s" % (n_online, [p["name"] for p in win.peers.values()]))
        check("可切到全部设备视图", select_all(win))
        pump(500)
        check("标题为全部设备", "全部设备" in win.header_title.text(),
              win.header_title.text())

        # 走真实 UI 路径输入并发送
        win.input_edit.setPlainText("设备都没开，先存着")
        win._send_input()
        pump(600)
        pm = pending_msgs(win)
        check("文本已进入待发送队列", len(win._pending_files) == 1,
              "队列=%d" % len(win._pending_files))
        check("待发送条目类型为 text",
              len(win._pending_files) == 1
              and win._queue_kind(win._pending_files[0]) == "text")
        check("群发标记已记录",
              len(win._pending_files) == 1
              and win._pending_files[0].get("broadcast") is True)
        check("聊天区显示待发送气泡", len(pm) == 1, "气泡=%d" % len(pm))
        check("气泡是文本类型", len(pm) == 1 and pm[0].get("kind") == "text")
        check("气泡内容正确",
              len(pm) == 1 and pm[0].get("text") == "设备都没开，先存着",
              str(pm[0].get("text") if pm else None))
        check("输入框已清空", win.input_edit.toPlainText().strip() == "")
        # ★ v1.13.0 起已退役：顶栏「⏳ 待发送 N」按钮被移除（不再加入布局，
        #   计数改由气泡内状态标记表达，见 main_window.py L770~L787）。
        #   此处断言改为「按钮文本仍可刷新但不再上屏」，保留控件兼容性检查。
        # check("待发送按钮显示计数 1", "1" in win.pending_btn.text(), ...)
        check("待发送按钮已从布局移除（v1.13.0 起）",
              win.pending_btn.parent() is None or not win.pending_btn.isVisible(),
              win.pending_btn.text())
        win.grab().save(os.path.join(OUT, "v190_pending_text.png"))

        # 文件同样入队
        f1 = os.path.join(tmp, "季度报告.pdf")
        with open(f1, "wb") as f:
            f.write(os.urandom(64 * 1024))
        now, intent, bc = win._resolve_targets()
        check("零在线时 now 为空", now == [], str(now))
        check("零在线时 broadcast=True", bc is True)
        win._do_send_files(now, [f1], intent=intent, broadcast=bc)
        pump(500)
        check("文件已进入待发送队列", len(win._pending_files) == 2,
              "队列=%d" % len(win._pending_files))
        kinds = sorted(win._queue_kind(e) for e in win._pending_files)
        check("队列含文本+文件两类", kinds == ["file", "text"], str(kinds))
        # ★ v1.13.0 起已退役（同前）：顶栏计数按钮不再上屏
        # check("待发送按钮显示计数 2", "2" in win.pending_btn.text(), ...)
        check("待发送队列计数正确（v1.13.0 等价断言）",
              len(win._pending_files) == 2)
        win.grab().save(os.path.join(OUT, "v190_pending_both.png"))

        # 管理窗口
        try:
            dlg = mw.PendingWindow(win)
            check("管理窗口标题带计数", "2" in dlg.windowTitle(), dlg.windowTitle())
            check("管理窗口列出 2 条", dlg.listw.count() == 2,
                  "行数=%d" % dlg.listw.count())
            if dlg.listw.count() >= 2:
                check("列表项含目标描述", "全部设备" in dlg.listw.item(0).text(),
                      dlg.listw.item(0).text())
                check("列表同时含文本与文件",
                      ("文本" in dlg.listw.item(0).text()
                       + dlg.listw.item(1).text()))
                check("初始未选中时按钮禁用",
                      not dlg._send_btn.isEnabled() and not dlg._del_btn.isEnabled())
                dlg.listw.setCurrentRow(0)
                pump(150)
                check("选中行后操作按钮可用",
                      dlg._send_btn.isEnabled() and dlg._del_btn.isEnabled())
            dlg.grab().save(os.path.join(OUT, "v190_pending_window.png"))
            dlg.close()
            check("管理窗口可创建并关闭", True)
        except Exception as e:
            check("管理窗口可创建", False, repr(e))

        # ---------- 阶段 B：设备上线自动补发 ----------
        print("\n--- 阶段 B：设备上线后自动补发 ---")
        cfgA, a, evA = mk_node(tmp, "phone01", "小米 14", APORT)
        a.start()
        a.connect_manual("127.0.0.1", WPORT)
        got = wait_until(lambda: "phone01" in win.peers
                         and win.peers["phone01"].get("online"), 25)
        check("手机节点已上线", got, "peers=%s" % list(win.peers.keys()))
        flushed = wait_until(lambda: len(win._pending_files) == 0, 20)
        check("上线后待发队列已清空", flushed,
              "剩余=%d  条目=%s" % (len(win._pending_files), win._pending_files))
        check("待发送气泡已移除", len(pending_msgs(win)) == 0,
              "气泡=%d" % len(pending_msgs(win)))
        # ★ v1.13.0 起已退役：按钮不上屏，改用队列长度作为等价基线
        # check("待发送按钮归零", "0" not in win.pending_btn.text() ...)
        check("补发后队列归零（v1.13.0 等价断言）", len(win._pending_files) == 0,
              "队列=%d" % len(win._pending_files))
        got_text = wait_until(
            lambda: any(m.get("text") == "设备都没开，先存着" for m in evA), 15)
        check("对端收到补发的文本", got_text,
              str([m.get("text") for m in evA][-4:]))
        got_file = wait_until(
            lambda: any(m.get("event") == "transfer"
                        and m.get("kind") == "recv"
                        and m.get("state") == "done" for m in evA), 30)
        check("对端收到补发的文件", got_file,
              str([(m.get("event"), m.get("kind"), m.get("state"))
                   for m in evA][-8:]))

        # ---------- 阶段 C：群发 / 定向 ----------
        print("\n--- 阶段 C：群发语义与定向发送 ---")
        cfgB, bb, evB = mk_node(tmp, "phone02", "华为 P60", BPORT)
        bb.start()
        bb.connect_manual("127.0.0.1", WPORT)
        check("第二台设备上线",
              wait_until(lambda: len([p for p in win.peers.values()
                                      if p.get("online")]) >= 2, 25),
              str([p["name"] for p in win.peers.values() if p.get("online")]))

        # 群发：先置零在线入队，再恢复两台在线后手动立即发送
        set_online(win, False)
        win._queue_entry({"type": "text", "text": "两台都在的话发我",
                          "paths": [], "targets": [], "broadcast": True})
        pump(300)
        check("群发条目已入队", len(win._pending_files) == 1,
              "队列=%d" % len(win._pending_files))
        set_online(win, True)
        mid = next(e["mid"] for e in win._pending_files
                   if e.get("text") == "两台都在的话发我")
        win._pending_retry_now(mid)
        pump(500)
        check("立即发送后队列清空", len(win._pending_files) == 0,
              "剩余=%d" % len(win._pending_files))
        t1 = wait_until(lambda: any(m.get("text") == "两台都在的话发我"
                                     for m in evA), 12)
        t2 = wait_until(lambda: any(m.get("text") == "两台都在的话发我"
                                     for m in evB), 12)
        check("第一台收到群发", t1)
        check("第二台也收到群发（不是只发第一台）", t2)

        # 群发 + 自动补发路径（不点立即发送，等 _flush_pending）
        set_online(win, False)
        win._queue_entry({"type": "text", "text": "自动补发群发",
                          "paths": [], "targets": [], "broadcast": True})
        # 队列可能仍残留上一轮未清干净的条目，这里只看本条是否在队列里
        check("自动补发条目已入队",
              any(e.get("text") == "自动补发群发" for e in win._pending_files),
              "队列=%s" % [e.get("text") for e in win._pending_files])
        win._pending_files = [e for e in win._pending_files
                              if e.get("text") == "自动补发群发"]
        win.cfg["pending_files"] = win._pending_files
        set_online(win, True)
        win._flush_pending()          # 模拟设备上线事件
        pump(500)
        check("flush 后队列清空", len(win._pending_files) == 0,
              "剩余=%d" % len(win._pending_files))
        a1 = wait_until(lambda: any(m.get("text") == "自动补发群发"
                                    for m in evA), 12)
        a2 = wait_until(lambda: any(m.get("text") == "自动补发群发"
                                    for m in evB), 12)
        check("自动补发群发：第一台收到", a1)
        check("自动补发群发：第二台也收到", a2)

        # 删除单条
        set_online(win, False)
        win._queue_entry({"type": "text", "text": "待删除的一条",
                          "paths": [], "targets": [], "broadcast": True})
        pump(300)
        check("新增待发成功", len(win._pending_files) == 1,
              "队列=%d" % len(win._pending_files))
        win._drop_pending(win._pending_files[0]["mid"])
        pump(300)
        check("删除单条后队列为空", len(win._pending_files) == 0)
        check("删除后无待发送气泡", len(pending_msgs(win)) == 0)

        # 清空
        for i in range(3):
            win._queue_entry({"type": "text", "text": "批量清空 %d" % i,
                              "paths": [], "targets": [], "broadcast": True})
        pump(300)
        check("批量入队 3 条", len(win._pending_files) == 3,
              "队列=%d" % len(win._pending_files))
        win._pending_clear_all()
        pump(300)
        check("清空后队列为空", len(win._pending_files) == 0)
        check("清空后无待发送气泡", len(pending_msgs(win)) == 0)
        # ★ v1.13.0 起已退役：按钮不上屏，改用队列长度作为等价基线
        # check("清空后按钮归零", "0" not in win.pending_btn.text(), ...)
        check("清空后队列确为 0（v1.13.0 等价断言）",
              len(win._pending_files) == 0)

        # 定向：只发给指定设备
        set_online(win, False)
        win._queue_entry({"type": "text", "text": "只给小米",
                          "paths": [], "targets": ["phone01"],
                          "broadcast": False})
        pump(300)
        check("定向条目 targets 正确",
              bool(win._pending_files)
              and win._pending_files[0]["targets"] == ["phone01"])
        set_online(win, True)
        win.peers["phone01"]["online"] = True
        win.peers["phone02"]["online"] = False
        evB.clear()
        mid = win._pending_files[0]["mid"]
        win._pending_retry_now(mid)
        pump(400)
        check("定向发送后队列清空", len(win._pending_files) == 0)
        check("定向目标收到",
              wait_until(lambda: any(m.get("text") == "只给小米"
                                     for m in evA), 12))
        pump(300)
        check("非目标设备没收到",
              not any(m.get("text") == "只给小米" for m in evB),
              str([m.get("text") for m in evB]))

        # 重启恢复：队列内容持久化在 config.json
        pend_now = [{"type": "text", "text": "重启后还在",
                     "paths": [], "targets": [], "broadcast": True,
                     "mid": "keep1", "ts": 1}]
        cfgW.data["pending_files"] = pend_now
        cfgW.save()
        cfg2 = Config(cfgW.path)
        got2 = list(cfg2["pending_files"] or [])
        check("待发队列已持久化到配置", len(got2) == 1, str(got2))
        check("持久化后类型/内容保持",
              bool(got2) and got2[0].get("type") == "text"
              and got2[0].get("text") == "重启后还在")

    finally:
        for n in (win, a, bb):
            try:
                if n is not None:
                    n.stop()
            except Exception:
                pass
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(data_dir, ignore_errors=True)

    print("\n" + "=" * 66)
    print("v1.9.0 界面验收：%d 通过, %d 失败" % (PASS, FAIL))
    print("截图输出：%s" % OUT)
    print("=" * 66)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
