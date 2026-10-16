# -*- coding: utf-8 -*-
"""v1.18.9 专项：截图按钮下箭头是否重复 —— 像素级放大裁决

用户在 v1.18.8 反馈"下箭头多了一个/重复了"。
本脚本把截图按钮区域放大 8 倍导出，并检测按钮文本区右侧是否出现
**两个** 独立的下三角墨迹块（自绘 '▾' 字符 + Qt InstantPopup 指示器）。
"""
import os, sys, tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.abspath(ROOT)
sys.path.insert(0, ROOT)

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QPainter, QColor, QFont, QPen, QImage
from PySide6.QtWidgets import QApplication, QToolButton

app = QApplication.instance() or QApplication([])
tmp = tempfile.mkdtemp(prefix="fd_arrow_")
os.environ["FLASHDROP_DATA_DIR"] = tmp

from app.config import Config
from app.node import FlashNode
from app.ui.main_window import MainWindow

OUT = os.path.dirname(os.path.abspath(__file__))
fails = []
checks = 0


def ck(cond, label, extra=""):
    global checks
    checks += 1
    print(f"  [{'OK ' if cond else 'FAIL'}] {label} {extra}")
    if not cond:
        fails.append(label)


for theme in ("light", "dark"):
    print(f"--- theme={theme} ---")
    cfg = Config()
    cfg["theme"] = theme
    cfg["save_dir"] = tmp
    win = MainWindow(cfg, FlashNode(cfg))
    win.resize(1180, 760)
    win.show()
    app.processEvents()
    app.processEvents()

    arrows = [b for b in win.input_panel.findChildren(QToolButton)
              if b.objectName() == "SnipArrow"]
    mains = [b for b in win.input_panel.findChildren(QToolButton)
             if b.objectName() == "SnipMain"]
    ck(len(arrows) == 1, "截图下拉三角按钮唯一", f"count={len(arrows)}")
    ck(len(mains) == 1, "截图主按钮唯一", f"count={len(mains)}")
    if not arrows or not mains:
        win.close()
        continue

    arrow, main = arrows[0], mains[0]
    # 1) 文本层：'▾' 只出现一次
    ck(arrow.text().count("▾") == 1,
       "三角按钮文本只含 1 个 '▾'", f"text={arrow.text()!r}")
    ck("▾" not in main.text(),
       "主按钮文本不含 '▾'", f"text={main.text()!r}")

    # 2) 是否让 Qt 再画一个内建指示器：InstantPopup + arrowType
    ck(arrow.popupMode() == QToolButton.InstantPopup,
       "三角按钮为 InstantPopup（会画内建指示器）")
    ck(arrow.arrowType() == Qt.NoArrow,
       "已显式关闭 Qt 内建箭头（NoArrow）",
       f"arrowType={arrow.arrowType()}")

    # 3) 像素检测：统计按钮区域内"独立墨迹簇"数量。
    #    注意：离屏字体可能把 '▾' 渲染成 ▯(tofu 方框)，此刻一条中线上
    #    会出现 [左壁, 空腔, 右壁] 三段 —— 必须按**二维连通簇**判定，
    #    不能按单行游程，否则把 1 个方框误判成 3 个箭头。
    pm = arrow.grab()
    img = pm.toImage().convertToFormat(QImage.Format_RGB32)
    w, h = img.width(), img.height()

    # 阈值改用**相对**判定：先取四角像素的亮度作为按钮底色，
    # 与底色差异超过 60 的才算墨迹。这样深/浅主题都不用调参，
    # 也不会把按钮自身的底色块当成箭头。
    def lum(x, y):
        c = QColor(img.pixel(x, y))
        return 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()

    bg = min(lum(1, 1), lum(w - 2, 1), lum(1, h - 2), lum(w - 2, h - 2))
    bg = max(bg, lum(w // 2, 1), lum(1, h // 2))
    diff_thr = 60

    def is_dark(x, y):
        return abs(lum(x, y) - bg) > diff_thr

    print(f"    底色亮度={bg:.1f}  差异阈值={diff_thr}")

    # 只在**中央区域**找墨迹，避开按钮自身的圆角/边框（四周 3px 内不收）
    pad = 4
    seen = [[False] * w for _ in range(h)]
    clusters = []
    for y0 in range(pad, h - pad):
        for x0 in range(pad, w - pad):
            if seen[y0][x0] or not is_dark(x0, y0):
                continue
            # BFS 4-邻域
            stack = [(x0, y0)]
            seen[y0][x0] = True
            pts = []
            while stack:
                x, y = stack.pop()
                pts.append((x, y))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if (pad <= nx < w - pad and pad <= ny < h - pad
                            and not seen[ny][nx] and is_dark(nx, ny)):
                        seen[ny][nx] = True
                        stack.append((nx, ny))
            # 忽略噪点：像素数太少的簇不算
            if len(pts) >= 6:
                xs = [q[0] for q in pts]
                clusters.append((min(xs), max(xs), len(pts)))
    clusters.sort()
    print(f"    三角按钮 {w}x{h}  二维墨迹簇={clusters}（bg={bg:.0f}）")
    ck(len(clusters) <= 1,
       "三角按钮内只有 1 个墨迹簇（无重复箭头）",
       f"clusters={len(clusters)} detail={clusters}")

    # 4) 放大导出便于肉眼复核
    big = pm.scaled(pm.width() * 8, pm.height() * 8,
                    Qt.KeepAspectRatio, Qt.FastTransformation)
    p = QPainter(big)
    f = QFont("Microsoft YaHei UI"); f.setPixelSize(14); f.setBold(True)
    p.setFont(f); p.setPen(QColor("#ef4444"))
    p.drawText(4, 18, f"SnipArrow 8x  theme={theme}")
    p.end()
    o = os.path.join(OUT, f"shots_v1189_arrow8x_{theme}.png")
    big.save(o, "PNG")
    print(f"    -> {o}")

    # 5) 整条工具行（含组合按钮）也导一张
    pm2 = win.input_panel.grab()
    p2 = QPainter(pm2)
    p2.setFont(QFont("Microsoft YaHei UI", 9))
    p2.setPen(QPen(QColor("#ef4444"), 2))
    for b in (main, arrow):
        tl = b.mapTo(win.input_panel, b.rect().topLeft())
        r = QRect(tl, b.size())
        p2.drawRect(r.adjusted(0, 0, -1, -1))
        p2.setPen(QColor("#ef4444"))
        p2.drawText(r.left(), r.top() - 3, f"{b.objectName()} w={r.width()}")
        p2.setPen(QPen(QColor("#ef4444"), 2))
    p2.end()
    o2 = os.path.join(OUT, f"shots_v1189_snip_{theme}.png")
    pm2.save(o2, "PNG")
    print(f"    -> {o2}")

    win.close()

print("\n" + "=" * 56)
print(f"截图箭头专项：{checks - len(fails)}/{checks} 通过")
if fails:
    print("失败项：")
    for f_ in fails:
        print("  -", f_)
    sys.exit(1)
print("结论：截图按钮下箭头无重复 ✓")
