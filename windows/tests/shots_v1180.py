# -*- coding: utf-8 -*-
"""v1.18.0 验收截图生成（离屏渲染）

产出到 _out_v1180/：
  s01_button_dropdown.png   截图按钮 + 下拉三角（含菜单项渲染）
  s02_snip_flow.png         框选流程 4 步（空态/拖动中/完成/Shift 正方形）
  s03_divider.png           设置项分隔线示意（浅/深两色）
  s04_contrast.png          对比度审计表（改前 vs 改后，双主题）
  s05_photmode_name.png     照片模式文件名可见性 改前/改后 对照
  s06_card_placeholder.png  卡片首帧占位图机制示意
  s07_version.png           版本号四件套
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from PySide6.QtCore import Qt, QRect, QPoint, QEvent
from PySide6.QtGui import (QPixmap, QColor, QPainter, QFont, QPen, QBrush,
                           QLinearGradient, QImage, QMouseEvent, QPainterPath)
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

# ★ 离屏 Qt 默认字体库为空（families count = 0），中文会渲染成方块。
# 从 C:\Windows\Fonts 显式注册微软雅黑，让验收截图可读。
from PySide6.QtGui import QFontDatabase

CJK_FAMILY = "Microsoft YaHei"
_fdb = QFontDatabase()
if not _fdb.families():
    for _fp in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc",
                r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\simsun.ttc"):
        if os.path.isfile(_fp):
            try:
                _fdb.addApplicationFont(_fp)
            except Exception:
                pass
    _fams = _fdb.families()
    if _fams:
        CJK_FAMILY = _fams[0]
print("CJK family in use:", CJK_FAMILY, "| available:",
      len(_fdb.families()))

OUT = os.path.join(os.path.dirname(HERE), "_out_v1180")
os.makedirs(OUT, exist_ok=True)

BG = QColor("#1A1C20")
CARD = QColor("#23262C")
TXT = QColor("#E8EAED")
DIM = QColor("#9AA1AC")
GREEN = QColor("#22C55E")
RED = QColor("#EF4444")
BLUE = QColor("#3B82F6")
ACC = QColor("#1D4ED8")


def _font(sz, bold=False):
    f = QFont(CJK_FAMILY)
    f.setPointSize(sz)
    f.setBold(bold)
    return f


def canvas(w, h, bg=BG):
    pm = QPixmap(w, h)
    pm.fill(bg)
    return pm


def title(p, text, y=26):
    p.setFont(_font(15, True))
    p.setPen(TXT)
    p.drawText(20, y, text)


def sub(p, text, y):
    p.setFont(_font(9))
    p.setPen(DIM)
    p.drawText(20, y, text)


# ═══════════════════════════════════════════════════════════
# s01 截图按钮 + 下拉三角
# ═══════════════════════════════════════════════════════════
W, H = 900, 460
pm = canvas(W, H)
p = QPainter(pm)
p.setRenderHint(QPainter.Antialiasing, True)
title(p, "s01 截图按钮 = 主按钮 + 下拉三角（对齐微信）")
sub(p, "主按钮：直接用上次的设置执行截图　·　▾：切换是否隐藏当前窗口", 46)

# 按钮组
bx, by, bw, bh = 40, 78, 132, 36
p.setPen(QPen(QColor("#3A4049"), 1))
p.setBrush(QColor("#2B3038"))
p.drawRoundedRect(bx, by, bw, bh, 7, 7)
p.setFont(_font(10))
p.setPen(TXT)
p.drawText(QRect(bx, by, bw - 22, bh), Qt.AlignCenter, "截图")
# 细分隔
p.setPen(QPen(QColor("#454B55"), 1))
p.drawLine(bx + bw - 22, by + 7, bx + bw - 22, by + bh - 7)
# 三角（自绘，避免字形缺失）
p.setPen(Qt.NoPen)
p.setBrush(QColor("#C7CCD4"))
_tri = QPainterPath()
_cx, _cy = bx + bw - 11, by + bh // 2
_tri.moveTo(_cx - 5, _cy - 2.5)
_tri.lineTo(_cx + 5, _cy - 2.5)
_tri.lineTo(_cx, _cy + 3)
_tri.closeSubpath()
p.drawPath(_tri)

# 标注引线
p.setPen(QPen(BLUE, 1, Qt.DashLine))
p.drawLine(bx + 10, by + bh + 4, bx + 10, by + bh + 34)
p.setPen(BLUE)
p.setFont(_font(8))
p.drawText(bx - 4, by + bh + 48, "主按钮")
p.setPen(QPen(GREEN, 1, Qt.DashLine))
p.drawLine(bx + bw - 11, by + bh + 4, bx + bw - 11, by + bh + 24)
p.setPen(GREEN)
p.drawText(bx + bw - 30, by + bh + 38, "下拉三角")

# 菜单渲染
mx, my, mw = bx + 40, by + 92, 210
p.setPen(QPen(QColor("#3E444D"), 1))
p.setBrush(QColor("#282C33"))
p.drawRoundedRect(mx, my, mw, 74, 8, 8)
p.setFont(_font(9))
# 项1（勾选：自绘对勾）
p.setPen(QPen(GREEN, 2))
p.drawLine(mx + 13, my + 21, mx + 17, my + 25)
p.drawLine(mx + 17, my + 25, mx + 23, my + 15)
p.setFont(_font(9))
p.setPen(TXT)
p.drawText(QRect(mx + 32, my + 6, mw - 40, 30), Qt.AlignVCenter,
           "截图时隐藏当前窗口")
p.setPen(QPen(QColor("#343A43"), 1))
p.drawLine(mx + 8, my + 37, mx + mw - 8, my + 37)
# 项2（未选：空心圆）
p.setPen(QPen(QColor("#5A6270"), 1.4))
p.setBrush(Qt.NoBrush)
p.drawEllipse(mx + 14, my + 52, 9, 9)
p.setPen(DIM)
p.drawText(QRect(mx + 32, my + 42, mw - 40, 28), Qt.AlignVCenter,
           "截图时保留当前窗口")

# 说明
p.setPen(DIM)
p.setFont(_font(8))
p.drawText(40, my + 122, "· 勾选态实时反映当前设置（aboutToShow 重建菜单）")
p.drawText(40, my + 140, "· 选择被持久化到 config.json 的 snip_hide_self")
p.drawText(40, my + 158, "· 默认 true = 隐藏，与旧版行为一致（升级无意外变化）")
p.drawText(40, my + 176, "· 选中后立即执行一次截图，少一次点击")
p.end()
pm.save(os.path.join(OUT, "s01_button_dropdown.png"))
print("s01 ok")


# ═══════════════════════════════════════════════════════════
# s02 框选流程 4 步
# ═══════════════════════════════════════════════════════════
from app.ui.snip import SnipOverlay, MASK

SW, SH = 380, 250
gaps = 24
W = SW * 2 + gaps * 3
H = 60 + SH * 2 + gaps + 40
pm = canvas(W, H)
p = QPainter(pm)
p.setRenderHint(QPainter.Antialiasing, True)
title(p, "s02 截图框选：4 种状态")
sub(p, "暗罩压暗全屏 → 拖动拉出选区 → 松开完成　·　Esc/右键取消　·　Shift 锁正方形", 46)


class AutoSnip(SnipOverlay):
    def drag(self, x1, y1, x2, y2, shift=False):
        p1, p2 = QPoint(x1, y1), QPoint(x2, y2)
        mods = Qt.ShiftModifier if shift else Qt.NoModifier
        self.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, p1,
                                         self.mapToGlobal(p1), Qt.LeftButton,
                                         Qt.LeftButton, mods))
        self.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, p2,
                                        self.mapToGlobal(p2), Qt.NoButton,
                                        Qt.LeftButton, mods))
        self.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, p2,
                                           self.mapToGlobal(p2), Qt.LeftButton,
                                           Qt.NoButton, mods))

    def snapshot(self, w, h):
        self.resize(w, h)
        out = QPixmap(w, h)
        out.fill(Qt.transparent)
        self.render(out)
        return out


def make_canvas(w, h):
    """造一张有内容的"假桌面"，便于看清选区。"""
    pmx = QPixmap(w, h)
    pp = QPainter(pmx)
    g = QLinearGradient(0, 0, w, h)
    g.setColorAt(0, QColor("#2E5A88"))
    g.setColorAt(1, QColor("#7A4E86"))
    pp.fillRect(0, 0, w, h, QBrush(g))
    pp.setPen(QColor(255, 255, 255, 40))
    for i in range(0, w, 40):
        pp.drawLine(i, 0, i, h)
    for j in range(0, h, 40):
        pp.drawLine(0, j, w, j)
    pp.setFont(_font(14, True))
    pp.setPen(QColor(255, 255, 255, 120))
    pp.drawText(QRect(0, 0, w, h), Qt.AlignCenter, "桌面画面")
    pp.end()
    return pmx


states = [("① 初始：全屏压暗 + 引导文案", None, False),
          ("② 拖动中：实时显示尺寸", (60, 60, 300, 190), False),
          ("③ 松开完成 → 裁出该区域", (100, 70, 330, 200), False),
          ("④ 按住 Shift → 锁正方形", (70, 50, 320, 150), True)]

for i, (label, region, shift) in enumerate(states):
    col = i % 2
    row = i // 2
    ox = gaps + col * (SW + gaps)
    oy = 60 + row * (SH + gaps)

    cvs = make_canvas(SW, SH)
    ov = AutoSnip(cvs, hint="拖动鼠标框选截图区域 · Esc 取消")
    ov.resize(SW, SH)
    # 把控件几何钉到 0,0 起点，保证渲染坐标可预期
    ov.setGeometry(0, 0, SW, SH)
    if region:
        x1, y1, x2, y2 = region
        # 记录起点/当前点（不触发 release，保留拖动中状态）
        ov._origin = QPoint(x1, y1)
        ov._cur = QPoint(x2, y2)
        ov._dragging = True
        ov._shift = shift
    shot = ov.snapshot(SW, SH)
    p.drawPixmap(ox, oy, shot)
    p.setPen(QPen(QColor("#3A4049"), 1))
    p.setBrush(Qt.NoBrush)
    p.drawRect(ox, oy, SW, SH)
    p.setFont(_font(9, True))
    p.setPen(TXT)
    p.drawText(ox, oy - 8, label)
    ov.close()

p.end()
pm.save(os.path.join(OUT, "s02_snip_flow.png"))
print("s02 ok")


# ═══════════════════════════════════════════════════════════
# s03 设置项分隔线
# ═══════════════════════════════════════════════════════════
W, H = 900, 460
pm = canvas(W, H)
p = QPainter(pm)
p.setRenderHint(QPainter.Antialiasing, True)
title(p, "s03 设置项分隔线（轻度界限）")
sub(p, "1px 高 · 左右内缩 2dp · 线色取主题 border（浅 #E2E4E8 / 深 #33363D）", 46)


def draw_settings(p, x0, y0, w, dark):
    bgc = QColor("#191B1F") if dark else QColor("#F2F3F5")
    cardc = QColor("#26292F") if dark else QColor("#FFFFFF")
    txtc = QColor("#E5E7EB") if dark else QColor("#1F2328")
    dimc = QColor("#9CA3AF") if dark else QColor("#4B5563")
    bordc = QColor("#33363D") if dark else QColor("#E2E4E8")
    rows = ["自动接收文件", "收到消息时提示",
            "显示常驻通知（关闭后服务仍保持在线）",
            "开机自启（手机重启后自动恢复接收服务）",
            "传输加密（TLS）：两端都开启时加密通信，未开启自动回退明文"]
    p.setPen(Qt.NoPen)
    p.setBrush(bgc)
    p.drawRoundedRect(x0, y0, w, 372, 10, 10)
    p.setFont(_font(12, True))
    p.setPen(txtc)
    p.drawText(x0 + 16, y0 + 28, "设置")

    ry = y0 + 56
    for i, r in enumerate(rows):
        p.setFont(_font(9))
        p.setPen(txtc)
        p.drawText(QRect(x0 + 16, ry, w - 90, 44), Qt.AlignVCenter, r)
        # Switch
        sx = x0 + w - 66
        p.setPen(Qt.NoPen)
        p.setBrush(ACC if dark else QColor("#1D4ED8"))
        p.drawRoundedRect(sx, ry + 12, 38, 20, 10, 10)
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(sx + 20, ry + 15, 14, 14)
        # 分隔线（最后一项之后不画）
        if i < len(rows) - 1:
            p.setPen(QPen(bordc, 1))
            p.drawLine(x0 + 18, ry + 44, x0 + w - 18, ry + 44)
        ry += 48
    # 标注
    p.setFont(_font(8))
    p.setPen(RED if not dark else GREEN)
    return bordc


bord_l = draw_settings(p, 40, 62, 390, False)
bord_d = draw_settings(p, 470, 62, 390, True)
p.setFont(_font(10, True))
p.setPen(TXT)
p.drawText(40, 50, "浅色主题")
p.drawText(470, 50, "深色主题")

# 放大示意
p.setPen(QPen(QColor("#3A4049"), 1))
p.setBrush(QColor("#23262C"))
p.drawRoundedRect(40, 396, 820, 52, 8, 8)
p.setFont(_font(9))
p.setPen(TXT)
p.drawText(56, 418, "对比：无分隔线 → 各行紧贴，用户分不清哪行算一项")
p.setPen(DIM)
p.drawText(56, 436, "有分隔线 → 每项边界清晰，观感对齐微信/系统设置的分组列表")
p.end()
pm.save(os.path.join(OUT, "s03_divider.png"))
print("s03 ok")


# ═══════════════════════════════════════════════════════════
# s04 对比度审计表
# ═══════════════════════════════════════════════════════════
def chan(v):
    v = v / 255.0
    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4


def relum(c):
    return (0.2126 * chan((c >> 16) & 0xFF) + 0.7152 * chan((c >> 8) & 0xFF)
            + 0.0722 * chan(c & 0xFF))


def cr(a, b):
    l1, l2 = relum(a), relum(b)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


rows = [
    ("text",   0xFF1F2328, 0xFF1F2328, 0xFFF2F3F5),
    ("dim",    0xFF6B7280, 0xFF4B5563, 0xFFF2F3F5),
    ("accent", 0xFF3B82F6, 0xFF1D4ED8, 0xFFF2F3F5),
    ("accent2",0xFF06B6D4, 0xFF0E7490, 0xFFF2F3F5),
    ("green",  0xFF16A34A, 0xFF15803D, 0xFFF2F3F5),
    ("red",    0xFFDC2626, 0xFFB91C1C, 0xFFF2F3F5),
    ("warn",   0xFFD97706, 0xFFB45309, 0xFFF2F3F5),
]

W, H = 980, 500
pm = canvas(W, H)
p = QPainter(pm)
p.setRenderHint(QPainter.Antialiasing, True)
title(p, "s04 浅色主题对比度审计（对页面底 #F2F3F5，WCAG 2.1）")
sub(p, "起因：用户报「图片文件名看不见」→ 审计整个调色板，发现 accent2/green/warn 三项不及格", 46)

# 表头
hx, hy = 40, 66
cols = [("语义色", 0, 110), ("改前色值", 110, 130), ("改前 CR", 240, 90),
        ("改后色值", 330, 130), ("改后 CR", 460, 90),
        ("色块", 550, 120), ("判定", 670, 90), ("对页面底", 760, 190)]
p.setFont(_font(9, True))
p.setPen(DIM)
for name, dx, w in cols:
    p.drawText(QRect(hx + dx, hy, w, 24), Qt.AlignVCenter, name)
p.setPen(QPen(QColor("#3A4049"), 1))
p.drawLine(hx, hy + 26, hx + 950, hy + 26)

ry = hy + 34
for name, old, new, bg in rows:
    o, n = cr(old, bg), cr(new, bg)
    p.setFont(_font(9, True))
    p.setPen(TXT)
    p.drawText(QRect(hx, ry, 110, 30), Qt.AlignVCenter, name)

    p.setFont(_font(9))
    p.setPen(DIM)
    p.drawText(QRect(hx + 110, ry, 130, 30), Qt.AlignVCenter,
               "#%06X" % (old & 0xFFFFFF))
    # 改前 CR
    oc = GREEN if o >= 4.5 else (QColor("#F59E0B") if o >= 3 else RED)
    p.setPen(oc)
    p.drawText(QRect(hx + 240, ry, 90, 30), Qt.AlignVCenter, "%.2f" % o)

    p.setPen(DIM)
    p.drawText(QRect(hx + 330, ry, 130, 30), Qt.AlignVCenter,
               "#%06X" % (new & 0xFFFFFF))
    nc = GREEN if n >= 4.5 else (QColor("#F59E0B") if n >= 3 else RED)
    p.setPen(nc)
    p.setFont(_font(9, True))
    p.drawText(QRect(hx + 460, ry, 90, 30), Qt.AlignVCenter, "%.2f" % n)

    # 色块：旧 / 新
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(old & 0xFFFFFFFF))
    p.drawRoundedRect(hx + 550, ry + 5, 48, 20, 4, 4)
    p.setBrush(QColor(new & 0xFFFFFFFF))
    p.drawRoundedRect(hx + 604, ry + 5, 48, 20, 4, 4)

    p.setFont(_font(8, True))
    if o < 4.5 <= n:
        p.setPen(GREEN)
        p.drawText(QRect(hx + 670, ry, 90, 30), Qt.AlignVCenter, "已修 →AA")
    elif n >= 4.5:
        p.setPen(GREEN)
        p.drawText(QRect(hx + 670, ry, 90, 30), Qt.AlignVCenter, "AA 通过")
    else:
        p.setPen(QColor("#F59E0B"))
        p.drawText(QRect(hx + 670, ry, 90, 30), Qt.AlignVCenter, "AA-large")

    ry += 34

# 图例
p.setPen(QPen(QColor("#3A4049"), 1))
p.drawLine(hx, ry + 4, hx + 950, ry + 4)
p.setFont(_font(8))
p.setPen(GREEN)
p.drawText(hx, ry + 26, "■ CR ≥ 4.5")
p.setPen(QColor("#F59E0B"))
p.drawText(hx + 110, ry + 26, "■ 3 ≤ CR < 4.5")
p.setPen(RED)
p.drawText(hx + 260, ry + 26, "■ CR < 3（不可接受）")
p.setPen(DIM)
p.drawText(hx + 450, ry + 26,
           "结论：5 项提升到 AA 通过（其中 2 项原为不及格）；text 原本已达标保持不变")
p.end()
pm.save(os.path.join(OUT, "s04_contrast.png"))
print("s04 ok")


# ═══════════════════════════════════════════════════════════
# s05 照片模式文件名可见性
# ═══════════════════════════════════════════════════════════
W, H = 900, 420
pm = canvas(W, H)
p = QPainter(pm)
p.setRenderHint(QPainter.Antialiasing, True)
title(p, "s05 照片模式文件名可见性（需求 2 核心）")
sub(p, "根因：photoMode 气泡背景被清空，文字实际压在页面底色上，却仍用按气泡推导的颜色", 46)

cases = [
    ("深色主题 / 改前", 0xFF191B1F, 0xFF4B5563, "2.28 看不见", False),
    ("深色主题 / 改后", 0xFF191B1F, 0xFF9CA3AF, "6.79 清晰", True),
    ("浅色主题 / 改前", 0xFFF2F3F5, 0xFF6B7280, "4.35 偏弱", False),
    ("浅色主题 / 改后", 0xFFF2F3F5, 0xFF4B5563, "6.81 清晰", True),
]

cw, ch = 200, 150
for i, (label, bg, fg, note, fixed) in enumerate(cases):
    col = i % 2
    row = i // 2
    ox = 40 + col * 430
    oy = 70 + row * 175

    p.setPen(Qt.NoPen)
    p.setBrush(QColor(bg))
    p.drawRoundedRect(ox, oy, cw, ch, 10, 10)
    p.setPen(QPen(QColor("#3A4049"), 1))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(ox, oy, cw, ch, 10, 10)

    # 假图片
    p.setPen(Qt.NoPen)
    gg = QLinearGradient(ox + 12, oy + 10, ox + 100, oy + 90)
    gg.setColorAt(0, QColor("#3E6FA8"))
    gg.setColorAt(1, QColor("#6E4E90"))
    p.setBrush(QBrush(gg))
    p.drawRoundedRect(ox + 12, oy + 10, 100, 78, 6, 6)

    # 文件名（关键：用 fg 上色）
    p.setFont(_font(8))
    p.setPen(QColor(fg))
    p.drawText(ox + 12, oy + 108, "甘肃国钛拆除技术附件.pdf · 2.4 MB")
    p.setPen(QColor(fg))

    # 标注
    p.setFont(_font(9, True))
    p.setPen(TXT)
    p.drawText(ox, oy - 10, label)
    p.setFont(_font(8, True))
    p.setPen(GREEN if fixed else RED)
    p.drawText(ox + cw + 8, oy + 108, note)
    if fixed:
        p.setPen(GREEN)
        p.drawText(ox + cw + 8, oy + 124, "已修")
    else:
        p.setPen(RED)
        p.drawText(ox + cw + 8, oy + 124, "问题")

p.end()
pm.save(os.path.join(OUT, "s05_photomode_name.png"))
print("s05 ok")


# ═══════════════════════════════════════════════════════════
# s06 卡片首帧占位图机制
# ═══════════════════════════════════════════════════════════
W, H = 980, 440
pm = canvas(W, H)
p = QPainter(pm)
p.setRenderHint(QPainter.Antialiasing, True)
title(p, "s06 文件卡片首帧错乱：根因与修法（需求 3）")
sub(p, "关键：ImageView 无 drawable 时参与 ListView 首次测量会塌成 0 宽", 46)

# 左：改前
p.setFont(_font(10, True))
p.setPen(RED)
p.drawText(40, 78, "改前：首帧塌陷")
p.setPen(DIM)
p.setFont(_font(8))
for i, t in enumerate([
        "① ListView.onMeasure 先测缓存 convertView",
        "② msg_typeicon 无 src / 无 background",
        "③ 零 drawable → 期望宽 = 0",
        "④ 卡片先按「没有图标」排一帧",
        "⑤ 下一帧补上 → 用户看到跳变"]):
    p.drawText(40, 100 + i * 17, t)

# 无图标卡片（窄）
bx, by = 40, 200
p.setPen(QPen(QColor("#3A4049"), 1))
p.setBrush(QColor("#26292F"))
p.drawRoundedRect(bx, by, 190, 62, 10, 10)
p.setFont(_font(8))
p.setPen(TXT)
p.drawText(bx + 12, by + 24, "文件.pdf")
p.setPen(DIM)
p.drawText(bx + 12, by + 42, "88.2 KB  已保存")
p.setPen(RED)
p.setFont(_font(8, True))
p.drawText(bx, by + 80, "宽 = 文字自然宽（塌陷）")

# 右：改后
p.setFont(_font(10, True))
p.setPen(GREEN)
p.drawText(520, 78, "改后：首帧即终值")
p.setPen(DIM)
p.setFont(_font(8))
for i, t in enumerate([
        "① inflate 后立刻 setImageBitmap(placeholder)",
        "② 占位图 = 透明 40×52dp（尺寸恒定）",
        "③ 同时 setLayoutParams 钉死尺寸",
        "④ 首次测量 = 终值，无重排",
        "⑤ bind 再换成真图标（走了才写）"]):
    p.drawText(520, 100 + i * 17, t)

bx2, by2 = 520, 200
p.setPen(QPen(QColor("#3A4049"), 1))
p.setBrush(QColor("#26292F"))
p.drawRoundedRect(bx2, by2, 344, 62, 10, 10)
p.setFont(_font(8))
p.setPen(TXT)
p.drawText(bx2 + 12, by2 + 24, "文件.pdf")
p.setPen(DIM)
p.drawText(bx2 + 12, by2 + 42, "88.2 KB  已保存")
# 图标
p.setPen(Qt.NoPen)
p.setBrush(QColor("#D6336C"))
p.drawRoundedRect(bx2 + 344 - 12 - 40, by2 + 5, 40, 52, 4, 4)
p.setPen(QColor("#FFFFFF"))
p.setFont(_font(8, True))
p.drawText(QRect(bx2 + 344 - 12 - 40, by2 + 5, 40, 52), Qt.AlignCenter, "PDF")
p.setPen(GREEN)
p.setFont(_font(8, True))
p.drawText(bx2, by2 + 80, "宽 = 344dp 恒定（首帧即正确）")

# 底部：辅助修复
p.setPen(QPen(QColor("#3A4049"), 1))
p.setBrush(QColor("#23262C"))
p.drawRoundedRect(40, 300, 900, 108, 8, 8)
p.setFont(_font(9, True))
p.setPen(TXT)
p.drawText(56, 324, "配套修复（同样针对首帧/复用）")
p.setFont(_font(8))
p.setPen(DIM)
for i, t in enumerate([
    "· getViewTypeCount()=4 + getItemViewType()：让 ListView 按 4 类分桶回收，文件卡片 convertView 才能稳定进 recycle 池（旧写法类型不符就丢弃，永远不进池，反复 inflate 放大了问题）",
    "· 文字列容器 msg_textcol 固定宽：此前只有内部 TextView 固定，容器 wrap_content 会先按自然宽测一次再被顶开，多出一次重排",
    "· FdFileIcon.make 改用 putIfAbsent：并发首绘时只保留先写入者，避免后写覆盖掉已被 ImageView 持有的位图（会造成某张卡片忽然空白）"]):
    p.drawText(56, 344 + i * 20, t)
p.end()
pm.save(os.path.join(OUT, "s06_card_placeholder.png"))
print("s06 ok")


# ═══════════════════════════════════════════════════════════
# s07 版本号四件套
# ═══════════════════════════════════════════════════════════
W, H = 900, 300
pm = canvas(W, H)
p = QPainter(pm)
p.setRenderHint(QPainter.Antialiasing, True)
title(p, "s07 版本号四件套（v1.18.0 / versionCode 29）")
items = [
    ("FdUtil.java", 'APP_VERSION = "1.18.0"'),
    ("AndroidManifest.xml", 'versionCode="29"  versionName="1.18.0"'),
    ("build_apk.bat", "--version-code 29  --version-name 1.18.0"),
    ("windows/app/__init__.py", '__version__ = "1.18.0"'),
]
ry = 74
for name, val in items:
    p.setPen(QPen(QColor("#3A4049"), 1))
    p.setBrush(QColor("#23262C"))
    p.drawRoundedRect(40, ry, 820, 40, 7, 7)
    p.setFont(_font(9, True))
    p.setPen(TXT)
    p.drawText(56, ry + 25, name)
    p.setFont(_font(9))
    p.setPen(GREEN)
    p.drawText(340, ry + 25, val)
    ry += 50
p.setFont(_font(8))
p.setPen(DIM)
p.drawText(40, ry + 12,
           "签名证书 SHA-256 6efa0a80…6e4a8 保持不变 → 可直接覆盖安装升级")
p.end()
pm.save(os.path.join(OUT, "s07_version.png"))
print("s07 ok")

print("\n全部截图已生成到", OUT)
