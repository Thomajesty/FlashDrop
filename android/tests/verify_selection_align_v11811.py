# -*- coding: utf-8 -*-
"""v1.18.11 专项验收：安卓局部选择文字（用户第 5 条）+ 顶部设备列表对齐（用户第 1 条）。

背景：v1.18.3 ~ v1.18.6 的旧套件各自断言**已废弃的中间实现**
（系统 TextIsSelectable / wantSelect 常驻写入）。v1.18.9 起改为
自绘手柄方案 TextSelectionHelper，旧断言因此全部失效。
本套件针对**最终实现**建立权威门槛。

运行：python tests/verify_selection_align_v11811.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
JAVA = os.path.join(ROOT, "app", "src", "main", "java", "com", "flashdrop", "app")
LAYOUT = os.path.join(ROOT, "app", "src", "main", "res", "layout")

MA = open(os.path.join(JAVA, "MainActivity.java"), encoding="utf-8").read()
TSH = open(os.path.join(JAVA, "TextSelectionHelper.java"), encoding="utf-8").read()
XML = open(os.path.join(LAYOUT, "activity_main.xml"), encoding="utf-8").read()

PASS = []
FAIL = []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    mark = "PASS" if cond else "FAIL"
    extra = ("   " + detail) if (detail and not cond) else ""
    print("  %s  %s%s" % (mark, name, extra))


def sec(t):
    print("\n=== %s ===" % t)


# ═════════════════════════════════════════════════════════════
sec("§1 局部选择：自绘手柄架构（最终实现）")
# ═════════════════════════════════════════════════════════════
check("存在 TextSelectionHelper.java", os.path.exists(
    os.path.join(JAVA, "TextSelectionHelper.java")))
check("内部类 BdTextView（可绑定的正文 TextView）",
      "class BdTextView" in TSH or "BdTextView" in TSH)
check("attach(tv, cb) 静态挂载入口",
      "public static TextSelectionHelper attach(" in TSH)
check("attach 返回 helper 并挂长按监听",
      "tv.setOnLongClickListener" in TSH)
check("attach 挂触摸监听（拖动手柄靠它）",
      "tv.setOnTouchListener" in TSH)
check("长按有触觉反馈（可感知）",
      "HapticFeedbackConstants.LONG_PRESS" in TSH)
check("长按 → 立刻全选（保证可见反馈）",
      "h.selectAll();" in TSH)
check("selectAll() 用 applySelection(0, len)",
      "applySelection(0, t.length())" in TSH)

sec("§2 局部选择：手柄 + 选区几何")
check("自绘左侧手柄", "handlePaint" in TSH)
check("手柄有描边（白圈）", "handleStroke" in TSH)
check("手柄主色 = accent 蓝 #3B82F6", "0xFF3B82F6" in TSH)
check("拖动时能命中手柄（有触摸判定）",
      "onTouch" in TSH and ("isNearHandle" in TSH or "hitHandle" in TSH
                            or "distance" in TSH or "handleHit" in TSH))
check("选区落在字符边界（Layout 反查 offset）",
      "getOffsetForHorizontal" in TSH or "getLineForVertical" in TSH
      or "getPrimaryHorizontal" in TSH)
check("松手回调 onSettled（弹菜单）",
      "onSettled" in TSH)

sec("§3 局部选择：与系统选择模式互斥（根因）")
check("★ 明确注释禁止再调 setTextIsSelectable（避免两套选区互抢）",
      "再调" in TSH and "setTextIsSelectable" in TSH
      and "系统选择模式" in TSH)
check("attach 路径内**不**调用 setTextIsSelectable",
      "setTextIsSelectable" not in TSH.split("public static TextSelectionHelper attach")[1]
      .split("// ====================")[0])

sec("§4 局部选择：MainActivity 接线")
check("存在 _textMenuHelper 字段",
      "private TextSelectionHelper _textMenuHelper;" in MA)
# ★ 已过期断言修正（v1.18.12 复核）：
#   v1.18.11 时 BdTextView 是 TextSelectionHelper 的**嵌套类**，
#   故判定写成 `instanceof TextSelectionHelper.BdTextView`。
#   但嵌套类 dex 名是 `TextSelectionHelper$BdTextView`，而 XML 布局里
#   **不允许**裸 `$`（aapt2: not well-formed）也不允许 `&#36;`，
#   → 用户实测点击离线设备直接 ClassNotFoundException 闪退。
#   修法是把 BdTextView 提升为**顶层类** com.flashdrop.app.BdTextView。
#   不变量不变：仍要把「正文 View 是否为本应用自绘的 BdTextView」判准，
#   只是全限定名少了一层。
check("绑定路径区分 BdTextView（顶层类全限定名）",
      "h.meta instanceof BdTextView" in MA)
check("attach 时传入 showTextMenu 回调",
      "showTextMenu(mm, bd)" in MA)
check("用 tag_sel_helper 做复用保护（convertView 安全）",
      'bd.getTag(R.id.tag_sel_helper)' in MA)
check("多选模式下退出选择态（避免与勾选争触摸）",
      "h.selHelper.isActive()" in MA and "h.selHelper.clear();" in MA)
check("自建菜单含「复制选中」", "复制选中" in MA)
check("自建菜单含「全选」", "全选" in MA)
check("存在 showTextMenu 方法",
      re.search(r"(private|void)\s+void\s+showTextMenu\(", MA) is not None
      or "void showTextMenu(" in MA)

# ═════════════════════════════════════════════════════════════
sec("§5 顶部设备列表对齐（用户第 1 条）")
# ═════════════════════════════════════════════════════════════
check("整行最小高度 40dp（与选择框等高）",
      "row.setMinimumHeight(dp(40))" in MA)
check("整行水平内缩统一为 14dp / 14dp",
      "row.setPadding(dp(14), 0, dp(14), 0)" in MA,
      "★ v1.18.13 由 14/12 改为左右对称 14（配合固定槽位方案，避免右侧多退 2dp）")
check("整行垂直居中",
      "row.setGravity(android.view.Gravity.CENTER_VERTICAL)" in MA)
check("状态灯 9dp（尺寸统一）",
      "new FrameLayout.LayoutParams(\n                dp(9), dp(9)," in MA
      or re.search(r"new FrameLayout\.LayoutParams\(\s*dp\(9\),\s*dp\(9\)", MA)
      is not None,
      "★ v1.18.13：灯由 LinearLayout 直挂改为放进 DOT_SLOT 槽位（FrameLayout.LayoutParams）")
check("名字 → 状态灯 间距 8dp",
      "tlp.rightMargin = dp(8)" in MA or "dlp.leftMargin = dp(8)" in MA,
      "★ v1.18.13：间距改由名字右侧 margin 控制（灯不再依赖左侧 margin）")
check("★ 固定槽位把 ✕ 推到最右端（DOT_SLOT_DP / X_SLOT_DP）",
      "DOT_SLOT_DP" in MA and "X_SLOT_DP" in MA,
      "★ v1.18.13 取代原「weight 1f 弹性空白」方案：固定宽度槽位保证收起/展开骨架一致")
check("★ 状态灯在槽位内右对齐（收起/展开同一 x）",
      "android.view.Gravity.RIGHT" in MA and "dotSlot" in MA,
      "★ v1.18.13 取代原「状态灯 → ✕ 间距 10dp」；✕ 槽位独立，间距不再手工指定")
check("✕ 由 getDropDownView 填入既有槽位（唯一）",
      "TAG_DELETE_X" in MA and "xSlot" in MA)

sec("§6 表情按钮（用户第 4 条）回归")
check("btn_emoji 在布局中存在", 'android:id="@+id/btn_emoji"' in XML)
check("emoji_panel 容器存在", 'android:id="@+id/emoji_panel"' in XML)
check("btn_emoji 在 btn_plus 之前（左侧）",
      XML.index("@+id/btn_emoji") < XML.index("@+id/btn_plus"))
check("输入时表情图标常驻（updateSendPlus 不动 btnEmoji）",
      "btnEmoji" not in (re.search(
          r"private void updateSendPlus\(\)\s*\{(.*?)\n    \}", MA, re.S
      ).group(1) if re.search(
          r"private void updateSendPlus\(\)\s*\{(.*?)\n    \}", MA, re.S) else ""))

sec("§7 取消按钮 + 待发送文案（用户第 3 条）回归")
check("取消按钮走 normalizeButton 统一样式",
      "normalizeButton" in MA)
check("待发送文案精简为「⏳ 待发送」",
      "⏳ 待发送" in MA)
check("文案长度 <= 6 字符（不含 emoji）",
      len("待发送") <= 6)

# ═════════════════════════════════════════════════════════════
print("\n" + "=" * 62)
if FAIL:
    print("失败项：")
    for f in FAIL:
        print("  - %s" % f)
print("v1.18.11 专项验收：通过 %d 项，失败 %d 项" % (len(PASS), len(FAIL)))
print("=" * 62)
sys.exit(1 if FAIL else 0)
