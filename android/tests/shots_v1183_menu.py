# -*- coding: utf-8 -*-
"""v1.18.3 长按菜单「精致化」视觉对比图

用 PIL 按 FdMenuIcon.java 的**真实矢量绘制逻辑**复刻图标
（32x32 设计基准 + 8x 超采样抗锯齿），再按两套布局参数渲染菜单项：

  旧（v1.18.2）：图标 32dp · 文字 12sp · 内边距 8/6 · 图标文字间距 5
  新（v1.18.3）：图标 26dp · 文字 11sp · 内边距 6/4 · 图标文字间距 3

输出：交付/v1183验收截图/menu_before_after.png
"""
import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ANDROID = os.path.dirname(HERE)
PROJ = os.path.dirname(ANDROID)
OUT = os.path.join(PROJ, "交付", "v1183验收截图")
os.makedirs(OUT, exist_ok=True)

DENSITY = 3.0          # xxhdpi：1dp = 3px
SS = 8                 # 超采样倍数
S = 32.0               # 图标设计基准

FG = (233, 234, 236)       # 菜单前景色 0xFFE9EAEC
ACCENT = (96, 165, 250)
MENU_BG = (38, 38, 42)     # 菜单深色底
CANVAS_BG = (245, 246, 248)
TITLE = (31, 35, 40)
DIM = (110, 118, 128)
OLD_C = (190, 74, 74)
NEW_C = (21, 128, 61)

FONT_PATH = r"C:\Windows\Fonts\msyh.ttc"


def font(size_px):
    try:
        return ImageFont.truetype(FONT_PATH, int(size_px))
    except Exception:
        return ImageFont.load_default()


# ══════════════ 图标绘制（严格照搬 FdMenuIcon.java 的坐标） ══════════════

def icon(size_px, kind):
    """按 32x32 设计基准绘制，输出 size_px 方形 RGBA。"""
    W = int(size_px * SS)
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    k = W / S
    lw = max(1, int(round(2.2 * k)))

    if kind == "copy":
        # drawCopy：两个错位圆角矩形
        d.rounded_rectangle([5 * k, 5 * k, 20 * k, 20 * k],
                            radius=2.5 * k, outline=FG, width=lw)
        d.rounded_rectangle([12 * k, 12 * k, 27 * k, 27 * k],
                            radius=2.5 * k, outline=FG, width=lw)
    elif kind == "select":
        # drawSelect（v1.18.3 新增）：三行文字 + 左右选择把手
        for (x0, y0, x1, y1) in [(9.5, 9.5, 21, 11.5),
                                 (9.5, 15, 24, 17),
                                 (9.5, 20.5, 18, 22.5)]:
            d.rectangle([x0 * k, y0 * k, x1 * k, y1 * k], fill=FG)
        d.rectangle([2.5 * k, 7 * k, 5 * k, 25 * k], fill=FG)
        d.rectangle([27 * k, 7 * k, 29.5 * k, 25 * k], fill=FG)
    elif kind == "delete":
        # drawDelete：盖子 + 提手 + 桶身 + 两条竖纹
        d.line([6 * k, 9 * k, 26 * k, 9 * k], fill=FG, width=lw)
        d.line([13 * k, 9 * k, 13 * k, 6 * k], fill=FG, width=lw)
        d.line([13 * k, 6 * k, 19 * k, 6 * k], fill=FG, width=lw)
        d.line([19 * k, 6 * k, 19 * k, 9 * k], fill=FG, width=lw)
        d.line([8 * k, 9 * k, 9.5 * k, 26 * k], fill=FG, width=lw)
        d.line([9.5 * k, 26 * k, 22.5 * k, 26 * k], fill=FG, width=lw)
        d.line([22.5 * k, 26 * k, 24 * k, 9 * k], fill=FG, width=lw)
        d.line([13.5 * k, 13 * k, 14 * k, 22 * k], fill=FG, width=lw)
        d.line([18.5 * k, 13 * k, 18 * k, 22 * k], fill=FG, width=lw)
    elif kind == "multi":
        # drawMulti：四宫格
        for (x0, y0, x1, y1) in [(6, 6, 14, 14), (18, 6, 26, 14),
                                 (6, 18, 14, 26), (18, 18, 26, 26)]:
            d.rounded_rectangle([x0 * k, y0 * k, x1 * k, y1 * k],
                                radius=2 * k, outline=FG, width=lw)
    return img.resize((int(size_px), int(size_px)), Image.LANCZOS)


# ══════════════ 菜单项渲染 ══════════════

def measure_item(label, icon_dp, text_sp, pad_h, gap, max_text_dp):
    f = font(text_sp * DENSITY)
    tb = f.getbbox(label)
    text_w = min(tb[2] - tb[0], max_text_dp * DENSITY)
    icon_px = icon_dp * DENSITY
    w = max(icon_px, text_w) + 2 * pad_h * DENSITY
    h = (2 * pad_h * DENSITY * 0.66 + icon_px
         + gap * DENSITY + text_sp * DENSITY * 1.25)
    return w, h, icon_px, text_w


def draw_menu(canvas, ox, oy, items, icon_dp, text_sp, pad_h, pad_v, gap,
              max_text_dp, label_prefix=None):
    d = ImageDraw.Draw(canvas)
    box_pad = 4 * DENSITY if icon_dp < 30 else 6 * DENSITY

    # 先算尺寸
    cells = []
    for kind, txt in items:
        f = font(text_sp * DENSITY)
        tb = f.getbbox(txt)
        tw = min(tb[2] - tb[0], max_text_dp * DENSITY)
        iw = icon_dp * DENSITY
        cw = max(iw, tw) + 2 * pad_h * DENSITY
        ch = int(2 * pad_v * DENSITY + iw + gap * DENSITY
                 + text_sp * DENSITY * 1.3)
        cells.append((kind, txt, cw, ch, iw, tw, f))

    total_w = int(sum(c[2] for c in cells) + 2 * box_pad)
    total_h = int(max(c[3] for c in cells) + 2 * box_pad)

    # 菜单底板
    d.rounded_rectangle([ox, oy, ox + total_w, oy + total_h],
                        radius=int(14 * DENSITY * 0.6), fill=MENU_BG)

    x = ox + box_pad
    for (kind, txt, cw, ch, iw, tw, f) in cells:
        ic = icon(iw, kind)
        ix = int(x + (cw - iw) / 2)
        iy = int(oy + box_pad + pad_v * DENSITY * 0.66)
        # canvas 是 RGB，图标是 RGBA —— 用 paste + alpha 作 mask
        canvas.paste(ic, (ix, iy), ic)

        tx = int(x + (cw - tw) / 2)
        ty = int(iy + iw + gap * DENSITY)
        d.text((tx, ty), txt, font=f, fill=FG)
        x += cw

    return total_w, total_h


def main():
    items_old = [("copy", "复制"), ("delete", "删除"), ("multi", "多选")]
    items_new = [("copy", "复制"), ("select", "选择文字"),
                 ("delete", "删除"), ("multi", "多选")]

    W, H = 1180, 760
    canvas = Image.new("RGB", (W, H), CANVAS_BG)
    d = ImageDraw.Draw(canvas)

    f_title = font(30)
    f_sub = font(19)
    f_note = font(17)
    f_tag = font(18)

    d.text((40, 26), "长按菜单「精致化」对比  v1.18.2 → v1.18.3",
           font=f_title, fill=TITLE)
    d.text((40, 68),
           "按 FdMenuIcon.java 真实矢量逻辑复刻渲染  ·  密度 3x（xxhdpi）",
           font=f_sub, fill=DIM)

    # ── 上：旧版 ──
    y = 116
    d.text((40, y), "改动前  v1.18.2", font=f_tag, fill=OLD_C)
    d.text((40, y + 26),
           "图标 32dp · 文字 12sp · 内边距 8/6 · 间距 5",
           font=f_note, fill=DIM)
    ow, oh = draw_menu(canvas, 40, y + 58, items_old,
                       icon_dp=32, text_sp=12, pad_h=8, pad_v=6, gap=5,
                       max_text_dp=72)
    d.text((40 + ow + 24, y + 58 + oh // 2 - 30),
           f"行高 ≈ {oh / DENSITY:.0f}dp", font=f_note, fill=OLD_C)
    d.text((40 + ow + 24, y + 58 + oh // 2 - 4),
           "图标明显压过文字", font=f_note, fill=DIM)

    # ── 下：新版 ──
    y2 = 132 + oh + 90
    d.text((40, y2), "改动后  v1.18.3", font=f_tag, fill=NEW_C)
    d.text((40, y2 + 26),
           "图标 26dp · 文字 11sp · 内边距 6/4 · 间距 3   "
           "（新增「选择文字」用于框选局部文字）",
           font=f_note, fill=DIM)
    nw, nh = draw_menu(canvas, 40, y2 + 58, items_new,
                       icon_dp=26, text_sp=11, pad_h=6, pad_v=4, gap=3,
                       max_text_dp=60)
    d.text((40 + nw + 24, y2 + 58 + nh // 2 - 30),
           f"行高 ≈ {nh / DENSITY:.0f}dp", font=f_note, fill=NEW_C)
    d.text((40 + nw + 24, y2 + 58 + nh // 2 - 4),
           f"较旧版降低 {(1 - nh / oh) * 100:.0f}%", font=f_note, fill=NEW_C)

    # ── 底部说明 ──
    yb = y2 + 58 + nh + 34
    d.line([40, yb, W - 40, yb], fill=(222, 226, 232), width=2)
    d.text((40, yb + 16),
           "图标改为按目标尺寸直接渲染矢量（新增 sizeDp 参数），"
           "不是把 32dp 位图塞进小 ImageView 降采样 —— 缩小后线条依然锐利。",
           font=f_note, fill=DIM)
    d.text((40, yb + 42),
           "「选择文字」图标 = 左右两根选择把手 + 三行文字，"
           "对应新增的「框选局部文字并复制」能力。",
           font=f_note, fill=DIM)

    out = os.path.join(OUT, "menu_before_after.png")
    canvas.save(out, "PNG")
    print(f"已生成：{out}")
    print(f"  旧版行高 {oh / DENSITY:.1f}dp  →  新版 {nh / DENSITY:.1f}dp"
          f"（降低 {(1 - nh / oh) * 100:.1f}%）")


if __name__ == "__main__":
    main()
