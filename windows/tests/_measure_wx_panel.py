# -*- coding: utf-8 -*-
"""量取微信桌面版表情面板的真实尺寸，作为 FlashDrop 的对齐基准。

参考图：剪贴板_665749.png（微信主窗口 + 表情面板浮层）
面板是白色浮层，背景是微信聊天列表（浅灰）+ 聊天区（白）。
用「纯白连续区域」的边界来定位面板，再数格子。
"""
import os
from PIL import Image

P = r"C:\Users\Administrator\Desktop\剪贴板_665749.png"
im = Image.open(P).convert("RGB")
W, H = im.size
print("图片尺寸:", W, H)

px = im.load()


def is_white(c, tol=6):
    return abs(c[0] - 255) <= tol and abs(c[1] - 255) <= tol and abs(c[2] - 255) <= tol


# 面板大致在左侧 60~500 px 区域（从缩略图目测）。
# 逐行扫描 x∈[60,520]，统计纯白像素数，找出面板的上下边界。
def row_white(y, x0=60, x1=540):
    n = 0
    for x in range(x0, x1):
        if is_white(px[x, y]):
            n += 1
    return n


counts = [(y, row_white(y)) for y in range(0, H)]
# 面板行的白像素数应接近 (x1-x0)
thr = (540 - 60) * 0.75
panel_rows = [y for y, n in counts if n > thr]
if panel_rows:
    print("面板纵向范围(粗):", panel_rows[0], "~", panel_rows[-1],
          "高度≈", panel_rows[-1] - panel_rows[0] + 1)
else:
    print("未找到面板行，放宽阈值重试")
    thr = (540 - 60) * 0.5
    panel_rows = [y for y, n in counts if n > thr]
    if panel_rows:
        print("面板纵向范围(松):", panel_rows[0], "~", panel_rows[-1],
              "高度≈", panel_rows[-1] - panel_rows[0] + 1)

# 逐列扫描找出面板左右边界（在面板中段取一行）
if panel_rows:
    ymid = (panel_rows[0] + panel_rows[-1]) // 2
    col_white = [x for x in range(0, W) if is_white(px[x, ymid])]
    # 取连续段
    segs = []
    s = None
    for x in range(0, W):
        if is_white(px[x, ymid]):
            if s is None:
                s = x
        else:
            if s is not None and x - s > 80:
                segs.append((s, x - 1))
            s = None
    if s is not None:
        segs.append((s, W - 1))
    print("面板横向连续白段:", segs)
