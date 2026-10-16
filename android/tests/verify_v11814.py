# -*- coding: utf-8 -*-
"""v1.18.14 专项验收 —— 用户 2 条反馈的代码审计。

用户第 1 条（安卓）：表情选择页比输入法高一行 → 对齐键盘高度 + 优化切换动效
用户第 2 条（电脑）：表情包显示太小 → 放大到微信尺寸

本脚本做**源码级审计**；像素级验证见 windows/tests/verify_v11814_emoji_size.py。

运行：python tests/verify_v11814.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
AND = os.path.join(ROOT, "app", "src", "main", "java", "com", "flashdrop", "app")
WIN = os.path.join(os.path.dirname(ROOT), "windows")

MA = open(os.path.join(AND, "MainActivity.java"), encoding="utf-8").read()
EP = open(os.path.join(AND, "EmojiPicker.java"), encoding="utf-8").read()
EMOJI_PY = open(os.path.join(WIN, "app", "ui", "emoji.py"), encoding="utf-8").read()

P, F = [], []


def check(name, cond, detail=""):
    (P if cond else F).append(name)
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", name,
                          ("   " + detail) if (detail and not cond) else ""))


def sec(t):
    print("\n" + "=" * 68)
    print(t)
    print("=" * 68)


# ==================================================================
sec("① 电脑端表情放大：修「全局 QSS padding 压小图标」的根因（用户第 2 条）")
# theme.py 全局 `QToolButton { padding: 4px 14px; }` 会把 44px 格子内容区
# 压到 14px → QIcon 被缩到 14px。这是 v1.18.10/12/13 三次"放大"都没生效的原因。
check("★ 表情格子带 objectName = EmojiCell",
      'self.setObjectName("EmojiCell")' in EMOJI_PY)
check("★ 格子自身样式表把 padding 归零（最高优先级，压过任何继承规则）",
      re.search(r'setStyleSheet\(\s*"QToolButton\s*\{\s*padding:\s*0px;\s*\}\s*"\s*\)',
                EMOJI_PY) is not None)
check("面板 QSS 里有 QToolButton#EmojiCell 规则（双保险）",
      "QToolButton#EmojiCell {" in EMOJI_PY)
check("QToolButton#EmojiCell 规则内 padding: 0px",
      re.search(r"QToolButton#EmojiCell\s*\{[^}]*padding:\s*0px", EMOJI_PY,
                re.S) is not None)
check("★ 分类按钮也重置 padding（全局 QPushButton 的 6px 14px 会裁掉图标）",
      re.search(r'setStyleSheet\(\s*"QPushButton\s*\{\s*padding:\s*0px;\s*\}\s*"\s*\)',
                EMOJI_PY) is not None)
check("QPushButton#EmojiTabIcon 规则内 padding: 0px",
      # 注意：QSS 是 f-string，源码里大括号是 {{ }}，且规则体里还有 {text}
      # 这类占位符 —— 不能简单用 [^}] 匹配，改用有界窗口。
      re.search(r"QPushButton#EmojiTabIcon\s*\{\{.{0,300}?padding:\s*0px",
                EMOJI_PY, re.S) is not None)
check("ICON_PAD 由 18 收到 16（图标框 28px，可视约 24px ≈ 微信 22~24px）",
      re.search(r"ICON_PAD\s*=\s*16\s*(?:#.*)?$", EMOJI_PY, re.M) is not None)
check("iconSize 仍按 cell - icon_pad 计算",
      "setIconSize(QSize(cell - icon_pad, cell - icon_pad))" in EMOJI_PY)

# ==================================================================
sec("② 安卓面板高度对齐键盘：修「IME 高度多算一个状态栏」（用户第 1 条）")
# v1.18.13 用 getWindowVisibleDisplayFrame 的缺口 − 导航栏，但缺口里
# **同时含状态栏**，于是算出的 imeHeightPx 比真实键盘高约一个状态栏
# （S23U 约 140px），正好是用户看到的"面板比键盘高一行"。
check("★ 新增 imeInsetPx()：直接读官方 IME inset",
      "private int imeInsetPx(android.view.View decor)" in MA)
check("★ 用 WindowInsets.Type.ime()（API 30+ 精确高度）",
      "WindowInsets.Type.ime()" in MA)
check("imeInsetPx 有 SDK_INT < 30 的版本保护",
      "Build.VERSION.SDK_INT < 30" in MA)
check("★ watchImeHeight 优先走 imeInsetPx",
      re.search(r"int exact = imeInsetPx\(decor\);\s*\n\s*if \(exact > 0\)",
                MA) is not None)
check("★ 兜底公式改为 screenH - r.bottom - nav（不再用含状态栏的 gap）",
      re.search(r"int candidate = screenH - r\.bottom - nav;", MA) is not None)
check("新增 navBarPx()：inset 取不到时退回系统资源值",
      "private int navBarPx(android.view.View decor)" in MA
      and "navigation_bar_height" in MA)
check("★ panelHeight 上限由 50% 收到 45%",
      "screenH * 0.45f" in MA and "screenH * 0.50f" not in MA)
check("EmojiPicker.getHeight 上限同步收到 45%",
      "screenH * 0.45f" in EP and "screenH * 0.50f" not in EP)
check("兜底比例仍为屏高 36%（微信键盘 36%~40%）",
      "screenH * 0.36f" in MA and "screenH * 0.36f" in EP)

# ==================================================================
sec("③ 安卓切换动效：整高位移（微信式上推/下拉）（用户第 1 条）")
check("★ 新增 slidePanelIn()：面板整高上推动效",
      "private void slidePanelIn(View host)" in MA)
check("slidePanelIn 位移量 = host.getHeight()（整高，不是 26dp）",
      re.search(r"private void slidePanelIn\(View host\)\s*\{.*?"
                r"host\.setTranslationY\(host\.getHeight\(\)\)", MA, re.S)
      is not None)
check("slidePanelIn 不做 alpha 淡入（纯位移，与键盘同构）",
      re.search(r"private void slidePanelIn\(View host\)\s*\{.*?"
                r"host\.setAlpha\(1f\);", MA, re.S) is not None)
check("slidePanelIn 用 DURATION_ENTER",
      re.search(r"private void slidePanelIn\(View host\)\s*\{.*?"
                r"FdAnim\.DURATION_ENTER", MA, re.S) is not None)
check("★ 收起面板位移量改为 host.getHeight()（真正滑出视野）",
      re.search(r"host\.animate\(\)\.translationY\(host\.getHeight\(\)\)", MA)
      is not None)
check("面板收起不再用 26dp 轻推（host 的位移量走 getHeight）",
      # 注意：MainActivity.hidePanel() 里的 FdUtil.dp(this, 26) 是「＋」面板的
      # 下滑动效，与表情面板无关，是合理保留 —— 这里只断言 host 不再被 26dp 推。
      re.search(r"host\.animate\(\)\.translationY\(FdUtil\.dp", MA) is None)
check("toggleEmojiPanel 展开时调用 slidePanelIn",
      "slidePanelIn(host);" in MA)
check("收起动画结束后仍同步图标状态",
      re.search(r"updateEmojiIcon\(\);\s*//\s*★\s*收起后图标回到「表情」", MA)
      is not None)

# ==================================================================
print()
print("=" * 68)
if F:
    print("失败项：")
    for f in F:
        print("  - %s" % f)
print("v1.18.14 专项验收：通过 %d 项，失败 %d 项" % (len(P), len(F)))
print("=" * 68)
sys.exit(1 if F else 0)
