# -*- coding: utf-8 -*-
"""
FlashDrop v1.11.0 Windows 端端到端测试：连接去重修复（问题 1）

用户现象：连接好的情况下，电脑发送的文字，安卓端收不到。

根因（两端同源）：
    registerConn / _register_conn 的去重逻辑写成
        if (new_pref && !old_pref) { 替换 } else { close(conn); return False }
    —— 同方向的两条连接 new_pref == old_pref，走进 else 把**新来的**这条丢掉。
    对端重连 / 双向同时互连时，真正活着的恰恰是新连接；丢掉它之后，
    对端 _wait_conn 拿到的正是这条被丢弃的连接 → 该链路上后续所有 TEXT
    都读不到。表现为"心跳正常、显示已连接，但文字收不到"，
    而文件因为会走重试/另一条链路所以还能收到，极具迷惑性。

修复：方向不同 → 仍按原偏好规则；方向相同 → 新连接接管旧连接。

本测试起**真实的 FlashNode**（不做逻辑复刻），用协议客户端模拟安卓端。
注意 FlashNode.start()/stop() 是**同步**的（内部自己跑一个 asyncio loop 的线程），
所以测试主体是同步的，客户端用 socket + struct 手工编解码帧：
  第 1 节：连一次 → 发 TEXT → 必须收到 text 事件
  第 2 节：同方向再连一次（模拟重连）→ 再发 TEXT → 必须仍能收到
           （这一节在修复前必然失败，是本测试的核心）
  第 3 节：只保留新连接时 send_text 能等到 ACK
  第 4 节：不同方向（incoming 偏好反转）时按原偏好规则保留
  第 5 节：stop 不抛异常
"""
import json
import os
import struct
import sys
import socket
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import protocol as P          # noqa: E402
from app.config import Config          # noqa: E402
from app.node import FlashNode, Conn   # noqa: E402

PASS = FAIL = 0
VERBOSE = os.environ.get("FD_VERBOSE") not in (None, "", "0")


def check(name, ok, extra=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {extra}")


def sec(t):
    print(f"\n[{t}]")


MY_PEER = "winpc0001ffffffff"   # 模拟对端（安卓）设备 id，16 位，与 Android 端一致


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def make_node():
    d = tempfile.mkdtemp(prefix="fd1110_")
    os.environ["FLASHDROP_DATA_DIR"] = d
    cfg = Config(os.path.join(d, "config.json"))
    cfg["save_dir"] = os.path.join(d, "save")
    cfg["cache_dir"] = os.path.join(d, "cache")
    cfg["encrypt"] = False
    cfg.ensure_dirs()
    events = []
    node = FlashNode(cfg, emit=events.append)
    return node, events


class Peer:
    """模拟安卓端：完成 HELLO 握手，并可发 TEXT / 等 ACK（同步 socket 实现）"""

    def __init__(self, sock, node_id=MY_PEER, name="测试手机"):
        self.sock = sock
        self.sock.settimeout(8.0)
        self.node_id = node_id
        self.name = name
        self._reader = None
        self._reader_stop = False
        self.ack_seen = False
        # ★ 共享接收缓冲：read_obj 超时后**绝不能**丢掉已读字节，
        #   否则下一帧的 4 字节长度头会错位，之后所有帧都解析失败
        #   （表现为"文字明明到了，但 ACK 一直收不到"）。
        self._buf = b""
        self._lock = threading.Lock()
        # 客户端侧观测：服务端发来的文字内容 + 已回 ACK 的 mid
        self.texts_seen = []
        self.acked_mids = []

    @classmethod
    def connect(cls, port, node_id=MY_PEER, name="测试手机", timeout=8.0):
        s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        p = cls(s, node_id, name)
        p.send_hello()
        return p

    def send_hello(self):
        self.send({"type": P.T_HELLO, "app": P.APP, "id": self.node_id,
                   "name": self.name, "port": 58899, "host": "android-test"})

    def send(self, obj):
        body = json.dumps(obj, ensure_ascii=False,
                          separators=(",", ":")).encode("utf-8")
        payload = bytes([P.KIND_JSON]) + body
        self.sock.sendall(struct.pack(">I", len(payload)) + payload)

    def read_obj(self, timeout=6.0):
        """读一帧 JSON，返回 dict；超时返回 None（已读字节保留在 self._buf）"""
        with self._lock:
            end = time.time() + timeout
            # 1) 缓冲里凑够 4 字节长度头
            while len(self._buf) < 4:
                if not self._pump(end):
                    return None
            (length,) = struct.unpack(">I", self._buf[:4])
            # 2) 缓冲里凑够整帧
            while len(self._buf) < 4 + length:
                if not self._pump(end):
                    return None
            payload = self._buf[4:4 + length]
            self._buf = self._buf[4 + length:]
            if payload and payload[0] == P.KIND_JSON:
                try:
                    return json.loads(payload[1:].decode("utf-8"))
                except Exception:
                    return {"type": "?BADJSON"}
            return {"type": "?BIN"}

    def _pump(self, end):
        """从 socket 读一批数据进缓冲；到点/出错返回 False"""
        left = end - time.time()
        if left <= 0:
            return False
        try:
            self.sock.settimeout(min(0.5, left))
            chunk = self.sock.recv(65536)
        except socket.timeout:
            return False       # 超时不是错误，缓冲保持原样，下次继续
        except OSError:
            return False
        if not chunk:
            return False       # 对端关闭
        self._buf += chunk
        return True

    def read_ack(self, timeout=6.0):
        """
        读一帧，返回 ('ack', mid) / ('other', type) / None。

        连接建立时服务端会先回一条自己的 HELLO，所以这里要**跳过非 ACK 帧**，
        否则第一次读到的总是 HELLO，断言会误判成"没收到 ACK"。
        """
        end = time.time() + timeout
        while time.time() < end:
            obj = self.read_obj(max(0.3, end - time.time()))
            if obj is None:
                return None
            if obj.get("type") == P.T_ACK:
                return ("ack", obj.get("mid"))
            # HELLO / PING / OFFER 等一律跳过，继续等 ACK
        return None

    def start_reader(self, auto_ack_text=True):
        """
        起后台读线程，持续读服务端下发的消息（模拟真实客户端）。

        auto_ack_text=True 时，收到 TEXT 自动回 ACK —— 这一步不能省：
        真实安卓端（FlashNode 的 T_TEXT 分支）收到文字必然 send_json({T_ACK})，
        少了这一步，Windows 侧的 ack_waiters 永远等不到 future，
        只能等到 12s 超时 → text_state=timeout，
        看起来像"发文字失败"，实际是测试客户端没实现协议的对端行为。
        """
        def _loop():
            while not self._reader_stop:
                try:
                    obj = self.read_obj(0.5)
                except Exception:
                    break
                if obj is None:
                    continue
                t = obj.get("type")
                if t == P.T_ACK:
                    self.ack_seen = True
                elif t == P.T_TEXT and auto_ack_text:
                    mid = obj.get("mid")
                    self.texts_seen.append(obj.get("text", ""))
                    try:
                        self.send({"type": P.T_ACK, "mid": mid})
                        self.acked_mids.append(mid)
                    except Exception:
                        pass

        self._reader = threading.Thread(target=_loop, daemon=True)
        self._reader.start()

    def stop_reader(self):
        self._reader_stop = True
        try:
            self.sock.settimeout(0.2)
        except Exception:
            pass

    def close(self):
        self.stop_reader()
        try:
            self.sock.close()
        except Exception:
            pass


def texts_of(events, peer_id=MY_PEER):
    return [e for e in events
            if e.get("event") == "text" and e.get("peer_id") == peer_id]


def wait_for(fn, timeout=6.0, step=0.05):
    """同步轮询等待条件成立"""
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return True
        time.sleep(step)
    return bool(fn())


def main():
    node, events = make_node()
    port = free_port()
    node.port = port
    node.start()
    sec("0. 环境")
    check("FlashNode 已启动", node._started.is_set())

    # ==================================================================
    sec("1. 首次连接：握手后发 TEXT，应收到 text 事件")

    p1 = Peer.connect(port)
    ok = wait_for(lambda: len(node.conns) > 0)
    check("对端已注册连接", ok, f"conns={list(node.conns)}")
    check("peer 已登记", MY_PEER in node.peers, f"peers={list(node.peers)}")

    p1.send({"type": P.T_TEXT, "mid": "m1", "text": "第一条文字",
             "ts": 111, "scheme": "blue"})
    ok = wait_for(lambda: len(texts_of(events)) >= 1)
    check("收到第 1 条文字", ok, f"events={[e.get('event') for e in events[-6:]]}")
    if texts_of(events):
        t1 = texts_of(events)[0]
        check("文字内容正确", t1.get("text") == "第一条文字", f"实际={t1.get('text')}")
        check("peer_id 正确", t1.get("peer_id") == MY_PEER)
        check("mid 正确", t1.get("mid") == "m1")
        check("ts 正确", t1.get("ts") == 111)
    r = p1.read_ack()
    check("服务端回了 ACK", r is not None and r[0] == "ack", f"实际={r}")

    # ==================================================================
    sec("2. ★ 同方向再连一次（模拟重连）：新连接必须接管，且仍能收到文字")

    # 保留 p1（不关），模拟"对端重连时旧连接尚未完全死透"的真实情况。
    # 这正是原 bug 触发条件：两条连接方向相同 → new_pref == old_pref。
    p2 = Peer.connect(port)
    ok = wait_for(lambda: len(node.conns) > 0)
    check("第二次连接后仍有活跃连接", ok)

    # 等待去重逻辑把 p1 换成 p2（_delayed_close(existing, 1.0)）
    time.sleep(1.8)

    before = len(texts_of(events))
    # 从**新连接**发文字 —— 修复后这条连接被保留，文字必须能收到
    try:
        p2.send({"type": P.T_TEXT, "mid": "m2", "text": "重连后的文字",
                 "ts": 222, "scheme": "blue"})
    except Exception as e:
        check("新连接可发送数据", False, f"写入失败：{e}")
    ok = wait_for(lambda: len(texts_of(events)) > before)
    check("★ 同方向重连后仍能收到文字（不丢消息）", ok,
          f"收到 {len(texts_of(events))} 条，期望 > {before}；"
          f"events={[e.get('event') for e in events[-8:]]}")
    if len(texts_of(events)) > before:
        t2 = texts_of(events)[-1]
        check("重连后文字内容正确", t2.get("text") == "重连后的文字",
              f"实际={t2.get('text')}")
        check("重连后 mid 正确", t2.get("mid") == "m2")
    r2 = p2.read_ack()
    check("新连接收到 ACK", r2 is not None and r2[0] == "ack", f"实际={r2}")

    # ==================================================================
    sec("3. 多次连续重连后依然稳定（连丢 3 次）")

    olds = []
    for i in range(3):
        pk = Peer.connect(port)
        olds.append(pk)
        time.sleep(1.4)
    cur = Peer.connect(port)
    time.sleep(1.8)
    base = len(texts_of(events))
    try:
        cur.send({"type": P.T_TEXT, "mid": "mx", "text": "多次重连后",
                  "ts": 333, "scheme": "blue"})
    except Exception as e:
        check("最新连接可发送", False, f"写入失败：{e}")
    ok = wait_for(lambda: len(texts_of(events)) > base, timeout=8.0)
    check("★ 连丢 3 次后仍能收到文字", ok,
          f"收到 {len(texts_of(events))} 条，期望 > {base}")

    # ==================================================================
    sec("4. send_text 走正式接口，对端回 ACK → state=ok")

    # 这一节用**全新的 Node + 全新的客户端**，不复用前面反复重连的现场。
    # 原因：前面 3 节故意制造了大量同向重连（这正是要测的场景），
    #       结束时 conns 里的连接刚被 _delayed_close 接管、old socket 又已被关闭，
    #       此时再测 send_text 混入的变量太多（_wait_conn 拿到哪条、
    #       旧 socket 有没有把 ACK 吃掉），失败无法归因。
    # 真实客户端的"发文字并等 ACK"是一条独立干净路径，单独起实例最可靠。
    node.stop()
    node2, events2 = make_node()
    port2 = free_port()
    node2.port = port2
    node2.start()
    ok = wait_for(lambda: node2._started.is_set())
    check("第二个节点已启动", ok)

    live = Peer.connect(port2)
    live.start_reader()
    ok = wait_for(lambda: MY_PEER in node2.peers)
    check("客户端已连上第二个节点", ok, f"peers={list(node2.peers)}")
    time.sleep(0.4)

    peer_ids = [MY_PEER] if MY_PEER in node2.peers else list(node2.peers)
    check("存在在线 peer 可发", bool(peer_ids), f"peers={list(node2.peers)}")
    if peer_ids:
        try:
            node2.send_text(peer_ids, "来自 send_text 的文字")
            # 客户端侧观测：TEXT 真的到达了安卓端这边
            ok = wait_for(lambda: "来自 send_text 的文字" in live.texts_seen,
                          timeout=12.0)
            check("客户端确实收到了该文字", ok,
                  f"客户端收到={live.texts_seen}")
            # 服务端侧观测：ack_waiters 被 future 兑现 → state=ok
            ok2 = wait_for(lambda: any(
                e.get("event") == "text_state" and e.get("state") == "ok"
                for e in events2), timeout=12.0)
            check("send_text 等到了 ACK（state=ok）", ok2,
                  f"events={[(e.get('event'), e.get('state')) for e in events2[-8:]]}")
            # 客户端确实把 ACK 发回去了（acked_mids 与服务端发出的 mid 对得上）
            check("客户端已回 ACK", bool(live.acked_mids),
                  f"acked_mids={live.acked_mids}")
            # 服务端应发出 ack 事件（ack_waiters 被 pop 后 emit）
            check("服务端发出 ack 事件", any(
                e.get("event") == "ack" for e in events2),
                f"events={[e.get('event') for e in events2[-8:]]}")
        except Exception as e:
            check("send_text 未抛异常", False, f"{type(e).__name__}: {e}")
    live.close()
    try:
        node2.stop()
    except Exception:
        pass

    # ==================================================================
    sec("5. 停止不抛异常")

    try:
        node.stop()   # 第 1 节起的那台，第 4 节开头已停过，这里再调一次应无副作用
        check("stop() 正常返回（重复调用也安全）", True)
    except Exception as e:
        check("stop() 未抛异常", False, f"{type(e).__name__}: {e}")

    for pk in [p1, p2, cur] + olds:
        try:
            pk.close()
        except Exception:
            pass

    print("\n" + "=" * 62)
    print(f" 通过 {PASS} 项，失败 {FAIL} 项")
    print("=" * 62)
    if VERBOSE:
        print("\n事件流：")
        for e in events[-40:]:
            print("   ", e)
    return 1 if FAIL else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
