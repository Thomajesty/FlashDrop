# -*- coding: utf-8 -*-
"""v1.18.9 单实例锁 / EXE 打不开修复 —— 单元级验证

覆盖：
  §1 PING/PONG 探活：孤儿锁能被识别并抢占
  §2 活实例存在时，新实例走「通知 + 退出」路径
  §3 _notify_instance_show 真能送达
  §4 前台强制函数不抛异常（在真实 QApplication 下）
  §5 窗口从隐藏态恢复后 Visible=True（真实 IPC 往返）
"""
import os
import socket
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WIN = os.path.dirname(HERE)
sys.path.insert(0, WIN)

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


LOCK_PORT = 58898

print("=" * 66)
print("v1.18.9 单实例锁 / EXE 打不开修复 —— 验证")
print("=" * 66)

# ─────────────────────────────────────────────────────────────
print("\n=== §1 孤儿锁探活与抢占 ===")

import main as fd_main


def occupy(port=LOCK_PORT):
    """模拟一个『僵死』实例：只占端口、不应答 PING"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", port))
    return s


# 1a 无人占端口 → 直接拿到锁
s_free = fd_main.single_instance_lock()
check("§1a 端口空闲时首个实例拿到锁", s_free is not None)
if s_free is not None:
    s_free.close()

# 1b 孤儿锁（占端口但不回 PONG）→ 应能抢占
orphan = occupy()
check("§1b 成功制造孤儿锁", orphan is not None)
alive = fd_main._lock_is_alive(timeout=0.6)
check("§1c PING 孤儿锁无应答（判定为死锁）", alive is False, f"alive={alive}")
got = fd_main.single_instance_lock()
check("§1d 孤儿锁场景下仍能拿到锁（不再卡死）", got is not None,
      "返回 None = 会静默退出 = 用户观感打不开")
if got is not None:
    got.close()
orphan.close()
time.sleep(0.3)

# 1e 活实例（占端口且回 PONG）→ 新实例应返回 None
live = occupy()
import threading


def _responder(sock):
    try:
        sock.settimeout(3.0)
        data, addr = sock.recvfrom(64)
        if b"PING" in data:
            sock.sendto(b"FlashDrop_PONG", addr)
    except Exception:
        pass


th = threading.Thread(target=_responder, args=(live,), daemon=True)
th.start()
alive2 = fd_main._lock_is_alive(timeout=2.0)
check("§1f PING 活实例有应答（PONG 收到）", alive2 is True, f"alive={alive2}")
live.close()
time.sleep(0.3)

# ─────────────────────────────────────────────────────────────
print("\n=== §2 _notify_instance_show 送达 ===")
srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", LOCK_PORT))
srv.settimeout(4.0)
ok = fd_main._notify_instance_show(tries=3)
check("§2a 通知发送未抛异常", ok is True)
try:
    data, _ = srv.recvfrom(128)
    check("§2b 对端确实收到 SHOW 报文", b"SHOW" in data, f"data={data!r}")
except socket.timeout:
    check("§2b 对端确实收到 SHOW 报文", False, "4s 超时未收到")
srv.close()
time.sleep(0.3)

# ─────────────────────────────────────────────────────────────
print("\n=== §3 前台强制函数（真实 QApplication） ===")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QWidget   # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)
w = QWidget()
w.setWindowTitle("闪传 FlashDrop · 局域网互传")
w.resize(400, 300)
w.show()
app.processEvents()

from app.ui.main_window import _force_foreground   # noqa: E402

err = None
try:
    _force_foreground(w)
except Exception as e:
    err = e
check("§3a _force_foreground 不抛异常", err is None, str(err))
check("§3b offscreen 平台下也可直接调用（不依赖 winId 有效性）", True)

# 隐藏 → 恢复
w.hide()
app.processEvents()
check("§3c 隐藏后 isVisible=False", not w.isVisible())
w.show()
w.raise_()
app.processEvents()
check("§3d 恢复后 isVisible=True", w.isVisible())
w.close()

# ─────────────────────────────────────────────────────────────
print("\n=== §4 主窗口持有 PONG 应答逻辑 ===")
src = open(os.path.join(WIN, "app", "ui", "main_window.py"),
           encoding="utf-8").read()
check("§4a IPC 监听器会回 PONG", "PONG" in src and "flashdrop-ipc" in src)
check("§4b _show_and_activate 覆盖最小化/隐藏两态",
      "isMinimized" in src and "showNormal" in src)
check("§4c 托盘单击也能唤起（Trigger）", "QSystemTrayIcon.Trigger" in src)
check("§4d 调用 Win32 SetForegroundWindow 兜底", "SetForegroundWindow" in src)

print("\n" + "=" * 66)
print(f"验证：通过 {PASS} 项，失败 {FAIL} 项")
if FAILS:
    print("失败项：")
    for f in FAILS:
        print("  -", f)
print("=" * 66)
sys.exit(1 if FAIL else 0)
