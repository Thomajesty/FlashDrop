# -*- coding: utf-8 -*-
"""v1.18.29 表情面板验收：assets 必须进包 + 加载失败必须可见

用户反馈：「安卓版的表情包不显示了」。

根因（版本回归，已定位到 v1.18.22）：
  构建脚本 build_apk.bat 的 aapt2 link 漏了 `-A <assets>` 参数 →
  assets/emoji_catalog.json 没打进 APK → EmojiPicker.loadCatalog()
  抛异常被 `catch (Throwable ignored)` 静默吞掉 → 目录为空 →
  页签/网格全空，面板打开就是一块空白。
  （v1.18.13~v1.18.21 的包都有 catalog，v1.18.22 起丢失，
    已逐个拆 release/history 的 APK 对比确认；1592 张表情 PNG 一直都在，
    唯独缺这一个 json。）

本脚本三层验收：
  A. 构建脚本：两个打包入口的 aapt2 link 都必须带 -A assets（反向防护，
     历史上正是漏了它）；
  B. 运行时兜底：目录加载失败必须 logcat 留痕 + 面板显示可见提示，
     不允许再出现"静默空白"；
  C. 资源完整性：源码 catalog（10 组）与 drawable-nodpi 的 e_*.png
     一一对应；若已有 v1.18.29 的 APK 产物，拆包断言
     assets/emoji_catalog.json 与全部表情图确已在包内。

运行：python windows/tests/verify_v11829_emoji_assets.py
"""
import json
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
AND = os.path.join(ROOT, "android", "app", "src", "main", "java",
                   "com", "flashdrop", "app")
AND_RES = os.path.join(ROOT, "android", "app", "src", "main")
CATALOG = os.path.join(AND_RES, "assets", "emoji_catalog.json")
NODPI = os.path.join(AND_RES, "res", "drawable-nodpi")
BUILD_BAT = os.path.join(ROOT, "android", "build_apk.bat")
BUILD_SH = os.path.join(ROOT, "android", "_build_v11817.sh")
PICKER = os.path.join(AND, "EmojiPicker.java")

FAILS = []
N = 0


def ck(name, cond, extra=""):
    global N
    N += 1
    if not cond:
        FAILS.append(f"{name} | {extra}")
    print(("  ok  " if cond else " FAIL ") + name +
          ((" | " + str(extra)) if extra else ""))


def rd(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


# ================= A. 构建脚本必须把 assets 带进包 =================

def section_build_scripts():
    print("\n—— A. 构建脚本：aapt2 link 必须带 -A assets ——")
    bat = rd(BUILD_BAT)
    ck("build_apk.bat 的 aapt2 link 带 -A \"%SRC%\\assets\"",
       '-A "%SRC%\\assets"' in bat,
       "v1.18.22~v1.18.28 正是漏了它 → catalog 不进包 → 表情面板全空白")
    ck("build_apk.bat 里有说明该参数原因的注释",
       "emoji_catalog.json 不会进包" in bat or "assets/ 打进 APK" in bat)

    sh = rd(BUILD_SH)
    ck("_build_v11817.sh 的 aapt2 link 带 -A assets",
       re.search(r'-A\s+"\$BPW\\+assets"', sh) is not None,
       "bash 字符串里写作 -A \"$BPW\\\\assets\"（两个反斜杠=一个字面反斜杠）")
    # 反向防护：link 命令（跨行续接）里 --java 之前必须确有 -A
    m = re.search(r'aapt2\.exe" link(.*?)--java', sh, re.S)
    ck("_build_v11817.sh link 参数串里确有 -A", bool(m and "-A" in m.group(1)))


# ================= B. 运行时兜底：失败必须可见 =================

def section_runtime_guard():
    print("\n—— B. EmojiPicker：加载失败必须留痕 + 可见提示 ——")
    src = rd(PICKER)

    # loadCatalog 的 catch 不能再是静默的 ignored（至少打 Log.e）
    m = re.search(r"private void loadCatalog\(\).*?\n    \}", src, re.S)
    ck("能定位到 loadCatalog() 方法", m is not None)
    if m:
        body = m.group(0)
        ck("loadCatalog 失败时打 Log.e 留痕（logcat 可诊断）",
           "Log.e" in body and "emoji_catalog.json failed" in body,
           "曾用 catch (Throwable ignored) 静默吞掉，线上无任何线索")
        ck("loadCatalog 不再用裸 ignored 吞异常",
           "catch (Throwable ignored)" not in body)
        ck("loadCatalog 拍平时把 groups[].name 注入条目的 group 字段",
           'put("group"' in body and "gname" in body,
           "catalog 条目本身不带 group；不注入 → 全部归「全部表情」→ 只剩 1 个页签")

    # 目录为空时构造函数必须给 hint 设置可见提示
    ck("groupNames 为空时 hint 显示「表情加载失败」提示",
       "groupNames.isEmpty()" in src and "表情加载失败" in src,
       "不允许出现打开面板却一片空白、无任何提示")
    ck("提示文案引导用户重启/反馈",
       "重启应用" in src)


# ================= C. 资源完整性 + 产物断言 =================

def section_resources():
    print("\n—— C1. 源码资源：catalog ↔ drawable-nodpi 一一对应 ——")
    ck("assets/emoji_catalog.json 存在", os.path.isfile(CATALOG))
    if not os.path.isfile(CATALOG):
        return None
    with open(CATALOG, encoding="utf-8") as f:
        cat = json.load(f)
    groups = cat.get("groups", [])
    entries = [e for g in groups for e in g.get("emojis", [])]
    ck("catalog 可解析且有 10 个分组", len(groups) == 10, f"实际 {len(groups)}")
    ck("catalog 条目总数 > 1500（Microsoft Fluent Emoji 全量）",
       len(entries) > 1500, f"实际 {len(entries)}")
    ck("每条条目都有 slug/char/cn 三个字段",
       all(all(k in e for k in ("slug", "char", "cn")) for e in entries))
    ck("catalog 条目按设计**不带** group（分组由 groups[].name 归属）",
       all("group" not in e for e in entries),
       "因此 loadCatalog 必须注入组名，否则 buildTabs 全归到 Other")
    ck("catalog 里无重复 slug",
       len({e["slug"] for e in entries}) == len(entries))

    # 每个 slug 都应有对应 PNG：e_<slug 的 - 换 _>.png
    expect = {"e_" + e["slug"].replace("-", "_") + ".png" for e in entries}
    have = {f for f in os.listdir(NODPI)
            if f.startswith("e_") and f.endswith(".png")} \
        if os.path.isdir(NODPI) else set()
    missing = expect - have
    ck("每个 catalog 条目都有对应 e_*.png", not missing,
       f"缺 {len(missing)} 张：{sorted(missing)[:3]}")
    ck("drawable-nodpi 的 e_*.png 数量与 catalog 条目数一致",
       len(have) == len(entries), f"png={len(have)} catalog={len(entries)}")


def section_apk():
    print("\n—— C2. 打包产物：APK 内必须含 catalog + 全部表情图 ——")
    apk = None
    for p in (os.path.join(ROOT, "release", "latest", "FlashDrop_v1.18.29.apk"),
              os.path.join(ROOT, "android", "dist", "FlashDrop.apk")):
        if os.path.isfile(p):
            apk = p
            break
    if apk is None:
        print("  --  未找到 v1.18.29 APK 产物（打包前运行属正常），跳过拆包断言")
        return
    print(f"  拆包：{os.path.relpath(apk, ROOT)}")
    with zipfile.ZipFile(apk) as zf:
        names = zf.namelist()
        ck("APK 内含 assets/emoji_catalog.json",
           "assets/emoji_catalog.json" in names,
           "v1.18.22~v1.18.28 的包正是缺这一条")
        png = [n for n in names
               if re.search(r"res/[^/]*/e_[a-z0-9_]+\.png$", n)]
        ck("APK 内 e_*.png 数量 = 1592", len(png) == 1592,
           f"实际 {len(png)}")
        if "assets/emoji_catalog.json" in names:
            cat = json.loads(zf.read("assets/emoji_catalog.json")
                             .decode("utf-8"))
            n = sum(len(g.get("emojis", [])) for g in cat.get("groups", []))
            ck("APK 内 catalog 可解析：10 组 / 1592 条",
               len(cat.get("groups", [])) == 10 and n == 1592,
               f"实际 {len(cat.get('groups', []))} 组 / {n} 条")


# ================= D. 面板逻辑仿真（Python 复刻） =================

def section_sim():
    print("\n—— D. 面板逻辑仿真：成功路径 / 目录缺失路径 ——")
    src = rd(PICKER)
    pairs = re.findall(r'\{"([^"]+)", "([^"]+)"\}', src)
    group_cn = dict(pairs)
    ck("从源码解析到 10 个分组中文映射", len(group_cn) == 10,
       f"实际 {len(group_cn)}")
    ck("「Other」映射为「全部表情」（v1.18.13 要求）",
       group_cn.get("Other") == "全部表情")

    with open(CATALOG, encoding="utf-8") as f:
        cat = json.load(f)

    def flatten(cat_doc):
        """复刻 loadCatalog()（v1.18.29 修复后）：拍平并把组名注入条目"""
        out = []
        for g in cat_doc.get("groups", []):
            gname = g.get("name", "Other")
            for e in g.get("emojis", []):
                e2 = dict(e)
                e2["group"] = gname
                out.append(e2)
        return out

    cache = flatten(cat)

    def build_tabs(cache_entries):
        """复刻 buildTabs()：按 GROUP_CN 顺序归组，空组不进页签"""
        order = [g[0] for g in pairs]
        for o in cache_entries:
            g = o.get("group", "Other")
            if g not in order:
                order.append(g)
        names, buckets = [], []
        for g in order:
            b = [o for o in cache_entries if o.get("group", "Other") == g]
            if b:
                names.append(g)
                buckets.append(b)
        return names, buckets

    def hint_of(names, buckets, idx=0):
        """复刻构造函数收尾 + selectGroup(idx) 对 hint 的影响"""
        if not names:
            return "表情加载失败，请重启应用或向开发者反馈"
        return f"{group_cn.get(names[idx], names[idx])} · 共 {len(buckets[idx])} 个"

    # 成功路径：10 个页签、首个页签是「表情」
    names, buckets = build_tabs(cache)
    ck("正常路径：10 个页签（与 catalog 分组一致）",
       len(names) == 10, f"实际 {len(names)}")
    ck("正常路径：首个页签是「表情」，提示含个数",
       names and group_cn.get(names[0]) == "表情" and "共" in hint_of(names, buckets),
       hint_of(names, buckets))
    ck("正常路径：末个页签是「全部表情」（Other 组 4 个）",
       names and group_cn.get(names[-1]) == "全部表情" and len(buckets[-1]) == 4,
       f"{names[-1] if names else '-'} / {len(buckets[-1]) if buckets else 0} 个")
    ck("正常路径：各页签条目数之和 = 1592（无遗漏无重复）",
       sum(len(b) for b in buckets) == 1592)

    # 反向防护：不注入 group（旧行为）→ 全部塌进「全部表情」→ 只剩 1 个页签
    raw = [e for g in cat.get("groups", []) for e in g.get("emojis", [])]
    names_bug, buckets_bug = build_tabs(raw)
    ck("反向：不注入组名时确实会塌成 1 个页签（证明注入必要）",
       names_bug == ["Other"] and len(buckets_bug[0]) == 1592,
       f"实际 {len(names_bug)} 个页签")

    # 失败路径：catalog 缺失 → CACHE 空 → 无页签 → 必须显示失败提示
    names0, buckets0 = build_tabs([])
    h = hint_of(names0, buckets0)
    ck("目录缺失路径：无页签（复现当时的空白面板）", names0 == [])
    ck("目录缺失路径：hint 必须显示「表情加载失败」而非空白",
       bool(h) and "失败" in h, f"hint={h!r}")

    # 切页签时 hint 跟随分组刷新
    if len(names) >= 2:
        ck("切换页签后 hint 显示对应分组中文名与个数",
           group_cn.get(names[1], "") in hint_of(names, buckets, 1),
           hint_of(names, buckets, 1))


def main():
    print("=" * 70)
    print("v1.18.29 表情面板验收：assets 进包 + 失败可见")
    print("=" * 70)
    section_build_scripts()
    section_runtime_guard()
    section_resources()
    section_apk()
    section_sim()
    print("\n" + "=" * 70)
    print(f"结果：{N - len(FAILS)}/{N} 通过")
    if FAILS:
        print("失败项：")
        for f in FAILS:
            print("  - " + f)
        return 1
    print("全部通过 —— assets 已进包、目录缺失时有可见提示，表情面板可正常显示")
    return 0


if __name__ == "__main__":
    sys.exit(main())
