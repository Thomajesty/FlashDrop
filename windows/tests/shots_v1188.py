# -*- coding: utf-8 -*-
"""v1.18.8 底部工具行按钮一致性 —— 真实渲染截图

离屏渲染 MainWindow 的输入面板区域，导出两张对比图：
  shots_v1188_light.png / shots_v1188_dark.png
并在图上标注每个按钮的实际像素高度，便于肉眼复核。
"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QPainter, QColor, QFont, QPen
from PySide6.QtWidgets import QApplication, QPushButton, QToolButton

app = QApplication.instance() or QApplication([])

import tempfile
tmp = tempfile.mkdtemp(prefix="fd_shot1188_")
os.environ["FLASHDROP_DATA_DIR"] = tmp

from app.config import Config
from app.node import FlashNode
from app.ui.main_window import MainWindow

OUT = os.path.dirname(os.path.abspath(__file__))

for theme in ("light", "dark"):
    cfg = Config()
    cfg["theme"] = theme
    cfg["save_dir"] = tmp
    win = MainWindow(cfg, FlashNode(cfg))
    win.resize(1080, 720)
    win.show()
    app.processEvents()
    app.processEvents()

    panel = win.input_panel
    pm = panel.grab()
    img = pm.toImage()

    # 收集按钮几何（相对 input_panel 坐标）
    items = []
    for b in panel.findChildren(QPushButton):
        if b.text() in ("📎 发送文件", "🖼 发送图片", "📋 发送剪贴板"):
            items.append((b.text(), b))
    for b in panel.findChildren(QToolButton):
        if "截图" in b.text() or b.text().strip() == "▾":
            items.append((f"[{b.objectName()}] {b.text()}", b))

    # 画标注
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    f = QFont("Microsoft YaHei UI"); f.setPixelSize(11); f.setBold(True)
    p.setFont(f)
    for label, b in items:
        tl = b.mapTo(panel, b.rect().topLeft())
        r = QRect(tl, b.size())
        p.setPen(QPen(QColor("#ef4444"), 2))
        p.drawRect(r.adjusted(0, 0, -1, -1))
        txt = f"h={r.height()}"
        p.setPen(QColor("#ef4444"))
        p.drawText(r.left(), r.top() - 4, txt)
        print(f"  [{theme}] {label}: x={r.left()} y={r.top()} "
              f"w={r.width()} h={r.height()}")
    p.end()

    out = os.path.join(OUT, f"shots_v1188_{theme}.png")
    pm.save(out, "PNG")
    print(f"  -> {out}  ({pm.width()}x{pm.height()})")
    win.close()

print("done")
