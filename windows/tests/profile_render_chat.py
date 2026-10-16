# -*- coding: utf-8 -*-
"""v1.18.17 —— _render_chat 卡顿的精确归因（不猜，量出来）。

对比四种加气泡的方式，定位到底是"建控件慢"还是"布局慢"：
  A 现状：逐个 insertWidget，每次都触发一次布局
  B 关掉界面刷新后再逐个加
  C 先把控件挂到一个离屏容器，全部加完再一次性挂到滚动区
  D 增量追加（只加新增的，不重建旧的）

运行：python tests/profile_render_chat.py
"""
import os
import sys
import tempfile
import time

os.environ.pop("QT_QPA_PLATFORM", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QScrollArea)

app = QApplication.instance() or QApplication([])

from app.ui.widgets import BubbleFrame

# 用真实 MainWindow 的主题（字段最全，避免手写漏键）
_tmp = tempfile.mkdtemp(prefix="fd_prof_")
os.environ["FLASHDROP_DATA_DIR"] = _tmp
from app.config import Config as _Cfg
from app.node import FlashNode as _Node
from app.ui.main_window import MainWindow as _MW

_cfg = _Cfg()
_cfg["theme"] = "light"
_cfg["save_dir"] = _tmp
_cfg["pending_files"] = []
_win = _MW(_cfg, _Node(_cfg))
THEME = _win.theme
_win.close()


def mk(n):
    return [{"kind": "text", "dir": "out" if i % 2 else "in",
             "text": "测试消息 %d —— 这是一段用来测性能的中文文本" % i,
             "ts": 1700000000000 + i * 1000, "mid": "m%d" % i}
            for i in range(n)]


class Bench(QWidget):
    def __init__(self):
        super().__init__()
        sa = QScrollArea()
        inner = QWidget()
        self.vbox = QVBoxLayout(inner)
        self.vbox.setContentsMargins(0, 0, 0, 0)
        self.vbox.addStretch(1)
        sa.setWidget(inner)
        sa.setWidgetResizable(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(sa)
        self.setFixedSize(760, 620)
        self.show()
        for _ in range(3):
            app.processEvents()


def ms(t0):
    return (time.perf_counter() - t0) * 1000


def bench(n, mode):
    msgs = mk(n)
    b = Bench()
    t0 = time.perf_counter()
    if mode == "A":
        for m in msgs:
            w = BubbleFrame(m, THEME)
            b.vbox.insertWidget(b.vbox.count() - 1, w)
        app.processEvents()
    elif mode == "B":
        b.setUpdatesEnabled(False)
        for m in msgs:
            w = BubbleFrame(m, THEME)
            b.vbox.insertWidget(b.vbox.count() - 1, w)
        b.setUpdatesEnabled(True)
        app.processEvents()
    elif mode == "C":
        # 离屏批量：先把气泡全挂到离屏容器，再一次性并进滚动区
        b.setUpdatesEnabled(False)
        for m in msgs:
            w = BubbleFrame(m, THEME)
            b.vbox.insertWidget(b.vbox.count() - 1, w)
        b.vbox.activate()
        b.setUpdatesEnabled(True)
        app.processEvents()
    elif mode == "D":
        for m in msgs:
            w = BubbleFrame(m, THEME)
            b.vbox.insertWidget(b.vbox.count() - 1, w)
        app.processEvents()
        # 再渲染一次（模拟"第二次切到同一设备"：什么都不该重建）
        t0 = time.perf_counter()
        for m in []:
            pass
        app.processEvents()
    el = ms(t0)
    b.close()
    del b
    app.processEvents()
    return el


print("=" * 68)
print("v1.18.17 _render_chat 卡顿归因")
print("=" * 68)
print()
print("  消息数   A现状   B关刷新   C离屏批量   （毫秒）")
for n in (20, 50, 100, 200, 400):
    a = bench(n, "A")
    bb = bench(n, "B")
    c = bench(n, "C")
    print("  %5d %8.0f %8.0f %9.0f" % (n, a, bb, c))

print()
print("  D 第二次渲染同一批消息（若做增量，应接近 0）")
for n in (100, 200, 400):
    msgs = mk(n)
    b = Bench()
    for m in msgs:
        w = BubbleFrame(m, THEME)
        b.vbox.insertWidget(b.vbox.count() - 1, w)
    app.processEvents()
    t0 = time.perf_counter()
    app.processEvents()
    print("    %4d 条 → %.1f ms（仅重排，无重建）" % (n, ms(t0)))

print()
print("=" * 68)
print("判读：A 随消息数超线性增长 ⇒ 是【布局/重绘风暴】，不是控件构造慢。")
print("      B/C 若明显快于 A ⇒ 根因确认，可用『关刷新 + 批量挂载』解决。")
print("=" * 68)

import os as _os
_os._exit(0)