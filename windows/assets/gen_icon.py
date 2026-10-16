# -*- coding: utf-8 -*-
"""生成应用图标 icon.ico（多尺寸）"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QPainter, QColor, QPolygonF, QLinearGradient, QBrush, QIcon

app = QApplication(sys.argv)


def make_pixmap(size):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    m = int(size * 0.04)
    grad = QLinearGradient(m, m, size - m, size - m)
    grad.setColorAt(0, QColor("#3b82f6"))
    grad.setColorAt(1, QColor("#06b6d4"))
    p.setBrush(QBrush(grad))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(m, m, size - 2 * m, size - 2 * m, size * 0.22, size * 0.22)
    poly = QPolygonF()
    for x, y in [(0.56, 0.16), (0.30, 0.55), (0.47, 0.55), (0.40, 0.86),
                 (0.70, 0.44), (0.52, 0.44), (0.62, 0.16)]:
        poly.append(__import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(x * size, y * size))
    p.setBrush(QColor("white"))
    p.drawPolygon(poly)
    p.end()
    return pm


out = os.path.join(os.path.dirname(__file__), "icon.ico")
icon = QIcon()
for s in (16, 24, 32, 48, 64, 128, 256):
    icon.addPixmap(make_pixmap(s))
ok = icon.pixmap(256).save(out, "ICO")
print("ICON_OK" if ok else "ICON_FAIL", out)
