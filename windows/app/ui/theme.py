# -*- coding: utf-8 -*-
"""主题与样式表"""

import os
import sys

ACCENT = "#3b82f6"
ACCENT2 = "#06b6d4"
GREEN = "#22c55e"
RED = "#ef4444"
YELLOW = "#f59e0b"


def _res_url(name: str) -> str:
    """资源 PNG 路径（兼容 PyInstaller onefile）"""
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "..")
    return os.path.join(base, "assets", name).replace("\\", "/")


def _arrow_url() -> str:
    """下拉箭头 PNG 的资源路径（兼容 PyInstaller onefile）"""
    return _res_url("down_arrow.png")

DARK = {
    "name": "dark",
    "window": "#191b1f",
    "sidebar": "#1f2126",
    "sidebar_hover": "#282b31",
    "sidebar_sel": "#2d3749",
    "chatbg": "#22252b",
    "bubble_out": "qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #3b82f6, stop:1 #06b6d4)",
    "bubble_in": "#2d3038",
    "text": "#e5e7eb",
    "text_dim": "#AEB6C2",
    "input_bg": "#26292f",
    "border": "#33363d",
    "card": "#26292f",
    "progress": "#3b82f6",
    "scrollbar": "#3a3d44",
}

LIGHT = {
    "name": "light",
    "window": "#f5f6f8",
    "sidebar": "#ffffff",
    "sidebar_hover": "#f0f2f5",
    "sidebar_sel": "#e3efff",
    "chatbg": "#f2f3f5",
    "bubble_out": "qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #3b82f6, stop:1 #06b6d4)",
    "bubble_in": "#ffffff",
    "text": "#1f2328",
    "text_dim": "#6b7280",
    "input_bg": "#ffffff",
    "border": "#e2e4e8",
    "card": "#ffffff",
    "progress": "#3b82f6",
    "scrollbar": "#c8ccd2",
}


def build_qss(t: dict) -> str:
    return f"""
* {{
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
    outline: none;
}}
QMainWindow, QDialog {{ background: {t['window']}; }}
QWidget {{ color: {t['text']}; font-size: 13px; }}

/* ---- 左侧栏 ---- */
#Sidebar {{ background: {t['sidebar']}; border-right: 1px solid {t['border']}; }}
#AppTitle {{ font-size: 17px; font-weight: 600; color: {t['text']}; padding: 2px; }}
#SelfCard {{ background: {t['sidebar_hover']}; border-radius: 10px; }}
#SelfInfoName {{ font-size: 11px; color: {t['text_dim']}; }}
#SelfIp {{ font-size: 10px; color: {t['text_dim']}; }}
#SelfName {{ font-size: 13px; font-weight: 600; }}

QListWidget#DeviceList {{
    background: transparent; border: none; font-size: 13px;
}}
QListWidget#DeviceList::item {{ border-radius: 8px; margin: 2px 6px; padding: 6px; }}
QListWidget#DeviceList::item:hover {{ background: {t['sidebar_hover']}; }}
QListWidget#DeviceList::item:selected {{ background: {t['sidebar_sel']}; }}

/* ---- 通用控件 ---- */
QPushButton {{
    background: {t['card']}; border: 1px solid {t['border']};
    border-radius: 6px; padding: 6px 14px; color: {t['text']};
}}
QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
QPushButton:disabled {{ color: {t['text_dim']}; border-color: {t['border']}; }}

/* ★ v1.18.8：QToolButton 通用样式 —— 修复「截图」按钮与左侧三个
   QPushButton 视觉不一致（无底色/无圆角/高度更矮/原生灰边框）。

   高度对齐的坑（实测得出，别随手改 padding）：QToolButton 的 sizeHint
   走 QStyle::sizeFromContents(CT_ToolButton)，比 CT_PushButton 多吃一份
   字体的 leading。实测 Microsoft YaHei UI @13px 时 leading=2，
   于是同样 padding 下 QToolButton 会高出 3px（30 vs 27）。
   故这里把纵向 padding 由 6 收到 4，横向保持 14 与 QPushButton 对齐：
     4 + 2*1(border) + (13+2 leading) = 21 … 加上 QSS 盒模型后正好 27。
   若以后改字号，纵向 padding 需同步微调，验证见 verify_v1188_btn.py §3。 */
QToolButton {{
    background: {t['card']}; border: 1px solid {t['border']};
    border-radius: 6px; padding: 4px 14px; color: {t['text']};
    font-size: 13px;
}}
QToolButton:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
QToolButton:disabled {{ color: {t['text_dim']}; border-color: {t['border']}; }}

/* 「✂ 截图」组合按钮：主按钮右接下拉三角，合成一个整体（对齐微信）。
   做法：主按钮只保留左半圆角 + 无右边框；三角只保留右半圆角 + 无左边框。
   两者纵向 padding 一致 → 拼接后总高与左侧普通按钮齐平。
   横向 padding 适当收窄，让「✂ 截图」+「▾」的总宽接近单个普通按钮，
   避免组合控件明显比邻居宽。

   ★ v1.18.9：三角**必须清掉 menu-indicator 背景图**。
   QToolButton 设了 InstantPopup 后会由样式绘制一个原生下拉箭头；
   我们又用 setText("▾") 画了一个字符箭头 → 屏幕上出现**两个箭头**。
   这里把 ::menu-indicator 的 image 置空并给 0 尺寸，彻底关掉原生那个，
   只保留自绘的 ▾。见 verify_v1189_ui.py §2。 */
QToolButton#SnipMain {{
    border-top-right-radius: 0; border-bottom-right-radius: 0;
    border-right: none;
    padding: 4px 8px 4px 14px;
}}
QToolButton#SnipArrow {{
    border-top-left-radius: 0; border-bottom-left-radius: 0;
    padding: 4px 8px 4px 6px;
}}
QToolButton#SnipArrow::menu-indicator {{
    image: none;
    width: 0; height: 0;
    subcontrol-position: right center;
    subcontrol-origin: padding;
}}
/* 展开菜单时（三角常驻弹出）保持高亮，避免松手瞬间"闪烁回未选" */
QToolButton#SnipArrow:checked,
QToolButton#SnipArrow:pressed {{ border-color: {ACCENT}; color: {ACCENT}; }}

QPushButton#Primary {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {ACCENT}, stop:1 {ACCENT2});
    border: none; color: white; font-weight: 600; padding: 7px 18px;
}}
QPushButton#Primary:hover {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #2563eb, stop:1 #0891b2); }}
QPushButton#Primary:disabled {{ background: #4b5563; color: #9ca3af; }}
QPushButton#Danger {{ color: {RED}; }}
QPushButton#NewMsgPill {{
    background: {ACCENT}; color: white; border: none;
    border-radius: 15px; padding: 7px 16px; font-weight: 600;
}}
QPushButton#NewMsgPill:hover {{ background: #2563eb; }}

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QComboBox {{
    background: {t['input_bg']}; border: 1px solid {t['border']};
    border-radius: 6px; padding: 6px 8px; color: {t['text']}; selection-background-color: {ACCENT};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{ background: {t['input_bg']}; border: 1px solid {t['border']}; }}

QCheckBox {{ spacing: 6px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px; border: 1px solid {t['text_dim']};
    border-radius: 4px; background: {t['card']};
}}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{
    background: {ACCENT}; border-color: {ACCENT};
    image: url("{_res_url('check.png')}");
}}
QCheckBox::indicator:disabled {{ border-color: {t['border']}; background: {t['border']}; }}
QCheckBox::indicator:checked:disabled {{ background: {t['border']}; border-color: {t['border']}; }}

/* ---- 下拉框（现代扁平风格） ---- */
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{
    image: url("{_arrow_url()}");
    width: 12px; height: 8px;
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background: {t['card']}; border: 1px solid {t['border']};
    border-radius: 8px; padding: 4px; outline: none;
    color: {t['text']};
    selection-background-color: {ACCENT}; selection-color: white;
}}
QComboBox QAbstractItemView::item {{
    min-height: 30px; border-radius: 6px; padding: 2px 8px;
    background: transparent; color: {t['text']};
}}
QComboBox QAbstractItemView::item:selected {{
    background: {ACCENT}; color: white;
}}

QProgressBar {{
    background: {t['window']}; border: none; border-radius: 4px;
    text-align: center; color: {t['text']}; font-size: 11px; height: 8px;
}}
QProgressBar::chunk {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {ACCENT}, stop:1 {ACCENT2}); border-radius: 4px; }}

/* ---- 聊天区 ---- */
#ChatHeader {{ background: {t['sidebar']}; border-bottom: 1px solid {t['border']}; }}
#ChatHeaderLabel {{ font-size: 15px; font-weight: 600; }}
#ChatSub {{ font-size: 11px; color: {t['text_dim']}; }}
#ChatScroll {{ background: {t['chatbg']}; border: none; }}
#InputPanel {{ background: {t['sidebar']}; border-top: 1px solid {t['border']}; }}

QScrollArea {{ border: none; }}
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {t['scrollbar']}; border-radius: 5px; min-height: 30px; margin: 2px;
}}
QScrollBar::handle:vertical:hover {{ background: {ACCENT}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ height: 0; }}

QToolTip {{ background: {t['card']}; color: {t['text']}; border: 1px solid {t['border']}; padding: 4px; }}

/* ---- 右键菜单（加大） ---- */
QMenu {{
    background: {t['card']}; color: {t['text']};
    border: 1px solid {t['border']}; border-radius: 8px; padding: 6px;
    font-size: 14px;
}}
QMenu::item {{ padding: 7px 30px; border-radius: 6px; margin: 1px 2px; }}
QMenu::item:selected {{ background: {ACCENT}; color: white; }}
QMenu::separator {{ height: 1px; background: {t['border']}; margin: 4px 8px; }}
QMenu::icon {{ padding-left: 8px; }}

/* ---- 对话框 ---- */
QTabWidget::pane {{ border: 1px solid {t['border']}; border-radius: 6px; }}
QTabBar::tab {{
    background: transparent; padding: 8px 18px; color: {t['text_dim']};
}}
QTabBar::tab:selected {{ color: {ACCENT}; border-bottom: 2px solid {ACCENT}; }}
"""


def system_prefers_dark() -> bool:
    """读取 Windows 系统应用的深浅色偏好；非 Windows 默认深色"""
    if sys.platform != "win32":
        return True
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            v, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
            return v == 0
    except Exception:
        return True


def resolve_theme(setting: str) -> dict:
    """设置值 dark/light/system -> 实际主题字典"""
    if setting == "light":
        return LIGHT
    if setting == "dark":
        return DARK
    return DARK if system_prefers_dark() else LIGHT


# 对话框（气泡）颜色方案：key -> {名称, 发送气泡底色, 发送气泡文字色}
BUBBLE_SCHEMES = {
    "blue":   {"name": "闪传蓝", "out": "#3B82F6", "out_text": "#FFFFFF"},
    "green":  {"name": "微信绿", "out": "#95EC69", "out_text": "#17301B"},
    "purple": {"name": "清新紫", "out": "#8B5CF6", "out_text": "#FFFFFF"},
    "orange": {"name": "暖橙",   "out": "#F59E0B", "out_text": "#3B2503"},
    "pink":   {"name": "樱花粉", "out": "#F472B6", "out_text": "#FFFFFF"},
}


def bubble_scheme(scheme_key: str) -> dict:
    return BUBBLE_SCHEMES.get(scheme_key, BUBBLE_SCHEMES["blue"])
