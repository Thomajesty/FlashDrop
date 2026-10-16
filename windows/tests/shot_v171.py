# -*- coding: utf-8 -*-
"""v1.7.1 可视化验收：用真实窗口（windows 平台插件）渲染三张验收截图。

1) shot_main.png   —— 主界面含"⏳ 待发送"气泡（勾选离线设备发文件）
2) shot_dialog.png —— 设置对话框（网络加密复选框取色修复效果，深/浅两套）
数据全部写入独立临时目录，不污染真实数据。
"""
import os
import sys
import time
import tempfile

os.environ.pop("QT_QPA_PLATFORM", None)  # 必须真实平台插件，否则 grab 无意义
_TMP = tempfile.mkdtemp(prefix="fd_shot_")
os.environ["FLASHDROP_DATA_DIR"] = _TMP

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

from app.config import Config
from app.node import FlashNode
from app.ui.main_window import MainWindow

OUT = os.path.dirname(os.path.abspath(__file__))

app = QApplication(sys.argv)
cfg = Config()
node = FlashNode(cfg)
node.start()
win = MainWindow(cfg, node)
win.resize(1120, 760)
win.show()

# 注入一个"离线设备"，模拟用户勾选了它然后发文件
OFFLINE = {
    "id": "deadbeefdeadbeefdeadbeefdeadbeef",
    "name": "我的旧手机",
    "host": "192.168.1.77",
    "ips": ["192.168.1.77"],
    "online": False,
    "last": int(time.time() * 1000),
}
win.peers[OFFLINE["id"]] = OFFLINE
# _on_peers 会在下一次 peers 刷新时覆盖 peers，所以直接构造含离线设备的列表
_real_peers = [
    {"id": OFFLINE["id"], "name": OFFLINE["name"], "platform": "android",
     "ips": OFFLINE["ips"], "online": False, "last": OFFLINE["last"]},
    {"id": "0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f", "name": "同事的笔记本",
     "platform": "windows", "ips": ["192.168.1.23"], "online": False,
     "last": int(time.time() * 1000) - 60000},
]
win._on_peers(_real_peers)

# 构造一条真实待发送记录
_real = os.path.join(_TMP, "现场照片.jpg")
with open(_real, "wb") as f:
    f.write(b"\xff\xd8\xff\xe0" + b"demo" * 64)
win._queue_files([_real], [OFFLINE["id"]])

# 切到该离线设备的视图，验证单设备视图下待发送气泡同样可见
win.device_list.setCurrentRow(1)
for _ in range(40):
    app.processEvents()
    time.sleep(0.05)


def shot_main():
    win.grab().save(os.path.join(OUT, "shot_main.png"))
    print("SAVED shot_main.png")

    # 打开设置对话框（不阻塞：直接 show 而非 exec），截网络页的网络加密复选框
    from PySide6.QtWidgets import QTabWidget
    from app.ui.main_window import SettingsDialog

    def snap(dlg, fname):
        for _ in range(40):
            app.processEvents()
            time.sleep(0.03)
        dlg.grab().save(os.path.join(OUT, fname))
        print("SAVED", fname)

    # ---------- 深色主题 ----------
    win.cfg["theme"] = "dark"
    win._apply_theme()
    dlg = SettingsDialog(win.cfg, win)
    dlg.resize(560, 660)
    dlg.show()
    tabs = dlg.findChild(QTabWidget)
    tabs.setCurrentIndex(2)          # "网络"页 —— 网络加密复选框在这里
    snap(dlg, "shot_dlg_network_dark.png")
    dlg.close()

    # ---------- 浅色主题 ----------
    win.cfg["theme"] = "light"
    win._apply_theme()
    for _ in range(40):
        app.processEvents()
        time.sleep(0.03)
    dlg2 = SettingsDialog(win.cfg, win)
    dlg2.resize(560, 660)
    dlg2.show()
    dlg2.findChild(QTabWidget).setCurrentIndex(2)
    snap(dlg2, "shot_dlg_network_light.png")
    dlg2.close()
    app.quit()


QTimer.singleShot(2500, shot_main)
QTimer.singleShot(20000, app.quit)
app.exec()
print("DONE")