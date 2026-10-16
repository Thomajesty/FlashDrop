# -*- coding: utf-8 -*-
"""v1.18.13 —— 把 APK 里的 dex 解出来做字符串级审计（证明 6 项修复真的编译进去）。"""
import os
import shutil
import zipfile

APK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dist", "FlashDrop.apk")
APK = os.path.abspath(APK)
OUT = r"C:/Users/Administrator/AppData/Local/Temp/apkcheck14"

shutil.rmtree(OUT, ignore_errors=True)
os.makedirs(OUT, exist_ok=True)

z = zipfile.ZipFile(APK)
dex_names = [n for n in z.namelist() if n.endswith(".dex")]
for n in dex_names:
    z.extract(n, OUT)

blob = b""
for n in sorted(dex_names):
    p = os.path.join(OUT, n.replace("/", os.sep))
    with open(p, "rb") as f:
        blob += f.read()

print("dex 文件：", dex_names)
print("dex 合计字节：", len(blob))
print()

# 判定用字符串/方法名 —— 只看“是否被编译进 dex”
CHECKS = [
    ("① 安卓 sendTextSync（阻塞等结果）", b"sendTextSync"),
    ("① 安卓 flushPendingSendsAsync（确认式补发）", b"flushPendingSendsAsync"),
    ("① 安卓 schedulePendingRetry（周期重试）", b"schedulePendingRetry"),
    ("② 安卓 imeInsetPx（官方 IME inset 精确高度）", b"imeInsetPx"),
    ("② 安卓 navBarPx（导航栏高度兜底）", b"navBarPx"),
    ("③ 安卓 slidePanelIn（面板整高上推动效）", b"slidePanelIn"),
    ("③ 设备栏槽位常量 DOT_SLOT_DP（22dp）", b"DOT_SLOT_DP"),
    ("③ ✕ 槽位常量 X_SLOT_DP（34dp）", b"X_SLOT_DP"),
    ("③ ✕ 标记 TAG_DELETE_X", b"TAG_DELETE_X"),
    ("④ 文案「全部表情」", "全部表情".encode("utf-8")),
    ("④ 旧文案「其他」应已不在 GROUP_CN", None),  # 反向：见下
    ("⑤ 字段 imeHeightPx", b"imeHeightPx"),
    ("⑤ 方法 watchImeHeight", b"watchImeHeight"),
    ("⑤ 方法 panelHeight", b"panelHeight"),
    ("⑤ 方法 hideImeThen", b"hideImeThen"),
    ("⑤ 方法 hideEmojiPanelThen", b"hideEmojiPanelThen"),
    ("② 方法 updateEmojiIcon", b"updateEmojiIcon"),
    ("① 顶层类 BdTextView（上版回归保持）", b"Lcom/flashdrop/app/BdTextView;"),
]

ok = 0
fail = 0
for label, token in CHECKS:
    if token is None:
        continue
    hit = token in blob
    print(("  PASS  " if hit else "  FAIL  ") + label)
    ok += 1 if hit else 0
    fail += 0 if hit else 1

# ④ 反向：确认 dex 里真的没有旧的“其他”作为分组标签。
# 注意源码里别处也可能出现「其他」字样，所以这里以 UTF-8 编码出现次数作为参考值打印，
# 真正的强断言靠源码级 GROUP_CN 检查（verify_v11815.py §④）。
cnt_qita = blob.count("其他".encode("utf-8"))
cnt_quanbu = blob.count("全部表情".encode("utf-8"))
print("  INFO  dex 内「其他」出现次数 = %d（0 为最理想）" % cnt_qita)
print("  INFO  dex 内「全部表情」出现次数 = %d" % cnt_quanbu)
if cnt_quanbu > 0:
    ok += 1
    print("  PASS  ④ 「全部表情」已进入 dex")
else:
    fail += 1
    print("  FAIL  ④ 「全部表情」未进入 dex")

print()
print("=" * 62)
print("APK dex 审计：通过 %d 项，失败 %d 项" % (ok, fail))
print("=" * 62)
raise SystemExit(1 if fail else 0)
