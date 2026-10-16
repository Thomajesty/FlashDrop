# -*- coding: utf-8 -*-
"""v1.18.14 冻结环境验收：启动**打包后的 EXE**，点开表情面板并量图标像素尺寸。

为什么必须做：
  同一份源码，「源码直跑」渲染出 22~25px，「打包 EXE」只渲染 14px ——
  差异来自冻结环境里全局 QSS 会作用到 Qt.Popup（见 v1.18.14 修复说明）。
  所以静态断言 + 源码渲染都**不足以**证明修好了，必须在真 EXE 上量一次。

做法：subprocess 启动 EXE → Win32 找到主窗口 → 按相对偏移点击表情按钮
      → 枚举出新增的顶层窗口（面板）→ 截它 → 量图标可视宽度。

运行：python tests/verify_v11814_frozen_icon.py
"""
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXE = os.path.join(ROOT, "dist", "FlashDrop.exe")
OUTDIR = os.path.join(HERE, "_v11814")

user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

P, F = [], []


def check(name, cond, detail=""):
    (P if cond else F).append(name)
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", name,
                          ("   " + detail) if (detail and not cond) else ""))


def all_top_windows():
    """全部可见顶层窗口 [(hwnd, l, t, r, b, title)]。"""
    out = []

    def _cb(h, _l):
        if not user32.IsWindowVisible(h):
            return True
        ln = user32.GetWindowTextLengthW(h)
        buf = ctypes.create_unicode_buffer(ln + 2)
        user32.GetWindowTextW(h, buf, ln + 2)
        r = wt.RECT()
        user32.GetWindowRect(h, ctypes.byref(r))
        out.append((h, r.left, r.top, r.right, r.bottom, buf.value))
        return True

    user32.EnumWindows(WNDENUMPROC(_cb), 0)
    return out


def find_main_window():
    """按标题找主窗口。

    ★ 注意：PyInstaller onefile 的引导进程会**派生一个子进程**跑真正的应用，
      窗口属于子进程 —— 用 proc.pid 过滤 EnumWindows 永远找不到窗口。
      所以这里直接按窗口标题（含「闪传」）匹配。
    """
    for w in all_top_windows():
        if "闪传" in (w[5] or ""):
            return w
    return None


def click(x, y):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.15)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.06)
    user32.mouse_event(0x0004, 0, 0, 0, 0)


def measure(img):
    W, H = img.size
    px = img.load()

    def colorful(x, y):
        r, g, b = px[x, y]
        return max(r, g, b) - min(r, g, b) > 40

    rows = [sum(1 for x in range(W) if colorful(x, y)) for y in range(H)]
    mx = max(rows) if rows else 0
    if mx == 0:
        return None
    band, cur = None, None
    for y, v in enumerate(rows):
        if v > mx * 0.3:
            if cur is None:
                cur = y
        else:
            if cur is not None:
                band = (cur, y)
                break
    if not band:
        return None
    y0, y1 = band
    xs = [x for x in range(W) if any(colorful(x, y) for y in range(y0, y1))]
    groups, cur, prev = [], None, None
    for x in xs:
        if cur is None:
            cur = x
        elif x - prev > 6:
            groups.append((cur, prev))
            cur = x
        prev = x
    if cur is not None:
        groups.append((cur, prev))
    ws = [b - a + 1 for a, b in groups]
    ps = [groups[i + 1][0] - groups[i][0] for i in range(len(groups) - 1)]
    return {
        "cols": len(groups), "widths": ws, "pitches": ps,
        "median_w": sorted(ws)[len(ws) // 2] if ws else 0,
        "median_p": sorted(ps)[len(ps) // 2] if ps else 0,
        "row_h": y1 - y0,
    }


print("=" * 68)
print("v1.18.14 冻结 EXE 表情图标尺寸验收")
print("=" * 68)
print("EXE:", EXE, "\n")

if not os.path.exists(EXE):
    print("!! EXE 不存在，先打包")
    sys.exit(2)

os.makedirs(OUTDIR, exist_ok=True)
tmp = tempfile.mkdtemp(prefix="fd_frozen_")
env = dict(os.environ)
env["FLASHDROP_DATA_DIR"] = tmp
env.pop("QT_QPA_PLATFORM", None)

proc = subprocess.Popen([EXE], env=env,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
print("启动 PID:", proc.pid)

try:
    # ★ PyInstaller onefile 冷启动在沙箱单核下实测 ~100s（解包 53MB），
    #   官方 e2e 脚本用 45s 会假失败，这里给足 220s。
    deadline = time.time() + 220
    main = None
    while time.time() < deadline:
        main = find_main_window()
        if main:
            break
        time.sleep(0.8)

    if not main:
        try:
            proc.terminate()
        except Exception:
            pass
        print("未找到标题含「闪传」的窗口")
        check("EXE 创建了可见主窗口", False)
        raise SystemExit(1)

    hwnd, l, t, r, b, title = main
    print("主窗口: %r  rect=(%d,%d)-(%d,%d)  %dx%d"
          % (title, l, t, r, b, r - l, b - t))
    check("EXE 创建了可见主窗口", True)

    try:
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass
    time.sleep(0.8)

    before = set(w[0] for w in all_top_windows())
    W, H = r - l, b - t
    # 表情按钮：主窗口内 左 314 / 距底 95（实测自 1074x749 全窗截图）
    bx = l + int(W * 314.0 / 1074)
    by = b - int(H * 95.0 / 749)
    print("点击表情按钮 @ 屏幕 (%d,%d)" % (bx, by))
    click(bx, by)
    time.sleep(1.8)

    new = [w for w in all_top_windows() if w[0] not in before]
    print("新增顶层窗口 %d 个：%s"
          % (len(new), [(w[5] or "(无标题)", w[3] - w[1], w[4] - w[2])
                        for w in new]))
    check("点击后出现了表情面板窗口（Qt.Popup）", len(new) > 0)

    from PIL import ImageGrab
    target = None
    for w in new:
        _h, wl, wtop, wr, wb, _ti = w
        if (wr - wl) > 300 and (wb - wtop) > 300:
            target = w
            break
    if target is None and new:
        target = new[0]

    if target:
        _h, wl, wtop, wr, wb, _ti = target
        print("面板 rect = (%d,%d)-(%d,%d)  %dx%d"
              % (wl, wtop, wr, wb, wr - wl, wb - wtop))
        img = ImageGrab.grab(bbox=(wl, wtop, wr, wb))
        shot = os.path.join(OUTDIR, "frozen_panel.png")
        img.save(shot)
        print("截图 ->", shot)
        res = measure(img)
        if res:
            print("    列数=%d  图标宽=%s  列pitch=%s"
                  % (res["cols"], res["widths"], res["pitches"]))
            check("★ 冻结 EXE 图标可视宽度 >= 22px",
                  res["median_w"] >= 22, "实际中位 %dpx" % res["median_w"])
            check("冻结 EXE 仍是 10 列", res["cols"] == 10,
                  "实际 %d" % res["cols"])
            check("冻结 EXE 列 pitch 仍为 44", res["median_p"] == 44,
                  "实际 %d" % res["median_p"])
        else:
            check("能在面板截图里量到表情行", False)
    else:
        check("找到可截图的面板窗口", False)

finally:
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

print()
print("=" * 68)
if F:
    print("失败项：")
    for f in F:
        print("  - %s" % f)
print("冻结 EXE 图标验收：通过 %d 项，失败 %d 项" % (len(P), len(F)))
print("=" * 68)
sys.exit(1 if F else 0)
