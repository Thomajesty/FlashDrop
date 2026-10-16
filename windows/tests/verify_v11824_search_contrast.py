# -*- coding: utf-8 -*-
"""v1.18.24 搜索结果可读性「视觉验收」（量化版）

背景：用户反馈安卓搜索结果"没有底色，黑色文字 + 透明背景"。
本脚本不靠肉眼，而是**从 FdTheme.java 解析真实调色板**，按 WCAG 2.1
计算搜索结果行的实际对比度，深/浅双主题都必须达标。

运行：python windows/tests/verify_v11824_search_contrast.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
THEME = os.path.join(ROOT, "android", "app", "src", "main", "java",
                     "com", "flashdrop", "app", "FdTheme.java")

FAILS = []
N = 0


def ck(name, cond, extra=""):
    global N
    N += 1
    if not cond:
        FAILS.append(f"{name} | {extra}")
    print(("  ok  " if cond else " FAIL ") + name +
          ((" | " + str(extra)) if extra else ""))


def srgb_to_linear(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def rel_luminance(argb):
    r = (argb >> 16) & 0xFF
    g = (argb >> 8) & 0xFF
    b = argb & 0xFF
    return (0.2126 * srgb_to_linear(r)
            + 0.7152 * srgb_to_linear(g)
            + 0.0722 * srgb_to_linear(b))


def contrast(a, b):
    la, lb = rel_luminance(a), rel_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def hexs(v):
    return "#%06X" % (v & 0xFFFFFF)


def parse_palette():
    """从 FdTheme.java 解析深/浅两套调色板（按 if(dark){} else{} 分块）。"""
    src = open(THEME, encoding="utf-8").read()
    dark_at = src.index("if (dark) {")
    else_at = src.index("} else {", dark_at)
    end_at = src.index("bubbleInRes", else_at)
    out = {}
    for name, block in (("深色", src[dark_at:else_at]),
                        ("浅色", src[else_at:end_at])):
        pal = {}
        for m in re.finditer(r"(\w+)\s*=\s*0x([0-9A-Fa-f]{8})", block):
            pal[m.group(1)] = int(m.group(2), 16)
        out[name] = pal
    # bar 在源码里是常量（DARK_BAR / LIGHT_BAR）而不是字面量，正则抓不到 → 补齐
    for name, const in (("深色", "DARK_BAR"), ("浅色", "LIGHT_BAR")):
        m = re.search(const + r"\s*=\s*(0x[0-9A-Fa-f]{8})", src)
        if m:
            out[name].setdefault("bar", int(m.group(1), 16))
    return out


def main():
    print("=" * 68)
    print("v1.18.24 搜索结果可读性 · 视觉验收（WCAG 2.1）")
    print("=" * 68)

    pal = parse_palette()
    ck("解析到深色 / 浅色两套调色板",
       "深色" in pal and "浅色" in pal
       and "card" in pal["深色"] and "card" in pal["浅色"],
       str({k: sorted(v) for k, v in pal.items()}))

    for theme_name in ("深色", "浅色"):
        p = pal[theme_name]
        card, bg = p["card"], p["bg"]
        text, dim, border = p["text"], p["dim"], p["border"]
        print(f"\n[{theme_name}主题]  行底色 card={hexs(card)}  "
              f"列表底 bg={hexs(bg)}")
        print(f"           标题 text={hexs(text)}  摘要 dim={hexs(dim)}  "
              f"分隔线 border={hexs(border)}")

        # 1) 底色必须不透明（alpha = FF）—— 透明正是用户看到的 bug
        for cname, c in (("card", card), ("bg", bg)):
            ck(f"{theme_name}·{cname} 不透明（alpha=FF）",
               (c >> 24) & 0xFF == 0xFF, hexs(c))

        # 2) 行底色与列表底色必须能区分 → 证明"有底色"看得出来
        d_card_bg = contrast(card, bg)
        ck(f"{theme_name}·行底色与列表底色可区分（CR={d_card_bg:.2f} ≥1.10）",
           d_card_bg >= 1.10, f"{d_card_bg:.3f}")

        # 3) 标题对行底色：正文级 AA 4.5
        cr_title = contrast(text, card)
        ck(f"{theme_name}·标题对行底色 CR={cr_title:.2f} ≥4.5（AA 正文）",
           cr_title >= 4.5, f"{cr_title:.3f}")

        # 4) 摘要对行底色：次级文字 AA-large 3.0（放宽到 3.0）
        cr_dim = contrast(dim, card)
        ck(f"{theme_name}·摘要对行底色 CR={cr_dim:.2f} ≥3.0（AA 大字）",
           cr_dim >= 3.0, f"{cr_dim:.3f}")

        # 5) 分隔线对行底色：可见但不必强对比（≥1.15）
        cr_border = contrast(border, card)
        ck(f"{theme_name}·分隔线对行底色可见（CR={cr_border:.2f} ≥1.15）",
           cr_border >= 1.15, f"{cr_border:.3f}")

    # 6) 回归护栏：旧实现里行没有背景，确认源码里已显式设背景
    ma_path = os.path.join(ROOT, "android", "app", "src", "main", "java",
                           "com", "flashdrop", "app", "MainActivity.java")
    ma = open(ma_path, encoding="utf-8").read()
    print("\n[源码护栏]")
    ck("搜索结果行显式设背景 row.setBackgroundColor(theme.card)",
       "row.setBackgroundColor(theme.card)" in ma)
    ck("搜索结果列表显式设背景 searchResultList.setBackgroundColor(theme.bg)",
       "searchResultList.setBackgroundColor(theme.bg)" in ma)
    ck("分隔线跟随主题（不再写死 #2E3138）",
       "searchResultList.setDivider(" in ma and "theme.border" in ma)

    # 7) ★ v1.18.25：sel_bar 形变按钮（删除 ↔ 搜全局）的配色验收
    print("\n[v1.18.25 形变按钮配色]")
    for theme_name in ("深色", "浅色"):
        p = pal[theme_name]
        card, text, red = p["card"], p["text"], p["red"]
        # 搜索态「搜全局」= 正文色 text 压在按钮底色 card 上 → 正文级 AA
        cr_glb = contrast(text, card)
        ck(f"{theme_name}·搜全局（正文色）对按钮底 CR={cr_glb:.2f} ≥4.5",
           cr_glb >= 4.5, f"{cr_glb:.3f}")
        # 设备态「删除」= 语义警示红 red → 只要求 AA-large 3.0
        # （红色是警示语义色，不能为对比度改色相；与既有设计一致）
        cr_del = contrast(red, card)
        ck(f"{theme_name}·删除（警示红）对按钮底 CR={cr_del:.2f} ≥3.0",
           cr_del >= 3.0, f"{cr_del:.3f}")
    ck("形变按钮按模式取色（搜索态用正文色，不再用警示红）",
       "btnDelete.setTextColor(searchMode ? theme.text : theme.red)" in ma)
    ck("形变过程字色连续渐变（ArgbEvaluator，不跳变）",
       "ArgbEvaluator" in ma and "btnDelete.setTextColor(" in ma)

    # 8) ★ v1.18.26：状态栏可见性（用户反馈"页面顶部手机导航栏不显示"）
    print("\n[v1.18.26 状态栏可见性]")
    for theme_name in ("深色", "浅色"):
        p = pal[theme_name]
        # 深色主题：状态栏底 #15171B（硬编码，略深于页面）+ 浅色图标；
        # 浅色主题：状态栏底 = theme.bar（白）+ 深色图标（v1.18.26 起动态切换）
        bg_bar = 0xFF15171B if theme_name == "深色" else p["bar"]
        icon = 0xFFFFFFFF if theme_name == "深色" else 0xFF000000
        cr = contrast(icon, bg_bar)
        ck(f"{theme_name}·状态栏图标对状态栏底 CR={cr:.2f} ≥3.0",
           cr >= 3.0, f"{hexs(bg_bar)} / {hexs(icon)} / {cr:.3f}")
    ck("状态栏底色跟随主题（浅色用 bar、深色用 #15171B）",
       "getWindow().setStatusBarColor(theme.dark ? 0xFF15171B : theme.bar)"
       in ma)
    ck("★ 状态栏图标明暗按主题动态切（浅底→深色图标，否则白底白字看不见）",
       "SYSTEM_UI_FLAG_LIGHT_STATUS_BAR" in ma
       and "sf |= View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR" in ma
       and "sf &= ~View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR" in ma
       and "Build.VERSION.SDK_INT >= Build.VERSION_CODES.M" in ma)

    print("\n" + "=" * 68)
    print(f"结果：{N - len(FAILS)}/{N} 通过")
    if FAILS:
        print("失败项：")
        for f in FAILS:
            print("  - " + f)
        return 1
    print("全部通过 —— 搜索结果在深浅双主题下均有不透明底色且文字达标")
    return 0


if __name__ == "__main__":
    sys.exit(main())
