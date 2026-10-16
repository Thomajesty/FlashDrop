# -*- coding: utf-8 -*-
"""微信表情面板精确量测（修正版）。

从裁剪图 panel_full.png 目测（该图原点 = 原图 (60,30)）：
  面板左 ≈ x=95 / 右 ≈ x=555 / 上 ≈ y=242 / 下 ≈ y=715
结构（自上而下）：最近使用标题 → 1 行最近表情 → 所有表情标题 → 笑脸网格 7 行 → 底部工具条
"""
from PIL import Image

P = r"C:\Users\Administrator\Desktop\剪贴板_665749.png"
im = Image.open(P).convert("RGB")
px = im.load()


def is_whiteish(c, tol=10):
    return c[0] > 255 - tol and c[1] > 255 - tol and c[2] > 255 - tol


def row_all_white(y, x0=96, x1=554):
    return all(is_whiteish(px[x, y]) for x in range(x0, x1, 4))


top = None
for y in range(200, 400):
    if row_all_white(y):
        top = y
        break
print("面板上边界(全白行) y =", top)

bot = None
for y in range(735, 400, -1):
    if y < 744 and row_all_white(y):
        bot = y
        break
print("面板下边界 y =", bot)

ymid = 500
xs = [x for x in range(60, 700) if is_whiteish(px[x, ymid])]
segs = []
s = None
prev = None
for x in xs:
    if s is None:
        s = x
    elif prev is not None and x - prev > 3:
        if x - s > 200:
            segs.append((s, prev))
        s = x
    prev = x
if s is not None and (x - s) > 200:
    segs.append((s, prev))
print("面板横向段(宽>200):", [(a, b, b - a + 1) for a, b in segs])

X0, X1 = (segs[0][0], segs[0][1]) if segs else (95, 555)
print("面板: x %d~%d (宽 %d)" % (X0, X1, X1 - X0 + 1))
Y0 = top if top else 242
Y1 = bot if bot else 715
print("面板: y %s~%s (高 %s)" % (Y0, Y1, Y1 - Y0 + 1))

print("\n=== 面板内部内容带 ===")


def row_nw(y):
    return sum(1 for x in range(X0 + 2, X1 - 2) if not is_whiteish(px[x, y]))


content = [y for y in range(Y0, Y1 + 1) if row_nw(y) > 6]
bands = []
s = None
prev = None
for y in content:
    if s is None:
        s = y
    elif prev is not None and y - prev > 3:
        bands.append((s, prev))
        s = y
    prev = y
if s is not None:
    bands.append((s, prev))

for b in bands:
    h = b[1] - b[0] + 1
    print("   y %4d ~ %4d  h=%3d  (相对面板顶 +%d)" % (b[0], b[1], h, b[0] - Y0))

print("\n=== 每行内容带上各含几个图标列 ===")
for b in bands:
    if b[1] - b[0] + 1 < 12:
        continue
    ys = range(b[0], b[1] + 1)

    def col_has(x):
        return any(not is_whiteish(px[x, y]) for y in ys)

    cols = [x for x in range(X0, X1 + 1) if col_has(x)]
    cb = []
    s = None
    prev = None
    for x in cols:
        if s is None:
            s = x
        elif prev is not None and x - prev > 5:
            cb.append((s, prev))
            s = x
        prev = x
    if s is not None:
        cb.append((s, prev))
    pitch = (cb[1][0] - cb[0][0]) if len(cb) >= 2 else None
    print("   y%4d h=%2d → %2d 列  pitch=%s  首列x=%s" %
          (b[0], b[1] - b[0] + 1, len(cb), pitch, cb[0][0] if cb else None))
