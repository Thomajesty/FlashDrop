# -*- coding: utf-8 -*-
"""v1.18.39 验收：接收/发送「一次变两次」根治

用户反馈（v1.18.38 截图）：手机发一张图，PC 收到两张一模一样的卡片。

根因（两端同病）：
  待发队列补发每轮 sendFileSync / send_files_sync 都重新生成**新 tid**
  → 接收端「同 tid 幂等应答」失效 → 对端其实已收下但 FILE_OK 回程丢失时，
  下一轮补发让接收端**真收第二次**（新卡片 + 新文件）。
  Windows 幂等表还是 pop 一次性（第 3 次重试失效）且键无 peer_id。

修复：
  A) 两端补发带稳定 tid 种子（tid = seed + "-" + 文件序号，随队列持久化）
  B) Windows 接收端 _on_transfer recv 分支 msgs 回扫同 tid 复用卡片
     （对齐安卓 v1.13.0 防御）
  C) Windows 幂等表改保留式 FIFO（键 (peer_id, tid)，容量 128）
  D) 安卓新增 recvDone 幂等表（此前完全没有）

套件结构：
  A 组  静态断言：两端 tid_seed / 回扫 / 幂等表链路完整
  B 组  双节点网络行为：同 tid 重发 2/3 次幂等不重收；无种子旧行为不变
  C 组  UI 层：接收端「重启后」同 tid 重发不产生第二张卡片
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))   # 仓库根
WIN = os.path.join(ROOT, "windows")

FAILS = []
N = 0

if WIN not in sys.path:
    sys.path.insert(0, WIN)


def ck(name, cond, extra=""):
    global N
    N += 1
    if not cond:
        FAILS.append(f"{name} | {extra}")
    print(("  ok  " if cond else " FAIL ") + name +
          ((" | " + str(extra)) if extra and not cond else ""))


# ============================ A 组：静态断言 ============================

def group_a():
    print("\n===== A 组：静态断言（两端源码链路）=====")
    node = open(os.path.join(WIN, "app", "node.py"), encoding="utf-8").read()
    bridge = open(os.path.join(WIN, "app", "ui", "bridge.py"),
                  encoding="utf-8").read()
    mw = open(os.path.join(WIN, "app", "ui", "main_window.py"),
              encoding="utf-8").read()
    fapp = open(os.path.join(ROOT, "android", "app", "src", "main", "java",
                             "com", "flashdrop", "app", "FlashApp.java"),
                encoding="utf-8").read()
    fnode = open(os.path.join(ROOT, "android", "app", "src", "main", "java",
                              "com", "flashdrop", "app", "FlashNode.java"),
                 encoding="utf-8").read()
    mact = open(os.path.join(ROOT, "android", "app", "src", "main", "java",
                             "com", "flashdrop", "app", "MainActivity.java"),
                encoding="utf-8").read()

    # --- Windows 发送链：tid_seed ---
    ck("A1 node.send_files_sync 带 tid_seed 参数",
       "tid_seed: str = None" in node)
    ck("A2 sync 任务内 tid = seed-i",
       'f"{tid_seed}-{i}"' in node)
    ck("A3 一次性 send_files 仍是随机 tid（旧行为不变）",
       "tid = util.gen_uid()" in node.split("async def _send_files_task")[1])
    ck("A4 bridge 透传 tid_seed",
       "tid_seed=tid_seed" in bridge)
    ck("A5 flush 传 entry mid 作种子",
       'tid_seed=entry.get("mid")' in mw)
    ck("A6 幂等表保留式（不再 pop）",
       "self._recent_done.get((conn.peer_id, tid))" in node
       and ".pop(tid, None)" not in
       node.split("async def _on_file_start")[1].split("if key in self.inbounds")[0])
    ck("A7 幂等表键 (peer_id, tid) 登记 + FIFO 128",
       'self._recent_done[(conn.peer_id, tid)]' in node
       and "len(self._recent_done) > 128" in node)

    # --- Windows 接收链：同 tid 卡片复用 ---
    seg = mw.split('if kind == "recv"')[1].split("else:  # send")[0]
    ck("A8 recv 分支回扫 msgs 尾部同 tid 卡",
       'self.msgs.get(pid) or [])[-50:]' in seg.replace("\n", "").replace(" ", "")
       or "(self.msgs.get(pid) or [])[-50:]" in seg)
    ck("A9 复用卡标记 _appended=True（防双气泡）",
       'm["_appended"] = True' in seg)
    ck("A10 复用后回填 in_by_tid",
       "self.in_by_tid[key] = m" in seg)

    # --- Android 发送链：tidSeed ---
    ck("A11 PendingSend.tidSeed 字段",
       "public String tidSeed" in fapp)
    ck("A12 tidSeed 落盘（tid_seed key）",
       'o.put("tid_seed", p.tidSeed)' in fapp
       and 'ps.tidSeed = o.optString("tid_seed"' in fapp)
    ck("A13 flush 懒生成种子并传 sendFileSync",
       "ps.tidSeed = FdUtil.shortUid()" in fapp
       and "node().sendFileSync(targets, ps.uris, seed)" in fapp)
    ck("A14 sendFileSync 三参重载 tid = seed-fi",
       "tidSeed + \"-\" + fi" in fnode
       and "sendFileSync(List<String> targetIds,\n"
           "                                                      List<String> paths,\n"
           "                                                      String tidSeed)" in fnode)
    ck("A15 sendFiles 三参重载（手动立即发送用）",
       "public void sendFiles(List<String> targetIds, List<String> paths,\n"
       "                          String tidSeed)" in fnode)
    ck("A16 pendingSendNow 用 tidSeed",
       "sendFiles(targets, p.uris, p.tidSeed)" in mact)

    # --- Android 接收链：recvDone 幂等表 ---
    ck("A17 recvDone 幂等表声明",
       "recvDone = new ConcurrentHashMap<>()" in fnode)
    ck("A18 onFileStart 幂等命中直接回 FILE_OK",
       "recvDone.get(key)" in fnode
       and "T_FILE_OK, \"tid\", tid,\n                    \"path\", prevSaved" in fnode)
    ck("A19 onFileEnd verified 后登记 recvDone",
       "if (verified) {" in fnode
       and "recvDone.put(conn.peerId + \"|\" + tid, saved[0])" in fnode
       and "recvDone.size() > 128" in fnode)


# ====================== B 组：双节点网络行为 ======================

def group_b(tmp):
    print("\n===== B 组：双节点网络行为（同 tid 重发幂等）=====")
    import asyncio
    import hashlib
    import json
    import threading
    from app.config import Config
    from app.node import FlashNode, Conn, Peer

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

    def mk_node(tag, events, port):
        os.environ["FLASHDROP_DEVICE_ID"] = (tag * 2)[:16]
        try:
            cfg = Config(os.path.join(tmp, f"cfg_{tag}.json"))
            cfg.data["name"] = tag
            cfg.data["port"] = port
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
        def __init__(self, reader):
            self.reader = reader
            self._closed = False

        def write(self, data):
            if self._closed:
                raise ConnectionError("pipe closed")
            self.reader.feed_data(data)

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

    def start_nodes(*nodes):
        holder = {}

        async def boot():
            loop = asyncio.get_running_loop()
            for n in nodes:
                n.loop = loop
                n._started.set()
                n._stopping = False
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
        h = hashlib.sha256(b"seed39").digest()
        buf = bytearray()
        while len(buf) < size:
            h = hashlib.sha256(h).digest()
            buf.extend(h)
        with open(path, "wb") as f:
            f.write(bytes(buf[:size]))

    evA, evB = Collector(), Collector()
    a = mk_node("A", evA, 58881)
    b = mk_node("B", evB, 58882)
    start_nodes(a, b)
    try:
        wire_pair(a, b, a.device_id, b.device_id)
        time.sleep(0.3)

        src = os.path.join(tmp, "photo.jpg")
        mkfile(src, 400_000)
        save_b = os.path.join(tmp, "save_B")

        # ---- B0/B1/B2: 同 tid_seed 重发 3 次 ----
        seed = "queuemid123"
        r1 = a.send_files_sync([b.device_id], [src], timeout=30,
                               tid_seed=seed)
        ck("B0 第一次补发送达 ok", r1.get(b.device_id) == "ok", str(r1))
        tid_expect = seed + "-0"
        ck("B0 tid = seed-0",
           any(e.get("tid") == tid_expect and e.get("state") == "done"
               for e in evB.recv_events()),
           str([(e.get("tid"), e.get("state")) for e in evB.recv_events()][-4:]))
        n1 = len([f for f in os.listdir(save_b) if not f.endswith(".part")])
        ck("B0 接收目录 1 个文件", n1 == 1, f"got {n1}")

        # 模拟 FILE_OK 回程丢失：发送端没收到 OK，队列条目保留，重试
        r2 = a.send_files_sync([b.device_id], [src], timeout=30,
                               tid_seed=seed)
        ck("B1 第二次补发幂等 ok", r2.get(b.device_id) == "ok", str(r2))
        n2 = len([f for f in os.listdir(save_b) if not f.endswith(".part")])
        ck("B1 接收目录仍 1 个文件（没重收）", n2 == 1, f"got {n2}")
        starts = [e for e in evB.recv_events()
                  if e.get("tid") == tid_expect and e.get("state") == "started"]
        ck("B1 无第二次 started（幂等直答）", len(starts) == 1,
           f"got {len(starts)}")

        # 第 3 次（旧 pop 一次性实现在这里会失效 → 重收）
        r3 = a.send_files_sync([b.device_id], [src], timeout=30,
                               tid_seed=seed)
        ck("B2 第三次补发幂等 ok", r3.get(b.device_id) == "ok", str(r3))
        n3 = len([f for f in os.listdir(save_b) if not f.endswith(".part")])
        ck("B2 接收目录仍 1 个文件", n3 == 1, f"got {n3}")

        # ---- B3: 不带种子的一次性同步发送，tid 每次随机（旧行为）----
        r4 = a.send_files_sync([b.device_id], [src], timeout=30)
        r5 = a.send_files_sync([b.device_id], [src], timeout=30)
        ck("B3 两次无种子发送均 ok",
           r4.get(b.device_id) == "ok" and r5.get(b.device_id) == "ok")
        done_tids = [e.get("tid") for e in evB.recv_events()
                     if e.get("state") == "done"
                     and e.get("tid") not in (tid_expect,)]
        ck("B3 无种子 tid 互不相同（旧行为保留）",
           len(set(done_tids)) == len(done_tids) and len(done_tids) >= 2,
           str(done_tids))
    finally:
        stop_nodes(a, b)
        time.sleep(0.2)


# ====================== C 组：UI 层同 tid 卡片复用 ======================

def group_c(tmp):
    print("\n===== C 组：接收端重启后同 tid 重发不产生第二张卡 =====")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["FLASHDROP_DATA_DIR"] = os.path.join(tmp, "ui_data")
    os.makedirs(os.environ["FLASHDROP_DATA_DIR"], exist_ok=True)
    sys.path.insert(0, WIN)

    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer, QEventLoop
    from app.config import Config
    from app.node import FlashNode
    from app.ui.main_window import MainWindow

    def wait_ms(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    tmp2 = os.path.join(tmp, "ui")
    cfgA = Config(os.path.join(tmp2, "a.json"))
    cfgA.data.update({"device_id": "cccccccccccccccc", "name": "UI-C",
                      "port": 58911,
                      "save_dir": os.path.join(tmp2, "c_save"),
                      "cache_dir": os.path.join(tmp2, "c_cache"),
                      "minimize_to_tray": False, "notify_on_receive": False})
    cfgA.save()
    app = QApplication.instance() or QApplication(sys.argv)
    nodeA = FlashNode(cfgA)
    win = MainWindow(cfgA, nodeA)
    win.show()
    wait_ms(300)

    pid = "dddddddddddddddd"
    win._on_peers([{"id": pid, "name": "手机", "platform": "android",
                    "ips": ["192.168.1.9"], "online": True,
                    "connected": True}])
    wait_ms(150)

    # 模拟「重启后从磁盘加载的旧 done 卡」（重启后 in_by_tid 是空的）
    tid = "queueabc-0"
    old = {"kind": "file", "dir": "in", "peer_id": pid, "tid": tid,
           "file": "photo.jpg", "size": 400_000, "state": "done",
           "mime": "image/jpeg",
           "path": os.path.join(tmp2, "c_save", "photo.jpg"),
           "ts": int(time.time() * 1000) - 60_000}
    win.msgs.setdefault(pid, []).append(old)
    win.in_by_tid.pop((pid, tid), None)   # 重启后索引为空的等价状态
    wait_ms(100)

    cards_before = [m for m in win.msgs.get(pid, []) if m.get("tid") == tid]
    ck("C1 预置旧卡 1 张", len(cards_before) == 1, f"got {len(cards_before)}")

    # 发送端按稳定 tid 补发 → recv started 事件到达（无内存索引命中）
    win._on_transfer({"kind": "recv", "tid": tid, "peer_id": pid,
                      "name": "手机", "file": "photo.jpg", "size": 400_000,
                      "state": "started", "transferred": 0})
    wait_ms(100)
    cards = [m for m in win.msgs.get(pid, []) if m.get("tid") == tid]
    ck("C2 started 后仍只有 1 张卡（复用不新增）", len(cards) == 1,
       f"got {len(cards)}")
    ck("C3 复用卡状态推进到 started", cards[0].get("state") == "started",
       str(cards[0].get("state")))
    ck("C4 复用卡 _appended=True", cards[0].get("_appended") is True)

    # done 收尾
    win._on_transfer({"kind": "recv", "tid": tid, "peer_id": pid,
                      "name": "手机", "file": "photo.jpg", "size": 400_000,
                      "state": "done", "transferred": 400_000,
                      "path": os.path.join(tmp2, "c_save", "photo.jpg")})
    wait_ms(100)
    cards2 = [m for m in win.msgs.get(pid, []) if m.get("tid") == tid]
    ck("C5 done 后仍 1 张卡", len(cards2) == 1, f"got {len(cards2)}")
    ck("C6 状态 done", cards2[0].get("state") == "done")

    # 新 tid 仍正常建新卡（不误伤正常接收）
    win._on_transfer({"kind": "recv", "tid": "fresh-tid-9", "peer_id": pid,
                      "name": "手机", "file": "other.jpg", "size": 111,
                      "mime": "image/jpeg",
                      "state": "started", "transferred": 0})
    wait_ms(100)
    fresh = [m for m in win.msgs.get(pid, []) if m.get("tid") == "fresh-tid-9"]
    ck("C7 新 tid 正常建卡 1 张", len(fresh) == 1, f"got {len(fresh)}")

    win._real_quit()
    wait_ms(100)


def main():
    import shutil
    import tempfile
    tmp = tempfile.mkdtemp(prefix="fd_v11839_")
    try:
        group_a()
        group_b(tmp)
        group_c(tmp)
    finally:
        try:
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass
    print(f"\n===== 结果: {N - len(FAILS)}/{N} "
          f"{'ALL PASS' if not FAILS else 'FAIL ' + str(len(FAILS))} =====")
    for f in FAILS:
        print("  FAIL:", f)
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
