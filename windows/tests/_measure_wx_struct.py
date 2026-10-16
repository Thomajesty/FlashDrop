# -*- coding: utf-8 -*-
"""量取微信表情面板的完整纵向结构：
   面板高 664px 里，标题区 / 最近使用 / 所有表情网格 各占多少，
   网格共几行。
"""
from PIL import Image

P = r"C:\Users\Administrator\Desktop\剪贴板_665749.png"
im = Image.open(P).convert("RGB")
px = im.load()
X0, X1 = 91, 554
Y0, Y1 = 42, 705


def is_whiteish(c, tol=12):
    return c[0] > 255 - tol and c[1] > 255 - tol and c[2] > 255 - tol


def row_nw(y):
    return sum(1 for x in range(X0 + 2, X1 - 2) if not is_whiteish(px[x, y]))


# 逐行打印非白像素数，帮助识别区块
print("行  y   nw")
prev_zero = True
blocks = []
for y in range(Y0, Y1 + 1):
    n = row_nw(y)
    z = n <= 3
    if z != prev_zero:
        blocks.append((y, "START-EMPTY" if z else "START-CONTENT", n))
        prev_zero = z
print("区块切换点:")
for b in blocks[:40]:
    print("   y=%4d  %s  nw=%d" % b)

# 表情行（图标）判定：非白像素多且行高小
rows = [(y, row_nw(y)) for y in range(Y0, Y1 + 1)]
content_rows = [y for y, n in rows if n > 8]
# 切带
bands = []
s = None
prev = None
for y in content_rows:
    if s is None:
        s = y
    elif prev is not None and y - prev > 4:
        bands.append((s, prev))
        s = y
    prev = y
if s is not None:
    bands.append((s, prev))

print("\n=== 各带（高 <= 40 视为表情行/文字行，高 > 40 视为网格块）===")
emoji_rows = []
for b in bands:
    h = b[1] - b[0] + 1
    kind = "GRID-BLOCK" if h > 40 else ("text-or-icon" if h > 8 else "thin")
    print("   y %4d ~ %4d  h=%3d  %s" % (b[0], b[1], h, kind))
    if 15 <= h <= 30:
        emoji_rows.append(b)

print("\n识别出的单行表情行数:", len(emoji_rows))
for b in emoji_rows:
    print("   y %4d ~ %4d  h=%d" % (b[0], b[1], b[1] - b[0] + 1))
if len(emoji_rows) >= 2:
    st = [b[0] for b in emoji_rows]
    print("行起点:", st)
    print("行 pitch:", [st[i + 1] - st[i] for i in range(len(st) - 1)])

print("\n面板总高:", Y1 - Y0 + 1)
