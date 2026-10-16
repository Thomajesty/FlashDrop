# -*- coding: utf-8 -*-
"""把 release/latest/screenshots/ 下的逐项验收截图拼成 1 张总览图。

用法：
    python tools/make_overview.py              # 默认处理 release/latest
    python tools/make_overview.py <版本号>      # 例如 1.18.14

约定：截图命名 `NN_平台_内容.png`（NN 为两位序号，00_ 开头的是总览图本身，会被跳过）。
输出：release/latest/screenshots/00_总览.png
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

VERSION = sys.argv[1] if len(sys.argv) > 1 else None
SHOTS = os.path.join(ROOT, "release", "latest", "screenshots")
OUT = os.path.join(SHOTS, "00_总览.png")

BG = (24, 26, 31)
TITLE = (232, 234, 238)
SUB = (140, 146, 156)
PAD = 20
GAP = 16
MAXW = 1400
CAP_H = 30


def fnt(size, bold=False):
    for name in (("msyhbd.ttc" if bold else "msyh.ttc"), "simhei.ttf"):
        p = os.path.join("C:\\Windows\\Fonts", name)
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def caption_for(fn):
    """按文件名给出一句说明；找不到就退回文件名。"""
    base = os.path.basename(fn)
    table = {
        # v1.18.15
        "01_pending_fix.png": "离线待发队列：确认送达才移除 + 周期重试（两端对称修复）",
        # v1.18.14
        "01_win_icon_compare.png": "① 电脑端表情放大：旧 EXE / 新 EXE / 微信 三方对比（14px → 25px）",
        "02_win_real_exe_after.png": "① 新 EXE 实拍：图标可视 25px",
        "03_win_real_exe_before.png": "① 旧 EXE 实拍：图标可视 14px（被全局 QSS padding 压小）",
        "04_android_panel_height.png": "② 安卓面板高度对齐键盘（1346px → 1208px）",
        "05_android_kbd_switch.png": "③ 安卓 表情⇄键盘 切换动效（26dp 轻推 → 整高位移）",
        # v1.18.13
        "01_win_emoji_vs_wx.png": "① 电脑版表情面板对齐微信（微信实拍 / 旧版 / 新版）",
        "02_android_devbar.png": "③ 安卓设备选择栏：收起态灯贴右 · 展开态名字完整 · 灯对齐 · ✕ 在灯后",
        "03_android_group_rename.png": "④ 安卓表情分组「其他」→「全部表情」",
        "04_android_panel_height.png_v13": "⑤ 安卓表情面板高度 ≈ 键盘高度",
        "05_android_kbd_switch.png_v13": "⑤ 表情 ⇄ 键盘 互切时序（无闪动）",
    }
    return table.get(base, base)


def main():
    if not os.path.isdir(SHOTS):
        print("目录不存在：", SHOTS)
        return 1

    files = sorted(f for f in os.listdir(SHOTS)
                   if f.lower().endswith(".png") and not f.startswith("00_"))
    if not files:
        print("没有可拼接的截图：", SHOTS)
        return 1

    items = []
    for fn in files:
        im = Image.open(os.path.join(SHOTS, fn)).convert("RGB")
        if im.width > MAXW:
            r = MAXW / im.width
            im = im.resize((MAXW, int(im.height * r)), Image.LANCZOS)
        items.append((im, caption_for(fn)))

    ver = VERSION or "latest"
    total_h = 90 + sum(im.height + CAP_H + GAP for im, _ in items) + PAD
    canvas = Image.new("RGB", (MAXW + PAD * 2, total_h), BG)
    d = ImageDraw.Draw(canvas)

    d.text((PAD, 20), "FlashDrop v%s 验收总览" % ver, font=fnt(26, True), fill=TITLE)
    d.text((PAD, 56), "逐项截图 + 代码审计对照 · %d 张" % len(items),
           font=fnt(14), fill=SUB)

    y = 90
    for im, cap in items:
        d.text((PAD, y), cap, font=fnt(14, True), fill=SUB)
        y += CAP_H
        canvas.paste(im, (PAD, y))
        y += im.height + GAP

    canvas.save(OUT)
    print("saved:", OUT, canvas.width, "x", canvas.height)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
