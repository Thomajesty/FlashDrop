# -*- coding: utf-8 -*-
"""真实环境下量表情图标尺寸（复现用户场景：MainWindow 全局 QSS + Qt.Popup 面板）。

用法：
    python tests/probe_emoji_size.py                # 仅 MainWindow 级样式
    python tests/probe_emoji_size.py light          # 指定主题
    python tests/probe_emoji_size.py light appqss   # ★ 把 build_qss 挂到 QApplication
                                                    #   （复现打包 EXE 里全局 QSS 压到 popup 的情况）

产出 tests/_v11814/real_panel_<theme>.png，并打印第一行每颗表情的外接框宽度。
"""
import os
import sys
import tempfile

os.environ.pop("QT_QPA_PLATFORM", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

tmp = tempfile.mkdtemp(prefix="fd_probe_")
os.environ["FLASHDROP_DATA_DIR"] = tmp

from app.config import Config
from app.node import FlashNode
from app.ui import theme as TH
from app.ui.main_window import MainWindow

theme = sys.argv[1] if len(sys.argv) > 1 else "light"
use_app_qss = "appqss" in sys.argv
suffix = "_appqss" if use_app_qss else ""

if use_app_qss:
    app.setStyleSheet(TH.build_qss(TH.resolve_theme(theme)))
cfg = Config()
cfg["theme"] = theme
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
pm = pnl.grab()
outdir = os.path.join(ROOT, "tests", "_v11814")
os.makedirs(outdir, exist_ok=True)
out = os.path.join(outdir, "real_panel_%s%s.png" % (theme, suffix))
pm.save(out)

print("=" * 66)
print("真实环境表情面板：[%s]%s" % (theme, " + 应用级QSS" if use_app_qss else ""))
print("=" * 66)
print("  面板尺寸 = %d x %d" % (pm.width(), pm.height()))
print("  图片 -> %s" % out)
print("  _EmojiButton.iconSize() = %s"
      % (win.emoji_btn._panel._grid.itemAt(0).widget().iconSize()
         if win.emoji_btn._panel._grid.count() else "n/a"))

img = pm.toImage()
W, H = img.width(), img.height()


def colorful(x, y):
    c = img.pixelColor(x, y)
    return max(c.red(), c.green(), c.blue()) - min(c.red(), c.green(), c.blue()) > 40


rows = [sum(1 for x in range(W) if colorful(x, y)) for y in range(H)]
mx = max(rows)
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
    print()
    print("  第一表情行带 y=%d~%d  可见高=%d px" % (y0, y1, y1 - y0))
    print("  列数     = %d" % len(groups))
    print("  图标宽   = %s" % ws)
    if ps:
        print("  列 pitch = %s" % ps)
    if ws:
        print("  >>> 中位图标宽 = %d px" % sorted(ws)[len(ws) // 2])
else:
    print("  未检出表情行")

win.close()
