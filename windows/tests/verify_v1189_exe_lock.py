# -*- coding: utf-8 -*-
"""v1.18.9 EXE 端到端：孤儿锁抢占（用户第 1 条「EXE 打不开」的真实场景）

═══ 为什么必须有这个测试 ═══════════════════════════════════════
v1.18.8 之前 single_instance_lock() 的行为是：

    bind 失败 → 一律认定「已有实例」→ 发个 SHOW 就 sys.exit(0)

问题：**bind 失败不等于有实例活着**。Windows 上 UDP 端口可能被
僵死的残留进程、或被别的程序占用。此时：
  · 发 SHOW 无人应答
  · 当前进程直接退出
  · 用户双击 EXE → 什么都没发生 = 「打不开」

修复后：bind 失败 → 先 PING 探活 → 无 PONG 则**抢占**（视为孤儿锁）。

本脚本在真实 EXE 上验证这两条路径。
"""
import os
import re
import socket
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WIN = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(HERE)
LOCK_PORT = 58898

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
        FAILS.append(f"{name} {detail}")
        print(f"  [FAIL] {name} {detail}")


def find_exe():
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


def procs():
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq FlashDrop.exe",
                            "/FO", "CSV", "/NH"],
                           capture_output=True, text=True, timeout=20,
                           encoding="gbk", errors="replace")
        return [(l.split('","')[1]) for l in (r.stdout or "").splitlines()
                if l.strip().startswith('"')]
    except Exception:
        return []


def kill_all():
    subprocess.run(["taskkill", "/F", "/IM", "FlashDrop.exe"],
                   capture_output=True, timeout=20)


print("=" * 66)
print("v1.18.9 EXE 端到端：孤儿锁抢占")
print("=" * 66)

exe = find_exe()
check("找到 FlashDrop.exe", exe is not None)
if not exe:
    sys.exit(1)
print(f"  目标: {exe}\n  大小: {os.path.getsize(exe):,} B")

kill_all()
time.sleep(2)

# ─────────────────────────────────────────────────────────────
print("\n=== §1 场景：孤儿锁（端口被占但无人应答 PING） ===")
print("  复现用户场景：上次异常退出残留了端口占用")

# 制造孤儿锁：占住端口，但**故意不应答 PING**
orphan = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
orphan.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
orphan.bind(("127.0.0.1", LOCK_PORT))
print("  已制造孤儿锁（占端口 / 不回应）")

d = tempfile.mkdtemp(prefix="fd_orphan_")
env = dict(os.environ)
env["FLASHDROP_DATA_DIR"] = d
env.setdefault("QT_QPA_PLATFORM", "offscreen")

p = subprocess.Popen([exe, "--hidden"], env=env, cwd=os.path.dirname(exe),
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
time.sleep(16)

alive = p.poll() is None
check("§1a 孤儿锁存在时 EXE **仍然启动成功**（旧版会静默退出）", alive,
      f"rc={p.poll()} → 这正是用户看到的「打不开」")

ps = procs()
check("§1b 进程确实在运行", len(ps) >= 1, f"procs={ps}")

cfg = os.path.join(d, "config.json")
for _ in range(12):
    if os.path.isfile(cfg):
        break
    time.sleep(0.5)
check("§1c 已进入正常初始化（config 落盘）", os.path.isfile(cfg))

out = ""
try:
    os.set_blocking(p.stdout.fileno(), False)
    raw = p.stdout.read() or b""
    for enc in ("gbk", "utf-8"):
        try:
            out = raw.decode(enc)
            break
        except Exception:
            continue
except Exception:
    pass
check("§1d 未被单实例逻辑提前 exit（无「已在运行」）",
      "已在运行" not in out, out[-200:])

# 关掉：先杀 EXE，再释放孤儿端口
kill_all()
time.sleep(2)
try:
    orphan.close()
except Exception:
    pass
time.sleep(1)

# ─────────────────────────────────────────────────────────────
print("\n=== §2 场景：真实活实例（第二次双击应唤起而非再开一个） ===")
d2 = tempfile.mkdtemp(prefix="fd_live_")
env2 = dict(os.environ)
env2["FLASHDROP_DATA_DIR"] = d2
env2.setdefault("QT_QPA_PLATFORM", "offscreen")

p1 = subprocess.Popen([exe, "--hidden"], env=env2, cwd=os.path.dirname(exe),
                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
time.sleep(16)
check("§2a 首个实例存活", p1.poll() is None)

# 第二个实例：应 PING 到 PONG → 通知后退出
p2 = subprocess.Popen([exe], env=env2, cwd=os.path.dirname(exe),
                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
try:
    rc2 = p2.wait(timeout=40)
    got = True
except subprocess.TimeoutExpired:
    rc2 = None
    got = False
    p2.kill()

check("§2b 第二个实例自动退出（不会开出第二个窗口）", got, f"rc={rc2}")
check("§2c 退出码 0", rc2 == 0, f"rc={rc2}")

out2 = ""
try:
    raw2 = p2.stdout.read() or b""
    for enc in ("gbk", "utf-8"):
        try:
            c = raw2.decode(enc)
        except Exception:
            continue
        if "已在运行" in c:
            out2 = c
            break
        if not out2:
            out2 = c
except Exception:
    pass
check("§2d 提示「已在运行，已唤起现有窗口」", "已在运行" in out2,
      (out2 or "")[-200:])

check("§2e 原实例未被影响", p1.poll() is None)

kill_all()
time.sleep(2)

# ─────────────────────────────────────────────────────────────
print("\n=== §3 端口最终释放 ===")
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
free = True
try:
    s.bind(("127.0.0.1", LOCK_PORT))
except OSError:
    free = False
finally:
    s.close()
check("§3a 全部退出后锁端口可重新绑定", free)

import shutil
shutil.rmtree(d, ignore_errors=True)
shutil.rmtree(d2, ignore_errors=True)

print("\n" + "=" * 66)
print(f"EXE 孤儿锁端到端：通过 {PASS} 项，失败 {FAIL} 项")
if FAILS:
    print("失败项：")
    for f in FAILS:
        print("  -", f)
print("=" * 66)
sys.exit(1 if FAIL else 0)
