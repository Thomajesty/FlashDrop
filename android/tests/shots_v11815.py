# -*- coding: utf-8 -*-
"""v1.18.15 验收图：离线待发队列「确认送达才移除」修复示意。

产出 tests/_v11815/pending_fix.png
"""
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "_v11815")
os.makedirs(OUT, exist_ok=True)

BG = (24, 26, 31)
CARD = (38, 41, 48)
TEXT = (232, 234, 238)
DIM = (140, 146, 156)
RED = (226, 75, 74)
GREEN = (99, 153, 34)
BLUE = (59, 130, 246)
AMBER = (186, 117, 23)


def fnt(size, bold=False):
    for name in (("msyhbd.ttc" if bold else "msyh.ttc"), "simhei.ttf"):
        p = os.path.join("C:\\Windows\\Fonts", name)
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def box(d, x, y, w, h, title, sub, color, dashed=False):
    d.rounded_rectangle([x, y, x + w, y + h], radius=8,
                        fill=CARD, outline=color, width=2)
    d.text((x + w / 2, y + h / 2 - 9), title, font=fnt(12, True), fill=TEXT,
           anchor="mm")
    if sub:
        d.text((x + w / 2, y + h / 2 + 10), sub, font=fnt(9), fill=DIM,
               anchor="mm")


def arrow(d, x0, y, x1, color):
    d.line([x0, y, x1 - 8, y], fill=color, width=2)
    d.polygon([(x1, y), (x1 - 9, y - 5), (x1 - 9, y + 5)], fill=color)


def lane(d, y, label, label_color, steps):
    """steps = [(标题, 副标题, 颜色)]，等距排开并用箭头连接"""
    d.text((24, y - 22), label, font=fnt(14, True), fill=label_color)
    n = len(steps)
    gap = 22
    total = 1180
    w = (total - gap * (n - 1)) // n
    x = 24
    for i, (t, s, c) in enumerate(steps):
        box(d, x, y, w, 52, t, s, c)
        if i < n - 1:
            arrow(d, x + w, y + 26, x + w + gap, c)
        x += w + gap


def main():
    W, H = 1240, 560
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)

    d.text((24, 18), "v1.18.15 离线待发队列修复：确认送达才移除 + 周期重试",
           font=fnt(18, True), fill=TEXT)
    d.text((24, 46),
           "两端同一缺陷：send_text 是异步的（内部还要等 TCP 连接最多 15s + ack 12s），"
           "但补发刚调用完就把条目删了",
           font=fnt(11), fill=DIM)

    # ── 修复前 ──
    lane(d, 110, "修复前 —— 消息必丢", RED, [
        ("设备上线", "UDP 已判在线\n触发 peers 事件", DIM),
        ("flush 补发", "调用 send_text\n（异步，立刻返回）", BLUE),
        ("★ 立刻删条目", "从队列删除\n并落盘", RED),
        ("wait_conn 失败", "TCP 其实还没建好\n等 15s 后失败", AMBER),
        ("消息永久丢失", "接收端收不到\n发送端只显示失败", RED),
    ])

    # 分隔
    d.line([24, 232, W - 24, 232], fill=(60, 64, 72), width=1)
    d.text((W - 130, 222), "队列无任何重试机制", font=fnt(10, True), fill=RED)

    # ── 修复后 ──
    lane(d, 320, "修复后 —— 不丢消息", GREEN, [
        ("设备上线", "UDP 已判在线\n触发 peers 事件", DIM),
        ("后台线程补发", "离开 UI 线程\n不卡界面", BLUE),
        ("等发送结果", "send_text_sync\n阻塞等 ack", BLUE),
        ("成功才移除", "确认送达才出队\n气泡用真实 mid", GREEN),
        ("失败则保留", "条目留在队列\n每 10s 自动重试", GREEN),
    ])

    d.rounded_rectangle([24, 452, W - 24, 524], radius=8, fill=(32, 35, 42))
    d.text((40, 470),
           "三条修法（两端对称）：① 确认送达才移除条目，失败/超时一律保留；"
           "② 补发移到工作线程，不压 UI；③ 队列非空且有在线设备时每 10s 周期重试，队列空了自动停。",
           font=fnt(12), fill=TEXT)
    d.text((40, 496),
           "附带修掉：补发期间用户新加的待发条目不再被 clear()+addAll() 误删；"
           "手动「立即重发」也不再先删条目。",
           font=fnt(11), fill=DIM)

    out = os.path.join(OUT, "pending_fix.png")
    im.save(out)
    print("saved:", out, im.size)


if __name__ == "__main__":
    main()