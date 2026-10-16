# -*- coding: utf-8 -*-
"""v1.18.15 行为测试 —— Windows 端待发队列「确认送达才移除」。

用户反馈：安卓给电脑发离线消息，等电脑上线上「对方收不到、发送端也失败」。

根因（两端一致）：``_flush_pending()`` 调 ``bridge.send_text()``（**异步**，
内部还要 ``_wait_conn`` 等 TCP 最多 15s、再等 ack 12s）后，**立刻**把条目
从 ``_pending_files`` 删掉并落盘。设备刚上线时 UDP 已判在线 → 触发 flush，
但 TCP 往往还没建好 → 发送失败 → **条目已删，消息永久丢失**；而队列没有
任何重试机制，等于必丢。

本测试**真跑 MainWindow._flush_pending()**，把 bridge 的 send_text_sync 换成
脚本化的假实现，验证队列的「保留 / 移除」行为。

运行：python tests/verify_v11815_pending.py
"""
import os
import sys
import tempfile
import time

os.environ.pop("QT_QPA_PLATFORM", None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

tmp = tempfile.mkdtemp(prefix="fd_v11815_")
os.environ["FLASHDROP_DATA_DIR"] = tmp

from app.config import Config
from app.node import FlashNode
from app.ui.main_window import MainWindow

P, F = [], []


def check(name, cond, detail=""):
    (P if cond else F).append(name)
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", name,
                          ("   " + detail) if (detail and not cond) else ""))


PEER = "winpc001122334455"


def new_win():
    cfg = Config()
    cfg["theme"] = "light"
    cfg["save_dir"] = tmp
    cfg["pending_files"] = []
    w = MainWindow(cfg, FlashNode(cfg))
    w.resize(1000, 700)
    w.show()
    for _ in range(6):
        app.processEvents()
    # 造一个"在线"的对方
    w.peers = {PEER: {"id": PEER, "name": "测试电脑", "online": True,
                      "ips": ["192.168.1.9"], "last_seen": time.time()}}
    w._pending_files = []
    w.cfg["pending_files"] = []
    return w


def text_entry(text, targets=None, broadcast=True):
    return {"type": "text", "text": text, "targets": targets or [],
            "broadcast": broadcast, "mid": "m-" + text}


def pump(w, timeout=8.0):
    """等本轮 flush 结束（_flush_running 回到 False）"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        app.processEvents()
        if not getattr(w, "_flush_running", False):
            # 再多转几圈，确保信号已处理完
            for _ in range(5):
                app.processEvents()
            return True
        time.sleep(0.02)
    return False


def install_fake_bridge(w, mode, during=None, captured=None):
    """把 bridge 的发送换成脚本化假实现"""
    def send_text_sync(targets, text, timeout=45.0):
        mid = "real-" + text
        if captured is not None:
            captured["targets"] = list(targets)
            captured["text"] = text
            captured["mid"] = mid
            captured["calls"] = captured.get("calls", 0) + 1
        if during is not None:
            during()
        return mid, {t: mode for t in targets}

    def send_files(targets, paths):
        if captured is not None:
            captured["files"] = captured.get("files", 0) + len(paths)

    if captured is None:
        captured = {}
    w.bridge.send_text_sync = send_text_sync
    w.bridge.send_files = send_files
    return captured


print("=" * 70)
print("v1.18.15 Windows 待发队列行为验收")
print("=" * 70)

# ---------- §1 全部送达 → 条目移除 ----------
print("\n=== §1 全部送达 → 条目应被移出队列 ===")
w = new_win()
cap = install_fake_bridge(w, "ok")
w._pending_files = [text_entry("你好")]
w.cfg["pending_files"] = w._pending_files
w._flush_pending()
ok = pump(w)
check("flush 正常结束", ok)
check("队列已清空", len(w._pending_files) == 0,
      "实际剩 %d 条" % len(w._pending_files))
check("确实调用了 send_text_sync", cap.get("calls") == 1)
check("文本原样送达", cap.get("text") == "你好")
check("群发时目标是在线设备", cap.get("targets") == [PEER])

# ---------- §2 全部失败 → 条目必须保留（核心回归） ----------
print("\n=== §2 全部失败（连接未就绪）→ 条目必须保留 ===")
w = new_win()
cap = install_fake_bridge(w, "failed")
w._pending_files = [text_entry("离线消息")]
w.cfg["pending_files"] = w._pending_files
w._flush_pending()
pump(w)
check("★ 队列保留 1 条（旧实现会错删成 0）", len(w._pending_files) == 1,
      "实际剩 %d 条" % len(w._pending_files))
check("已安排周期重试", getattr(w, "_pending_retry", None) is not None
      and w._pending_retry.isActive())

# ---------- §3 超时同样保留 ----------
print("\n=== §3 ack 超时 → 条目同样保留 ===")
w = new_win()
install_fake_bridge(w, "timeout")
w._pending_files = [text_entry("会超时的消息")]
w.cfg["pending_files"] = w._pending_files
w._flush_pending()
pump(w)
check("★ 队列保留 1 条", len(w._pending_files) == 1,
      "实际剩 %d 条" % len(w._pending_files))

# ---------- §4 目标尚未上线 → 保留且不调用发送 ----------
print("\n=== §4 无在线设备 → 条目保留等待，不调用发送 ===")
w = new_win()
cap = install_fake_bridge(w, "ok")
w.peers = {}
w._pending_files = [text_entry("等对方上线", [PEER], broadcast=False)]
w.cfg["pending_files"] = w._pending_files
w._flush_pending()
pump(w)
check("★ 队列保留 1 条", len(w._pending_files) == 1)
check("没有调用发送", cap.get("calls", 0) == 0)

# ---------- §5 flush 期间新增的条目不被误删 ----------
print("\n=== §5 flush 进行中又入队一条 → 新条目不能被误删 ===")
w = new_win()
added = {}


def during():
    """模拟用户在对端连接建立的同时又加了一条待发"""
    added["entry"] = text_entry("第二条(发送期间新增)")
    w._pending_files.append(added["entry"])


cap = install_fake_bridge(w, "ok", during=during)
w._pending_files = [text_entry("第一条")]
w.cfg["pending_files"] = w._pending_files
w._flush_pending()
pump(w)
check("★ 只剩新增的那条（旧的已送达被移除）", len(w._pending_files) == 1,
      "实际剩 %d 条" % len(w._pending_files))
if added.get("entry") is not None and w._pending_files:
    check("留下的是新增条目",
          w._pending_files[0].get("text") == "第二条(发送期间新增)",
          repr(w._pending_files[0].get("text")))

# ---------- §6 队列清空后停掉重试 ----------
print("\n=== §6 队列清空后停止重试（避免空转） ===")
w = new_win()
install_fake_bridge(w, "ok")
w._pending_files = [text_entry("一次成功")]
w.cfg["pending_files"] = w._pending_files
w._flush_pending()
pump(w)
check("队列空", len(w._pending_files) == 0)
t = getattr(w, "_pending_retry", None)
check("重试定时器已停止", t is None or not t.isActive())

# ---------- §7 手动「立即重发」也不再先删条目 ----------
print("\n=== §7 手动立即重发 → 失败时同样保留 ===")
w = new_win()
install_fake_bridge(w, "failed")
w._pending_files = [text_entry("手动重发")]
w.cfg["pending_files"] = w._pending_files
w._pending_retry_now("m-手动重发")
pump(w)
check("★ 手动重发失败后条目仍在", len(w._pending_files) == 1,
      "实际剩 %d 条" % len(w._pending_files))

print()
print("=" * 70)
if F:
    print("失败项：")
    for f in F:
        print("  - %s" % f)
print("v1.18.15 Windows 待发队列验收：通过 %d 项，失败 %d 项" % (len(P), len(F)))
print("=" * 70)
sys.exit(1 if F else 0)