# -*- coding: utf-8 -*-
"""v1.18.18 双节点传输端到端测试（内存双向管道，无网络栈依赖）

为什么不用真实 socket
--------------------
本机可能同时运行着其他 FlashDrop 实例（如开发机上正在跑的 EXE），
它们会通过 UDP 发现/子网扫描连上测试节点，抢占 conns 槽位，
导致"连上了但数据不通"这类**与被测代码无关**的假失败（已实际踩到）。

因此这里用内存管道直连两个 FlashNode：每个节点的 reader_loop 消费
对端"写"入的字节，行为与真实 socket 完全一致（同一套 read_frame 解析），
但连接归属唯一、结果确定，且不占端口、不受邻居干扰。

运行：python windows/tests/verify_v11818_resume_net.py
"""
import asyncio
import hashlib
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WIN = os.path.dirname(HERE)
if WIN not in sys.path:
    sys.path.insert(0, WIN)

from app import resume as R            # noqa: E402
from app.config import Config          # noqa: E402
from app.node import FlashNode, Conn, Peer  # noqa: E402

FAILS = []
N = 0


def ck(name, cond, extra=""):
    global N
    N += 1
    if not cond:
        FAILS.append(f"{name} | {extra}")
    print(("  ok  " if cond else " FAIL ") + name +
          ((" | " + str(extra)) if extra and not cond else ""))


def wait_for(fn, timeout=20, interval=0.1):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if fn():
            return True
        time.sleep(interval)
    return False


def mkfile(path, size, seed=b"x"):
    h = hashlib.sha256(seed).digest()
    buf = bytearray()
    while len(buf) < size:
        h = hashlib.sha256(h).digest()
        buf.extend(h)
    data = bytes(buf[:size])
    with open(path, "wb") as f:
        f.write(data)
    return hashlib.md5(data).hexdigest()


def md5_file(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


class Collector:
    def __init__(self):
        self.evts = []

    def __call__(self, e):
        self.evts.append(e)

    def clear(self):
        self.evts = []


def mk_node(tmp, tag, events):
    os.environ["FLASHDROP_DEVICE_ID"] = (tag * 2)[:16]
    try:
        cfg = Config(os.path.join(tmp, f"cfg_{tag}.json"))
        cfg.data["name"] = tag
        cfg.data["port"] = 58899
        cfg.data["save_dir"] = os.path.join(tmp, f"save_{tag}")
        cfg.data["cache_dir"] = os.path.join(tmp, f"cache_{tag}")
        cfg.data["auto_accept"] = True
        cfg.data["known_subnets"] = []
        cfg.data["manual_peers"] = []
        cfg.save()
        return FlashNode(cfg, emit=events)
    finally:
        os.environ.pop("FLASHDROP_DEVICE_ID", None)


class PipeWriter:
    """喂给 StreamReader 的写入端（替代 socket writer）

    ★ 必须实现 drain()：FlashNode.Conn.send_frame 里有
    `await self.writer.write(frame); await self.writer.drain()`，
    缺 drain 会抛 AttributeError 被上层吞成"发送失败"。
    """
    # asyncio.StreamReader 底层缓冲上限，喂太多会触发流控断言
    LIMIT = 1 << 24

    def __init__(self, reader):
        self.reader = reader
        self._closed = False

    def write(self, data):
        if self._closed:
            raise ConnectionError("pipe closed")
        try:
            self.reader.feed_data(data)
        except Exception:
            raise ConnectionError("pipe feed failed")

    async def drain(self):
        # 内存管道无需背压；让出一次事件循环让对端有机会消费
        await asyncio.sleep(0)

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.reader.feed_eof()
        except Exception:
            pass

    def is_closing(self):
        return self._closed

    def get_extra_info(self, name):
        return ("127.0.0.1", 0) if name == "peername" else None


def connect_pair(a: FlashNode, b: FlashNode, a_id: str, b_id: str):
    """在共享 loop 上建立一条内存双向管道。

    ★ 关键：A 写的内容喂进 **B 的 reader**，B 写的内容喂进 **A 的 reader**。
    若两侧各自建 reader 而不交叉 feed，读到的永远是空流
    （这正是第一版"连上了但零数据"的根因）。
    """
    async def build():
        rd_a = asyncio.StreamReader()   # A 读（B 写进来）
        rd_b = asyncio.StreamReader()   # B 读（A 写进来）
        _wire(a, b, a_id, b_id, rd_a, rd_b)
    asyncio.run_coroutine_threadsafe(build(), a.loop).result(15)
    return a.conns.get(b_id), b.conns.get(a_id)


def _wire(a, b, a_id, b_id, rd_a, rd_b):
    """把管道两端挂到两个节点上（必须在共享 loop 内调用）"""
    conn_a = Conn(rd_a, PipeWriter(rd_b), incoming=False)
    conn_a.peer_id = b_id
    conn_a.hello_got = True
    a.conns[b_id] = conn_a
    pa = Peer(b_id)
    pa.name = "设备B"
    pa.platform = "android"
    pa.last_seen = time.time()
    pa.tcp_port = 58899
    a.peers[b_id] = pa

    conn_b = Conn(rd_b, PipeWriter(rd_a), incoming=True)
    conn_b.peer_id = a_id
    conn_b.hello_got = True
    b.conns[a_id] = conn_b
    pb = Peer(a_id)
    pb.name = "设备A"
    pb.platform = "windows"
    pb.last_seen = time.time()
    pb.tcp_port = 58899
    b.peers[a_id] = pb

    a.loop.create_task(a._reader_loop(conn_a))
    a.loop.create_task(b._reader_loop(conn_b))
    return conn_a, conn_b


def start_nodes(n1: FlashNode, n2: FlashNode):
    """让两个节点**共用同一个 asyncio loop**。

    ★ 为什么共用 loop：asyncio.StreamReader / asyncio.Lock 都绑定创建时的
    loop。本测试用内存管道模拟 TCP（避免本机其他 FlashDrop 实例通过 UDP
    发现/子网扫描连上测试节点、抢占连接槽位导致假失败 —— 已实际踩到）。
    两个节点共用一个 loop 后，管道两端的 reader/writer/send_lock 全部
    同 loop，行为与真实单线程 socket 完全一致，且连接归属唯一、结果确定。
    每个节点各自持有独立的 conns/peers/config/state，互不干扰。
    """
    holder = {}

    async def boot():
        loop = asyncio.get_running_loop()
        for n in (n1, n2):
            n.loop = loop
            n._started.set()
            # 关闭自动发现/扫描/心跳等后台任务：真实 socket 相关，
            # 本测试不需要（也避免与本机真实实例抢端口）
            n._stopping = False
            # ★ 关键隔离：_wait_conn 会调 _ensure_connected 去建**真实 TCP**。
            # 本机若跑着真 FlashDrop 实例，A 会直接把文件传到那个真设备上，
            # 导致"断链根本没发生""对方没按预期处理"这类假失败（已实际踩到：
            # 中断计数为 0，因为文件根本没发给测试节点 B）。
            # 打桩为空实现 —— 本测试的连接只由 _wire() 内存管道提供。
            n._ensure_connected = lambda *args, **kw: None
        holder["loop"] = loop
        await asyncio.sleep(3600)

    def run():
        try:
            asyncio.run(boot())
        except Exception:
            pass

    import threading
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t0 = time.time()
    while holder.get("loop") is None and time.time() - t0 < 10:
        time.sleep(0.05)
    return t


def main():
    print("=" * 70)
    print("v1.18.18 双节点传输（内存管道）")
    print("=" * 70)
    tmp = tempfile.mkdtemp(prefix="fd_net_")
    ev_a, ev_b = Collector(), Collector()
    a = mk_node(tmp, "nodeA", ev_a)
    b = mk_node(tmp, "nodeB", ev_b)
    aid = a.device_id
    bid = b.device_id
    ta = start_nodes(a, b)
    try:
        connect_pair(a, b, aid, bid)
        ck("A/B 通过内存管道连通", bid in a.conns and aid in b.conns)
        src = os.path.join(tmp, "f.bin")
        size = 4 * R.RESUME_CHUNK + 1234
        md5 = mkfile(src, size, b"net")

        # ---- 场景 A：一次成功 ----
        ev_a.clear()
        ev_b.clear()
        tid = "netA"

        async def send1():
            a.out_states[tid] = {bid: "sending"}
            a._send_info[tid] = {"name": "f.bin", "size": size,
                                 "mime": "application/octet-stream",
                                 "targets": [bid], "src_path": src}
            await a._send_file_to(bid, tid, src, "f.bin", size,
                                  "application/octet-stream")
        asyncio.run_coroutine_threadsafe(send1(), a.loop).result(60)
        done = [e for e in ev_b.evts
                if e.get("kind") == "recv" and e.get("state") == "done"]
        ck("B 接收完成", bool(done))
        ok = [e for e in ev_a.evts if e.get("state") == "ok" and e.get("tid") == tid]
        ck("A 收到 ok", bool(ok), [e.get("state") for e in ev_a.evts[-5:]])
        if done:
            p = done[-1].get("path")
            ck("文件 MD5 一致", os.path.isfile(p) and md5_file(p) == md5)
            ck("文件大小正确", os.path.isfile(p) and os.path.getsize(p) == size)
        ck("协商为 chunk 模式",
           any(e.get("total_chunks") == R.total_chunks(size)
               for e in ev_b.evts if e.get("kind") == "recv"))

        # ---- 场景 B：传输中断 → 自动重试 → 断点续传 ----
        # v1.18.18：**重试已内建在 _send_file_to 里**（同 tid + 指数退避），
        # 所以这里不需要（也不应该）测试自己再手动重发一遍 ——
        # 那样验证的是测试脚本而不是产品代码。
        # 真实链路里重试需要连接重建（_wait_conn 会 _ensure_connected），
        # 内存管道没有网络栈，所以在重试前手动重建一次管道，
        # 模拟"设备重新上线"，其余全部走产品代码路径。
        print("\n[断点续传] 中断后自动重试并只补缺失块")
        ev_a.clear()
        ev_b.clear()
        tid2 = "netB"
        # 让 B 侧在收到第 3 块后主动断链（模拟网络中断）
        orig_bin = b._on_bin
        state = {"n": 0, "cut": False}

        async def cut_bin(conn, t, data, index=-1):
            await orig_bin(conn, t, data, index)
            if t == tid2 and index >= 0:
                state["n"] += 1
                if state["n"] >= 3 and not state["cut"]:
                    state["cut"] = True
                    ib = b.inbounds.get((aid, tid2))
                    if ib:
                        b._flush_bitmap(ib, force=True)
                        b._cleanup_inbound(ib, drop_state=False)
                    conn.alive = False
                    raise ConnectionError("模拟网络中断")
        b._on_bin = cut_bin
        # 缩短重试退避，让测试跑得快
        import app.node as N_
        old_base = N_.SEND_RETRY_BASE
        N_.SEND_RETRY_BASE = 1.05
        # ★ 不要提前摘连接：第一次尝试必须真正把块发出去，
        #   由 B 侧 cut_bin 在收满3 块后切链 —— 这才是"传输中断"。
        #   （曾经提前 pop 掉连接，结果第一次尝试直接判"设备不在线"，
        #   B 一个块都没收到，中断计数恒为 0。）
        bmp_mid = {}

        # 在重试真正发起的那一刻重建管道（模拟设备重新上线）。
        # 必须与 send2 跑在**同一个 loop**：StreamReader 绑定创建时的 loop。
        async def rewire():
            # 等第一次尝试失败并进入退避 sleep
            for _ in range(100):
                if state["cut"]:
                    break
                await asyncio.sleep(0.05)
            # B 侧恢复为正常处理（网络已通）
            b._on_bin = orig_bin
            rd_a = asyncio.StreamReader()   # A 读
            rd_b = asyncio.StreamReader()   # B 读
            _wire(a, b, aid, bid, rd_a, rd_b)

        async def send2():
            rewire_task = a.loop.create_task(rewire())
            a.out_states[tid2] = {bid: "sending"}
            a._send_info[tid2] = {"name": "f.bin", "size": size,
                                  "mime": "application/octet-stream",
                                  "targets": [bid], "src_path": src}
            await a._send_file_to(bid, tid2, src, "f.bin", size,
                                  "application/octet-stream")
            rewire_task.cancel()
        asyncio.run_coroutine_threadsafe(send2(), a.loop).result(90)
        N_.SEND_RETRY_BASE = old_base
        ck("中断确实发生过（收满3 块后断链）", state["cut"] and state["n"] >= 3,
           state)

        # 自动重试已经跑完，验证接收端结果
        done2 = [e for e in ev_b.evts
                 if e.get("kind") == "recv" and e.get("state") == "done"
                 and e.get("tid") == tid2]
        ck("自动重试后续传完成", bool(done2),
           [e.get("state") for e in ev_b.evts[-6:]])
        if done2:
            p = done2[-1].get("path")
            ck("续传文件 MD5 一致", os.path.isfile(p) and md5_file(p) == md5)
        ck("发出过 retrying 状态",
           any(e.get("state") == "retrying" for e in ev_a.evts),
           [e.get("state") for e in ev_a.evts if e.get("state") in
            ("retrying", "ok", "failed")])
        ck("A 最终 ok",
           any(e.get("state") == "ok" and e.get("tid") == tid2
               for e in ev_a.evts),
           [e.get("state") for e in ev_a.evts[-5:]])
        logs = [e.get("msg") for e in ev_a.evts if e.get("event") == "log"]
        ck("续传日志出现跳过块数",
           any("断点续传" in (m or "") for m in logs), logs[-3:])
        ck("成功后位图已清理",
           R.ChunkMap.load(b.cfg.cache_dir, tid2, R.total_chunks(size)).count() == 0)

        # ---- 场景 C：接收端拒绝 → 不重试 ----
        #走**手动确认**路径：B 收到 FILE_START 后停在 confirm 态，
        # 测试显式调 reject_inbound()，验证 A 立即失败且**不重试**
        #（若重试会白白再敲一次，用户体验很差）。
        print("\n[不可重试] 对方拒绝时立即失败不重试")
        b.cfg.data["auto_accept"] = False
        ev_a.clear()
        ev_b.clear()
        tid3 = "netC"
        src3 = os.path.join(tmp, "small.bin")
        mkfile(src3, 100, b"c")

        # 缩短"等待 FILE_OK"超时：拒绝场景里 A 会走到 ok_fut 等待，
        # 默认 SEND_WAIT_OK=300s 会让测试假超时。
        import app.node as N_
        old_ok = N_.SEND_WAIT_OK
        N_.SEND_WAIT_OK = 8.0
        try:
            async def send3():
                # 后台任务：B 一进入待确认态就立刻拒绝（模拟用户点"拒绝"）
                async def auto_reject():
                    for _ in range(200):
                        ib = b.inbounds.get((aid, tid3))
                        if ib and not ib.started and not ib.done:
                            await b._reject_inbound_task(tid3)
                            return
                        await asyncio.sleep(0.05)
                rj = a.loop.create_task(auto_reject())
                a.out_states[tid3] = {bid: "sending"}
                a._send_info[tid3] = {"name": "small.bin", "size": 100,
                                      "mime": "application/octet-stream",
                                      "targets": [bid], "src_path": src3}
                await a._send_file_to(bid, tid3, src3, "small.bin", 100,
                                      "application/octet-stream")
                rj.cancel()
            asyncio.run_coroutine_threadsafe(send3(), a.loop).result(40)
        finally:
            N_.SEND_WAIT_OK = old_ok

        offers = [e for e in ev_b.evts if e.get("state") == "confirm"]
        ck("接收端进入待确认态", bool(offers),
           [e.get("state") for e in ev_b.evts[-4:]])
        refused = [e for e in ev_b.evts if e.get("state") == "refused"]
        ck("接收端标记已拒绝", bool(refused),
           [e.get("state") for e in ev_b.evts[-4:]])
        astates = [e.get("state") for e in ev_a.evts
                   if e.get("state") in ("retrying", "ok", "failed", "refused")]
        ck("发送端标记失败/拒绝", any(s in astates
                                for s in ("failed", "refused")), astates)
        ck("拒绝后不重试（无 retrying）", "retrying" not in astates, astates)
        ck("拒绝只发生一次（未反复敲）", astates.count("refused") <= 1
           and astates.count("failed") <= 1, astates)
    except Exception as e:
        import traceback
        traceback.print_exc()
        FAILS.append(f"异常: {e}")
    finally:
        try:
            os.environ["FLASHDROP_STOP"] = "1"
        except Exception:
            pass

    print("\n" + "=" * 70)
    print(f"结果：{N - len(FAILS)}/{N} 通过")
    if FAILS:
        print("失败项：")
        for f in FAILS:
            print("  - " + str(f))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())