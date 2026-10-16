# -*- coding: utf-8 -*-
"""用真实屏幕截图（而非 widget.grab()）确认中文页签显示正常。

背景：Qt.Popup 顶层窗口在 QWidget.grab() 里走的是后备存储(lower-level)
      重绘路径，中文会退化成豆腐块。这不代表实际屏幕上也是这样。
      这里用 QScreen.grabWindow() 抓真实屏幕像素来验证。
"""
import os
import sys

os.environ.pop("QT_QPA_PLATFORM", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

import tempfile
tmp = tempfile.mkdtemp(prefix="fd_screen_")
os.environ["FLASHDROP_DATA_DIR"] = tmp

from app.config import Config
from app.node import FlashNode
from app.ui.main_window import MainWindow

OUT = os.path.dirname(os.path.abspath(__file__))
theme = sys.argv[1] if len(sys.argv) > 1 else "dark"

cfg = Config()
cfg["theme"] = theme
cfg["save_dir"] = tmp
win = MainWindow(cfg, FlashNode(cfg))
win.resize(1100, 740)
win.show()

state = {"n": 0}


def step():
    state["n"] += 1
    n = state["n"]
    for _ in range(6):
        app.processEvents()

    if n == 1:
        win.emoji_btn.click()
        for _ in range(10):
            app.processEvents()
        pnl = win.emoji_btn._panel
        # 用真实屏幕截取面板区域
        scr = pnl.screen()
        gp = pnl.mapToGlobal(QPoint(0, 0))
        dpr = scr.devicePixelRatio() or 1.0
        pm = scr.grabWindow(0, int(gp.x()), int(gp.y()),
                            pnl.width(), pnl.height())
        pm.save(os.path.join(OUT, "screen_emoji_panel_%s.png" % theme))
        print("  screen grab panel:", pm.width(), "x", pm.height(),
              "dpr=", dpr)

        # 整窗截图（含底部工具行）
        gp2 = win.mapToGlobal(QPoint(0, 0))
        pm2 = scr.grabWindow(0, int(gp2.x()), int(gp2.y()),
                             win.width(), win.height())
        pm2.save(os.path.join(OUT, "screen_emoji_full_%s.png" % theme))
        print("  screen grab window:", pm2.width(), "x", pm2.height())
        QTimer.singleShot(300, step)
        return

    print("done")
    win.close()
    app.quit()


QTimer.singleShot(700, step)
app.exec()
