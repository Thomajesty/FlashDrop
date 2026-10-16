# -*- coding: utf-8 -*-
"""v1.18.11 安卓端交付截图（PIL 像素级还原 Java 布局参数）。

由于无法在 Windows 上运行 Android 模拟器，这里按 MainActivity.java 里
**真实的 dp 数值** 用 PIL 重绘，用于验证：
  1. 顶部设备行对齐（#68）—— 名称左、✕ 最右、✕ 与状态灯有间距
  2. 表情面板（#71）—— 中文页签 + Fluent Emoji 网格 + 计数
  3. 输入栏顺序（#71）—— 相册 · 表情 · 输入框 · ＋ · 发送

产出到 tests/：
  android_devicelist.png / android_emoji_panel.png / android_inputbar.png
"""
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CATALOG = os.path.join(ROOT, "app", "src", "main", "assets", "emoji_catalog.json")
EMOJI_DIR = os.path.join(ROOT, "app", "src", "main", "res", "drawable-nodpi")

DP = 3  # 假设 xxhdpi（1dp = 3px）

# 与 EmojiPicker.java 的 GROUP_CN 保持逐字一致
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

# ── 主题（FdTheme DARK，与 Java 端一致）
BG = (11, 12, 16)
BAR = (31, 33, 38)
CARD = (38, 41, 48)
BORDER = (52, 56, 64)
TEXT = (232, 234, 238)
DIM = (140, 146, 156)
ACCENT = (59, 130, 246)
GREEN = (34, 197, 94)
YELLOW = (245, 158, 11)


def font(size, bold=False):
    for name in (("msyhbd.ttc" if bold else "msyh.ttc"), "simhei.ttf",
                 "segoeui.ttf"):
        p = os.path.join("C:\\Windows\\Fonts", name)
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def font_emoji(size):
    p = os.path.join("C:\\Windows\\Fonts", "seguiemj.ttf")
    if os.path.exists(p):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return font(size)


def dpx(v):
    return int(round(v * DP))


def draw_check(d, cx, cy, r, color):
    """矢量对勾（避免字体缺字）"""
    w = max(2, int(r * 0.34))
    d.line([(cx - r * 0.42, cy + r * 0.02),
            (cx - r * 0.10, cy + r * 0.36),
            (cx + r * 0.46, cy - r * 0.34)],
           fill=color, width=w, joint="curve")


def draw_cross(d, cx, cy, r, color, w=None):
    """矢量叉号"""
    w = w or max(2, int(r * 0.30))
    d.line([(cx - r * 0.42, cy - r * 0.42), (cx + r * 0.42, cy + r * 0.42)],
           fill=color, width=w)
    d.line([(cx + r * 0.42, cy - r * 0.42), (cx - r * 0.42, cy + r * 0.42)],
           fill=color, width=w)


# ─────────────────────────────────────────────────────────────
# 1) 顶部设备列表（#68）
# ─────────────────────────────────────────────────────────────
def shot_devicelist():
    W = dpx(250)
    ROW_H = dpx(40)
    rows = [
        ("我的手机 (HaoPhone)", "在线", GREEN, True),
        ("客厅台式 (HaoStation)", "在线", GREEN, True),
        ("笔记本 (ThinkPad)", "离线", DIM, False),
        ("平板 (HaoPad)", "忙碌", YELLOW, False),
    ]
    H = dpx(30) + ROW_H * len(rows) + dpx(14)
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)

    d.text((dpx(14), dpx(9)), "设备列表", font=font(dpx(6), True), fill=TEXT)

    f_name = font(dpx(7), False)
    f_mid = font(dpx(5), False)
    f_dot = font(dpx(5), False)

    for i, (name, status, color, checked) in enumerate(rows):
        top = dpx(30) + i * ROW_H
        # 选择框背景
        d.rounded_rectangle([dpx(8), top + dpx(2), W - dpx(8), top + ROW_H - dpx(2)],
                            radius=dpx(8),
                            fill=(24, 27, 33) if i == 0 else BG,
                            outline=BORDER if i == 0 else None)
        # 复选圆点
        cx = dpx(8) + dpx(14)
        cy = top + ROW_H // 2
        r = dpx(8)
        d.ellipse([cx - r, cy - r, cx + r, cy + r],
                  fill=ACCENT if checked else (44, 48, 56))
        if checked:
            draw_check(d, cx, cy, r * 0.92, (255, 255, 255))

        # 名称（左对齐，紧跟复选点 + 8dp）
        nx = cx + r + dpx(8)
        d.text((nx, cy - dpx(6.5)), name, font=f_name, fill=TEXT)

        # ★ 关键：✕ 在最右端，与状态灯之间留 10dp
        x_size = dpx(13)
        x_right = W - dpx(12)
        x_left = x_right - x_size
        draw_cross(d, x_left + x_size / 2, cy, x_size * 0.86, DIM)

        # 状态灯（9dp 圆点），位于 ✕ 左侧 10dp
        dot_x = x_left - dpx(10) - dpx(9)
        dd = dpx(4.5)
        d.ellipse([dot_x - dd, cy - dd, dot_x + dd, cy + dd], fill=color)

        # 状态文字，位于灯左侧 8dp（右对齐）
        tw = d.textlength(status, font=f_mid)
        d.text((dot_x - dpx(8) - tw, cy - dpx(4.5)), status, font=f_mid, fill=color)

        if i < len(rows) - 1:
            d.line([dpx(14), top + ROW_H, W - dpx(14), top + ROW_H],
                   fill=(30, 33, 39))

    out = os.path.join(HERE, "android_devicelist.png")
    im.save(out)
    print("devicelist:", im.width, "x", im.height, "->", out)


# ─────────────────────────────────────────────────────────────
# 2) 表情面板（#71）
# ─────────────────────────────────────────────────────────────
def shot_emoji_panel():
    with open(CATALOG, "r", encoding="utf-8") as f:
        cat = json.load(f)
    groups = cat["groups"]

    W = dpx(250)
    COLS = 8
    CELL = dpx(40)
    TAB_H = dpx(34)
    HINT_H = dpx(26)
    grid_h = CELL * 5
    H = TAB_H + grid_h + HINT_H + dpx(16)

    im = Image.new("RGB", (W, H), BAR)
    d = ImageDraw.Draw(im)

    f_tab = font(dpx(6.5), False)
    f_tab_on = font(dpx(6.5), True)
    f_hint = font(dpx(5.5), False)

    # 页签行
    x = dpx(8)
    y = dpx(4)
    for gi, g in enumerate(groups[:8]):
        label = GROUP_CN.get(g["name"], g["name"])   # ★ 运行时中文化
        tw = d.textlength(label, font=f_tab_on if gi == 0 else f_tab)
        pad = dpx(6)
        bw = tw + pad * 2
        if x + bw > W - dpx(8):
            break
        if gi == 0:
            d.rounded_rectangle([x, y, x + bw, y + TAB_H - dpx(8)],
                                radius=dpx(6), fill=CARD)
        d.text((x + pad, y + dpx(5)), label,
               font=f_tab_on if gi == 0 else f_tab, fill=TEXT if gi == 0 else DIM)
        x += bw + dpx(4)

    # 网格（第一组「表情」）
    emojis = groups[1]["emojis"] if len(groups) > 1 else groups[0]["emojis"]
    gy = TAB_H
    fx = font_emoji(int(CELL * 0.72))
    for idx, e in enumerate(emojis[:COLS * 5]):
        r, c = divmod(idx, COLS)
        cx = c * CELL + CELL // 2
        cy = gy + r * CELL + CELL // 2
        slug = e["slug"].replace("-", "_")
        p = os.path.join(EMOJI_DIR, "e_%s.png" % slug)
        if os.path.exists(p):
            ico = Image.open(p).convert("RGBA")
            s = int(CELL * 0.66)
            ico = ico.resize((s, s), Image.LANCZOS)
            im.paste(ico, (cx - s // 2, cy - s // 2), ico)
        else:
            d.text((cx - dpx(6), cy - dpx(7)), e.get("char", "?"),
                   font=fx, fill=TEXT)

    # 底部计数
    cnt = len(emojis)
    d.text((dpx(12), H - HINT_H + dpx(4)),
           "表情 · 共 %d 个" % cnt, font=f_hint, fill=DIM)

    out = os.path.join(HERE, "android_emoji_panel.png")
    im.save(out)
    print("emoji panel:", im.width, "x", im.height,
          "| group=", GROUP_CN.get(groups[1]["name"], groups[1]["name"]),
          "n=", cnt, "->", out)


# ─────────────────────────────────────────────────────────────
# 3) 输入栏（#71 顺序：相册 · 表情 · 输入框 · ＋ · 发送）
# ─────────────────────────────────────────────────────────────
def shot_inputbar():
    W = dpx(250)
    H = dpx(56)
    im = Image.new("RGB", (W, H), BAR)
    d = ImageDraw.Draw(im)

    # 相册
    d.rounded_rectangle([dpx(10), dpx(14), dpx(34), dpx(38)],
                        radius=dpx(6), fill=CARD)
    d.text((dpx(16), dpx(18)), "🖼", font=font_emoji(dpx(10)), fill=TEXT)
    # ★ 表情（相册右侧、输入框左侧）
    d.rounded_rectangle([dpx(40), dpx(14), dpx(64), dpx(38)],
                        radius=dpx(6), fill=CARD)
    d.text((dpx(45), dpx(18)), "😀", font=font_emoji(dpx(10)), fill=TEXT)
    # 输入框
    d.rounded_rectangle([dpx(72), dpx(12), W - dpx(72), dpx(40)],
                        radius=dpx(10), fill=CARD, outline=BORDER)
    d.text((dpx(82), dpx(21)), "输入消息…", font=font(dpx(6)), fill=DIM)
    # ＋
    d.text((W - dpx(66), dpx(17)), "＋", font=font(dpx(11), True), fill=DIM)
    # 发送
    d.rounded_rectangle([W - dpx(56), dpx(12), W - dpx(10), dpx(40)],
                        radius=dpx(10), fill=ACCENT)
    tw = d.textlength("发送", font=font(dpx(6), True))
    tx = ((W - dpx(56)) + (W - dpx(10))) / 2 - tw / 2
    d.text((tx, dpx(21)), "发送", font=font(dpx(6), True), fill=(255, 255, 255))

    out = os.path.join(HERE, "android_inputbar.png")
    im.save(out)
    print("inputbar:", im.width, "x", im.height, "->", out)


if __name__ == "__main__":
    shot_devicelist()
    shot_emoji_panel()
    shot_inputbar()
    print("OK")
