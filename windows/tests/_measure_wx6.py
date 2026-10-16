# -*- coding: utf-8 -*-
r"""从裁切图精确测量微信卡片几何（v6）—— 用"从卡片中心向外扩"避免头像污染。

裁切图 wx_card2_pdf已下载.png 源自原图 (300,1090)-(1400,1440)，放大 2x。
裁切图 px / 2 = 原图 px；原图 px / 2.2 = dp。→ 裁切 px / 4.4 = dp
"""
import os

from PIL import Image

D = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(D, "_out_v1160", "wx_card2_pdf已下载.png")
K = 4.4

im = Image.open(SRC).convert("RGB")
W, H = im.size
px = im.load()
print(f"裁切图 {W}x{H}   换算：裁切px / {K} = dp\n")

CARD = (44, 44, 44)


def near(c, t, tol=10):
    return all(abs(c[i] - t[i]) < tol for i in range(3))


def dp(v):
    return v / K


# ---------- 卡片竖向（x=40 在卡内左侧） ----------
col = 40
a = b = 0
for y in range(H):
    if near(px[col, y], CARD):
        a = y
        break
for y in range(H - 1, -1, -1):
    if near(px[col, y], CARD):
        b = y
        break
print(f"=== 卡片竖向 y=[{a},{b}] 高 {b - a + 1}px = {dp(b - a + 1):.1f}dp")

# ---------- 卡片横向：从卡片中心向左 / 右各走一步找边界 ----------
mid = (a + b) // 2
# 找一个肯定在卡片内的点（x=100）
cx = 100
L = cx
while L > 0 and near(px[L - 1, mid], CARD):
    L -= 1
R = cx
while R < W - 1 and near(px[R + 1, mid], CARD):
    R += 1
print(f"=== 卡片横向 x=[{L},{R}] 宽 {R - L + 1}px = {dp(R - L + 1):.1f}dp")

# ---------- PDF 图标（红色）----------
def is_red(c):
    return c[0] > 150 and c[1] < 100 and c[2] < 90


pts = [(x, y) for x in range(L, R + 1) for y in range(a, b + 1)
       if is_red(px[x, y])]
if pts:
    xsv = [p[0] for p in pts]
    ysv = [p[1] for p in pts]
    ix0, ix1 = min(xsv), max(xsv)
    iy0, iy1 = min(ysv), max(ysv)
    iw, ih = ix1 - ix0 + 1, iy1 - iy0 + 1
    print(f"\n=== PDF 图标（红色块）===")
    print(f"  x=[{ix0},{ix1}] 宽 {iw}px = {dp(iw):.1f}dp")
    print(f"  y=[{iy0},{iy1}] 高 {ih}px = {dp(ih):.1f}dp")
    print(f"  宽高比 = {iw / ih:.3f}")
    print(f"  右内边距（图标右→卡右） = {R - ix1}px = {dp(R - ix1):.1f}dp")
    print(f"  上内边距（卡上→图标上） = {iy0 - a}px = {dp(iy0 - a):.1f}dp")
    print(f"  下内边距（图标下→卡下） = {b - iy1}px = {dp(b - iy1):.1f}dp")

    # 文字（亮灰）
    def is_text(c):
        return c[0] > 170 and c[1] > 170 and c[2] > 170

    tpts = [(x, y) for x in range(L, ix0 - 5) for y in range(a, b + 1)
            if is_text(px[x, y])]
    if tpts:
        tx0 = min(p[0] for p in tpts)
        tx1 = max(p[0] for p in tpts)
        ty0 = min(p[1] for p in tpts)
        ty1 = max(p[1] for p in tpts)
        print(f"\n=== 文字区 ===")
        print(f"  文字 x=[{tx0},{tx1}]")
        print(f"  左内边距（卡左→文字左） = {tx0 - L}px = {dp(tx0 - L):.1f}dp")
        print(f"  文字上 y={ty0} → 上内边距 = {ty0 - a}px = {dp(ty0 - a):.1f}dp")
        print(f"  文字下 y={ty1} → 下内边距 = {b - ty1}px = {dp(b - ty1):.1f}dp")
        print(f"  图标左边距文字最右 = {ix0 - tx1}px = {dp(ix0 - tx1):.1f}dp")
        print(f"\n=== 公式 ===")
        print(f"  {dp(tx0 - L):.1f}(左) + {dp(ix0 - tx1):.1f}(间距) + "
              f"{dp(iw):.1f}(图标) + {dp(R - ix1):.1f}(右) "
              f"= {dp(tx0 - L + (ix0 - tx1) + iw + (R - ix1)):.1f}")
        print(f"  卡片实宽 = {dp(R - L + 1):.1f}")
