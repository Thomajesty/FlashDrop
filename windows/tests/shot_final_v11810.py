# -*- coding: utf-8 -*-
"""v1.18.10 交付截图：把表情面板作为普通子控件渲染（非 Qt.Popup），
   避免顶层窗口在 grab() 下的中文豆腐块伪影，得到干净的验收截图。

产出（tests/）：
  final_panel_dark.png   / final_panel_light.png    —— 表情面板本体
  final_bar_dark.png     / final_bar_light.png      —— 底部工具行（验证按钮顺序）
"""
import os
import sys

os.environ.pop("QT_QPA_PLATFORM", None)
os.environ.setdefault("QT_LOGGING_RULES", "*=false")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tempfile

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout

app = QApplication.instance() or QApplication([])

tmp = tempfile.mkdtemp(prefix="fd_final_")
os.environ["FLASHDROP_DATA_DIR"] = tmp

OUT = os.path.dirname(os.path.abspath(__file__))

# 全局字体：确保与主窗口一致（微软雅黑 UI）
f = QFont("Microsoft YaHei UI")
f.setPixelSize(13)
app.setFont(f)

from app.ui.emoji import EmojiPanel
from app.ui.theme import resolve_theme

theme_name = sys.argv[1] if len(sys.argv) > 1 else "dark"
theme = resolve_theme(theme_name)


def build_panel():
    """把面板放到一个普通 QWidget 里（非 Popup），这样 grab() 走正常合成路径。"""
    host = QWidget()
    host.setAttribute(Qt.WA_DontShowOnScreen, False)
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    pnl = EmojiPanel(host, theme)
    pnl.setWindowFlags(Qt.Widget)          # ★ 关键：降级为普通控件
    pnl.setParent(host)
    lay.addWidget(pnl)
    host.resize(pnl.width(), pnl.height())
    return host, pnl


state = {"n": 0}


def step():
    state["n"] += 1
    n = state["n"]

    if n == 1:
        host, pnl = build_panel()
        host.show()
        for _ in range(12):
            app.processEvents()
        pm = host.grab()
        path = os.path.join(OUT, "final_panel_%s.png" % theme_name)
        pm.save(path)
        print("  panel:", pm.width(), "x", pm.height(), "->", path)
        print("  tabs:", [b.text() for _k, b in pnl._tab_btns][:12])
        host.hide()
        state["host"] = host
        QTimer.singleShot(250, step)
        return

    if n == 2:
        # 工具行截图：从主窗口里把 tools 行单独抓出来
        from app.config import Config
        from app.node import FlashNode
        from app.ui.main_window import MainWindow
        cfg = Config()
        cfg["theme"] = theme_name
        cfg["save_dir"] = tmp
        win = MainWindow(cfg, FlashNode(cfg))
        win.resize(1100, 740)
        win.show()
        for _ in range(14):
            app.processEvents()
        bar = win.emoji_btn.parentWidget()
        pm = bar.grab()
        path = os.path.join(OUT, "final_bar_%s.png" % theme_name)
        pm.save(path)
        print("  bar:", pm.width(), "x", pm.height(), "->", path)
        # 打印按钮顺序（验收要点：表情 在 发送文件 之前）
        btns = []
        for i in range(bar.layout().count()):
            w = bar.layout().itemAt(i).widget()
            if w is None:
                continue
            t = getattr(w, "text", lambda: "")()
            btns.append(t or type(w).__name__)
        print("  bar order:", btns)
        state["win"] = win
        QTimer.singleShot(250, step)
        return

    print("done")
    if "win" in state:
        state["win"].close()
    if "host" in state:
        state["host"].close()
    app.quit()


QTimer.singleShot(500, step)
app.exec()
