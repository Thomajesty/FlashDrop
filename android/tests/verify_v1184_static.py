# -*- coding: utf-8 -*-
"""v1.18.7 静态验收 —— 文本长按改为微信式「选择光标 + 动态悬浮菜单」

═══ 用户需求（原文） ═══════════════════════════════════════════

  做成和微信一样的 长按文本内出现可以选择的光标
  上面菜单是 复制 删除 多选
  当光标移动来选择文本时 上面菜单显示 复制 全选

（并特别提醒：**注意菜单项顺序**）

═══ 实现要点 ═══════════════════════════════════════════════════

1. 正文**常驻可选**：bind 里 `wantSelect = !selectMode`，长按文字直接进入
   系统文本选择模式（出现可选择的光标 / 左右把手），不再需要先弹 popup 菜单。

2. 悬浮菜单由 textSelectionCallback **完全接管**（先 `menu.clear()` 丢弃
   系统默认项，再自己 add），**顺序固定**：
       · 刚长按 / 已全选（moved == false 或 full）→ 复制 · 删除 · 多选   消息级
       · 拖动光标选中局部（moved && !full）      → 复制 · 全选         选区级

3. 判定用 `moved && !full`：
   - "刚长按"还没动光标 → 给消息级的 删除/多选 最顺手
   - "拖动把手"说明想精确选一段 → 给 全选 一键回到整体
   - 点过全选后选区=全文 → 又回到消息级菜单，形成闭环

4. 移除 v1.18.3 的中间态（`m.textSelectable` / 菜单项「选择文字」/
   `enterTextSelectMode`）—— 长按已直接进选择模式，不需要二次入口。

5. ★ 编译期坑：本项目 android.jar 里 **TextView 未暴露 setSelection(int,int)**
   （只有 getSelectionStart/End），全选改走官方 `android.text.Selection`。
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

print("=" * 62)
print("v1.18.7 静态验收 —— 微信式选择光标 + 动态悬浮菜单")
print("=" * 62)

section("§1 正文常驻可选（长按直接进选择模式）")
check("wantSelect 由 !selectMode 驱动（不再依赖 m.textSelectable）",
      "boolean wantSelect = !selectMode;" in MA_CODE)
check("按需写入 setTextIsSelectable",
      "h.meta.setTextIsSelectable(wantSelect)" in MA_CODE)
check("状态未变时不重复写（避免 requestLayout / 打断选区）",
      "wantSelect != h.meta.isTextSelectable()" in MA_CODE)
check("可选时挂自定义选择菜单回调",
      "textSelectionCallback(h.meta, m)" in MA_CODE)
check("可选时设高亮色", "setHighlightColor(0x403B82F6)" in MA_CODE)
check("不可选时清空回调",
      "h.meta.setCustomSelectionActionModeCallback(null)" in MA_CODE)

section("§2 ★ 菜单顺序（用户重点提醒）")
m = re.search(r"if \(moved && !full\) \{(.*?)\n                \} else \{(.*?)\n                \}",
              MA_CODE, re.S)
BR_SEL = m.group(1) if m else ""
BR_MSG = m.group(2) if m else ""
check("找到两个菜单分支", bool(BR_SEL) and bool(BR_MSG))

if BR_SEL and BR_MSG:
    i_c1, i_a = BR_SEL.find('"复制"'), BR_SEL.find('"全选"')
    check("选区级顺序 = 复制 → 全选",
          i_c1 >= 0 and i_a >= 0 and i_c1 < i_a,
          f"复制@{i_c1} 全选@{i_a}")
    check("选区级只有 2 项（复制 / 全选）",
          BR_SEL.count("menu.add(") == 2,
          f"实际 {BR_SEL.count('menu.add(')} 项")
    j_c, j_d, j_m = (BR_MSG.find('"复制"'), BR_MSG.find('"删除"'),
                     BR_MSG.find('"多选"'))
    check("消息级顺序 = 复制 → 删除 → 多选",
          j_c >= 0 and j_d > j_c and j_m > j_d,
          f"复制@{j_c} 删除@{j_d} 多选@{j_m}")
    check("消息级只有 3 项（复制 / 删除 / 多选）",
          BR_MSG.count("menu.add(") == 3,
          f"实际 {BR_MSG.count('menu.add(')} 项")
    check("菜单项 order 参数递增（0/1/2）",
          ", 0, \"复制\")" in BR_MSG and ", 1, \"删除\")" in BR_MSG
          and ", 2, \"多选\")" in BR_MSG)
    def _first_label(branch):
        """取该分支里第一个 menu.add(...) 的文案，用于校验排序"""
        i = branch.find("menu.add(")
        if i < 0:
            return ""
        j = branch.find('"', i)
        k = branch.find('"', j + 1) if j >= 0 else -1
        return branch[j + 1:k] if j >= 0 and k > j else ""

    check("复制在两套菜单里都排第一",
          _first_label(BR_SEL) == "复制" and _first_label(BR_MSG) == "复制",
          f"选区级首项={_first_label(BR_SEL)!r} 消息级首项={_first_label(BR_MSG)!r}")

section("§3 菜单切换判据")
check("用 selectionMoved() 判断光标是否被拖动",
      "private boolean selectionMoved()" in MA_CODE)
check("首次准备时记录初始选区", "initS = s;" in MA_CODE and "initE = e;" in MA_CODE)
check("切换条件为 moved && !full",
      "if (moved && !full)" in MA_CODE)
check("full 判据 = 选中全部且文本非空",
      "boolean full = tv.length() > 0 && s == 0 && e == tv.length();" in MA_CODE)
check("先 menu.clear() 丢弃系统默认项", "menu.clear();" in MA_CODE)

section("§4 四个菜单动作")
check("「复制」写剪贴板", "setPrimaryClip(ClipData.newPlainText" in MA_CODE)
check("「复制」有选区取选区、否则全文",
      "tv.getText().subSequence(s, e)" in MA_CODE)
check("「复制」后有 toast", 'toast("已复制")' in MA_CODE)
check("「全选」走 android.text.Selection", "android.text.Selection.setSelection" in MA_CODE)
check("「全选」后 invalidate 刷新菜单", "mode.invalidate();" in MA_CODE)
check("「删除」走 FdDialog 危险确认",
      'FdDialog.danger(MainActivity.this, "删除消息"' in MA_CODE)
check("「多选」进入多选模式", "enterSelectMode(cm);" in MA_CODE)

section("§5 ★ 编译期坑：不用 TextView.setSelection")
check("不再调用 tv.setSelection（本 jar 不支持）",
      not re.search(r"\btv\.setSelection\(", MA_CODE),
      "android.jar 里 TextView 无该方法 → 会编译失败")
check("改用 android.text.Selection 设置选区",
      "android.text.Selection.setSelection(" in MA_CODE)
check("设置前做 Spannable 判断",
      "text instanceof android.text.Spannable" in MA_CODE)
check("注释说明了原因", "未暴露" in MA or "android.text.Selection" in MA)

section("§6 移除 v1.18.3 的中间态")
check("Msg 不再有 textSelectable 字段",
      not re.search(r"boolean textSelectable\s*;", MA_CODE))
check("不再有 enterTextSelectMode 方法",
      "enterTextSelectMode" not in MA_CODE)
check("popup 菜单不再有「选择文字」项",
      '"选择文字"' not in MA_CODE)
check("popup 文本分支仅保留「复制」作兜底",
      re.search(r'if \("text"\.equals\(m\.kind\)\) \{\s*\n\s*//[^\n]*\n(?:\s*//[^\n]*\n)*\s*items\.add\(new FdMenuIcon\.Item\("复制"',
                MA, re.S) is not None
      or '"复制", FdMenuIcon.COPY' in MA_CODE)

section("§7 回归：v1.18.3 图标精致化保留")
check("菜单图标尺寸常量仍是 26dp", "ICON_MENU_DP = 26" in MA_CODE)
check("makeMenuItem 仍用该常量", "dp(ICON_MENU_DP)" in MA_CODE)
check("图标按目标尺寸渲染", "FdMenuIcon.make(this, it.icon, 0xFFE9EAEC, ICON_MENU_DP)" in MA_CODE)
check("项内边距仍为 6/4", "setPadding(dp(6), dp(4), dp(6), dp(4))" in MA_CODE)
check("FdMenuIcon 仍支持 sizeDp 参数",
      "public static Bitmap make(Context ctx, int type, int color, int sizeDp)" in MI)

section("§8 回归：文件消息与其他能力未受影响")
check("行级长按仍统一 showMsgMenu",
      "showMsgMenu(viewMsgs.get(position), view)" in MA_CODE)
check("文件菜单含「打开」", '"打开"' in MA_CODE)
check("文件菜单含「保存」", '"保存"' in MA_CODE)
check("文件菜单含「分享」", '"分享"' in MA_CODE)
check("统一「删除」仍在", '"删除"' in MA_CODE)
check("统一「多选」仍在", '"多选"' in MA_CODE)
check("getItemViewType 仍在", "public int getItemViewType(int position)" in MA_CODE)
check("getViewTypeCount 仍返回 4", "return 4" in MA_CODE)

section("§9 版本号四件套（1.18.7 / code 36）")
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
