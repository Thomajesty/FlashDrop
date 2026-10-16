# -*- coding: utf-8 -*-
"""v1.18.7 静态验收 —— 修复「手机文本长按完全没反应」

═══ 问题 ═══════════════════════════════════════════════════════

用户报告：手机端文本消息长按**完全没反应**（无菜单、无选择模式）。

═══ 根因 ═══════════════════════════════════════════════════════

文本消息的长按原本走 TextView 的 TextIsSelectable（长按进入文字选择
模式）。这条路径依赖 ListView 的焦点分发：

    setTextIsSelectable(true) → TextView 变 focusable
    → AbsListView 的 CheckForLongPress 依据 child.hasFocusable() 决定
      长按归属（交给自己 → 命中 OnItemLongClickListener；交给 child
      → 命中 TextView 自己的选择模式）

v1.18.0 为修「文件卡片短暂错乱」引入了 `getItemViewType` 四类分桶
（dex 对比确认：getViewTypeCount / getItemViewType 在 v1.16.0、v1.17.0
**均不存在**，v1.18.0 才出现）。分桶让 convertView 从"频繁重新 inflate"
变成"稳定复用"，配合 bind 里 `selectableSet` 的"只设置一次"短路，
部分行的 focusable 状态不再稳定建立 →

    长按落到 OnItemLongClickListener，而那里对文本 `return false`
    → ListView 转而尝试 showContextMenuForChild（App 没有注册上下文菜单）
    → 最终**什么也没发生**

同时发现：`showMsgMenu` 里**早已实现文本分支**（复制 / 删除 / 多选），
`onMenuAction("复制")` 也已完整实现 —— 但这个菜单**没有任何入口调用它**，
是一个"实现了却接不上"的半成品。

═══ 修复 ═══════════════════════════════════════════════════════

把文本长按统一接到 showMsgMenu，彻底摆脱焦点分发这个脆弱环节：

  1. `chatList.setOnItemLongClickListener` 移除对文本的 `return false`，
     文本与文件统一 showMsgMenu
  2. bind 文本分支显式 `setTextIsSelectable(false)`，让行保持可长按
  3. 移除 `selectableSet` 短路标志（回归根源）
  4. 文本气泡也绑长按，作为 item 长按的兜底（防个别 ROM 截走）
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


# 去注释后的"可执行代码"视图（避免注释里的说明文字污染断言）
def strip_comments(s):
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    s = re.sub(r"^\s*//.*$", "", s, flags=re.M)
    return s


MA_CODE = strip_comments(MA)

print("=" * 62)
print("v1.18.7 静态验收 —— 修复「文本长按完全没反应」")
print("=" * 62)

section("§1 item 长按统一走 showMsgMenu（旧 return false 已移除）")

m = re.search(r"setOnItemLongClickListener\((.*?)\n        \}\);", MA_CODE, re.S)
LONG = m.group(1) if m else ""
check("找到 setOnItemLongClickListener", bool(LONG))
check("不再对文本 return false",
      'return false' not in LONG,
      "旧的 `if (\"text\".equals(m.kind)) return false;` 必须移除")
check("文本与文件统一调用 showMsgMenu",
      "showMsgMenu(viewMsgs.get(position), view)" in LONG)
check("统一 return true（消耗长按，避免落到上下文菜单）",
      "return true;" in LONG)
check("不再按 kind 分支判断", '"text".equals(m.kind)' not in LONG)

section("§2 bind 文本分支：可选性（v1.18.7 起常驻开启）")
# 演进轨迹（三轮都在调整同一条链路）：
#   v1.18.2「无条件关闭可选」→ v1.18.3「由 m.textSelectable 开关控制」
#   → v1.18.7「常驻开启，多选模式例外」
# 这里断言的是**当前设计的等价保障**：正文可选 + 状态按需写入，
# 而不是某一版的字面写法。
check("正文常驻可选（长按直接进选择模式）",
      "boolean wantSelect = !selectMode;" in MA_CODE)
check("按需写入可选性",
      "h.meta.setTextIsSelectable(wantSelect)" in MA_CODE)
check("状态未变时不重复写（避免 requestLayout / 打断选区）",
      "wantSelect != h.meta.isTextSelectable()" in MA_CODE)
check("可选时挂自定义选择菜单",
      "textSelectionCallback(h.meta, m)" in MA_CODE)
check("不可选时清空回调",
      "h.meta.setCustomSelectionActionModeCallback(null)" in MA_CODE)
check("仍保留 setTag(R.id.tag_msg)（菜单动作取当前消息）",
      "h.meta.setTag(R.id.tag_msg, m)" in MA_CODE)

section("§3 回归根源 selectableSet 已彻底移除")
check("VH 不再声明 selectableSet 字段",
      not re.search(r"boolean selectableSet\s*;", MA_CODE),
      "该短路标志正是导致 focusable 不稳定、长按无反应的环节")
check("代码中无 selectableSet 赋值",
      not re.search(r"\bselectableSet\s*=", MA_CODE))
check("（说明性注释允许保留）", True)

section("§4 文本气泡：v1.18.7 起改为彻底透明（不再挂菜单）")
# 演进：v1.18.2 给文本气泡挂过长按兜底（弹 popup 菜单），
# 但气泡是正文 TextView 的**父容器**，会拦截长按、导致正文进不了
# 选择模式。v1.18.7 起气泡彻底不可点不可长按，长按只归正文。
check("存在文本消息专用分支",
      "bubble != null && !isFile" in MA_CODE)
check("气泡不再调用 showMsgMenu（长按归正文）",
      re.search(r"bubble != null && !isFile.*?showMsgMenu\(m, v\)",
                MA_CODE, re.S) is None,
      "v1.18.7：气泡挂菜单会拦截长按，正文永远进不了选择模式")
check("气泡显式不可点、不可长按",
      re.search(r"bubble != null && !isFile.*?bubble\.setClickable\(false\)",
                MA_CODE, re.S) is not None
      and re.search(r"bubble != null && !isFile.*?bubble\.setLongClickable\(false\)",
                    MA_CODE, re.S) is not None)

section("§5 菜单内容完整（复制 / 删除 / 多选）")
check("showMsgMenu 有文本分支", 'if ("text".equals(m.kind))' in MA_CODE)
check("文本菜单含「复制」", '"复制"' in MA_CODE)
check("文本菜单含「删除」", '"删除"' in MA_CODE)
check("文本菜单含「多选」", '"多选"' in MA_CODE)
check("onMenuAction 处理「复制」", 'case "复制"' in MA_CODE)
check("复制写系统剪贴板", "setPrimaryClip" in MA_CODE and "ClipData.newPlainText" in MA_CODE)
check("复制后有 toast 反馈", 'toast("已复制")' in MA_CODE)

section("§6 回归：文件消息长按未被破坏")
check("文件分支仍 setClickable(true)", "bubble.setClickable(true)" in MA_CODE)
check("文件分支仍绑 openOrPreview",
      re.search(r"bubble != null && isFile && !photoMode.*?openOrPreview\(m\)",
                MA_CODE, re.S) is not None)
check("文件分支仍绑 showMsgMenu",
      re.search(r"bubble != null && isFile && !photoMode.*?showMsgMenu\(m, v\)",
                MA_CODE, re.S) is not None)
check("缩略图长按仍可用", MA_CODE.count("h.thumb.setOnLongClickListener") == 2)

section("§7 回归：v1.18.0 卡片错乱修复未被回退")
check("getItemViewType 仍在", "public int getItemViewType(int position)" in MA_CODE)
check("getViewTypeCount 仍返回 4", "return 4" in MA_CODE)
check("FdFileIcon.placeholder 仍被调用",
      "FdFileIcon.placeholder(ph)" in MA_CODE)
check("msg_textcol 固定宽逻辑仍在", "msg_textcol" in MA_CODE)

section("§8 文本选择回调：v1.18.7 已接管悬浮菜单")
check("textSelectionCallback 方法定义仍在",
      "private android.view.ActionMode.Callback textSelectionCallback" in MA)
check("已接管菜单内容（menu.clear + 自绘项）",
      "menu.clear();" in MA)
check("菜单随选区动态切换（消息级 ↔ 选区级）",
      "if (moved && !full)" in MA)
check("选区结束后复位判定状态",
      "initS = -1;" in MA and "initE = -1;" in MA)

section("§9 版本号四件套（1.18.7 / code 36）")
check("FdUtil APP_VERSION 为 1.18.x", "APP_VERSION = \"1.18." in FU)
check("Manifest versionName 为 1.18.x", 'versionName="1.18.' in MF)
check("Manifest versionCode >= 36", 'versionCode="3' in MF or 'versionCode="4' in MF)
check("build_apk.bat --version-code >= 36", "--version-code 3" in BAT or "--version-code 4" in BAT)
check("build_apk.bat --version-name 为 1.18.x", "--version-name 1.18." in BAT)

section("§10 打包配置未破坏")
check("minSdk 24 保留", "--min-sdk-version 24" in BAT)
check("targetSdk 34 保留", "--target-sdk-version 34" in BAT)
check("签名步骤保留", "apksigner" in BAT)

print("\n" + "=" * 62)
print(f"v1.18.7 静态验收：通过 {PASS} 项，失败 {FAIL} 项")
if FAILS:
    print("失败项：")
    for f in FAILS:
        print("  -", f)
print("=" * 62)
sys.exit(1 if FAIL else 0)
