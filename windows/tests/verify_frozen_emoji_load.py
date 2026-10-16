# -*- coding: utf-8 -*-
"""验证 emoji.py 在 **冻结环境语义** 下能正确加载资产。

做法：把 EXE 的 CArchive 按 PyInstaller 运行时布局解包到临时目录
      （模拟 sys._MEIPASS），然后把 emoji.py 的 _emoji_dir()/_catalog_path()
      切到该目录，真实调用 load_catalog() + 取 8 个 QPixmap，
      确认"打包后能出图"这条关键路径成立。

不依赖 GUI 窗口可见（沙箱里窗口不可见，但 QPixmap 渲染不需要可见窗口）。
"""
import io
import os
import sys
import tempfile

os.environ.pop("QT_QPA_PLATFORM", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

EXE = os.path.join(ROOT, "dist", "FlashDrop.exe")

P, F = [], []


def check(name, cond, detail=""):
    (P if cond else F).append(name)
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", name,
                          ("   " + detail) if (detail and not cond) else ""))


print("=" * 62)
print("冻结环境（_MEIPASS 语义）下表情资产加载验收")
print("=" * 62)

# ── 1. 模拟 _MEIPASS：解包 EXE 里的 assets/*
MP = tempfile.mkdtemp(prefix="fd_meipass_")
from PyInstaller.archive.readers import CArchiveReader

r = CArchiveReader(EXE)
toc = list(r.toc.keys())
n_ok = 0
for n in toc:
    norm = n.replace("\\", "/")
    if not norm.startswith("assets/"):
        continue
    dst = os.path.join(MP, *norm.split("/"))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "wb") as fh:
        fh.write(r.extract(n))
    n_ok += 1

print("已模拟 _MEIPASS:", MP)
print("解出 assets/ 文件数:", n_ok)
check("解出 assets/ 文件数 > 1590", n_ok > 1590, "实际 %d" % n_ok)
_emj = os.path.join(MP, "assets", "fluent_emoji")
check("存在 assets/fluent_emoji 目录", os.path.isdir(_emj))
check("PNG 数量 = 1592", len(os.listdir(_emj)) == 1592,
      "实际 %d" % len(os.listdir(_emj)))
check("存在 assets/emoji_catalog.json",
      os.path.exists(os.path.join(MP, "assets", "emoji_catalog.json")))

# ── 2. 用真实 emoji.py 的解析逻辑读目录
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

import app.ui.emoji as E

# 把两个路径函数指向模拟的 _MEIPASS
E._emoji_dir = lambda: _emj
E._catalog_path = lambda: os.path.join(MP, "assets", "emoji_catalog.json")

print("\n=== §1 emoji.py 真实解析 catalog ===")
try:
    cat = E.load_catalog()
    check("load_catalog() 不抛异常", True)
except Exception as e:
    cat = {"groups": []}
    check("load_catalog() 不抛异常", False, repr(e))

check("返回 dict 且含 groups 键",
      isinstance(cat, dict) and "groups" in cat)
groups = cat.get("groups", [])
total = sum(len(g.get("emojis", [])) for g in groups) if groups else 0
print("  声明 count:", cat.get("count"), "| 分组数:", len(groups),
      "| 实际条目:", total)
check("声明 count == 1592", cat.get("count") == 1592,
      "实际 %s" % cat.get("count"))
check("分组数 == 10", len(groups) == 10, "实际 %d" % len(groups))
check("拍平后条目 == 1592", total == 1592, "实际 %d" % total)

print("\n=== §2 QPixmap 真实出图（抽检 12 张）===")
all_slugs = [e["slug"] for g in groups for e in g["emojis"]]
sample = all_slugs[::max(1, len(all_slugs) // 12)][:12]
ok, bad = 0, []
for s in sample:
    p = os.path.join(_emj, s + ".png")
    if not os.path.exists(p):
        bad.append((s, "文件不存在"))
        continue
    pm = QPixmap(p)
    if pm.isNull():
        bad.append((s, "QPixmap 为空"))
    elif pm.width() < 32:
        bad.append((s, "尺寸 %d" % pm.width()))
    else:
        ok += 1
check("抽检 12 张 QPixmap 全部有效", ok == 12,
      "有效 %d/12, 问题 %s" % (ok, bad[:3]))

print("\n=== §3 中文名 + 可插入字符 ===")
check("每条都有 cn", all(e.get("cn") for g in groups for e in g["emojis"]))
check("每条都有 char", all(e.get("char") for g in groups for e in g["emojis"]))
cn_names = [E.GROUP_CN.get(g["name"], g["name"]) for g in groups]
print("  分组名（英文 -> 中文）:",
      [(g["name"], c) for g, c in zip(groups, cn_names)])
check("分组名全部映射为中文（10 组）",
      all(any("\u4e00" <= c <= "\u9fff" for c in n) for n in cn_names),
      "未命中: %s" % [g["name"] for g, c in zip(groups, cn_names)
                     if not any("\u4e00" <= x <= "\u9fff" for x in c)])

print("\n=== §4 EmojiPanel 能在模拟冻结环境构建 ===")
from app.ui.theme import resolve_theme
try:
    pnl = E.EmojiPanel(None, resolve_theme("dark"))
    check("EmojiPanel 构造成功", True)
    btns = pnl._tab_btns
    # ★ v1.18.13：分类栏由「顶部文字页签」改为「微信式底部图标条」，
    #   _tab_btns 元素从 (key, btn) 变成 (key, btn, label) 三元组。
    # 11 = 10 个分组 + 1 个「🕘 最近」（RECENT_KEY，设计如此）
    check("分类按钮数量 == 分组数 + 1（含「最近」）",
          len(btns) == len(groups) + 1,
          "%d vs %d+1" % (len(btns), len(groups)))
    labels = [lb for _k, _b, lb in btns]
    print("  分类:", labels)
    check("首个分类是「最近」", "最近" in labels[0], labels[0])
    check("分类文案含中文", all(any("\u4e00" <= c <= "\u9fff" for c in l)
                            for l in labels if l))
    # 图标条：每个分类按钮都应挂上圆形图标（emoji 字符）
    check("分类按钮为图标按钮（有 objectName=EmojiTabIcon）",
          all((b.objectName() or "") == "EmojiTabIcon" for _k, b, _l in btns))
except Exception as e:
    import traceback
    traceback.print_exc()
    check("EmojiPanel 构造成功", False, repr(e))

print("\n" + "=" * 62)
if F:
    print("失败项：")
    for f in F:
        print("  - %s" % f)
print("冻结环境表情加载：通过 %d 项，失败 %d 项" % (len(P), len(F)))
print("=" * 62)
sys.exit(1 if F else 0)
