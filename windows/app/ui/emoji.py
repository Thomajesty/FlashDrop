# -*- coding: utf-8 -*-
"""
Fluent Emoji 表情面板（Windows 端）
==================================

数据来源：Microsoft Fluent Emoji (MIT)，已离线内置在 assets/fluent_emoji/。
目录：assets/emoji_catalog.json —— {style, count, groups:[{name, emojis:[{slug,char,name,cn,group}]}]}

设计要点（对齐微信 / 飞书桌面端的表情面板）
  - 弹出式无边框浮层，点击外部或 Esc 关闭
  - 顶部分类页签（Smileys / People / Animals …），横向滚动
  - 网格显示 8 列，懒加载 QPixmap（只在实际可见时解码）
  - 悬停高亮 + 提示（中文名）
  - 点击把 emoji 字符插入调用方指定的插入函数
  - 底部「最近使用」记录（最多 32 个），持久化到 QSettings
"""
from __future__ import annotations

import json
import os
import sys

from PySide6.QtCore import Qt, Signal, QSize, QPoint, QTimer, QSettings
from PySide6.QtGui import (QPixmap, QPainter, QColor, QIcon, QCursor, QFont,
                           QFontMetrics)
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QScrollArea, QGridLayout, QPushButton,
                               QFrame, QToolButton, QSizePolicy, QToolTip)


# ---------- 资源定位（兼容 PyInstaller onefile）----------
def _emoji_dir() -> str:
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "..")
    return os.path.join(base, "assets", "fluent_emoji")


def _catalog_path() -> str:
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "..")
    return os.path.join(base, "assets", "emoji_catalog.json")


# ---------- 分类中文名 ----------
GROUP_CN = {
    "Smileys & Emotion": "表情",
    "People & Body": "人物",
    "Animals & Nature": "动物",
    "Food & Drink": "食物",
    "Travel & Places": "旅行",
    "Activities": "活动",
    "Objects": "物品",
    "Symbols": "符号",
    "Flags": "旗帜",
    "Other": "其他",
}

RECENT_KEY = "emoji/recent"
RECENT_MAX = 32

# ★ v1.18.13：底部分类图标条用的图标（对齐微信底栏的圆形图标风格）
TAB_ICON = {
    "Smileys & Emotion": "😀",
    "People & Body": "🧑",
    "Animals & Nature": "🐻",
    "Food & Drink": "🍔",
    "Travel & Places": "🚗",
    "Activities": "⚽",
    "Objects": "💡",
    "Symbols": "❤",
    "Flags": "🏳",
    "Other": "⋯",
}


def load_catalog() -> dict:
    """读取内置表情目录；失败时返回空结构（UI 会显示占位提示）。"""
    p = _catalog_path()
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"style": "modern", "count": 0, "groups": []}


class _EmojiButton(QToolButton):
    """单个表情格子：懒加载图标 + 悬停提示。

    ★ v1.18.14（用户第 2 条）：**图标被全局 QSS 压小的坑**。

    theme.py 里有一条全局规则 `QToolButton { padding: 4px 14px; }`
    （为的是让「截图」下拉按钮与左侧 QPushButton 等高）。它同样命中了
    这里的表情格子 —— 格子是 44px 定宽，扣掉 4px*2 竖向、14px*2 横向
    的 padding 和 1px*2 边框后，内容区只剩 44-28-2 = **14px**，于是
    setIconSize(26) 被 Qt 强行压到 14px。

    这也解释了为什么 v1.18.10 / v1.18.12 / v1.18.13 几次「放大表情」
    用户都觉得没变 —— 改动全被 padding 吃掉了。

    修法：给格子一个 objectName，并在面板 QSS 里用 **ID 选择器**
    （特异性高于裸 QToolButton）把 padding 归零。
    """

    picked = Signal(str, str)   # (char, slug)

    def __init__(self, ent: dict, img_dir: str, cell: int, parent=None,
                 icon_pad: int = 16):
        super().__init__(parent)
        self.ent = ent
        self.img_dir = img_dir
        self._loaded = False
        self.setObjectName("EmojiCell")      # ★ 让 QSS 能精确命中
        self.setFixedSize(cell, cell)
        # ★ v1.18.14：把 padding 归零**写在按钮自己的样式表里**。
        #   只靠面板 QSS 的 ID 选择器不够稳 —— 实测打包后的 EXE 里，
        #   MainWindow 的全局 `QToolButton { padding: 4px 14px; }` 仍会
        #   作用到这个 Popup，把 44px 格子的内容区压到 14px，
        #   图标被 Qt 缩到 14px（用户"表情太小"的真正根因）。
        #   控件自身样式表的优先级高于任何祖先/应用级规则，最可靠。
        self.setStyleSheet("QToolButton { padding: 0px; }")
        self.setCursor(Qt.PointingHandCursor)
        self.setAutoRaise(True)
        # ★ v1.18.14：微信桌面端实测图标可视 22~24px（cell pitch 44）。
        #   这里 iconSize = 44 - 16 = 28px → 实际可见约 24px，落在微信区间上沿。
        self.setIconSize(QSize(cell - icon_pad, cell - icon_pad))
        self.setToolTip("%s  %s" % (ent.get("cn") or ent.get("name", ""),
                                    ent.get("char", "")))
        self.clicked.connect(self._emit)

    def _emit(self):
        self.picked.emit(self.ent.get("char", ""), self.ent.get("slug", ""))

    def ensure_loaded(self):
        if self._loaded:
            return
        self._loaded = True
        p = os.path.join(self.img_dir, self.ent.get("slug", "") + ".png")
        if os.path.exists(p):
            pm = QPixmap(p)
            if not pm.isNull():
                self.setIcon(QIcon(pm))

    # 首次显示时再解码，避免一次性加载 1592 张
    def showEvent(self, ev):
        super().showEvent(ev)
        if not self._loaded:
            self.ensure_loaded()


class EmojiPanel(QFrame):
    """表情选择浮层。owner 为触发它的按钮，用于定位。

    ★ v1.18.13（用户第 1 条）：「电脑版表情显示还是太小，包括行数大小，
      要和微信对齐」。

    ── 微信桌面版实测（tests/_measure_wx2b.py，100% 缩放）─────────────
        面板            464 × 462 px
        列数            10
        列 pitch        44 px
        行 pitch        44 px
        图标可视        23 × 23 px
        左侧留白        22 px（面板 91 → 首列 113）
        纵向结构（相对面板顶）：
            +24   「最近使用」标题
            +58   最近使用 1 行
            +105  「所有表情」标题
            +139  网格第 1 行
            +182  网格第 2 行
            +226  网格第 3 行
            +270  网格第 4 行
            +315  网格第 5 行
            +358  网格第 6 行   ← 可见 6 行
            +402  分割线
            +424  底部工具条
      结论：微信**可见 6 行**、面板高 462；而 FlashDrop 旧版只有 357 高、
      且图标 36px 反而比微信(23px)大 —— 用户感觉"太小"其实是**面板整体
      偏小/行数偏少**。本版按微信 1:1 对齐。

    ── 本版规格（对齐微信）────────────────────────────────────────────
        COLS = 10 · CELL = 44 · 图标 26px · 网格可见 6 行
        面板宽 = 10*44 + 2*12 = 464       （微信 464）
        面板高 = 顶部30 + 标题16 + 网格 6*44 + 分割6 + 分类条52 ≈ 458
        分类栏改为**底部圆形图标工具条**（同微信）
    """
    # 对齐微信：10 列 / 44px 格子 / 图标 26px（微信 23px，略大以保证锐利）
    COLS = 10
    CELL = 44
    ICON_PAD = 16          # 44 - 16 = 28px 图标框（微信图标可视 22~24px）
    GRID_ROWS = 6          # 可见 6 行（与微信一致）
    SIDE_PAD = 12          # 面板左右内边距 → 10*44+24 = 464
    RECENT_STRIP = 10      # 顶部「最近使用」横条最多展示几个（微信 3 个，这里给 10）

    picked = Signal(str)          # 选中表情字符

    # ★ Qt.Popup 是**顶层窗口**，不会继承 MainWindow 上 setStyleSheet() 里的
    #   font-family —— 实测页签的中文全部渲染成豆腐块 ▯（见
    #   tests/real_emoji_panel_dark.png 首版）。这里显式指定与全局一致的
    #   字体栈，保证中文页签正常显示。
    FONT_STACK = ("Microsoft YaHei UI", "Microsoft YaHei",
                  "Segoe UI", "sans-serif")

    def __init__(self, parent, theme: dict):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint |
                         Qt.NoDropShadowWindowHint)
        self.setObjectName("EmojiPanel")
        self._theme = theme
        f = QFont(self.FONT_STACK[0])
        f.setPixelSize(12)
        self.setFont(f)
        self._img_dir = _emoji_dir()
        self._cat = load_catalog()
        self._entries = [e for g in self._cat.get("groups", [])
                         for e in g["emojis"]]
        self._by_slug = {e["slug"]: e for e in self._entries}
        self._settings = QSettings("FlashDrop", "FlashDrop")
        self._recent = self._load_recent()
        self._buttons = []
        self._build()
        self._apply_theme(theme)

    # ---------- 最近使用 ----------
    def _load_recent(self) -> list:
        raw = self._settings.value(RECENT_KEY, [])
        if isinstance(raw, str):
            raw = [s for s in raw.split(",") if s]
        out = []
        for s in (raw or []):
            if s in self._by_slug and s not in out:
                out.append(s)
        return out[:RECENT_MAX]

    def _push_recent(self, slug: str):
        if not slug or slug not in self._by_slug:
            return
        if slug in self._recent:
            self._recent.remove(slug)
        self._recent.insert(0, slug)
        del self._recent[RECENT_MAX:]
        self._settings.setValue(RECENT_KEY, self._recent)

    # ---------- 构建 ----------
    def _build(self):
        v = QVBoxLayout(self)
        # ★ v1.18.13：外边距按微信比例放大（微信顶部留白 24、左右 12）
        v.setContentsMargins(self.SIDE_PAD, 10, self.SIDE_PAD, 8)
        v.setSpacing(4)

        # ── v1.18.13：分类栏从「顶部文字页签」改为微信式「底部圆形图标条」──
        #   微信面板结构：网格在上、分类图标条在下（带一条分割线）。
        #   图标条横向可滚动，每个分类一个圆形图标按钮，选中态有浅色圆底。
        self._tab_btns = []
        groups = [("recent", "最近", "🕘")] + \
                 [(g["name"], GROUP_CN.get(g["name"], g["name"]), TAB_ICON.get(g["name"], "•"))
                  for g in self._cat.get("groups", [])]
        self._groups = [("recent", "最近", None)] + \
                       [(g["name"], GROUP_CN.get(g["name"], g["name"]), g)
                        for g in self._cat.get("groups", [])]

        # ── 「最近使用」横条（对齐微信顶部那一行 3 个最近表情）──────────
        #   微信面板顶部是「最近使用」标题 + 一行最近表情（行高 44），
        #   这是微信面板能到 462 高的主要来源。这里同等实现：
        #   只在真有历史记录时显示，避免冷启动出现空白条。
        self._recent_wrap = QWidget()
        self._recent_wrap.setObjectName("EmojiRecentWrap")
        rv = QVBoxLayout(self._recent_wrap)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(2)
        self._recent_title = QLabel("最近使用")
        self._recent_title.setObjectName("EmojiSection")
        rv.addWidget(self._recent_title)
        self._recent_row_host = QWidget()
        self._recent_row_host.setObjectName("EmojiRecentRow")
        self._recent_row = QHBoxLayout(self._recent_row_host)
        self._recent_row.setContentsMargins(0, 0, 0, 0)
        self._recent_row.setSpacing(0)
        rv.addWidget(self._recent_row_host)
        v.addWidget(self._recent_wrap)

        # ── 分组标题（对齐微信的「所有表情」区块标题）──
        self._sec = QLabel("")
        self._sec.setObjectName("EmojiSection")
        v.addWidget(self._sec)

        # 网格滚动区（放在分类条**之上**，与微信一致）
        self._scroll = QScrollArea()
        self._scroll.setObjectName("EmojiScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 可见 6 行（微信同）× 44px 格子 = 264；加 2px 余量防末行裁切
        self._scroll.setFixedHeight(self.CELL * self.GRID_ROWS + 2)
        self._host = QWidget()
        self._host.setObjectName("EmojiHost")
        self._grid = QGridLayout(self._host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(0)
        self._scroll.setWidget(self._host)
        v.addWidget(self._scroll)

        # 分割线（微信在两区之间有一条浅线）
        self._divider = QFrame()
        self._divider.setObjectName("EmojiDivider")
        self._divider.setFixedHeight(1)
        v.addWidget(self._divider)

        # 分类图标条（微信式底栏：圆形图标 + 选中浅底）
        self._tabs_host = QWidget()
        self._tabs_host.setObjectName("EmojiTabsHost")
        self._tabs_row = QHBoxLayout(self._tabs_host)
        self._tabs_row.setSpacing(4)
        self._tabs_row.setContentsMargins(0, 4, 0, 4)

        self._tabs_scroll = QScrollArea()
        self._tabs_scroll.setObjectName("EmojiTabs")
        self._tabs_scroll.setWidgetResizable(True)
        self._tabs_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._tabs_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._tabs_scroll.setFrameShape(QFrame.NoFrame)
        # ★ 微信底栏图标 32px + 上下留白 → 条高 44（对齐微信 ~60 的观感）
        self._tabs_scroll.setFixedHeight(44)
        self._tabs_scroll.setWidget(self._tabs_host)
        v.addWidget(self._tabs_scroll)

        for key, label, icon in groups:
            if key != "recent":
                g = next((g for k, _, g in self._groups if k == key and g), None)
                if g is not None and not g["emojis"]:
                    continue
            b = QPushButton(icon)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setObjectName("EmojiTabIcon")
            b.setFixedSize(34, 34)
            # ★ v1.18.14：同 EmojiCell —— 全局 `QPushButton { padding: 6px 14px; }`
            #   会把 34px 按钮的内容区压到 6px，分类图标被裁掉。
            b.setStyleSheet("QPushButton { padding: 0px; }")
            b.setToolTip(label)
            # ★ 顶层 Popup 不继承 QSS font-family，emoji 图标必须显式 setFont
            bf = QFont(self.FONT_STACK[0])
            bf.setPixelSize(17)
            b.setFont(bf)
            b.clicked.connect(lambda _=False, k=key: self._show_group(k))
            self._tabs_row.addWidget(b)
            self._tab_btns.append((key, b, label))
        self._tabs_row.addStretch(1)

        # 面板宽度 = 10 列 * 44 + 左右各 12 = 464（与微信一致）
        self.setFixedWidth(self.COLS * self.CELL + self.SIDE_PAD * 2)
        self._show_group("Smileys & Emotion")

    def wheelEvent(self, ev):
        """滚轮在页签条上时改为横向滚动，方便切分类。"""
        pos = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
        if self._tabs_scroll.geometry().contains(pos):
            sb = self._tabs_scroll.horizontalScrollBar()
            sb.setValue(sb.value() - ev.angleDelta().y() // 2)
            ev.accept()
            return
        super().wheelEvent(ev)

    def _refresh_recent_strip(self):
        """重建顶部「最近使用」横条（最多 RECENT_STRIP 个）。"""
        while self._recent_row.count():
            it = self._recent_row.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        slugs = self._recent[:self.RECENT_STRIP]
        has = bool(slugs)
        self._recent_wrap.setVisible(has)
        if not has:
            return
        for s in slugs:
            e = self._by_slug.get(s)
            if not e:
                continue
            b = _EmojiButton(e, self._img_dir, self.CELL, self._recent_row_host,
                             self.ICON_PAD)
            b.picked.connect(self._on_click)
            b.ensure_loaded()
            self._recent_row.addWidget(b)
        self._recent_row.addStretch(1)

    def _clear_grid(self):
        while self._grid.count():
            it = self._grid.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._buttons = []

    def _show_group(self, key: str):
        for k, b, _label in self._tab_btns:
            b.setChecked(k == key)
        if key == "recent":
            ents = [self._by_slug[s] for s in self._recent if s in self._by_slug]
            # 对齐微信的区块标题文案
            self._sec.setText("最近使用" if ents else "还没有使用记录")
        else:
            g = next((g for k, _, g in self._groups if k == key and g), None)
            ents = g["emojis"] if g else []
            # ★ v1.18.13：对齐微信的「所有表情」标题；flag/other 等小分组
            #   仍显示各自中文名，避免全部叫「所有表情」造成误解。
            title = GROUP_CN.get(key, key)
            self._sec.setText(title if len(ents) < 40
                              else "%s · 共 %d 个" % (title, len(ents)))
        self._clear_grid()
        self._refresh_recent_strip()
        for i, e in enumerate(ents):
            btn = _EmojiButton(e, self._img_dir, self.CELL, self._host,
                               self.ICON_PAD)
            btn.picked.connect(self._on_click)
            btn.ensure_loaded()
            self._grid.addWidget(btn, i // self.COLS, i % self.COLS)
            self._buttons.append(btn)
        self._scroll.verticalScrollBar().setValue(0)

    def _on_click(self, ch: str, slug: str):
        if not ch:
            return
        self._push_recent(slug)
        # ★ 只走一条通路：picked 信号。
        #   曾经这里同时 emit(picked) 又调 self._on_pick(ch)，
        #   而 EmojiButton 已把 picked 接到自己的 picked → 字符被插入两次
        #   （实测输入框出现 "A😠😠B"）。见 verify_emoji_v11810.py §3。
        self.hide()
        self.picked.emit(ch)

    # ---------- 定位与主题 ----------
    def show_at(self, widget: QWidget):
        """把面板贴到 widget 上方（下方空间不足时改到下方）。"""
        self.adjustSize()
        gp = widget.mapToGlobal(QPoint(0, 0))
        scr = widget.screen().availableGeometry()
        w, h = self.width(), self.sizeHint().height()
        x = gp.x()
        y = gp.y() - h - 6                      # 默认在按钮上方
        if y < scr.top() + 4:                   # 上方放不下 -> 下方
            y = gp.y() + widget.height() + 6
        x = max(scr.left() + 4, min(x, scr.right() - w - 4))
        self.move(x, y)
        self.show()
        self.raise_()

    def _apply_theme(self, t: dict):
        bg = t.get("card", "#26292f")
        text = t.get("text", "#e5e7eb")
        dim = t.get("text_dim", "#AEB6C2")
        bd = t.get("border", "#33363d")
        fam = ", ".join('"%s"' % f for f in self.FONT_STACK)
        self.setStyleSheet(f"""
            QFrame#EmojiPanel {{
                background: {bg};
                border: 1px solid {bd};
                border-radius: 10px;
                font-family: {fam};
                font-size: 12px;
            }}
            QWidget#EmojiHost {{ background: transparent; }}
            QWidget#EmojiTabsHost {{ background: transparent; }}
            QFrame#EmojiDivider {{
                background: {bd}; border: none;
            }}
            QScrollArea#EmojiScroll, QScrollArea#EmojiTabs {{
                background: transparent; border: none;
            }}
            QScrollArea#EmojiTabs QScrollBar:horizontal {{
                height: 0px; background: transparent;
            }}
            /* ★ v1.18.14：微信式底部分类图标条：圆形按钮，选中态浅底。
               padding 必须显式归零 —— 全局 QPushButton 规则的 padding
               是 6px 14px，会把 34px 宽按钮的内容区压到 34-28 = 6px，
               分类图标被裁掉。（ID 选择器特异性高于裸 QPushButton。） */
            QPushButton#EmojiTabIcon {{
                background: transparent; color: {text};
                border: none; border-radius: 16px;
                padding: 0px;
                font-family: {fam};
            }}
            QPushButton#EmojiTabIcon:hover {{
                background: {t.get("sidebar_hover", "#282b31")};
            }}
            QPushButton#EmojiTabIcon:checked {{
                background: {t.get("sidebar_sel", "#2d3749")};
            }}
            /* ★ v1.18.14：表情格子。必须用 ID 选择器把 padding 归零，
               否则全局 QToolButton 规则的 padding（4px 14px）会把 44px
               格子的内容区压到 14px，图标被 Qt 缩放成 14px
               —— 这就是用户反复反馈「表情太小」的根因。 */
            QToolButton#EmojiCell {{
                background: transparent; border: none; border-radius: 8px;
                padding: 0px;
            }}
            QToolButton#EmojiCell:hover {{
                background: {t.get("sidebar_hover", "#282b31")};
            }}
            QToolButton {{
                background: transparent; border: none; border-radius: 6px;
            }}
            QToolButton:hover {{
                background: {t.get("sidebar_hover", "#282b31")};
            }}
            QLabel#EmojiHint {{
                color: {dim}; font-size: 10px;
                font-family: {fam};
                padding-left: 2px;
            }}
            QLabel#EmojiSection {{
                color: {dim}; font-size: 11px;
                font-family: {fam};
                padding: 2px 0 2px 2px;
            }}
        """)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(ev)


class EmojiButton(QToolButton):
    """工具行里的「😀 表情」按钮，点击弹出 EmojiPanel。"""

    picked = Signal(str)

    def __init__(self, theme: dict, parent=None, text: str = "😀 表情"):
        super().__init__(parent)
        self.setText(text)
        self.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("EmojiMain")
        self._theme = theme
        self._panel = None
        self.clicked.connect(self._toggle)

    def _toggle(self):
        if self._panel is None:
            self._panel = EmojiPanel(self.window(), self._theme)
            self._panel.picked.connect(self.picked)
        if self._panel.isVisible():
            self._panel.hide()
        else:
            self._panel.show_at(self)
