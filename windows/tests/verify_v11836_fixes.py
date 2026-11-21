# -*- coding: utf-8 -*-
"""v1.18.36 验收套件：双卡片 + 内存占用

A 组 运行时：双节点复现测试 tests/repro_dup_card.py（P0~P3）
B 组 内存：ImageViewer 关闭即销毁（行为级 + 静态）
C 组 版本：五处版本号同步

运行：python windows/tests/verify_v11836_fixes.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WIN = os.path.dirname(HERE)
ROOT = os.path.dirname(WIN)

FAILS = []
N = 0


def ck(name, cond, extra=""):
    global N
    N += 1
    if not cond:
        FAILS.append(f"{name} | {extra}")
    print(("  ok  " if cond else " FAIL ") + name +
          ((" | " + str(extra)) if extra and not cond else ""))


def rd(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def main():
    print("=" * 70)
    print("v1.18.36 验收套件")
    print("=" * 70)

    # ---------- A 组：双卡片（复现测试） ----------
    print("\n=== A. 双卡片运行时复现 ===")
    import subprocess
    py = sys.executable
    r = subprocess.run([py, os.path.join(HERE, "repro_dup_card.py")],
                       capture_output=True, text=True, timeout=180,
                       cwd=WIN, encoding="utf-8", errors="replace")
    out = r.stdout or ""
    ck("A1 repro_dup_card 全部通过", "ALL" in out and "FAILS" not in out,
       out[-400:])
    ck("A2 落盘恰好 1 行（P2）", "P2 落盘恰好 1 行" in out and "  ok  P2" in out)
    ck("A3 存量脏数据去重（P3）", "  ok  P3" in out)

    # 静态：offer 不落盘
    mw = rd("windows/app/ui/main_window.py")
    ck("A4 offer 状态不调用 _refresh_msg（不落盘 offer）",
       re.search(r'if state != "offer":\s*\n\s*self\._refresh_msg\(m\)', mw))
    ck("A5 upsert 注释标记 v1.18.36", "v1.18.36" in rd("windows/app/ui/history.py"))

    # ---------- B 组：内存 ----------
    print("\n=== B. ImageViewer 关闭即销毁 ===")
    ck("B1 finished 回调含 deleteLater",
       "_release_viewer" in mw and "vv.deleteLater()" in mw)
    ck("B2 旧泄漏 lambda 已移除",
       "lambda _r, vv=v: self._viewers.remove(vv)" not in mw)

    # 行为级：viewer 关闭 + deleteLater 后 C++ 对象销毁、pixmap 释放
    try:
        sys.path.insert(0, WIN)
        from PySide6.QtWidgets import QApplication, QWidget
        from PySide6.QtGui import QImage, QPainter, QColor
        from PySide6.QtCore import QTimer
        import shiboken6
        from app.ui.image_viewer import ImageViewer

        app = QApplication.instance() or QApplication([])
        # 造一张 4000x3000 的"手机照片"（16MB ARGB32）
        big = os.path.join(WIN, "tests", "_v11836_big.png")
        img = QImage(4000, 3000, QImage.Format_ARGB32)
        img.fill(QColor(180, 40, 90))
        p = QPainter(img)
        p.fillRect(100, 100, 800, 600, QColor(255, 255, 255))
        p.end()
        img.save(big, "PNG")

        parent = QWidget()
        v = ImageViewer([big], 0, parent)
        v.show()
        # 强制加载大图
        v._load(0)
        app.processEvents()
        canvas_pm = v.canvas.current_pixmap()
        ck("B3 大图已载入查看器", not canvas_pm.isNull()
           and canvas_pm.width() == 4000)

        v.close()
        v.deleteLater()          # 复刻 _release_viewer 的销毁链
        # processEvents 不处理 DeferredDelete，必须显式派发
        from PySide6.QtCore import QCoreApplication, QEvent
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()
        ck("B4 关闭后 viewer C++ 对象已销毁", not shiboken6.isValid(v))
        os.remove(big)
    except ImportError as e:
        ck("B3/B4 行为测试（Qt 环境缺失时跳过断言）", True, str(e))

    # ---------- C 组：版本 ----------
    print("\n=== C. 版本号 ===")
    initpy = rd("windows/app/__init__.py")
    ck("C1 windows __version__ = 1.18.36", '__version__ = "1.18.36"' in initpy)
    fdutil = rd("android/app/src/main/java/com/flashdrop/app/FdUtil.java")
    ck("C2 FdUtil.APP_VERSION = 1.18.36",
       'public static final String APP_VERSION = "1.18.36";' in fdutil)
    manifest = rd("android/app/src/main/AndroidManifest.xml")
    ck("C3 manifest 65 / 1.18.36",
       'android:versionCode="65"' in manifest
       and 'android:versionName="1.18.36"' in manifest)
    bat = rd("android/build_apk.bat")
    sh = rd("android/_build_v11817.sh")
    ck("C4 构建脚本 version 同步",
       "--version-code 65 --version-name 1.18.36" in bat
       and "--version-code 65 --version-name 1.18.36" in sh)

    print()
    if FAILS:
        print("FAILS:", len(FAILS))
        for f in FAILS:
            print(" -", f)
        sys.exit(1)
    print(f"ALL {N} PASS")


if __name__ == "__main__":
    main()
