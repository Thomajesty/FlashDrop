# -*- coding: utf-8 -*-
"""用真实 Windows 平台（非 offscreen）渲染表情面板，确认中文页签正常显示。"""
import os
import sys

# 关键：不设 QT_QPA_PLATFORM=offscreen，用真实 windows 平台
os.environ.pop("QT_QPA_PLATFORM", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

import tempfile
tmp = tempfile.mkdtemp(prefix="fd_real_")
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
for _ in range(8):
    app.processEvents()

win.emoji_btn.click()
for _ in range(12):
    app.processEvents()

pnl = win.emoji_btn._panel
pnl.grab().save(os.path.join(OUT, "real_emoji_panel_%s.png" % theme))

# 切到「人物」分类再截一张
pnl._show_group("People & Body")
for _ in range(8):
    app.processEvents()
pnl.grab().save(os.path.join(OUT, "real_emoji_panel2_%s.png" % theme))

win.input_panel.grab().save(os.path.join(OUT, "real_emoji_bar_%s.png" % theme))
print("saved real_emoji_panel_%s.png / panel2 / bar" % theme)
win.close()
