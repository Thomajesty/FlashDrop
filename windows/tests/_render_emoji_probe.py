# -*- coding: utf-8 -*-
"""实际渲染 EmojiPanel，量出真实图标可视尺寸（定位 26px 为何只显示 14px）。"""
import os
import sys

os.environ.pop("QT_QPA_PLATFORM", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QPushButton

app = QApplication.instance() or QApplication([])
f = QFont("Microsoft YaHei UI")
f.setPixelSize(13)
app.setFont(f)

import app.ui.emoji as E
from app.ui.theme import resolve_theme

print("=" * 70)
print("EmojiPanel 类常量")
print("=" * 70)
for k in ("COLS", "CELL", "ICON_PAD", "GRID_ROWS", "SIDE_PAD", "RECENT_STRIP"):
    print("  %-14s = %s" % (k, getattr(E.EmojiPanel, k, "N/A")))
print("  → setIconSize 尺寸 = CELL - ICON_PAD = %d px"
      % (E.EmojiPanel.CELL - E.EmojiPanel.ICON_PAD))

for theme_name in ("light", "dark"):
    T = resolve_theme(theme_name)
    pnl = E.EmojiPanel(None, T)
    pnl.resize(pnl.sizeHint())
    app.processEvents()
    pm = pnl.grab()
    out = os.path.join(ROOT, "tests", "_v11814",
                       "rendered_%s.png" % theme_name)
    pm.save(out)
    print()
    print("[%s] 面板渲染尺寸 = %d x %d  -> %s"
          % (theme_name, pm.width(), pm.height(), out))

    # 量第一颗表情的可见外接框
    img = pm.toImage()
    W, H = img.width(), img.height()
    # 找网格区第一行：从顶部往下第一片「多彩像素」密集的行
    def colorful(x, y):
        c = img.pixelColor(x, y)
        r, g, b = c.red(), c.green(), c.blue()
        return max(r, g, b) - min(r, g, b) > 40
    rows = [sum(1 for x in range(W) if colorful(x, y)) for y in range(H)]
    mx = max(rows)
    band = None
    cur = None
    for y, v in enumerate(rows):
        if v > mx * 0.3:
            if cur is None:
                cur = y
        else:
            if cur is not None:
                band = (cur, y)
                break
    if band:
        y0, y1 = band
        xs = [x for x in range(W)
              if any(colorful(x, y) for y in range(y0, y1))]
        # 第一颗的横向范围
        groups, cur = [], None
        prev = None
        for x in xs:
            if cur is None:
                cur = x
            elif x - prev > 6:
                groups.append((cur, prev))
                cur = x
            prev = x
        if cur is not None:
            groups.append((cur, prev))
        if groups:
            g0, g1 = groups[0]
            print("  第1行带 y=%d~%d" % (y0, y1))
            print("  第1颗表情横向 x=%d~%d → 宽 %d px" % (g0, g1, g1 - g0 + 1))
            print("  第1行可见高度 = %d px" % (y1 - y0))
            print("  同列数（本行）= %d" % len(groups))
