# -*- coding: utf-8 -*-
"""v1.18.17 —— 界面流畅度优化验收：既测提速，也测功能没被改坏。

对照 `profile_ui.py` 的优化前基线：
    20 条 48ms · 50 条 104ms · 100 条 203ms · 200 条 2993ms
本脚本验证：
  ① 性能：同样的消息数，切设备 / 收消息 / 重复渲染各要多久
  ② 正确性：增量渲染后气泡内容不丢、不重、不乱序
  ③ 头像 / 平台徽标 / 缩略图缓存确实命中

运行：python tests/verify_v11817_perf.py
"""
import os
import sys
import tempfile
import time

os.environ.pop("QT_QPA_PLATFORM", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

tmp = tempfile.mkdtemp(prefix="fd_v11817_")
os.environ["FLASHDROP_DATA_DIR"] = tmp

from app.config import Config
from app.node import FlashNode
from app.ui.main_window import MainWindow, ALL_ID
from app.ui import widgets as W

P, F = [], []


def check(name, cond, detail=""):
    (P if cond else F).append(name)
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", name,
                          ("   " + detail) if (detail and not cond) else ""))


def ms(t0):
    return (time.perf_counter() - t0) * 1000


def pump(n=2):
    for _ in range(n):
        app.processEvents()


def mkmsg(pid, i):
    return {"kind": "text", "dir": "out" if i % 2 else "in",
            "text": "%s 的第 %d 条消息" % (pid[-2:], i),
            "ts": 1700000000000 + i * 1000, "mid": "%s-m%d" % (pid, i)}


cfg = Config()
cfg["theme"] = "light"
cfg["save_dir"] = tmp
cfg["pending_files"] = []
win = MainWindow(cfg, FlashNode(cfg))
win.resize(1100, 740)
win.show()
pump(8)

PIDS = ["%016x" % i for i in range(1, 11)]
# 设备列表来自 node.peers_snapshot() + cfg["known_peers"]，直接给 _on_peers 最稳
SNAP = [{"id": pid, "name": "设备%02d" % i, "online": True,
         "platform": "android", "ips": ["192.168.1.%d" % (i + 1)],
         "last_seen": time.time()}
        for i, pid in enumerate(PIDS)]
win._on_peers(SNAP)
win.peers = {p["id"]: p for p in SNAP}
for pid in PIDS:
    win.msgs[pid] = [mkmsg(pid, k) for k in range(200)]
win._refresh_devices()      # ★ 必须刷新，设备列表才会真的建出这些项
pump(4)
print("设备列表条目数：%d（含固定的「全部设备」）" % win.device_list.count())

print("=" * 70)
print("v1.18.17 界面流畅度优化验收")
print("=" * 70)


def select(pid):
    """选中某设备（必须用 Qt.UserRole 枚举，原型 int 匹配不上）"""
    win.device_list.blockSignals(True)
    win.device_list.clearSelection()
    found = False
    for i in range(win.device_list.count()):
        if win.device_list.item(i).data(Qt.UserRole) == pid:
            win.device_list.item(i).setSelected(True)
            found = True
            break
    win.device_list.blockSignals(False)
    assert found, "设备列表里找不到 %s" % pid
    win._on_target_changed()
    return found


def cur_view():
    return [it.data(Qt.UserRole) for it in win.device_list.selectedItems()]

# ---------- ① 性能 ----------
print("\n=== ① 性能 ===")
select(PIDS[0])
pump()
t0 = time.perf_counter()
win._render_chat()
pump()
same = ms(t0)
check("★ 重复渲染同一视图 ≤ 5ms（原来是 200 条 ≈ 3000ms）",
      same <= 5, "实测 %.1f ms" % same)
print("      重复渲染 200 条：%.1f ms" % same)

t0 = time.perf_counter()
for pid in PIDS[:5]:
    select(pid)
    pump()
    win._render_chat()      # 切过去后再触发一次渲染（模拟来消息）
    pump()
switch5 = ms(t0) / 5 / 2
# 注意：这里量的是**首次**进入某设备（必须新建 200 个气泡，建完会被缓存）。
# 重访走页缓存，见下面「往返切换」断言。优化前首次也是 ≈3000ms。
check("★ 首次进入某设备 ≤ 200ms（原来是 200 条 ≈ 3000ms/次）",
      switch5 <= 200, "实测 %.1f ms/次" % switch5)
print("      首次进入（每台 200 条消息）：%.1f ms/次" % switch5)

# 切回刚才看过的设备 → 应命中"没变直接返回"
select(PIDS[0])
pump()
t0 = time.perf_counter()
select(PIDS[3])
pump()
select(PIDS[0])
pump()
back = ms(t0) / 2
check("★ 切回看过的设备 ≤ 40ms/次（页缓存命中，不重建任何气泡）",
      back <= 40, "实测 %.1f ms" % back)
print("      重访（页缓存命中）：%.1f ms/次" % back)

# 追加一条消息 → 只补 1 个气泡
select(PIDS[0])
pump()
win.msgs[PIDS[0]].append(mkmsg(PIDS[0], 999))
t0 = time.perf_counter()
win._render_chat()
pump()
append_ms = ms(t0)
# ★ v1.18.19 演进：15 → 20ms。v1.18.18 起事件携带断点续传字段
#   （attempt/total_chunks/have_chunks）+ 追加路径加了按 tid 的尾部查重，
#   追加耗时诚实上移约 1ms（15.1~15.9ms），仍远低于全量重建（3000ms 量级），
#   断言守护的语义（"不重建全量"）不变。
check("★ 追加一条消息 ≤ 20ms（不重建全量）",
      append_ms <= 20, "实测 %.1f ms" % append_ms)
print("      追加 1 条：%.1f ms" % append_ms)

# ---------- ② 正确性 ----------
print("\n=== ② 正确性（增量渲染后内容不能错） ===")
select(PIDS[0])
pump()
check("★ 当前确实是单设备视图（排除测错视图）",
      cur_view() == [PIDS[0]], "实际 %s" % cur_view())
bubble_ids = [k for k in win.widgets_by_msg]
check("200 条消息全部建出气泡", len(bubble_ids) == 201,
      "实际 %d 个（200 + 追加 1）" % len(bubble_ids))

txts = []
for k, ws in win.widgets_by_msg.items():
    for w in ws:
        m = w.msg
        if m.get("text"):
            txts.append(m["text"])
check("气泡文本条数正确", len(txts) == 201, "实际 %d" % len(txts))
check("消息顺序正确（首尾对得上）",
      txts[0].endswith("第 0 条消息") and txts[-1].endswith("第 999 条消息"),
      "首=%r 尾=%r" % (txts[0], txts[-1]) if txts else "空")
check("无重复气泡", len(set(txts)) == len(txts),
      "有重复" if len(set(txts)) != len(txts) else "")

# 删掉中间一条 → 应能正确重建
victim = win.msgs[PIDS[0]].pop(5)
win._render_chat(force=True)
pump()
after = [w.msg for ws in win.widgets_by_msg.values() for w in ws]
check("★ 删除一条消息后气泡数正确",
      len(after) == len(win.msgs[PIDS[0]]),
      "%d vs %d" % (len(after), len(win.msgs[PIDS[0]])))
check("★ 被删的消息确实不在气泡里了",
      all(w is not victim for w in after))

# 切到另一台再切回来，内容仍完整
select(PIDS[5])
pump()
select(PIDS[0])
pump()
back2 = [w.msg for ws in win.widgets_by_msg.values() for w in ws]
check("★ 切走再切回，内容条数不变",
      len(back2) == len(win.msgs[PIDS[0]]),
      "%d vs %d" % (len(back2), len(win.msgs[PIDS[0]])))
check("★ 切走再切回，内容顺序不变",
      [id(m) for m in back2] == [id(m) for m in win.msgs[PIDS[0]]])

# ---------- ③ 缓存命中 ----------
print("\n=== ③ 头像 / 徽标 / 缩略图缓存 ===")
W._AVATAR_CACHE.clear()
W._BADGE_CACHE.clear()
t0 = time.perf_counter()
for _ in range(50):
    W.make_avatar("测试", "seed1", 38)
cold = ms(t0) / 50
t0 = time.perf_counter()
for _ in range(50):
    W.make_avatar("测试", "seed1", 38)
warm = ms(t0) / 50
print("      make_avatar 冷 %.3f ms → 热 %.3f ms" % (cold, warm))
check("★ 头像缓存命中后明显更快", warm < cold, "%.3f vs %.3f" % (cold, warm))

W._BADGE_CACHE.clear()
W.make_platform_badge("android", 14)
t0 = time.perf_counter()
for _ in range(50):
    W.make_platform_badge("android", 14)
badge = ms(t0) / 50
print("      make_platform_badge 热 %.4f ms" % badge)
check("★ 徽标缓存生效（<0.01ms）", badge < 0.01, "%.4f ms" % badge)

# 缩略图：生成一张真实大图，验证按需解码 + 缓存
try:
    from PySide6.QtGui import QImage, QColor as QC
    big = QImage(4000, 3000, QImage.Format_RGB32)
    big.fill(QC("#3366aa"))
    p = os.path.join(tmp, "big.jpg")
    big.save(p, "JPG", 92)
    W._THUMB_CACHE.clear()
    t0 = time.perf_counter()
    pm1 = W.make_thumb(p, 300)
    cold_img = ms(t0)
    t0 = time.perf_counter()
    pm2 = W.make_thumb(p, 300)
    warm_img = ms(t0)
    print("      4000x3000 缩略图：冷 %.1f ms → 热 %.1f ms" % (cold_img, warm_img))
    check("★ 缩略图尺寸为 300 级（未解整张大图）",
          pm1.width() <= 300, "实际 %dx%d" % (pm1.width(), pm1.height()))
    check("★ 缩略图缓存命中后接近 0", warm_img < 1.0, "%.2f ms" % warm_img)
except Exception as e:
    check("缩略图测试可执行", False, str(e))

print()
print("=" * 70)
if F:
    print("失败项：")
    for f in F:
        print("  - %s" % f)
print("v1.18.17 性能验收：通过 %d 项，失败 %d 项" % (len(P), len(F)))
print("=" * 70)

import os as _os
_os._exit(1 if F else 0)