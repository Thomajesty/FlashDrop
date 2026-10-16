# -*- coding: utf-8 -*-
"""v1.18.16 验收图：设备列表右键删除 + 多选全部删除。

产出 tests/_v11816/device_delete.png
"""
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "_v11816")
os.makedirs(OUT, exist_ok=True)

BG = (24, 26, 31)
CARD = (38, 41, 48)
SEL = (45, 74, 122)
TEXT = (232, 234, 238)
DIM = (140, 146, 156)
RED = (226, 75, 74)
GREEN = (99, 153, 34)
BLUE = (59, 130, 246)
FIXED = (90, 96, 108)


def fnt(size, bold=False):
    for name in (("msyhbd.ttc" if bold else "msyh.ttc"), "simhei.ttf"):
        p = os.path.join("C:\\Windows\\Fonts", name)
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def draw_list(d, x, y, w, items, selected):
    """画一个设备列表；items = [(名称, 副标题, 颜色)]"""
    lh = 46
    for i, (name, sub, col) in enumerate(items):
        yy = y + i * lh
        d.rounded_rectangle([x, yy, x + w, yy + lh - 4], radius=6,
                            fill=SEL if i in selected else CARD,
                            outline=BLUE if i in selected else (52, 56, 64),
                            width=2 if i in selected else 1)
        d.ellipse([x + 10, yy + 16, x + 20, yy + 26], fill=col)
        d.text((x + 30, yy + 12), name, font=fnt(12, True), fill=TEXT)
        d.text((x + 30, yy + 28), sub, font=fnt(9), fill=DIM)
    return y + len(items) * lh


def del_btn(d, x, y, w, text, on):
    d.rounded_rectangle([x, y, x + w, y + 32], radius=6,
                        fill=CARD if on else (30, 32, 38),
                        outline=RED if on else FIXED, width=2)
    d.text((x + w / 2, y + 16), text, font=fnt(12, True),
           fill=RED if on else FIXED, anchor="mm")


def main():
    W, H = 1160, 470
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)

    d.text((24, 18), "v1.18.16 电脑版：设备列表右键删除 + 多选全部删除",
           font=fnt(18, True), fill=TEXT)
    d.text((24, 46),
           "「全部设备」是固定的聚合视图，没有档案也没有专属文件夹 —— 全程不可删除",
           font=fnt(11), fill=DIM)

    items = [
        ("全部设备", "固定视图 · 不可删除", FIXED),
        ("办公室电脑", "192.168.1.12 · 在线", GREEN),
        ("我的手机", "192.168.1.33 · 在线", GREEN),
        ("平板", "192.168.1.47 · 离线", DIM),
    ]

    # ---- ① 右键单个删除 ----
    d.text((40, 96), "① 右击某个设备", font=fnt(14, True), fill=TEXT)
    y = draw_list(d, 40, 128, 300, items, selected=[2])
    d.rounded_rectangle([200, 128 + 46 * 2 - 12, 360, 128 + 46 * 2 + 34],
                        radius=4, fill=(52, 56, 66), outline=BLUE, width=1)
    d.rounded_rectangle([206, 128 + 46 * 2 - 6, 354, 128 + 46 * 2 + 28],
                        radius=3, fill=(58, 62, 74))
    d.text((212, 128 + 46 * 2 + 2), "删除「我的手机」的会话",
           font=fnt(11), fill=TEXT)
    d.text((212, 128 + 46 * 2 + 16), "删除选中的 1 个设备",
           font=fnt(11), fill=DIM)

    # ---- ② 多选 → 底部按钮 ----
    d.text((420, 96), "② Ctrl/Shift 多选 → 底部出现按钮", font=fnt(14, True),
           fill=TEXT)
    y2 = draw_list(d, 420, 128, 300, items, selected=[1, 2, 3])
    del_btn(d, 420, y2 + 6, 300, "删除选中的 3 个设备", True)

    # ---- ③ 全部设备受保护 ----
    d.text((800, 96), "③「全部设备」被挡住", font=fnt(14, True), fill=TEXT)
    y3 = draw_list(d, 800, 128, 300, items, selected=[0])
    d.rounded_rectangle([806, 128 - 6, 1094, 128 + 40], radius=4,
                        fill=(52, 56, 66), outline=BLUE, width=1)
    d.text((816, 128 + 10), "「全部设备」是固定视图，不可删除",
           font=fnt(11), fill=FIXED)
    d.rounded_rectangle([806, 128 + 26, 1094, 128 + 66], radius=3,
                        fill=(46, 48, 56))
    d.text((816, 128 + 46), "（灰字不可点击）", font=fnt(10), fill=FIXED)

    # ---- 底部说明 ----
    d.rounded_rectangle([24, 356, W - 24, 446], radius=8, fill=(32, 35, 42))
    d.text((40, 374), "删除时连带清理三类数据：", font=fnt(13, True), fill=TEXT)
    for i, (t, col) in enumerate([
            ("① 聊天记录", BLUE),
            ("② 接收文件夹", GREEN),
            ("③ 设备档案 known_peers", RED)]):
        d.rounded_rectangle([40 + i * 300, 400, 40 + i * 300 + 270, 432],
                            radius=6, fill=CARD, outline=col, width=1)
        d.text((40 + i * 300 + 135, 416), t, font=fnt(12, True), fill=col,
               anchor="mm")
    d.text((40, 438), "批量删除只动「本轮选中」的设备；未选中的记录、文件夹、设备都保持不动",
           font=fnt(10), fill=DIM)

    out = os.path.join(OUT, "device_delete.png")
    im.save(out)
    print("saved:", out, im.size)


if __name__ == "__main__":
    main()