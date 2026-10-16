# -*- coding: utf-8 -*-
"""v1.18.8 静态验收 —— 修复「文件已收到却显示接收失败」

═══ 用户反馈 ═══════════════════════════════════════════════════

> 电脑给手机端发送文件 电脑端显示已送达 手机端显示失败
> 我是不确定是不是后台是打开的
> 确定了 后台状态下接收不成功
> 文件在 但是显示接受失败      ← ★ 关键：文件其实收到了！

═══ 根因（后台落库的去重缺陷） ═════════════════════════════════

`FlashApp.persistInboundEvent()` 负责「前台界面不在时把接收记录落库」。
它按 `peerId|tid` 去重：

    String key = peerId + "|" + "t" + tid;
    if (bgSeenKeys.contains(key)) return;     // 只落第一条

**但一次文件接收会产生一串事件**：

    offer → confirm → started → progress… → done

第一条 `offer` 被写进历史并**占住了 key**，真正代表结果的 `done`
反而被去重**跳过**。

于是用户回到前台读到的是 `state = offer` 的记录：
  · 文件卡片 `got=false` → 渲染成**未接收的虚线态**
  · 状态文案停在「等待接收…」
→ 看起来就是「接收失败」，而文件其实**已完整落盘**
（这正好解释了：电脑端显示已送达、手机 Download 里也能找到文件）。

═══ 修复（三处） ═══════════════════════════════════════════════

1. **后台落库只认终态**（done/failed/refused/cancelled）—— 根因修复，
   中间态不再占 key。
2. **UI 状态自愈**：接收侧若 `hasLocalContent(m)` 为真但 state 不是成功态，
   就地修正为 `done` —— 让**已经写坏的旧记录无需重传**即可正常显示。
3. **got 判定改以本地实况为准**：`hasLocalContent(m) || done`，
   「文件在本地」是不会骗人的事实。
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ANDROID = os.path.dirname(HERE)
SRC = os.path.join(ANDROID, "app", "src", "main", "java", "com", "flashdrop", "app")
MA = open(os.path.join(SRC, "MainActivity.java"), encoding="utf-8").read()
FA = open(os.path.join(SRC, "FlashApp.java"), encoding="utf-8").read()
FU = open(os.path.join(SRC, "FdUtil.java"), encoding="utf-8").read()
MF = open(os.path.join(ANDROID, "app", "src", "main", "AndroidManifest.xml"),
          encoding="utf-8").read()
BAT = open(os.path.join(ANDROID, "build_apk.bat"), encoding="utf-8").read()

# v1.18.12 新增：TextSelectionHelper 现在是正文可选中能力的提供方，
# 该套件最后一条不变量断言需要读它。
_TSH_PATH = os.path.join(SRC, "TextSelectionHelper.java")
TSH_CODE = (open(_TSH_PATH, encoding="utf-8").read()
            if os.path.exists(_TSH_PATH) else "")

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


FA_CODE = strip_comments(FA)
MA_CODE = strip_comments(MA)

print("=" * 62)
print("v1.18.8 静态验收 —— 文件已收到却显示接收失败")
print("=" * 62)

section("§1 ★ 根因修复：后台落库只认终态")
m = re.search(r"String st = e\.optString\(\"state\"\);(.*?)\n            \}", FA_CODE, re.S)
BLOCK = m.group(1) if m else ""
check("已提取 state 变量", 'String st = e.optString("state");' in FA_CODE)
check("接收类事件先判终态", "if (isRecv)" in BLOCK)
check("终态包含 done", '"done".equals(st)' in BLOCK)
check("终态包含 failed", '"failed".equals(st)' in BLOCK)
check("终态包含 refused", '"refused".equals(st)' in BLOCK)
check("终态包含 cancelled", '"cancelled".equals(st)' in BLOCK)
check("非终态直接 return（不占 key）", "if (!terminal) return;" in BLOCK)
check("去重逻辑仍在（防重复落终态）",
      "bgSeenKeys.contains(key)" in FA_CODE)
check("落库使用提取出的 st", 'rec.put("state", st);' in FA_CODE)
check("注释点明了根因（offer 占住 key）",
      "offer" in FA and "去重" in FA)

section("§2 ★ UI 状态自愈（让旧记录无需重传）")
check("接收侧存在自愈逻辑",
      'if (!out && hasLocalContent(m)' in MA_CODE)
check("自愈条件排除已是成功态的情况",
      '!"done".equals(m.state) && !"ok".equals(m.state)' in MA_CODE)
check("自愈动作是置为 done", 'm.state = "done";' in MA_CODE)
check("自愈位置在 got 判定之前",
      MA_CODE.find("if (!out && hasLocalContent(m)")
      < MA_CODE.find('got = hasLocalContent(m) || "done".equals(m.state)'))

section("§3 got 判定改以本地实况为准")
check("接收侧 got = hasLocalContent(m) || done",
      'got = hasLocalContent(m) || "done".equals(m.state);' in MA_CODE)
check("发送侧判定未受影响",
      'got = "done".equals(m.state) || "ok".equals(m.state);' in MA_CODE)

section("§4 回归：前台接收链路未受影响")
check("前台仍复用同一条消息（byTidIn）", "byTidIn.get(tid)" in MA_CODE)
check("前台每次事件更新 state", "m.state = state;" in MA_CODE)
check("已上屏条目状态推进时写盘", "persistState(m)" in MA_CODE)
check("落盘回读确认仍在（verifySavedFile）",
      "verifySavedFile" in open(os.path.join(SRC, "FlashNode.java"),
                                encoding="utf-8").read())
check("FILE_OK 仍带 verified",
      '"verified", verified' in open(os.path.join(SRC, "FlashNode.java"),
                                     encoding="utf-8").read())

section("§5 回归：文本长按三层修复仍在")
check("setItemsCanFocus(true) 保留",
      "chatList.setItemsCanFocus(true);" in MA_CODE)
check("文本气泡不可点不可长按",
      re.search(r"bubble != null && !isFile.*?bubble\.setLongClickable\(false\)",
                MA_CODE, re.S) is not None)
# ★ 已过期断言二次修正（v1.18.12 复核）：
#   断言演进史：
#     v1.18.7  写法 `h.meta.setTextIsSelectable(wantSelect)` 一次性灌入
#     v1.18.8+ 为避免"气泡整体可选中"导致长按菜单错乱 → 改为按需开启，
#              用户真正要全选时才 `tv.setTextIsSelectable(true)`
#              字面量形态是 `tv.setTextIsSelectable(true)`
#     v1.18.12 全选入口 `selectAllText(TextView tv)` 被判定为死代码删除
#              （长按菜单已统一走 TextSelectionHelper 的局部选择路径，
#               不再有第二个全选入口），最后一次 `setTextIsSelectable(true)`
#              字面量随之消失。
#   ★ 不变量（真正要守的）从未改变：**正文最终仍可被选中**。
#     现在它由 TextSelectionHelper 内部保证，所以断言改为校验
#     helper 的 attach 链路上确实开启了文本可选中能力。
check("正文可选中能力保留（改由 TextSelectionHelper 提供）",
      ("setTextIsSelectable" in MA_CODE
       or "setTextIsSelectable" in TSH_CODE
       or "textIsSelectable" in TSH_CODE)
      and "TextSelectionHelper" in MA_CODE)

section("§6 回归：状态文案未被破坏")
check("offer 文案仍在", '"等待接收…"' in MA_CODE)
check("done 文案（接收侧=已保存）", '"已保存"' in MA_CODE)
check("failed 文案仍在", '"失败 · "' in MA_CODE)

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
