# -*- coding: utf-8 -*-
r"""从裁切图精确测量微信文件卡片几何（v5，最终版）。

裁切图 wx_card2_pdf已下载.png 是原图 (300,1090)-(1400,1440) 放大 2 倍。
所以：裁切图像素 / 2 = 原图像素；原图 / 2.2 = dp。
综合系数：裁切图 px / 4.4 = dp
"""
import os

from PIL import Image

D = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(D, "_out_v1160", "wx_card2_pdf已下载.png")
K = 4.4   # 裁切图 px → dp

im = Image.open(SRC).convert("RGB")
W, H = im.size
px = im.load()
print(f"裁切图 {W}x{H}  系数 {K}（裁切px / 4.4 = dp）\n")


def near(c, t, tol=12):
    return all(abs(c[i] - t[i]) < tol for i in range(3))


CARD = (44, 44, 44)


def dp(v):
    return v / K


# ---------- 卡片边界：最长连续 CARD 色段 ----------
def card_row(y):
    best, s = (0, 0), None
    for x in range(W):
        if near(px[x, y], CARD):
            if s is None:
                s = x
        else:
            if s is not None and x - 1 - s > best[1] - best[0]:
                best = (s, x - 1)
            s = None
    if s is not None and W - 1 - s > best[1] - best[0]:
        best = (s, W - 1)
    return best


# 卡片竖向：在 x=30（卡内左侧空白）扫
col = 30
runs, prev, s = [], False, 0
for y in range(H):
    cur = near(px[col, y], CARD)
    if cur != prev:
        if prev:
            runs.append((s, y - 1))
        s, prev = y, cur
if prev:
    runs.append((s, H - 1))
cv = [r for r in runs if r[1] - r[0] > 100]
print("=== 卡片竖向 ===")
for a, b in cv:
    print(f"  y=[{a},{b}] 高 {b - a + 1}px = {dp(b - a + 1):.1f}dp")

a, b = cv[0] if cv else (0, H - 1)
mid = (a + b) // 2
ch0, ch1 = card_row(mid)
print(f"\n=== 卡片横向（y={mid}）===")
print(f"  x=[{ch0},{ch1}] 宽 {ch1 - ch0 + 1}px = {dp(ch1 - ch0 + 1):.1f}dp")

# ---------- PDF 图标：红色块 ----------
def is_red(c):
    return c[0] > 150 and c[1] < 100 and c[2] < 90


rxs = [x for x in range(ch0, ch1 + 1)
       for y in range(a, b + 1) if is_red(px[x, y])]
rys = [y for y in range(a, b + 1)
       for x in range(ch0, ch1 + 1) if is_red(px[x, y])]
if rxs:
    ix0, ix1 = min(rxs), max(rxs)
    iy0, iy1 = min(rys), max(rys)
    iw, ih = ix1 - ix0 + 1, iy1 - iy0 + 1
    print(f"\n=== PDF 图标（红色块）===")
    print(f"  x=[{ix0},{ix1}] 宽 {iw}px = {dp(iw):.1f}dp")
    print(f"  y=[{iy0},{iy1}] 高 {ih}px = {dp(ih):.1f}dp")
    print(f"  宽高比 = {iw / ih:.3f}")
    print(f"  >>> 图标右边距卡右  = {ch1 - ix1}px = {dp(ch1 - ix1):.1f}dp")
    print(f"  >>> 图标上距卡上    = {iy0 - a}px = {dp(iy0 - a):.1f}dp")
    print(f"  >>> 图标下距卡下    = {b - iy1}px = {dp(b - iy1):.1f}dp")
    print(f"  >>> 图标垂直居中偏移 = "
          f"{dp((iy0 - a) - (b - iy1)):.1f}dp (正=偏下)")

# ---------- 文字 ----------
def is_text(c):
    return c[0] > 170 and c[1] > 170 and c[2] > 170


txs = [x for x in range(ch0, ch1 + 1)
       for y in range(a, b + 1) if is_text(px[x, y])]
tys = [y for y in range(a, b + 1)
       for x in range(ch0, ch1 + 1) if is_text(px[x, y])]
if txs:
    print(f"\n=== 文字区 ===")
    print(f"  文字最左 x={min(txs)} → 左内边距 = "
          f"{min(txs) - ch0}px = {dp(min(txs) - ch0):.1f}dp")
    print(f"  文字最右 x={max(txs)} （仅该行内）")
    print(f"  文字上 y={min(tys)} → 上内边距 = "
          f"{min(tys) - a}px = {dp(min(tys) - a):.1f}dp")
    print(f"  文字下 y={max(tys)} → 下内边距 = "
          f"{b - max(tys)}px = {dp(b - max(tys)):.1f}dp")
    if rxs:
        print(f"  >>> 图标左边距文字最右 = {ix0 - max(txs)}px "
              f"= {dp(ix0 - max(txs)):.1f}dp")

print(f"\n=== 汇总公式校验 ===")
if rxs and txs:
    print(f"  左内边距 {dp(min(txs) - ch0):.1f} + 文字区 + 间距 + "
          f"图标 {dp(iw):.1f} + 右内边距 {dp(ch1 - ix1):.1f} = "
          f"{dp(ch1 - ch0 + 1):.1f}")
