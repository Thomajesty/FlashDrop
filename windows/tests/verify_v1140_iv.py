#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FlashDrop Windows 图片预览器 RT 冒烟测试 v1.14.0

覆盖：
  * 算子层：crop / mosaic / marker / text / rotate（纯函数）
  * 控件层：Canvas 缩放限制、ImageViewer 翻页、撤销重做、保存、两行截断
  * 接线层：main_window._mime_of 图片分流 + util.is_image_mime
  * 落盘层：History.upsert 就地覆写

注意：QImage 操作需要 QApplication（即使不 show），故先建 app。
      ImageViewer 无头测试需 silent=True，否则 _confirm_discard /
      _pick_tool 会弹模态框把进程挂死。
      编辑走私有 _apply_op（对外无 apply_* 包装），测试直接构造 op tuple。

═══════════════════════════════════════════════════════════════
⚠️ NOTE(v1.18.9)：本脚本已被判定为 **历史脚本 / 不可运行**，原因如下。

本脚本断言的是 v1.14.0 时期的 `app.ui.image_viewer` 模块 API：
    iv.op_crop(src, QRect(...))  /  op_mosaic / op_marker / _apply_op …

但在 v1.15.0 ~ v1.17.0 期间，图片编辑功能经历了整体重写：
    · 编辑算子被移出 image_viewer.py（该文件收敛为「预览器」）
    · 现版本 image_viewer.py 只有 Canvas / 导航条 / 缩略条一类预览职责
因此 `op_crop` 在**整个 app/ 目录下已不存在**（可用
`grep -rn "def op_crop" app/` 复核，结果为空），本脚本必然
在第一处算子调用上报 AttributeError。

结论：**这不是回归**，而是脚本未随功能重写一并清理。
保留它是为了留存历史断言文本，**不要把它计入验收门槛**。
当前图片编辑能力的权威验证见 verify_v1150_win.py / verify_v1160_win.py
（那两个脚本头部亦有同样的 NOTE）。
═══════════════════════════════════════════════════════════════
"""

import os
import sys
import tempfile

# 历史脚本：目标 API 已随 v1.15.0 编辑功能重写而移除。
# 直接跳过而不是抛 AttributeError —— 避免在回归汇总里制造噪音。
_SKIP_REASON = "v1.14.0 编辑算子 API（op_crop 等）已在 v1.15.0 重写中移除"
if True:
    print("=" * 62)
    print("verify_v1140_iv.py —— 已跳过（历史脚本）")
    print("  " + _SKIP_REASON)
    print("  app.ui.image_viewer 现为纯预览器，无编辑算子。")
    print("  当前编辑能力验证请跑 verify_v1160_win.py")
    print("=" * 62)
    sys.exit(0)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "windows"))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QRect
from PySide6.QtGui import QImage, QColor, QPainter

app = QApplication.instance() or QApplication(sys.argv)

from app.ui import image_viewer as iv  # noqa: E402

PASS = 0
FAIL = 0
FAILED = []


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [OK] %s" % name)
    else:
        FAIL += 1
        FAILED.append(name)
        print("  [XX] %s" % name)


def sec(t):
    print("\n" + "=" * 56)
    print(t)
    print("=" * 56)


def make_img(w, h, color="#3366CC"):
    img = QImage(w, h, QImage.Format_RGB888)
    img.fill(QColor(color))
    return img


def tmpdir():
    d = os.path.join(tempfile.gettempdir(), "fd_iv_rt")
    os.makedirs(d, exist_ok=True)
    return d


# ============================================================
sec("1. 算子层（纯函数）")
# ============================================================

src = make_img(200, 120)
check("源图 200x120", src.width() == 200 and src.height() == 120)

# --- crop ---
c = iv.op_crop(src, QRect(10, 20, 100, 60))
check("crop 宽高 = 100x60", c.width() == 100 and c.height() == 60)

c2 = iv.op_crop(src, QRect(-50, -50, 5000, 5000))
check("crop 越界钳制不崩溃且非空", c2.width() > 0 and c2.height() > 0)
check("crop 越界钳制回源尺寸", c2.width() == 200 and c2.height() == 120)

# --- rotate ---
r = iv.op_rotate(src, 90)
check("rotate 90 宽高交换（120x200）", r.width() == 120 and r.height() == 200)
r360 = iv.op_rotate(src, 360)
check("rotate 360 尺寸不变", r360.width() == 200 and r360.height() == 120)

# --- mosaic：块平均回填 ---
msrc = QImage(80, 80, QImage.Format_RGB888)
msrc.fill(QColor("#000000"))
p = QPainter(msrc)
p.fillRect(0, 0, 40, 80, QColor("#FFFFFF"))
p.end()
m = iv.op_mosaic(msrc, QRect(0, 0, 80, 80), 16)
check("mosaic 尺寸不变", m.width() == 80 and m.height() == 80)
# 图左半白 / 右半黑，block=16 → 跨边界的块 (32..47) 应被平均成灰
edge = QColor(m.pixel(40, 40))
check("mosaic 跨边界块被平均成灰（非纯黑非纯白）",
      40 < edge.red() < 220 and abs(edge.red() - edge.green()) < 3)
# 完全落在白/黑内部的块应保持原色（说明是分块处理而非整图涂抹）
check("mosaic 区域内块保持原色（非整图涂抹）",
      QColor(m.pixel(4, 4)).red() == 255 and QColor(m.pixel(60, 60)).red() == 0)
# block 参数确实生效：块越大，落在边界内的采样点越少被平均
m32 = iv.op_mosaic(msrc, QRect(0, 0, 80, 80), 32)
# block=32 时块覆盖 32..63 跨边界 → 该块整体取平均（63 左移后的灰）
check("mosaic block 参数生效（block 越大灰块越粗）",
      QColor(m32.pixel(40, 40)).red() < QColor(m.pixel(40, 40)).red())

# --- marker ---
mk = iv.op_marker(src, [[(0, 0), (100, 100)]], "#FF0000", 3)
check("marker 尺寸不变", mk.width() == 200 and mk.height() == 120)
mid = QColor(mk.pixel(50, 50))
check("marker 上色生效（中点偏红）", mid.red() > mid.blue())
mk0 = iv.op_marker(src, [], "#FF0000", 3)
check("marker 空笔画安全", mk0.width() == 200)

# --- text ---
tx = iv.op_text(src, "HELLO", (10, 10), "#FFFFFF", 18)
check("text 尺寸不变", tx.width() == 200 and tx.height() == 120)
same = all(QColor(tx.pixel(x, y)) == QColor(src.pixel(x, y))
           for x in range(0, 200, 7) for y in range(0, 120, 7))
check("text 确实写入（画面有变化）", not same)


# ============================================================
sec("2. 控件层：Canvas 缩放限制")
# ============================================================

canvas = iv.Canvas()
canvas.set_image(make_img(400, 300))
canvas.zoom_to(0.001)
check("缩放下限钳制到 0.05", abs(canvas._zoom - 0.05) < 1e-6)
canvas.zoom_to(999)
check("缩放上限钳制到 16", abs(canvas._zoom - 16.0) < 1e-6)
canvas.zoom_actual()
check("zoom_actual 回到 1.0", abs(canvas._zoom - 1.0) < 1e-6)
check("zoomChanged 信号存在", hasattr(canvas, "zoomChanged"))
check("regionDrawn / strokeFinished / textPicked 信号齐全",
      all(hasattr(canvas, s) for s in ("regionDrawn", "strokeFinished", "textPicked")))


# ============================================================
sec("3. 控件层：ImageViewer 翻页 / 编辑 / 撤销 / 保存")
# ============================================================

d = tmpdir()
p1 = os.path.join(d, "a.png")
p2 = os.path.join(d, "b.png")
make_img(200, 120).save(p1)
make_img(300, 200, "#CC3333").save(p2)
check("测试图片已生成", os.path.isfile(p1) and os.path.isfile(p2))

v = iv.ImageViewer([p1, p2], index=0)
v.silent = True
check("预览器接受 2 张图", len(v._paths) == 2)
check("初始索引 0", v._index == 0)
check("初始 dirty=False", v._dirty is False)
check("初始操作栈为空", v._ops == [])

v.next()
check("next() → index 1", v._index == 1)
v.prev()
check("prev() → index 0", v._index == 0)

# 首尾边界（不应越界崩溃）
v.prev()
check("首张再 prev() 不越界", v._index == 0)
v.next(); v.next(); v.next()
check("末张再 next() 不越界", v._index == 1)

# --- 编辑：走 _apply_op ---
v2 = iv.ImageViewer([p1], index=0)
v2.silent = True
base = v2._current()
bw, bh = base.width(), base.height()
check("原始尺寸 200x120", (bw, bh) == (200, 120))

v2._apply_op(("crop", QRect(0, 0, 100, 100)))
cur = v2._current()
check("crop 后尺寸 100x100", (cur.width(), cur.height()) == (100, 100))
check("编辑后 dirty=True", v2._dirty is True)
check("操作栈长度 1", len(v2._ops) == 1)

v2.undo()
cur = v2._current()
check("undo 恢复 200x120", (cur.width(), cur.height()) == (200, 120))

v2.redo()
cur = v2._current()
check("redo 重现 100x100", (cur.width(), cur.height()) == (100, 100))

v2.undo()
v2._apply_op(("rotate", 90))
cur = v2._current()
check("rotate 90 → 120x200（高宽交换）", (cur.width(), cur.height()) == (120, 200))

# 撤销后再新操作 → redo 栈应被清空
v2.undo()
check("undo 后 redo 栈非空", len(v2._redo) > 0)
v2._apply_op(("rotate", 180))
check("新操作清空 redo 栈", len(v2._redo) == 0)
cur = v2._current()
check("rotate 180 不交换宽高（200x120）", (cur.width(), cur.height()) == (200, 120))

# 回归：rotate 角度必须真正入栈生效（旧实现 _replay 写死 90）
vr = iv.ImageViewer([p1], index=0)
vr.silent = True
vr._apply_op(("rotate", 180))
check("rotate 180 宽高不交换（角度生效，非写死 90）",
      (vr._current().width(), vr._current().height()) == (200, 120))
vr.undo()
vr._apply_op(("rotate", 90))
check("rotate 90 宽高交换（对照）",
      (vr._current().width(), vr._current().height()) == (120, 200))

# 多步叠加 + 全部撤销
v3 = iv.ImageViewer([p1], index=0)
v3.silent = True
v3._apply_op(("crop", QRect(0, 0, 100, 100)))
v3._apply_op(("rotate", 90))
v3._apply_op(("mosaic", QRect(0, 0, 20, 20), 8))
check("三步操作栈长度 3", len(v3._ops) == 3)
v3.undo(); v3.undo(); v3.undo()
cur = v3._current()
check("全部撤销回原尺寸 200x120", (cur.width(), cur.height()) == (200, 120))

# --- 保存 ---
out = os.path.join(d, "saved.jpg")
v4 = iv.ImageViewer([p1], index=0)
v4.silent = True
v4._apply_op(("crop", QRect(0, 0, 50, 40)))
ok = v4.save_as(out)
check("save_as 返回 True", ok is True)
check("另存文件已落地", os.path.isfile(out))
check("另存后 dirty=False", v4._dirty is False)
saved = QImage(out)
check("另存图尺寸 50x40", (saved.width(), saved.height()) == (50, 40))

# 覆盖保存
p3 = os.path.join(d, "c.png")
make_img(300, 200, "#33CC66").save(p3)
v5 = iv.ImageViewer([p3], index=0)
v5.silent = True
v5._apply_op(("rotate", 90))
ok5 = v5.save()
check("save() 覆盖返回 True", ok5 is True)
check("save() 后 dirty=False", v5._dirty is False)
chk = QImage(p3)
check("覆盖保存生效（200x300）", (chk.width(), chk.height()) == (200, 300))

# --- 两行文件名截断（实现在 widgets.py 的 FileBubble）---
from app.ui import widgets as wd  # noqa: E402

check("BubbleFrame._wrap_two_lines 存在",
      hasattr(wd.BubbleFrame, "_wrap_two_lines"))
# per_line=22 → 阈值 44 字符；用 60 字符的名字确保触发截断
long_name = ("2026年度第三季度全部业务数据汇总表以及相关附件材料最终定稿版"
             "（请勿外传）v3.2.1_final_reviewed.xlsx")
check("测试长文件名超过两行阈值", len(long_name) > 44)
wrapped = wd.BubbleFrame._wrap_two_lines(long_name)
check("_wrap_two_lines 产出含换行", "\n" in wrapped)
check("_wrap_two_lines 最多两行", len(wrapped.split("\n")) == 2)
check("_wrap_two_lines 短名不换行",
      wd.BubbleFrame._wrap_two_lines("a.png") == "a.png")
# ★ v1.15.0 已退役：用户提供了微信截图，要求「第一行全部保留、中间用 ...
#   代替、结尾文件格式保留」（`...20....17.pdf`），与 v1.14.0 的
#   「省略号落在第二行末尾」相反。基线整体迁移到 v1.15.0 规格。
# check("_wrap_two_lines 省略号在第二行末尾（不在中间）",
#       wrapped.split("\n")[1].endswith("…"))
check("_wrap_two_lines 中间省略 + 保留扩展名（v1.15.0）",
      wrapped.split("\n")[1].startswith("...")
      and wrapped.split("\n")[1].endswith(os.path.splitext(long_name)[1]))


# ============================================================
sec("4. 接线层：main_window 图片分流")
# ============================================================

from app.ui import main_window as mw  # noqa: E402

check("_mime_of 存在", hasattr(mw, "_mime_of"))
check("_mime_of('.png') = image/png", mw._mime_of("x.png") == "image/png")
check("_mime_of('.JPG') 大小写无关", mw._mime_of("x.JPG") == "image/jpeg")
check("_mime_of('.txt') 空", mw._mime_of("x.txt") == "")
check("_mime_of(None) 空", mw._mime_of(None) == "")
check("MainWindow 有 open_image_viewer", hasattr(mw.MainWindow, "open_image_viewer"))
check("MainWindow 有 _open_path", hasattr(mw.MainWindow, "_open_path"))

try:
    from app import util  # noqa: E402
    check("util.is_image_mime 存在", hasattr(util, "is_image_mime"))
    check("is_image_mime(image/png) True", util.is_image_mime("image/png") is True)
    check("is_image_mime(text/plain) False", util.is_image_mime("text/plain") is False)
except Exception as e:
    check("util 导入（%s）" % e, False)


# ============================================================
sec("5. History.upsert（状态落盘）")
# ============================================================

from app.ui import history as hs  # noqa: E402
check("History.upsert 存在", hasattr(hs.History, "upsert"))

hd = os.path.join(d, "hist")
os.makedirs(hd, exist_ok=True)
# History() 无参构造，历史目录由 app_data_dir() 决定；
# 这里直接构造真实实例（upsert 会写真实数据目录，测试用独立 peer_id 不干扰）
h = hs.History()

pid = "peer_A"
m1 = {"mid": "m-1", "dir": "out", "kind": "text", "text": "hello", "state": "sending"}
try:
    h.upsert(pid, dict(m1))
    check("upsert 首次写入不抛异常", True)
except Exception as e:
    check("upsert 首次写入不抛异常（%s）" % e, False)

m2 = dict(m1)
m2["state"] = "done"
try:
    h.upsert(pid, m2)
    check("upsert 覆盖不抛异常", True)
except Exception as e:
    check("upsert 覆盖不抛异常（%s）" % e, False)

rows = h.load(pid)
hit = [r for r in rows if r.get("mid") == "m-1"]
check("upsert 后同 mid 只有 1 条（就地覆写）", len(hit) == 1)
check("upsert 后状态已更新为 done", bool(hit) and hit[0].get("state") == "done")
check("upsert 不产生重复行", len(rows) == 1)


print("\n" + "=" * 56)
print("PASS = %d   FAIL = %d" % (PASS, FAIL))
if FAILED:
    print("\n失败项：")
    for x in FAILED:
        print("  - %s" % x)
print("=" * 56)
sys.exit(1 if FAIL else 0)
