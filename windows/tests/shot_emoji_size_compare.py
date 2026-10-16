# -*- coding: utf-8 -*-
"""v1.18.12 用户第 2 条验收：电脑端表情**放大前后对比**。

产出 tests/emoji_size_compare.png：
  左 = 旧尺寸（CELL=36 / icon 26px）
  右 = 新尺寸（CELL=44 / icon 36px）
同一张源图、同一主题，直接像素并排，便于判断"能不能看清"。
"""
import os
import sys

os.environ.pop("QT_QPA_PLATFORM", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter, QColor
from PySide6.QtWidgets import (QApplication, QFrame, QGridLayout, QLabel,
                               QToolButton, QVBoxLayout, QWidget)

app = QApplication.instance() or QApplication([])
f = QFont("Microsoft YaHei UI")
f.setPixelSize(13)
app.setFont(f)

OUT = os.path.join(ROOT, "tests", "emoji_size_compare.png")
IMG_DIR = os.path.join(ROOT, "assets", "fluent_emoji")

# 取前 24 个（按目录序，风格一致）
files = sorted(os.listdir(IMG_DIR))[:24]

from app.ui.theme import resolve_theme
T = resolve_theme("dark")


def make_grid(cell: int, pad: int) -> QWidget:
    w = QWidget()
    w.setStyleSheet("background:%s;" % T["window"])
    g = QGridLayout(w)
    g.setContentsMargins(10, 10, 10, 10)
    g.setSpacing(2)
    for i, fn in enumerate(files):
        b = QToolButton()
        b.setFixedSize(cell, cell)
        b.setAutoRaise(True)
        b.setIconSize(QSize(cell - pad, cell - pad))
        pm = QPixmap(os.path.join(IMG_DIR, fn))
        if not pm.isNull():
            b.setIcon(QIcon(pm))
        g.addWidget(b, i // 8, i % 8)
    return w


def title(text, color):
    lb = QLabel(text)
    lb.setStyleSheet("color:%s;font-size:13px;font-weight:bold;" % color)
    return lb


root = QWidget()
root.setStyleSheet("background:%s;" % T["window"])
v = QVBoxLayout(root)
v.setContentsMargins(14, 12, 14, 14)
v.setSpacing(6)

v.addWidget(title("旧：CELL=36 · 图标 26px（看不清）", "#F59E0B"))
v.addWidget(make_grid(36, 10))
v.addSpacing(10)
v.addWidget(title("新：CELL=44 · 图标 36px（可视面积 ≈1.9 倍）", "#22C55E"))
v.addWidget(make_grid(44, 8))

root.adjustSize()
root.show()
for _ in range(12):
    app.processEvents()
pm = root.grab()
pm.save(OUT)
print("对比图:", pm.width(), "x", pm.height(), "->", OUT)

QTimer.singleShot(100, app.quit)
app.exec()
