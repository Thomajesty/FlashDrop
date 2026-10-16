# -*- coding: utf-8 -*-
"""
FlashDrop 内置图片查看器（v1.17.0）

═══ v1.17.0 重大精简（用户要求）═══════════════════════════════════

用户原话：
  「把双击打开的图片编辑框，包括裁剪 到应用马赛克 的功能都删除，
    在另存为前增加 其他应用打开功能，
    把上一张 下一张功能做到图片左侧右侧 使用合理的布局 参照其他大厂的做法」

因此本版**只保留浏览能力**，彻底移除所有编辑功能：
  移除：裁剪 / 马赛克 / 标记（画笔）/ 文字 / 撤销 / 重做 / 保存（覆盖）
  保留：上一张 / 下一张 / 放大 / 缩小 / 适应窗口 / 1:1 / 旋转 /
        另存为 / 复制 / 在文件夹中显示 / 删除

═══ 导航按钮布局（对齐大厂做法）═══════════════════════════════════

参照 Windows 照片、macOS 预览、微信图片查看器等主流实现：
  翻页按钮**悬浮在图片左右两侧垂直居中**，半透明圆形底 + 白色箭头，
  鼠标移入才完全显现，移出淡出 —— 视线始终停留在图片上，不打断浏览。

     ┌──────────────────────────────────────────────┐
     │  [≡ 文件名 · 3/12]           [另存为] [关闭] │ ← 顶部细条
     ├──────────────────────────────────────────────┤
     │                                              │
     │   ( ‹ )            [   图片   ]        ( › )  │ ← 左右悬浮翻页
     │                                              │
     ├──────────────────────────────────────────────┤
     │  [−] 100% [+] [适应] [1:1] [⟳]   1200×800    │ ← 底部工具条
     └──────────────────────────────────────────────┘

  · 到达首/末张时对应按钮自动禁用并降到 25% 不透明度
  · 键盘 ← → / Esc / Ctrl+0 / Ctrl+1 / Ctrl+± 全部保留
  · 滚轮缩放、按住拖拽平移保留
"""

import os

from PySide6.QtCore import Qt, QRectF, QSize, Signal, QTimer
from PySide6.QtGui import (QPixmap, QImage, QPainter, QColor, QPen,
                           QKeySequence, QAction, QBrush)
from PySide6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout,
                               QLabel, QPushButton, QToolButton, QFileDialog,
                               QMessageBox, QFrame, QSizePolicy, QGraphicsView,
                               QGraphicsScene, QGraphicsPixmapItem, QApplication,
                               QGraphicsOpacityEffect)

ACCENT = "#3B82F6"
DARK_BG = "#16181D"
DARK_PANEL = "#1E2026"
DARK_CARD = "#262A32"
TEXT = "#E8EAED"
TEXT_DIM = "#9AA1AC"
BORDER = "#333842"


# ============================================================
# 画布（仅缩放 / 平移，无编辑）
# ============================================================

class Canvas(QGraphicsView):
    """图片画布：滚轮缩放、按住拖拽平移。v1.17.0 起不再承担任何编辑交互。"""

    zoomChanged = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.item = QGraphicsPixmapItem()
        self.item.setTransformationMode(Qt.SmoothTransformation)
        self.scene().addItem(self.item)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setBackgroundBrush(QBrush(QColor(DARK_BG)))
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._zoom = 1.0
        self._panning = False
        self._pan_origin = None

    # ---------- 内容 ----------
    def set_image(self, img: QImage):
        pm = QPixmap.fromImage(img)
        self.item.setPixmap(pm)
        self.scene().setSceneRect(QRectF(pm.rect()))
        self.fit()

    def current_pixmap(self) -> QPixmap:
        return self.item.pixmap()

    def fit(self):
        pm = self.item.pixmap()
        if pm.isNull():
            return
        self.resetTransform()
        vw = max(1, self.viewport().width() - 4)
        vh = max(1, self.viewport().height() - 4)
        s = min(vw / pm.width(), vh / pm.height())
        s = max(0.05, min(s, 8.0))
        self.scale(s, s)
        self._zoom = s
        self.zoomChanged.emit(s)

    def zoom_to(self, factor):
        """factor>1 放大；限制 0.05x ~ 16x"""
        cur = self._zoom
        target = max(0.05, min(cur * factor, 16.0))
        real = target / cur
        if abs(real - 1.0) < 1e-6:
            return
        self.scale(real, real)
        self._zoom = target
        self.zoomChanged.emit(target)

    def zoom_actual(self):
        self.resetTransform()
        self._zoom = 1.0
        self.zoomChanged.emit(1.0)

    def rotate_cw(self):
        """顺时针旋转 90°（仅当前查看，不改动磁盘文件）"""
        self.item.setRotation(self.item.rotation() + 90)

    # ---------- 交互 ----------
    def wheelEvent(self, e):
        delta = e.angleDelta().y()
        if delta:
            self.zoom_to(1.15 if delta > 0 else 1 / 1.15)
        e.accept()

    def mousePressEvent(self, e):
        if e.button() == Qt.MiddleButton or e.button() == Qt.LeftButton:
            self._panning = True
            self.viewport().setCursor(Qt.ClosedHandCursor)
            self._pan_origin = e.position()
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._panning and self._pan_origin is not None:
            d = e.position() - self._pan_origin
            self._pan_origin = e.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(d.x()))
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(d.y()))
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._panning:
            self._panning = False
            self.viewport().setCursor(Qt.ArrowCursor)
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        """双击在「适应窗口」与「1:1」之间切换（与 Windows 照片一致）"""
        pm = self.item.pixmap()
        if not pm.isNull():
            vw = max(1, self.viewport().width() - 4)
            vh = max(1, self.viewport().height() - 4)
            fit_s = max(0.05, min(min(vw / pm.width(), vh / pm.height()), 8.0))
            if abs(self._zoom - fit_s) < 1e-3 or abs(self._zoom - 1.0) > 1e-3:
                self.zoom_actual()
            else:
                self.fit()
        e.accept()


# ============================================================
# 悬浮圆形翻页按钮（左右两侧）
# ============================================================

class NavButton(QToolButton):
    """图片两侧的半透明圆形翻页按钮。

    参照大厂做法：默认 55% 不透明度、鼠标移入完全显现、
    禁用态降到 25%。视觉上是一个"磨砂玻璃"圆片压在图片上，
    不占据额外布局空间（绝对定位悬浮）。

    ★ 透明度实现说明（v1.17.0 实测踩坑）：
      QWidget.setWindowOpacity() **只对顶层窗口生效**，对作为子控件的
      按钮调用它会被 Qt 静默忽略（实测调用后 windowOpacity() 仍返回 1.0）。
      子控件必须用 QGraphicsOpacityEffect 挂在 graphicsEffect 上，
      这里因此改用 set_opacity() 封装，内部走 effect。
    """

    def __init__(self, arrow: str, tip: str, parent=None):
        super().__init__(parent)
        self.setText(arrow)
        self.setToolTip(tip)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(46, 46)
        self.setFocusPolicy(Qt.NoFocus)
        self._opacity = 0.55
        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(self._opacity)
        self.setGraphicsEffect(self._effect)
        self.setStyleSheet(f"""
            QToolButton {{
                color: #FFFFFF;
                background: rgba(0, 0, 0, 140);
                border: 1px solid rgba(255, 255, 255, 60);
                border-radius: 23px;
                font-size: 22px;
                font-weight: bold;
                padding-bottom: 3px;
            }}
            QToolButton:hover {{
                background: rgba(0, 0, 0, 200);
                border-color: rgba(255, 255, 255, 120);
            }}
            QToolButton:pressed {{ background: rgba(59, 130, 246, 220); }}
            QToolButton:disabled {{
                color: rgba(255, 255, 255, 70);
                background: rgba(0, 0, 0, 70);
                border-color: rgba(255, 255, 255, 25);
            }}
        """)

    # ---------- 透明度（走 QGraphicsOpacityEffect，子控件可用） ----------
    def set_opacity(self, v: float):
        self._opacity = max(0.0, min(1.0, float(v)))
        # 极端值直接摘掉 effect，让 Qt 走最快路径
        if self._opacity >= 1.0:
            self.setGraphicsEffect(None)
        else:
            if self.graphicsEffect() is not self._effect:
                self.setGraphicsEffect(self._effect)
            self._effect.setOpacity(self._opacity)

    def opacity(self) -> float:
        if self._opacity >= 1.0:
            return 1.0
        eff = self.graphicsEffect()
        if isinstance(eff, QGraphicsOpacityEffect):
            return eff.opacity()
        return self._opacity

    def enterEvent(self, e):
        if self.isEnabled():
            self.set_opacity(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self.isEnabled():
            self.set_opacity(0.55)
        # 复用 _update_buttons 里的"基线"值：这里简单恢复 0.55，
        # 禁用态由 setEnabled 后的再次 set_opacity(0.25) 覆盖
        if not self.isEnabled():
            self.set_opacity(0.25)
        super().leaveEvent(e)


# ============================================================
# 查看器主窗口
# ============================================================

class ImageViewer(QDialog):
    """内置图片查看器（v1.17.0：纯浏览，无编辑功能）"""

    # 供外部（如截图流程）在查看器内触发保存
    savedAs = Signal(str)

    def __init__(self, paths, index=0, parent=None, silent=False):
        super().__init__(parent)
        self.setWindowTitle("图片查看")
        self.setModal(False)
        self.resize(1120, 760)
        # silent：自动化/无头测试用，跳过阻塞式对话框
        self.silent = silent
        self.setStyleSheet(f"""
            QDialog {{ background: {DARK_BG}; }}
            QWidget {{ color: {TEXT}; }}
            QToolButton, QPushButton {{
                background: {DARK_CARD}; color: {TEXT};
                border: 1px solid {BORDER}; border-radius: 6px;
                padding: 5px 10px; font-size: 12px;
            }}
            QToolButton:hover, QPushButton:hover {{ background: #313742; }}
            QToolButton:disabled, QPushButton:disabled {{
                color: #5A6270; border-color: #2A2F38;
            }}
            QLabel {{ background: transparent; }}
        """)

        self._paths = [p for p in (paths or []) if p and os.path.isfile(p)]
        self._index = max(0, min(index, len(self._paths) - 1)) if self._paths else -1

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._make_topbar())

        # ---- 画布 + 左右悬浮翻页按钮（叠在同一层） ----
        stage = QWidget()
        stage_lay = QVBoxLayout(stage)
        stage_lay.setContentsMargins(0, 0, 0, 0)

        self.canvas = Canvas(stage)
        self.canvas.zoomChanged.connect(self._on_zoom)
        stage_lay.addWidget(self.canvas)

        # 悬浮按钮的 parent 是 stage，靠 raise_() 浮在 canvas 之上
        self.btn_prev = NavButton("‹", "上一张 (←)", stage)
        self.btn_next = NavButton("›", "下一张 (→)", stage)
        self.btn_prev.clicked.connect(self.prev)
        self.btn_next.clicked.connect(self.next)
        self.btn_prev.set_opacity(0.55)
        self.btn_next.set_opacity(0.55)
        self._stage = stage
        root.addWidget(stage, 1)

        root.addWidget(self._make_bottombar())
        self._load(self._index)

        # 尺寸变化时重新摆放悬浮按钮
        self.canvas.installEventFilter(self)

    # ---------------- 悬浮按钮定位 ----------------
    def eventFilter(self, obj, ev):
        if obj is self.canvas and ev.type() in (ev.Type.Resize, ev.Type.Show):
            QTimer.singleShot(0, self._place_nav)
        return super().eventFilter(obj, ev)

    def _place_nav(self):
        """把左右翻页按钮垂直居中贴到画布左右边缘内侧。"""
        try:
            c = self.canvas
            m = 18            # 距画布边缘的留白
            cy = (c.height() - self.btn_prev.height()) // 2
            self.btn_prev.move(m, max(0, cy))
            self.btn_next.move(
                max(0, c.width() - self.btn_next.width() - m),
                max(0, cy))
            self.btn_prev.raise_()
            self.btn_next.raise_()
            self.btn_prev.setVisible(True)
            self.btn_next.setVisible(True)
        except Exception:
            pass

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_nav()

    def showEvent(self, e):
        """首次显示时 viewport 才有真实尺寸，此时重新适应窗口 + 摆按钮，
        否则会按构造期的微小尺寸算出过小的缩放（表现为"图很小"）。"""
        super().showEvent(e)
        if not getattr(self, "_did_fit", False):
            self._did_fit = True
            QTimer.singleShot(0, self.canvas.fit)
        QTimer.singleShot(0, self._place_nav)

    # ---------------- 顶部条 ----------------
    def _make_topbar(self):
        bar = QWidget()
        bar.setFixedHeight(42)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 6, 10, 6)
        lay.setSpacing(8)

        self.lbl_title = QLabel("")
        self.lbl_title.setStyleSheet(f"color: {TEXT}; font-size: 13px;")
        lay.addWidget(self.lbl_title)
        lay.addStretch(1)

        self.btn_folder = QToolButton()
        self.btn_folder.setText("在文件夹中显示")
        self.btn_folder.setToolTip("在资源管理器中定位该文件")
        self.btn_folder.clicked.connect(self._reveal_in_folder)
        lay.addWidget(self.btn_folder)

        self.btn_copy = QToolButton()
        self.btn_copy.setText("复制")
        self.btn_copy.setToolTip("复制图片到剪贴板 (Ctrl+C)")
        self.btn_copy.clicked.connect(self.copy_to_clipboard)
        lay.addWidget(self.btn_copy)

        self.btn_open_with = QToolButton()
        self.btn_open_with.setText("其他应用打开…")
        self.btn_open_with.setToolTip("选择其它程序打开这张图片")
        self.btn_open_with.clicked.connect(self._open_with)
        lay.addWidget(self.btn_open_with)

        self.btn_saveas = QToolButton()
        self.btn_saveas.setText("另存为…")
        self.btn_saveas.setToolTip("另存到其它位置 (Ctrl+Shift+S)")
        self.btn_saveas.clicked.connect(self.save_as)
        lay.addWidget(self.btn_saveas)

        self.btn_close = QToolButton()
        self.btn_close.setText("关闭")
        self.btn_close.setToolTip("关闭 (Esc)")
        self.btn_close.clicked.connect(self.close)
        lay.addWidget(self.btn_close)
        return bar

    # ---------------- 底部工具条 ----------------
    def _make_bottombar(self):
        bar = QWidget()
        bar.setFixedHeight(40)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 4, 12, 6)
        lay.setSpacing(6)

        def tb(text, tip, slot):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            return b

        lay.addWidget(tb("−", "缩小 (Ctrl+-)", lambda: self.canvas.zoom_to(1 / 1.25)))
        self.lbl_zoom = QLabel("100%")
        self.lbl_zoom.setFixedWidth(52)
        self.lbl_zoom.setAlignment(Qt.AlignCenter)
        self.lbl_zoom.setStyleSheet(f"color: {TEXT_DIM}; font-size: 12px;")
        lay.addWidget(self.lbl_zoom)
        lay.addWidget(tb("+", "放大 (Ctrl++)", lambda: self.canvas.zoom_to(1.25)))
        lay.addWidget(tb("适应窗口", "适应窗口 (Ctrl+0)", self.canvas.fit))
        lay.addWidget(tb("1:1", "原始大小 (Ctrl+1)", self.canvas.zoom_actual))
        lay.addWidget(tb("⟳ 旋转", "顺时针旋转 90°", self.canvas.rotate_cw))

        lay.addStretch(1)
        self.lbl_info = QLabel("")
        self.lbl_info.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")
        lay.addWidget(self.lbl_info)
        return bar

    # ---------------- 图片加载 ----------------
    def _load(self, idx):
        if idx < 0 or idx >= len(self._paths):
            return
        path = self._paths[idx]
        img = QImage(path)
        if img.isNull():
            if not self.silent:
                QMessageBox.warning(self, "无法打开", f"无法读取图片：\n{path}")
            return
        self._index = idx
        self.canvas.set_image(img.convertToFormat(QImage.Format_ARGB32))
        name = os.path.basename(path)
        self.setWindowTitle(f"图片查看 — {name}")
        self.lbl_title.setText(
            f"{name}　·　第 {idx + 1}/{len(self._paths)} 张")
        self._update_info()
        self._update_buttons()

    def _update_info(self):
        pm = self.canvas.current_pixmap()
        if pm.isNull():
            return
        self.lbl_info.setText(f"{pm.width()}×{pm.height()}")

    def _update_buttons(self):
        has_prev = self._index > 0
        has_next = 0 <= self._index < len(self._paths) - 1
        self.btn_prev.setEnabled(has_prev)
        self.btn_next.setEnabled(has_next)
        self.btn_prev.set_opacity(0.55 if has_prev else 0.25)
        self.btn_next.set_opacity(0.55 if has_next else 0.25)
        # 在文件夹中显示按钮已并入顶部

    def _on_zoom(self, z):
        self.lbl_zoom.setText(f"{int(round(z * 100))}%")

    # ---------------- 导航 ----------------
    def next(self):
        if self._index < len(self._paths) - 1:
            self._load(self._index + 1)

    def prev(self):
        if self._index > 0:
            self._load(self._index - 1)

    # ---------------- 动作 ----------------
    def _reveal_in_folder(self):
        if self._index < 0:
            return
        path = self._paths[self._index]
        try:
            if os.name == "nt":
                import subprocess
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            else:
                from PySide6.QtGui import QDesktopServices
                from PySide6.QtCore import QUrl
                QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))
        except Exception:
            pass

    def copy_to_clipboard(self):
        if self._index < 0:
            return
        try:
            img = QImage(self._paths[self._index])
            if not img.isNull():
                QApplication.clipboard().setImage(img)
        except Exception:
            pass

    def _open_with(self):
        """「其他应用打开…」：唤起系统"打开方式"（与右键菜单同一入口）"""
        if self._index < 0:
            return
        path = self._paths[self._index]
        try:
            if os.name == "nt":
                import subprocess
                subprocess.Popen(
                    ["rundll32.exe", "shell32.dll,OpenAs_RunDLL",
                     os.path.normpath(path)],
                    close_fds=True)
            else:
                from PySide6.QtGui import QDesktopServices
                from PySide6.QtCore import QUrl
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception:
            pass

    def save_as(self, target=None) -> bool:
        """另存为。返回是否真正写出文件。"""
        if self._index < 0:
            return False
        src = self._paths[self._index]
        base, ext = os.path.splitext(src)
        path = target
        if not path:
            if self.silent:
                return False
            sug = base + "_副本" + ext
            path, _ = QFileDialog.getSaveFileName(
                self, "另存为", sug,
                "图片 (*.png *.jpg *.jpeg *.bmp);;所有文件 (*)")
        if not path:
            return False
        try:
            import shutil
            if os.path.abspath(path) != os.path.abspath(src):
                shutil.copy2(src, path)
            self.savedAs.emit(path)
            return True
        except Exception:
            if not self.silent:
                QMessageBox.warning(self, "保存失败", f"无法写入：\n{path}")
            return False

    # ---------------- 快捷键 ----------------
    def keyPressEvent(self, e):
        k = e.key()
        mods = e.modifiers()
        if k in (Qt.Key_Left, Qt.Key_PageUp):
            self.prev()
        elif k in (Qt.Key_Right, Qt.Key_PageDown, Qt.Key_Space):
            self.next()
        elif k == Qt.Key_Escape:
            self.close()
            return
        elif k == Qt.Key_0 and mods & Qt.ControlModifier:
            self.canvas.fit()
        elif k == Qt.Key_1 and mods & Qt.ControlModifier:
            self.canvas.zoom_actual()
        elif k in (Qt.Key_Plus, Qt.Key_Equal) and mods & Qt.ControlModifier:
            self.canvas.zoom_to(1.25)
        elif k == Qt.Key_Minus and mods & Qt.ControlModifier:
            self.canvas.zoom_to(1 / 1.25)
        elif k == Qt.Key_C and mods & Qt.ControlModifier:
            self.copy_to_clipboard()
        elif k == Qt.Key_S and mods & Qt.ControlModifier:
            self.save_as()
        else:
            super().keyPressEvent(e)
