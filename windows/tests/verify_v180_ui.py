# -*- coding: utf-8 -*-
"""v1.8.0 界面验收：Windows 端按设备切换会话 + 接收文件分设备文件夹（真实窗口截图）。

跑一个真实 MainWindow + 两个后台手机节点，通过界面点击验证：
  1) 侧栏点某台设备 → 聊天区只显示该设备的消息（会话隔离）
  2) 两台设备消息互不串台
  3) 接收文件落在 <save_dir>/<设备名>/
数据目录用 FLASHDROP_DATA_DIR 隔离，不污染真实数据。
"""
import os
import sys
import time
import tempfile
import hashlib
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
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots_v180")


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


def select_device(win, peer_id):
    """模拟真实单击：先清空原选中（否则会与"全部设备"叠加，_view_peer_ids 里
    ALL_ID 优先，导致视图不切换），再单选目标设备。"""
    for i in range(win.device_list.count()):
        it = win.device_list.item(i)
        if it.data(Qt.UserRole) == peer_id:
            win.device_list.clearSelection()
            it.setSelected(True)
            win.device_list.setCurrentItem(it)
            win._on_target_changed()
            return True
    return False


def texts_of(win):
    return [m.get("text", "") for m in win._visible_msgs() if m.get("kind") == "text"]


def main():
    print("=" * 66)
    print("v1.8.0 界面验收：按设备分会话 + 接收文件分设备文件夹")
    print("=" * 66)
    os.makedirs(OUT, exist_ok=True)
    data_dir = tempfile.mkdtemp(prefix="fd180ui_")
    os.environ["FLASHDROP_DATA_DIR"] = data_dir
    tmp = tempfile.mkdtemp(prefix="fd180ui_s_")
    QApp = QApplication.instance() or QApplication(sys.argv)

    win = a = b = None
    try:
        def mk_node(dev_id, name, port):
            cfg = Config(os.path.join(tmp, "%s.json" % dev_id))
            cfg.data.update(device_id=dev_id, name=name, port=port,
                            save_dir=os.path.join(tmp, "%s_save" % dev_id),
                            cache_dir=os.path.join(tmp, "%s_cache" % dev_id),
                            auto_accept=True)
            cfg.save()
            ev = []
            n = FlashNode(cfg, emit=ev.append)
            n.start()
            return cfg, n, ev

        cfgA, a, evA = mk_node("phone01", "小米: 14/Pro", 59521)
        cfgB, b, evB = mk_node("phone02", "华为 P60", 59522)
        cfgW = Config(os.path.join(tmp, "win.json"))
        cfgW.data.update(device_id="win01", name="我的电脑", port=59520,
                         save_dir=os.path.join(tmp, "win_save"),
                         cache_dir=os.path.join(tmp, "win_cache"), auto_accept=True)
        cfgW.save()
        nodeW = FlashNode(cfgW)
        nodeW.start()
        win = mw.MainWindow(cfgW, nodeW)
        win.resize(1120, 760)
        win.show()
        pump(900)
        check("主窗口标题", "闪传" in win.windowTitle(), win.windowTitle())

        # 让手机节点连上 Windows
        a.connect_manual("127.0.0.1", 59520)
        b.connect_manual("127.0.0.1", 59520)
        got = wait_until(lambda: "phone01" in win.peers and "phone02" in win.peers, 25)
        check("两台手机节点都被发现", got, "peers=%s" % list(win.peers.keys()))

        # --- 制造各设备独立历史 ---
        a.send_text(["win01"], "小米发来的消息")
        b.send_text(["win01"], "华为发来的消息")
        # 电脑侧必须走真实 UI 路径（bridge.send_text 只发不落历史，
        # 落历史由 MainWindow._out_text_msg 负责）
        win.input_edit.setPlainText("电脑发给小米")
        win.device_list.clearSelection()
        for i in range(win.device_list.count()):
            if win.device_list.item(i).data(Qt.UserRole) == "phone01":
                win.device_list.item(i).setSelected(True)
                win.device_list.setCurrentItem(win.device_list.item(i))
        win._on_target_changed()
        win._send_input()
        check("等待消息入列",
              wait_until(lambda: len(win._visible_msgs()) >= 1, 15))

        # --- 1) 单设备会话隔离 ---
        check("可点选小米设备", select_device(win, "phone01"))
        pump(800)
        check("标题切到该设备", "小米" in win.header_title.text(), win.header_title.text())
        t = texts_of(win)
        check("小米会话含小米消息", "小米发来的消息" in t, str(t))
        check("小米会话含电脑发给它的", "电脑发给小米" in t, str(t))
        check("小米会话不含华为消息", "华为发来的消息" not in t, str(t))
        shot1 = os.path.join(OUT, "v180_single_device.png")
        win.grab().save(shot1)
        check("单设备会话截图已保存", os.path.isfile(shot1))

        # --- 2) 切到另一台，验证不串台 ---
        check("可点选华为设备", select_device(win, "phone02"))
        pump(800)
        check("标题切到华为", "华为" in win.header_title.text(), win.header_title.text())
        t2 = texts_of(win)
        check("华为会话含华为消息", "华为发来的消息" in t2, str(t2))
        check("华为会话不含小米消息", "小米发来的消息" not in t2, str(t2))
        check("华为会话不含发给小米的消息", "电脑发给小米" not in t2, str(t2))
        shot2 = os.path.join(OUT, "v180_device_huawei.png")
        win.grab().save(shot2)

        # --- 3) 接收文件按设备分文件夹 ---
        src = os.path.join(tmp, "设计稿.png")
        data = os.urandom(120 * 1024)
        with open(src, "wb") as f:
            f.write(data)
        md5 = hashlib.md5(data).hexdigest()
        a.send_files(["win01"], [src])
        save_dir = cfgW.data["save_dir"]
        sub = os.path.join(save_dir, "小米_ 14_Pro")
        check("文件按设备名落到子目录", wait_until(
            lambda: os.path.isfile(os.path.join(sub, "设计稿.png")), 25), sub)
        check("未落在 save_dir 根目录（隔离生效）",
              not os.path.isfile(os.path.join(save_dir, "设计稿.png")))
        p = os.path.join(sub, "设计稿.png")
        if os.path.isfile(p):
            with open(p, "rb") as f:
                check("MD5 一致", hashlib.md5(f.read()).hexdigest() == md5)

        # 第二台设备的文件进另一个目录
        src2 = os.path.join(tmp, "华为资料.bin")
        with open(src2, "wb") as f:
            f.write(os.urandom(60 * 1024))
        b.send_files(["win01"], [src2])
        sub2 = os.path.join(save_dir, "华为 P60")
        check("第二台设备独立目录", wait_until(
            lambda: os.path.isdir(sub2) and os.path.isfile(
                os.path.join(sub2, "华为资料.bin")), 25), sub2)
        check("两台设备目录互不干扰",
              not os.path.isfile(os.path.join(sub, "华为资料.bin")))

        # --- 4) 全部设备视图 ---
        for i in range(win.device_list.count()):
            it = win.device_list.item(i)
            if it.data(Qt.UserRole) == mw.ALL_ID:
                it.setSelected(True)
                win.device_list.setCurrentItem(it)
                win._on_target_changed()
                break
        pump(1200)
        tall = texts_of(win)
        check("全部设备视图含全部消息", len(tall) >= 3, str(tall))
        check("全部视图标题", "全部设备" in win.header_title.text(), win.header_title.text())
        shot3 = os.path.join(OUT, "v180_all_devices.png")
        win.grab().save(shot3)
    finally:
        for x in (win, a, b):
            try:
                if x is not None:
                    x.close() if hasattr(x, "close") else x.stop()
            except Exception:
                pass
        try:
            nodeW.stop()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(data_dir, ignore_errors=True)

    print()
    print("截图输出目录: %s" % OUT)
    print("===== 结果: %d 通过, %d 失败 =====" % (PASS, FAIL))
    print("ALL_OK" if FAIL == 0 else "HAS_FAILURE")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
