# -*- coding: utf-8 -*-
"""v1.18.13 安卓端验收截图（按 Java/XML 真实参数用 PIL 还原）。

产出 tests/：
  v11813_devbar.png        ③ 设备选择栏：收起态（灯贴右）vs 展开态（名字完整 + 灯对齐 + ✕ 在灯后）
  v11813_group_rename.png  ④ 底部分类条：末位由「其他」改为「全部表情」
  v11813_panel_height.png  ⑤ 面板高度：与 36% 屏高的键盘等高（对齐微信）
  v11813_kbd_switch.png    ⑤ 表情 ⇄ 键盘 互切时序（先收面板/等 IME 收完再展开，无闪动）
"""
import json
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CATALOG = os.path.join(ROOT, "app", "src", "main", "assets", "emoji_catalog.json")
EMOJI_DIR = os.path.join(ROOT, "app", "src", "main", "res", "drawable-nodpi")

DP = 3
GROUP_CN = {
    "Smileys & Emotion": "表情", "People & Body": "人物",
    "Animals & Nature": "动物", "Food & Drink": "食物",
    "Travel & Places": "旅行", "Activities": "活动",
    "Objects": "物品", "Symbols": "符号", "Flags": "旗帜",
    "Other": "全部表情",          # ★ v1.18.13 改名后的文案
}
TAB_ICON = ["😀", "🧑", "🐻", "🍔", "🚗", "⚽", "💡", "❤", "🏳", "⋯"]

BG = (11, 12, 16)
BAR = (31, 33, 38)
CARD = (38, 41, 48)
BORDER = (52, 56, 64)
TEXT = (232, 234, 238)
DIM = (140, 146, 156)
ACCENT = (59, 130, 246)
INPUT_BG = (44, 47, 54)
GREEN = (52, 199, 89)
GREY = (110, 116, 126)


def fnt(size, bold=False):
    for name in (("msyhbd.ttc" if bold else "msyh.ttc"), "simhei.ttf"):
        p = os.path.join("C:\\Windows\\Fonts", name)
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def sym_fnt(size):
    """✕ / ✖ 这类符号用 seguisym 渲染，msyh 的 U+2715 会出豆腐块。"""
    for name in ("seguisym.ttf", "arial.ttf", "simhei.ttf"):
        p = os.path.join("C:\\Windows\\Fonts", name)
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return fnt(size)


def dpx(v):
    return int(round(v * DP))


def load_emoji(slug, size):
    p = os.path.join(EMOJI_DIR, "e_%s.png" % slug.replace("-", "_"))
    if not os.path.exists(p):
        return None
    im = Image.open(p).convert("RGBA")
    return im.resize((size, size), Image.LANCZOS)


def paste_emoji(canvas, slug, cx, cy, size):
    ico = load_emoji(slug, size)
    if ico is None:
        return False
    canvas.paste(ico, (cx - size // 2, cy - size // 2), ico)
    return True


def draw_dot(d, cx, cy, r, on):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(GREEN if on else GREY))


# ─────────────────────────────────────────────────────────────
# ③ 设备选择栏：收起态 vs 展开态
#    Java 参数：行高 40dp、左右 padding 14dp、名字→灯 8dp、
#               DOT_SLOT_DP=22（灯右对齐）、X_SLOT_DP=34
# ─────────────────────────────────────────────────────────────
def shot_devbar():
    W = dpx(250)
    ROW = dpx(40)
    ROWS = [("我的手机", True), ("办公室笔记本", False), ("iPad Pro 11", True)]
    GAP = dpx(10)
    H = ROW * 2 + GAP + dpx(30) * 3 + dpx(26)

    im = Image.new("RGB", (W, H), BAR)
    d = ImageDraw.Draw(im)

    # ── 收起态 ──
    y0 = dpx(8)
    d.text((dpx(14), dpx(2)), "收起态（未展开）", font=fnt(dpx(8), True), fill=DIM)
    row_top = y0 + dpx(14)
    d.rounded_rectangle([dpx(8), row_top, W - dpx(8), row_top + ROW],
                        radius=dpx(8), fill=INPUT_BG)
    # 名字（占满，最长可显示）
    d.text((dpx(14), row_top + dpx(12)), "我的手机", font=fnt(dpx(11)), fill=TEXT)
    # 状态灯：右对齐到 DOT_SLOT 右沿，再往左留 X_SLOT 空位
    x_right = W - dpx(14) - dpx(34)          # X 槽占位
    dot_cx = x_right - dpx(22) + dpx(22) - dpx(5)   # 22dp 槽内右贴
    dot_cx = x_right - dpx(5)
    draw_dot(d, dot_cx, row_top + ROW // 2, dpx(4.5), True)
    # 说明：右侧没有任何 ✕
    d.text((dpx(14), row_top + ROW + dpx(4)),
           "灯贴最右（✕ 槽为收起态空占位，不影响灯 x）",
           font=fnt(dpx(7)), fill=DIM)

    # ── 展开态 ──
    y1 = row_top + ROW + dpx(22)
    d.text((dpx(14), y1), "展开态（下拉）", font=fnt(dpx(8), True), fill=DIM)
    top = y1 + dpx(14)
    for i, (nm, on) in enumerate(ROWS):
        rt = top + i * ROW
        if i == 0:
            d.rounded_rectangle([dpx(8), rt, W - dpx(8), rt + ROW],
                                radius=dpx(8), fill=(48, 52, 60))
        else:
            d.rounded_rectangle([dpx(8), rt, W - dpx(8), rt + ROW],
                                radius=dpx(6), fill=CARD)
        # 名字：限长但足够长（ellipsize END）
        d.text((dpx(14), rt + dpx(12)), nm, font=fnt(dpx(11)), fill=TEXT)
        # 灯：与收起态同一 x（关键：固定槽位）
        draw_dot(d, dot_cx, rt + ROW // 2, dpx(4.5), on)
        # ✕：在灯之后（X 槽）
        d.text((dot_cx + dpx(12), rt + dpx(10)), "✕",
               font=sym_fnt(dpx(12)), fill=DIM)
    d.text((dpx(14), top + len(ROWS) * ROW + dpx(4)),
           "名字完整 · 灯与「全部设备」同 x · ✕ 在灯右侧",
           font=fnt(dpx(7)), fill=DIM)

    out = os.path.join(HERE, "v11813_devbar.png")
    im.save(out)
    print("devbar:", im.width, "x", im.height, "->", out)


# ─────────────────────────────────────────────────────────────
# ④ 底部分类条：末位「全部表情」
# ─────────────────────────────────────────────────────────────
def shot_group_rename():
    W = dpx(250)
    H = dpx(110)
    im = Image.new("RGB", (W, H), BAR)
    d = ImageDraw.Draw(im)

    d.text((dpx(14), dpx(6)), "底部分类条（改后）", font=fnt(dpx(9), True), fill=TEXT)

    # 圆形图标工具条（图标用真实 Fluent Emoji 贴图，避免字形豆腐块）
    cat = json.load(open(CATALOG, encoding="utf-8"))
    groups = cat["groups"]
    first_slug = {}
    for g in groups:
        items = g.get("items") or g.get("emojis") or []
        if items:
            it = items[0]
            first_slug[g["name"]] = (it.get("slug") if isinstance(it, dict)
                                     else str(it))

    cy = dpx(44)
    names = list(GROUP_CN.keys())
    n = len(names)
    pad = dpx(10)
    avail = W - pad * 2
    step = avail / n
    for i, en in enumerate(names):
        cn = GROUP_CN[en]
        cx = int(pad + step * (i + 0.5))
        last = (cn == "全部表情")
        r = dpx(12)
        if last:
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=ACCENT)
        slug = first_slug.get(en)
        ok = paste_emoji(im, slug, cx, cy, dpx(15)) if slug else False
        if not ok:
            d.text((cx, cy), cn[:1], font=fnt(dpx(8)), fill=TEXT, anchor="mm")
        lab = cn if len(cn) <= 4 else cn[:4]
        d.text((cx, cy + dpx(26)), lab, font=fnt(dpx(7), last),
               fill=ACCENT if last else DIM, anchor="mm")

    d.text((W // 2, H - dpx(16)),
           "末位「其他」→「全部表情」（页签 + 标题 + 空态同步）",
           font=fnt(dpx(7)), fill=DIM, anchor="mm")

    out = os.path.join(HERE, "v11813_group_rename.png")
    im.save(out)
    print("rename:", im.width, "x", im.height, "->", out)


# ─────────────────────────────────────────────────────────────
# ⑤-A 面板高度：与键盘等高（36% 屏高）
# ─────────────────────────────────────────────────────────────
def shot_panel_height():
    W = dpx(250)
    IMG = dpx(230)          # 手机内容区高度示意
    KBD = int(IMG * 0.36)   # 36% 兜底比例（真实取 imeHeightPx）
    H = IMG + dpx(30)

    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)

    # 聊天气泡（上）
    for i, (t, out) in enumerate([("你好呀", False), ("在的，说~", True)]):
        bw = dpx(60)
        bx = (W - dpx(12) - bw) if out else dpx(12)
        by = dpx(14) + i * dpx(30)
        d.rounded_rectangle([bx, by, bx + bw, by + dpx(22)],
                            radius=dpx(8),
                            fill=(48, 82, 140) if out else CARD)

    # 输入栏
    iy = IMG - dpx(52)
    d.rounded_rectangle([dpx(8), iy, W - dpx(8), iy + dpx(44)],
                        radius=dpx(10), fill=INPUT_BG)
    d.text((dpx(20), iy + dpx(16)), "发消息…", font=fnt(dpx(9)), fill=DIM)

    # 表情面板占位（高 = KBD）
    py = IMG - KBD - dpx(52)
    d.rounded_rectangle([dpx(8), py, W - dpx(8), py + KBD],
                        radius=dpx(10), fill=CARD, outline=BORDER)
    d.text((W // 2, py + KBD // 2),
           "表情面板\n高 ≈ 键盘高 (36%%)",
           font=fnt(dpx(9)), fill=TEXT, anchor="mm", align="center")

    # 右侧标注条
    d.line([W - dpx(4), py, W - dpx(4), py + KBD], fill=ACCENT, width=dpx(2))
    d.text((W - dpx(6), py + KBD // 2), "36%%",
           font=fnt(dpx(8), True), fill=ACCENT, anchor="rm")

    d.text((dpx(12), H - dpx(20)),
           "panelHeight()：优先用真实 IME 高度，夹在 28%%~50%% 屏高",
           font=fnt(dpx(7)), fill=DIM)

    out = os.path.join(HERE, "v11813_panel_height.png")
    im.save(out)
    print("panel_height:", im.width, "x", im.height, "->", out)


# ─────────────────────────────────────────────────────────────
# ⑤-B 表情 ⇄ 键盘 互切时序
# ─────────────────────────────────────────────────────────────
def shot_kbd_switch():
    W = dpx(250)
    H = dpx(150)
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)

    d.text((dpx(12), dpx(6)), "表情 ⇄ 键盘 互切时序（消除闪动）",
           font=fnt(dpx(9), True), fill=TEXT)

    steps = [
        ("收面板：slideOut（纯位移，无 alpha）", "面板下移出屏"),
        ("等 IME 真正收完（轮询 ≤320ms）", "避免两帧跳动"),
        ("展开另一侧：slideInFromBottom", "一次到位，不闪"),
    ]
    y = dpx(26)
    for i, (a, b) in enumerate(steps):
        d.rounded_rectangle([dpx(12), y, W - dpx(12), y + dpx(30)],
                            radius=dpx(8), fill=CARD, outline=BORDER)
        d.ellipse([dpx(20), y + dpx(9), dpx(32), y + dpx(21)],
                  fill=ACCENT)
        d.text((dpx(26), y + dpx(15)), str(i + 1), font=fnt(dpx(8), True),
               fill=(255, 255, 255), anchor="mm")
        d.text((dpx(40), y + dpx(6)), a, font=fnt(dpx(8)), fill=TEXT)
        d.text((dpx(40), y + dpx(17)), b, font=fnt(dpx(7)), fill=DIM)
        y += dpx(36)
        if i < len(steps) - 1:
            d.line([dpx(26), y - dpx(6), dpx(26), y - dpx(1)],
                   fill=DIM, width=dpx(1))

    d.text((dpx(12), H - dpx(16)),
           "toggleEmojiPanel()：先 hideEmojiPanelThen → 再 hideImeThen → 最后 slideIn",
           font=fnt(dpx(7)), fill=DIM)

    out = os.path.join(HERE, "v11813_kbd_switch.png")
    im.save(out)
    print("kbd_switch:", im.width, "x", im.height, "->", out)


if __name__ == "__main__":
    shot_devbar()
    shot_group_rename()
    shot_panel_height()
    shot_kbd_switch()
    print("done.")
