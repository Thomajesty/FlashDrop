# -*- coding: utf-8 -*-
"""v1.18.12 安卓端交付截图（按 Java/XML 真实参数用 PIL 还原）。

产出 tests/：
  v11812_inputbar.png     输入栏：相册 | 输入框 | 表情 | ＋/发送
  v11812_emoji_panel.png  键盘区表情面板（常用表情行 + 页签 + 网格）
  v11812_switch.png       表情⇄键盘 图标互切对比
"""
import json
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CATALOG = os.path.join(ROOT, "app", "src", "main", "assets", "emoji_catalog.json")
EMOJI_DIR = os.path.join(ROOT, "app", "src", "main", "res", "drawable-nodpi")

DP = 3

GROUP_CN = {
    "Smileys & Emotion": "表情", "People & Body": "人物",
    "Animals & Nature": "动物", "Food & Drink": "食物",
    "Travel & Places": "旅行", "Activities": "活动",
    "Objects": "物品", "Symbols": "符号", "Flags": "旗帜", "Other": "其他",
}

BG = (11, 12, 16)
BAR = (31, 33, 38)
CARD = (38, 41, 48)
BORDER = (52, 56, 64)
TEXT = (232, 234, 238)
DIM = (140, 146, 156)
ACCENT = (59, 130, 246)
INPUT_BG = (44, 47, 54)


def fnt(size, bold=False):
    for name in (("msyhbd.ttc" if bold else "msyh.ttc"), "simhei.ttf"):
        p = os.path.join("C:\\Windows\\Fonts", name)
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def dpx(v):
    return int(round(v * DP))


def load_emoji(slug, size):
    p = os.path.join(EMOJI_DIR, "e_%s.png" % slug.replace("-", "_"))
    if not os.path.exists(p):
        return None
    im = Image.open(p).convert("RGBA")
    return im.resize((size, size), Image.LANCZOS)


def paste_emoji(canvas, slug, cx, cy, size):
    ico = load_emoji(slug, size)
    if ico is None:
        return False
    canvas.paste(ico, (cx - size // 2, cy - size // 2), ico)
    return True


# ─────────────────────────────────────────────────────────────
# 1) 输入栏：相册 | 输入框 | 表情 | ＋
# ─────────────────────────────────────────────────────────────
def shot_inputbar():
    W = dpx(250)
    H = dpx(58)
    im = Image.new("RGB", (W, H), BAR)
    d = ImageDraw.Draw(im)

    # 胶囊背景
    d.rounded_rectangle([dpx(8), dpx(8), W - dpx(8), H - dpx(10)],
                        radius=dpx(12), fill=INPUT_BG)

    # 相册（左）——用矢量图标而非 emoji 字形（PIL 的 emoji 字体渲染不稳）
    d.rounded_rectangle([dpx(16), dpx(19), dpx(40), dpx(43)],
                        radius=dpx(6), fill=CARD)
    # 画一个"山 + 太阳"的相册图形
    ax, ay = dpx(28), dpx(31)
    d.rectangle([ax - dpx(8), ay - dpx(6), ax + dpx(8), ay + dpx(6)],
                outline=TEXT, width=dpx(1.2))
    d.ellipse([ax + dpx(2), ay - dpx(4.5), ax + dpx(5.5), ay - dpx(1)],
              fill=TEXT)
    d.polygon([(ax - dpx(7), ay + dpx(5)), (ax - dpx(1), ay - dpx(1)),
               (ax + dpx(4), ay + dpx(5))], fill=TEXT)

    # 输入框 hint
    d.text((dpx(50), dpx(25)), "发消息…", font=fnt(dpx(7)), fill=DIM)

    # ★ 表情按钮：贴右下，「＋」左侧（46dp 间距）
    plus_cx = W - dpx(10) - dpx(18)          # ＋ 圆心
    emoji_cx = plus_cx - dpx(46) + dpx(12)   # 表情图标中心
    ey = H - dpx(8) - dpx(18)
    d.rounded_rectangle([emoji_cx - dpx(12), ey - dpx(12),
                         emoji_cx + dpx(12), ey + dpx(12)],
                        radius=dpx(6), fill=CARD)
    # 用真实 Fluent Emoji 贴图
    paste_emoji(im, "grinning-face", emoji_cx, ey, dpx(20))

    # ＋ 圆
    r = dpx(18)
    d.ellipse([plus_cx - r, ey - r, plus_cx + r, ey + r], fill=CARD)
    d.line([plus_cx - dpx(7), ey, plus_cx + dpx(7), ey], fill=TEXT, width=dpx(1.6))
    d.line([plus_cx, ey - dpx(7), plus_cx, ey + dpx(7)], fill=TEXT, width=dpx(1.6))

    out = os.path.join(HERE, "v11812_inputbar.png")
    im.save(out)
    print("inputbar:", im.width, "x", im.height, "->", out)


# ─────────────────────────────────────────────────────────────
# 2) 表情面板（键盘区）：常用表情 + 页签 + 网格
# ─────────────────────────────────────────────────────────────
def shot_panel():
    cat = json.load(open(CATALOG, encoding="utf-8"))
    groups = cat["groups"]

    W = dpx(250)
    COLS = 8
    CELL = dpx(40)
    RECENT = ["face-with-tears-of-joy", "smiling-face-with-heart-eyes",
              "grinning-face-with-smiling-eyes", "thumbs-up",
              "folded-hands", "red-heart", "fire", "waving-hand"]

    tab_h = dpx(36)
    recent_h = dpx(16) + CELL      # 标题 + 一行
    grid_rows = 5
    hint_h = dpx(26)
    H = recent_h + tab_h + CELL * grid_rows + hint_h + dpx(18)

    im = Image.new("RGB", (W, H), BAR)
    d = ImageDraw.Draw(im)

    f_title = fnt(dpx(5.5))
    f_tab = fnt(dpx(6.5))
    f_tab_on = fnt(dpx(6.5), True)
    f_hint = fnt(dpx(5.5), True)

    # ── 常用表情 ──
    d.text((dpx(10), dpx(6)), "常用表情", font=f_title, fill=DIM)
    ry = dpx(16) + CELL // 2
    cw = W // COLS
    for i, slug in enumerate(RECENT[:COLS]):
        cx = i * cw + cw // 2
        paste_emoji(im, slug, cx, ry, int(CELL * 0.72))

    # ── 页签 ──
    y = recent_h
    x = dpx(8)
    for gi, g in enumerate(groups[:7]):
        label = GROUP_CN.get(g["name"], g["name"])
        tw = d.textlength(label, font=f_tab_on if gi == 0 else f_tab)
        pad = dpx(6)
        bw = tw + pad * 2
        if x + bw > W - dpx(8):
            break
        if gi == 0:
            d.rounded_rectangle([x, y + dpx(2), x + bw, y + tab_h - dpx(8)],
                                radius=dpx(6), fill=CARD)
        d.text((x + pad, y + dpx(7)), label,
               font=f_tab_on if gi == 0 else f_tab,
               fill=TEXT if gi == 0 else DIM)
        x += bw + dpx(4)

    # ── 网格（第一组）──
    emojis = groups[0]["emojis"]
    gy = recent_h + tab_h
    for idx, e in enumerate(emojis[:COLS * grid_rows]):
        r, c = divmod(idx, COLS)
        cx = c * CELL + CELL // 2
        cy = gy + r * CELL + CELL // 2
        paste_emoji(im, e["slug"], cx, cy, int(CELL * 0.7))

    # ── 提示 ──
    d.text((dpx(12), H - hint_h + dpx(4)),
           "表情 · 共 %d 个" % len(emojis), font=f_hint, fill=DIM)

    out = os.path.join(HERE, "v11812_emoji_panel.png")
    im.save(out)
    print("emoji panel:", im.width, "x", im.height, "->", out)


# ─────────────────────────────────────────────────────────────
# 3) 表情 ⇄ 键盘 图标互切
# ─────────────────────────────────────────────────────────────
def shot_switch():
    W = dpx(250)
    H = dpx(120)
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)

    f = fnt(dpx(6), True)
    r = dpx(18)

    # 左：面板关闭 → 表情图标
    lx = dpx(60)
    ly = dpx(40)
    d.ellipse([lx - r, ly - r, lx + r, ly + r], fill=CARD)
    paste_emoji(im, "grinning-face", lx, ly, dpx(24))
    d.text((lx - dpx(30), ly + dpx(26)), "面板关闭 = 表情图标",
           font=fnt(dpx(5.5), True), fill=DIM)

    # 箭头
    d.line([dpx(105), ly, dpx(140), ly], fill=ACCENT, width=dpx(1.5))
    d.polygon([(dpx(140), ly), (dpx(132), ly - dpx(4)), (dpx(132), ly + dpx(4))],
              fill=ACCENT)

    # 右：面板打开 → 键盘图标
    rx = dpx(188)
    d.ellipse([rx - r, ly - r, rx + r, ly + r], fill=CARD)
    # 画键盘
    kx, ky = rx, ly
    d.rounded_rectangle([kx - dpx(11), ky - dpx(7), kx + dpx(11), ky + dpx(7)],
                        radius=dpx(2), outline=TEXT, width=dpx(1.1))
    for i in range(4):
        x0 = kx - dpx(8) + i * dpx(4.4)
        d.rectangle([x0, ky - dpx(4.4), x0 + dpx(2.6), ky - dpx(2)],
                    fill=TEXT)
        d.rectangle([x0, ky - dpx(0.5), x0 + dpx(2.6), ky + dpx(1.9)],
                    fill=TEXT)
    d.rectangle([kx - dpx(4), ky + dpx(3.2), kx + dpx(4), ky + dpx(5)],
                fill=TEXT)
    d.text((rx - dpx(30), ly + dpx(26)), "面板打开 = 键盘图标",
           font=fnt(dpx(5.5), True), fill=DIM)

    out = os.path.join(HERE, "v11812_switch.png")
    im.save(out)
    print("switch:", im.width, "x", im.height, "->", out)


if __name__ == "__main__":
    shot_inputbar()
    shot_panel()
    shot_switch()
    print("OK")
