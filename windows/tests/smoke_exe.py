# -*- coding: utf-8 -*-
"""v1.18.0 EXE 冒烟测试 —— 真实启动打包后的 FlashDrop.exe

═══ 为什么必须单独有这个脚本 ═══════════════════════════════════

v1.18.0 首包出过一次**严重事故**：

    用户双击新 EXE → 弹「Unhandled exception in script」
    AttributeError: 'Config' object has no attribute 'get'

根因：`MainWindow.__init__` 写了 `cfg.get("snip_hide_self", True)`，
而运行时 `cfg` 是 `Config` 对象 —— 它只实现了 `__getitem__`/`__setitem__`，
**没有 dict 的 `.get()`**。

**为什么单测没抓到**：当时的离屏测试只用 `inspect.getsource()` 检查源码串，
从未真正构造 `MainWindow`，更没启动过打包产物。

**本脚本的职责**：直接启动 `dist*/FlashDrop.exe`，
  ① 确认进程能存活（不因启动异常秒退）
  ② 捕获 stderr / 弹窗式异常输出
  ③ 确认端口开始监听（服务真的起来了）
这样任何"启动即崩"的回归都逃不掉。
"""
import os
import re
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WIN = os.path.dirname(HERE)

PASS = 0
FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK] {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name} {detail}")


def find_exe():
    """优先用最新版本号目录（dist1180 之类），否则回落到 dist。"""
    cands = []
    for d in os.listdir(WIN):
        if re.fullmatch(r"dist\d*", d):
            p = os.path.join(WIN, d, "FlashDrop.exe")
            if os.path.isfile(p):
                cands.append((os.path.getmtime(p), p))
    if not cands:
        return None
    cands.sort(reverse=True)
    return cands[0][1]


print("=" * 62)
print("v1.18.0 EXE 冒烟测试（真实启动打包产物）")
print("=" * 62)

exe = find_exe()
check("找到 FlashDrop.exe", exe is not None, "未找到，请先打包")
if not exe:
    sys.exit(1)
print(f"  目标: {exe}")
print(f"  大小: {os.path.getsize(exe):,} B")

# 用独立数据目录，避免污染用户真实配置
data_dir = tempfile.mkdtemp(prefix="fd_smoke_")
env = dict(os.environ)
env["FLASHDROP_DATA_DIR"] = data_dir
# ★ v1.18.32：本机若跑着真实 FlashDrop，单实例锁(UDP 58898)会让冒烟实例
#   直接"唤起已有窗口后退出"，config.json 永远不会生成 → 假失败。
#   用多开开关 + 独立服务端口彻底隔离。
env["FLASHDROP_ALLOW_MULTI"] = "1"
import socket as _s
_smoke_port = 58899
_c = _s.socket()
try:
    _c.bind(("127.0.0.1", 0))
    _smoke_port = _c.getsockname()[1]
finally:
    _c.close()
env["FLASHDROP_SMOKE_PORT"] = str(_smoke_port)
# 让 Qt 在无桌面会话时也能起（CI/沙箱）
env.setdefault("QT_QPA_PLATFORM", "offscreen")

print("\n=== §1 启动进程并观察存活 ===")
proc = subprocess.Popen(
    [exe, "--hidden", "--port", env["FLASHDROP_SMOKE_PORT"]],
    env=env,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    cwd=os.path.dirname(exe),
    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
)

# 给启动留足时间（PyInstaller 解包 + Qt 初始化 + 首次建配置）
time.sleep(14)

alive = proc.poll() is None
check("进程存活 ≥14s（未启动即崩）", alive,
      f"已退出，returncode={proc.poll()}")

if not alive:
    try:
        out = proc.stdout.read().decode("utf-8", "replace")
    except Exception:
        out = ""
    print("\n--- 进程输出 ---")
    print(out[-4000:] if out else "(无输出)")
    print("---------------\n")
    check("输出中没有 'has no attribute'", "has no attribute" not in out)
    check("输出中没有 'AttributeError'", "AttributeError" not in out)
    check("输出中没有 'Unhandled exception'",
          "Unhandled exception" not in out)
    sys.exit(1)

print("\n=== §2 无启动异常输出 ===")
# 进程还活着，尝试非阻塞读一点输出（不应有 traceback）
out = ""
try:
    if proc.stdout is not None:
        os.set_blocking(proc.stdout.fileno(), False)
        raw = proc.stdout.read() or b""
        out = raw.decode("utf-8", "replace")
except Exception:
    pass
if out.strip():
    print("--- 进程输出（截断 2000）---")
    print(out[-2000:])
    print("--------------------------")
check("无 'has no attribute'", "has no attribute" not in out)
check("无 'AttributeError'", "AttributeError" not in out)
check("无 'Traceback'", "Traceback" not in out)
check("无 'Unhandled exception'", "Unhandled exception" not in out)

print("\n=== §3 配置文件被正确创建（说明 __init__ 走通） ===")
cfg_path = os.path.join(data_dir, "config.json")
# ★ v1.18.32：等待放宽到 220s —— 沙箱内 onefile 冷启动约 100s（解包+Defender
#   扫描），原先只等 5s，冷启动时 Config 还没建就误报"config.json 未生成"。
deadline = time.time() + 220
while time.time() < deadline and not os.path.isfile(cfg_path):
    time.sleep(0.5)
check("config.json 已生成", os.path.isfile(cfg_path), cfg_path)

if os.path.isfile(cfg_path):
    import json
    try:
        cfgd = json.load(open(cfg_path, encoding="utf-8"))
        check("config.json 是合法 JSON", isinstance(cfgd, dict))
        check("含 snip_hide_self 键（v1.18.0 新增）",
              "snip_hide_self" in cfgd, f"keys={sorted(cfgd)[:8]}")
        check("snip_hide_self 默认 True",
              cfgd.get("snip_hide_self") is True,
              f"{cfgd.get('snip_hide_self')}")
        check("含 device_id（Config.load 跑完）", bool(cfgd.get("device_id")))
    except Exception as e:
        check("config.json 可解析", False, f"{type(e).__name__}: {e}")

print("\n=== §4 服务端口开始监听 ===")
port = None
if os.path.isfile(cfg_path):
    try:
        import json
        port = int(json.load(open(cfg_path, encoding="utf-8")).get("port", 58899))
    except Exception:
        port = 58899
else:
    port = int(env.get("FLASHDROP_SMOKE_PORT") or 58899)
print(f"  期望端口: {port}")

listening = False
try:
    r = subprocess.run(
        ["netstat", "-ano"], capture_output=True, text=True, timeout=25,
        encoding="utf-8", errors="replace")
    txt = (r.stdout or "") + (r.stderr or "")
    listening = (f":{port}" in txt and "LISTENING" in txt.upper())
except Exception as e:
    print(f"  netstat 失败：{e}")
check(f"端口 {port} 处于 LISTENING", listening,
      "netstat 未见监听（可能被沙箱限制，非必然失败）")

print("\n=== §5 正常退出 ===")
try:
    proc.terminate()
    try:
        proc.wait(timeout=12)
        check("进程可被正常终止", True)
    except subprocess.TimeoutExpired:
        proc.kill()
        check("进程可被正常终止", False, "terminate 后 12s 未退出，已强杀")
except Exception as e:
    check("进程可被正常终止", False, str(e))

# 清理
import shutil
shutil.rmtree(data_dir, ignore_errors=True)

print("\n" + "=" * 62)
print(f"EXE 冒烟测试：通过 {PASS} 项，失败 {FAIL} 项")
if FAILS:
    print("失败项：")
    for f in FAILS:
        print("  -", f)
print("=" * 62)
sys.exit(1 if FAIL else 0)
