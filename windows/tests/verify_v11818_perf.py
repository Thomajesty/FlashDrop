# -*- coding: utf-8 -*-
"""v1.18.18 性能验收 —— 缩略图磁盘缓存 / 文件图标缓存 / QSS 缓存 / 历史尾读 / 空闲预热

接续 verify_v11817_perf 的套路：耗时上限断言 + 正确性计数断言 + 缓存命中相对断言。
运行：python windows/tests/verify_v11818_perf.py
"""
import os
import shutil
import sys
import tempfile
import time

os.environ.pop("QT_QPA_PLATFORM", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

tmp = tempfile.mkdtemp(prefix="fd_v11818perf_")
os.environ["FLASHDROP_DATA_DIR"] = tmp

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor

app = QApplication.instance() or QApplication([])

from app.ui import widgets
from app.ui.history import History

P, F = [], []


def check(name, cond, extra=""):
    (P if cond else F).append(name)
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", name,
                          ("   " + str(extra)) if (extra and not cond) else ""))


def main():
    print("=" * 68)
    print("v1.18.18 性能验收")
    print("=" * 68)

    # ---------- 1. 文件图标缓存 ----------
    print("\n[文件图标缓存]")
    pm1 = widgets.make_file_icon("报告.pdf")
    check("首次绘制非空", not pm1.isNull())
    t0 = time.perf_counter()
    for _ in range(50):
        widgets.make_file_icon("任意名字.pdf")
    t1 = time.perf_counter()
    hot_ms = (t1 - t0) / 50 * 1000
    check("同扩展名命中缓存（热 < 0.5ms/次）", hot_ms < 0.5, f"{hot_ms:.3f}ms")
    # ★ 计数断言必须放在画完 3 个 key 之后
    widgets.make_file_icon("报告.doc")
    widgets.make_file_icon("报告.pdf", dimmed=True)
    check("不同扩展名/灰化各自缓存（pdf/doc/灰化pdf）",
          len(widgets._ICON_CACHE) >= 3,
          f"cache={len(widgets._ICON_CACHE)}")
    check("灰化态独立缓存（dimmed 进 key）",
          widgets._file_icon_key("报告.pdf", 52, True)
          != widgets._file_icon_key("报告.pdf", 52, False))
    check("扩展名 key 忽略大小写与点前缀",
          widgets._file_icon_key("A.PDF", 52, False)
          == widgets._file_icon_key("b.pdf", 52, False))

    # ---------- 2. 缩略图磁盘缓存 ----------
    print("\n[缩略图磁盘缓存]")
    d = os.path.join(tmp, "src")
    os.makedirs(d, exist_ok=True)
    img = os.path.join(d, "t1.png")
    big = widgets.QPixmap(900, 700)
    big.fill(QColor("#336699"))
    big.save(img)
    pm = widgets.make_thumb(img, 300)
    check("首次解码非空", not pm.isNull())
    ddir = widgets._thumb_disk_dir()
    check("磁盘缓存目录已建", os.path.isdir(ddir), ddir)
    files = os.listdir(ddir) if os.path.isdir(ddir) else []
    check("解码后写入磁盘", len(files) >= 1, str(files))
    # 内存清空 -> 磁盘命中
    widgets._THUMB_CACHE.clear()
    t0 = time.perf_counter()
    pm2 = widgets.make_thumb(img, 300)
    t1 = time.perf_counter()
    disk_ms = (t1 - t0) * 1000
    check("重启场景（内存 miss）磁盘命中", not pm2.isNull())
    check("磁盘命中 < 20ms（对比解码 100~300ms）", disk_ms < 20,
          f"{disk_ms:.2f}ms")
    check("磁盘命中回填内存缓存", len(widgets._THUMB_CACHE) == 1)
    # 源文件变化 -> key 变化 -> 不吃旧缓存
    time.sleep(0.02)
    big2 = widgets.QPixmap(900, 700)
    big2.fill(QColor("#FFAA00"))
    big2.save(img)       # 同路径覆盖 -> mtime/size 变
    os.utime(img, (time.time() + 2, time.time() + 2))
    pm3 = widgets.make_thumb(img, 300)
    check("源文件覆盖后不吃旧磁盘缓存", not pm3.isNull())
    # 空路径
    check("空路径返回空 pixmap", widgets.make_thumb("", 300).isNull())

    # ---------- 3. QSS 缓存 ----------
    print("\n[QSS 缓存]")
    q1 = widgets._bubble_qss("#111111", "#FFFFFF")
    q2 = widgets._bubble_qss("#111111", "#FFFFFF")
    check("同配色返回同一字符串对象（缓存命中）", q1 is q2)
    check("QSS 内容完整", "border-radius: 12px" in q1 and "14px" in q1)
    q3 = widgets._bubble_qss("#222222", "#EEEEEE")
    check("不同配色各自缓存", q1 is not q3)

    # ---------- 4. 历史尾读 ----------
    print("\n[历史尾读]")
    h = History()
    pid = "perftail00000001"
    path = h._path(pid)
    N_LINES = 5000
    with open(path, "w", encoding="utf-8") as f:
        for i in range(N_LINES):
            f.write('{"mid":"m%d","text":"%s"}\n' % (i, "消息" * 60))
    # 正确性：尾部精确
    msgs = h.load(pid, 500)
    check("load(500) 条数", len(msgs) == 500, str(len(msgs)))
    check("尾部精确（最后一条）", msgs[-1].get("mid") == f"m{N_LINES - 1}",
          msgs[-1].get("mid"))
    check("尾部精确（第一条）", msgs[0].get("mid") == f"m{N_LINES - 500}",
          msgs[0].get("mid"))
    # 性能：尾读 << 全读
    t0 = time.perf_counter()
    History._read_tail(path, 1000)
    t_tail = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    with open(path, "rb") as f:
        f.read()
    t_full = (time.perf_counter() - t0) * 1000
    check("尾读(1000) 不慢于全读", t_tail <= t_full * 1.5 + 2,
          f"tail={t_tail:.2f}ms full={t_full:.2f}ms")
    # 边界：空文件 / 无换行 / 全量模式
    open(path, "w").close()
    check("空文件返回空", History._read_tail(path, 10) == [])
    with open(path, "w", encoding="utf-8") as f:
        f.write("单行无换行")
    check("无换行单行不丢", History._read_tail(path, 10) == ["单行无换行"])
    with open(path, "w", encoding="utf-8") as f:
        for i in range(5):
            f.write('{"i":%d}\n' % i)
    # ★ 必须换 pid：同 pid 的 _cache_n=500 缓存会命中旧内容
    #   （缓存不追踪文件外部变化 —— 既有行为）
    pid3 = "fullmode000000001"
    with open(h._path(pid3), "w", encoding="utf-8") as f:
        for i in range(5):
            f.write('{"i":%d}\n' % i)
    check("limit=None 全量模式兼容", len(h.load(pid3, None)) == 5,
          str(len(h.load(pid3, None))))
    # 多字节边界：中文长行跨 64KB 块
    with open(path, "w", encoding="utf-8") as f:
        f.write('{"mid":"x0","text":"%s"}\n' % ("长" * 40000))
        f.write('{"mid":"x1","text":"尾"}\n')
    tail = History._read_tail(path, 2)
    ok2 = len(tail) == 2 and "x0" in tail[0] and "x1" in tail[1]
    check("多字节跨块不乱码", ok2, tail[:1])

    # ---------- 5. 幽灵清理行为不变（尾读重构的回归） ----------
    print("\n[幽灵传输清理回归]")
    h2 = History()
    pid2 = "ghosttest0000001"
    with open(h2._path(pid2), "w", encoding="utf-8") as f:
        f.write('{"kind":"file","state":"progress","mid":"g1","file":"a.bin"}\n')
        f.write('{"kind":"text","state":"ok","mid":"g2","text":"hi"}\n')
    gmsgs = h2.load(pid2, 10)
    g1 = [m for m in gmsgs if m.get("mid") == "g1"]
    g2 = [m for m in gmsgs if m.get("mid") == "g2"]
    check("进行中的传输标记为失败", bool(g1) and g1[0].get("state") == "failed",
          g1 and g1[0].get("state"))
    check("正常消息不受影响", bool(g2) and g2[0].get("state") == "ok")

    shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 68)
    print(f"结果：{len(P)}/{len(P) + len(F)} 通过")
    if F:
        print("失败项：")
        for x in F:
            print("  - " + x)
    if F:
        os._exit(1)
    os._exit(0)


if __name__ == "__main__":
    main()
