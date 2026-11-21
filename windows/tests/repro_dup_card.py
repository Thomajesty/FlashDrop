# -*- coding: utf-8 -*-
"""v1.18.36 复现测试：Windows 收文件「一张卡片变两张」

用户数据（9974f85e054eb116.jsonl）实锤：每个接收 tid 落盘两行
[done(ts=X, path=有), started(ts=X, path=null, transferred=0)]，
ts 完全相同、_appended 均 True —— 同一传输被 append 两次或事件序列异常。

本测试两层定位：
  P1) FlashNode 层：一次传输 B 节点 emit 的 recv 事件序列（重复/乱序？）
  P2) History+recv处理层：按真实事件序列走 _on_transfer 等价逻辑，
      检查 jsonl 行数
"""
import asyncio
import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WIN = os.path.dirname(HERE)
if WIN not in sys.path:
    sys.path.insert(0, WIN)

from app.config import Config          # noqa: E402
from app.node import FlashNode, Conn, Peer  # noqa: E402
from app.ui.history import History     # noqa: E402

FAILS = []
N = 0


def ck(name, cond, extra=""):
    global N
    N += 1
    if not cond:
        FAILS.append(f"{name} | {extra}")
    print(("  ok  " if cond else " FAIL ") + name +
          ((" | " + str(extra)) if extra and not cond else ""))


def wait_for(fn, timeout=20, interval=0.05):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if fn():
            return True
        time.sleep(interval)
    return False


class Collector:
    def __init__(self):
        self.evts = []
        self.lock = threading.Lock()

    def __call__(self, e):
        with self.lock:
            self.evts.append(dict(e))

    def recv_events(self):
        with self.lock:
            return [e for e in self.evts if e.get("kind") == "recv"]


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


def wire_pair(a, b, a_id, b_id):
    async def build():
        rd_a = asyncio.StreamReader()
        rd_b = asyncio.StreamReader()
        conn_a = Conn(rd_a, PipeWriter(rd_b), incoming=False)
        conn_a.peer_id = b_id
        conn_a.hello_got = True
        a.conns[b_id] = conn_a
        pa = Peer(b_id)
        pa.name = "设备B"
        pa.last_seen = time.time()
        a.peers[b_id] = pa

        conn_b = Conn(rd_b, PipeWriter(rd_a), incoming=True)
        conn_b.peer_id = a_id
        conn_b.hello_got = True
        b.conns[a_id] = conn_b
        pb = Peer(a_id)
        pb.name = "设备A"
        pb.last_seen = time.time()
        b.peers[a_id] = pb

        a.loop.create_task(a._reader_loop(conn_a))
        b.loop.create_task(b._reader_loop(conn_b))
    asyncio.run_coroutine_threadsafe(build(), a.loop).result(15)


def start_nodes(n1, n2):
    holder = {}

    async def boot():
        loop = asyncio.get_running_loop()
        for n in (n1, n2):
            n.loop = loop
            n._started.set()
            n._stopping = False
            # 打桩：避免 _wait_conn 建真实 TCP 把文件发给本机真实例
            n._ensure_connected = lambda *args, **kw: None
        holder["loop"] = loop
        await asyncio.sleep(3600)

    def run():
        try:
            asyncio.run(boot())
        except Exception:
            pass

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t0 = time.time()
    while holder.get("loop") is None and time.time() - t0 < 10:
        time.sleep(0.05)
    return t


def stop_nodes(*nodes):
    for n in nodes:
        try:
            n.loop.call_soon_threadsafe(n.loop.stop)
        except Exception:
            pass


def mkfile(path, size):
    h = hashlib.sha256(b"seed").digest()
    buf = bytearray()
    while len(buf) < size:
        h = hashlib.sha256(h).digest()
        buf.extend(h)
    with open(path, "wb") as f:
        f.write(bytes(buf[:size]))


def main():
    tmp = tempfile.mkdtemp(prefix="fd_dup_card_")
    try:
        # ---------- P1: FlashNode 层事件序列 ----------
        evA, evB = Collector(), Collector()
        a = mk_node(tmp, "A", evA)
        b = mk_node(tmp, "B", evB)
        start_nodes(a, b)
        wire_pair(a, b, a.device_id, b.device_id)
        time.sleep(0.3)

        src = os.path.join(tmp, "src.png")
        mkfile(src, 300_000)

        a.send_files([b.device_id], [src])
        ok = wait_for(lambda: any(e.get("state") == "done"
                                  for e in evB.recv_events()), 20)
        ck("P0 传输完成", ok)
        time.sleep(0.5)
        seq = [(e.get("state"), e.get("tid", "")[:8]) for e in evB.recv_events()]
        print("P1 B 节点 recv 事件序列:", seq)
        tids = set(t for _, t in seq)
        ck("P1 单次传输 tid 唯一", len(tids) == 1, str(tids))
        starts = [s for s, _ in seq if s == "started"]
        ck("P1 started 事件恰好 1 次", len(starts) == 1, f"got {len(starts)}")
        dones = [s for s, _ in seq if s == "done"]
        ck("P1 done 事件恰好 1 次", len(dones) == 1, f"got {len(dones)}")
        # 顺序检查：started 应在 done 前
        states = [s for s, _ in seq]
        if len(seq) >= 2:
            ck("P1 started 先于 done",
               states.index("started") < states.index("done"), str(states))

        # ---------- P2: History + recv 处理逻辑落盘 ----------
        # 打桩 app_data_dir，隔离本机真实历史
        import app.ui.history as H
        H.app_data_dir = lambda: os.path.join(tmp, "appdata")
        os.makedirs(os.path.join(tmp, "appdata", "history"), exist_ok=True)
        hist = History()
        pid = b.device_id

        in_map = {}   # 复刻 MainWindow.in_by_tid
        for e in evB.recv_events():
            tid = e.get("tid")
            key = (pid, tid)
            m = in_map.get(key)
            if not m:
                m = {"kind": "file", "dir": "in", "peer_id": pid,
                     "peer_name": e.get("name"), "tid": tid,
                     "file": e.get("file"), "size": e.get("size"),
                     "mime": e.get("mime"), "state": e.get("state"),
                     "peer_scheme": e.get("scheme", ""),
                     "transferred": e.get("transferred", 0),
                     "speed": e.get("speed", 0), "path": e.get("path"),
                     "ts": int(time.time() * 1000)}
                in_map[key] = m
            else:
                for f in ("state", "transferred", "speed", "path", "reason",
                          "file", "size", "total_chunks", "have_chunks",
                          "attempt"):
                    if e.get(f) is not None:
                        m[f] = e[f]
            if not m.get("_appended") and e.get("state") != "offer":
                m["_appended"] = True
                hist.append(pid, m)
            # _refresh_msg 等价：每次事件都 upsert
            hist.upsert(pid, m)

        path = hist._path(pid)
        lines = [json.loads(l) for l in open(path, encoding="utf-8")
                 if l.strip()]
        print("P2 jsonl 行数:", len(lines))
        for i, m in enumerate(lines):
            print(f"  line#{i} state={m.get('state')} path={m.get('path')} "
                  f"ts={m.get('ts')} _appended={m.get('_appended')}")
        ck("P2 落盘恰好 1 行", len(lines) == 1, f"got {len(lines)}")

        # ---------- P3: load 去重清理存量脏数据 ----------
        dirty = os.path.join(tmp, "appdata", "history", "p3.jsonl")
        ts = int(time.time() * 1000)
        rows = [
            {"kind": "file", "dir": "in", "peer_id": "p3", "tid": "T1",
             "file": "a.png", "size": 1, "state": "done",
             "path": "C:/x/a.png", "ts": ts},
            {"kind": "file", "dir": "in", "peer_id": "p3", "tid": "T1",
             "file": "a.png", "size": 1, "state": "started",
             "path": None, "ts": ts},
            {"kind": "file", "dir": "in", "peer_id": "p3", "tid": "T2",
             "file": "b.png", "size": 1, "state": "started",
             "path": None, "ts": ts + 1},
        ]
        with open(dirty, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        loaded = hist.load("p3")
        ck("P3 存量 [done,started] 去重为 1 条",
           len([m for m in loaded if m.get("tid") == "T1"]) == 1,
           str([(m.get("tid"), m.get("state")) for m in loaded]))
        t1 = [m for m in loaded if m.get("tid") == "T1"][0]
        ck("P3 保留终态行", t1.get("state") == "done", t1.get("state"))
        t2 = [m for m in loaded if m.get("tid") == "T2"]
        ck("P3 无终态的幽灵 started 转为 failed 保留",
           len(t2) == 1 and t2[0].get("state") == "failed",
           str(t2))

        stop_nodes(a, b)

        print()
        if FAILS:
            print("FAILS:", len(FAILS))
            for f in FAILS:
                print(" -", f)
            sys.exit(1)
        print(f"ALL {N} PASS")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
