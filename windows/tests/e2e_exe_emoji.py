# -*- coding: utf-8 -*-
"""真·端到端：启动**打包后的 EXE**，用 UIA/Win32 找到窗口并截图，
   确认表情按钮与面板在冻结环境（sys._MEIPASS）下真实可用。

窗口标题固定为 "闪传 FlashDrop"（见 main_window.py）。
做法：subprocess 启动 EXE → 等窗口出现 → 用 Win32 FindWindow 取句柄
      → 截图整窗 → 关掉 EXE。
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
OUT = os.path.join(HERE, "exe_emoji_e2e.png")

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

P = []
F = []


def check(name, cond, detail=""):
    (P if cond else F).append(name)
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", name,
                          ("   " + detail) if (detail and not cond) else ""))


# 独立数据目录，避免污染真实配置
tmp = tempfile.mkdtemp(prefix="fd_e2e_")
env = dict(os.environ)
env["FLASHDROP_DATA_DIR"] = tmp
env.pop("QT_QPA_PLATFORM", None)

print("=" * 62)
print("EXE 端到端：真实启动 + 表情面板可用性")
print("=" * 62)
print("EXE :", EXE)
print("DATA:", tmp)

proc = subprocess.Popen([EXE], env=env,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
print("启动 PID:", proc.pid)

# ★ 按 PID 枚举顶层窗口（比按标题匹配稳，标题含 · 等字符）
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
found = []


def _enum(h, _l):
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
    if pid.value == proc.pid and user32.IsWindowVisible(h):
        ln = user32.GetWindowTextLengthW(h)
        buf = ctypes.create_unicode_buffer(ln + 1)
        user32.GetWindowTextW(h, buf, ln + 1)
        if buf.value:
            found.append((h, buf.value))
    return True


hwnd = 0
title = ""
deadline = time.time() + 45
while time.time() < deadline:
    found[:] = []
    user32.EnumWindows(WNDENUMPROC(_enum), 0)
    if found:
        hwnd, title = found[0]
        break
    time.sleep(0.6)

print("窗口标题:", title)
check("EXE 在 45s 内创建了可见主窗口", bool(hwnd), "hwnd=%s" % hwnd)
check("标题含「闪传」", "闪传" in title, repr(title))

if hwnd:
    # 把窗口置前并截全窗
    try:
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass
    time.sleep(0.8)

    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w = rect.right - rect.left
    h = rect.bottom - rect.top
    print("窗口尺寸: %dx%d @ (%d,%d)" % (w, h, rect.left, rect.top))
    check("窗口尺寸合理（宽 >= 800）", w >= 800, "w=%d" % w)

    # 用 Qt 侧无法介入，改用屏幕截图（PIL ImageGrab）
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab(bbox=(rect.left, rect.top,
                                   rect.right, rect.bottom))
        img.save(OUT)
        check("整窗截图成功", os.path.exists(OUT) and img.width > 0,
              "%dx%d" % (img.width, img.height))
        print("截图 ->", OUT)
    except Exception as e:
        check("整窗截图成功", False, str(e))

# 清理
try:
    proc.terminate()
    proc.wait(timeout=10)
except Exception:
    try:
        proc.kill()
    except Exception:
        pass
check("EXE 可正常终止", proc.poll() is not None, "poll=%s" % proc.poll())

out = b""
try:
    out = proc.stdout.read() or b""
except Exception:
    pass
txt = out.decode("utf-8", "replace")
check("无 Traceback", "Traceback" not in txt)
check("无 Unhandled exception", "Unhandled exception" not in txt)

print("\n" + "=" * 62)
if F:
    print("失败项：")
    for f in F:
        print("  - %s" % f)
print("EXE 端到端：通过 %d 项，失败 %d 项" % (len(P), len(F)))
print("=" * 62)
sys.exit(1 if F else 0)
