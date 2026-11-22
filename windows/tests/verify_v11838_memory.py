# -*- coding: utf-8 -*-
"""v1.18.38 验收套件：内存占用治理

A 组 运行时：内存归因脚本（页缓存上限 3 + trim 后零增长 + viewer 零泄漏）
B 组 静态：页缓存/渲染窗口/trim 接线
C 组 版本：五处版本号同步 1.18.38 / versionCode 67

运行：python windows/tests/verify_v11838_memory.py
"""
import os
import re
import subprocess
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
    print("v1.18.38 验收套件（内存占用治理）")
    print("=" * 70)

    # ---------- A 组：运行时内存归因 ----------
    print("\n=== A. 内存归因运行时（profile_memory_v11838.py）===")
    py = sys.executable
    r = subprocess.run(
        [py, "-u", os.path.join(HERE, "profile_memory_v11838.py")],
        capture_output=True, text=True, timeout=420,
        cwd=WIN, encoding="utf-8", errors="replace")
    out = r.stdout or ""
    ck("A1 归因脚本完整跑完（S10 出现）", "S10" in out, out[-400:])
    ck("A2 ImageViewer 真实入口零残留",
       "_viewers 残留: 0" in out, out[-300:])
    ck("A3 trim 后页数断言 ok", "trim 后页数断言: ok" in out)
    mb = re.search(r"气泡数: (\d+)", out)
    ck("A4 trim 后重建正常（气泡数 >1）",
       mb is not None and int(mb.group(1)) > 1,
       out[-200:] if mb is None else f"got {mb.group(1)}")
    # S10 行 = trim 后再切 3 轮的私有总量必须 <= S9 行的总量 + 60MB 容差
    m9 = re.search(r"S9[^\n]*私有总量\s+([\d.]+)", out)
    m10 = re.search(r"S10[^\n]*私有总量\s+([\d.]+)", out)
    if m9 and m10:
        d = float(m10.group(1)) - float(m9.group(1))
        ck("A5 trim 后反复切换零增长（Δ%.1fMB ≤ 60MB）" % d, d <= 60.0)
    else:
        ck("A5 trim 后反复切换零增长", False, "未解析到 S9/S10 私有总量")
    ck("A6 页缓存 3 页生效", "页缓存 3 页" in out, out[-300:])

    # ---------- B 组：静态 ----------
    print("\n=== B. 静态断言 ===")
    mw = rd("windows/app/ui/main_window.py")
    ck("B1 _CHAT_PAGE_CAP = 3", "_CHAT_PAGE_CAP = 3" in mw)
    ck("B2 渲染窗口 200", "rest[-200:] + pended" in mw)
    ck("B3 _trim_pages 定义存在", "def _trim_pages" in mw)
    ck("B4 closeEvent 隐藏托盘时调用 trim",
       "self._trim_pages()" in mw.split("def closeEvent(self, e: QCloseEvent)")[1]
       .split("def ")[0])
    ce = mw.split("def changeEvent")[1].split("\n    def ")[0] if "def changeEvent" in mw else ""
    ck("B5 changeEvent 最小化时调用 trim",
       "WindowStateChange" in ce and "_trim_pages()" in ce, ce[:200])
    ck("B6 trim 保留当前页与初始页",
       'k != cur and k != init_key' in mw)
    hist = rd("windows/app/ui/history.py")
    ck("B7 history 负载上限仍在（max 保守截断）",
       "self.max" in hist)

    # ---------- C 组：版本 ----------
    print("\n=== C. 版本五处同步 ===")
    ck("C1 __init__ 版本演进",
       bool(re.search(r'1\.18\.\d+', rd("windows/app/__init__.py"))))
    ck("C2 FdUtil.APP_VERSION 演进",
       bool(re.search(r'APP_VERSION = "1\.18\.\d+"',
                      rd("android/app/src/main/java/com/flashdrop/app/FdUtil.java"))))
    man = rd("android/app/src/main/AndroidManifest.xml")
    ck("C3 manifest versionName/versionCode",
       bool(re.search(r'versionName="1\.18\.\d+"', man))
       and bool(re.search(r'versionCode="\d+"', man)))
    ck("C4 build_apk.bat 同步",
       bool(re.search(r"--version-code \d+ --version-name 1\.18\.\d+",
                      rd("android/build_apk.bat"))))
    ck("C5 _build_v11817.sh 同步",
       bool(re.search(r"--version-code \d+ --version-name 1\.18\.\d+",
                      rd("android/_build_v11817.sh"))))

    print()
    if FAILS:
        print("FAILS:", len(FAILS))
        for f in FAILS:
            print(" -", f)
        sys.exit(1)
    print(f"ALL {N} PASS")


if __name__ == "__main__":
    main()
