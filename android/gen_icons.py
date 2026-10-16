# -*- coding: utf-8 -*-
"""生成 Android mipmap 启动图标 PNG"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "windows"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPixmap, QPainter, QColor, QPolygonF, QLinearGradient, QBrush

app = QApplication(sys.argv)
RES = os.path.join(os.path.dirname(__file__), "..", "android", "app", "src", "main", "res")


def make_pixmap(size):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    m = int(size * 0.08)
    grad = QLinearGradient(m, m, size - m, size - m)
    grad.setColorAt(0, QColor("#3b82f6"))
    grad.setColorAt(1, QColor("#06b6d4"))
    p.setBrush(QBrush(grad))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(m, m, size - 2 * m, size - 2 * m, size * 0.22, size * 0.22)
    poly = QPolygonF()
    for x, y in [(0.56, 0.20), (0.34, 0.54), (0.49, 0.54), (0.42, 0.82),
                 (0.68, 0.44), (0.52, 0.44), (0.60, 0.20)]:
        poly.append(QPointF(x * size, y * size))
    p.setBrush(QColor("white"))
    p.drawPolygon(poly)
    p.end()
    return pm


sizes = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}
for dpi, s in sizes.items():
    d = os.path.join(RES, f"mipmap-{dpi}")
    os.makedirs(d, exist_ok=True)
    ok = make_pixmap(s).save(os.path.join(d, "ic_launcher.png"), "PNG")
    print(dpi, s, "OK" if ok else "FAIL")
print("ICONS_DONE")
