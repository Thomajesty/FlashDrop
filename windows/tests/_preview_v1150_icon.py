# -*- coding: utf-8 -*-
"""v1.15.0 图标 + 文件卡片几何自检（离屏渲染出 PNG 供肉眼核对）

对照微信「文件传输助手」文件卡片：
  · 图标 44x50，矩形缺右下角
  · 卡片等宽 450，卡内左右各 12 内边距，图标左边距文字 14
  · 文件名严格两行 + 中间省略 + 保留扩展名
  · 大小与状态同一行
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont
from PySide6.QtWidgets import QApplication

from app.ui import widgets as wd
from app.ui.theme import DARK

OUT = os.path.join(os.path.dirname(__file__), "_out_v1150")
os.makedirs(OUT, exist_ok=True)


def render_icons():
    """把 12 类图标 + 虚化版排成一张图"""
    names = ["report.pdf", "plan.docx", "data.xlsx", "slides.pptx",
             "notes.txt", "photo.jpg", "movie.mp4", "backup.zip",
             "setup.exe", "font.ttf", "store.db", "image.iso", "unknown.xyz"]
    H, gap, pad = 50, 26, 20
    W = pad * 2 + len(names) * (44 + gap)
    pm = QPixmap(W, H + pad * 2 + 26)
    pm.fill(QColor("#111111"))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    x = pad
    for n in names:
        icon = wd.make_file_icon(n, H, False)
        p.drawPixmap(x, pad, icon)
        # 虚化版放下面
        dim = wd.make_file_icon(n, H, True)
        p.drawPixmap(x, pad, dim)
        x += 44 + gap
    p.end()
    pm.save(os.path.join(OUT, "icons_v1150.png"))

    # 单独一张：实色 + 虚化并排对比
    pm2 = QPixmap(44 * 6 + 20 * 7, H + 40)
    pm2.fill(QColor("#111111"))
    p2 = QPainter(pm2)
    p2.setRenderHint(QPainter.Antialiasing)
    x = 20
    for n in ["report.pdf", "plan.docx", "data.xlsx"]:
        p2.drawPixmap(x, 20, wd.make_file_icon(n, H, False))
        x += 44 + 20
    for n in ["report.pdf", "plan.docx", "data.xlsx"]:
        p2.drawPixmap(x, 20, wd.make_file_icon(n, H, True))
        x += 44 + 20
    p2.end()
    pm2.save(os.path.join(OUT, "icons_dim_compare.png"))


def render_card():
    """渲染两张文件卡片（长名 / 短名）验证等宽与两行截断"""
    msgs = [
        {"kind": "file", "dir": "out", "file": "甘肃国钛拆除、砌筑、安装技术附件20240117.pdf",
         "size": 2_458_112, "state": "done", "mime": "application/pdf"},
        {"kind": "file", "dir": "in", "file": "a.txt", "size": 1024,
         "state": "done", "mime": "text/plain", "path": __file__},
    ]
    W = 700
    pm = QPixmap(W, 300)
    pm.fill(QColor("#111111"))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    y = 20
    for m in msgs:
        card = QPixmap(450, 80)
        card.fill(Qt.transparent)
        cp = QPainter(card)
        cp.setRenderHint(QPainter.Antialiasing)
        cp.setBrush(QColor("#181818"))
        cp.setPen(Qt.NoPen)
        cp.drawRoundedRect(QRectF(0, 0, 450, 80), 8, 8)
        # 左文字区
        cp.setPen(QColor("#FFFFFF"))
        f = QFont("Microsoft YaHei UI")
        f.setPixelSize(14)
        f.setBold(True)
        cp.setFont(f)
        txt = wd.BubbleFrame._wrap_two_lines(m["file"], 24)
        cp.drawText(QRectF(12, 12, 368, 40), Qt.TextWordWrap | Qt.AlignTop, txt)
        f2 = QFont("Microsoft YaHei UI")
        f2.setPixelSize(11)
        cp.setFont(f2)
        cp.setPen(QColor("#9AA1AC"))
        cp.drawText(QRectF(12, 56, 368, 16), Qt.AlignTop,
                    "2.34 MB  已送达")
        # 右图标
        cp.drawPixmap(12 + 368 + 14, 15, wd.make_file_icon(m["file"], 50, False))
        cp.end()
        p.drawPixmap(20, y, card)
        # 标注卡宽
        p.setPen(QColor("#6B7280"))
        f3 = QFont("Microsoft YaHei UI")
        f3.setPixelSize(11)
        p.setFont(f3)
        p.drawText(20, y + 96, f"卡片宽 450px  |  内边距 12  |  图标 44x50  |  图标←文字 14")
        y += 120
    p.end()
    pm.save(os.path.join(OUT, "cards_v1150.png"))


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    render_icons()
    render_card()
    print("OK ->", OUT)
    print("  icons_v1150.png")
    print("  icons_dim_compare.png")
    print("  cards_v1150.png")


if __name__ == "__main__":
    main()
