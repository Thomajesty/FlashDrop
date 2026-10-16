# -*- coding: utf-8 -*-
"""生成复选框勾选图标（白色对勾，用于 QSS indicator checked 态）"""
import os
from PIL import Image, ImageDraw

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "check.png")
s = 24
img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
w = max(3, s // 6)
pts = [(5, 13), (10, 18), (19, 6)]
d.line([pts[0], pts[1]], fill=(255, 255, 255, 255), width=w)
d.line([pts[1], pts[2]], fill=(255, 255, 255, 255), width=w)
d.ellipse([pts[0][0]-w//2, pts[0][1]-w//2, pts[0][0]+w//2, pts[0][1]+w//2],
          fill=(255, 255, 255, 255))
d.ellipse([pts[2][0]-w//2, pts[2][1]-w//2, pts[2][0]+w//2, pts[2][1]+w//2],
          fill=(255, 255, 255, 255))
img.save(out)
print("saved:", out)
