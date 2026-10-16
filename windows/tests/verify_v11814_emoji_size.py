# -*- coding: utf-8 -*-
"""v1.18.14 验收 —— Windows 表情图标实际渲染尺寸（像素级，最高优先级门槛）。

为什么必须有这个测试：
  v1.18.10 / v1.18.12 / v1.18.13 三次「把表情放大」都没生效，因为
  theme.py 的全局 `QToolButton { padding: 4px 14px; }` 会作用到 Qt.Popup
  里的 44px 表情格子，把内容区压到 14px，QIcon 被 Qt 缩小到 14px。
  纯静态断言（看源码里 ICON_PAD 是多少）**测不出这个问题** ——
  只有真渲染 + 量像素才拦得住。

断言：
  ① 每个表情格子按钮自身样式表含 padding: 0px（修复手段）
  ② 在「应用级 QSS」这种最坏情况下渲染面板，图标可视宽度 >= 22px（微信实测 22~24px）
  ③ 渲染出的面板仍是 10 列 / pitch 44（没把布局改坏）

运行：python tests/verify_v11814_emoji_size.py
"""
import os
import sys
import tempfile

os.environ.pop("QT_QPA_PLATFORM", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

P, F = [], []


def check(name, cond, detail=""):
    (P if cond else F).append(name)
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", name,
                          ("   " + detail) if (detail and not cond) else ""))


# 关键：把 build_qss 挂到 QApplication 级 —— 复现打包 EXE 里
# 全局 QSS 会作用到 popup 的最坏情况。修复必须在这种环境下依然生效。
from app.ui import theme as TH

app.setStyleSheet(TH.build_qss(TH.resolve_theme("light")))

tmp = tempfile.mkdtemp(prefix="fd_v11814_")
os.environ["FLASHDROP_DATA_DIR"] = tmp

from app.config import Config
from app.node import FlashNode
from app.ui.main_window import MainWindow

cfg = Config()
cfg["theme"] = "light"
cfg["save_dir"] = tmp
win = MainWindow(cfg, FlashNode(cfg))
win.resize(1100, 740)
win.show()
for _ in range(8):
    app.processEvents()

win.emoji_btn.click()
for _ in range(12):
    app.processEvents()

pnl = win.emoji_btn._panel
OUT = os.path.join(ROOT, "tests", "_v11814")
os.makedirs(OUT, exist_ok=True)
pm = pnl.grab()
pm.save(os.path.join(OUT, "verify_panel_light.png"))

print("=" * 70)
print("v1.18.14 Windows 表情图标渲染尺寸验收")
print("=" * 70)

# ---------- ① 按钮自身样式表 ----------
cells = []
for i in range(pnl._grid.count()):
    w = pnl._grid.itemAt(i).widget()
    if w is not None:
        cells.append(w)
check("① 网格里存在表情格子", len(cells) > 0, "count=%d" % len(cells))
if cells:
    bad = [c for c in cells if "padding: 0px" not in (c.styleSheet() or "")]
    check("① 所有格子自带 padding:0 样式（%d 个）" % len(cells),
          not bad, "有 %d 个格子未设置" % len(bad))
    check("① 格子 objectName = EmojiCell",
          all((c.objectName() or "") == "EmojiCell" for c in cells))
    sz = cells[0].iconSize()
    check("① iconSize = CELL - ICON_PAD = %d px" % (44 - 16),
          sz.width() == 44 - 16 and sz.height() == 44 - 16,
          "实际 %dx%d" % (sz.width(), sz.height()))

# ---------- ② 渲染像素 ----------
img = pm.toImage()
W, H = img.width(), img.height()


def colorful(x, y):
    c = img.pixelColor(x, y)
    return max(c.red(), c.green(), c.blue()) - min(c.red(), c.green(), c.blue()) > 40


rows = [sum(1 for x in range(W) if colorful(x, y)) for y in range(H)]
mx = max(rows) if rows else 0
band, cur = None, None
for y, v in enumerate(rows):
    if v > mx * 0.3:
        if cur is None:
            cur = y
    else:
        if cur is not None:
            band = (cur, y)
            break

if band:
    y0, y1 = band
    xs = [x for x in range(W) if any(colorful(x, y) for y in range(y0, y1))]
    groups, cur, prev = [], None, None
    for x in xs:
        if cur is None:
            cur = x
        elif x - prev > 6:
            groups.append((cur, prev))
            cur = x
        prev = x
    if cur is not None:
        groups.append((cur, prev))
    ws = [b - a + 1 for a, b in groups]
    ps = [groups[i + 1][0] - groups[i][0] for i in range(len(groups) - 1)]
    med = sorted(ws)[len(ws) // 2] if ws else 0
    print("    面板 %dx%d  第一行 %d 颗  图标宽 %s"
          % (pm.width(), pm.height(), len(groups), ws))
    check("② 图标可视宽度 >= 22px（微信实测 22~24）", med >= 22,
          "实际中位 %dpx" % med)
    check("② 图标可视高度 >= 20px", (y1 - y0) >= 20, "实际 %dpx" % (y1 - y0))
    # ---------- ③ 布局没坏 ----------
    check("③ 仍是 10 列", len(groups) == 10, "实际 %d" % len(groups))
    if ps:
        med_p = sorted(ps)[len(ps) // 2]
        check("③ 列 pitch 仍为 44", med_p == 44, "实际 %d" % med_p)
    check("③ 面板宽 464", pm.width() == 464, "实际 %d" % pm.width())
else:
    check("② 渲染出可测量的表情行", False, "未检出彩色行")

win.close()

print()
print("=" * 70)
if F:
    print("失败项：")
    for f in F:
        print("  - %s" % f)
print("v1.18.14 图标尺寸验收：通过 %d 项，失败 %d 项" % (len(P), len(F)))
print("=" * 70)
sys.exit(1 if F else 0)
