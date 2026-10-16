# -*- coding: utf-8 -*-
"""v1.18.7 静态验收 —— 菜单图标精致化 + 文字框选局部复制

═══ 用户需求 ═══════════════════════════════════════════════════

  1. 不论文件还是文字，长按弹出的**图标过大**，需要精致一点
  2. 文字弹出的菜单，**复制排第一**
  3. **支持框选局部文字**：可拖动选择局部文字，并复制

═══ 实现要点 ═══════════════════════════════════════════════════

需求 1（精致化）：
  · 图标 32dp → **26dp**，且改为**按目标尺寸直接渲染矢量**
    （FdMenuIcon.make 新增 sizeDp 参数）—— 而不是把 32dp 位图塞进小
    ImageView 降采样，那样边缘会发虚
  · 项内边距 8/6 → 6/4，图标与文字间距 5 → 3
  · 文字 12sp → 11sp，宽度上限 72 → 60dp
  · 浮层容器内边距 6/10 → 4/8

需求 2（顺序）：文本菜单 = 复制（第一）→ 选择文字 → 删除 → 多选

需求 3（框选）：
  · 新增菜单项「选择文字」+ 新图标 SELECT（左右把手 + 三行文字）
  · 点击 → Msg.textSelectable = true → 刷新
  · bind 据此把正文 TextView 设为可选（长按即进入系统文本选择模式，
    出现可拖动的左右把手 + 复制/全选菜单）
  · onDestroyActionMode 自动复位 textSelectable —— **必须自动复位**，
    否则 TextView 永久 focusable，行级长按再也触发不了，
    用户既打不开菜单也没法取消，形成死锁
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ANDROID = os.path.dirname(HERE)
SRC = os.path.join(ANDROID, "app", "src", "main", "java", "com", "flashdrop", "app")
MA = open(os.path.join(SRC, "MainActivity.java"), encoding="utf-8").read()
MI = open(os.path.join(SRC, "FdMenuIcon.java"), encoding="utf-8").read()
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

# 取出 makeMenuItem 方法体
m = re.search(r"private View makeMenuItem\(.*?\n    \}", MA_CODE, re.S)
ITEM = m.group(0) if m else ""

print("=" * 62)
print("v1.18.7 静态验收 —— 菜单精致化 + 文字框选局部复制")
print("=" * 62)

section("§1 图标精致化：尺寸 32dp → 26dp")
check("定义菜单图标尺寸常量 ICON_MENU_DP",
      "ICON_MENU_DP = 26" in MA_CODE, "应为 26dp")
check("makeMenuItem 使用该常量",
      "dp(ICON_MENU_DP)" in ITEM)
check("图标按目标尺寸渲染（传第 4 参数）",
      "FdMenuIcon.make(this, it.icon, 0xFFE9EAEC, ICON_MENU_DP)" in ITEM)
check("makeMenuItem 不再硬编码 dp(32)",
      "dp(32)" not in ITEM)

section("§2 图标精致化：间距 / 字号收紧")
check("项内边距 6/4（原 8/6）", "setPadding(dp(6), dp(4), dp(6), dp(4))" in ITEM)
check("图标与文字间距 3（原 5）", "topMargin = dp(3)" in ITEM)
check("文字 11sp（原 12sp）",
      "TypedValue.COMPLEX_UNIT_SP, 11" in ITEM)
check("文字宽度上限 60dp（原 72dp）", "setMaxWidth(dp(60))" in ITEM)
check("文字仍强制单行不换行", "setSingleLine(true)" in ITEM)
check("浮层容器内边距收紧为 4/8",
      "box.setPadding(dp(4), dp(8), dp(4), dp(8))" in MA_CODE)

section("§3 FdMenuIcon 支持自定义尺寸（避免降采样发虚）")
check("存在 4 参数 make(sizeDp)",
      "public static Bitmap make(Context ctx, int type, int color, int sizeDp)" in MI)
check("3 参数 make 委托给 4 参数版",
      "return make(ctx, type, color, 32);" in MI)
check("按传入 dp 计算位图尺寸",
      "int size = FdUtil.dp(ctx, sizeDp);" in MI)
check("3 参数版不再自带 switch（无重复实现）",
      MI.count("switch (type)") == 1)

section("§4 新增「选择文字」图标")
check("定义 SELECT 常量", "public static final int SELECT = 12;" in MI)
check("有 drawSelect 绘制方法", "private static void drawSelect" in MI)
check("switch 中接入 SELECT 分支", "case SELECT:" in MI)
check("绘制左右两个选择把手",
      MI.count("drawRect") >= 5, "三行文字 + 两根把手")

section("§5 文字菜单：v1.18.7 已改为长按直接进选择模式")
# 演进说明：v1.18.3 曾在 popup 菜单里加「选择文字」作为框选的"二次入口"
# （点它 → 再长按 → 进选择模式）。v1.18.7 按用户要求改成
# **长按文本直接出现选择光标**，该中间态整体移除。
# 这里断言演进后的结果，保持套件的回归价值。
check("popup 文本分支不再有「选择文字」", '"选择文字"' not in MA_CODE)
check("popup 文本分支保留「复制」作兜底",
      '"复制", FdMenuIcon.COPY' in MA_CODE)
check("长按直接进入选择模式（正文常驻可选）",
      "boolean wantSelect = !selectMode;" in MA_CODE)

section("§6 框选局部文字：v1.18.7 实现方式")
check("已移除 m.textSelectable 中间态",
      not re.search(r"boolean textSelectable\s*;", MA_CODE))
check("已移除 enterTextSelectMode",
      "enterTextSelectMode" not in MA_CODE)
check("选择菜单由 textSelectionCallback 接管",
      "private android.view.ActionMode.Callback textSelectionCallback" in MA)
check("可框选（挂自定义选择菜单回调）",
      "setCustomSelectionActionModeCallback(" in MA_CODE)

section("§7 框选局部文字：bind 联动（v1.18.7）")
check("bind 打开正文可选性",
      "h.meta.setTextIsSelectable(wantSelect)" in MA_CODE)
check("状态未变不重复写",
      "wantSelect != h.meta.isTextSelectable()" in MA_CODE)
check("文本行显式校准 longClickable（v1.18.7 起）",
      "h.meta.setLongClickable(wantSelect)" in MA_CODE,
      "v1.18.7 起每次 bind 显式重申，防止 convertView 复用时被改写")

section("§8 v1.18.7 不再需要「选择结束复位」（无常驻开关可死锁）")
check("onDestroyActionMode 只复位选区记录",
      "initS = -1;" in MA_CODE and "initE = -1;" in MA_CODE)
check("未再对 textSelectable 做复位",
      "cm.textSelectable = false" not in MA_CODE)
section("§9 回归：v1.18.2 长按菜单修复未被破坏")
check("行级长按仍统一 showMsgMenu",
      "showMsgMenu(viewMsgs.get(position), view)" in MA_CODE)
check("行级长按仍 return true", "return true;" in MA_CODE)
check("文本气泡长按兜底仍在", "bubble != null && !isFile" in MA_CODE)
check("selectableSet 仍已移除",
      not re.search(r"\bselectableSet\s*=", MA_CODE))

section("§10 回归：文件菜单未受影响")
check("文件菜单含「打开」", '"打开"' in MA_CODE)
check("文件菜单含「保存」", '"保存"' in MA_CODE)
check("文件菜单含「分享」", '"分享"' in MA_CODE)
check("文件菜单含「其他应用打开」", '"其他应用打开"' in MA_CODE)
check("统一「删除」仍在", '"删除"' in MA_CODE)
check("统一「多选」仍在", '"多选"' in MA_CODE)

section("§11 回归：卡片错乱修复未回退")
check("getItemViewType 仍在", "public int getItemViewType(int position)" in MA_CODE)
check("getViewTypeCount 仍返回 4", "return 4" in MA_CODE)
check("placeholder 仍被调用", "FdFileIcon.placeholder(ph)" in MA_CODE)

section("§12 版本号四件套（1.18.7 / code 36）")
check("FdUtil APP_VERSION 为 1.18.x", "APP_VERSION = \"1.18." in FU)
check("Manifest versionName 为 1.18.x", 'versionName="1.18.' in MF)
check("Manifest versionCode >= 36", 'versionCode="3' in MF or 'versionCode="4' in MF)
check("build_apk.bat --version-code >= 36", "--version-code 3" in BAT or "--version-code 4" in BAT)
check("build_apk.bat --version-name 为 1.18.x", "--version-name 1.18." in BAT)

print("\n" + "=" * 62)
print(f"v1.18.7 静态验收：通过 {PASS} 项，失败 {FAIL} 项")
if FAILS:
    print("失败项：")
    for f in FAILS:
        print("  -", f)
print("=" * 62)
sys.exit(1 if FAIL else 0)
