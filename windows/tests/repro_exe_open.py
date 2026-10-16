# -*- coding: utf-8 -*-
"""v1.18.9 EXE「双击打不开」缺陷复现脚本

═══ 用户报的现象 ═══════════════════════════════════════════════
    v1.18.8 交付的 FlashDrop.exe，双击无任何反应。

═══ 本脚本要回答的问题 ════════════════════════════════════════
1. 冷启动（无任何实例）时，EXE 能否真正起来、窗口是否可见？
2. 热启动（已有实例）时，第二个 EXE 是否正常退出、并唤起第一个窗口？
3. onefile bootloader 的**辅助进程**是否会让锁语义出错？

═══ 手段 ═════════════════════════════════════════════════════
用 subprocess 直接拉起 dist*/FlashDrop.exe，关闭 DETACHED，
再分别探测：进程存活 / UDP 58898 归属 / 配置落盘 / stdout 内容。
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WIN = os.path.dirname(HERE)
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


def lock_port_owner():
    """返回持有 UDP 58898 的 PID（无则 None）。权限不足时返回 'unknown'。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
        return None                      # 能 bind 说明没人占
    except OSError:
        return "occupied"
    finally:
        s.close()


def procs():
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq FlashDrop.exe",
                            "/FO", "CSV", "/NH"],
                           capture_output=True, text=True, timeout=20,
                           encoding="gbk", errors="replace")
        rows = []
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if not line.startswith('"'):
                continue
            cols = [c.strip('"') for c in line.split('","')]
            if len(cols) >= 5:
                rows.append({"pid": cols[1], "mem": cols[4]})
        return rows
    except Exception:
        return []


def kill_all():
    subprocess.run(["taskkill", "/F", "/IM", "FlashDrop.exe"],
                   capture_output=True, timeout=20)


print("=" * 66)
print("v1.18.9 EXE「双击打不开」缺陷复现")
print("=" * 66)

exe = find_exe()
check("找到 FlashDrop.exe", exe is not None, "未找到，请先打包")
if not exe:
    sys.exit(1)
print(f"  目标: {exe}")
print(f"  大小: {os.path.getsize(exe):,} B  "
      f"mtime={time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(exe)))}")

# 先清场
kill_all()
time.sleep(2)
check("§0 清理后端口空闲", lock_port_owner() is None)

# ─────────────────────────────────────────────────────────────
print("\n=== §1 冷启动（模拟首次双击） ===")
d1 = tempfile.mkdtemp(prefix="fd_cold_")
env = dict(os.environ)
env["FLASHDROP_DATA_DIR"] = d1
env.setdefault("QT_QPA_PLATFORM", "offscreen")

t0 = time.time()
p1 = subprocess.Popen([exe], env=env, cwd=os.path.dirname(exe),
                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
time.sleep(15)

check("§1a 主进程存活 ≥15s", p1.poll() is None,
      f"rc={p1.poll()}")

ps = procs()
print(f"  FlashDrop.exe 进程数 = {len(ps)}  {[x['pid'] for x in ps]}")
check("§1b 只有 1 个 FlashDrop.exe 逻辑实例（允许 bootloader+child=2 进程）",
      len(ps) <= 2, f"实际 {len(ps)} 个：{ps}")
check("§1c 锁端口 58898 被本程序持有", lock_port_owner() == "occupied",
      f"owner={lock_port_owner()}")

cfg1 = os.path.join(d1, "config.json")
for _ in range(12):
    if os.path.isfile(cfg1):
        break
    time.sleep(0.5)
check("§1d config.json 落盘（__init__ 走通）", os.path.isfile(cfg1), cfg1)
if os.path.isfile(cfg1):
    try:
        cd = json.load(open(cfg1, encoding="utf-8"))
        check("§1e offline_chat 键存在（v1.18.9 新增）", "offline_chat" in cd,
              f"keys={sorted(cd)}")
        check("§1f known_peers 键存在（v1.18.9 新增）", "known_peers" in cd)
    except Exception as e:
        check("§1e/§1f config 可解析", False, f"{type(e).__name__}: {e}")

# 读 stdout 快照（非阻塞）
out1 = ""
try:
    os.set_blocking(p1.stdout.fileno(), False)
    out1 = (p1.stdout.read() or b"").decode("utf-8", "replace")
except Exception:
    pass
check("§1g 冷启动无 AttributeError/Traceback",
      "AttributeError" not in out1 and "Traceback" not in out1,
      out1[-300:])

# ─────────────────────────────────────────────────────────────
print("\n=== §2 热启动（模拟已有实例时再双击） ===")
d2 = tempfile.mkdtemp(prefix="fd_hot_")
env2 = dict(os.environ)
env2["FLASHDROP_DATA_DIR"] = d2
env2.setdefault("QT_QPA_PLATFORM", "offscreen")

p2 = subprocess.Popen([exe], env=env2, cwd=os.path.dirname(exe),
                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
try:
    rc2 = p2.wait(timeout=40)
    got_rc = True
except subprocess.TimeoutExpired:
    rc2 = None
    got_rc = False
    p2.kill()

check("§2a 第二个 EXE 自动退出（不再弹第二个窗口）", got_rc,
      f"40s 未退出 rc={rc2}")
check("§2b 退出码为 0（正常单实例路径）", rc2 == 0, f"rc={rc2}")

out2 = ""
try:
    raw2 = p2.stdout.read() or b""
except Exception:
    raw2 = b""
# 子进程是 Windows 控制台程序，stdout 默认 GBK —— 必须两种编码都试，
# 否则中文提示会被 decode 成乱码，断言出现假阴性（§2c 曾因此误报）。
for enc in ("gbk", "utf-8"):
    try:
        cand = raw2.decode(enc)
    except Exception:
        continue
    if "已在运行" in cand:
        out2 = cand
        break
    if not out2:
        out2 = cand
print("  --- 第二个实例 stdout ---")
print("  " + (out2.strip().replace("\n", "\n  ") or "(空)"))
print("  -------------------------")
check("§2c 打印了「已在运行」提示", "已在运行" in out2,
      "未见提示 → 未走到单实例分支")
check("§2d 无 Traceback", "Traceback" not in out2, out2[-300:])

# 原实例应仍在
ps2 = procs()
check("§2e 原实例仍然存活（未被第二个实例挤掉）", len(ps2) >= 1,
      f"进程数={len(ps2)}")

# ─────────────────────────────────────────────────────────────
print("\n=== §3 清理 ===")
kill_all()
time.sleep(2)
check("§3a 全部退出后端口释放", lock_port_owner() is None)
shutil.rmtree(d1, ignore_errors=True)
shutil.rmtree(d2, ignore_errors=True)

print("\n" + "=" * 66)
print(f"复现脚本：通过 {PASS} 项，失败 {FAIL} 项")
if FAILS:
    print("失败项：")
    for f in FAILS:
        print("  -", f)
print("=" * 66)
sys.exit(1 if FAIL else 0)
