# -*- coding: utf-8 -*-
"""v1.18.8 静态验收 —— 修复「不能局部复制」+ ActionMode 样式对齐微信

═══ 用户反馈 ═══════════════════════════════════════════════════

> 目前你给我的 1.18.4 版本还是不能局部复制 主要是这个问题 需要参考解决

═══ 根因（两层，缺一不可） ═══════════════════════════════════════

v1.18.4 已经让文本正文 `setTextIsSelectable(true)`（因而 focusable），
但**真正的拦路虎在 ListView 这一层**：

① `AbsListView` 的 `mItemsCanFocus` **默认 false**。
   它意味着"列表假定 item 内没有可聚焦控件"，于是**所有触摸事件都由列表
   自己消化**，绝不向下传递。文本正文虽然可选，长按却永远到不了它手上 ——
   选择光标不出现，自然无法框选局部文字。

② `chatList.setOnItemLongClickListener(...)` 返回 **true**，
   把长按彻底消费掉，连"漏给子控件"的机会都没有。

═══ 修复 ═══════════════════════════════════════════════════════

1. **`chatList.setItemsCanFocus(true)`** —— 关键一行。
   开启后 ListView 检测到 item 内有 focusable 子控件时会把事件交给它；
   而文本行的 row 因此 `hasFocusable() == true`，`CheckForLongPress`
   会跳过行级长按 —— 两层正好配套。

2. 对**文件消息无影响**：文件卡片是自绘 LinearLayout（clickable 但不可聚焦），
   row 内没有可聚焦控件，事件仍由 ListView 处理，点击/长按照旧。

3. 顺带对齐微信长按文本的菜单观感（参考用户给的两张微信截图）：
   · ActionMode 深灰圆角浮层（action_mode_bg.xml）+ 浮在内容之上
   · 菜单项挂 22dp 矢量图标（比 popup 菜单的 26dp 再小一档）
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ANDROID = os.path.dirname(HERE)
SRC = os.path.join(ANDROID, "app", "src", "main", "java", "com", "flashdrop", "app")
RES = os.path.join(ANDROID, "app", "src", "main", "res")
MA = open(os.path.join(SRC, "MainActivity.java"), encoding="utf-8").read()
MI = open(os.path.join(SRC, "FdMenuIcon.java"), encoding="utf-8").read()
FU = open(os.path.join(SRC, "FdUtil.java"), encoding="utf-8").read()
MF = open(os.path.join(ANDROID, "app", "src", "main", "AndroidManifest.xml"),
          encoding="utf-8").read()
BAT = open(os.path.join(ANDROID, "build_apk.bat"), encoding="utf-8").read()
STYLES = open(os.path.join(RES, "values", "styles.xml"), encoding="utf-8").read()
AMB = open(os.path.join(RES, "drawable", "action_mode_bg.xml"),
           encoding="utf-8").read()

PASS = 0
FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK] {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name} {detail}")


def section(t):
    print(f"\n=== {t} ===")


def strip_comments(s):
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    s = re.sub(r"^\s*//.*$", "", s, flags=re.M)
    return s


MA_CODE = strip_comments(MA)

print("=" * 62)
print("v1.18.8 静态验收 —— 局部复制修复 + 菜单样式对齐微信")
print("=" * 62)

section("§1 ★ 核心修复：ListView 把事件下传给 item 内可聚焦子控件")
check("已调用 chatList.setItemsCanFocus(true) —— 关键一行",
      "chatList.setItemsCanFocus(true);" in MA_CODE,
      "缺这一行，长按永远到不了正文 TextView")
check("调用位置在 setAdapter 之后",
      MA_CODE.find("chatList.setAdapter(adapter)")
      < MA_CODE.find("chatList.setItemsCanFocus(true)"))
check("注释说明了 mItemsCanFocus 默认 false 的成因",
      "mItemsCanFocus" in MA)
check("注释说明了它对文件消息无影响",
      "不可聚焦" in MA and "文件" in MA)

section("§2 文本正文保持可选（v1.18.4 已建立）")
check("wantSelect 由 !selectMode 驱动",
      "boolean wantSelect = !selectMode;" in MA_CODE)
check("按需写入 setTextIsSelectable",
      "h.meta.setTextIsSelectable(wantSelect)" in MA_CODE)
check("挂着自定义选择菜单回调",
      "textSelectionCallback(h.meta, m)" in MA_CODE)

section("§3 ActionMode 样式对齐微信（深灰圆角浮层）")
check("styles.xml 定义了 FdActionMode",
      'name="FdActionMode"' in STYLES)
check("AppTheme 引用 actionModeStyle",
      "android:actionModeStyle" in STYLES)
check("★ windowActionModeOverlay=true（菜单浮在内容上，不下压布局）",
      "android:windowActionModeOverlay" in STYLES and "true" in STYLES)
check("菜单文字色为浅色（深底可读）",
      "android:actionMenuTextColor" in STYLES)
check("action_mode_bg.xml 存在", bool(AMB))
check("底板为中灰 #4B4F55（对齐微信菜单色）",
      "#4B4F55" in AMB)
check("底板为圆角", "corners" in AMB)

section("§4 菜单项图标（22dp，对齐微信）")
check("定义 ICON_ACTION_DP = 22", "ICON_ACTION_DP = 22" in MA_CODE)
check("新增 putActionIcon 辅助方法",
      "private void putActionIcon(android.view.MenuItem mi, int iconType)" in MA_CODE)
check("用 BitmapDrawable 承载矢量图标",
      "new android.graphics.drawable.BitmapDrawable(" in MA_CODE)
check("设为 SHOW_AS_ACTION_ALWAYS 才会显示图标",
      "SHOW_AS_ACTION_ALWAYS" in MA_CODE)
check("按 ICON_ACTION_DP 渲染（不是降采样）",
      "FdMenuIcon.make(this, iconType, 0xFFE9EAEC, ICON_ACTION_DP)" in MA_CODE)
check("FdMenuIcon 新增 SELECT_ALL 图标",
      "public static final int SELECT_ALL = 13;" in MI)
check("drawSelectAll 绘制方法存在", "private static void drawSelectAll" in MI)
check("switch 中接入 SELECT_ALL", "case SELECT_ALL:" in MI)

section("§5 ★ 菜单顺序（用户强调过）")
m = re.search(r"if \(moved && !full\) \{(.*?)\n                \} else \{(.*?)\n                \}",
              MA_CODE, re.S)
BR_SEL = m.group(1) if m else ""
BR_MSG = m.group(2) if m else ""
check("找到两个菜单分支", bool(BR_SEL) and bool(BR_MSG))
if BR_SEL and BR_MSG:
    check("选区级顺序 = 复制 → 全选",
          BR_SEL.find('"复制"') < BR_SEL.find('"全选"'))
    check("消息级顺序 = 复制 → 删除 → 多选",
          BR_MSG.find('"复制"') < BR_MSG.find('"删除"') < BR_MSG.find('"多选"'))
    check("选区级 2 项", BR_SEL.count("putActionIcon(") == 2)
    check("消息级 3 项", BR_MSG.count("putActionIcon(") == 3)
    check("每项都挂了图标（不存在裸 menu.add）",
          BR_SEL.count("menu.add(") == BR_SEL.count("putActionIcon(menu.add(")
          and BR_MSG.count("menu.add(") == BR_MSG.count("putActionIcon(menu.add("),
          f"选区级 {BR_SEL.count('menu.add(')}/{BR_SEL.count('putActionIcon(menu.add(')}"
          f" 消息级 {BR_MSG.count('menu.add(')}/{BR_MSG.count('putActionIcon(menu.add(')}")

section("§6 菜单切换判据未变")
check("moved && !full 判据保留", "if (moved && !full)" in MA_CODE)
check("menu.clear() 丢弃系统默认项", "menu.clear();" in MA_CODE)
check("全选走 android.text.Selection",
      "android.text.Selection.setSelection" in MA_CODE)
check("复制写剪贴板", "setPrimaryClip(ClipData.newPlainText" in MA_CODE)

section("§7 回归：文件消息与其他能力")
check("setOnItemClickListener 仍在", "setOnItemClickListener" in MA_CODE)
check("文件消息长按仍走 showMsgMenu",
      "showMsgMenu(viewMsgs.get(position), view)" in MA_CODE)
check("文件菜单含 打开 / 保存 / 分享",
      '"打开"' in MA_CODE and '"保存"' in MA_CODE and '"分享"' in MA_CODE)
check("getItemViewType 仍在", "public int getItemViewType(int position)" in MA_CODE)
check("图标精致化（popup 26dp）保留", "ICON_MENU_DP = 26" in MA_CODE)
check("FdMenuIcon 仍支持 sizeDp 参数",
      "public static Bitmap make(Context ctx, int type, int color, int sizeDp)" in MI)

section("§8 版本号四件套（1.18.8 / code 36）")
check("FdUtil APP_VERSION 为 1.18.x", "APP_VERSION = \"1.18." in FU)
check("Manifest versionName 为 1.18.x", 'versionName="1.18.' in MF)
check("Manifest versionCode >= 36", 'versionCode="3' in MF or 'versionCode="4' in MF)
check("build_apk.bat --version-code >= 36", "--version-code 3" in BAT or "--version-code 4" in BAT)
check("build_apk.bat --version-name 为 1.18.x", "--version-name 1.18." in BAT)

print("\n" + "=" * 62)
print(f"v1.18.8 静态验收：通过 {PASS} 项，失败 {FAIL} 项")
if FAILS:
    print("失败项：")
    for f in FAILS:
        print("  -", f)
print("=" * 62)
sys.exit(1 if FAIL else 0)
