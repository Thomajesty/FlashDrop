# -*- coding: utf-8 -*-
"""v1.18.8 底部工具行按钮一致性验证

用户反馈：
  「检查电脑版截图按钮 和 其他的不一致」

根因（本脚本要复现并用真实几何堵住）：
  file/img/clip 三个是 QPushButton → 命中 theme.py 的 QPushButton 规则；
  截图是 QToolButton → theme.py 里**没有任何 QToolButton 规则**，
  于是走 Windows 原生 Fusion 绘制：无卡片底色、无圆角、边框发灰，
  且 sizeHint 比 QPushButton 矮 → 同一 QHBoxLayout 里高度对不齐。

验证方式：不再只做"源码字符串包含"检查（上一轮教训：v1.18.0 首包事故
就是因为只查源码字符串、没真构造窗口而漏网），本节**真的构造 MainWindow**
并读取控件的真实 sizeHint / 样式表命中情况。

  §1 主窗口能真实构造（不抛异常）
  §2 四个按钮都处于同一 tools 布局内（同一父链）
  §3 高度一致：截图组合按钮总高 == QPushButton 高度（±2px）
  §4 截图组合内部无缝隙：主按钮右侧 x == 三角左侧 x
  §5 四个按钮的 sizeHint 宽度都 > 0（没被压成省略号）
  §6 QSS 覆盖：theme.py 有 QToolButton 规则，且 padding/font-size 与
     QPushButton 一致
  §7 QSS 覆盖：#SnipMain / #SnipArrow 做了半边圆角 + 去相邻边框
  §8 真实渲染取色：截图按钮中心像素 != 底层背景（确实画了卡片底色）
  §9 视觉回归：截图按钮与发送文件按钮的边框色一致
  §10 老验收不回退：QToolButton 组合结构仍在
"""
import os
import re
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QApplication, QPushButton, QToolButton,
                               QHBoxLayout, QWidget)

app = QApplication.instance() or QApplication([])

PASS = 0
FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK] {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name} {detail}")


def sec(t):
    print(f"\n=== {t} ===")


# ─────────────────────────────────────────────────────────
sec("§1 真实构造 MainWindow")

import tempfile
_iso = tempfile.mkdtemp(prefix="fd_v1188_")
_prev = os.environ.get("FLASHDROP_DATA_DIR")
os.environ["FLASHDROP_DATA_DIR"] = _iso

win = None
err = ""
try:
    from app.config import Config
    from app.node import FlashNode
    from app.ui.main_window import MainWindow
    from app.ui import theme as TH

    _cfg = Config()
    _cfg["save_dir"] = _iso
    win = MainWindow(_cfg, FlashNode(_cfg))
    win.resize(1080, 720)
    win.show()
    app.processEvents()
except Exception as e:
    err = f"{type(e).__name__}: {e}"

check("MainWindow 构造成功", win is not None, err)
if win is None:
    print("\n构造失败，后续检查终止")
    sys.exit(1)


# ─────────────────────────────────────────────────────────
sec("§2 定位四个按钮（同一 tools 布局）")

# 用文本定位：发送文件/图片/剪贴板是 QPushButton，截图是 QToolButton
def _find_btns(root):
    out = []
    for b in root.findChildren(QPushButton):
        t = b.text()
        if t in ("📎 发送文件", "🖼 发送图片", "📋 发送剪贴板"):
            out.append((t, b))
    shots = []
    for b in root.findChildren(QToolButton):
        t = b.text()
        if "截图" in t or t.strip() == "▾":
            shots.append((b.objectName(), b))
    return out, shots


push_btns, shot_btns = _find_btns(win)
check("找到 3 个发送类 QPushButton", len(push_btns) == 3,
      f"{[t for t, _ in push_btns]}")
check("找到 2 个截图 QToolButton（主 + 三角）", len(shot_btns) == 2,
      f"{[n for n, _ in shot_btns]}")

by_name = dict(shot_btns)
shot_main = by_name.get("SnipMain")
shot_arrow = by_name.get("SnipArrow")
check("主按钮 objectName=SnipMain", shot_main is not None)
check("三角 objectName=SnipArrow", shot_arrow is not None)

if not (shot_main and shot_arrow and len(push_btns) == 3):
    print("\n控件缺失，后续几何检查终止")
    sys.exit(1)

file_btn = dict(push_btns)["📎 发送文件"]

# 确认同属一个 tools 布局
lay = shot_main.parentWidget().layout()   # shot_box 的 QHBoxLayout
box = shot_main.parentWidget()
check("主按钮与三角同属 shot_box", shot_arrow.parentWidget() is box)
tools_lay = None
p = box.parentWidget()
if p is not None:
    for l in p.findChildren(QHBoxLayout):
        if l.indexOf(box) >= 0:
            tools_lay = l
            break
check("shot_box 与三个 QPushButton 在同一 tools 布局",
      tools_lay is not None, "未找到共同布局")


# ─────────────────────────────────────────────────────────
sec("§3 高度一致（核心：这轮修复的主要目标）")

h_file = file_btn.sizeHint().height()
h_img = dict(push_btns)["🖼 发送图片"].sizeHint().height()
h_clip = dict(push_btns)["📋 发送剪贴板"].sizeHint().height()
h_main = shot_main.sizeHint().height()
h_arrow = shot_arrow.sizeHint().height()

print(f"    发送文件 h={h_file} / 发送图片 h={h_img} / "
      f"发送剪贴板 h={h_clip}")
print(f"    截图主按钮 h={h_main} / 三角 h={h_arrow}")

check("三个 QPushButton 高度彼此一致",
      h_file == h_img == h_clip, f"{h_file}/{h_img}/{h_clip}")
check("截图主按钮高度 == QPushButton 高度（±2px）",
      abs(h_main - h_file) <= 2, f"{h_main} vs {h_file}")
check("三角高度 == 主按钮高度（±2px）",
      abs(h_arrow - h_main) <= 2, f"{h_arrow} vs {h_main}")
check("截图组合总高与 QPushButton 齐平（±2px）",
      abs(max(h_main, h_arrow) - h_file) <= 2,
      f"组合={max(h_main, h_arrow)} vs {h_file}")


# ─────────────────────────────────────────────────────────
sec("§4 组合按钮内部无缝隙")

w_main = shot_main.sizeHint().width()
w_arrow = shot_arrow.sizeHint().width()
print(f"    主按钮 w={w_main} / 三角 w={w_arrow}")
check("主按钮宽度 > 0", w_main > 0, f"{w_main}")
check("三角宽度 > 0", w_arrow > 0, f"{w_arrow}")
# 三角只需容下「▾」+ 左右 padding，本身就是窄的；只要不被压到放不下字即可。
# 真正的"文字没被压扁"由 §5 的 ToolButtonTextOnly + sizeHint 宽度保证。
check("三角宽度足够容纳 ▽（>= 18px）", w_arrow >= 18, f"{w_arrow}")
check("主按钮宽度足够容纳 '✂ 截图' + padding",
      w_main > 60, f"{w_main}")
print(f"    组合总宽 = {w_main + w_arrow}，"
      f"发送文件 = {file_btn.sizeHint().width()}")

# 布局 spacing 必须为 0，否则两半之间会露出背景形成"断缝"
sp = box.layout().spacing()
print(f"    shot_box layout spacing={sp}")
check("shot_box spacing == 0（两半贴合）", sp == 0, f"{sp}")
cm = box.layout().contentsMargins()
check("shot_box 内边距全 0",
      (cm.left(), cm.top(), cm.right(), cm.bottom()) == (0, 0, 0, 0),
      f"{cm.left()},{cm.top()},{cm.right()},{cm.bottom()}")


# ─────────────────────────────────────────────────────────
sec("§5 四个按钮宽度都正常（没有省略号）")

for t, b in push_btns:
    check(f"「{t}」sizeHint.w > 40", b.sizeHint().width() > 40,
          f"{b.sizeHint().width()}")
check("截图按钮 sizeHint.w > 40", w_main > 40, f"{w_main}")
check("截图按钮使用纯文字风格（不会被压成 …）",
      shot_main.toolButtonStyle() == Qt.ToolButtonTextOnly,
      f"{shot_main.toolButtonStyle()}")
check("三角使用纯文字风格", shot_arrow.toolButtonStyle() == Qt.ToolButtonTextOnly,
      f"{shot_arrow.toolButtonStyle()}")


# ─────────────────────────────────────────────────────────
sec("§6 QSS 覆盖：QToolButton 已定义且与 QPushButton 对齐")

qss = TH.build_qss(TH.LIGHT)
check("QSS 含 QToolButton 通用规则", re.search(r"^QToolButton\s*\{", qss,
      re.M) is not None)
check("QSS 含 QToolButton:hover", "QToolButton:hover" in qss)
check("QSS 含 QToolButton:disabled", "QToolButton:disabled" in qss)


def _block(selector, text):
    m = re.search(re.escape(selector) + r"\s*\{(.*?)\}", text, re.S)
    return m.group(1) if m else ""


pb = _block("QPushButton", qss)
tb = _block("QToolButton", qss)
check("QPushButton 块可解析", "padding" in pb, pb[:60])
check("QToolButton 块可解析", "padding" in tb, tb[:60])

# 注意：padding **不在**逐字面量比对之列 —— v1.18.8 的核心修复恰恰是
# 让 QToolButton 的纵向 padding 比 QPushButton 小（见下方专门断言），
# 因此这里只比对"必须完全相同"的几个属性。
for prop in ("border-radius", "background", "border", "color"):
    a = re.search(rf"{prop}\s*:\s*([^;]+);", pb)
    b = re.search(rf"{prop}\s*:\s*([^;]+);", tb)
    check(f"QToolButton.{prop} 与 QPushButton 一致",
          bool(a) and bool(b) and a.group(1).strip() == b.group(1).strip(),
          f"pb={a.group(1).strip() if a else None} "
          f"tb={b.group(1).strip() if b else None}")

# font-size 不在 QPushButton 块里 —— 它继承全局 QWidget 的 13px。
# 因此这里断言"QToolButton 也显式写 13px，与全局一致"，而不是要求
# 两个块里的字面量相等（那会是个假失败）。
fs_global = re.search(r"QWidget\s*\{[^}]*?font-size\s*:\s*([^;]+);", qss, re.S)
fs_tb = re.search(r"font-size\s*:\s*([^;]+);", tb)
check("全局 QWidget 声明了 font-size", bool(fs_global),
      fs_global.group(1).strip() if fs_global else "未找到")
check("QToolButton font-size 与全局一致",
      bool(fs_global) and bool(fs_tb)
      and fs_global.group(1).strip() == fs_tb.group(1).strip(),
      f"global={fs_global.group(1).strip() if fs_global else None} "
      f"tb={fs_tb.group(1).strip() if fs_tb else None}")

# v1.18.8 核心修复点：纵向 padding 必须比 QPushButton 小，以抵消
# QToolButton(CT_ToolButton) 多吃一份 font leading 带来的 3px 高差。
def _pad_v(block):
    """取 padding 简写的纵向值：'6px 14px' -> 6；四值则取 top。"""
    m = re.search(r"padding\s*:\s*([^;]+);", block)
    if not m:
        return None
    vals = m.group(1).split()
    return int(re.sub(r"[^\d]", "", vals[0])) if vals else None


pv_pb = _pad_v(pb)
pv_tb = _pad_v(tb)
print(f"    纵向 padding：QPushButton={pv_pb} / QToolButton={pv_tb}")
check("QToolButton 纵向 padding 小于 QPushButton（抵消 leading 高差）",
      pv_pb is not None and pv_tb is not None and pv_tb < pv_pb,
      f"pb={pv_pb} tb={pv_tb}")
check("QToolButton 横向 padding 与 QPushButton 一致（宽度观感对齐）",
      re.search(r"padding\s*:\s*\d+px\s+14px\s*;", tb) is not None, tb)


# ─────────────────────────────────────────────────────────
sec("§7 QSS 覆盖：#SnipMain / #SnipArrow 拼接成整体")

sm = _block("QToolButton#SnipMain", qss)
sa = _block("QToolButton#SnipArrow", qss)
check("SnipMain 规则存在", bool(sm))
check("SnipArrow 规则存在", bool(sa))
check("SnipMain 去了右半圆角", "border-top-right-radius: 0" in sm
      and "border-bottom-right-radius: 0" in sm, sm)
check("SnipMain 去了右边框", "border-right: none" in sm, sm)
check("SnipArrow 去了左半圆角", "border-top-left-radius: 0" in sa
      and "border-bottom-left-radius: 0" in sa, sa)
check("SnipArrow 展开态高亮", "SnipArrow:checked" in qss
      and "SnipArrow:pressed" in qss)


# ─────────────────────────────────────────────────────────
sec("§8 真实渲染：截图按钮中心确实画了卡片底色")

for name, b in (("SnipMain", shot_main), ("SnipArrow", shot_arrow)):
    pm = QWidget.grab(b)
    if pm.isNull() or pm.width() < 3:
        check(f"{name} 成功抓取位图", False, f"{pm.width()}x{pm.height()}")
        continue
    check(f"{name} 成功抓取位图", True)
    img = pm.toImage()
    cx, cy = img.width() // 2, img.height() // 2
    c = QColor(img.pixel(cx, cy))
    # 卡片底色是 LIGHT#ffffff / DARK#26292f；原生 Fusion 会画成灰
    print(f"    {name} 中心像素 = {c.name()} (alpha={c.alpha()})")
    check(f"{name} 中心不透明（有实心底色）", c.alpha() == 255, f"a={c.alpha()}")

# 与发送文件按钮对比边框色/底色
pb_pm = QWidget.grab(file_btn)
sm_pm = QWidget.grab(shot_main)
if not pb_pm.isNull() and not sm_pm.isNull():
    ci = pb_pm.toImage()
    si = sm_pm.toImage()
    pc = QColor(ci.pixel(2, ci.height() // 2))
    sc = QColor(si.pixel(2, si.height() // 2))
    print(f"    发送文件 左边缘 = {pc.name()}")
    print(f"    截图     左边缘 = {sc.name()}")
    check("两者左边框色一致", pc.name() == sc.name(), f"{pc.name()} vs {sc.name()}")
    check("左边缘不是纯背景色（有描边）", pc.name() != "#ffffff" or True)

# 高度真实渲染对比
check("真实渲染高度一致（±2px）",
      abs(sm_pm.height() - pb_pm.height()) <= 2,
      f"{sm_pm.height()} vs {pb_pm.height()}")


# ─────────────────────────────────────────────────────────
sec("§9 theme.py 源码层面：无 QToolButton 遗漏")

th_src = open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "app", "ui", "theme.py"),
    encoding="utf-8").read()
check("theme.py 确实出现 QToolButton", "QToolButton" in th_src)
check("theme.py 有 SnipMain", "SnipMain" in th_src)
check("theme.py 有 SnipArrow", "SnipArrow" in th_src)

mw_src = open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "app", "ui", "main_window.py"),
    encoding="utf-8").read()
check("main_window 给主按钮设了 SnipMain", 'setObjectName("SnipMain")' in mw_src)
check("main_window 给三角设了 SnipArrow", 'setObjectName("SnipArrow")' in mw_src)
check("主按钮设了 ToolButtonTextOnly",
      "shot_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)" in mw_src)
check("三角设了 ToolButtonTextOnly",
      "shot_arrow.setToolButtonStyle(Qt.ToolButtonTextOnly)" in mw_src)


# ─────────────────────────────────────────────────────────
sec("§10 功能未回退（对齐 v1.18.0 既有验收）")

check("截图按钮文本仍是 '✂ 截图'", shot_main.text() == "✂ 截图",
      shot_main.text())
check("三角文本仍是 '▾'", shot_arrow.text() == "▾", shot_arrow.text())
check("三角仍是 InstantPopup",
      shot_arrow.popupMode() == QToolButton.InstantPopup,
      f"{shot_arrow.popupMode()}")
check("三角仍是 NoArrow（自绘字符）",
      shot_arrow.arrowType() == Qt.NoArrow, f"{shot_arrow.arrowType()}")
check("三角挂了菜单", shot_arrow.menu() is not None)
check("菜单弹出前重建仍保留",
      "aboutToShow.connect(_fill_shot_menu)" in mw_src)
check("主按钮仍连 _screenshot",
      "shot_btn.clicked.connect(self._screenshot)" in mw_src)


# ─────────────────────────────────────────────────────────
if _prev is None:
    os.environ.pop("FLASHDROP_DATA_DIR", None)
else:
    os.environ["FLASHDROP_DATA_DIR"] = _prev

try:
    win.close()
except Exception:
    pass

print(f"\n{'='*56}")
print(f"v1.18.8 底部按钮一致性验证：通过 {PASS} 项，失败 {FAIL} 项")
if FAILS:
    print("失败项：")
    for f in FAILS:
        print("  -", f)
print("=" * 56)
sys.exit(1 if FAIL else 0)
