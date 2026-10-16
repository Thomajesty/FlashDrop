# -*- coding: utf-8 -*-
"""
FlashDrop 截图取景器（v1.18.0 新增）

═══ 背景（用户要求）═══════════════════════════════════════════

用户原话：
  「截图功能应该能够框选  并且和微信一样 带下拉三角选择
    是否隐藏当前窗口」

原来（v1.16.0）的截图是"全屏直抓 + 固定隐藏窗口"：
  · 只能整屏，不能框选想要的区域；
  · 是否隐藏主窗口是写死的（先 hide 再延迟抓屏），用户无法选择 ——
    有时恰恰需要把 FlashDrop 窗口本身拍进去。

本模块实现"框选"这一半；"是否隐藏窗口"的下拉三角在主窗口侧
（见 main_window._screenshot_clicked / _screenshot_menu）。

═══ 交互设计（对齐微信 / QQ 截图）═══════════════════════════════

     ┌────────────────────────────────────────────────────┐
     │  冻结的整屏画面（半透明暗罩）                        │
     │                                                    │
     │      ┌───────────────────────┐  ← 拖动鼠标拉出选区   │
     │      │                       │                    │
     │      │       选区（高亮）      │                    │
     │      │                       │                    │
     │      └───────────────────────┘                    │
     │        1240 × 680                ← 尺寸提示跟随光标 │
     └────────────────────────────────────────────────────┘

  · 按下左键 → 起点；拖动 → 实时更新选区；松开 → 完成
  · 未拖动直接单击 → 视为**取消**（避免误触截到 1×1）
  · Esc / 右键 → 取消
  · 拖动中按住 Shift → 锁定正方形（微信同款隐藏技巧）
  · 光标处显示"宽 × 高"，方便按需精确取景

═══ 为什么用"冻结画面"而不是"实时截屏"═══════════════════════════

取景期间把整屏**抓一次**作为背景画布。
  ① 性能：拖动时只重绘本地 QPixmap，不再反复 grabWindow（后者在
     多显示器 / 高 DPI 下开销很大，会造成选区跟手迟滞）；
  ② 正确性：给用户看到的就是最终会被截下的那一帧，所见即所得。
"""

import os

from PySide6.QtCore import Qt, QRect, QPoint, QRectF, Signal
from PySide6.QtGui import (QPixmap, QPainter, QColor, QPen, QBrush, QFont,
                           QCursor, QGuiApplication, QPainterPath)
from PySide6.QtWidgets import QWidget

# 暗罩：选区外压暗，突出选区（微信是约 45% 黑）
MASK = QColor(0, 0, 0, 130)
# 选区边框主题色，与主界面强调色一致
ACCENT = "#3B82F6"
HINT_BG = QColor(28, 30, 36, 235)
HINT_TEXT = QColor(240, 242, 245)


class SnipOverlay(QWidget):
    """全屏取景遮罩：在其上框选一块矩形，松开即回调。

    用法::

        ov = SnipOverlay(pixmap, hint="拖动选择截图区域")
        ov.picked.connect(on_region)     # QRect（屏幕/图片坐标）
        ov.cancelled.connect(on_cancel)
        ov.show()
    """

    picked = Signal(QRect)
    cancelled = Signal()

    def __init__(self, canvas: QPixmap, hint: str = "", parent=None):
        super().__init__(parent)
        self._canvas = canvas
        # 无边框 + 置顶 + 不进任务栏，铺满整个虚拟桌面（多显示器也覆盖）
        flags = (Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                 | Qt.Tool | Qt.NoDropShadowWindowHint)
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setMouseTracking(True)
        # 十字光标，明确"这里是取景点"
        self.setCursor(Qt.CrossCursor)

        self._hint = hint
        self._origin = None       # 拖动起点（控件坐标）
        self._cur = None          # 当前点
        self._dragging = False
        self._shift = False       # 按住 Shift 锁正方形

        # 覆盖虚拟桌面的并集（多显示器时可能不是从 0,0 开始）
        geo = QRect()
        for s in QGuiApplication.screens():
            geo = geo.united(s.geometry())
        self._screen_geo = geo
        self.setGeometry(geo)

    # ---------------- 绘制 ----------------

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        full = self.rect()

        # 1) 底图 = 冻结的屏幕画面
        p.drawPixmap(full, self._canvas)

        # 2) 暗罩：整个屏幕压暗，再把选区"挖亮"
        sel = self._selection()
        if sel is None:
            p.fillRect(full, MASK)
        else:
            path = QPainterPath()
            path.addRect(QRectF(full))
            hole = QPainterPath()
            hole.addRect(QRectF(sel))
            p.fillPath(path.subtracted(hole), MASK)

        # 3) 空态提示（还没开始拖）
        if sel is None:
            self._draw_hint(p, full)
            return

        # 4) 选区边框 + 四角把手
        pen = QPen(QColor(ACCENT))
        pen.setWidth(2)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRect(sel)

        # 四角加粗短线，强化"这是可调整的框"的暗示
        arm = 14
        pen.setWidth(4)
        p.setPen(pen)
        # 左上
        p.drawLine(sel.left(), sel.top(), sel.left() + arm, sel.top())
        p.drawLine(sel.left(), sel.top(), sel.left(), sel.top() + arm)
        # 右上
        p.drawLine(sel.right() - arm, sel.top(), sel.right(), sel.top())
        p.drawLine(sel.right(), sel.top(), sel.right(), sel.top() + arm)
        # 左下
        p.drawLine(sel.left(), sel.bottom() - arm, sel.left(), sel.bottom())
        p.drawLine(sel.left(), sel.bottom(), sel.left() + arm, sel.bottom())
        # 右下
        p.drawLine(sel.right() - arm, sel.bottom(), sel.right(), sel.bottom())
        p.drawLine(sel.right(), sel.bottom() - arm, sel.right(), sel.bottom())

        # 5) 尺寸标签：跟随光标，显示 宽 × 高
        self._draw_size_tag(p, sel)

    def _draw_hint(self, p, full):
        """空态引导文案，居中显示（微信是左上角小字，这里更醒目一些）。"""
        if not self._hint:
            return
        f = QFont()
        f.setPointSize(13)
        p.setFont(f)
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(self._hint)
        pad = 16
        box = QRect(0, 0, tw + pad * 2, fm.height() + pad)
        box.moveCenter(QPoint(full.center().x(),
                              full.top() + full.height() // 5))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(HINT_BG))
        p.drawRoundedRect(box, 8, 8)
        p.setPen(QPen(HINT_TEXT))
        p.drawText(box, Qt.AlignCenter, self._hint)

    def _draw_size_tag(self, p, sel):
        f = QFont()
        f.setPointSize(11)
        f.setBold(True)
        p.setFont(f)
        txt = f"{sel.width()} × {sel.height()}"
        fm = p.fontMetrics()
        pad = 9
        w = fm.horizontalAdvance(txt) + pad * 2
        h = fm.height() + pad
        # 默认放在选区左上角上方；顶到屏幕顶就翻到选区内部左上
        x, y = sel.left(), sel.top() - h - 4
        if y < self.rect().top():
            y = sel.top() + 4
        if x + w > self.rect().right():
            x = self.rect().right() - w
        box = QRect(x, y, w, h)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(HINT_BG))
        p.drawRoundedRect(box, 6, 6)
        p.setPen(QPen(HINT_TEXT))
        p.drawText(box, Qt.AlignCenter, txt)

    # ---------------- 选区计算 ----------------

    def _selection(self):
        if self._origin is None or self._cur is None:
            return None
        a, b = self._origin, self._cur
        x1, x2 = sorted((a.x(), b.x()))
        y1, y2 = sorted((a.y(), b.y()))
        if self._shift:
            # 锁正方形：以较短边为准，方向跟随拖动
            side = min(x2 - x1, y2 - y1)
            if b.x() < a.x():
                x1 = a.x() - side
            else:
                x2 = a.x() + side
            if b.y() < a.y():
                y1 = a.y() - side
            else:
                y2 = a.y() + side
        return QRect(x1, y1, max(1, x2 - x1), max(1, y2 - y1))

    # ---------------- 事件 ----------------

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self._cancel()
            return
        if e.button() == Qt.LeftButton:
            self._origin = e.position().toPoint()
            self._cur = self._origin
            self._dragging = True
            self.update()

    def mouseMoveEvent(self, e):
        self._shift = bool(e.modifiers() & Qt.ShiftModifier)
        if self._dragging:
            self._cur = e.position().toPoint()
            self.update()
        else:
            # 未拖动时只更新尺寸标签位置也要重绘（保持轻量）
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or not self._dragging:
            return
        self._dragging = False
        sel = self._selection()
        # 单击（没真正拖动）或选区太小 → 视为取消，避免截到 1×1
        if sel is None or sel.width() < 8 or sel.height() < 8:
            self._cancel()
            return
        # 转成"画布坐标"（虚拟桌面可能有负原点，需减去桌面左上角）
        g = self._screen_geo
        out = QRect(sel.left() - g.left(), sel.top() - g.top(),
                    sel.width(), sel.height())
        self.picked.emit(out)
        self.close()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._cancel()
            return
        if e.key() == Qt.Key_Shift:
            self._shift = True
            self.update()
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key_Shift:
            self._shift = False
            self.update()
        super().keyReleaseEvent(e)

    def _cancel(self):
        self.cancelled.emit()
        self.close()


def grab_virtual_desktop(_unused=None):
    """抓取整个虚拟桌面（含多显示器）为一张 QPixmap。

    返回 (pixmap, origin)：
      · pixmap —— 覆盖所有屏幕的并集图像
      · origin —— 并集左上角在**全局屏幕坐标**里的位置（多屏可为负）

    注意：`QScreen.grabWindow(0)` 在 Qt6 里抓的是**单屏**；
    多屏要么逐屏抓再拼，要么用虚拟桌面几何。这里逐屏拼接，
    保证跨屏框选出来的位置与最终像素严格对应。
    """
    app = QGuiApplication.instance()
    if app is None:
        return QPixmap(), QPoint(0, 0)
    union = QRect()
    for s in QGuiApplication.screens():
        union = union.united(s.geometry())
    if union.isEmpty():
        return QPixmap(), QPoint(0, 0)

    # 取设备像素比：高 DPI 下 grabWindow 返回物理像素，需要据此换算
    dpr = max((s.devicePixelRatio() for s in QGuiApplication.screens()),
              default=1.0)
    canvas = QPixmap(int(union.width() * dpr), int(union.height() * dpr))
    canvas.setDevicePixelRatio(dpr)
    canvas.fill(QColor(0, 0, 0, 255))

    p = QPainter(canvas)
    for s in QGuiApplication.screens():
        sg = s.geometry()
        shot = s.grabWindow(0)
        if shot.isNull():
            continue
        # 目标矩形：该屏在并集里的相对位置（按物理像素换算）
        dst = QRect(int((sg.left() - union.left()) * dpr),
                    int((sg.top() - union.top()) * dpr),
                    int(sg.width() * dpr), int(sg.height() * dpr))
        p.drawPixmap(dst, shot)
    p.end()
    return canvas, union.topLeft()


def region_from_canvas(canvas: QPixmap, region: QRect, origin: QPoint):
    """从整屏画布里裁出选区，返回 (sub_pixmap, global_rect)。

    region 是"画布坐标"（已减去 origin），global_rect 是屏幕全局坐标，
    供调用方在需要时做坐标换算（如高亮所在显示器）。
    """
    dpr = canvas.devicePixelRatio() or 1.0
    phys = QRect(int(region.left() * dpr), int(region.top() * dpr),
                 int(region.width() * dpr), int(region.height() * dpr))
    phys = phys.intersected(QRect(0, 0, canvas.width(), canvas.height()))
    if phys.isEmpty():
        return QPixmap(), QRect()
    sub = canvas.copy(phys)
    sub.setDevicePixelRatio(dpr if dpr else 1.0)
    global_rect = QRect(region.left() + origin.x(), region.top() + origin.y(),
                        region.width(), region.height())
    return sub, global_rect
