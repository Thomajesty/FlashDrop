# -*- coding: utf-8 -*-
"""v1.17.0 电脑端静态审计 + 离屏渲染验收。

对应本轮与**电脑端**相关的需求：

  [4] 图片右键菜单 & 查看器改造
      · 删除「编辑图片」入口（与「打开」重复）
      · 删除双击打开的图片编辑框（裁剪 → 马赛克 全部移除）
      · 在「另存为」之前新增「其他应用打开…」
      · 上一张 / 下一张 改为图片**左右两侧**悬浮按钮（对齐大厂布局）

跑法（需要 PySide6，故用系统 Python）：
    "C:/Users/Administrator/AppData/Local/Programs/Python/Python312/python.exe" \
        windows/tests/verify_v1170_win.py
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WIN = os.path.join(ROOT, "windows")
APP = os.path.join(WIN, "app")

pass_n = 0
fail_n = 0
_fails = []


def check(name, cond, detail=""):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print(f"  [PASS] {name}")
    else:
        fail_n += 1
        _fails.append(name)
        print(f"  [FAIL] {name}  {detail}")


def rd(p):
    with io.open(p, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


WDG = rd(os.path.join(APP, "ui", "widgets.py"))
MW = rd(os.path.join(APP, "ui", "main_window.py"))
IV = rd(os.path.join(APP, "ui", "image_viewer.py"))
INIT = rd(os.path.join(APP, "__init__.py"))

print("=" * 72)
print("v1.17.0 电脑端静态审计")
print("=" * 72)

# ---------------------------------------------------------------- 版本
print("\n【版本】")
check("__version__ 存在（>=1.18.0）", "__version__ = " in INIT and "1.18." in INIT)

# --------------------------------------------- [4-a] 右键菜单去重
print("\n【需求4-a：右键菜单删除「编辑图片」入口】")
check("菜单不再有「编辑图片（裁剪 / 标记 / 马赛克 / 文字）」项",
      "编辑图片（裁剪 / 标记 / 马赛克 / 文字）" not in WDG)
check("不再声明 act_edit_image 变量",
      "act_edit_image = m.addAction" not in WDG)
check("不再派发 editImageRequested",
      "self.editImageRequested.emit(" not in WDG)
check("editImageRequested 信号保留为兼容位（防外部 ImportError）",
      "editImageRequested = Signal(str)" in WDG)
check("main_window 不再 connect editImageRequested",
      "w.editImageRequested.connect" not in MW)

# --------------------------------------------- [4-b] 其他应用打开
print("\n【需求4-b：「另存为」前新增「其他应用打开…」】")
check("新增 openWithRequested 信号",
      "openWithRequested = Signal(str)" in WDG)
check("菜单含「其他应用打开…」项",
      'act_open_with = m.addAction("其他应用打开…")' in WDG)
check("菜单含「复制图片」项", 'act_copy_image = m.addAction("复制图片")' in WDG)
check("菜单含「图片另存为…」项",
      'act_saveas_image = m.addAction("图片另存为…")' in WDG)
# 顺序断言：复制图片 < 其他应用打开 < 图片另存为
_i_copy = WDG.index('act_copy_image = m.addAction("复制图片")')
_i_openw = WDG.index('act_open_with = m.addAction("其他应用打开…")')
_i_saveas = WDG.index('act_saveas_image = m.addAction("图片另存为…")')
check("菜单顺序 = 复制图片 → 其他应用打开… → 图片另存为…",
      _i_copy < _i_openw < _i_saveas,
      f"({_i_copy}, {_i_openw}, {_i_saveas})")
check("派发 openWithRequested",
      "self.openWithRequested.emit(self._openable_path())" in WDG)
check("main_window 实现 _open_image_with()",
      "def _open_image_with(self, path):" in MW)
check("_open_image_with 调用系统「打开方式」(OpenAs_RunDLL)",
      "shell32.dll,OpenAs_RunDLL" in MW)
check("main_window 连接 openWithRequested",
      "w.openWithRequested.connect(self._open_image_with)" in MW)

# --------------------------------------------- [4-c] 删除编辑器
print("\n【需求4-c：删除双击打开的图片编辑框（含裁剪→马赛克）】")
# 注意：只断言**可执行代码**里没有这些能力，不误伤说明性注释
IV_CODE = re.sub(r'"""[\s\S]*?"""', "", IV)      # 去掉模块 docstring
IV_CODE = re.sub(r"(?m)^\s*#.*$", "", IV_CODE)   # 去掉行注释
for bad in ("def open_image_editor", "def op_crop", "def op_mosaic",
            "def op_marker", "def op_text", "def op_rotate",
            "_apply_crop", "_apply_mosaic", "TOOL_CROP", "TOOL_MOSAIC",
            "TOOL_MARKER", "TOOL_TEXT", "应用裁剪", "应用马赛克",
            "def undo", "def redo", "edit_done"):
    check(f"image_viewer 代码中已无 {bad}", bad not in IV_CODE)
check("main_window 已移除 open_image_editor",
      "def open_image_editor" not in MW)
check("_open_path 不再进内置查看器（改交系统默认程序）",
      "self.open_image_viewer(path)" not in MW.split("def _open_path")[1]
      .split("def ")[0])
check("_open_path 使用 QDesktopServices.openUrl",
      "QDesktopServices.openUrl(QUrl.fromLocalFile(path))" in MW)
check("截图提示语不再提「编辑图片」",
      "可右键「编辑图片」标注后发送" not in MW)
check("图片 tooltip 不再提「编辑」",
      "右键可编辑 / 复制 / 另存为" not in WDG)

# --------------------------------------------- [4-d] 左右悬浮翻页
print("\n【需求4-d：上一张/下一张改为图片左右两侧悬浮按钮】")
check("新增 NavButton 类（半透明圆形）",
      "class NavButton(QToolButton):" in IV)
check("NavButton 有 hover / disabled 态样式",
      "QToolButton:hover {" in IV and "QToolButton:disabled {" in IV
      and "border-radius: 23px;" in IV)
check("查看器创建 btn_prev / btn_next",
      'self.btn_prev = NavButton("‹"' in IV
      and 'self.btn_next = NavButton("›"' in IV)
check("两个按钮 parent 为画布所在 stage（可悬浮）",
      "self.btn_prev = NavButton(\"‹\", \"上一张 (←)\", stage)" in IV
      and "self.btn_next = NavButton(\"›\", \"下一张 (→)\", stage)" in IV)
check("新增 _place_nav() 做左右定位",
      "def _place_nav(self):" in IV)
check("_place_nav 左侧贴左、右侧贴右、垂直居中",
      "cy = (c.height() - self.btn_prev.height()) // 2" in IV
      and "self.btn_next.move(" in IV
      and "max(0, c.width() - self.btn_next.width() - m)" in IV)
check("resizeEvent 重新摆放按钮",
      "def resizeEvent(self, e):" in IV and "self._place_nav()" in IV)
check("showEvent 首次也摆放按钮",
      "QTimer.singleShot(0, self._place_nav)" in IV)
check("按钮通过 raise_() 浮在画布之上",
      "self.btn_prev.raise_()" in IV and "self.btn_next.raise_()" in IV)
check("顶部工具栏**不再**放上一张/下一张",
      "◀ 上一张" not in IV and "下一张 ▶" not in IV)
check("首/末张时按钮禁用且降透明度",
      "self.btn_prev.setEnabled(has_prev)" in IV
      and "self.btn_prev.set_opacity(0.55 if has_prev else 0.25)" in IV)
check("默认 55% 不透明度（不抢视线）",
      "self.btn_prev.set_opacity(0.55)" in IV)
check("透明度走 QGraphicsOpacityEffect（子控件专用，非 setWindowOpacity）",
      "QGraphicsOpacityEffect" in IV and "def set_opacity(self, v: float):" in IV)
check("不再使用对子控件无效的 setWindowOpacity",
      "setWindowOpacity(" not in IV_CODE)

# --------------------------------------------- [2] 卡片加长（桌面端）
print("\n【需求2（桌面端）：文件卡片加长到与微信一致】")
check("FILE_CARD_W 由 322 提到 344", "FILE_CARD_W = 344" in WDG)
check("旧值 322 已不再作为卡片宽", "FILE_CARD_W = 322" not in WDG)
check("文字区常量随之变宽（344-12*2-14-40 = 266）",
      "FILE_CARD_TEXT_W = (FILE_CARD_W - FILE_CARD_PAD * 2" in WDG)
check("卡片仍固定宽度（非自适应）",
      "card.setFixedWidth(self.FILE_CARD_W)" in WDG)
check("图标仍 40x52", "FILE_ICON_W = 40" in WDG and "FILE_ICON_H = 52" in WDG)

# --------------------------------------------- 保留能力
print("\n【回归：浏览能力必须保留】")
for keep in ("缩放", "适应窗口", "1:1", "旋转", "复制", "另存为",
             "在文件夹中显示"):
    check(f"保留「{keep}」", keep in IV)
check("保留滚轮缩放", "def wheelEvent" in IV)
check("保留拖拽平移", "self._panning = True" in IV)
check("保留键盘 ←/→ 翻页", "if k in (Qt.Key_Left, Qt.Key_PageUp):" in IV)
check("保留 Ctrl+S 另存为", "self.save_as()" in IV)
check("保留 Ctrl+C 复制", "self.copy_to_clipboard()" in IV)
check("画布双击在适应/1:1 间切换（对齐 Windows 照片）",
      "def mouseDoubleClickEvent" in IV and "self.zoom_actual()" in IV)
check("save_as 返回 bool 契约", "def save_as(self, target=None) -> bool:" in IV)
check("silent 模式跳过阻塞对话框（供自动化）",
      "self.silent = silent" in IV and "if not path:" in IV)

# ---------------------------------------------------------------- 运行期
print("\n【运行期：真实导入 + 离屏渲染】")
OUT = os.path.join(HERE, "_out_v1170")
os.makedirs(OUT, exist_ok=True)

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, WIN)
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QImage, QColor, QPainter, QPixmap
    from PySide6.QtCore import Qt, QPoint

    _app = QApplication.instance() or QApplication([])

    from app.ui.image_viewer import ImageViewer, NavButton, Canvas

    # 造 3 张测试图
    paths = []
    for i, col in enumerate(("#E8453C", "#217346", "#3B82F6")):
        img = QImage(640, 400, QImage.Format_ARGB32)
        img.fill(QColor(col))
        p = os.path.join(OUT, f"test_{i}.png")
        img.save(p)
        paths.append(p)
    check("测试图生成", len(paths) == 3 and all(os.path.isfile(p) for p in paths))

    v = ImageViewer(paths, 1, None, silent=True)
    v.resize(1000, 640)
    v.show()
    _app.processEvents()
    v._place_nav()
    _app.processEvents()

    check("查看器可实例化", v is not None)
    check("标题显示当前序号",
          "第 2/3 张" in v.lbl_title.text(), v.lbl_title.text())
    check("左右按钮都在画布内（x 合法）",
          0 <= v.btn_prev.x() < v.canvas.width()
          and 0 <= v.btn_next.x() < v.canvas.width(),
          f"prev.x={v.btn_prev.x()} next.x={v.btn_next.x()} w={v.canvas.width()}")
    check("左按钮贴左（x < 宽度的 20%）",
          v.btn_prev.x() < v.canvas.width() * 0.2,
          f"x={v.btn_prev.x()}")
    check("右按钮贴右（右边缘距画布右 < 20%）",
          (v.canvas.width() - (v.btn_next.x() + v.btn_next.width()))
          < v.canvas.width() * 0.2,
          f"gap={v.canvas.width() - (v.btn_next.x() + v.btn_next.width())}")
    check("两按钮垂直居中对齐（y 相同）",
          abs(v.btn_prev.y() - v.btn_next.y()) <= 2,
          f"prev.y={v.btn_prev.y()} next.y={v.btn_next.y()}")
    check("两按钮都在画布垂直中点附近",
          abs(v.btn_prev.y() + v.btn_prev.height() / 2
              - v.canvas.height() / 2) < v.canvas.height() * 0.2,
          f"cy={v.btn_prev.y() + v.btn_prev.height() / 2} "
          f"canvas_h={v.canvas.height()}")
    check("按钮尺寸为 46x46",
          v.btn_prev.width() == 46 and v.btn_prev.height() == 46)
    check("中间张时左右按钮均可用",
          v.btn_prev.isEnabled() and v.btn_next.isEnabled())
    check("默认透明度 55%",
          abs(v.btn_prev.opacity() - 0.55) < 0.01,
          str(v.btn_prev.opacity()))

    # 翻到首张 → prev 禁用
    v._load(0)
    _app.processEvents()
    check("首张时「上一张」禁用", not v.btn_prev.isEnabled())
    check("首张时「下一张」可用", v.btn_next.isEnabled())
    check("禁用按钮透明度降到 25%",
          abs(v.btn_prev.opacity() - 0.25) < 0.01,
          str(v.btn_prev.opacity()))

    # 翻到末张 → next 禁用
    v._load(2)
    _app.processEvents()
    check("末张时「下一张」禁用", not v.btn_next.isEnabled())
    check("末张时「上一张」可用", v.btn_prev.isEnabled())

    # 缩放 / 适应 / 1:1
    v.canvas.zoom_actual()
    check("1:1 缩放 = 100%", "100%" in v.lbl_zoom.text(), v.lbl_zoom.text())
    v.canvas.zoom_to(1.25)
    check("放大后百分比上升", "125%" in v.lbl_zoom.text(), v.lbl_zoom.text())
    v.canvas.fit()
    _app.processEvents()
    check("适应窗口后百分比有值", "%" in v.lbl_zoom.text())

    # 另存为（走 target 直存，不弹框）
    dst = os.path.join(OUT, "saved_copy.png")
    if os.path.exists(dst):
        os.remove(dst)
    ok = v.save_as(dst)
    check("另存为成功写出文件", ok and os.path.isfile(dst))
    check("另存为不修改原文件", os.path.isfile(paths[2]))

    # 整窗截图
    _app.processEvents()
    shot = v.grab()
    shot.save(os.path.join(OUT, "viewer_with_nav.png"))
    check("查看器截图已生成（含左右悬浮按钮）",
          os.path.isfile(os.path.join(OUT, "viewer_with_nav.png")))

    # 菜单结构静态复现（不依赖真实 msg 队列）
    check("菜单不再含「编辑」字样项",
          re.search(r'addAction\("编辑', WDG) is None)

    v.close()
except Exception as e:
    import traceback
    traceback.print_exc()
    check(f"运行期无异常（{type(e).__name__}: {e}）", False)

# ---------------------------------------------------------------- 汇总
print("\n" + "=" * 72)
print(f"结果：{pass_n} 通过 / {fail_n} 失败")
if _fails:
    print("失败项：")
    for f in _fails:
        print("  · " + f)
print("=" * 72)
sys.exit(1 if fail_n else 0)
