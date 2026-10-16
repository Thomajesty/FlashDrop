# -*- coding: utf-8 -*-
"""v1.18.0 截图取景器运行时验证（离屏，无需真实桌面交互）

验证目标（用户需求 1：截图应能框选 + 带下拉三角选择是否隐藏窗口）：
  §1  SnipOverlay 能被子类化成"自动拖动"版本并真的裁出正确区域
  §2  单击（未拖动）视为取消，不产生 1x1 垃圾图
  §3  Esc 取消
  §4  Shift 锁正方形
  §5  多屏拼接 grab_virtual_desktop 能返回并集尺寸
  §6  主窗口侧：截图按钮带 QToolButton 下拉三角 + 菜单两项 + 勾选态
  §7  配置项 snip_hide_self 默认 True 且能持久化
"""
import os
import re
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt, QRect, QPoint, QEvent
from PySide6.QtGui import QPixmap, QColor, QMouseEvent, QKeyEvent
from PySide6.QtWidgets import QApplication, QToolButton, QMenu

app = QApplication.instance() or QApplication([])

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


def sec(t):
    print(f"\n=== {t} ===")


from app.ui.snip import SnipOverlay, region_from_canvas, grab_virtual_desktop, MASK, ACCENT


def make_canvas(w=800, h=600, color=0xFF204060):
    pm = QPixmap(w, h)
    pm.fill(QColor(color))
    return pm


class AutoSnip(SnipOverlay):
    """把"人手拖动"替换成程序化事件，便于离屏跑。"""

    def drag(self, x1, y1, x2, y2, shift=False):
        p1 = QPoint(x1, y1)
        p2 = QPoint(x2, y2)
        mods = Qt.ShiftModifier if shift else Qt.NoModifier
        self.mousePressEvent(QMouseEvent(
            QEvent.MouseButtonPress, p1, self.mapToGlobal(p1),
            Qt.LeftButton, Qt.LeftButton, mods))
        self.mouseMoveEvent(QMouseEvent(
            QEvent.MouseMove, p2, self.mapToGlobal(p2),
            Qt.NoButton, Qt.LeftButton, mods))
        self.mouseReleaseEvent(QMouseEvent(
            QEvent.MouseButtonRelease, p2, self.mapToGlobal(p2),
            Qt.LeftButton, Qt.NoButton, mods))


# ─────────────────────────────────────────────────────────
sec("§1 框选：拖动后裁出正确区域")
c1 = make_canvas(800, 600)
ov = AutoSnip(c1)
got = []
ov.picked.connect(lambda r: got.append(r))
ov.show()
ov.drag(100, 80, 500, 380)
check("picked 被触发一次", len(got) == 1, f"got={got}")
if got:
    r = got[0]
    check("选区宽=400", r.width() == 400, f"w={r.width()}")
    check("选区高=300", r.height() == 300, f"h={r.height()}")
    sub, grect = region_from_canvas(c1, r, QPoint(0, 0))
    check("裁剪图宽=400", sub.width() == 400, f"w={sub.width()}")
    check("裁剪图高=300", sub.height() == 300, f"h={sub.height()}")
    check("裁剪图非空", not sub.isNull())
    check("global_rect 正确", grect == QRect(100, 80, 400, 300), f"{grect}")
    # 像素校验：裁出来的图应与源同色
    img = sub.toImage()
    check("裁剪像素取自源画布",
          QColor(img.pixel(10, 10)).rgb() == QColor(0xFF204060).rgb(),
          f"{QColor(img.pixel(10,10)).name()}")

# 反向拖动（右下往左上）也应得到正的矩形
sec("§1b 反向拖动仍得到规范化矩形")
c1b = make_canvas(800, 600)
ov1b = AutoSnip(c1b)
got1b = []
ov1b.picked.connect(lambda r: got1b.append(r))
ov1b.show()
ov1b.drag(500, 380, 100, 80)
check("反向拖动触发 picked", len(got1b) == 1)
if got1b:
    r = got1b[0]
    check("反向拖动宽=400", r.width() == 400, f"w={r.width()}")
    check("反向拖动高=300", r.height() == 300, f"h={r.height()}")

# ─────────────────────────────────────────────────────────
sec("§2 单击（未拖动）→ 取消，不产生垃圾图")
c2 = make_canvas(800, 600)
ov2 = AutoSnip(c2)
picked2 = []
canc2 = []
ov2.picked.connect(lambda r: picked2.append(r))
ov2.cancelled.connect(lambda: canc2.append(1))
ov2.show()
ov2.drag(300, 300, 300, 300)
check("单击不产生 picked", len(picked2) == 0, f"{picked2}")
check("单击触发 cancelled", len(canc2) == 1, f"{canc2}")

sec("§2b 微小拖动（<8px）→ 取消")
c2b = make_canvas(800, 600)
ov2b = AutoSnip(c2b)
picked2b, canc2b = [], []
ov2b.picked.connect(lambda r: picked2b.append(r))
ov2b.cancelled.connect(lambda: canc2b.append(1))
ov2b.show()
ov2b.drag(100, 100, 103, 102)
check("3x2 选区被丢弃", len(picked2b) == 0, f"{picked2b}")
check("触发 cancelled", len(canc2b) == 1)

# ─────────────────────────────────────────────────────────
sec("§3 Esc 取消")
c3 = make_canvas(800, 600)
ov3 = AutoSnip(c3)
canc3 = []
ov3.cancelled.connect(lambda: canc3.append(1))
ov3.show()
ov3.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
check("Esc 触发 cancelled", len(canc3) == 1, f"{canc3}")

sec("§3b 右键取消")
c3b = make_canvas(800, 600)
ov3b = AutoSnip(c3b)
canc3b = []
ov3b.cancelled.connect(lambda: canc3b.append(1))
ov3b.show()
p = QPoint(400, 400)
ov3b.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, p,
                                 ov3b.mapToGlobal(p), Qt.RightButton,
                                 Qt.RightButton, Qt.NoModifier))
check("右键触发 cancelled", len(canc3b) == 1, f"{canc3b}")

# ─────────────────────────────────────────────────────────
sec("§4 Shift 锁正方形")
c4 = make_canvas(800, 600)
ov4 = AutoSnip(c4)
got4 = []
ov4.picked.connect(lambda r: got4.append(r))
ov4.show()
ov4.drag(100, 100, 500, 250, shift=True)   # 400x150 -> 应锁成 150x150
check("Shift 触发 picked", len(got4) == 1)
if got4:
    r = got4[0]
    check("锁成正方形", r.width() == r.height(), f"{r.width()}x{r.height()}")
    check("边长=150", r.width() == 150, f"side={r.width()}")

# ─────────────────────────────────────────────────────────
sec("§5 grab_virtual_desktop 多屏并集")
canvas, origin = grab_virtual_desktop()
check("返回非空 pixmap", not canvas.isNull())
check("画布宽>0", canvas.width() > 0, f"w={canvas.width()}")
check("origin 是 QPoint", isinstance(origin, QPoint))
screens = QApplication.screens()
exp_w = int(sum(s.geometry().width() for s in screens))
check("画布宽≈各屏宽之和(或并集)",
      canvas.width() > 0 and canvas.width() >= max(s.geometry().width()
                                                   for s in screens),
      f"canvas={canvas.width()} screen_max="
      f"{max(s.geometry().width() for s in screens)}")

# ─────────────────────────────────────────────────────────
sec("§6 主窗口截图按钮：下拉三角 + 菜单")
import inspect
from app.ui import main_window as MW

src = inspect.getsource(MW)
check("使用 QToolButton 实现组合按钮", "QToolButton()" in src)
check("截图按钮文本 '✂ 截图'", '"✂ 截图"' in src)
check("存在下拉三角字符 ▾", '"▾"' in src)
check("setPopupMode(InstantPopup)", "QToolButton.InstantPopup" in src)
check("菜单在弹出前重建", "aboutToShow.connect(_fill_shot_menu)" in src)
check("菜单含'隐藏当前窗口'", '"截图时隐藏当前窗口"' in src)
check("菜单含'保留当前窗口'", '"截图时保留当前窗口"' in src)
check("两项均为 checkable", src.count("setCheckable(True)") >= 2)
check("勾选态绑定 _snip_hide_self", "a_hide.setChecked(self._snip_hide_self)" in src)
check("有 _remember_snip_hide 持久化", "def _remember_snip_hide" in src)
check("主按钮连到 _screenshot", "shot_btn.clicked.connect(self._screenshot)" in src)

sec("§6b 主入口走框选（不再整屏直抓）")
check("_screenshot 转调 _start_snip", "self._start_snip(hide_self=self._snip_hide_self)" in src)
check("存在 _start_snip", "def _start_snip" in src)
check("存在 _save_shot", "def _save_shot" in src)
check("旧 _capture_screen 已移除", "def _capture_screen" not in src)
check("导入 SnipOverlay", "SnipOverlay" in src)
check("导入 grab_virtual_desktop", "grab_virtual_desktop" in src)
check("导入 region_from_canvas", "region_from_canvas" in src)
check("hide_self=True 先 hide()", "self.hide()" in src)
check("hide_self 分支存在", "if hide_self and was_visible:" in src)
check("保留窗口时不 hide", "QTimer.singleShot(60, do_capture)" in src)
check("持住 overlay 防 GC", "self._snip_overlay = ov" in src)
check("toast 带分辨率", "已截图 {pixmap.width()}×{pixmap.height()}" in src)

# ─────────────────────────────────────────────────────────
sec("§7 配置项 snip_hide_self")
from app.config import DEFAULTS
check("DEFAULTS 含 snip_hide_self", "snip_hide_self" in DEFAULTS)
check("默认值 True（与旧行为一致）", DEFAULTS.get("snip_hide_self") is True)

# 用临时目录跑一次真实持久化
import tempfile, json
tmpd = tempfile.mkdtemp(prefix="fd_cfg_")
os.environ["FLASHDROP_DATA_DIR"] = tmpd
for m in [k for k in list(sys.modules) if k.startswith("app.config")]:
    del sys.modules[m]
from app.config import Config
cfg = Config()
check("新配置默认 True", cfg["snip_hide_self"] is True)
cfg["snip_hide_self"] = False
cfg.save()
cfg2 = Config()
check("False 能持久化并读回", cfg2["snip_hide_self"] is False,
      f"{cfg2['snip_hide_self']}")
raw = json.load(open(cfg2.path, encoding="utf-8"))
check("落盘 JSON 含该键且为 false", raw.get("snip_hide_self") is False,
      f"{raw.get('snip_hide_self')}")

# ─────────────────────────────────────────────────────────
sec("§7b ★ 崩溃回归：Config 没有 .get()（v1.18.0 首包事故）")
#
# 事故经过：首版 v1.18.0 的 EXE 一启动就抛
#   AttributeError: 'Config' object has no attribute 'get'
# 原因是 MainWindow.__init__ 里写了 cfg 的点号 get 调用。
# Config 只实现了 __getitem__ / __setitem__，**没有** dict 的 .get()，
# 而离屏单测当时只检查了 snip.py 的源码字符串，从未真正构造 MainWindow，
# 所以漏网。本节改为**真实构造 MainWindow**，从根上堵住"接口用错"。
#
# 注意：本节用独立临时目录另起一份 Config，避免受 §7 已写入的 False 影响。
import shutil as _shutil
_iso = tempfile.mkdtemp(prefix="fd_iso_")
_prev_data = os.environ.get("FLASHDROP_DATA_DIR")
os.environ["FLASHDROP_DATA_DIR"] = _iso

_mw_src_raw = inspect.getsource(MW.MainWindow)
# 去掉注释后再查，避免把"说明为什么不能用 cfg.get"的注释误判成调用。
# 注意：只在 **cfg 这个 Config 对象** 上查 —— m/e/entry/self.msgs 等
# 都是真 dict，用 .get() 完全正常，不能一刀切。
_mw_src = re.sub(r"#[^\n]*", "", _mw_src_raw)
_cfg_get_hits = [ln.strip() for ln in _mw_src.split("\n")
                 if re.search(r"self\.cfg\.get\(|(?<![\w.])cfg\.get\(", ln)]
check("MainWindow 源码没有对 Config 对象调用 .get()",
      not _cfg_get_hits, f"命中: {_cfg_get_hits}")

try:
    from app.config import Config as _Cfg
    from app.node import FlashNode as _Node
    _cfg = _Cfg()
    check("全新配置默认 snip_hide_self = True",
          _cfg["snip_hide_self"] is True, f"{_cfg['snip_hide_self']}")
    _w = MW.MainWindow(_cfg, _Node(_cfg))
    _built = True
    _err = ""
except Exception as e:
    _built = False
    _err = f"{type(e).__name__}: {e}"
check("真实构造 MainWindow 不抛异常（复现原崩溃）", _built, _err)
if _built:
    check("默认 _snip_hide_self = True",
          _w._snip_hide_self is True, f"{_w._snip_hide_self}")

    # 老配置文件（缺 snip_hide_self 键）也要能起来
    import json as _json
    _d = _json.load(open(_cfg.path, encoding="utf-8"))
    _d.pop("snip_hide_self", None)
    _json.dump(_d, open(_cfg.path, "w", encoding="utf-8"), ensure_ascii=False)
    try:
        _cfg2 = _Cfg()
        _w2 = MW.MainWindow(_cfg2, _Node(_cfg2))
        _ok2 = True
        _err2 = ""
    except Exception as e:
        _ok2 = False
        _err2 = f"{type(e).__name__}: {e}"
    check("老配置（缺该键）仍能启动并回落 True", _ok2, _err2)
    if _ok2:
        check("老配置回落值 = True（沿用旧行为）",
              _w2._snip_hide_self is True, f"{_w2._snip_hide_self}")
        _w2.close()

    # False 也要能读回
    _cfg["snip_hide_self"] = False
    _cfg.save()
    _cfg3 = _Cfg()
    _w3 = MW.MainWindow(_cfg3, _Node(_cfg3))
    check("显式 False 能读回并生效",
          _w3._snip_hide_self is False, f"{_w3._snip_hide_self}")
    _w3.close()
    _w.close()

check("_snip_hide_self 初始化有 KeyError/TypeError 兜底",
      "except (KeyError, TypeError):" in _mw_src_raw)

# 恢复环境变量并清理
if _prev_data is None:
    os.environ.pop("FLASHDROP_DATA_DIR", None)
else:
    os.environ["FLASHDROP_DATA_DIR"] = _prev_data
_shutil.rmtree(_iso, ignore_errors=True)

# ─────────────────────────────────────────────────────────
sec("§8 snip.py 设计约束")
import app.ui.snip as SN
snip_src = inspect.getsource(SN)
check("暗罩用 45%± 黑", "QColor(0, 0, 0, 130)" in snip_src)
check("十字光标", "Qt.CrossCursor" in snip_src)
check("置顶无边框", "Qt.WindowStaysOnTopHint" in snip_src)
check("覆盖虚拟桌面并集", "united(s.geometry())" in snip_src)
check("逐屏拼接（多显示器）", "for s in QGuiApplication.screens()" in snip_src)
check("处理 devicePixelRatio", "devicePixelRatio" in snip_src)
check("四角把手绘制", "arm = 14" in snip_src)
check("尺寸标签绘制", "_draw_size_tag" in snip_src)
check("矩形规范化 sorted", "sorted((a.x(), b.x()))" in snip_src)
check("WA_DeleteOnClose", "WA_DeleteOnClose" in snip_src)

# ─────────────────────────────────────────────────────────
print(f"\n{'='*56}")
print(f"v1.18.0 截图功能验证：通过 {PASS} 项，失败 {FAIL} 项")
if FAILS:
    print("失败项：")
    for f in FAILS:
        print("  -", f)
print("=" * 56)
sys.exit(1 if FAIL else 0)
