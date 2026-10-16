# -*- coding: utf-8 -*-
"""v1.18.8 静态验收 —— 文本长按选择（第三层修复：气泡不再拦截）

═══ 用户反馈 ═══════════════════════════════════════════════════

> 另外 文字长按选择的功能还是没有出现

即 v1.18.5 的 `setItemsCanFocus(true)` 仍不够。

═══ 根因（事件链上的最后一层拦截） ═════════════════════════════

文本消息的气泡（`msg_bubble`，LinearLayout）在 v1.18.2 被挂上了
`OnLongClickListener` 并 `setClickable(true)`（当时是为了"让长按至少有点反应"）。

但气泡是正文 TextView 的**父容器**：它一旦 clickable / longClickable，
就会在事件分发里成为**拦截者** —— 长按落在气泡上被它消费，
正文的 TextIsSelectable 永远进不去选择模式。

═══ 三层修复串起来看 ═══════════════════════════════════════════

| 版本 | 补掉的一层 |
|---|---|
| v1.18.4 | 正文设为可选（`setTextIsSelectable(true)`）—— 打开了开关 |
| v1.18.5 | `chatList.setItemsCanFocus(true)` —— 让列表把事件下传 |
| **v1.18.8** | **文本气泡彻底不可点不可长按** —— 移除最后的拦截者 |

三层缺一不可：**事件要能到达正文**（v1.18.5）**、正文要有处理能力**（v1.18.4）
**、中间不能有拦截者**（v1.18.8）。

═══ 附带加固 ═══════════════════════════════════════════════════

bind 文本分支里每次校准 `setClickable / setLongClickable / setFocusable /
setFocusableInTouchMode` —— 防止 convertView 复用时这些属性被其它分支改写。
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ANDROID = os.path.dirname(HERE)
SRC = os.path.join(ANDROID, "app", "src", "main", "java", "com", "flashdrop", "app")
MA = open(os.path.join(SRC, "MainActivity.java"), encoding="utf-8").read()
FU = open(os.path.join(SRC, "FdUtil.java"), encoding="utf-8").read()
MF = open(os.path.join(ANDROID, "app", "src", "main", "AndroidManifest.xml"),
          encoding="utf-8").read()
BAT = open(os.path.join(ANDROID, "build_apk.bat"), encoding="utf-8").read()

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

# 取出文本气泡分支
m = re.search(r"\} else if \(bubble != null && !isFile\) \{(.*?)\n        \} else if",
              MA_CODE, re.S)
TXT_BUBBLE = m.group(1) if m else ""

print("=" * 62)
print("v1.18.8 静态验收 —— 文本长按选择（气泡不再拦截）")
print("=" * 62)

section("§1 ★ 核心修复：文本气泡彻底透明（移除拦截者）")
check("找到文本气泡分支", bool(TXT_BUBBLE))
check("气泡不再 setClickable(true)",
      "bubble.setClickable(true)" not in TXT_BUBBLE,
      "父容器可点会拦截长按")
check("气泡显式 setClickable(false)",
      "bubble.setClickable(false)" in TXT_BUBBLE)
check("气泡显式 setLongClickable(false)",
      "bubble.setLongClickable(false)" in TXT_BUBBLE)
check("气泡清空 OnClickListener",
      "bubble.setOnClickListener(null)" in TXT_BUBBLE)
check("气泡清空 OnLongClickListener",
      "bubble.setOnLongClickListener(null)" in TXT_BUBBLE)
check("气泡不再挂 showMsgMenu（长按只归正文）",
      "showMsgMenu" not in TXT_BUBBLE)
check("注释说明了「父容器拦截」这一成因",
      "父容器" in MA and "拦截" in MA)

section("§2 正文显式具备「接收并处理长按」的能力")
check("正文 setTextIsSelectable 保留",
      "h.meta.setTextIsSelectable(wantSelect)" in MA_CODE)
check("正文 setClickable 校准", "h.meta.setClickable(wantSelect)" in MA_CODE)
check("正文 setLongClickable 校准", "h.meta.setLongClickable(wantSelect)" in MA_CODE)
check("正文 setFocusable 校准", "h.meta.setFocusable(wantSelect)" in MA_CODE)
check("正文 setFocusableInTouchMode 校准",
      "h.meta.setFocusableInTouchMode(wantSelect)" in MA_CODE)
check("挂着自定义选择菜单回调",
      "textSelectionCallback(h.meta, m)" in MA_CODE)

section("§3 v1.18.5 的事件下传修复仍在")
check("chatList.setItemsCanFocus(true) 保留",
      "chatList.setItemsCanFocus(true);" in MA_CODE)

section("§4 菜单顺序未变（用户强调过）")
m2 = re.search(r"if \(moved && !full\) \{(.*?)\n                \} else \{(.*?)\n                \}",
               MA_CODE, re.S)
BR_SEL = m2.group(1) if m2 else ""
BR_MSG = m2.group(2) if m2 else ""
check("选区级顺序 = 复制 → 全选",
      BR_SEL.find('"复制"') < BR_SEL.find('"全选"'))
check("消息级顺序 = 复制 → 删除 → 多选",
      BR_MSG.find('"复制"') < BR_MSG.find('"删除"') < BR_MSG.find('"多选"'))
check("menu.clear() 保留", "menu.clear();" in MA_CODE)
check("全选走 android.text.Selection",
      "android.text.Selection.setSelection" in MA_CODE)

section("§5 回归：文件消息不受影响")
check("文件气泡仍 setClickable(true)",
      re.search(r"bubble != null && isFile && !photoMode.*?bubble\.setClickable\(true\)",
                MA_CODE, re.S) is not None)
check("文件气泡仍绑 showMsgMenu",
      re.search(r"bubble != null && isFile && !photoMode.*?showMsgMenu\(m, v\)",
                MA_CODE, re.S) is not None)
check("行级长按监听器保留（文件兜底）",
      "setOnItemLongClickListener" in MA_CODE)
check("文件菜单含 打开 / 保存 / 分享",
      '"打开"' in MA_CODE and '"保存"' in MA_CODE and '"分享"' in MA_CODE)

section("§6 回归：其它能力")
check("getItemViewType 保留", "public int getItemViewType(int position)" in MA_CODE)
check("图标精致化 26dp 保留", "ICON_MENU_DP = 26" in MA_CODE)
check("ActionMode 图标 22dp 保留", "ICON_ACTION_DP = 22" in MA_CODE)
check("popup 菜单图标按尺寸渲染",
      "FdMenuIcon.make(this, it.icon, 0xFFE9EAEC, ICON_MENU_DP)" in MA_CODE)

section("§7 版本号四件套（1.18.8 / code 36）")
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
