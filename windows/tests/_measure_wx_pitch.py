# -*- coding: utf-8 -*-
"""从已定位的行带推导微信表情面板的格子规格。

行带（图标可视行）：
  y 382~404 / 425~448 / 469~492 / 513~536 / 558~580 / 602~624
  → 相邻起点差 = 43~44px，图标可视高 ≈ 23~24px
"""
from PIL import Image

P = r"C:\Users\Administrator\Desktop\剪贴板_665749.png"
im = Image.open(P).convert("RGB")
px = im.load()
X0, X1 = 91, 554

# 取一条"网格行"带做纵向投影，数出列数
GY0, GY1 = 382, 404          # 其中一条表情行


def is_whiteish(c, tol=12):
    return c[0] > 255 - tol and c[1] > 255 - tol and c[2] > 255 - tol


def col_has(x):
    return any(not is_whiteish(px[x, y]) for y in range(GY0, GY1 + 1))


cols = [x for x in range(X0, X1 + 1) if col_has(x)]
cbands = []
s = None
prev = None
for x in cols:
    if s is None:
        s = x
    elif prev is not None and x - prev > 5:
        cbands.append((s, prev))
        s = x
    prev = x
if s is not None:
    cbands.append((s, prev))

print("该行检测到 %d 个图标列" % len(cbands))
for c in cbands:
    print("   x %4d ~ %4d  宽=%2d" % (c[0], c[1], c[1] - c[0] + 1))
if len(cbands) >= 2:
    pitches = [cbands[i + 1][0] - cbands[i][0] for i in range(len(cbands) - 1)]
    print("\n列间距样本:", pitches)
    print("列间距均值: %.1f" % (sum(pitches) / len(pitches)))
ws = [c[1] - c[0] + 1 for c in cbands]
print("图标可视宽: min=%d max=%d avg=%.1f" % (min(ws), max(ws), sum(ws) / len(ws)))

# 行带起点
row_starts = [382, 425, 469, 513, 558, 602]
rp = [row_starts[i + 1] - row_starts[i] for i in range(len(row_starts) - 1)]
print("\n行间距样本:", rp, "均值: %.1f" % (sum(rp) / len(rp)))

# 首列左边界 -> 面板左边界 的留白
print("\n面板左边界=%d, 首个图标左=%d, 左侧留白=%d" % (X0, cbands[0][0], cbands[0][0] - X0))
print("面板右边界=%d, 末个图标右=%d, 右侧留白=%d" % (X1, cbands[-1][1], X1 - cbands[-1][1]))

# 推算格子边长 = 列间距 - 间隙；微信格子间隙很小
print("\n=== 推算 ===")
pitch = sum(pitches) / len(pitches)
print("列 pitch ≈ %.1f px" % pitch)
print("图标可视 ≈ 23~24 px")
print("→ 若格子 = pitch = %.0f，间隙 ≈ %.0f px" % (pitch, pitch - 24))
