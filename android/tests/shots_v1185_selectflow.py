# -*- coding: utf-8 -*-
"""v1.18.5 文本长按交互示意图（微信式：选择光标 + 动态悬浮菜单）

画两种状态，直观呈现"菜单随选区切换"：
  状态 A —— 刚长按：整段选中，光标/把手出现，菜单 = 复制 · 删除 · 多选
  状态 B —— 拖动光标选中局部：菜单 = 复制 · 全选

输出：交付/v1185验收截图/select_flow.png
"""
import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ANDROID = os.path.dirname(HERE)
PROJ = os.path.dirname(ANDROID)
OUT = os.path.join(PROJ, "交付", "v1185验收截图")
os.makedirs(OUT, exist_ok=True)

DENSITY = 3.0
SS = 8
S = 32.0

FG = (233, 234, 236)
MENU_BG = (38, 38, 42)
CANVAS_BG = (242, 243, 245)
BUBBLE_BG = (255, 255, 255)
TEXT_C = (31, 35, 40)
TITLE = (31, 35, 40)
DIM = (110, 118, 128)
SEL_BG = (96, 165, 250, 90)      # 选中高亮（半透明蓝）
HANDLE = (29, 78, 216)
A_C = (190, 74, 74)
B_C = (21, 128, 61)

FONT = r"C:\Windows\Fonts\msyh.ttc"


def font(sz):
    try:
        return ImageFont.truetype(FONT, int(sz))
    except Exception:
        return ImageFont.load_default()


def icon(size_px, kind):
    """复刻 FdMenuIcon.java 的矢量坐标（32x32 基准）"""
    W = int(size_px * SS)
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    k = W / S
    lw = max(1, int(round(2.2 * k)))

    if kind == "copy":
        d.rounded_rectangle([5 * k, 5 * k, 20 * k, 20 * k], radius=2.5 * k,
                            outline=FG, width=lw)
        d.rounded_rectangle([12 * k, 12 * k, 27 * k, 27 * k], radius=2.5 * k,
                            outline=FG, width=lw)
    elif kind == "delete":
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
        for (x0, y0, x1, y1) in [(6, 6, 14, 14), (18, 6, 26, 14),
                                 (6, 18, 14, 26), (18, 18, 26, 26)]:
            d.rounded_rectangle([x0 * k, y0 * k, x1 * k, y1 * k],
                                radius=2 * k, outline=FG, width=lw)
    elif kind == "all":
        # 全选：外框 + 内部三行（自绘，FdMenuIcon 无此项）
        d.rounded_rectangle([6 * k, 7 * k, 26 * k, 25 * k], radius=2.5 * k,
                            outline=FG, width=lw)
        for yy in (12.5, 16, 19.5):
            d.line([10 * k, yy * k, 22 * k, yy * k], fill=FG, width=max(1, lw - 1))
    return img.resize((int(size_px), int(size_px)), Image.LANCZOS)


def draw_menu(canvas, cx, cy, items, icon_dp=22):
    """在 (cx, cy) 居中偏上绘制浮动菜单，返回 (w, h)"""
    d = ImageDraw.Draw(canvas)
    f = font(11 * DENSITY)
    pad_h, pad_v, gap, box_pad = 6 * DENSITY, 4 * DENSITY, 3 * DENSITY, 4 * DENSITY
    iw = icon_dp * DENSITY

    cells = []
    for kind, txt in items:
        tb = f.getbbox(txt)
        tw = tb[2] - tb[0]
        cw = max(iw, tw) + 2 * pad_h
        ch = 2 * pad_v + iw + gap + 11 * DENSITY * 1.3
        cells.append((kind, txt, cw, ch, tw))

    total_w = int(sum(c[2] for c in cells) + 2 * box_pad)
    total_h = int(max(c[3] for c in cells) + 2 * box_pad)
    x0 = int(cx - total_w / 2)
    y0 = int(cy - total_h)

    d.rounded_rectangle([x0, y0, x0 + total_w, y0 + total_h],
                        radius=int(8 * DENSITY), fill=MENU_BG)

    x = x0 + box_pad
    for (kind, txt, cw, ch, tw) in cells:
        ic = icon(iw, kind)
        canvas.paste(ic, (int(x + (cw - iw) / 2), int(y0 + box_pad + pad_v)), ic)
        d.text((int(x + (cw - tw) / 2), int(y0 + box_pad + pad_v + iw + gap)),
               txt, font=f, fill=FG)
        x += cw
    return total_w, total_h


def draw_state(canvas, top, label, label_c, desc, sel_prefix, items, menu_icon=22):
    """绘制一个状态块：说明 + 菜单 + 气泡(含选中/把手)"""
    d = ImageDraw.Draw(canvas)
    f_lab = font(19)
    f_desc = font(16)
    f_text = font(14 * DENSITY * 0.62)

    d.text((40, top), label, font=f_lab, fill=label_c)
    d.text((40, top + 24), desc, font=f_desc, fill=DIM)

    # 气泡（给上方菜单留足空间，避免与说明文字重叠）
    bx, by = 90, top + 252
    bubble_w = 560
    bubble_h = 76
    d.rounded_rectangle([bx, by, bx + bubble_w, by + bubble_h],
                        radius=18, fill=BUBBLE_BG,
                        outline=(226, 228, 232), width=2)

    text = "这是一条测试文本，长按可以选中"
    tx, ty = bx + 24, by + 26
    full_w = f_text.getlength(text)
    pre_w = f_text.getlength(sel_prefix)

    # 选中高亮
    hx0 = tx + (0 if not sel_prefix else pre_w)
    hx1 = tx + (full_w if not sel_prefix else pre_w + f_text.getlength("测试文本"))
    if sel_prefix == "":
        hx1 = tx + full_w
    hl = Image.new("RGBA", (int(hx1 - hx0), int(30)), SEL_BG)
    canvas.paste(hl, (int(hx0), int(ty - 4)), hl)

    d.text((tx, ty), text, font=f_text, fill=TEXT_C)

    # 左右选择把手
    for hxp in (hx0, hx1):
        d.rounded_rectangle([hxp - 3, ty - 12, hxp + 3, ty + 40],
                            radius=3, fill=HANDLE)
        d.ellipse([hxp - 9, ty + 38, hxp + 9, ty + 56], fill=HANDLE)

    # 菜单（在气泡上方）
    draw_menu(canvas, bx + bubble_w / 2, by - 22, items, menu_icon)


def main():
    W, H = 1180, 900
    canvas = Image.new("RGB", (W, H), CANVAS_BG)

    d = ImageDraw.Draw(canvas)
    d.text((40, 26), "文本长按交互（微信式）  v1.18.5", font=font(28), fill=TITLE)
    d.text((40, 64),
           "长按正文直接出现选择光标（v1.18.5 已修复事件下传）；上方菜单随选区动态切换，顺序固定",
           font=font(17), fill=DIM)

    y = 100
    draw_state(
        canvas, y, "① 刚长按（或已全选）", A_C,
        "光标出现，此时给出消息级操作  →  复制 · 删除 · 多选",
        sel_prefix="", items=[("copy", "复制"), ("delete", "删除"),
                              ("multi", "多选")])

    y2 = 470
    draw_state(
        canvas, y2, "② 拖动光标选中局部文字", B_C,
        "切换到选区级操作  →  复制 · 全选",
        sel_prefix="这是一条", items=[("copy", "复制"), ("all", "全选")])

    d.line([40, 852, W - 40, 852], fill=(222, 226, 232), width=2)
    f = font(16)
    d.text((40, 866),
           "判定用 moved && !full：点「全选」后选区=全文，菜单会自动回到 ① 的消息级，形成闭环。",
           font=f, fill=DIM)

    out = os.path.join(OUT, "select_flow.png")
    canvas.save(out, "PNG")
    print(f"已生成：{out}")


if __name__ == "__main__":
    main()
