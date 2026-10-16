# -*- coding: utf-8 -*-
"""v1.16.0 验收截图生成（电脑端）

产出到 windows/tests/_out_v1160/ ，用于用户逐项核对。

覆盖：
  · 文件卡片（深/浅 × 收/发）—— 微信几何
  · 文件类型图标矩阵（APK 绿 / EXE 蓝 / PDF 红 / 图片 / 未知问号）
  · 未下载态（虚线描边）
  · 文字气泡（微信绿 / 闪传蓝 / 发送侧右贴）
  · 图片消息（缩略图 + 可拖拽提示）

跑法：
    "C:/Users/Administrator/AppData/Local/Programs/Python/Python312/python.exe" \
        windows/tests/shots_v1160.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap

from app.ui.widgets import BubbleFrame, make_file_icon
from app.ui.theme import resolve_theme, BUBBLE_SCHEMES

OUT = os.path.join(HERE, "_out_v1160")
os.makedirs(OUT, exist_ok=True)

_app = QApplication.instance() or QApplication([])


def theme_of(theme_key, scheme_key="green"):
    t = dict(resolve_theme(theme_key))
    sch = BUBBLE_SCHEMES[scheme_key]
    t["scheme_out"] = sch["out"]
    t["scheme_out_text"] = sch["out_text"]
    return t


def shot(msg, theme_key, scheme_key, fname, w=900, h=210):
    t = theme_of(theme_key, scheme_key)
    if msg.get("dir") == "in" and msg.get("state") == "done" \
            and not msg.get("path"):
        msg = dict(msg)
        msg["path"] = os.path.join(OUT, msg.get("file", "x"))
    bw = BubbleFrame(msg, t)
    bw.resize(w, h)
    bw.show()
    _app.processEvents()
    pm = bw.grab()
    bw.hide()
    p = os.path.join(OUT, fname)
    pm.save(p)
    print(f"  {fname}  {os.path.getsize(p)}B")
    return p


# ---------- 1. 文件卡片：深/浅 × 收/发 ----------
print("[1] 文件卡片")
pdf = {"dir": "in", "kind": "file", "file": "甘肃国钛干部请假审批表.pdf",
       "size": 90312, "state": "done", "mime": "application/pdf",
       "peer_name": "电脑端"}
shot(pdf, "dark", "green", "s01_card_dark_in.png")
shot(pdf, "light", "green", "s02_card_light_in.png")

pdf_out = dict(pdf, dir="out", state="ok", peer_name="手机")
shot(pdf_out, "dark", "green", "s03_card_dark_out_green.png")
shot(pdf_out, "light", "green", "s04_card_light_out_green.png")

# ---------- 2. 未下载态（虚线描边） ----------
print("[2] 未下载态（虚线）")
pend = {"dir": "in", "kind": "file", "file": "未下载的报表.xlsx",
        "size": 20480, "state": "confirm",
        "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "peer_name": "电脑端"}
shot(pend, "dark", "green", "s05_card_pending_dash.png")
shot(pend, "light", "green", "s06_card_pending_dash_light.png")

# ---------- 3. 图标分类矩阵 ----------
print("[3] 图标分类矩阵")
names = [
    ("FlashDrop_1.16.0.apk", "APK 安卓绿"),
    ("FlashDrop-Setup.exe", "EXE 蓝"),
    ("安装包.msi", "MSI 蓝"),
    ("报告.pdf", "PDF 红"),
    ("表格.xlsx", "XLS 绿"),
    ("文档.docx", "DOC 蓝"),
    ("演示.pptx", "PPT 橙"),
    ("照片.jpg", "JPG 紫"),
    ("歌曲.mp3", "MP3 粉"),
    ("备份.zip", "ZIP 棕"),
    ("笔记.txt", "TXT 灰"),
    ("未知格式.xyzq", "未知 问号"),
]
tiles = []
for nm, label in names:
    pm = make_file_icon(nm, 52, False)
    tiles.append((label, nm, pm))
    pm.save(os.path.join(OUT, f"icon_{nm.replace('.', '_')}.png"))

# 拼一张矩阵图
cols = 4
rows = (len(tiles) + cols - 1) // cols
TW, TH = 190, 110
sheet = QPixmap(TW * cols, TH * rows)
sheet.fill(0xFF1B1D22)
from PySide6.QtGui import QPainter, QColor, QFont
pt = QPainter(sheet)
pt.setRenderHint(QPainter.Antialiasing)
for i, (label, nm, pm) in enumerate(tiles):
    cx = (i % cols) * TW
    cy = (i // cols) * TH
    pt.drawPixmap(cx + 16, cy + 18, pm)
    f = QFont("Microsoft YaHei UI")
    f.setPixelSize(12)
    pt.setFont(f)
    pt.setPen(QColor("#E5E7EB"))
    pt.drawText(cx + 16, cy + 92, label)
    f2 = QFont("Microsoft YaHei UI")
    f2.setPixelSize(10)
    pt.setFont(f2)
    pt.setPen(QColor("#8B93A1"))
    pt.drawText(cx + 16, cy + 105, nm)
pt.end()
sheet.save(os.path.join(OUT, "s07_icon_matrix.png"))
print(f"  s07_icon_matrix.png  {os.path.getsize(os.path.join(OUT, 's07_icon_matrix.png'))}B")

# 未下载态矩阵
sheet2 = QPixmap(TW * 4, TH)
sheet2.fill(0xFF1B1D22)
pt2 = QPainter(sheet2)
for i, nm in enumerate(["报表.xlsx", "合同.pdf", "包.apk", "程序.exe"]):
    pm = make_file_icon(nm, 52, True)
    pt2.drawPixmap(i * TW + 16, 18, pm)
pt2.end()
sheet2.save(os.path.join(OUT, "s08_icon_dimmed.png"))
print(f"  s08_icon_dimmed.png  {os.path.getsize(os.path.join(OUT, 's08_icon_dimmed.png'))}B")

# ---------- 4. 文字气泡配色 ----------
print("[4] 文字气泡配色")
txt_in = {"dir": "in", "kind": "text",
          "text": "这条是接收到的文字消息，用于核对浅色适配与对比度。",
          "peer_name": "电脑端", "peer_scheme": ""}
txt_out = {"dir": "out", "kind": "text",
           "text": "这条是发送出去的文字消息，应显示微信绿气泡并靠右。",
           "state": "ok", "peer_name": "手机"}
shot(txt_in, "dark", "green", "s09_text_dark_in.png", h=120)
shot(txt_in, "light", "green", "s10_text_light_in.png", h=120)
shot(txt_out, "dark", "green", "s11_text_dark_out_green.png", h=140)
shot(txt_out, "light", "green", "s12_text_light_out_green.png", h=140)
shot(txt_out, "dark", "blue", "s13_text_dark_out_blue.png", h=140)

# ---------- 5. 图片消息 ----------
print("[5] 图片消息")
img_path = os.path.join(OUT, "_sample_img.png")
demo = QPixmap(320, 200)
demo.fill(0xFF3B82F6)
demo.save(img_path)
img_msg = {"dir": "in", "kind": "file", "file": "截图_9d27ba.png",
           "size": 41520, "state": "done", "mime": "image/png",
           "path": img_path, "peer_name": "电脑端"}
shot(img_msg, "dark", "green", "s14_image_dark_in.png", h=280)
shot(img_msg, "light", "green", "s15_image_light_in.png", h=280)

print(f"\n全部输出 → {OUT}")
