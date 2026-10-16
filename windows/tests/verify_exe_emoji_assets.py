# -*- coding: utf-8 -*-
"""验证**打包后的 EXE** 能从 sys._MEIPASS 正确读到 Fluent Emoji 资产。

这是表情功能的关键路径：源码运行时走 `windows/assets/`，
打包后走 `<_MEIPASS>/assets/`。smoke_exe.py 只验证进程能起来，
本脚本额外验证 1592 张 PNG + catalog 在冻结环境里真实可读。

做法：用 EXE 自带的 Python 环境不可行（无解释器），
改为解包 EXE 的 CArchive 到临时目录，按 emoji.py 的查找逻辑验证。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

EXE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "dist", "FlashDrop.exe")

from PyInstaller.archive.readers import CArchiveReader

P = []
F = []


def check(name, cond, detail=""):
    (P if cond else F).append(name)
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", name,
                          ("   " + detail) if (detail and not cond) else ""))


print("=" * 62)
print("EXE 内表情资产完整性验收")
print("=" * 62)
print("EXE:", EXE, "%.2f MB" % (os.path.getsize(EXE) / 1024 / 1024))

r = CArchiveReader(EXE)
names = list(r.toc.keys())

png = sorted(n for n in names
             if "fluent_emoji" in n.lower() and n.lower().endswith(".png"))
cat = [n for n in names if n.lower().endswith("emoji_catalog.json")]

print("\n=== §1 归档条目 ===")
check("EXE 内含 fluent_emoji PNG 目录", len(png) > 0, "实际 %d" % len(png))
check("PNG 数量 = 1592", len(png) == 1592, "实际 %d" % len(png))
check("EXE 内含 emoji_catalog.json", len(cat) == 1, "实际 %d" % len(cat))

print("\n=== §2 catalog 可解析 ===")
import json
raw = r.extract(cat[0])
data = json.loads(raw.decode("utf-8"))
check("JSON 合法", isinstance(data, dict))
check("count == 1592", data.get("count") == 1592,
      "实际 %s" % data.get("count"))
groups = data.get("groups", [])
check("分组数 == 10", len(groups) == 10, "实际 %d" % len(groups))

all_slugs = [e["slug"] for g in groups for e in g["emojis"]]
check("拍平后条目 == 1592", len(all_slugs) == 1592, "实际 %d" % len(all_slugs))
check("每条都有 char（可插入）", all(e.get("char") for g in groups
                            for e in g["emojis"]))
check("每条都有中文名 cn", all(e.get("cn") for g in groups
                          for e in g["emojis"]))

print("\n=== §3 slug → EXE 内 PNG 一一对应 ===")
# 归档里的名字形如 assets\fluent_emoji\<slug>.png
have = set()
for n in png:
    base = os.path.basename(n.replace("\\", "/"))
    have.add(base[:-4])   # 去 .png
miss = [s for s in all_slugs if s not in have]
extra = sorted(have - set(all_slugs))
check("全部 slug 都能在 EXE 里找到 PNG（缺失 0）", len(miss) == 0,
      "缺 %d 例: %s" % (len(miss), miss[:5]))
check("EXE 里没有多余 PNG（多余 0）", len(extra) == 0,
      "多 %d 例: %s" % (len(extra), extra[:5]))

print("\n=== §4 PNG 内容真实可读（抽检 8 张）===")
from PIL import Image
import io as _io
sample = all_slugs[::max(1, len(all_slugs) // 8)][:8]
ok = 0
bad = []
for s in sample:
    hit = [n for n in png
           if os.path.basename(n.replace("\\", "/")) == s + ".png"]
    if not hit:
        bad.append((s, "归档内无此文件"))
        continue
    try:
        blob = r.extract(hit[0])
        im = Image.open(_io.BytesIO(blob)).convert("RGBA")
        if im.width >= 32 and im.height >= 32:
            # 必须真的有非透明像素（不是全空图）
            alpha = im.getchannel("A")
            if alpha.getextrema()[1] > 0:
                ok += 1
            else:
                bad.append((s, "全透明"))
        else:
            bad.append((s, "尺寸 %dx%d" % (im.width, im.height)))
    except Exception as e:
        bad.append((s, str(e)))
check("抽检 8 张全部有效（尺寸 >=32 且有可见像素）", ok == 8,
      "有效 %d/8, 问题: %s" % (ok, bad[:3]))

print("\n=== §5 emoji.py 的查找逻辑与归档布局一致 ===")
# emoji.py 里 _emoji_dir() = <base>/assets/fluent_emoji, 文件名 = slug + '.png'
src = open(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "app", "ui", "emoji.py"), encoding="utf-8").read()
check("emoji.py 兼容 sys._MEIPASS", "_MEIPASS" in src)
check("emoji.py 用 assets/fluent_emoji 目录", "fluent_emoji" in src)
check("emoji.py 用 slug + .png 命名", ".png" in src)
check("归档路径前缀确为 assets\\fluent_emoji\\",
      all(n.replace("/", "\\").startswith("assets\\fluent_emoji\\") for n in png))

print("\n" + "=" * 62)
if F:
    print("失败项：")
    for f in F:
        print("  - %s" % f)
print("EXE 表情资产验收：通过 %d 项，失败 %d 项" % (len(P), len(F)))
print("=" * 62)
sys.exit(1 if F else 0)
