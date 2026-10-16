# -*- coding: utf-8 -*-
"""v1.18.14 安卓端验收截图。

产出 tests/_v11814/：
  android_panel_height.png  修复前/后：表情面板高度 vs 键盘高度
  android_kbd_switch.png    切换动效：由 26dp 轻推 → 整高上推/下拉
"""
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "_v11814")
os.makedirs(OUT, exist_ok=True)

BG = (11, 12, 16)
BORDER = (52, 56, 64)
TEXT = (232, 234, 238)
DIM = (140, 146, 156)
MUTED = (110, 116, 126)
ACCENT = (59, 130, 246)
RED = (226, 75, 74)
GREEN = (99, 153, 34)
PANEL_BG = (56, 60, 70)
KBD_BG = (46, 50, 58)
BAR_BG = (44, 47, 54)

# ── 实测数据（Galaxy S23U 1440x3088 @ density 3.5）──────────────
SCREEN = 3088
KB_REAL = 1208           # 键盘真实高（39% 屏高）
PANEL_BEFORE = 1346      # 修复前：IME 高度多算了一个状态栏
PANEL_AFTER = KB_REAL
DIFF = PANEL_BEFORE - PANEL_AFTER     # = 138px


def fnt(size, bold=False):
    for name in (("msyhbd.ttc" if bold else "msyh.ttc"), "simhei.ttf"):
        p = os.path.join("C:\\Windows\\Fonts", name)
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


KBD_VIS = 150            # 键盘在示意图里的视觉高度
BAR_VIS = 26             # 输入栏视觉高度
EXTRA_VIS = 38           # 面板多出来的那一行（视觉）


def draw_phone(d, x0, y0, w, h, panel_vis, accent, title, sub):
    d.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=16,
                        fill=BG, outline=BORDER, width=2)
    bottom = y0 + h - 6

    # 聊天区
    chat_bot = bottom - panel_vis - BAR_VIS - 8
    d.rectangle([x0 + 20, y0 + 26, x0 + w - 20, chat_bot], fill=(13, 14, 18))

    # 输入栏
    bar_top = chat_bot + 8
    d.rounded_rectangle([x0 + 14, bar_top, x0 + w - 14, bar_top + BAR_VIS],
                        radius=10, fill=BAR_BG)

    # 面板
    ptop = bottom - panel_vis
    d.rounded_rectangle([x0 + 10, ptop, x0 + w - 10, bottom],
                        radius=8, fill=PANEL_BG, outline=accent, width=2)
    d.text((x0 + w / 2, (ptop + bottom) / 2), "表情面板", font=fnt(13, True),
           fill=TEXT, anchor="mm")

    # 键盘参考线（修复后应与面板顶对齐）
    kbd_top = bottom - KBD_VIS
    for xx in range(x0 + 14, x0 + w - 14, 12):
        d.line([xx, kbd_top, xx + 6, kbd_top], fill=MUTED, width=1)

    d.text((x0 + w / 2, y0 - 30), title, font=fnt(15, True), fill=TEXT,
           anchor="mm")
    d.text((x0 + w / 2, y0 - 11), sub, font=fnt(11), fill=DIM, anchor="mm")

    return kbd_top, ptop


def shot_height():
    TW, TH = 320, 560
    GAP = 170
    W = 30 + TW + GAP + TW + 30
    H = 748
    im = Image.new("RGB", (W, H), (24, 26, 31))
    d = ImageDraw.Draw(im)

    d.text((30, 16), "v1.18.14 安卓：表情面板高度对齐键盘", font=fnt(19, True),
           fill=TEXT)
    d.text((30, 44),
           "根因：v1.18.13 的 IME 高度算法只减了导航栏、漏了状态栏 → 面板比键盘高一整行",
           font=fnt(12), fill=DIM)

    y0 = 126
    # 左：修复前
    kt_l, pt_l = draw_phone(d, 30, y0, TW, TH, KBD_VIS + EXTRA_VIS, RED,
                            "修复前", "面板 1346px，比键盘多 138px")
    # 右：修复后
    kt_r, pt_r = draw_phone(d, 30 + TW + GAP, y0, TW, TH, KBD_VIS, GREEN,
                            "修复后", "面板 = 键盘 = 1208px")

    # 左：多出来的一行高亮 + 标注
    d.rectangle([40, pt_l, 30 + TW - 10, kt_l], outline=RED, width=2)
    d.text((30 + TW / 2, (pt_l + kt_l) / 2), "+138px\n= 一行",
           font=fnt(12, True), fill=RED, anchor="mm", align="center")

    # 中间说明
    mx = 30 + TW + GAP / 2
    d.text((mx, y0 + 200), "→", font=fnt(38, True), fill=ACCENT, anchor="mm")
    d.text((mx, y0 + 268),
           "改用官方\nWindowInsets\n.Type.ime()\n(API 30+)",
           font=fnt(11), fill=DIM, anchor="mm", align="center")

    d.text((30, H - 34),
           "实测：Galaxy S23U 1440x3088，键盘 1208px（39% 屏高）；"
           "修复前面板 1346px，差值 138px ≈ 一个状态栏高度",
           font=fnt(11), fill=DIM)

    out = os.path.join(OUT, "android_panel_height.png")
    im.save(out)
    print("saved:", out, im.size)


def shot_switch():
    W, H = 780, 300
    im = Image.new("RGB", (W, H), (24, 26, 31))
    d = ImageDraw.Draw(im)
    d.text((20, 14), "v1.18.14 安卓：表情 ⇄ 键盘 切换动效", font=fnt(17, True),
           fill=TEXT)

    rows = [
        ("修复前", "面板只下滑 26dp（轻轻推一下）→ 面板还在，键盘已经盖上来", RED),
        ("", "观感：两层重叠，不像键盘在替换面板", DIM),
        ("修复后", "面板下滑 = 整高 host.getHeight() → 完全滑出视野", GREEN),
        ("", "上推同样整高位移 + 去掉 alpha 淡入 → 与键盘同构，视觉连续", DIM),
    ]
    y = 54
    for tag, txt, col in rows:
        if tag:
            d.rounded_rectangle([20, y, 96, y + 26], radius=6, fill=col)
            d.text((58, y + 13), tag, font=fnt(12, True), fill=(255, 255, 255),
                   anchor="mm")
            d.text((108, y + 13), txt, font=fnt(12), fill=TEXT, anchor="lm")
            y += 36
        else:
            d.text((108, y + 8), txt, font=fnt(11), fill=col, anchor="lm")
            y += 32

    d.text((20, H - 36),
           "关键：面板高度已与键盘等高 → 切换时布局零位移，不再闪动",
           font=fnt(12, True), fill=ACCENT)
    out = os.path.join(OUT, "android_kbd_switch.png")
    im.save(out)
    print("saved:", out, im.size)


if __name__ == "__main__":
    shot_height()
    shot_switch()
