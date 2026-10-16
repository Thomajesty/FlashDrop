# -*- coding: utf-8 -*-
"""v1.18.13 用户第 1 条验收：电脑端表情面板「对齐微信」三联对比。

产出 tests/v11813_win_vs_wx.png：
  左  = 微信桌面版（实测截图，裁剪后等比）
  中  = FlashDrop v1.18.12（CELL=36 / 图标 26px / 顶部文字页签）
  右  = FlashDrop v1.18.13（CELL=44 / 图标 26px / 10 列 6 行 / 底部图标条）

微信实测（来自 _measure_wx_panel.py 等的量取结果）：
  面板 464 x 462、10 列、pitch 44、图标 23x23、可见 6 行
"""
import os
import sys

os.environ.pop("QT_QPA_PLATFORM", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QPushButton, QVBoxLayout, QWidget)

app = QApplication.instance() or QApplication([])
f = QFont("Microsoft YaHei UI")
f.setPixelSize(13)
app.setFont(f)

TESTS = os.path.join(ROOT, "tests")
IMG_DIR = os.path.join(ROOT, "assets", "fluent_emoji")
WX_SHOT = os.path.join(TESTS, "_wx", "wx_panel.png")
OUT = os.path.join(TESTS, "v11813_win_vs_wx.png")

from app.ui.theme import resolve_theme
T = resolve_theme("dark")

# 取目录前 60 个（10 列 x 6 行）
files = sorted(os.listdir(IMG_DIR))[:60]


def make_grid(cell: int, pad: int, cols: int = 10, rows: int = 6) -> QWidget:
    """按给定格子/内缩画一块纯网格，用于并排比尺寸。"""
    w = QWidget()
    w.setStyleSheet("background:%s;" % T["window"])
    g = QGridLayout(w)
    g.setContentsMargins(2, 2, 2, 2)
    g.setSpacing(0)
    for i, fn in enumerate(files[:cols * rows]):
        b = QPushButton()
        b.setFixedSize(cell, cell)
        b.setFlat(True)
        b.setStyleSheet("border:none;background:transparent;")
        b.setIconSize(QSize(cell - pad, cell - pad))
        pm = QPixmap(os.path.join(IMG_DIR, fn))
        if not pm.isNull():
            b.setIcon(QIcon(pm))
        g.addWidget(b, i // cols, i % cols)
    return w


def band(title: str, sub: str, widget: QWidget, width: int, height: int) -> QWidget:
    box = QWidget()
    v = QVBoxLayout(box)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(6)
    t = QLabel(title)
    t.setStyleSheet("color:%s;font-size:14px;font-weight:600;" % T["text"])
    s = QLabel(sub)
    s.setStyleSheet("color:%s;font-size:11px;" % T["text_dim"])
    v.addWidget(t)
    v.addWidget(s)
    holder = QFrame()
    holder.setFixedSize(width, height)
    holder.setStyleSheet(
        "background:%s;border:1px solid %s;border-radius:6px;"
        % (T["window"], T["border"]))
    hl = QHBoxLayout(holder)
    hl.setContentsMargins(0, 0, 0, 0)
    hl.addWidget(widget)
    v.addWidget(holder)
    v.addStretch(1)
    return box


def render(widget: QWidget) -> QPixmap:
    widget.show()
    app.processEvents()
    pm = widget.grab()
    widget.hide()
    return pm


# ---------- 三格尺寸 ----------
# 微信：464 宽面板，网格区高 6*44 = 264 左右（此处只比“格子+图标”观感）
WX_W, WX_H = 464, 300
OLD_W, OLD_H = 380, 300     # v1.18.12：面板更窄
NEW_W, NEW_H = 464, 300

panels = []

# ① 微信实拍
if os.path.exists(WX_SHOT):
    wxlab = QLabel()
    pm = QPixmap(WX_SHOT)
    pm = pm.scaledToWidth(WX_W, Qt.SmoothTransformation)
    wxlab.setPixmap(pm)
    wxlab.setFixedSize(WX_W, min(pm.height(), WX_H))
    panels.append(("① 微信桌面版（实拍）",
                   "464 宽 · 10 列 · pitch 44 · 图标 23px · 可见 6 行",
                   wxlab, WX_W, min(pm.height(), WX_H)))
else:
    panels.append(("① 微信桌面版（实拍缺失）",
                   "未找到 tests/_wx/wx_panel.png",
                   QLabel("缺少微信实拍图"), WX_W, WX_H))

# ② 旧版：CELL=36 / icon_pad=10 → 图标 26px，8 列
old = make_grid(36, 10, cols=8, rows=6)
old.setFixedSize(OLD_W, OLD_H)
panels.append(("② FlashDrop v1.18.12",
               "CELL 36 · 图标 26px · 8~9 列 · 面板 355 高",
               old, OLD_W, OLD_H))

# ③ 新版：CELL=44 / icon_pad=18 → 图标 26px，10 列 6 行
new = make_grid(44, 18, cols=10, rows=6)
new.setFixedSize(NEW_W, NEW_H)
panels.append(("③ FlashDrop v1.18.13（对齐微信）",
               "CELL 44 · 图标 26px · 10 列 · 可见 6 行 · 底部图标条",
               new, NEW_W, NEW_H))

row = QWidget()
hl = QHBoxLayout(row)
hl.setContentsMargins(14, 14, 14, 14)
hl.setSpacing(18)
for title, sub, w, ww, hh in panels:
    hl.addWidget(band(title, sub, w, ww, hh))

row.setStyleSheet("background:%s;" % T["window"])
row.setFixedSize(WX_W + OLD_W + NEW_W + 18 * 2 + 28 + 40, 420)

row.show()
app.processEvents()
img = row.grab()
row.hide()
img.save(OUT)
print("saved:", OUT, img.width(), "x", img.height())
