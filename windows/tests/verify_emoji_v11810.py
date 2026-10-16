# -*- coding: utf-8 -*-
"""v1.18.10 表情按钮 —— 真实渲染截图 + 行为验证

验证项：
  §1 底部工具行第一个按钮就是「😀 表情」（在「📎 发送文件」左侧）
  §2 面板能打开，分类页签数量正确，网格渲染出真实 PNG 图标
  §3 点击某个表情后，字符被插入输入框光标处
  §4 最近使用记录写入并回读
  §5 深/浅主题下都有截图产出
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt, QPoint, QSettings
from PySide6.QtWidgets import QApplication, QToolButton, QPushButton, QToolTip

app = QApplication.instance() or QApplication([])

import tempfile
tmp = tempfile.mkdtemp(prefix="fd_shot11810_")
os.environ["FLASHDROP_DATA_DIR"] = tmp

from app.config import Config
from app.node import FlashNode
from app.ui.main_window import MainWindow
from app.ui import emoji as EMOJI

OUT = os.path.dirname(os.path.abspath(__file__))
results = []


def rec(ok, msg):
    results.append((ok, msg))
    print(("  PASS  " if ok else "  FAIL  ") + msg)


# ---------- §0 目录资源自检 ----------
print("\n=== §0 表情资源自检 ===")
cat = EMOJI.load_catalog()
rec(cat["count"] > 1500, "目录条目数 = %d（期望 >1500）" % cat["count"])
rec(len(cat["groups"]) == 10, "分类数 = %d（期望 10）" % len(cat["groups"]))
img_dir = EMOJI._emoji_dir()
pngs = [f for f in os.listdir(img_dir) if f.endswith(".png")] if os.path.isdir(img_dir) else []
rec(len(pngs) == cat["count"],
    "PNG 文件数 %d == 目录条目数 %d" % (len(pngs), cat["count"]))
# 抽查 10 个能否真正解码
from PySide6.QtGui import QPixmap
bad = []
for g in cat["groups"]:
    for e in g["emojis"][:1]:
        pm = QPixmap(os.path.join(img_dir, e["slug"] + ".png"))
        if pm.isNull() or pm.width() < 8:
            bad.append(e["slug"])
rec(not bad, "抽检 10 个 PNG 均可解码（坏图 %d）" % len(bad))

# 中文命中率
cn_hit = sum(1 for g in cat["groups"] for e in g["emojis"] if e["cn"] != e["name"])
rec(cn_hit > 400, "中文名命中 %d 条" % cn_hit)


# ---------- §1 按钮位置 ----------
print("\n=== §1 按钮位置（必须在「发送文件」左侧）===")
for theme in ("light", "dark"):
    cfg = Config()
    cfg["theme"] = theme
    cfg["save_dir"] = tmp
    win = MainWindow(cfg, FlashNode(cfg))
    win.resize(1100, 740)
    win.show()
    app.processEvents()

    panel = win.input_panel
    order = []
    for b in panel.findChildren(QToolButton):
        order.append(("QToolButton", b.objectName(), b.text(), b))
    for b in panel.findChildren(QPushButton):
        order.append(("QPushButton", b.objectName(), b.text(), b))

    # 只保留底部工具行那一批，按 x 坐标排序
    names = ("📎 发送文件", "🖼 发送图片", "📋 发送剪贴板")
    row = [o for o in order
           if ("表情" in o[2] or "截图" in o[2] or o[2] in names
               or o[2].strip() == "▾")]
    row.sort(key=lambda o: o[3].mapTo(panel, QPoint(0, 0)).x())
    seq = [o[2] for o in row]
    print("   工具行顺序:", " | ".join(seq))
    rec(bool(seq) and "表情" in seq[0],
        "[%s] 工具行第一个是表情按钮" % theme)
    if "表情" in seq and "📎 发送文件" in seq:
        rec(seq.index("表情") < seq.index("📎 发送文件"),
            "[%s] 表情按钮在「📎 发送文件」左侧" % theme)

    emoji_btn = next((o[3] for o in row if "表情" in o[2]), None)
    rec(emoji_btn is not None, "[%s] 找到表情按钮实例" % theme)

    if emoji_btn is not None:
        # ---------- §2 面板打开 ----------
        emoji_btn.click()
        app.processEvents()
        pnl = emoji_btn._panel
        rec(pnl is not None and pnl.isVisible(), "[%s] 面板已打开" % theme)
        if pnl:
            # ★ v1.18.13：分类栏改为微信式底部图标条，_tab_btns 由 2 元组
            #   变为 3 元组 (key, btn, label)；btn.text() 现在是图标。
            tabs = [lb for _k, _b, lb in pnl._tab_btns]
            print("   分类:", " ".join(tabs))
            rec(len(tabs) >= 9, "[%s] 分类数 = %d" % (theme, len(tabs)))
            # 分类按钮必须是圆形图标按钮（新样式）
            rec(all(b.objectName() == "EmojiTabIcon" for _k, b, _l in pnl._tab_btns),
                "[%s] 分类按钮为微信式图标条 (EmojiTabIcon)" % theme)
            rec(all(len(b.text()) >= 1 for _k, b, _l in pnl._tab_btns),
                "[%s] 每个分类按钮都有图标字形" % theme)
            rec(all(b.icon().isNull() is False for b in pnl._buttons[:20]),
                "[%s] 网格前 20 格图标已加载" % theme)
            rec(len(pnl._buttons) > 100,
                "[%s] 首个分类渲染 %d 格" % (theme, len(pnl._buttons)))
            # ★ v1.18.13 尺寸对齐微信：面板 464 宽 · 可见 6 行
            rec(pnl.width() == 464,
                "[%s] 面板宽 = %d（对齐微信 464）" % (theme, pnl.width()))
            rec(getattr(pnl, "GRID_ROWS", None) == 6,
                "[%s] 网格可见行数 = %s（对齐微信 6）" % (theme, getattr(pnl, "GRID_ROWS", None)))
            rec(getattr(pnl, "CELL", None) == 44,
                "[%s] 格子边长 = %s（对齐微信 44）" % (theme, getattr(pnl, "CELL", None)))
            rec(getattr(pnl, "ICON_PAD", None) == 16,
                "[%s] 图标内边距 = %s → 图标框 28px"
                % (theme, getattr(pnl, "ICON_PAD", None)))
            # ★ v1.18.14：光看 ICON_PAD 不够 —— 全局 QSS 的 QToolButton padding
            #   会把图标实际压小（v1.18.13 名义 26px、实际只渲染 14px）。
            #   所以这里同时断言格子自带 padding:0 样式；真正的像素门槛见
            #   tests/verify_v11814_emoji_size.py。
            _cell0 = pnl._grid.itemAt(0).widget() if pnl._grid.count() else None
            rec(_cell0 is not None
                and "padding: 0px" in (_cell0.styleSheet() or ""),
                "[%s] 表情格子自带 padding:0（防被全局 QSS 压小）" % theme)

            # ---------- §3 点击插入 ----------
            target = pnl._buttons[3]
            ch = target.ent["char"]
            win.input_edit.setPlainText("AB")
            cur = win.input_edit.textCursor()
            cur.setPosition(1)
            win.input_edit.setTextCursor(cur)
            target._emit()
            app.processEvents()
            got = win.input_edit.toPlainText()
            rec(got == "A" + ch + "B",
                "[%s] 表情插入光标处 -> %r（期望 %r）"
                % (theme, got, "A" + ch + "B"))
            self_closed = not pnl.isVisible()
            rec(self_closed, "[%s] 选中后面板自动关闭" % theme)

            # ---------- §4 最近使用 ----------
            slug = target.ent["slug"]
            rec(slug in pnl._recent, "[%s] 最近使用已记录 %s" % (theme, slug))
            st = QSettings("FlashDrop", "FlashDrop")
            raw = st.value(EMOJI.RECENT_KEY, [])
            if isinstance(raw, str):
                raw = [s for s in raw.split(",") if s]
            rec(slug in (raw or []), "[%s] 最近使用已持久化" % theme)

    # ---------- §5 截图 ----------
    emoji_btn = next((o[3] for o in row if "表情" in o[2]), None)
    if emoji_btn is not None:
        if emoji_btn._panel and emoji_btn._panel.isVisible():
            emoji_btn._panel.hide()
        emoji_btn.click()
        app.processEvents()
        pnl = emoji_btn._panel
        pnl.grab().save(os.path.join(OUT, "shot_emoji_panel_%s.png" % theme))
        # 面板 + 底部工具行一起截
        bar = panel.grab()
        bar.save(os.path.join(OUT, "shot_emoji_bar_%s.png" % theme))
        print("   截图: shot_emoji_panel_%s.png / shot_emoji_bar_%s.png"
              % (theme, theme))

    win.close()


print("\n=== 汇总 ===")
bad_n = sum(1 for ok, _ in results if not ok)
print("  %d/%d 通过，%d 失败" % (len(results) - bad_n, len(results), bad_n))
for ok, m in results:
    if not ok:
        print("   x", m)
sys.exit(1 if bad_n else 0)
