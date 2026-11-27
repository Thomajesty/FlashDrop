# -*- coding: utf-8 -*-
"""v1.18.46 验收：ctypes 动态类泄漏根治 + 弹窗堆积 + 自动重启

真因：高频路径里动态创建 ctypes.Structure 类 ——
  ① netinfo._ctypes_get_adapters() 每次 new 3 个 Structure（_update_self_info
     每 5s 调用）② 看门狗 _mem_private_mb() 每次 new 1 个 PMC。
  ctypes 类型对象参与循环引用、gc 素数代才回收，深度回收清不掉。
实测修复前每轮 +70 个 CField/StgDict/PyCStructType，一晚上百万级常驻。

A 组 静态
B 组 运行时：高频调用不泄漏 ctypes 元对象 + 待发场景稳定 + 自动重启防重入

运行：python windows/tests/verify_v11846_ctypes_leak.py
"""
import gc
import os
import re
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WIN = os.path.dirname(HERE)
for p in (WIN,):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["FLASHDROP_DATA_DIR"] = tempfile.mkdtemp(prefix="fd_v11846_")

FAILS = []
N = 0


def ck(name, cond, extra=""):
    global N
    N += 1
    if not cond:
        FAILS.append(f"{name} | {extra}")
    print(("  ok  " if cond else " FAIL ") + name +
          ((" | " + str(extra)) if extra and not cond else ""), flush=True)


def rd(rel):
    with open(os.path.join(WIN, rel), encoding="utf-8") as f:
        return f.read()


def ctypes_meta_count():
    c = {}
    for o in gc.get_objects():
        try:
            n = type(o).__name__
            if n in ("CField", "StgDict", "PyCStructType"):
                c[n] = c.get(n, 0) + 1
        except Exception:
            pass
    return c


def group_a():
    net = rd("app/netinfo.py")
    mw = rd("app/ui/main_window.py")
    ck("A1 netinfo 结构体提到模块级",
       "class IP_ADDRESS_STRING(ctypes.Structure)" in net
       and net.index("class IP_ADDRESS_STRING") < net.index("def _ctypes_get_adapters"))
    ck("A2 看门狗 PMC 提到模块级单例",
       "class _PMC(ctypes.Structure)" in mw
       and mw.index("class _PMC") < mw.index("def _mem_private_mb")
       and "            class PMC(ctypes.Structure)" not in mw)
    ck("A3 自动重启 + 防重入（替代反复弹窗）",
       "def _auto_restart" in mw and "_restart_pending" in mw
       and "600" in mw)  # 10 分钟冷却
    ck("A4 toast 即时析构",
       "lambda ll=lbl: dispose_widget(ll)" in mw)
    ver = re.search(r'__version__ = "(1\.18\.\d+)"', rd("app/__init__.py"))
    ck("A5 版本 >= 1.18.46", bool(ver) and
       tuple(int(x) for x in ver.group(1).split(".")) >= (1, 18, 46),
       ver and ver.group(1))


def group_b():
    from app import netinfo
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer, QEventLoop
    from app.config import Config
    from app.node import FlashNode
    from app.ui.main_window import MainWindow

    # B1: netinfo 高频调用 1000 次（≈83 分钟真实运行）
    gc.collect()
    base = ctypes_meta_count()
    for i in range(1000):
        netinfo.get_local_ifaces()
    gc.collect()
    after = ctypes_meta_count()
    delta = sum(after.get(k, 0) - base.get(k, 0) for k in base)
    ck("B1 get_local_ifaces ×1000 ctypes 元对象增量 < 10",
       delta < 10, f"{base} -> {after} (delta={delta})")

    # B2: MainWindow 看门狗高频调用 1000 次
    app = QApplication.instance() or QApplication(sys.argv)
    tmp = tempfile.mkdtemp(prefix="fd_v11846_cfg_")
    cfg = Config(os.path.join(tmp, "a.json"))
    cfg.data.update({"device_id": "aaaaaaaaaaaaaaaa", "name": "A",
                     "port": 59231, "save_dir": os.path.join(tmp, "s"),
                     "cache_dir": os.path.join(tmp, "c"),
                     "notify_on_receive": False, "offline_chat": True})
    cfg.save()
    node = FlashNode(cfg)
    win = MainWindow(cfg, node)
    win.resize(1000, 760); win.show()
    for _ in range(6):
        app.processEvents()
    gc.collect()
    base = ctypes_meta_count()
    for i in range(1000):
        win._mem_private_mb()
    gc.collect()
    after = ctypes_meta_count()
    delta = sum(after.get(k, 0) - base.get(k, 0) for k in base)
    ck("B2 _mem_private_mb ×1000 ctypes 元对象增量 < 10",
       delta < 10, f"{base} -> {after} (delta={delta})")

    # B3: 待发场景（用户截图的 2 待发 + 4 离线）稳定
    node.start(); win.bridge.start()
    time.sleep(6)  # 等启动扫描 task 归位
    peers = [{"id": "aa", "name": "A", "platform": "android",
              "ips": ["192.0.2.1"], "online": True, "connected": False}]
    for i in range(4):
        peers.append({"id": f"off{i}", "name": f"离线{i}",
                      "platform": "android", "ips": [],
                      "online": False, "connected": False})
    win._on_peers(peers)
    for i in range(2):
        p = os.path.join(tmp, f"p{i}.bin")
        with open(p, "wb") as f:
            f.write(b"x" * 1024)
        win._pending_files.append({"type": "file", "paths": [p], "targets": [],
                                   "mid": f"mid{i}", "ts": int(time.time() * 1000)})
    win._start_pending_retry()
    gc.collect()
    obj0 = len(gc.get_objects())
    meta0 = ctypes_meta_count()
    for rnd in range(30):
        for i in range(10):
            win._on_peers(peers)
        win._update_self_info()
        win._mem_watchdog_tick()
        for _ in range(3):
            app.processEvents()
    gc.collect()
    obj1 = len(gc.get_objects())
    meta1 = ctypes_meta_count()
    meta_delta = sum(meta1.get(k, 0) - meta0.get(k, 0) for k in meta0)
    ck("B3 待发场景 ×30 轮 ctypes 元对象不增",
       meta_delta < 10, f"meta {meta0} -> {meta1} (delta={meta_delta})")
    ck("B3 待发场景 py 对象不累积",
       obj1 - obj0 < 5000, f"{obj0} -> {obj1}")
    ck("B3 待发条目保持恒定", len(win._pending_files) == 2,
       str(len(win._pending_files)))


def main():
    print("=" * 66)
    print("v1.18.46 ctypes 动态类泄漏根治验收")
    print("=" * 66)
    group_a()
    group_b()
    print("\n===== 结果: %d/%d %s =====" %
          (N - len(FAILS), N, "ALL PASS" if not FAILS else "FAIL"))
    for f in FAILS:
        print("  FAIL:", f)
    if FAILS:
        sys.exit(1)


if __name__ == "__main__":
    main()
