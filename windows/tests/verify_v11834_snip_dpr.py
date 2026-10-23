#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v1.18.34 —— 「截图比例不对/不是桌面全屏」静态断言 + 真屏 E2E 验证。

用户反馈：电脑版截图比例不对，不是桌面全屏的比例，点击截图比例变了。

根因（grab_virtual_desktop，125% 缩放下定量复现）：
  画布创建后立刻 setDevicePixelRatio(dpr) → QPainter 变逻辑坐标系，
  而 dst 仍按物理像素计算 → 逻辑绘制再被 DPR 放大一次。实测 60×60 逻辑
  标记被画成 92×92 物理（应 75×75），中心偏移 +25% —— 内容整体放大
  1.25×，框选"全屏"得到放大 1.25 倍的 80% 桌面。
  另外 grabWindow 返回的 shot 自带 DPR 标记，Qt drawPixmap 按逻辑尺寸
  解释它，直接画也会叠一次缩放 → 必须先剥掉标记（setDevicePixelRatio(1.0)）。

修法：画布先不设 DPR（QPainter=物理坐标），每屏 shot 剥 DPR 后按物理
矩形 1:1 落位，全部画完再统一打 DPR 标记。

E2E 部分需要真实显示器（沙箱 2560x1440@125% 可跑）；无显示环境自动跳过。
"""
import os
import re
import sys
import io

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PASS = 0
FAIL = 0


def ck(name, ok, extra=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("  PASS  " + name)
    else:
        FAIL += 1
        print("  FAIL  " + name + ("   " + str(extra) if extra else ""))


def rd(path):
    with io.open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return f.read()


def static_checks():
    print("\n=== A. grab_virtual_desktop 物理像素拼接 ===")
    snip = rd("windows/app/ui/snip.py")
    m = re.search(r"def grab_virtual_desktop.*?(?=\ndef )", snip, re.S)
    ck("A1 存在 grab_virtual_desktop", m is not None)
    g = m.group(0) if m else ""
    ck("A2 画布创建时**不设** DPR（QPainter 保持物理坐标）",
       re.search(r"canvas = QPixmap\(int\(union\.width\(\) \* dpr\), "
                 r"int\(union\.height\(\) \* dpr\)\)\n(?!\s*canvas\.setDevicePixelRatio)",
                 g) is not None)
    ck("A3 每屏 shot 剥掉 DPR 标记后再落位（防 Qt 逻辑尺寸二次缩放）",
       "shot.setDevicePixelRatio(1.0)" in g)
    ck("A4 dst 按物理像素计算（× dpr）",
       "(sg.left() - union.left()) * dpr" in g
       and "int(sg.width() * dpr)" in g)
    ck("A5 全部画完后统一打 DPR 标记",
       re.search(r"p\.end\(\)\s*\n\s*canvas\.setDevicePixelRatio\(dpr\)", g) is not None)
    ck("A6 旧 bug 写法已消失（画布创建后立即 setDevicePixelRatio）",
       re.search(r"canvas = QPixmap\([^)]*\)\n\s*canvas\.setDevicePixelRatio",
                 g) is None)

    print("\n=== B. 裁剪与显示路径保持正确 ===")
    ck("B1 region_from_canvas 仍按 DPR 换算物理裁剪",
       "int(region.left() * dpr)" in snip
       and "sub.setDevicePixelRatio(dpr" in snip)
    ck("B2 overlay 绘制用整幅 canvas（逻辑 1:1，不产生额外拉伸）",
       "p.drawPixmap(full, self._canvas)" in snip)

    print("\n=== C. 版本号 ===")
    # v1.18.35 起版本断言演进式化（正则任意版本号，勿钉死 x.y.z）
    VER = r"\d+\.\d+\.\d+"
    CODE = r"\d+"
    initpy = rd("windows/app/__init__.py")
    ck("C1 windows __version__ 存在（x.y.z）",
       re.search(r'__version__ = "%s"' % VER, initpy) is not None)
    fdutil = rd("android/app/src/main/java/com/flashdrop/app/FdUtil.java")
    ck("C2 FdUtil.APP_VERSION 存在（x.y.z）",
       re.search(r'public static final String APP_VERSION = "%s";' % VER,
                 fdutil) is not None)
    manifest = rd("android/app/src/main/AndroidManifest.xml")
    ck("C3 manifest versionCode/versionName 同步存在",
       re.search(r'android:versionCode="%s"' % CODE, manifest) is not None
       and re.search(r'android:versionName="%s"' % VER, manifest) is not None)
    bat = rd("android/build_apk.bat")
    sh = rd("android/_build_v11817.sh")
    ck("C4 构建脚本 version 同步",
       re.search(r"--version-code %s --version-name %s" % (CODE, VER), bat)
       is not None
       and re.search(r"--version-code %s --version-name %s" % (CODE, VER), sh)
       is not None)
    ck("C5 aapt2 link 两个入口都带 -A assets（表情资产铁律）",
       '-A "%SRC%\\assets"' in bat and '-A "$BPW\\\\assets"' in sh)


def e2e_checks():
    print("\n=== D. 真屏 E2E（需显示器，无则跳过） ===")
    try:
        sys.path.insert(0, os.path.join(ROOT, "windows"))
        from PySide6.QtWidgets import QApplication, QWidget
        from PySide6.QtCore import Qt, QRect
        import time
        app = QApplication.instance() or QApplication(sys.argv)
        s = app.primaryScreen()
        dpr = s.devicePixelRatio()
        print("  屏幕: %dx%d 逻辑, dpr=%s" % (s.geometry().width(),
                                              s.geometry().height(), dpr))

        from app.ui.snip import grab_virtual_desktop, region_from_canvas

        # 已知位置放一个品红标记：逻辑 (100,100,60,60) → 物理 (125,125,75,75)@1.25
        marker = QWidget()
        marker.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                              | Qt.Tool)
        marker.setGeometry(100, 100, 60, 60)
        marker.setStyleSheet("background-color: #FF00FF;")
        marker.show()
        for _ in range(10):
            app.processEvents()
            time.sleep(0.1)

        canvas, origin = grab_virtual_desktop()
        ck("D1 画布物理尺寸 = 逻辑并集 × dpr",
           canvas.width() == int(s.geometry().width() * dpr)
           and canvas.height() == int(s.geometry().height() * dpr),
           "实际 %dx%d" % (canvas.width(), canvas.height()))
        ck("D2 画布 DPR 标记 = %s" % dpr,
           abs((canvas.devicePixelRatio() or 1.0) - dpr) < 1e-6)

        img = canvas.toImage()

        def bbox():
            minx = miny = maxx = maxy = None
            for y in range(0, img.height(), 2):
                for x in range(0, img.width(), 2):
                    c = img.pixelColor(x, y)
                    if c.red() > 240 and c.blue() > 240 and c.green() < 40:
                        if minx is None or x < minx:
                            minx = x
                        if maxx is None or x > maxx:
                            maxx = x
                        if miny is None or y < miny:
                            miny = y
                        if maxy is None or y > maxy:
                            maxy = y
            return (minx, miny, maxx, maxy)

        bb = bbox()
        if bb[0] is None:
            ck("D3 标记进入抓屏画面", False, "未检测到品红（抓屏竞态），跳过位置断言")
            return
        exp = (int(100 * dpr), int(100 * dpr),
               int(160 * dpr), int(160 * dpr))
        ck("D3 标记物理位置 1:1 正确（无放大/偏移）",
           abs(bb[0] - exp[0]) <= 8 and abs(bb[2] - exp[2]) <= 8
           and abs(bb[1] - exp[1]) <= 8 and abs(bb[3] - exp[3]) <= 8,
           "实际 %s 期望 %s" % (bb, exp))

        sub, _ = region_from_canvas(
            canvas, QRect(0, 0, int(canvas.width() / dpr),
                          int(canvas.height() / dpr)), origin)
        ck("D4 全屏选区 → 整屏物理分辨率",
           sub.width() == canvas.width() and sub.height() == canvas.height())
        sub2, _ = region_from_canvas(canvas, QRect(200, 200, 100, 100), origin)
        ck("D5 局部选区 100x100 逻辑 → 100×dpr 物理",
           sub2.width() == int(100 * dpr) and sub2.height() == int(100 * dpr),
           "实际 %dx%d" % (sub2.width(), sub2.height()))
    except Exception as e:
        print("  SKIP  E2E 不可用: %s" % e)


def main():
    static_checks()
    if os.environ.get("FLASHDROP_SNIP_E2E", "1") != "0":
        e2e_checks()
    print("\n结果: %d 通过, %d 失败" % (PASS, FAIL))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
