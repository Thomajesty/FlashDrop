# -*- coding: utf-8 -*-
"""生成下拉框箭头 PNG（灰色三角，深浅主题通用）"""
import os
from PIL import Image, ImageDraw

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "down_arrow.png")
w, h = 12, 8
img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
color = (154, 162, 172, 255)  # #9AA2AC，两种主题下都可读
for i in range(h):
    half = i * (w - 2) // (2 * h) + 1
    d.line([(half, i), (w - 1 - half, i)], fill=color)
img.save(out)
print("saved:", out)
