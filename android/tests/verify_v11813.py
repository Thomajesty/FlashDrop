# -*- coding: utf-8 -*-
"""v1.18.13 专项验收 —— 6 项用户反馈修复的静态审计。

  ① 电脑端表情面板对齐微信（464 宽 / 44 格子 / 6 行 / 底部图标条）
  ② 安卓表情面板切后台与键盘重叠
  ③ 安卓顶部设备选择栏布局（灯贴右 / 名字不被压 / 灯对齐 / X 在后）
  ④ 安卓表情分组「其他」→「全部表情」
  ⑤ 安卓表情面板高度 + 键盘上推下拉 + 消除切换闪动
  ⑥ EXE 首启不在前台

跑法：python tests/verify_v11813.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
WIN = os.path.join(ROOT, "windows")
AND = os.path.join(ROOT, "android")
JAVA = os.path.join(AND, "app", "src", "main", "java", "com", "flashdrop", "app")
AXML = os.path.join(AND, "app", "src", "main", "res", "layout", "activity_main.xml")
MF = os.path.join(AND, "app", "src", "main", "AndroidManifest.xml")

PASS = 0
FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS  %s" % name)
    else:
        FAIL += 1
        FAILS.append(name)
        print("  FAIL  %s  %s" % (name, detail))


def section(t):
    print("\n" + "=" * 66)
    print(t)
    print("=" * 66)


def rd(p):
    try:
        return open(p, encoding="utf-8").read()
    except Exception:
        return ""


def strip_java(s):
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    s = re.sub(r"^\s*//.*$", "", s, flags=re.M)
    return s


def strip_xml(s):
    return re.sub(r"<!--.*?-->", "", s, flags=re.S)


EMOJI_PY = rd(os.path.join(WIN, "app", "ui", "emoji.py"))
MAIN_PY = rd(os.path.join(WIN, "main.py"))
MA = rd(os.path.join(JAVA, "MainActivity.java"))
MA_C = strip_java(MA)
EP = rd(os.path.join(JAVA, "EmojiPicker.java"))
EP_C = strip_java(EP)
AXML_C = strip_xml(rd(AXML))

print("=" * 66)
print("v1.18.13 专项验收 —— 6 项用户反馈修复")
print("=" * 66)

# ==================================================================
section("① 电脑端表情面板对齐微信（用户第 1 条）")
# 微信桌面版实测：464 宽 / 10 列 / 44 pitch / 6 行 / 底部图标条
check("COLS = 10（微信同）",
      re.search(r"^\s{4}COLS\s*=\s*10\s*$", EMOJI_PY, re.M) is not None)
check("CELL = 44（微信 pitch 44）",
      re.search(r"^\s{4}CELL\s*=\s*44\s*$", EMOJI_PY, re.M) is not None)
check("GRID_ROWS = 6（微信可见 6 行）",
      re.search(r"^\s{4}GRID_ROWS\s*=\s*6\s*(?:#.*)?$", EMOJI_PY, re.M) is not None)
check("ICON_PAD = 16 → 图标框 28px（v1.18.14 再放大，原 18/26px）",
      re.search(r"^\s{4}ICON_PAD\s*=\s*16\s*(?:#.*)?$", EMOJI_PY, re.M) is not None,
      "★ v1.18.14 演进：v1.18.13 的 18 只是名义上的图标框 —— 实际渲染被全局 "
      "QToolButton padding 压到 14px，用户仍觉得小。v1.18.14 归零 padding 后 "
      "把框收到 16（28px，可视约 24px ≈ 微信 22~24px）。")
check("SIDE_PAD = 12 → 面板宽 10*44+24 = 464",
      re.search(r"^\s{4}SIDE_PAD\s*=\s*12\s*(?:#.*)?$", EMOJI_PY, re.M) is not None)
check("面板宽度按 464 公式计算",
      "self.COLS * self.CELL + self.SIDE_PAD * 2" in EMOJI_PY)
check("★ 分类栏改为微信式底部图标条（EmojiTabIcon）",
      "EmojiTabIcon" in EMOJI_PY and "QPushButton#EmojiTabIcon" in EMOJI_PY)
check("旧顶部文字页签样式已移除（QPushButton#EmojiTab 不再定义）",
      "QPushButton#EmojiTab {" not in EMOJI_PY)
check("新增 TAB_ICON 图标映射",
      "TAB_ICON" in EMOJI_PY and '"Smileys & Emotion": "😀"' in EMOJI_PY)
check("网格在分类条之上（微信结构：网格在上、分类在下）",
      EMOJI_PY.index("v.addWidget(self._scroll)") <
      EMOJI_PY.index("v.addWidget(self._tabs_scroll)"))
check("新增「最近使用」横条（微信顶部那一行）",
      "_refresh_recent_strip" in EMOJI_PY and "RECENT_STRIP" in EMOJI_PY)
check("新增分组标题 EmojiSection（对齐微信「所有表情」）",
      "EmojiSection" in EMOJI_PY)
check("两区之间有分割线（微信同）",
      "EmojiDivider" in EMOJI_PY)
check("分类按钮为圆形 16dp 圆角（微信圆形图标观感）",
      "border-radius: 16px" in EMOJI_PY)
check("选中态有浅底（sidebar_sel）",
      "EmojiTabIcon:checked" in EMOJI_PY and "sidebar_sel" in EMOJI_PY)
check("_EmojiButton 接受 icon_pad 参数（v1.18.14 默认值 18→16）",
      re.search(r"icon_pad:\s*int\s*=\s*16", EMOJI_PY) is not None)
check("图标尺寸按 cell - icon_pad 计算",
      "QSize(cell - icon_pad, cell - icon_pad)" in EMOJI_PY)
check("★ v1.18.14：格子自身样式表把 padding 归零（修图标被压小的根因）",
      re.search(r'setStyleSheet\(\s*"QToolButton\s*\{\s*padding:\s*0px;\s*\}\s*"',
                EMOJI_PY) is not None)

# ==================================================================
section("② 安卓表情面板切后台与键盘重叠（用户第 2 条）")
check("★ onPause 内收起表情面板",
      re.search(r"onPause\(\)\s*\{.*?R\.id\.emoji_panel", MA_C, re.S) is not None)
check("onPause 收起时取消进行中的动画（避免后台残影）",
      "host.animate().cancel()" in MA_C)
check("onPause 收起时复位 translationY / alpha",
      "host.setTranslationY(0f)" in MA_C and "host.setAlpha(1f)" in MA_C)
check("onPause 收起后同步图标状态",
      re.search(r"onPause\(\)\s*\{.*?updateEmojiIcon\(\)", MA_C, re.S) is not None)

# ==================================================================
section("③ 安卓顶部设备选择栏布局（用户第 3 条）")
check("★ 新增状态灯固定槽位常量 DOT_SLOT_DP",
      "DOT_SLOT_DP" in MA)
check("★ 新增 ✕ 固定槽位常量 X_SLOT_DP",
      "X_SLOT_DP" in MA)
check("状态灯放进固定宽度 FrameLayout 槽位（保证收起/展开同 x）",
      re.search(r"FrameLayout dotSlot = new FrameLayout", MA) is not None)
check("灯在槽位内右对齐（贴最右）",
      "android.view.Gravity.RIGHT" in MA and "dotSlot.addView(dot, dlp)" in MA)
check("★ 名字与灯之间留 8dp（用户：灯与名称过近）",
      "tlp.rightMargin = dp(8)" in MA)
check("★ ✕ 槽位在 getView 里就建立（收起/展开骨架一致）",
      "FrameLayout xSlot = new FrameLayout" in MA)
check("✕ 由 getDropDownView 填入槽位（不再插 weight spacer）",
      "xSlot.addView(x" in MA)
check("旧 weight=1f spacer 推 ✕ 的写法已移除",
      "row.addView(spacer" not in MA)
check("✕ 排在状态灯**之后**（槽位顺序：名字→灯→X）",
      MA.index("row.addView(dotSlot)") < MA.index("row.addView(xSlot, xslp)"))
check("旧 stripDeleteButton 已移除（改为槽位清空）",
      "stripDeleteButton" not in MA)
check("★ Spinner 自身内边距清零（灯才能真贴右）",
      "targetSpinner.setPadding(0, 0, 0, 0)" in MA)
check("行左右内边距统一为 14dp",
      "row.setPadding(dp(14), 0, dp(14), 0)" in MA)
check("状态灯尺寸仍为 9dp 圆",
      "new FrameLayout.LayoutParams(\n                    dp(9), dp(9)" in MA or
      "dp(9), dp(9)" in MA)

# ==================================================================
section("④ 安卓表情分组「其他」→「全部表情」（用户第 4 条）")
check("★ GROUP_CN 里 Other 映射为「全部表情」",
      '{"Other", "全部表情"}' in EP)
check("旧的「其他」映射已移除",
      '{"Other", "其他"}' not in EP)
check("页签文案走 cnOf()（改映射即全局生效）",
      "t.setText(cnOf(groupNames.get(i)))" in EP)

# ==================================================================
section("⑤ 安卓表情面板高度 + 键盘互切 + 消除闪动（用户第 5 条）")
check("★ 新增真实 IME 高度记录字段 imeHeightPx",
      "imeHeightPx" in MA)
check("★ 新增 watchImeHeight 监听输入法高度",
      "private void watchImeHeight" in MA)
check("★ 新增 panelHeight()：优先用真实键盘高度",
      "private int panelHeight()" in MA and "imeHeightPx > 0 ? imeHeightPx" in MA)
check("★ 面板高度下限 28% / 上限 45%（v1.18.14 由 50% 收紧）",
      "(screenH * 0.28f)" in MA and "(screenH * 0.45f)" in MA,
      "★ v1.18.14 演进：50% 太松（键盘实测仅占屏高 36%~40%），会把面板放高一整行。")
check("★ 兜底比例由 42% 下调到 36%（微信实测 36%~40%）",
      "(screenH * 0.36f)" in MA and "(screenH * 0.42f)" not in MA)
check("EmojiPicker.getHeight 兜底同步下调到 36%",
      "(screenH * 0.36f)" in EP and "(screenH * 0.42f)" not in EP)
check("EmojiPicker.getHeight 上限同步收到 45%",
      "(screenH * 0.45f)" in EP and "(screenH * 0.50f)" not in EP,
      "★ v1.18.14 演进：原为 50%，随 MainActivity 一起收紧。")
check("★ 新增 hideImeThen()：等 IME 真正收完再展开面板",
      "private void hideImeThen" in MA)
check("隐藏 IME 走轮询等待可见高度恢复",
      "visibleBottom" in MA and "settled" in MA)
check("轮询有超时保护（320ms，不卡死）",
      "> 320" in MA)
check("★ 新增 hideEmojiPanelThen()：支持动画结束回调",
      "private void hideEmojiPanelThen" in MA)
check("切回键盘走「先收面板动画 → 再拉 IME」（避免同帧抢布局）",
      "hideEmojiPanelThen(1, () -> showIme())" in MA)
check("展开面板改为上推进入（v1.18.14：整高 slidePanelIn）",
      "slidePanelIn(host)" in MA,
      "★ v1.18.14 演进：v1.18.13 用 FdAnim.slideInFromBottom(host)（只挪 26dp + 淡入，\n"
      "     观感是轻轻推一下，不像键盘）；v1.18.14 改为位移=面板整高的 slidePanelIn。")
check("收起面板改为纯位移、且位移量为整高",
      "host.animate().translationY(host.getHeight())\n"
      "                    .setDuration" in MA
      and ".alpha(0f)" not in MA.split("hideEmojiPanelThen")[1][:1200],
      "★ v1.18.14 演进：位移量由 26dp 改为 host.getHeight()（真正滑出视野）。")
check("启动时注册 IME 高度监听",
      "watchImeHeight(" in MA and "findViewById(R.id.root)" in MA)

# ==================================================================
section("⑥ EXE 首启不在前台（用户第 6 条）")
check("★ main.py 启动后主动抢前台",
      "_bring_front" in MAIN_PY)
check("用 QTimer.singleShot(0) 在首帧后抢前台",
      "QTimer.singleShot(0, _bring_front)" in MAIN_PY)
check("250ms 后补抢一次（覆盖引导进程窗口消失时机）",
      "QTimer.singleShot(250, _bring_front)" in MAIN_PY)
check("调用 _force_foreground 兜底（AttachThreadInput 技巧）",
      "from app.ui.main_window import _force_foreground" in MAIN_PY)
check("抢前台包含 showNormal + raise_ + activateWindow",
      "win.showNormal()" in MAIN_PY and "win.raise_()" in MAIN_PY
      and "win.activateWindow()" in MAIN_PY)
check("抢前台整段 try 包裹（失败不影响启动）",
      "except Exception:" in MAIN_PY.split("_bring_front")[1][:600])

# ==================================================================
print("\n" + "=" * 66)
print("v1.18.13 专项验收：通过 %d 项，失败 %d 项" % (PASS, FAIL))
if FAILS:
    print("失败项：")
    for f in FAILS:
        print("  - " + f)
print("=" * 66)
sys.exit(0 if FAIL == 0 else 1)
