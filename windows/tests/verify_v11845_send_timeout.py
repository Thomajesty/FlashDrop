# -*- coding: utf-8 -*-
"""v1.18.45 验收：同步发送超时 cancel（慢泄漏根治）

根因：send_text_sync / send_files_sync 用 fut.result(timeout=...) 等待，
超时抛异常时 fut 从不 cancel —— asyncio 协程在 loop 里继续跑完
（_wait_conn 15s + ACK 12s + 文件传输重试退避），每个协程帧持有
conn/future/512KB 文件块。待发队列每 10s 重试，离线设备一晚上
数千个泄漏协程 → 数 GB 内存。

A 组 静态：两处超时分支都 cancel
B 组 运行时：60 次超时后 asyncio task 与 ack_waiters 不累积

运行：python windows/tests/verify_v11845_send_timeout.py
"""
import asyncio
import gc
import os
import re
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WIN = os.path.dirname(HERE)
for p in (WIN,):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["FLASHDROP_DATA_DIR"] = tempfile.mkdtemp(prefix="fd_v11845_")

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


def group_a():
    node = rd("app/node.py")
    ck("A1 concurrent.futures 导入",
       "import concurrent.futures" in node)
    # 两处 fut.result(timeout=...) 都必须跟 TimeoutError + cancel
    ck("A2 send_text_sync 超时 cancel",
       "except concurrent.futures.TimeoutError:" in node
       and node.count("fut.cancel()") >= 2,
       f"cancel 次数={node.count('fut.cancel()')}")
    ck("A3 send_files_sync 超时 cancel（文件块 512KB 释放）",
       node.count("except concurrent.futures.TimeoutError:") == 2)
    ck("A4 _send_file_to finally 取消 ready_task/ok_task 子任务",
       "locals().get(\"ready_task\")" in node
       and "locals().get(\"ok_task\")" in node
       and "_t.cancel()" in node)
    ver = re.search(r'__version__ = "(1\.18\.\d+)"', rd("app/__init__.py"))
    ck("A4 版本 >= 1.18.45", bool(ver) and
       tuple(int(x) for x in ver.group(1).split(".")) >= (1, 18, 45),
       ver and ver.group(1))


def group_b():
    from app.config import Config
    from app.node import FlashNode

    tmp = tempfile.mkdtemp(prefix="fd_v11845_cfg_")
    cfg = Config(os.path.join(tmp, "a.json"))
    cfg.data.update({"device_id": "aaaaaaaaaaaaaaaa", "name": "A",
                     "port": 59181, "save_dir": os.path.join(tmp, "s"),
                     "cache_dir": os.path.join(tmp, "c"),
                     "notify_on_receive": False})
    cfg.save()
    node = FlashNode(cfg)
    node.start()
    time.sleep(0.5)

    async def stat():
        return (len([t for t in asyncio.all_tasks() if not t.done()]),
                len(node.ack_waiters))

    def get_stat():
        f = asyncio.run_coroutine_threadsafe(stat(), node.loop)
        return f.result(timeout=5)

    time.sleep(6)  # 等启动扫描 task 跑完（实测 5 秒时仍有 536 个 session 在退出）
    base_tasks, base_ack = get_stat()
    ck("B0 启动扫描结束后 task 归位（<20）", base_tasks < 20,
       str(base_tasks))

    # 桩掉 _wait_conn：模拟离线设备（连接永远挂住）
    async def hang_conn(pid, timeout):
        await asyncio.sleep(3600)
    node._wait_conn = hang_conn

    def worker():
        for i in range(60):
            try:
                node.send_text_sync(["bbbbbbbbbbbbbbbb"], "test", timeout=0.2)
            except Exception:
                pass
    t = threading.Thread(target=worker)
    t.start()
    t.join(timeout=40)
    time.sleep(1)
    gc.collect()
    after_tasks, after_ack = get_stat()
    ck("B1 60 次超时后 task 不累积（<20）", after_tasks < 20,
       f"{base_tasks} -> {after_tasks}")
    ck("B2 ack_waiters 不累积", after_ack == 0, str(after_ack))


def main():
    print("=" * 66)
    print("v1.18.45 同步发送超时 cancel 验收（慢泄漏根治）")
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
