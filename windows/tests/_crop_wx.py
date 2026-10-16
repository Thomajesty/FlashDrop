# -*- coding: utf-8 -*-
r"""把微信参考图里的文件卡片裁切放大，供人工核对几何规格。"""
import os

from PIL import Image

SRC = r"C:\Users\Administrator\FlashDrop\收到的文件\1000402955.jpg"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_out_v1160")
os.makedirs(OUT, exist_ok=True)

im = Image.open(SRC).convert("RGB")
print("源图", im.size)

# 第一张卡片（FlashDrop.apk.1 + 问号图标）大致 y=[615,880]，x=[300,1390]（含头像）
crops = {
    "wx_card1_问号图标.png": (300, 600, 1400, 890),
    "wx_card2_pdf已下载.png": (300, 1090, 1400, 1440),
    "wx_pdf未下载.png": (300, 1430, 1400, 1780),
    "wx_card_pdf附件.png": (300, 1780, 1400, 2130),
}
for name, box in crops.items():
    c = im.crop(box)
    c = c.resize((c.width * 2, c.height * 2), Image.LANCZOS)
    p = os.path.join(OUT, name)
    c.save(p)
    print("输出", p, c.size)
