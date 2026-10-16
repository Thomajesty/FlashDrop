# -*- coding: utf-8 -*-
"""量取微信表情面板内部：格子尺寸、列数、行数、图标可视尺寸。

面板边界（上一步测得）：x 91~554 (464px 宽) · y 42~705 (664px 高)
表情是彩色圆脸，背景纯白。对每一列统计「非白像素」数量，可找到格子中心。
"""
from PIL import Image

P = r"C:\Users\Administrator\Desktop\剪贴板_665749.png"
im = Image.open(P).convert("RGB")
px = im.load()

X0, X1 = 91, 554
Y0, Y1 = 42, 705


def is_whiteish(c, tol=12):
    return c[0] > 255 - tol and c[1] > 255 - tol and c[2] > 255 - tol


# ---- 先定位「所有表情」网格区（下半部分）----
# 面板上部是「最近使用」(1 行「最近使用」标题 + 1 行表情)，
# 中下部是「所有表情」标题 + 网格。先做横向投影找列边界。
def nonwhite_count_in_row(y, x0=X0 + 6, x1=X1 - 6):
    return sum(1 for x in range(x0, x1) if not is_whiteish(px[x, y]))


# 找所有「有内容」的行
rows_with = [y for y in range(Y0, Y1 + 1)
             if nonwhite_count_in_row(y) > 8]
print("有内容行数:", len(rows_with), "范围:", rows_with[0], rows_with[-1])

# 把连续的有内容行切成「带」
bands = []
s = None
prev = None
for y in rows_with:
    if s is None:
        s = y
    elif prev is not None and y - prev > 4:
        bands.append((s, prev))
        s = y
    prev = y
if s is not None:
    bands.append((s, prev))
print("内容带（行方向）:", len(bands))
for b in bands:
    print("   y %4d ~ %4d   高=%3d" % (b[0], b[1], b[1] - b[0] + 1))

# ---- 对最宽的一条带（网格带）做纵向投影，找列间距 ----
if bands:
    grid_band = max(bands, key=lambda b: b[1] - b[0])
    gy0, gy1 = grid_band
    print("\n网格带:", gy0, "~", gy1)

    def nonwhite_count_in_col(x, y0=gy0, y1=gy1):
        return sum(1 for y in range(y0, y1 + 1) if not is_whiteish(px[x, y]))

    cols_with = [x for x in range(X0, X1 + 1)
                 if nonwhite_count_in_col(x) > 4]
    # 切列
    cbands = []
    s = None
    prev = None
    for x in cols_with:
        if s is None:
            s = x
        elif prev is not None and x - prev > 4:
            cbands.append((s, prev))
            s = x
        prev = x
    if s is not None:
        cbands.append((s, prev))
    print("网格列数:", len(cbands))
    for c in cbands:
        print("   x %4d ~ %4d   宽=%3d" % (c[0], c[1], c[1] - c[0] + 1))
    if len(cbands) >= 2:
        pitch = cbands[1][0] - cbands[0][0]
        print("列间距(pitch):", pitch)
        ws = [c[1] - c[0] + 1 for c in cbands]
        print("列宽: min=%d max=%d avg=%.1f" % (min(ws), max(ws), sum(ws) / len(ws)))

    # 行：对网格带内的每一行找「图标可视高度」——取一个格子的 y 跨度
    # 用第一列的范围做纵向投影
    c0 = cbands[0]
    ys = [y for y in range(gy0, gy1 + 1)
          if any(not is_whiteish(px[x, y]) for x in range(c0[0], c0[1] + 1))]
    rbands = []
    s = None
    prev = None
    for y in ys:
        if s is None:
            s = y
        elif prev is not None and y - prev > 4:
            rbands.append((s, prev))
            s = y
        prev = y
    if s is not None:
        rbands.append((s, prev))
    print("\n第一列上的行数:", len(rbands))
    for r in rbands:
        print("   y %4d ~ %4d   高=%3d" % (r[0], r[1], r[1] - r[0] + 1))
    if len(rbands) >= 2:
        rpitch = rbands[1][0] - rbands[0][0]
        print("行间距(pitch):", rpitch)
        hs = [r[1] - r[0] + 1 for r in rbands]
        print("行高(图标可视): min=%d max=%d avg=%.1f" % (min(hs), max(hs), sum(hs) / len(hs)))
