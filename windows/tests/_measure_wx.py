# -*- coding: utf-8 -*-
r"""从微信参考图反推文件卡片的精确几何规格。

参考图：收到的文件/1000402955.jpg（1440x3088）
微信「文件传输助手」深色模式截图，用于校准双端卡片实现。

输出：卡片宽度、内边距、图标尺寸与位置、文字区边界（单位 px 与 dp）。
"""
import os
import sys

from PIL import Image

SRC = r"C:\Users\Administrator\FlashDrop\收到的文件\1000402955.jpg"

im = Image.open(SRC).convert("RGB")
W, H = im.size
px = im.load()
print(f"图片尺寸 = {W} x {H}")


def is_card_bg(c, tol=12):
    """卡片底色判定（深灰偏中性）"""
    return abs(c[0] - 44) < tol and abs(c[1] - 44) < tol and abs(c[2] - 46) < tol


def scan_row(y, min_run=80):
    runs = []
    prev = False
    start = 0
    for x in range(W):
        cur = is_card_bg(px[x, y])
        if cur != prev:
            if prev:
                runs.append((start, x - 1))
            start = x
            prev = cur
    if prev:
        runs.append((start, W - 1))
    return [r for r in runs if r[1] - r[0] >= min_run]


print("\n=== 1. 卡片水平范围（多行采样）===")
for y in (700, 730, 760, 790, 820):
    print(f"  y={y}: {scan_row(y)}")

print("\n=== 2. 卡片垂直范围（取卡片中线列扫描）===")
# 先确定一张卡片的列区间，再竖向扫描找上下边界
rows = scan_row(760)
if rows:
    x0, x1 = rows[0]
    print(f"  选定卡片列区间 x=[{x0},{x1}]，宽 {x1 - x0 + 1}px")
    cy = 760
    top = cy
    while top > 0 and is_card_bg(px[x0 + 5, top]):
        top -= 1
    bot = cy
    while bot < H - 1 and is_card_bg(px[x0 + 5, bot]):
        bot += 1
    print(f"  卡片上下边界 y=[{top + 1},{bot - 1}]，高 {bot - 1 - top}px")

print("\n=== 3. 图标（PDF 红块）位置与尺寸 ===")
# 在卡片竖直中线附近找红色像素（PDF 图标 #E8453C 附近）
red_xs, red_ys = [], []
for y in range(600, 900):
    for x in range(0, W):
        r, g, b = px[x, y]
        if r > 170 and g < 90 and b < 80:
            red_xs.append(x)
            red_ys.append(y)
if red_xs:
    ix0, ix1 = min(red_xs), max(red_xs)
    iy0, iy1 = min(red_ys), max(red_ys)
    print(f"  红色图标范围 x=[{ix0},{ix1}] ({ix1 - ix0 + 1}px), "
          f"y=[{iy0},{iy1}] ({iy1 - iy0 + 1}px)")
    print(f"  图标宽高比 = {(ix1 - ix0 + 1) / (iy1 - iy0 + 1):.3f}")
else:
    print("  未找到红色图标")

print("\n=== 4. dp 换算 ===")
# 用卡片宽度反推密度：微信手机端文件卡片在 655dp 屏上约 450dp 宽
if rows:
    cw = rows[0][1] - rows[0][0] + 1
    for density in (2.0, 2.2, 2.5, 2.75, 3.0, 3.2):
        print(f"  若密度 {density}x → 卡片 {cw / density:.1f}dp, "
              f"屏 {W / density:.1f}dp")
