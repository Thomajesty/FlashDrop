# -*- coding: utf-8 -*-
r"""微信文件卡片几何精测（v3）—— 锁定单张卡片，输出全部关键尺寸。

参考图 收到的文件/1000402955.jpg = 1440 x 3088，密度 2.2x（655dp 屏）
已知：卡片横向 x=[312,1212]，即宽 901px
"""
from PIL import Image

SRC = r"C:\Users\Administrator\FlashDrop\收到的文件\1000402955.jpg"
DENSITY = 2.2
im = Image.open(SRC).convert("RGB")
W, H = im.size
px = im.load()


def near(c, t, tol=10):
    return (abs(c[0] - t[0]) < tol and abs(c[1] - t[1]) < tol
            and abs(c[2] - t[2]) < tol)


CARD = (44, 44, 44)
PAGE = (17, 17, 17)


def dp(v):
    return v / DENSITY


print(f"图片 {W}x{H}，密度 {DENSITY}x\n")

# ---------- 1. 锁定第一张卡片（FlashDrop.apk.1 / 问号图标那张）的竖向范围 ----------
# 在卡片左侧（x=320，肯定在卡片内）竖向找 CARD 色带
col = 320
runs = []
prev = False
start = 0
for y in range(560, 1450):
    cur = near(px[col, y], CARD)
    if cur != prev:
        if prev:
            runs.append((start, y - 1))
        start = y
        prev = cur
if prev:
    runs.append((start, 1449))
cards = [(a, b) for a, b in runs if b - a > 100]
print("=== 卡片竖向范围（x=320 列）===")
for a, b in cards:
    print(f"  y=[{a},{b}]  高 {b - a + 1}px = {dp(b - a + 1):.1f}dp")

# ---------- 2. 每张卡片的横向范围与图标位置 ----------
print("\n=== 每张卡片：横向边界 / 内边距 / 图标位置 ===")
for idx, (cy0, cy1) in enumerate(cards):
    cy = (cy0 + cy1) // 2
    # 在该卡片竖直中线处扫横向：卡片底色区段
    xs = [x for x in range(W) if near(px[x, cy], CARD)]
    if not xs:
        continue
    cx0, cx1 = min(xs), max(xs)
    # 图标：右下角有非卡片底色（彩色/灰紫）的块
    ixs = [x for x in range(cx0, cx1 + 1)
           if not near(px[x, cy], CARD, 14)]
    print(f"\n  卡片#{idx + 1}  y=[{cy0},{cy1}] 高={dp(cy1 - cy0 + 1):.1f}dp")
    print(f"    横向 x=[{cx0},{cx1}]  宽={cx1 - cx0 + 1}px = {dp(cx1 - cx0 + 1):.1f}dp")

# ---------- 3. 取带清晰图标的那张卡（y≈627..866）做完整测量 ----------
print("\n=== 完整测量：卡片 y=[617,872]（含问号图标）===")
ring = (617, 872)
cy = (ring[0] + ring[1]) // 2
xs = [x for x in range(W) if near(px[x, cy], CARD)]
cx0, cx1 = min(xs), max(xs)
print(f"  卡片 x=[{cx0},{cx1}] 宽 {cx1 - cx0 + 1}px = {dp(cx1 - cx0 + 1):.1f}dp")
print(f"  卡片 y=[{ring[0]},{ring[1]}] 高 {ring[1] - ring[0] + 1}px "
      f"= {dp(ring[1] - ring[0] + 1):.1f}dp")

# 图标横向：在图标竖直中线找非卡片色块
iy = 750
seg = [x for x in range(cx0, cx1 + 1) if not near(px[x, iy], CARD, 16)]
if seg:
    ix0, ix1 = min(seg), max(seg)
    print(f"  图标横向 x=[{ix0},{ix1}] 宽 {ix1 - ix0 + 1}px "
          f"= {dp(ix1 - ix0 + 1):.1f}dp")
    print(f"    图标右边距卡右 = {cx1 - ix1}px = {dp(cx1 - ix1):.1f}dp")

# 图标竖向
ixc = (ix0 + ix1) // 2 if seg else 1090
segv = [y for y in range(ring[0], ring[1] + 1)
        if not near(px[ixc, y], CARD, 16)]
if segv:
    iy0, iy1 = min(segv), max(segv)
    print(f"  图标竖向 y=[{iy0},{iy1}] 高 {iy1 - iy0 + 1}px "
          f"= {dp(iy1 - iy0 + 1):.1f}dp")
    print(f"    宽高比 = {(ix1 - ix0 + 1) / (iy1 - iy0 + 1):.3f}")
    print(f"    图标上距卡上 = {iy0 - ring[0]}px = {dp(iy0 - ring[0]):.1f}dp")
    print(f"    图标下距卡下 = {ring[1] - iy1}px = {dp(ring[1] - iy1):.1f}dp")

# 文字起点：文件名第一行最左侧亮像素
print("\n=== 文字区 ===")
for ty in (690, 695, 700):
    bright = [x for x in range(cx0, (ix0 if seg else cx1))
              if sum(px[x, ty]) > 330]
    if bright:
        print(f"  行 y={ty}: 文字最左 x={min(bright)}，"
              f"距卡左 = {min(bright) - cx0}px = {dp(min(bright) - cx0):.1f}dp")
        break
if seg:
    gap = (min(bright) - ix1) if bright else 0
    print(f"  文字区宽（左内边距→图标左）= {ix0 - min(bright)}px "
          f"= {dp(ix0 - min(bright)):.1f}dp")
