# -*- coding: utf-8 -*-
"""v1.18.14 验收图：Windows 表情图标放大 —— 旧 EXE / 新版 / 微信 三方对比。

数据来源（全部为实测像素，不是示意）：
  · 旧 EXE 面板 → 用户桌面截图 剪贴板_5427dc.png（实测图标可视 14px）
  · 新版面板   → windows/tests/_v11814/verify_panel_light.png（实测 22~26px）
  · 微信参考   → 微信图片_20261008210506_323_327.png（实测 22~24px）
"""
import os

from PIL import Image, ImageDraw, ImageFont

D = r"C:/Users/Administrator/Desktop"
FD = r"E:/工作缓存/Workbuddy/FlashDrop"
OUT = os.path.join(FD, "windows", "tests", "_v11814", "win_icon_compare.png")

OLD = os.path.join(D, "剪贴板_5427dc.png")
WX = os.path.join(D, "微信图片_20261008210506_323_327.png")
NEW = os.path.join(FD, "windows", "tests", "_v11814", "real_exe_after.png")

BG = (24, 26, 31)
TEXT = (232, 234, 238)
DIM = (140, 146, 156)
RED = (226, 75, 74)
GREEN = (99, 153, 34)
BLUE = (59, 130, 246)

# 裁剪区域（原图坐标）与实测图标宽度
# ① 旧 EXE 面板截图      ② 新 EXE 面板截图（用户 21:49 实拍）      ③ 微信
ITEMS = [
    ("① 旧 EXE（v1.18.13）", "图标可视 14px", RED, OLD, (250, 255, 760, 660), 14),
    ("② 新 EXE（v1.18.14）", "图标可视 22~26px", GREEN, NEW, (272, 200, 734, 620), 25),
    ("③ 微信桌面版（基准）", "图标可视 22~24px", BLUE, WX, (80, 60, 580, 340), 22),
]


def fnt(size, bold=False):
    for name in (("msyhbd.ttc" if bold else "msyh.ttc"), "simhei.ttf"):
        p = os.path.join("C:\\Windows\\Fonts", name)
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


TARGET_W = 420          # 每格统一宽
CROP_H = 236


def main():
    cols = []
    for title, sub, col, path, box, icon_w in ITEMS:
        if not os.path.exists(path):
            print("缺失:", path)
            continue
        im = Image.open(path).convert("RGB").crop(box)
        # 等比缩放到统一宽度
        r = TARGET_W / im.width
        im = im.resize((TARGET_W, int(im.height * r)), Image.LANCZOS)
        if im.height > CROP_H:
            im = im.crop((0, 0, TARGET_W, CROP_H))
        cols.append((title, sub, col, im, icon_w, box))

    if not cols:
        print("没有可用素材")
        return

    PAD = 22
    GAP = 18
    HEAD = 96
    CAPH = 30
    W = PAD * 2 + len(cols) * TARGET_W + (len(cols) - 1) * GAP
    H = HEAD + CROP_H + CAPH + PAD + 40
    canvas = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(canvas)

    d.text((PAD, 18), "v1.18.14 电脑端：表情图标放大（对齐微信）", font=fnt(19, True),
           fill=TEXT)
    d.text((PAD, 46),
           "根因：全局 QSS 的 QToolButton padding(4px 14px) 把 44px 格子的内容区压到 14px，"
           "图标被 Qt 缩到 14px",
           font=fnt(12), fill=DIM)

    x = PAD
    for title, sub, col, im, icon_w, box in cols:
        d.text((x, HEAD - 34), title, font=fnt(14, True), fill=TEXT)
        d.text((x, HEAD - 15), sub, font=fnt(11), fill=col)
        canvas.paste(im, (x, HEAD))
        d.rectangle([x - 1, HEAD - 1, x + TARGET_W, HEAD + CROP_H], outline=col,
                    width=2)
        x += TARGET_W + GAP

    # 结论条
    y = HEAD + CROP_H + CAPH
    d.rectangle([PAD, y, W - PAD, y + 30], fill=(32, 35, 42))
    d.text((PAD + 12, y + 15),
           "结论：14px → 25px（+79%），由「比微信小」变为「与微信一致」；"
           "面板仍为 464 宽 / 10 列 / pitch 44",
           font=fnt(12, True), fill=TEXT, anchor="lm")

    canvas.save(OUT)
    print("saved:", OUT, canvas.size)


if __name__ == "__main__":
    main()
