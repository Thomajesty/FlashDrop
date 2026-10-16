# -*- coding: utf-8 -*-
"""量测微信安卓版「表情面板 + 键盘」的占比，用于修正 FlashDrop 面板高度。

参考图 1000403321.jpg（1440x3088）：微信安卓，表情面板展开 + 键盘可见。
目标：算出「表情面板高度 / 屏幕高度」以及「键盘高度 / 屏幕高度」。
"""
from PIL import Image

P = r"C:\Users\Administrator\Desktop\1000403321.jpg"
im = Image.open(P).convert("RGB")
W, H = im.size
print("尺寸:", W, H)
px = im.load()


def is_dark_bg(c, tol=18):
    """微信深色模式背景 ~ (32,32,32)"""
    return abs(c[0] - 32) <= tol and abs(c[1] - 32) <= tol and abs(c[2] - 32) <= tol


# 从底部往上找到键盘顶边（键盘键帽是浅灰 ~ (80,80,80)）
# 先打印底部若干行的平均亮度，帮助定位分界
print("\n底部各行平均亮度（从 y=H-1 往上每 40px 采样）:")
for y in range(H - 10, 1400, -80):
    n = 0
    for x in range(0, W, 20):
        c = px[x, y]
        n += c[0] + c[1] + c[2]
    print("   y=%4d  平均=%.1f" % (y, n / (3 * (W // 20 + 1))))
