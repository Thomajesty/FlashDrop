# -*- coding: utf-8 -*-
r"""微信卡片几何精测（v4）—— 修正 v3 的两个测量误差：
  1) 卡片#1 横向被右侧头像污染 → 用"连续段"而非 min/max
  2) 图标竖向取到整卡高 → 只扫图标自己的列
"""
from PIL import Image

SRC = r"C:\Users\Administrator\FlashDrop\收到的文件\1000402955.jpg"
D = 2.2
im = Image.open(SRC).convert("RGB")
W, H = im.size
px = im.load()


def near(c, t, tol=10):
    return all(abs(c[i] - t[i]) < tol for i in range(3))


CARD = (44, 44, 44)


def dp(v):
    return v / D


def longest_run(y, target=CARD, tol=10):
    """一行里最长的连续 target 色段"""
    best = (0, 0)
    s = None
    for x in range(W):
        if near(px[x, y], target, tol):
            if s is None:
                s = x
        else:
            if s is not None:
                if x - 1 - s > best[1] - best[0]:
                    best = (s, x - 1)
                s = None
    if s is not None and W - 1 - s > best[1] - best[0]:
        best = (s, W - 1)
    return best


print(f"图片 {W}x{H}，密度 {D}x\n")
print("=== 卡片横向（取最长连续段，避免头像污染）===")
for y in (700, 750, 800):
    a, b = longest_run(y)
    print(f"  y={y}: x=[{a},{b}] 宽 {b - a + 1}px = {dp(b - a + 1):.1f}dp")

cx0, cx1 = longest_run(750)
print(f"\n采用卡片 x=[{cx0},{cx1}]，宽 {dp(cx1 - cx0 + 1):.1f}dp")

print("\n=== 图标（问号灰紫块）精确范围 ===")
# 问号图标颜色约 (85,93,116) / (82,93,121)
def is_icon(c):
    return 70 < c[0] < 110 and 75 < c[1] < 115 and 100 < c[2] < 140


ixs = [x for x in range(cx0, cx1 + 1)
       if any(is_icon(px[x, y]) for y in range(620, 880))]
iys = [y for y in range(600, 890)
       if any(is_icon(px[x, y]) for x in range(cx0, cx1 + 1))]
ix0, ix1 = min(ixs), max(ixs)
iy0, iy1 = min(iys), max(iys)
iw, ih = ix1 - ix0 + 1, iy1 - iy0 + 1
print(f"  图标 x=[{ix0},{ix1}] 宽 {iw}px = {dp(iw):.1f}dp")
print(f"  图标 y=[{iy0},{iy1}] 高 {ih}px = {dp(ih):.1f}dp")
print(f"  宽高比 = {iw / ih:.3f}")
print(f"  图标右距卡右 = {cx1 - ix1}px = {dp(cx1 - ix1):.1f}dp")

# 卡片竖向范围（在卡片左内空白列上扫）
lex = cx0 + 8
runs = []
prev = False
s = 0
for y in range(560, 920):
    cur = near(px[lex, y], CARD)
    if cur != prev:
        if prev:
            runs.append((s, y - 1))
        s, prev = y, cur
if prev:
    runs.append((s, 919))
cardv = [r for r in runs if r[1] - r[0] > 100]
print(f"\n=== 卡片竖向 ===")
for a, b in cardv:
    print(f"  y=[{a},{b}] 高 {b - a + 1}px = {dp(b - a + 1):.1f}dp")
    print(f"    图标上距卡上 = {iy0 - a}px = {dp(iy0 - a):.1f}dp")
    print(f"    图标下距卡下 = {b - iy1}px = {dp(b - iy1):.1f}dp")

print("\n=== 汇总（dp）===")
a, b = cardv[0] if cardv else (0, 0)
print(f"  卡片宽        {dp(cx1 - cx0 + 1):.1f}")
print(f"  卡片高        {dp(b - a + 1):.1f}")
print(f"  左内边距      {dp(354 - cx0):.1f}   (文字最左 - 卡左)")
print(f"  图标宽        {dp(iw):.1f}")
print(f"  图标高        {dp(ih):.1f}")
print(f"  图标右内边距  {dp(cx1 - ix1):.1f}")
print(f"  文字区宽      {dp(ix0 - 354):.1f}   (图标左 - 文字左)")
print(f"  上内边距      {dp(iy0 - a):.1f}")
