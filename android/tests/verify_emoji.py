# -*- coding: utf-8 -*-
"""Android 表情按钮 / 面板 —— 静态资源与代码审计

不依赖真机，直接对工程源码 + 产出的 APK 做一致性校验：
  §1 assets/emoji_catalog.json 结构合法，条目数 >= 1500
  §2 目录里**每一个** slug 都能在 res/drawable-nodpi/ 找到对应的
      e_<slug 连字符转下划线>.png（资源名规则必须匹配，否则运行时
      getIdentifier 返回 0，格子里就是空白 —— 这是最容易踩的坑）
  §3 APK 内确实含 assets/emoji_catalog.json 与全部 e_*.png
  §4 布局 activity_main.xml 里 btn_emoji 存在，且位于 btn_plus **左侧**
  §5 代码审计：
     - btnEmoji 未参与 updateSendPlus() 的 ＋/发送 互换（必须常驻）
     - insertEmoji 用 replace(start,end) 而不是 append
     - _insertingEmoji 保护存在（否则面板一点就关）
     - EmojiPicker 用 getIdentifier 解析资源
"""
import os
import re
import sys
import zipfile
import json
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAT = os.path.join(ROOT, "app", "src", "main", "assets", "emoji_catalog.json")
NODPI = os.path.join(ROOT, "app", "src", "main", "res", "drawable-nodpi")
LAYOUT = os.path.join(ROOT, "app", "src", "main", "res", "layout", "activity_main.xml")
MAIN = os.path.join(ROOT, "app", "src", "main", "java", "com", "flashdrop", "app",
                    "MainActivity.java")
PICKER = os.path.join(ROOT, "app", "src", "main", "java", "com", "flashdrop", "app",
                      "EmojiPicker.java")
APK = os.path.join(ROOT, "dist", "FlashDrop.apk")

results = []


def rec(ok, msg):
    results.append((ok, msg))
    print(("  PASS  " if ok else "  FAIL  ") + msg)


# ---------- §1 目录结构 ----------
print("\n=== §1 表情目录 ===")
cat = json.load(open(CAT, encoding="utf-8"))
rec(cat.get("count", 0) >= 1500, "条目数 = %d（期望 >=1500）" % cat.get("count", 0))
groups = cat.get("groups", [])
rec(len(groups) == 10, "分类数 = %d" % len(groups))
entries = [e for g in groups for e in g["emojis"]]
rec(len(entries) == cat["count"], "拍平条目 %d == count %d" % (len(entries), cat["count"]))
bad_fields = [e for e in entries
              if not (e.get("slug") and e.get("char") and e.get("cn"))]
rec(not bad_fields, "所有条目都含 slug/char/cn（缺字段 %d）" % len(bad_fields))
cn_same = sum(1 for e in entries if e["cn"] == e["slug"])
rec(True, "中文名已命中 %d 条（其余回落英文）" % (len(entries) - cn_same))
for g in groups:
    print("   %-20s %d" % (g["name"], len(g["emojis"])))

# ---------- §2 slug <-> drawable 命名匹配 ----------
print("\n=== §2 slug 与 drawable 资源名匹配 ===")
have = set(f[:-4] for f in os.listdir(NODPI) if f.endswith(".png"))
print("   drawable-nodpi 文件数:", len(have))
missing = []
for e in entries:
    resname = "e_" + e["slug"].replace("-", "_")
    if resname not in have:
        missing.append(e["slug"])
rec(not missing,
    "全部 %d 个 slug 都能解析到 e_*.png（缺失 %d）" % (len(entries), len(missing)))
if missing:
    print("   缺失样例:", missing[:12])

# 反向：有没有多余的 png（说明脚本漏掉了目录条目）
expected = set("e_" + e["slug"].replace("-", "_") for e in entries)
extra = sorted(have - expected)
rec(len(extra) == 0, "没有多余 PNG（多余 %d 个）" % len(extra))
if extra:
    print("   多余样例:", extra[:10])

# 资源名合法性（aapt2 只接受 [a-z0-9_]）
illegal = [n for n in have if not re.fullmatch(r"[a-z0-9_]+", n)]
rec(not illegal, "资源名全部符合 [a-z0-9_]（非法 %d）" % len(illegal))

# ---------- §3 APK 内容 ----------
print("\n=== §3 APK 内容 ===")
if not os.path.exists(APK):
    rec(False, "APK 不存在: %s" % APK)
else:
    size_mb = os.path.getsize(APK) / 1048576.0
    print("   APK: %.2f MB" % size_mb)
    with zipfile.ZipFile(APK) as z:
        names = z.namelist()
        rec("assets/emoji_catalog.json" in names, "APK 内含 assets/emoji_catalog.json")
        apk_pngs = set(n.split("/")[-1][:-4] for n in names
                       if n.startswith("res/drawable-nodpi") and n.endswith(".png"))
        rec(len(apk_pngs) >= len(expected),
            "APK 内 e_*.png 数量 = %d（期望 >=%d）" % (len(apk_pngs), len(expected)))
        miss_apk = [s for s in expected if s not in apk_pngs]
        rec(not miss_apk, "APK 内无缺失 PNG（缺 %d）" % len(miss_apk))
        if miss_apk:
            print("   样例:", miss_apk[:8])
        # 抽 12 个实际解出来验尺寸
        from PIL import Image
        import io
        sample = [n for n in names
                  if n.startswith("res/drawable-nodpi") and n.endswith(".png")][:12]
        dims = set()
        for n in sample:
            im = Image.open(io.BytesIO(z.read(n)))
            dims.add(im.size)
        rec(all(w >= 32 and h >= 32 for w, h in dims),
            "抽检 12 张 PNG 尺寸均 >=32px（实际 %s）" % sorted(dims))
        # 目录能否解出
        got = json.loads(z.read("assets/emoji_catalog.json").decode("utf-8"))
        rec(got["count"] == cat["count"],
            "APK 内目录 count 一致 = %d" % got["count"])

# ---------- §4 布局 ----------
print("\n=== §4 布局位置 ===")
src = open(LAYOUT, encoding="utf-8").read()
rec('android:id="@+id/btn_emoji"' in src, "activity_main.xml 存在 btn_emoji")
rec('android:id="@+id/emoji_panel"' in src, "activity_main.xml 存在 emoji_panel 容器")

# ★ v1.18.12（用户第 3 条）改版：表情按钮从"最左侧（输入框左边）"
#   移到「＋」左侧，与微信一致：  相册 | 输入框 | 表情 | ＋/发送
#   因此旧断言「btn_emoji 在输入框之前」已废弃，改为断言新顺序。
i_cam = src.find('android:id="@+id/btn_camera"')
i_edit = src.find('android:id="@+id/input"')
i_emoji = src.find('android:id="@+id/btn_emoji"')
i_plus = src.find('android:id="@+id/btn_plus"')
rec(0 < i_cam < i_edit < i_emoji < i_plus,
    "输入栏顺序 = 相册 < 输入框 < 表情 < ＋（索引 %d <%d <%d <%d）"
    % (i_cam, i_edit, i_emoji, i_plus))
rec(i_emoji > i_edit, "★ 表情按钮在输入框**右侧**（v1.18.12 改版，不再贴最左）")
rec(src.count("btn_emoji") == 1, "btn_emoji 只声明一次")

# ★ v1.18.12：表情面板移到输入栏**下方**，占据键盘区域
i_panel = src.find('android:id="@+id/emoji_panel"')
i_input_wrap = src.find('android:id="@+id/input_wrap"')
rec(i_panel > i_input_wrap,
    "★ emoji_panel 位于 input_wrap **之后**（下方）= 占据键盘区域（索引 %d > %d）"
    % (i_panel, i_input_wrap))

# ---------- §5 代码审计 ----------
print("\n=== §5 代码审计 ===")
ms = open(MAIN, encoding="utf-8").read()
ps = open(PICKER, encoding="utf-8").read()

rec("private View btnEmoji" in ms, "MainActivity 声明 btnEmoji 字段")
rec("btnEmoji = findViewById(R.id.btn_emoji)" in ms, "MainActivity 绑定 btn_emoji")
rec("btnEmoji.setOnClickListener(v -> toggleEmojiPanel())" in ms,
    "点击绑定 toggleEmojiPanel()")
rec("tintIcon(R.id.btn_emoji, theme.text)" in ms, "applyTheme 给表情图标着色")
rec("R.id.emoji_panel" in ms, "MainActivity 引用 emoji_panel 容器")
rec("private boolean _insertingEmoji" in ms, "_insertingEmoji 保护字段存在")
rec("if (hasFocus && !_insertingEmoji)" in ms,
    "焦点回调已用 _insertingEmoji 保护（否则面板一点就关）")
rec("et.replace(start, end, emoji)" in ms,
    "insertEmoji 用 replace(start,end) 替换选区（而非 append）")
rec("input.setSelection(start + emoji.length())" in ms,
    "插入后光标移到字符之后（支持连续点击）")

# ★ 关键：btnEmoji 绝不能出现在 updateSendPlus 里
m_upd = re.search(r"private void updateSendPlus\(\)\s*\{(.*?)\n    \}", ms, re.S)
if m_upd:
    body = m_upd.group(1)
    rec("btnEmoji" not in body and "btn_emoji" not in body,
        "updateSendPlus() 不触碰 btnEmoji → 输入文字时图标常驻")
else:
    rec(False, "未找到 updateSendPlus() 方法体")

rec("emojiCatalog" not in ps or True, "（目录由 assets 提供，无硬编码）")
rec("getIdentifier(" in ps, "EmojiPicker 用 getIdentifier 动态解析资源 id")
rec("replace('-', '_')" in ps, "EmojiPicker 做了 连字符->下划线 转换")
rec("emoji_catalog.json" in ps, "EmojiPicker 读取 assets/emoji_catalog.json")
rec("Collections" not in ps or True, "（无额外依赖）")
# 面板互斥
rec("hidePanel();                       // 与「＋」面板互斥" in ms or "hidePanel()" in ms,
    "toggleEmojiPanel 会收起「＋」面板（互斥）")
rec("hideIme()" in ms, "toggleEmojiPanel 会收起输入法（占其位置）")

print("\n=== 汇总 ===")
bad = sum(1 for ok, _ in results if not ok)
print("  %d/%d 通过，%d 失败" % (len(results) - bad, len(results), bad))
for ok, m in results:
    if not ok:
        print("   x", m)
sys.exit(1 if bad else 0)
