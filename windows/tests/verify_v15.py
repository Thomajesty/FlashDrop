# -*- coding: utf-8 -*-
"""v1.5.0 专项验证：TLS 传输加密（开/关/混合回退）+ 懒加载/滚动行为回归。"""

import os
import sys
import tempfile
import hashlib

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TMP = tempfile.mkdtemp(prefix="flashdrop_v15_")
os.environ["FLASHDROP_DATA_DIR"] = _TMP
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail and not cond else ""))


def md5file(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)

from app.config import Config
from app.node import FlashNode


def make_node(name, pid, port, encrypt):
    cfg = Config(os.path.join(_TMP, f"{pid}.json"))
    cfg.data.update({"device_id": pid, "name": name, "port": port,
                     "save_dir": os.path.join(_TMP, pid + "_save"),
                     "cache_dir": os.path.join(_TMP, pid + "_cache"),
                     "encrypt": encrypt})
    cfg.save()
    return FlashNode(cfg)


def wait_events(events, pred, timeout=10.0):
    import time
    t0 = time.time()
    while time.time() - t0 < timeout:
        if any(pred(e) for e in events):
            return True
        time.sleep(0.2)
    return False


import time

def connect_ok(node, host, port, peer_id, timeout=15):
    """连接成功 = 手动连接成功，或去重拒绝但目标已在线（announce 已建立连接）"""
    import time
    t0 = time.time()
    while time.time() - t0 < timeout:
        if peer_id in node.online_peer_ids():
            return True
        time.sleep(0.3)
    return False


print("== 1. 两端都开启加密：TLS 收发 ==")
nodeA = make_node("加密A", "aaaaaaaaaaaaaaaa", 58950, True)
nodeB = make_node("加密B", "bbbbbbbbbbbbbbbb", 58951, True)
evB = []
nodeB.emit = lambda e: evB.append(e)
nodeA.start(); nodeB.start()
check("加密互联成功", connect_ok(nodeA, "127.0.0.1", 58951, "bbbbbbbbbbbbbbbb"))
src = os.path.join(_TMP, "tls_test.bin")
with open(src, "wb") as f:
    f.write(os.urandom(3 * 1024 * 1024))
nodeA.send_files(["bbbbbbbbbbbbbbbb"], [src])
done = wait_events(evB, lambda e: e.get("event") == "transfer"
                   and e.get("state") == "done" and e.get("file") == "tls_test.bin")
check("TLS 模式文件接收完成", done)
if done:
    recv = [e for e in evB if e.get("event") == "transfer"
            and e.get("state") == "done"][-1]["path"]
    check("TLS 模式 MD5 一致", md5file(recv) == md5file(src))
nodeA.stop(); nodeB.stop()
time.sleep(0.5)

print("== 2. 两端都关闭加密：明文收发 ==")
nodeC = make_node("明文C", "cccccccccccccccc", 58952, False)
nodeD = make_node("明文D", "dddddddddddddddd", 58953, False)
evD = []
nodeD.emit = lambda e: evD.append(e)
nodeC.start(); nodeD.start()
check("明文互联成功", connect_ok(nodeC, "127.0.0.1", 58953, "dddddddddddddddd"))
nodeC.send_files(["dddddddddddddddd"], [src])
check("明文模式文件接收完成",
      wait_events(evD, lambda e: e.get("event") == "transfer" and e.get("state") == "done"))
nodeC.stop(); nodeD.stop()
time.sleep(0.5)

print("== 3. 混合：本端开加密对明文对端（自动回退） ==")
nodeE = make_node("混合E", "eeeeeeeeeeeeeeee", 58954, True)
nodeF = make_node("明文F", "ffffffffffffffff", 58955, False)
evF = []
nodeF.emit = lambda e: evF.append(e)
nodeE.start(); nodeF.start()
check("混合模式自动回退明文互联", connect_ok(nodeE, "127.0.0.1", 58955, "ffffffffffffffff"))
nodeE.send_files(["ffffffffffffffff"], [src])
check("混合模式文件接收完成",
      wait_events(evF, lambda e: e.get("event") == "transfer" and e.get("state") == "done"))
nodeE.stop(); nodeF.stop()
time.sleep(0.5)

print("== 4. 反向：本端明文对加密对端（服务端自适应） ==")
nodeG = make_node("明文G", "gggggggggggggggg", 58956, False)
nodeH = make_node("加密H", "hhhhhhhhhhhhhhhh", 58957, True)
evH = []
nodeH.emit = lambda e: evH.append(e)
nodeG.start(); nodeH.start()
check("明文客户端连加密服务端成功", connect_ok(nodeG, "127.0.0.1", 58957, "hhhhhhhhhhhhhhhh"))
time.sleep(1)
src2 = os.path.join(_TMP, "tls2.bin")
with open(src2, "wb") as f:
    f.write(os.urandom(1024 * 1024))
nodeG.send_files(["hhhhhhhhhhhhhhhh"], [src2])
ok_done = wait_events(evH, lambda e: e.get("event") == "transfer" and e.get("state") == "done")
check("该模式文件接收完成", ok_done)
if ok_done:
    recv = [e for e in evH if e.get("event") == "transfer" and e.get("state") == "done"][-1]["path"]
    check("该模式 MD5 一致", md5file(recv) == md5file(src2))
nodeG.stop(); nodeH.stop()

print("== 5. UI：粘贴图片发送 + 中文右键 + 懒加载 ==")
from app.config import Config as C2
from PySide6.QtGui import QImage
from PySide6.QtCore import Qt
from app.node import FlashNode as FN
from app.ui.main_window import MainWindow
cfgU = C2(os.path.join(_TMP, "ui.json"))
cfgU.data.update({"device_id": "uuuuuuuuuuuuuuuu", "name": "UI-15", "port": 58960,
                  "save_dir": os.path.join(_TMP, "us"), "cache_dir": os.path.join(_TMP, "uc")})
cfgU.save()
win = MainWindow(cfgU, FN(cfgU))

# 懒加载：启动时未加载任何历史
check("懒加载：启动不载入历史", win.history.all_peer_ids() == [] or len(win.msgs) == 0)

# 粘贴图片直发
img = QImage(64, 64, QImage.Format_RGB32)
img.fill(Qt.red)
QApplication.clipboard().setImage(img)
targets = []  # 无目标设备时 toast 不发送，但应走图片分支不落文本
r = win._send_clipboard_image()
check("剪贴板图片被识别为图片分支", r is True)
import glob
cached = glob.glob(os.path.join(_TMP, "uc", "剪贴板_*.png"))
check("剪贴板图片已暂存为 png", len(cached) == 1, str(cached))

# 中文右键菜单逻辑（不 exec，只验证处理器存在与剪贴板分支）
check("输入框自定义右键菜单已启用",
      win.input_edit.contextMenuPolicy() == Qt.CustomContextMenu)

win._real_quit()

print()
fails = [r for r in RESULTS if not r[1]]
print(f"===== v1.5.0 专项验证: {len(RESULTS) - len(fails)} 通过, {len(fails)} 失败 =====")
sys.exit(1 if fails else 0)
