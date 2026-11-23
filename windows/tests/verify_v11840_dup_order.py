# -*- coding: utf-8 -*-
"""v1.18.40 验收：排序/重复卡片三修复

用户反馈（截图）：
  1) 发送内容没有按最新的显示到最底部，下面一大片空白
     → 根因：pending 卡 ts=原发送时刻，_visible_msgs 二次 sort 按旧 ts
       排到顶部。修：pending 恒排尾部。
  2) 发送/接收仍然重复显示一次
     → 根因①：手动发送成功后队列同内容条目仍在，补发再发一遍。
       修：发送 done 时摘除同内容 pending 条目。
     → 根因②：旧版对端补发每轮换 tid，同 tid 幂等拦不住。
       修：node 层内容级幂等（peer+name+size 5 分钟窗口）+ UI 层兜底合并。

测试组：
  A 静态断言（两端源码）
  B UI 行为（pending 排尾 / 手动发送摘条目 / UI 内容级合并）
  C 双节点行为（node 层内容级幂等：不同 tid 重发 → 不落盘第二份）
"""
import asyncio
import hashlib
import os
import re
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WIN = os.path.dirname(HERE)          # windows/
ROOT = os.path.dirname(WIN)          # 仓库根
for p in (WIN,):
    if p not in sys.path:
        sys.path.insert(0, p)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# ★ v1.18.41：数据目录隔离（v1.18.40 血泪教训）。
#   之前本套件漏设 FLASHDROP_DATA_DIR —— group_b 的窗口把假设备
#   bbbb… 的历史写进真实 %APPDATA%\FlashDrop\history，下一轮运行
#   又把上轮残留的 recv-tid-1 旧卡 load 回来（ts 超出 3 分钟合并
#   窗口）→ B3「同内容不同 tid 复用同一张卡」假失败，且持续污染
#   真实数据。必须在任何 app.* 导入/实例化之前设好。
os.environ["FLASHDROP_DATA_DIR"] = tempfile.mkdtemp(prefix="fd_v11840_data_")

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


def rd(rel):
    return open(os.path.join(WIN, rel), encoding="utf-8").read()


# ============================ A 组：静态断言 ============================

def group_a():
    mw = rd("app/ui/main_window.py")
    node = rd("app/node.py")
    fnode = rd(os.path.join("..", "android", "app", "src", "main", "java",
                            "com", "flashdrop", "app", "FlashNode.java"))

    ck("A1 pending 恒排尾（去掉二次 sort）",
       "return rest[-200:] + pended" in mw
       and "out = (rest[-200:] + pended)\n        out.sort" not in mw)
    ck("A2 发送 done 摘同内容 pending 条目",
       "_consume_matching_pending" in mw
       and 'if m.get("state") in ("done", "ok"):\n                self._consume_matching_pending(m)' in mw)
    ck("A3 node 内容级幂等表存在",
       "_recent_done_content" in node
       and "time.time() - cprev < 300" in node)
    ck("A4 node 幂等命中回 duplicate OK",
       '"duplicate": True' in node)
    ck("A5 UI recv 内容级合并（3 分钟窗口，仅终态）",
       'now_ms - (x.get("ts") or 0) < 180_000' in mw
       and 'if state in ("done", "ok"):' in mw)
    ck("A6 安卓 recvDoneContent 表",
       "recvDoneContent" in fnode
       and "5 * 60 * 1000L" in fnode)
    ck("A7 安卓登记内容键",
       'recvDoneContent.put(conn.peerId + "|" + ib.name + "|" + ib.size' in fnode)
    # ★ v1.18.41：版本断言演进式化 —— 双端版本一致且不低于 1.18.41，
    #   manifest 与 __init__ 同源，不再钉死具体小版本号。
    mver = re.search(r'__version__ = "(1\.18\.\d+)"', rd("app/__init__.py"))
    aver = re.search(r'APP_VERSION = "(1\.18\.\d+)"',
                     rd(os.path.join("..", "android", "app", "src", "main",
                                     "java", "com", "flashdrop", "app",
                                     "FdUtil.java")))
    man = rd(os.path.join("..", "android", "app", "src", "main",
                          "AndroidManifest.xml"))
    mcode = re.search(r'android:versionCode="(\d+)"', man)
    mname = re.search(r'android:versionName="(1\.18\.\d+)"', man)

    def vtuple(s):
        return tuple(int(x) for x in s.split("."))

    ck("A8 双端版本号一致且 >= 1.18.41",
       bool(mver and aver) and mver.group(1) == aver.group(1)
       and vtuple(mver.group(1)) >= vtuple("1.18.41"),
       f"py={mver and mver.group(1)} java={aver and aver.group(1)}")
    ck("A9 manifest versionCode >= 70 且 versionName 同源",
       bool(mcode and mname and mver)
       and int(mcode.group(1)) >= 70
       and mname.group(1) == mver.group(1),
       f"code={mcode and mcode.group(1)} name={mname and mname.group(1)}")


# ============================ B 组：UI 行为 ============================

def group_b():
    import tempfile
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer, QEventLoop, Qt

    from app.config import Config
    from app.node import FlashNode
    from app.ui.main_window import MainWindow

    def wait_ms(ms):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    tmp = tempfile.mkdtemp(prefix="fd_v11840_")
    cfg = Config(os.path.join(tmp, "a.json"))
    cfg.data.update({"device_id": "aaaaaaaaaaaaaaaa", "name": "UI-A", "port": 58912,
                     "save_dir": os.path.join(tmp, "a_save"),
                     "cache_dir": os.path.join(tmp, "a_cache"),
                     "minimize_to_tray": False, "notify_on_receive": False})
    cfg.save()

    app = QApplication.instance() or QApplication(sys.argv)
    node = FlashNode(cfg)
    win = MainWindow(cfg, node)
    win.resize(1000, 760)
    win.show()
    wait_ms(300)

    pid = "bbbbbbbbbbbbbbbb"
    win._on_peers([{"id": pid, "name": "安卓手机", "platform": "android",
                    "ips": [], "online": False, "connected": False}])
    wait_ms(100)
    for i in range(win.device_list.count()):
        it = win.device_list.item(i)
        if it.data(Qt.UserRole) == pid:
            win.device_list.itemClicked.emit(it)
            it.setSelected(True)
            break
    wait_ms(200)

    now = int(time.time() * 1000)
    # 历史 5 条 + 1 条**更旧 ts** 的 pending（复刻用户场景：队列挂了很久）
    for i in range(5):
        win.msgs.setdefault(pid, []).append({
            "kind": "text", "dir": "in", "peer_id": pid,
            "text": f"历史 {i}", "ts": now - 30_000 + i * 1000})
    win.msgs.setdefault(win.PENDING_PEER, []).append({
        "kind": "file", "dir": "out", "peer_id": win.PENDING_PEER,
        "file": "old.apk", "size": 168_000, "state": "pending",
        "mid": "pend-mid-1", "ts": now - 300_000})
    win._pending_files.append({"mid": "pend-mid-1", "kind": "files",
                               "paths": [os.path.join(tmp, "old.apk")],
                               "targets": [pid], "ts": now - 300_000})
    os.makedirs(win._pending_files[0]["paths"][0], exist_ok=True) \
        if False else None
    with open(win._pending_files[0]["paths"][0], "wb") as f:
        f.write(b"x" * 168_000)

    win._render_chat()
    wait_ms(200)

    # ---- B1: pending 排尾 ----
    vis = win._visible_msgs()
    ck("B1 pending 排在可见消息最后", vis[-1].get("state") == "pending"
       and vis[-1].get("mid") == "pend-mid-1",
       f"last={vis[-1].get('state')}")

    # ---- B2: 手动发送 done → 摘同内容条目 ----
    win._on_transfer({"kind": "send", "tid": "manual-tid-1",
                      "peer_id": pid, "name": "安卓手机",
                      "file": "old.apk", "size": 168_000,
                      "mime": "application/vnd.android.package-archive",
                      "state": "ok", "targets": [pid]})
    wait_ms(100)
    mids = {e.get("mid") for e in win._pending_files}
    ck("B2 发送成功后队列条目已摘除", "pend-mid-1" not in mids,
       f"mids={mids}")
    pend_msgs = [m for m in win.msgs.get(win.PENDING_PEER, [])
                 if m.get("mid") == "pend-mid-1"]
    ck("B2 pending 气泡同步摘除", len(pend_msgs) == 0,
       f"got {len(pend_msgs)}")

    # ---- B3: UI recv 内容级合并（不同 tid 同内容 3 分钟内）----
    def cards_by_tid(tid):
        return [m for m in win.msgs.get(pid, [])
                if m.get("kind") == "file" and m.get("dir") == "in"
                and m.get("tid") == tid]

    # 注：测试节点的 UDP 真实监听可能收到局域网真设备的广播，
    # msgs[pid] 可能混入真实传输的卡片 —— 断言一律按测试 tid 精确匹配。
    win._on_transfer({"kind": "recv", "tid": "recv-tid-1", "peer_id": pid,
                      "name": "安卓手机", "file": "photo.jpg", "size": 1000,
                      "mime": "image/jpeg", "state": "done",
                      "path": os.path.join(tmp, "a_save", "photo.jpg"),
                      "transferred": 1000})
    wait_ms(100)
    ck("B3 首次 recv 建恰好 1 张卡", len(cards_by_tid("recv-tid-1")) == 1,
       f"got {len(cards_by_tid('recv-tid-1'))}")
    win._on_transfer({"kind": "recv", "tid": "recv-tid-2", "peer_id": pid,
                      "name": "安卓手机", "file": "photo.jpg", "size": 1000,
                      "mime": "image/jpeg", "state": "done",
                      "path": os.path.join(tmp, "a_save", "photo.jpg"),
                      "transferred": 1000})
    wait_ms(100)
    ck("B3 同内容不同 tid 复用同一张卡",
       len(cards_by_tid("recv-tid-1")) == 1
       and len(cards_by_tid("recv-tid-2")) == 0,
       f"tid1={len(cards_by_tid('recv-tid-1'))} "
       f"tid2={len(cards_by_tid('recv-tid-2'))}")
    # 不同内容 → 正常建新卡
    win._on_transfer({"kind": "recv", "tid": "recv-tid-3", "peer_id": pid,
                      "name": "安卓手机", "file": "other.jpg", "size": 999,
                      "mime": "image/jpeg", "state": "done",
                      "path": os.path.join(tmp, "a_save", "other.jpg"),
                      "transferred": 999})
    wait_ms(100)
    ck("B3 不同内容正常建新卡", len(cards_by_tid("recv-tid-3")) == 1,
       f"got {len(cards_by_tid('recv-tid-3'))}")


# ============================ C 组：双节点 node 层幂等 ============================

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


def group_c():
    from app.config import Config
    from app.node import FlashNode, Conn, Peer

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

    holder = {}

    def start_nodes(n1, n2):
        async def boot():
            loop = asyncio.get_running_loop()
            for n in (n1, n2):
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

    def mkfile(path, size):
        h = hashlib.sha256(b"seed40").digest()
        buf = bytearray()
        while len(buf) < size:
            h = hashlib.sha256(h).digest()
            buf.extend(h)
        with open(path, "wb") as f:
            f.write(bytes(buf[:size]))

    tmp = tempfile.mkdtemp(prefix="fd_v11840_c_")
    evA, evB = Collector(), Collector()
    a = mk_node(tmp, "C", evA)
    b = mk_node(tmp, "D", evB)
    start_nodes(a, b)
    wire_pair(a, b, a.device_id, b.device_id)
    time.sleep(0.3)

    src = os.path.join(tmp, "same.bin")
    mkfile(src, 200_000)

    # 第一次发送（tid1）
    a.send_files([b.device_id], [src])
    ck("C0 第一次传输完成",
       wait_for(lambda: any(e.get("state") == "done"
                            for e in evB.recv_events()), 20))
    time.sleep(0.5)
    save_dir = os.path.join(tmp, "save_D")
    n_files_1 = len(os.listdir(save_dir)) if os.path.isdir(save_dir) else 0
    ck("C1 第一次落盘 1 份", n_files_1 == 1, f"got {n_files_1}")

    # 第二次发送：**不同 tid**、同 peer+同名+同大小（复刻旧版对端补发）
    a.send_files([b.device_id], [src])
    time.sleep(2.5)
    n_files_2 = len(os.listdir(save_dir)) if os.path.isdir(save_dir) else 0
    ck("C2 内容级幂等：不落盘第二份", n_files_2 == 1, f"got {n_files_2}")
    starts = [e for e in evB.recv_events() if e.get("state") == "started"]
    ck("C3 无第二次 started 事件", len(starts) == 1, f"got {len(starts)}")
    aok = [e for e in evA.evts if e.get("kind") == "send"
           and e.get("state") == "ok"]
    ck("C4 发送端收到 OK（不卡队列）", len(aok) >= 2, f"got {len(aok)}")

    for n in (a, b):
        try:
            n.loop.call_soon_threadsafe(n.loop.stop)
        except Exception:
            pass


def main():
    group_a()
    group_b()
    group_c()
    print(f"\n{N - len(FAILS)}/{N} passed")
    if FAILS:
        for f in FAILS:
            print("  FAIL:", f)
        sys.exit(1)


if __name__ == "__main__":
    main()
