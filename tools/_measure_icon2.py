# -*- coding: utf-8 -*-
"""指定完整行带后量图标外接框（宽度 + 高度 + 列 pitch）。"""
import os

from PIL import Image

D = r"C:/Users/Administrator/Desktop"


def bg_light(px):
    r, g, b = px
    return r > 226 and g > 226 and b > 226 and max(r, g, b) - min(r, g, b) < 18


def measure(name, path, region, band):
    im = Image.open(path).convert("RGB")
    sub = im.crop(region)
    W, H = sub.size
    px = sub.load()
    y0, y1 = band
    # 列投影
    cols = []
    for x in range(W):
        cols.append(sum(0 if bg_light(px[x, y]) else 1 for y in range(y0, y1)))
    runs, cur = [], None
    for i, v in enumerate(cols):
        if v > 0:
            if cur is None:
                cur = i
        else:
            if cur is not None:
                if i - cur >= 4:
                    runs.append((cur, i))
                cur = None
    if cur is not None:
        runs.append((cur, len(cols)))
    print()
    print("=" * 74)
    print("%s  region=%s  band=y%d~%d" % (name, region, y0, y1))
    print("-" * 74)
    if len(runs) < 2:
        print("  列检出失败:", runs)
        return
    ws = [b - a for a, b in runs]
    ps = [runs[i + 1][0] - runs[i][0] for i in range(len(runs) - 1)]
    print("  列数      = %d" % len(runs))
    print("  各列起点  = %s" % [a for a, _b in runs])
    print("  图标宽    = %s" % ws)
    print("  列 pitch  = %s" % ps)
    print(">>> 中位图标宽 = %d px" % sorted(ws)[len(ws) // 2])
    print(">>> 中位 pitch = %d px" % sorted(ps)[len(ps) // 2])
    # 用第一列量垂直外接框
    a, b = runs[0]
    x0, x1 = a, b
    ys = [y for y in range(H)
          if any(not bg_light(px[x, y]) for x in range(x0, x1))]
    if ys:
        print(">>> 首列图标高 = %d px  (y %d~%d)" % (max(ys) - min(ys) + 1,
                                                 min(ys), max(ys)))
    # 面板宽度估计：整幅裁剪里最左/最右非背景
    allx = [x for x in range(W)
            if any(not bg_light(px[x, y]) for y in range(H))]
    if allx:
        print("  裁剪内非背景横向范围 = %d ~ %d" % (min(allx), max(allx)))


if __name__ == "__main__":
    # FlashDrop：面板在裁剪内 x≈8~470；表情行 pitch 44
    measure("FlashDrop 电脑端", os.path.join(D, "剪贴板_5427dc.png"),
            (250, 255, 760, 660), (50, 90))
    measure("FlashDrop 电脑端(第4行)", os.path.join(D, "剪贴板_5427dc.png"),
            (250, 255, 760, 660), (182, 222))
    # 微信：面板在裁剪内 x≈20~478
    measure("微信 桌面端", os.path.join(D, "微信图片_20261008210506_323_327.png"),
            (80, 60, 580, 570), (286, 334))
