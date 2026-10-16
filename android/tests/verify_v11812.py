# -*- coding: utf-8 -*-
"""v1.18.12 专项验收：用户本轮 3 条需求。

① 点击离线设备闪退（嵌套类 → 顶层类）
② 电脑端表情太小（CELL 36 → 44）
③ 安卓表情按钮位置 + 键盘互切 + 占键盘区 + 常用表情行

运行：python tests/verify_v11812.py
"""
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
AND = ROOT
WIN = os.path.join(os.path.dirname(ROOT), "windows")

JAVA = os.path.join(AND, "app", "src", "main", "java", "com", "flashdrop", "app")
RES = os.path.join(AND, "app", "src", "main", "res")
LAYOUT = os.path.join(RES, "layout")
APK = os.path.join(AND, "dist", "FlashDrop.apk")

P, F = [], []


def rec(cond, name, detail=""):
    (P if cond else F).append(name)
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", name,
                          ("   " + detail) if (detail and not cond) else ""))


def sec(t):
    print("\n=== %s ===" % t)


MA = open(os.path.join(JAVA, "MainActivity.java"), encoding="utf-8").read()
BD = open(os.path.join(JAVA, "BdTextView.java"), encoding="utf-8").read()
TSH = open(os.path.join(JAVA, "TextSelectionHelper.java"), encoding="utf-8").read()
EP = open(os.path.join(JAVA, "EmojiPicker.java"), encoding="utf-8").read()
L_MAIN = open(os.path.join(LAYOUT, "activity_main.xml"), encoding="utf-8").read()
L_IN = open(os.path.join(LAYOUT, "item_text_in.xml"), encoding="utf-8").read()
L_OUT = open(os.path.join(LAYOUT, "item_text_out.xml"), encoding="utf-8").read()

# ═════════════════════════════════════════════════════════════
sec("① 点击离线设备闪退 —— 嵌套类根因修复")
# ═════════════════════════════════════════════════════════════
rec(os.path.exists(os.path.join(JAVA, "BdTextView.java")),
    "BdTextView.java 存在（顶层类）")
rec("public class BdTextView extends TextView" in BD,
    "BdTextView 是**顶层** public class（非嵌套）")
rec("private TextSelectionHelper helper;" in BD,
    "持有 TextSelectionHelper 引用")
rec("void bindHelper(" in BD and "TextSelectionHelper helper()" in BD,
    "提供 bindHelper / helper 存取")
rec("protected void onDraw(Canvas canvas)" in BD and "drawHandles" in BD,
    "onDraw 里调用 drawHandles（自绘手柄）")

def strip_xml_comments(s):
    """去掉 XML 注释，避免把说明文字当成真实代码/标签判定。"""
    return re.sub(r"<!--.*?-->", "", s, flags=re.S)


def strip_java_comments(s):
    """去掉 Java 行注释与块注释。"""
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    s = re.sub(r"//[^\n]*", "", s)
    return s


MA_C = strip_java_comments(MA)
TSH_C = strip_java_comments(TSH)
L_IN_C = strip_xml_comments(L_IN)
L_OUT_C = strip_xml_comments(L_OUT)

# 旧嵌套类必须已移除（用去注释后的源码判定）
rec("BdTextView" not in TSH_C,
    "★ TextSelectionHelper 内**不再**保留嵌套 BdTextView")
rec("TextSelectionHelper.BdTextView" not in MA_C,
    "★ MainActivity 不再引用 TextSelectionHelper.BdTextView")
rec("TextSelectionHelper.BdTextView" not in L_IN_C
    and "TextSelectionHelper.BdTextView" not in L_OUT_C,
    "★ 布局不再引用嵌套类名")
rec("TextSelectionHelper$BdTextView" not in L_IN_C
    and "TextSelectionHelper$BdTextView" not in L_OUT_C,
    "布局未改用 `$`（XML 元素名不允许裸 $，也不允许 &#36;）")
rec("com.flashdrop.app.BdTextView" in L_IN_C,
    "item_text_in 引用顶层类全限定名")
rec("com.flashdrop.app.BdTextView" in L_OUT_C,
    "item_text_out 引用顶层类全限定名")
rec("h.meta instanceof BdTextView" in MA_C,
    "MainActivity 用顶层类名做 instanceof")

# APK 内实证
if os.path.exists(APK):
    z = zipfile.ZipFile(APK)
    dex = z.read("classes.dex")
    rec(dex.find(b"Lcom/flashdrop/app/BdTextView;") >= 0,
        "APK dex 内含 Lcom/flashdrop/app/BdTextView;")
    rec(dex.find(b"Lcom/flashdrop/app/TextSelectionHelper$BdTextView;") < 0,
        "★ APK dex 内无残留嵌套类 TextSelectionHelper$BdTextView")
else:
    rec(False, "APK 存在（跳过 dex 校验）", APK)

# ═════════════════════════════════════════════════════════════
sec("② 电脑端表情放大")
# ═════════════════════════════════════════════════════════════
WE = open(os.path.join(WIN, "app", "ui", "emoji.py"), encoding="utf-8").read()
# 只匹配**类属性赋值**（行首缩进 COLS/CELL = 数字），避免命中文档注释里的旧值
m = re.search(r"^\s{4}CELL\s*=\s*(\d+)\s*$", WE, re.M)
cell = int(m.group(1)) if m else 0
rec(cell == 44, "EmojiPanel.CELL == 44（原 36）", "实际 %d" % cell)
m2 = re.search(r"ICON_PAD\s*=\s*(\d+)", WE)
pad = int(m2.group(1)) if m2 else -1
rec(pad == 16, "图标内边距 ICON_PAD=16（v1.18.14）→ 图标框 28px", "实际 %d" % pad)
rec(re.search(r"setIconSize\(QSize\(cell\s*-\s*icon_pad", WE) is not None,
    "图标尺寸按 cell - icon_pad 计算")
rec("self.COLS = 10" in WE or "COLS = 10" in WE, "列数仍为 10")
# ★ v1.18.13：网格可见行数固定 6 行（微信同）
rec(re.search(r"GRID_ROWS\s*=\s*6", WE) is not None, "★ 网格可见 6 行（微信同）")

# 源图必须有足够分辨率
from PIL import Image
src_png = os.path.join(WIN, "assets", "fluent_emoji", "1st-place-medal.png")
if os.path.exists(src_png):
    im = Image.open(src_png)
    rec(im.width >= 72, "源图 >=72px（缩放后不糊）", "实际 %d" % im.width)
else:
    rec(False, "源图存在", src_png)

# ═════════════════════════════════════════════════════════════
sec("③ 安卓表情按钮位置 / 键盘互切 / 占键盘区 / 常用表情")
# ═════════════════════════════════════════════════════════════
i_cam = L_MAIN.find('android:id="@+id/btn_camera"')
i_edit = L_MAIN.find('android:id="@+id/input"')
i_emoji = L_MAIN.find('android:id="@+id/btn_emoji"')
i_plus = L_MAIN.find('android:id="@+id/btn_plus"')
rec(0 < i_cam < i_edit < i_emoji < i_plus,
    "输入栏顺序 相册 < 输入框 < 表情 < ＋")
rec("bottom|right" in L_MAIN[i_emoji - 300:i_emoji + 300],
    "表情按钮 anchored bottom|right（贴右下，「＋」左侧）")
rec("layout_marginRight=\"46dp\"" in L_MAIN[i_emoji - 200:i_emoji + 400],
    "与「＋」(36dp) 保持 46dp 间距，不重叠")
rec("btn_emoji" not in L_MAIN[:i_edit],
    "★ 表情按钮已从最左侧（输入框左边）移走")

# 面板在输入栏下方
i_panel = L_MAIN.find('android:id="@+id/emoji_panel"')
i_wrap = L_MAIN.find('android:id="@+id/input_wrap"')
rec(i_panel > i_wrap, "★ emoji_panel 在 input_wrap **下方**（键盘区域）")

# 键盘图标资源
rec(os.path.exists(os.path.join(RES, "drawable", "ic_keyboard.xml")),
    "ic_keyboard.xml 存在（键盘切换图标）")

# 图标互换逻辑
rec("updateEmojiIcon()" in MA, "MainActivity 有 updateEmojiIcon()")
rec("R.drawable.ic_keyboard : R.drawable.ic_emoji" in MA,
    "★ 面板可见→键盘图标，隐藏→表情图标")
rec("showIme()" in MA, "★ 新增 showIme()（切回键盘时拉起输入法）")
# ★ v1.18.13：改为「先收面板动画 → 动画结束回调里再拉起 IME」，
#   避免同一帧里既收面板又弹键盘造成聊天区闪动。
rec("hideEmojiPanelThen(1, () -> showIme())" in MA
    or re.search(r"hideEmojiPanelThen\(\s*1\s*,\s*\(\)\s*->\s*showIme\(\)\s*\)",
                 MA) is not None,
    "★ 再次点击面板 → 收起面板动画结束后再拉起键盘")
# ★ v1.18.14 演进：收起方法已由 hideEmojiPanel() 更名为
#   hideEmojiPanelThen(delayMs, after)，断言改为按方法名切片，避免改名连坐。
_seg = MA.split("private void hideEmojiPanelThen(")
rec(len(_seg) > 1 and "updateEmojiIcon();" in _seg[1][:1200],
    "收起动画结束后复位图标")

# 常用表情
rec("RECENT_MAX = 8" in EP, "常用表情上限 8（与微信一排对齐）")
rec("PREF_RECENT" in EP and "SharedPreferences" in EP,
    "常用表情持久化到 SharedPreferences")
rec("pushRecent(" in EP, "pushRecent() 记录常用")
rec("refreshRecent()" in EP, "refreshRecent() 重建那一行")
rec('"常用表情"' in EP, "界面文案含「常用表情」")
rec("recentWrap.setVisibility(View.GONE)" in EP,
    "无常用记录时整块隐藏（不占空白）")
rec(re.search(r"pushRecent\(fe\);\s*\n\s*refreshRecent\(\);\s*\n\s*onPick\.onPick",
              EP) is not None,
    "网格点击后立即入常用并刷新")

# 面板高度占键盘区
# ★ v1.18.13：兜底比例 42% → 36%（微信实测 36%~40%），上限 60% → 50%；
#   MainActivity 侧优先用真实测量到的 imeHeightPx。
rec("screenH * 0.36f" in EP, "★ 高度兜底比例下调到 36%（对齐微信，原 42%）")
rec("screenH * 0.45f" in EP, "★ 上限下调到屏幕 45%（v1.18.14；原 60% → 50% → 45%）")
rec(re.search(r"Math\.max\(lo,\s*Math\.min\(base,\s*hi\)\)", MA) is not None
    or "imeHeightPx" in MA,
    "★ 优先使用真实 IME 高度（MainActivity.imeHeightPx）")

# 目录资产未破坏
if os.path.exists(APK):
    z = zipfile.ZipFile(APK)
    n = z.namelist()
    rec("assets/emoji_catalog.json" in n, "APK 仍含 emoji_catalog.json")
    rec(len([x for x in n if x.startswith("res/drawable-nodpi")
             and x.endswith(".png")]) == 1592, "APK 仍含 1592 张表情 PNG")

print("\n" + "=" * 62)
if F:
    print("失败项：")
    for f in F:
        print("  - %s" % f)
print("v1.18.12 专项验收：通过 %d 项，失败 %d 项" % (len(P), len(F)))
print("=" * 62)
sys.exit(1 if F else 0)
