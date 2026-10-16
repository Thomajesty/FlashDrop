# -*- coding: utf-8 -*-
"""FlashDrop 核心节点：TCP 服务/连接管理、UDP 发现、子网扫描、文件传输。

架构：
- 独立线程运行 asyncio 事件循环；UI 线程通过 start/stop/send_*/connect_manual 等方法交互；
- 所有事件通过 self.emit(dict) 回调抛出（在 loop 线程调用，UI 侧需自行跨线程投递）；
- 多路由器级联环境：双向连接尝试 + "设备 ID 大者为首选发起方"的去重规则，
  单向可达时保留唯一可用连接并复用其双向通信；
- 文件接收流程：FILE_START -> 接收方 RECV_READY / REFUSE -> 分块 -> FILE_END -> FILE_OK/FAIL。
"""

import asyncio
import hashlib
import json as jsonlib
import os
import socket
import ssl as ssl_mod
import struct
import sys
import threading
import time

from . import protocol as P
from . import netinfo
from . import util
from . import resume as R
from .config import Config

PLATFORM = "windows"

UDP_SEEN_TTL = 15.0          # UDP 最后可见时间（在线判定）
CONN_DEAD_AFTER = 30.0       # 心跳死亡判定（无活跃传输时）
# ★ v1.16.0：有活跃接受/发送任务时放宽心跳死亡判定。
# 对端手机息屏后系统会冻结它的进程，30s 收不到包并不等于掉线；
# 沿用旧阈值会把正在传的链路判死，表现为"发送端已发送、接收端失败"。
CONN_DEAD_AFTER_BUSY = 90.0
RECV_CONFIRM_TTL = 35.0      # 发送方等待 RECV_READY 超时
# ★ v1.16.0：等待落盘确认由 180s 放宽到 300s（对端息屏低电下落盘可能变慢）
SEND_WAIT_OK = 300.0         # 发送后等待 FILE_OK 超时
PEER_OFFLINE_REMOVE = 1800.0  # 离线设备保留时长

# ★ v1.18.18：文件传输自动重试 + 断点续传
SEND_MAX_RETRY = 3           # 单目标最大重试次数（不含首次）
SEND_RETRY_BASE = 1.5        # 退避基数秒（指数增长，上限 30s）
BITMAP_FLUSH_CHUNKS = 16     # 每收满 N 个块落盘一次位图
BITMAP_FLUSH_SECS = 2.0      # 或距上次落盘超过 N 秒
RESUME_TTL = 7 * 86400.0     # 断点残留保留时长（超过则当垃圾清理）

COMMON_SUBNETS = (
    ["192.168.%d.0/24" % i for i in range(32)]
    + ["10.0.0.0/24", "10.0.1.0/24", "10.0.2.0/24", "10.1.0.0/24", "10.8.0.0/24",
       "172.16.0.0/24", "172.17.0.0/24", "172.20.0.0/24", "172.30.0.0/24",
       "100.64.0.0/24"]
)


def ip_is_private(ip: str) -> bool:
    try:
        parts = [int(x) for x in ip.split(".")]
    except Exception:
        return False
    if len(parts) != 4:
        return False
    if parts[0] == 10:
        return True
    if parts[0] == 172 and 16 <= parts[1] <= 31:
        return True
    if parts[0] == 192 and parts[1] == 168:
        return True
    if parts[0] == 127:
        return True
    return False


class Peer:
    __slots__ = ("id", "name", "platform", "tcp_port", "ips", "last_seen",
                 "manual", "connecting", "next_retry", "retry_backoff", "created",
                 "host")

    def __init__(self, pid):
        self.id = pid
        self.name = ""
        self.platform = ""
        self.tcp_port = P.DEFAULT_PORT
        self.ips = []
        self.last_seen = 0.0
        self.manual = False
        self.connecting = False
        self.next_retry = 0.0
        self.retry_backoff = 1.0
        self.created = time.time()
        self.host = ""

    def online(self, conns: dict) -> bool:
        c = conns.get(self.id)
        if c and c.alive and not c.replaced:
            return True
        return (time.time() - self.last_seen) < UDP_SEEN_TTL

    def snapshot(self, conns: dict) -> dict:
        c = conns.get(self.id)
        connected = bool(c and c.alive and not c.replaced)
        if connected:
            ip = c.remote_ip
            ips = [ip] + [x for x in self.ips if x != ip]
        else:
            ips = self.ips
        return {
            "id": self.id, "name": self.name or self.id[:8],
            "platform": self.platform or "unknown", "tcp_port": self.tcp_port,
            "ips": ips[:4], "online": self.online(conns), "connected": connected,
            "manual": self.manual,
        }


class Conn:
    def __init__(self, reader, writer, incoming):
        self.reader = reader
        self.writer = writer
        self.incoming = incoming
        self.alive = True
        self.replaced = False
        self.peer_id = None
        self.hello_got = False
        self.closed = False
        self.last_recv = time.time()
        self.send_lock = asyncio.Lock()
        pe = writer.get_extra_info("peername") or ("?", 0)
        self.remote_ip = pe[0] if pe else "?"
        self.remote_port = pe[1] if pe else 0

    async def send_frame(self, frame: bytes):
        if not self.alive:
            raise ConnectionError("conn closed")
        async with self.send_lock:
            self.writer.write(frame)
            await self.writer.drain()

    async def send_json(self, obj: dict):
        await self.send_frame(P.encode_json(obj))

    async def close(self):
        if self.closed:
            return
        self.closed = True
        self.alive = False
        try:
            self.writer.close()
        except Exception:
            pass


class Inbound:
    """一个接收中的传输

    ★ v1.18.18：新增断点续传字段。
    - `cmap`    块位图，记录哪些块已落盘
    - `mode`    "chunk" = 支持 seek 续传；"stream" = 老协议顺序追加
    - `pending`尚未落盘的块号（已 seek 写完但位图还没 save 的窗口期），
                用于崩溃后正确判定"这个块到底算不算收到"
    """
    __slots__ = ("peer_id", "tid", "meta", "f", "path_part", "received",
                 "started", "confirmed", "done", "md5", "t0", "win_bytes",
                 "win_t", "last_evt", "canceled", "scheme",
                 "cmap", "mode", "pending", "last_bmp_save", "since_bmp",
                 "attempt", "resume_supported")

    def __init__(self, peer_id, tid, meta):
        self.peer_id = peer_id
        self.tid = tid
        self.meta = meta
        self.f = None
        self.path_part = None
        self.received = 0
        self.started = False
        self.confirmed = False
        self.done = False
        self.md5 = None
        self.t0 = time.time()
        self.win_bytes = 0
        self.win_t = time.time()
        self.last_evt = 0.0
        self.canceled = False
        self.scheme = ""
        self.cmap = None
        self.mode = "stream"
        self.pending = []
        self.last_bmp_save = 0.0
        self.since_bmp = 0
        self.attempt = 0
        self.resume_supported = False


class FlashNode:
    def __init__(self, config: Config, emit=None):
        self.cfg = config
        self.emit = emit or (lambda evt: None)
        self.device_id = config.device_id
        self.name = config.name
        self.port = config.port
        try:
            self.hostname = socket.gethostname() or ""
        except Exception:
            self.hostname = ""
        try:
            self.alt_ids = [x for x in (config["legacy_ids"] or []) if x]
        except Exception:
            self.alt_ids = []

        self.loop = None
        self._thread = None
        self._stop_evt = None
        self._started = threading.Event()

        self.peers: dict = {}          # id -> Peer
        self.conns: dict = {}          # peer_id -> Conn
        self.inbounds: dict = {}       # (peer_id, tid) -> Inbound
        # ★ v1.18.19：最近完整接收的传输（tid -> (path, size)），
        # 供 FILE_OK 丢失后的重试幂等应答（容量 128，FIFO 淘汰）
        self._recent_done = {}
        self.out_waiters: dict = {}    # (peer_id, tid) -> Future（FILE_OK/FAIL/REFUSE/CANCEL）
        self.ready_waiters: dict = {}  # (peer_id, tid) -> Future（RECV_READY/REFUSE）
        self.ack_waiters: dict = {}    # (peer_id, mid) -> Future
        self.out_states: dict = {}     # tid -> {peer_id: state}
        self._send_info: dict = {}     # tid -> {name,size,mime,targets}
        self._tasks = set()
        self._udp = None
        self._udp_alt = None
        self._server = None
        self._last_reply = {}
        self._scanning = False
        self._stopping = False
        self._lock = threading.Lock()
        self._tls_server = None
        self._tls_client = None

    # ============================ 传输加密（TLS） ============================

    def _tls_server_context(self):
        """服务端 TLS 上下文（懒加载）：开启"传输加密"后对 TLS 客户端自动握手"""
        if self._tls_server is not None:
            return self._tls_server
        if not self.cfg["encrypt"]:
            return None
        base = getattr(sys, "_MEIPASS",
                       os.path.join(os.path.dirname(os.path.dirname(
                           os.path.abspath(__file__)))))
        cert = os.path.join(base, "assets", "fd_tls_cert.pem")
        key = os.path.join(base, "assets", "fd_tls_key.pem")
        try:
            ctx = ssl_mod.SSLContext(ssl_mod.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(cert, key)
            self._tls_server = ctx
            return ctx
        except Exception:
            return None

    def _tls_client_context(self):
        if self._tls_client is None:
            ctx = ssl_mod.SSLContext(ssl_mod.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl_mod.CERT_NONE   # 局域网点对点工具：不校验证书
            self._tls_client = ctx
        return self._tls_client

    async def _open_conn(self, ip, port, timeout):
        """建立出站连接：开启加密时优先 TLS，对端不支持（明文）自动回退"""
        if not self.cfg["encrypt"]:
            return await asyncio.wait_for(
                asyncio.open_connection(ip, port), timeout=timeout)
        try:
            return await asyncio.wait_for(
                asyncio.open_connection(ip, port, ssl=self._tls_client_context()),
                timeout=timeout + 2)
        except Exception:
            return await asyncio.wait_for(
                asyncio.open_connection(ip, port), timeout=timeout)

    # ============================ 生命周期 ============================

    def start(self):
        if self._started.is_set():
            return
        self._stop_evt = threading.Event()
        self._thread = threading.Thread(target=self._run, name="flashdrop-node", daemon=True)
        self._thread.start()
        self._started.wait(10)

    def _run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._main())
        except Exception as e:
            self.emit({"event": "log", "level": "error", "msg": f"节点异常退出: {e}"})
        finally:
            try:
                self.loop.close()
            except Exception:
                pass

    async def _main(self):
        loop = asyncio.get_running_loop()
        self.cfg.ensure_dirs()
        ok_udp = await self._udp_start()
        ok_srv = await self._tcp_start()
        self.emit({"event": "log", "level": "info",
                   "msg": f"服务已启动 tcp:{'ok' if ok_srv else 'FAIL'} "
                          f"udp:{'ok' if ok_udp else 'FAIL'} port={self.port}"})
        loop.create_task(self._safe(self.scan(full=False), "启动扫描"))
        loop.create_task(self._safe(self._announce_loop(), "广播"))
        loop.create_task(self._safe(self._expire_loop(), "过期检查"))
        loop.create_task(self._safe(self._bg_scan_loop(), "后台扫描"))
        self._started.set()
        # 等待停止
        while not self._stop_evt.is_set():
            await asyncio.sleep(0.15)
        # 清理：取消所有后台任务
        self._stopping = True
        me = asyncio.current_task()
        pending = [t for t in asyncio.all_tasks() if t is not me and not t.done()]
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        for c in list(self.conns.values()):
            try:
                await c.send_json({"type": P.T_BYE})
            except Exception:
                pass
            await c.close()
        for ib in list(self.inbounds.values()):
            # ★ v1.18.18 审计修复：停机保留断点（drop_state=False）。
            #   断点续传的核心价值就是"重启后接着传"，停机清光与
            #   7 天 GC 设计自相矛盾。异常中断的传输由 load() 的
            #   幽灵清理统一标记 failed，不影响 UI 一致性。
            self._cleanup_inbound(ib, drop_state=False)
        if self._udp:
            self._udp.close()
        if self._udp_alt:
            try:
                self._udp_alt.close()
            except Exception:
                pass
        if self._server:
            self._server.close()

    @staticmethod
    async def _safe(coro, tag):
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception as e:
            pass

    def stop(self, wait=True):
        if not self._started.is_set():
            return
        self._stop_evt.set()
        if self._thread and wait:
            self._thread.join(timeout=6)

    def _post(self, coro):
        if self.loop and self.loop.is_running():
            return asyncio.run_coroutine_threadsafe(coro, self.loop)
        return None

    # ============================ 服务器与发现 ============================

    async def _tcp_start(self) -> bool:
        try:
            self._server = await asyncio.start_server(
                self._on_accept, host="0.0.0.0", port=self.port)
            return True
        except OSError as e:
            self.emit({"event": "log", "level": "error",
                       "msg": f"TCP 端口 {self.port} 绑定失败: {e}"})
            return False

    async def _udp_start(self) -> bool:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.bind(("0.0.0.0", self.port))
            s.setblocking(False)
            self._udp = s
            # 备用监听：非默认端口时额外监听默认端口，
            # 使不同端口设置的实例间仍能通过广播互相发现
            self._udp_alt = None
            if self.port != P.DEFAULT_PORT:
                try:
                    s2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s2.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    s2.bind(("0.0.0.0", P.DEFAULT_PORT))
                    s2.setblocking(False)
                    self._udp_alt = s2
                except OSError:
                    self._udp_alt = None
            try:
                grp = socket.inet_aton(P.MULTICAST_GROUP)
                for sock in filter(None, (s, self._udp_alt)):
                    for iface in netinfo.get_local_ifaces():
                        try:
                            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                                            grp + socket.inet_aton(iface.ip))
                        except Exception:
                            pass
            except Exception:
                pass
            asyncio.get_running_loop().create_task(self._udp_listen(s))
            if self._udp_alt:
                asyncio.get_running_loop().create_task(self._udp_listen(self._udp_alt))
            return True
        except OSError as e:
            self.emit({"event": "log", "level": "error",
                       "msg": f"UDP 端口 {self.port} 绑定失败: {e}"})
            return False

    async def _udp_listen(self, s):
        loop = asyncio.get_running_loop()
        while True:
            try:
                data, addr = await loop.sock_recvfrom(s, 65536)
            except asyncio.CancelledError:
                return
            except Exception:
                await asyncio.sleep(0.2)
                continue
            try:
                msg = P.parse_disc(data)
                if not msg:
                    continue
                pid = msg.get("id")
                ip = addr[0] if addr else ""
                if pid == self.device_id:
                    continue
                peer = self._touch_peer(msg, ip)
                now = time.time()
                if now - self._last_reply.get(pid, 0) > 10:
                    self._last_reply[pid] = now
                    try:
                        await loop.sock_sendto(
                            s, self._disc_packet(), (ip, addr[1]))
                    except Exception:
                        pass
                self._ensure_connected(peer)
            except Exception:
                continue

    def _disc_packet(self) -> bytes:
        return P.encode_disc_msg(self.device_id, self.name, PLATFORM, self.port,
                                 host=self.hostname, alt_ids=self.alt_ids)

    def _touch_peer(self, msg, ip) -> Peer:
        pid = msg["id"]
        merged_from = self._merge_candidate(pid, msg)
        if merged_from:
            self._merge_peer(merged_from, pid)
        peer = self.peers.get(pid)
        if not peer:
            peer = Peer(pid)
            self.peers[pid] = peer
            self.emit({"event": "log", "level": "info",
                       "msg": f"发现设备 {msg.get('name') or pid[:8]} ({ip})"})
        if msg.get("name"):
            peer.name = msg["name"]
        if msg.get("platform"):
            peer.platform = msg["platform"]
        if msg.get("host"):
            peer.host = msg["host"]
        if msg.get("tcp"):
            try:
                peer.tcp_port = int(msg["tcp"])
            except Exception:
                pass
        if ip and ip not in peer.ips:
            peer.ips.insert(0, ip)
            peer.ips = peer.ips[:8]
        peer.last_seen = time.time()
        return peer

    def _merge_candidate(self, pid: str, msg: dict):
        """判断是否与已有 peer 为同一台设备（跨版本身份）：
        host 唯一标识相同，或 pid 命中对端广播的旧 ID 列表。
        仅合并离线条目：生产环境同机旧版本关闭后其条目必然离线，
        而同机多实例（FLASHDROP_ALLOW_MULTI=1 调试/测试）都在线，不应合并。"""
        host = msg.get("host")
        alts = msg.get("alt") or []
        if not host and not alts:
            return None
        for p in self.peers.values():
            if p.id == pid or p.online(self.conns):
                continue
            if (host and p.host and p.host == host) or (p.id in alts):
                return p.id
        return None

    def _merge_peer(self, old_id: str, new_id: str):
        """同机不同版本的设备身份合并：旧条目并入新条目，连接改键，通知 UI 迁移历史"""
        old = self.peers.get(old_id)
        if not old:
            return
        peer = self.peers.get(new_id)
        if peer is None:
            peer = Peer(new_id)
            self.peers[new_id] = peer
        for ip in old.ips:
            if ip not in peer.ips:
                peer.ips.append(ip)
        peer.ips = peer.ips[:8]
        if old.name and not peer.name:
            peer.name = old.name
        if old.platform and not peer.platform:
            peer.platform = old.platform
        if old.host:
            peer.host = old.host
        peer.manual = peer.manual or old.manual
        peer.last_seen = max(peer.last_seen, old.last_seen)
        self.peers.pop(old_id, None)
        conn = self.conns.get(old_id)
        if conn is not None:
            self.conns.pop(old_id, None)
            self.conns[new_id] = conn
            conn.peer_id = new_id
        self.emit({"event": "log", "level": "info",
                   "msg": f"设备身份已合并：{old_id[:8]} → {new_id[:8]}"})
        self.emit({"event": "peer_merged", "old": old_id, "new": new_id})

    def _announce_targets(self):
        ports = {self.port, P.DEFAULT_PORT}
        targets = [("255.255.255.255", p) for p in ports]
        targets.append(("127.0.0.1", self.port))
        for iface in netinfo.get_local_ifaces():
            if iface.broadcast:
                targets.extend((iface.broadcast, p) for p in ports)
        targets.extend((P.MULTICAST_GROUP, p) for p in ports)
        return targets

    async def _announce_loop(self):
        pkt = self._disc_packet()
        loop = asyncio.get_running_loop()
        first = True
        while True:
            delay = 1.0 if first else 3.0
            first = False
            for t in self._announce_targets():
                try:
                    await loop.sock_sendto(self._udp, pkt, t)
                except Exception:
                    pass
            await asyncio.sleep(delay)

    async def _expire_loop(self):
        last_sig = None
        gc_t = 0.0
        while True:
            await asyncio.sleep(2.0)
            now = time.time()
            changed = False
            for peer in list(self.peers.values()):
                c = self.conns.get(peer.id)
                if c and c.alive and not c.replaced:
                    peer.last_seen = max(peer.last_seen, now - 1)
                if (not peer.online(self.conns) and not peer.manual
                        and now - peer.last_seen > PEER_OFFLINE_REMOVE):
                    self.peers.pop(peer.id, None)
                    changed = True
            # ★ v1.18.18：每 5 分钟清理一次过期断点残留（.part/.bmp/.fp）。
            # 只删**没有任何在途任务**的旧文件，避免删掉正在续传的数据。
            if now - gc_t > 300:
                gc_t = now
                self._gc_resume_state(now)
            # 仅在设备状态签名变化时通知 UI，避免每 2 秒全量重建设备列表
            sig = tuple(sorted(
                (p.id, p.online(self.conns),
                 bool(self.conns.get(p.id) and self.conns[p.id].alive
                      and not self.conns[p.id].replaced),
                 p.name, p.tcp_port, tuple(p.ips[:1]))
                for p in self.peers.values()))
            if changed or sig != last_sig:
                self._notify_peers()
            last_sig = sig

    def _gc_resume_state(self, now: float):
        """清理过期的断点残留文件。

        保留期由 RESUME_TTL（默认 7 天）决定；先删 .bmp/.fp 再删 .part，
        顺序保证不会出现"位图没了但 .part 还在"的半状态（那会退化成全量重传，
        不会出错，只是浪费）。
        """
        try:
            d = self.cfg.cache_dir
            if not d or not os.path.isdir(d):
                return
            live = set()
            for key in self.inbounds:
                live.add(key[1])
            for k, info in self._send_info.items():
                if info.get("targets"):
                    live.add(k)
            for fn in os.listdir(d):
                for suf in (".bmp", ".fp", ".part"):
                    if not fn.endswith(suf):
                        continue
                    tid = fn[: -len(suf)]
                    if tid in live:
                        continue
                    p = os.path.join(d, fn)
                    try:
                        if now - os.path.getmtime(p) > RESUME_TTL:
                            os.remove(p)
                    except Exception:
                        pass
        except Exception:
            pass

    # ============================ 设备备注 ============================

    def set_alias(self, peer_id: str, alias: str):
        """设置/清除设备备注（空串 = 清除备注，恢复显示设备自报名）"""
        if not peer_id:
            return
        aliases = dict(self.cfg["peer_aliases"] or {})
        alias = (alias or "").strip()[:40]
        if alias:
            aliases[peer_id] = alias
        else:
            aliases.pop(peer_id, None)
        self.cfg["peer_aliases"] = aliases
        self._notify_peers()

    def get_alias(self, peer_id: str) -> str:
        try:
            return (self.cfg["peer_aliases"] or {}).get(peer_id, "") or ""
        except Exception:
            return ""

    # 消息搜索的实现见 ui/history.py 的 History.search()：
    # 搜索是纯读操作，属于历史记录层，不该耦合传输状态机。

    async def _bg_scan_loop(self):
        while True:
            await asyncio.sleep(30.0)
            if self._scanning:
                continue
            try:
                await self.scan(full=False)
            except Exception:
                pass

    def _notify_peers(self):
        snaps = [p.snapshot(self.conns) for p in self.peers.values()]
        snaps.sort(key=lambda x: (not x["online"], not x["connected"], x["name"]))
        self.emit({"event": "peers", "peers": snaps})

    # ============================ 连接管理 ============================

    async def _on_accept(self, reader, writer):
        conn = Conn(reader, writer, incoming=True)
        try:
            # 识别 TLS ClientHello（0x16）：开启加密时自动升级为 TLS 连接
            first = await asyncio.wait_for(reader.readexactly(1), timeout=6.0)
            # 预读字节必须插回缓冲区队首（feed_data 是追加，会破坏帧结构）
            reader._buffer[:0] = first
            if first == b"\x16":
                ctx = self._tls_server_context()
                if ctx is not None:
                    loop = asyncio.get_running_loop()
                    new_tr = await loop.start_tls(writer.transport, ctx,
                                                  server_side=True)
                    writer._transport = new_tr
        except (asyncio.IncompleteReadError, asyncio.TimeoutError):
            await conn.close()
            return
        except Exception:
            await conn.close()
            return
        try:
            await conn.send_json(self._hello_msg())
        except Exception:
            await conn.close()
            return
        await self._session(conn)

    def _hello_msg(self):
        try:
            ips = netinfo.get_local_ips()
        except Exception:
            ips = []
        msg = {"app": P.APP, "v": P.PROTO_VERSION, "type": P.T_HELLO,
               "id": self.device_id, "name": self.name, "platform": PLATFORM,
               "tcp": self.port, "ips": ips}
        if self.hostname:
            msg["host"] = self.hostname
        if self.alt_ids:
            msg["alt"] = list(self.alt_ids)
        return msg

    async def _recv_hello(self, conn: Conn, timeout=6.0):
        """读取并校验首帧 HELLO"""
        try:
            hdr = await asyncio.wait_for(conn.reader.readexactly(4), timeout=timeout)
            (length,) = struct.unpack(">I", hdr)
            if length <= 1 or length > P.MAX_FRAME:
                raise P.ProtocolError("bad length")
            payload = await asyncio.wait_for(conn.reader.readexactly(length), timeout=timeout)
            if payload[0] != P.KIND_JSON:
                raise P.ProtocolError("first frame not json")
            hello = jsonlib.loads(payload[1:].decode("utf-8"))
        except asyncio.IncompleteReadError:
            return None
        except Exception:
            return None
        if not isinstance(hello, dict) or hello.get("app") != P.APP or not hello.get("id"):
            return None
        return hello

    async def _session(self, conn: Conn):
        """新连接会话：等 HELLO、注册去重、进入读循环"""
        hello = await self._recv_hello(conn)
        if not hello:
            await conn.close()
            return
        if hello["id"] == self.device_id:
            await conn.close()
            return
        ok = await self._register_conn(conn, hello)
        if not ok:
            return
        await self._reader_loop(conn)

    def _conn_preferred(self, conn: Conn, peer_id: str) -> bool:
        if conn.incoming:
            return peer_id > self.device_id
        return self.device_id > peer_id

    async def _register_conn(self, conn: Conn, hello: dict) -> bool:
        pid = hello["id"]
        conn.peer_id = pid
        conn.hello_got = True
        conn.last_recv = time.time()

        merged_from = self._merge_candidate(pid, hello)
        if merged_from:
            self._merge_peer(merged_from, pid)

        peer = self.peers.get(pid)
        if not peer:
            peer = Peer(pid)
            self.peers[pid] = peer
        if hello.get("name"):
            peer.name = hello["name"]
        if hello.get("platform"):
            peer.platform = hello["platform"]
        if hello.get("host"):
            peer.host = hello["host"]
        if hello.get("tcp"):
            try:
                peer.tcp_port = int(hello["tcp"])
            except Exception:
                pass
        peer.last_seen = time.time()
        if conn.remote_ip and conn.remote_ip not in peer.ips:
            peer.ips.insert(0, conn.remote_ip)
            peer.ips = peer.ips[:8]

        existing = self.conns.get(pid)
        if existing is not None and existing is not conn and existing.alive \
                and not existing.replaced:
            # v1.11.0 修复「连着但收不到对端发来的文字」：
            # 原逻辑只看 incoming 方向偏好（_conn_preferred），**同方向的两条连接
            # new_pref == old_pref**，于是走进 else 把"新来的"这条 close 掉。
            # 但对端重连 / 双向同时互连时，真实情况恰恰是新连接才是活的那条 ——
            # 丢掉它 = 这条链路上后续所有 TEXT 都被对端读不到，表现为
            # "已连接却收不到文字"，而文件会走重试/另一条链路所以还能收到。
            #
            # 现在的规则（与 Android 端 FlashNode.registerConn 保持一致）：
            #   1) 方向不同 → 仍按原偏好规则，保留偏好方向那条（跨 NAT 单向可达时需要）
            #   2) 方向相同 → **新连接接管旧连接**（更新的握手更可信）
            new_pref = self._conn_preferred(conn, pid)
            old_pref = self._conn_preferred(existing, pid)
            if new_pref != old_pref:
                if new_pref:
                    # 新连接方向更优：替换
                    existing.replaced = True
                    self.conns[pid] = conn
                    asyncio.get_running_loop().create_task(self._delayed_close(existing, 1.0))
                    self.emit({"event": "log", "level": "info",
                               "msg": f"与 {peer.name or pid[:8]} 的连接已切换为首选链路"})
                else:
                    # 旧连接方向更优：丢弃新来的
                    await conn.close()
                    return False
            else:
                # 同方向重复连接：新接管旧（v1.11.0 修复点）
                existing.replaced = True
                self.conns[pid] = conn
                asyncio.get_running_loop().create_task(self._delayed_close(existing, 1.0))
                self.emit({"event": "log", "level": "info",
                           "msg": f"与 {peer.name or pid[:8]} 的连接已更新为最新链路"})
        else:
            self.conns[pid] = conn

        subnet = self._subnet_of(conn.remote_ip)
        if subnet:
            self.cfg.remember_subnet(subnet)

        asyncio.get_running_loop().create_task(self._heartbeat_loop(conn))
        self.emit({"event": "log", "level": "info",
                   "msg": f"已连接 {peer.name or pid[:8]} "
                          f"({conn.remote_ip}:{conn.remote_port})"})
        self._notify_peers()
        return True

    async def _delayed_close(self, conn: Conn, delay: float):
        await asyncio.sleep(delay)
        conn.replaced = True
        await conn.close()

    async def _heartbeat_loop(self, conn: Conn):
        try:
            while conn.alive and not conn.replaced:
                await asyncio.sleep(10.0)
                if not conn.alive or conn.replaced:
                    return
                # ★ v1.16.0：有在途接收任务时放宽死亡判定
                grace = (CONN_DEAD_AFTER_BUSY if self.inbounds
                         else CONN_DEAD_AFTER)
                if time.time() - conn.last_recv > grace:
                    break
                try:
                    await conn.send_json({"type": P.T_PING})
                except Exception:
                    break
        finally:
            await conn.close()

    async def _reader_loop(self, conn: Conn):
        try:
            while conn.alive:
                kind, a, b = await P.read_frame(conn.reader)
                conn.last_recv = time.time()
                if kind == P.KIND_CHUNK:
                    # ★ v1.18.18：带块号分块。replaced 连接仍要处理数据帧，
                    # 否则切链路瞬间在途的块会丢。
                    if conn.peer_id:
                        tid, idx = a
                        await self._on_bin(conn, tid, b, index=idx)
                    continue
                if conn.replaced:
                    if kind == P.KIND_BIN:
                        await self._on_bin(conn, a, b)
                    continue
                if kind == P.KIND_JSON:
                    await self._on_json(conn, a)
                else:
                    await self._on_bin(conn, a, b)
        except (asyncio.IncompleteReadError, ConnectionResetError, OSError):
            pass
        except P.ProtocolError as e:
            self.emit({"event": "log", "level": "warn", "msg": f"协议错误: {e}"})
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.emit({"event": "log", "level": "warn", "msg": f"读循环异常: {e}"})
        finally:
            await conn.close()
            pid = conn.peer_id
            if pid and self.conns.get(pid) is conn:
                self.conns.pop(pid, None)
                peer = self.peers.get(pid)
                if peer:
                    peer.next_retry = time.time() + peer.retry_backoff
                    peer.retry_backoff = min(peer.retry_backoff * 2, 30.0)
                    self._ensure_connected(peer, force=True)
            # ★ v1.18.18：连接断开会**保留**该连接上的接收断点
            #（.part + 位图），等发送方重连后 FILE_START 同 tid 即可续传。
            for key, ib in list(self.inbounds.items()):
                if key[0] == pid and ib.started and not ib.done:
                    self._flush_bitmap(ib, force=True)
                    self._cleanup_inbound(ib, drop_state=False)
                    self.emit(self._recv_evt(ib, "paused",
                                             reason="连接中断，可断点续传"))
            self._notify_peers()

    # ============================ 消息分发 ============================

    async def _on_json(self, conn: Conn, obj: dict):
        t = obj.get("type")
        pid = conn.peer_id
        if t == P.T_HELLO:
            return  # 已在握手阶段处理
        if t == P.T_PING:
            try:
                await conn.send_json({"type": P.T_PONG})
            except Exception:
                pass
            return
        if t == P.T_PONG:
            return
        if t == P.T_BYE:
            await conn.close()
            peer = self.peers.get(pid)
            if peer:
                peer.last_seen = 0
            self._notify_peers()
            return
        if t == P.T_TEXT:
            mid = obj.get("mid") or util.gen_uid()
            # ★ v1.18.18：走 display_name，否则用户给设备起的备注
            #   对文本消息完全不生效（气泡头像 / 托盘通知仍是旧名）。
            self.emit({"event": "text", "peer_id": pid,
                       "name": self.display_name(pid),
                       "mid": mid, "text": obj.get("text", ""),
                       "ts": obj.get("ts") or int(time.time() * 1000),
                       "scheme": obj.get("scheme", "")})
            try:
                await conn.send_json({"type": P.T_ACK, "mid": mid})
            except Exception:
                pass
            return
        if t == P.T_ACK:
            mid = obj.get("mid")
            fut = self.ack_waiters.pop((pid, mid), None)
            if fut and not fut.done():
                fut.set_result(True)
            self.emit({"event": "ack", "peer_id": pid, "mid": mid})
            return
        if t == P.T_FILE_START:
            await self._on_file_start(conn, obj)
            return
        if t == P.T_RECV_READY:
            key = (pid, obj.get("tid"))
            fut = self.ready_waiters.pop(key, None)
            if fut and not fut.done():
                # ★ v1.18.18：把断点信息（已收块位图）随结果一起回传给发送任务
                extra = None
                if obj.get("idx"):
                    extra = {"idx": 1, "have": obj.get("have") or [],
                             "total": obj.get("total"), "recv": obj.get("recv")}
                fut.set_result(("ready", extra))
            return
        if t == P.T_FILE_END:
            await self._on_file_end(conn, obj)
            return
        if t == P.T_FILE_OK:
            # ★ v1.16.0：接收方回读确认为 false 时按失败处理 ——
            # 对方虽回了 OK，但文件没真正落盘，不能对用户显示"已发送"。
            if obj.get("verified") is False:
                self._resolve_out(pid, obj.get("tid"), "fail", "对方未能写入文件")
            else:
                self._resolve_out(pid, obj.get("tid"), "ok", obj.get("path"))
            return
        if t == P.T_FILE_FAIL:
            self._resolve_out(pid, obj.get("tid"), "fail", obj.get("reason"))
            return
        if t == P.T_REFUSE:
            tid = obj.get("tid")
            for m in (self.ready_waiters, self.out_waiters):
                fut = m.pop((pid, tid), None)
                if fut and not fut.done():
                    fut.set_result(("refuse", obj.get("reason")))
            st = self.out_states.get(tid)
            if st and pid in st and st[pid] not in ("ok", "fail", "refuse", "cancel"):
                st[pid] = "refuse"
                self._emit_send_state(tid, pid, "refused",
                                      reason=obj.get("reason") or "对方拒绝接收")
            return
        if t == P.T_CANCEL:
            tid = obj.get("tid")
            ib = self.inbounds.get((pid, tid))
            if ib:
                self._cleanup_inbound(ib, drop_state=True)
                self._emit_recv_state(ib, "cancelled", reason="对方已取消")
                return
            st = self.out_states.get(tid)
            if st and pid in st and st[pid] not in ("ok", "fail", "refuse", "cancel"):
                st[pid] = "cancel"
                for m in (self.ready_waiters, self.out_waiters):
                    fut = m.pop((pid, tid), None)
                    if fut and not fut.done():
                        fut.set_result(("cancel", None))
                self._emit_send_state(tid, pid, "cancelled", reason="对方已取消")
            return
        # 未知类型忽略（向前兼容）

    def _resolve_out(self, pid, tid, result, extra):
        fut = self.out_waiters.pop((pid, tid), None)
        if fut and not fut.done():
            fut.set_result((result, extra))
        st = self.out_states.get(tid)
        if st and pid in st:
            st[pid] = result
            if result == "ok":
                self._emit_send_state(tid, pid, "ok", path=extra)
            else:
                self._emit_send_state(tid, pid, "failed",
                                      reason=extra or "对方接收失败")

    async def _on_bin(self, conn: Conn, tid: str, data: bytes, index: int = -1):
        """index >= 0 表示带块号的分块（断点续传路径）"""
        ib = self.inbounds.get((conn.peer_id, tid))
        if not ib or ib.done or not ib.started or ib.canceled:
            return
        try:
            if index >= 0 and ib.mode == "chunk":
                # 重复块：直接丢弃（幂等，重发不会写坏文件）
                if ib.cmap.has(index):
                    return
                want = R.chunk_len(index, ib.meta["size"])
                if len(data) != want:
                    ib.mode = "stream"  # 块长对不上 → 后续按顺序流处理
                    ib.f.seek(ib.received)
                    ib.f.write(data)
                    if ib.md5 is None:
                        ib.md5 = hashlib.md5()
                    ib.md5.update(data)
                    ib.received += len(data)
                else:
                    ib.f.seek(R.chunk_offset(index))
                    ib.f.write(data)
                    ib.cmap.add(index)
                    ib.since_bmp += 1
                    ib.received = ib.cmap.received_bytes(ib.meta["size"])
                    ib.win_bytes += len(data)
                    self._flush_bitmap(ib)
            else:
                ib.f.write(data)
                if ib.md5:
                    ib.md5.update(data)
                ib.received += len(data)
                ib.win_bytes += len(data)
        except Exception as e:
            self._cleanup_inbound(ib, drop_state=True)
            self._emit_recv_state(ib, "failed", reason=f"写入失败: {e}")
            try:
                await conn.send_json({"type": P.T_FILE_FAIL, "tid": tid, "reason": str(e)})
            except Exception:
                pass
            return
        if ib.received > ib.meta["size"]:
            self._cleanup_inbound(ib, drop_state=True)
            self._emit_recv_state(ib, "failed", reason="数据超出声明大小")
            return
        now = time.time()
        if now - ib.last_evt > 0.15:
            ib.last_evt = now
            dt = now - ib.win_t
            speed = ib.win_bytes / dt if dt > 0.05 else 0
            if dt > 1.0:
                ib.win_bytes = 0
                ib.win_t = now
            self.emit(self._recv_evt(ib, "progress", speed=speed))

    # ============================ 接收 ============================

    async def _on_file_start(self, conn: Conn, obj: dict):
        tid = obj.get("tid")
        if not tid:
            return
        key = (conn.peer_id, tid)
        # ★ v1.18.19：幂等 —— 该 tid 若**最近已完整接收**，直接回 FILE_OK
        # 告知发送方"已收过"。场景：FILE_OK 在返回路上连接断开，发送端
        # 300s 等待超时后同 tid 重试；不处理的话接收端会整文件再收一遍
        # （重复落盘 + 接收端出现第二条气泡）。
        # 注意不能用 inbounds 判定：成功路径会把 inbound 从注册表 pop 掉。
        prev = self._recent_done.pop(tid, None)
        if prev is not None:
            try:
                await conn.send_json(
                    {"type": P.T_FILE_OK, "tid": tid, "path": prev[0],
                     "verified": True, "size": prev[1], "duplicate": True})
            except Exception:
                pass
            return
        if key in self.inbounds:
            return
        meta = {
            "name": util.safe_filename(obj.get("name") or "file"),
            "size": int(obj.get("size") or 0),
            "mime": obj.get("mime") or "application/octet-stream",
        }
        ib = Inbound(conn.peer_id, tid, meta)
        ib.scheme = obj.get("scheme", "")
        ib.attempt = int(obj.get("attempt") or 0)
        # ★ v1.18.18：对方是否支持带块号的分块（断点续传）。
        # 只有双方都声明支持才走 chunk 模式，否则退回老的顺序流，
        # 这样 v1.18.17 及更早版本仍能与本版互传（老版本忽略未知字段）。
        ib.resume_supported = bool(obj.get("idx"))
        self.inbounds[key] = ib
        self.emit(self._recv_evt(ib, "offer"))
        if self.cfg["auto_accept"]:
            if self._begin_inbound(ib):
                await self._send_recv_ready(conn, ib)
        else:
            self.emit(self._recv_evt(ib, "confirm"))

            async def _timeout():
                await asyncio.sleep(RECV_CONFIRM_TTL)
                cur = self.inbounds.get(key)
                if cur is ib and not ib.started and not ib.done:
                    self._cleanup_inbound(ib, drop_state=True)
                    self.emit(self._recv_evt(ib, "refused", reason="确认超时，已自动拒绝"))
                    try:
                        await conn.send_json({"type": P.T_REFUSE, "tid": tid,
                                              "reason": "timeout"})
                    except Exception:
                        pass
            asyncio.get_running_loop().create_task(_timeout())

    async def _send_recv_ready(self, conn: Conn, ib: Inbound):
        """回 RECV_READY，chunk 模式下附带已收块位图（断点信息）"""
        msg = {"type": P.T_RECV_READY, "tid": ib.tid}
        if ib.mode == "chunk":
            msg["idx"] = 1
            msg["have"] = ib.cmap.to_compact()
            msg["total"] = ib.cmap.n
            msg["recv"] = ib.received
        try:
            await conn.send_json(msg)
        except Exception:
            pass

    def _begin_inbound(self, ib: Inbound) -> bool:
        """准备接收。返回是否成功开始。

        ★ v1.18.18：chunk 模式下会尝试**恢复已有 .part**：
        校验指纹（同一文件）+ 读回位图 + 校验 .part 实际大小，
        三者一致才续传，否则清干净重来（宁可多传，不产出损坏文件）。
        """
        if ib.started:
            return True
        try:
            os.makedirs(self.cfg.cache_dir, exist_ok=True)
            ib.path_part = os.path.join(self.cfg.cache_dir, ib.tid + ".part")
            size = ib.meta["size"]
            nchunks = R.total_chunks(size)
            fp = R.resume_fingerprint(size, ib.meta["name"])
            if ib.resume_supported:
                ib.mode = "chunk"
                ib.cmap = R.ChunkMap(nchunks)
                prev_fp = R.load_fingerprint(self.cfg.cache_dir, ib.tid)
                prev_cm = R.ChunkMap.load(self.cfg.cache_dir, ib.tid, nchunks)
                part_size = -1
                try:
                    if os.path.exists(ib.path_part):
                        part_size = os.path.getsize(ib.path_part)
                except Exception:
                    part_size = -1
                resumable = (prev_fp == fp and part_size == size
                             and prev_cm.count() > 0)
                if resumable:
                    ib.cmap = prev_cm
                    ib.pending = []
                    ib.received = ib.cmap.received_bytes(size)
                    ib.f = open(ib.path_part, "r+b")
                    self.emit({"event": "log", "level": "info",
                               "msg": f"断点续传：{ib.meta['name']} "
                                      f"已完成 {ib.cmap.count()}/{nchunks} 块"})
                else:
                    # 不匹配 → 清干净重来
                    R.drop_resume_state(self.cfg.cache_dir, ib.tid)
                    ib.cmap = R.ChunkMap(nchunks)
                    ib.received = 0
                    ib.f = open(ib.path_part, "wb")
                # ★ 关键：把 .part **预分配到完整大小**。
                # 断点续传时缺块判定依赖 part_size == size，
                # 且 seek 写入稀疏文件在部分文件系统上会得到错误的文件大小。
                try:
                    ib.f.truncate(size)
                except Exception:
                    pass
                R.save_fingerprint(self.cfg.cache_dir, ib.tid, size, ib.meta["name"])
            else:
                ib.mode = "stream"
                ib.f = open(ib.path_part, "wb")
                ib.received = 0
            # stream 模式用增量 md5；chunk 模式等全部块到齐后整体算 md5
            ib.md5 = None if ib.mode == "chunk" else hashlib.md5()
            ib.started = True
            ib.confirmed = True
            ib.last_bmp_save = time.time()
            ib.t0 = time.time()
            self.emit(self._recv_evt(ib, "started"))
            return True
        except Exception as e:
            self._cleanup_inbound(ib, drop_state=True)
            self.emit(self._recv_evt(ib, "failed", reason=f"无法创建缓存文件: {e}"))
            return False

    def _flush_bitmap(self, ib: Inbound, force=False):
        """位图落盘（节流）：崩溃/断线后能续的最大努力"""
        if ib.mode != "chunk" or not ib.cmap:
            return
        now = time.time()
        if not force:
            if (ib.since_bmp < BITMAP_FLUSH_CHUNKS
                    and now - ib.last_bmp_save < BITMAP_FLUSH_SECS):
                return
        try:
            ib.f.flush()
            os.fsync(ib.f.fileno())
        except Exception:
            pass
        ib.cmap.save(self.cfg.cache_dir, ib.tid)
        ib.last_bmp_save = now
        ib.since_bmp = 0
        ib.pending = []

    async def _on_file_end(self, conn: Conn, obj: dict):
        tid = obj.get("tid")
        ib = self.inbounds.get((conn.peer_id, tid))
        if not ib or not ib.started or ib.done:
            return
        ib.done = True
        try:
            ib.f.close()
        except Exception:
            pass
        ib.f = None
        size = ib.meta["size"]
        expect_md5 = (obj.get("md5") or "").lower()
        if ib.mode == "chunk":
            # chunk 模式：先确认位图完整（不依赖累加计数，避免漂移）
            self._flush_bitmap(ib, force=True)
            if not ib.cmap.complete():
                miss = ib.cmap.missing()
                self.emit(self._recv_evt(ib, "failed",
                                         reason=f"缺少数据块（{len(miss)} 块未收）"))
                try:
                    await conn.send_json({"type": P.T_FILE_FAIL, "tid": tid,
                                          "reason": f"missing {len(miss)} chunks"})
                except Exception:
                    pass
                # ★ v1.18.18 审计修复：必须把 inbound 从注册表摘掉
                #   （保留断点）。否则发送方重试的 FILE_START 命中
                #   "key 已存在"直接 return，永远等不到 RECV_READY →
                #   45s 超时 ×3 次重试全败，且补发的块被 ib.done 丢弃 ——
                #   该文件在本次运行期间永久无法续传。
                #   对齐 Android 端 onFileEnd 缺块分支 cleanupInbound(ib, false)。
                self._cleanup_inbound(ib, drop_state=False)
                return
            ib.received = size
            # 全部块到齐 → 整体算 md5（chunk 模式下不能增量算，因为块可能乱序到达）
            ib.md5 = self._md5_of_file(ib.path_part)
        else:
            if ib.received != size:
                self._cleanup_inbound(ib, drop_state=True)
                self.emit(self._recv_evt(ib, "failed", reason="文件大小校验失败"))
                try:
                    await conn.send_json({"type": P.T_FILE_FAIL, "tid": tid,
                                          "reason": "size mismatch"})
                except Exception:
                    pass
                return
        if expect_md5 and ib.md5:
            # ★ md5 两种形态：stream 模式是增量 hashlib 对象，
            # chunk 模式是全量算完的十六进制字符串。
            actual = ib.md5 if isinstance(ib.md5, str) else ib.md5.hexdigest()
            if actual != expect_md5:
                # ★ 校验失败：位图与 .part 已无意义（可能拼了错块），必须丢弃
                self._cleanup_inbound(ib, drop_state=True)
                self.emit(self._recv_evt(ib, "failed", reason="MD5 校验失败"))
                try:
                    await conn.send_json({"type": P.T_FILE_FAIL, "tid": tid,
                                          "reason": "md5 mismatch"})
                except Exception:
                    pass
                return
        try:
            # 按设备分文件夹：<保存目录>\<设备名>\<文件名>（类微信的"每台设备一个文件夹"）
            peer = self.peers.get(ib.peer_id)
            pname = self.display_name(ib.peer_id)
            folder = util.safe_folder(pname)
            dest_dir = os.path.join(self.cfg.save_dir, folder)
            os.makedirs(dest_dir, exist_ok=True)
            dest = util.unique_path(dest_dir, ib.meta["name"])
            os.replace(ib.path_part, dest)
            ib.path_part = None
        except Exception as e:
            # ★ v1.18.18 审计修复：落盘失败保留断点（drop_state=False）——
            #   .part 数据完整且校验通过，删了断点等于让用户整文件重传；
            #   对齐 Android 端 cleanupInbound(ib, chunkMode) 的行为。
            self._cleanup_inbound(ib, drop_state=(ib.mode != "chunk"))
            self.emit(self._recv_evt(ib, "failed", reason=f"保存失败: {e}"))
            try:
                await conn.send_json({"type": P.T_FILE_FAIL, "tid": tid,
                                      "reason": "save error"})
            except Exception:
                pass
            return
        R.drop_resume_state(self.cfg.cache_dir, ib.tid)
        self.inbounds.pop((conn.peer_id, tid), None)
        # ★ v1.18.19：登记“最近完整接收”，供发送端 FILE_OK 丢失后的
        # 同 tid 重试做幂等应答（不再重复接收）
        self._recent_done[tid] = (dest, ib.meta["size"])
        if len(self._recent_done) > 128:
            try:
                self._recent_done.pop(next(iter(self._recent_done)))
            except Exception:
                pass
        dt = max(time.time() - ib.t0, 0.001)
        self.emit(self._recv_evt(ib, "done", path=dest,
                                 speed=ib.meta["size"] / dt))
        # ★ v1.16.0：落盘后**回读确认**（read-back）。
        # 仅"os.replace 没抛异常"不足以证明文件真的可用（磁盘写缓存、
        # 被安全软件拦截等都会造成假成功），会导致发送端显示"已发送"
        # 而接收端实际拿不到文件。这里回读一次大小并回传结果。
        verified = self._verify_saved(dest, ib.meta["size"])
        try:
            await conn.send_json({"type": P.T_FILE_OK, "tid": tid, "path": dest,
                                  "verified": verified,
                                  "size": ib.meta["size"]})
        except Exception:
            pass

    @staticmethod
    def _md5_of_file(path: str) -> str:
        h = hashlib.md5()
        try:
            with open(path, "rb") as f:
                while True:
                    b = f.read(1024 * 1024)
                    if not b:
                        break
                    h.update(b)
        except Exception:
            return ""
        return h.hexdigest()

    def display_name(self, peer_id: str) -> str:
        """设备显示名：**备注优先**，其次设备自报名，最后 id 前 8 位。

        ★ v1.18.18：新增设备备注功能。备注只影响本机显示，
        不改写对端自报名（否则两端会互相覆盖备注）。
        """
        try:
            alias = (self.cfg["peer_aliases"] or {}).get(peer_id)
            if alias and str(alias).strip():
                return str(alias).strip()
        except Exception:
            pass
        peer = self.peers.get(peer_id)
        if peer and peer.name:
            return peer.name
        return (peer_id or "")[:8] or "未知设备"

    @staticmethod
    def _verify_saved(path: str, expect_size: int) -> bool:
        """回读确认：文件存在且大小与声明一致。

        主动删除（用户手动删消息 / 清空聊天）不参与本校验 ——
        那是用户意图，不是传输异常。
        """
        try:
            return bool(path) and os.path.isfile(path) \
                and os.path.getsize(path) == expect_size
        except Exception:
            return False

    def _cleanup_inbound(self, ib: Inbound, drop_state=False):
        """清理接收任务。

        ★ v1.18.18：`drop_state` 语义很关键：
        - False（默认，**连接中断**）：**保留** .part + 位图，
          等发送方重连后自动续传。这是断点续传生效的地方。
        - True（**校验失败/用户取消/对方拒绝**）：连位图一起删，
          因为这些场景继续用旧数据会产出损坏文件。
        """
        if not ib:
            return
        if ib.f:
            try:
                # 先把已写数据刷到盘，否则位图说"收到了"而 .part 里没有
                ib.f.flush()
                if ib.mode == "chunk":
                    os.fsync(ib.f.fileno())
            except Exception:
                pass
            try:
                ib.f.close()
            except Exception:
                pass
        ib.f = None
        if ib.path_part and os.path.exists(ib.path_part):
            if drop_state:
                try:
                    os.remove(ib.path_part)
                except Exception:
                    pass
                ib.path_part = None
        if drop_state:
            R.drop_resume_state(self.cfg.cache_dir, ib.tid)
        self.inbounds.pop((ib.peer_id, ib.tid), None)

    def _recv_evt(self, ib: Inbound, state, path=None, reason=None, speed=None):
        return {"event": "transfer", "kind": "recv", "tid": ib.tid,
                "peer_id": ib.peer_id, "name": self.display_name(ib.peer_id),
                "file": ib.meta["name"], "size": ib.meta["size"],
                "mime": ib.meta["mime"], "transferred": ib.received,
                "state": state, "path": path, "reason": reason, "speed": speed or 0,
                "scheme": getattr(ib, "scheme", ""),
                "total_chunks": (ib.cmap.n if ib.cmap else 0),
                "have_chunks": (ib.cmap.count() if ib.cmap else 0),
                "attempt": ib.attempt}

    def _emit_recv_state(self, ib: Inbound, state, reason=None, path=None):
        self.emit(self._recv_evt(ib, state, reason=reason, path=path))

    # ============================ 发送 ============================

    def send_text(self, target_ids: list, text: str) -> str:
        mid = util.gen_uid()
        self._post(self._send_text_task(list(target_ids), mid, text))
        return mid

    # ★ v1.18.15：阻塞版发送（**必须在工作线程调用**）。
    #   待发队列靠它判断"到底送没送到"，只有确认送达才把条目移出队列。
    def send_text_sync(self, target_ids: list, text: str,
                      timeout: float = 45.0) -> tuple:
        mid = util.gen_uid()
        fut = asyncio.run_coroutine_threadsafe(
            self._send_text_task(list(target_ids), mid, text), self.loop)
        return mid, fut.result(timeout=timeout)

    async def _send_text_task(self, target_ids, mid, text):
        # ★ v1.18.15：返回 {peer_id: ok/failed/timeout}，供待发队列判定去留
        results = {}
        for pid in target_ids:
            conn = await self._wait_conn(pid, 15.0)
            if not conn:
                results[pid] = "failed"
                self.emit({"event": "text_state", "peer_id": pid, "mid": mid,
                           "state": "failed", "reason": "设备不在线"})
                continue
            fut = asyncio.get_running_loop().create_future()
            self.ack_waiters[(pid, mid)] = fut
            try:
                await conn.send_json({"type": P.T_TEXT, "mid": mid, "text": text,
                                      "ts": int(time.time() * 1000),
                                      "scheme": self.cfg["bubble_scheme"]})
            except Exception as e:
                self.ack_waiters.pop((pid, mid), None)
                results[pid] = "failed"
                self.emit({"event": "text_state", "peer_id": pid, "mid": mid,
                           "state": "failed", "reason": str(e)})
                continue
            try:
                await asyncio.wait_for(fut, 12.0)
                results[pid] = "ok"
                self.emit({"event": "text_state", "peer_id": pid, "mid": mid,
                           "state": "ok"})
            except asyncio.TimeoutError:
                results[pid] = "timeout"
                self.emit({"event": "text_state", "peer_id": pid, "mid": mid,
                           "state": "timeout"})
        return results

    def send_files(self, target_ids: list, paths: list):
        self._post(self._send_files_task(list(target_ids), list(paths)))

    def send_files_sync(self, target_ids: list, paths: list,
                        timeout: float = 1800.0):
        """★ v1.18.20：同步发送文件并等到每个目标都有结论。

        与 send_files 的区别：send_files 起协程立即返回（fire-and-forget），
        待发队列补发必须知道**真实结论**才能决定条目去留 ——
        旧的 flush 文件分支"调完 send_files 就当成功"，一旦本次尝试失败
        （TCP 未就绪等），条目已被移除、无重试 → 内容丢失；且与用户手动
        重发并存时会出现两个气泡。

        返回 {peer_id: "ok"|"fail"} —— 任一文件送达即记 ok。
        必须在工作线程调用（内部阻塞等待，同 send_text_sync 模式）。
        """
        fut = asyncio.run_coroutine_threadsafe(
            self._send_files_sync_task(list(target_ids), list(paths)),
            self.loop)
        return fut.result(timeout=timeout)

    async def _send_files_sync_task(self, target_ids, paths):
        results = {}
        for path in paths:
            try:
                if not os.path.isfile(path):
                    continue
                size = os.path.getsize(path)
                name = os.path.basename(path)
            except Exception:
                continue
            tid = util.gen_uid()
            mime = util.guess_mime(name)
            self._send_info[tid] = {"name": name, "size": size, "mime": mime,
                                    "targets": list(target_ids),
                                    "src_path": path}
            st = self.out_states.setdefault(tid, {})
            for pid in target_ids:
                st[pid] = "sending"
                self.emit({"event": "transfer", "kind": "send", "tid": tid,
                           "peer_id": pid, "file": name, "size": size,
                           "mime": mime, "state": "started",
                           "transferred": 0, "targets": list(target_ids),
                           "src_path": path})
            await asyncio.gather(
                *[self._send_file_to(pid, tid, path, name, size, mime)
                  for pid in target_ids],
                return_exceptions=True)
            fin = self.out_states.pop(tid, None)
            self._send_info.pop(tid, None)
            for pid in target_ids:
                if fin and fin.get(pid) == "ok":
                    results[pid] = "ok"
                else:
                    results.setdefault(pid, "fail")
        return results

    async def _send_files_task(self, target_ids, paths):
        for path in paths:
            try:
                if not os.path.isfile(path):
                    continue
                size = os.path.getsize(path)
                name = os.path.basename(path)
            except Exception:
                continue
            tid = util.gen_uid()
            mime = util.guess_mime(name)
            self._send_info[tid] = {"name": name, "size": size, "mime": mime,
                                    "targets": list(target_ids), "src_path": path}
            st = self.out_states.setdefault(tid, {})
            for pid in target_ids:
                st[pid] = "sending"
                self.emit({"event": "transfer", "kind": "send", "tid": tid,
                           "peer_id": pid, "file": name, "size": size,
                           "mime": mime, "state": "started", "transferred": 0,
                           "targets": list(target_ids), "src_path": path})
            await asyncio.gather(
                *[self._send_file_to(pid, tid, path, name, size, mime)
                  for pid in target_ids],
                return_exceptions=True)

    async def _send_file_to(self, peer_id, tid, path, name, size, mime):
        """发送单个文件到单个目标。

        ★ v1.18.18：外层包了自动重试。
        失败分两类处理：
        - **可重试**（设备不在线/连接中断/等待超时）：指数退避后重试，
          **沿用同一个 tid**，接收端凭 tid 找回 .part + 位图，只补缺失块
          —— 这就是断点续传真正生效的地方。
        - **不可重试**（对方拒绝/取消/源文件读不了）：立即失败不重试，
          避免对着一个已拒绝的连接反复敲。
        """
        attempt = 0
        while True:
            result, reason, retryable = await self._send_file_once(
                peer_id, tid, path, name, size, mime, attempt)
            if result == "ok":
                return
            if not retryable or attempt >= SEND_MAX_RETRY:
                st = self.out_states.get(tid, {})
                st[peer_id] = "fail"
                self._emit_send_state(tid, peer_id, "failed", reason=reason,
                                      attempt=attempt)
                return
            attempt += 1
            delay = R.next_backoff(attempt, base=SEND_RETRY_BASE)
            self.emit({"event": "log", "level": "warn",
                       "msg": f"发送 {name} 给 {self.display_name(peer_id)} 失败"
                              f"（{reason}），{delay:.1f}s 后第 {attempt} 次重试"
                              f"（断点续传）"})
            self._emit_send_state(tid, peer_id, "retrying", reason=reason,
                                  attempt=attempt)
            await asyncio.sleep(delay)

    async def _send_file_once(self, peer_id, tid, path, name, size, mime, attempt):
        """单次发送尝试。返回 (result, reason, retryable)。

        result ∈ {"ok", "fail"}；retryable 表示是否值得重试。
        """
        conn = await self._wait_conn(peer_id, 15.0)
        if not conn:
            return ("fail", "设备不在线", True)
        loop = asyncio.get_running_loop()
        ready_fut = loop.create_future()
        ok_fut = loop.create_future()
        self.ready_waiters[(peer_id, tid)] = ready_fut
        self.out_waiters[(peer_id, tid)] = ok_fut
        last_evt = 0.0
        win_bytes = 0
        win_t = time.time()
        md5 = hashlib.md5()
        resumed_from = 0
        try:
            await conn.send_json({"type": P.T_FILE_START, "tid": tid, "name": name,
                                  "size": size, "mime": mime,
                                  "idx": 1,          # ★ 声明支持带块号分块
                                  "attempt": attempt,
                                  "scheme": self.cfg["bubble_scheme"]})
            # 等待对方就绪（自动接收时立即回；手动确认时等用户）
            try:
                res = await asyncio.wait_for(ready_fut, RECV_CONFIRM_TTL + 10.0)
            except asyncio.TimeoutError:
                return ("fail", "等待对方确认超时", True)
            if res[0] != "ready":
                # REFUSE / CANCEL：对方明确不要了，重试无意义
                return ("fail", "对方拒绝接收" if res[0] == "refuse" else "对方已取消",
                        False)
            # ★ 断点信息：对方已收的块（仅 chunk 模式下携带）
            idx_mode = bool(isinstance(res[1], dict) and res[1].get("idx"))
            nchunks = R.total_chunks(size)
            skip = set()
            if idx_mode:
                try:
                    cm = R.ChunkMap.from_compact(res[1].get("have") or [], nchunks)
                    # ★ missing() 是"还缺哪些块"= **需要发送**的块；
                    #   跳过集合必须是它的补集（已收到的块）。
                    #   v1.18.18 首版这里写反了（skip = missing()），
                    #   导致首次传输（have=[] → 全部块都是 missing）
                    #   一个块都不发，接收端立刻报"缺少数据块"。
                    todo = set(cm.missing())
                    skip = set(range(nchunks)) - todo
                    resumed_from = nchunks - len(todo)
                    if resumed_from:
                        self.emit({"event": "log", "level": "info",
                                   "msg": f"断点续传 {name} → "
                                          f"{self.display_name(peer_id)}："
                                          f"跳过已收 {resumed_from}/{nchunks} 块"})
                except Exception:
                    skip = set()
            with open(path, "rb") as f:
                idx = 0
                # 进度基准：续传时对方已有一部分，起始点就不是 0，
                # 否则进度条会从中间往回跳（用户看到"倒退"）。
                base_done = sum(R.chunk_len(i, size) for i in skip) if idx_mode else 0
                done = base_done
                while True:
                    chunk = f.read(P.CHUNK_SIZE)
                    if not chunk:
                        break
                    if idx_mode:
                        if idx not in skip:
                            await conn.send_frame(P.encode_chunk(tid, idx, chunk))
                    else:
                        await conn.send_frame(P.encode_bin(tid, chunk))
                    # ★ MD5 必须覆盖**全部**块（无论本轮发没发）。
                    #   接收端 FILE_END 时按整文件校验，摘要必须来自全量数据；
                    #   续传时"跳过的块"也要喂进去，否则摘要只覆盖本轮实际发出的部分。
                    #   v1.18.18 首版把 md5.update 放在 else 分支里，
                    #   导致正常传输（skip 为空）摘要恒为空 -> 接收端 MD5 校验失败。
                    md5.update(chunk)
                    win_bytes += len(chunk)
                    done += len(chunk)
                    idx += 1
                    now = time.time()
                    if now - last_evt > 0.15:
                        last_evt = now
                        dt = now - win_t
                        speed = win_bytes / dt if dt > 0.05 else 0
                        if dt > 1.0:
                            win_bytes = 0
                            win_t = now
                        self.emit({"event": "transfer", "kind": "send", "tid": tid,
                                   "peer_id": peer_id, "file": name, "size": size,
                                   "mime": mime, "state": "progress",
                                   "transferred": min(done, size), "speed": speed,
                                   "attempt": attempt})
            await conn.send_json({"type": P.T_FILE_END, "tid": tid,
                                  "md5": md5.hexdigest()})
            # ★ v1.18.18 审计修复：必须检查 ok_fut 的结果值。
            #   原来只等完成不看内容 —— 接收端 FILE_FAIL（MD5 失败/缺块/
            #   落盘失败）与 REFUSE/CANCEL 全被当成"已发送"，不重试，
            #   用户看到假成功。对齐 Android 端 FlashNode.sendFileOnce。
            try:
                st, extra = await asyncio.wait_for(ok_fut, SEND_WAIT_OK)
            except asyncio.TimeoutError:
                return ("fail", "等待对方确认超时", True)
            if st == "ok":
                return ("ok", "", False)
            if st == "refuse":
                return ("fail", extra or "对方拒绝接收", False)   # 不可重试
            if st == "cancel":
                return ("fail", extra or "对方已取消", False)     # 不可重试
            return ("fail", extra or "对方接收失败", True)        # 可重试
        except (ConnectionError, OSError, asyncio.IncompleteReadError) as e:
            return ("fail", f"连接中断: {e}", True)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            return ("fail", str(e), True)
        finally:
            self.ready_waiters.pop((peer_id, tid), None)
            self.out_waiters.pop((peer_id, tid), None)

    def _emit_send_state(self, tid, peer_id, state, reason=None, path=None, attempt=0):
        info = self._send_info.get(tid) or {}
        self.emit({"event": "transfer", "kind": "send", "tid": tid,
                   "peer_id": peer_id, "file": info.get("name", ""),
                   "size": info.get("size", 0), "mime": info.get("mime", ""),
                   "state": state, "reason": reason, "path": path,
                   "transferred": info.get("size", 0) if state == "ok" else 0,
                   "targets": info.get("targets", [peer_id]),
                   "src_path": info.get("src_path"), "attempt": attempt})

    async def _wait_conn(self, peer_id, timeout):
        t0 = time.time()
        peer = self.peers.get(peer_id)
        if peer:
            self._ensure_connected(peer)
        while time.time() - t0 < timeout:
            c = self.conns.get(peer_id)
            if c and c.alive and not c.replaced and c.hello_got:
                return c
            await asyncio.sleep(0.2)
        return None

    def cancel_send(self, tid):
        self._post(self._cancel_send_task(tid))

    async def _cancel_send_task(self, tid):
        st = self.out_states.get(tid)
        if not st:
            return
        for pid in list(st.keys()):
            if st[pid] in ("ok", "fail", "refuse", "cancel"):
                continue
            conn = self.conns.get(pid)
            if conn and conn.alive:
                try:
                    await conn.send_json({"type": P.T_CANCEL, "tid": tid})
                except Exception:
                    pass
            for m in (self.ready_waiters, self.out_waiters):
                fut = m.pop((pid, tid), None)
                if fut and not fut.done():
                    fut.set_result(("cancel", None))
            st[pid] = "cancel"
            self._emit_send_state(tid, pid, "cancelled", reason="已取消")

    def accept_inbound(self, tid):
        self._post(self._accept_inbound_task(tid))

    async def _accept_inbound_task(self, tid):
        for key, ib in list(self.inbounds.items()):
            if ib.tid == tid and not ib.started and not ib.done:
                if self._begin_inbound(ib):
                    conn = self.conns.get(ib.peer_id)
                    if conn and conn.alive:
                        await self._send_recv_ready(conn, ib)
                return

    def reject_inbound(self, tid):
        self._post(self._reject_inbound_task(tid))

    async def _reject_inbound_task(self, tid):
        for key, ib in list(self.inbounds.items()):
            if ib.tid == tid and not ib.done and not ib.started:
                conn = self.conns.get(ib.peer_id)
                if conn and conn.alive:
                    try:
                        await conn.send_json({"type": P.T_REFUSE, "tid": tid,
                                              "reason": "对方拒绝接收"})
                    except Exception:
                        pass
                self._cleanup_inbound(ib, drop_state=True)
                self.emit(self._recv_evt(ib, "refused", reason="已拒绝"))
                return

    def cancel_inbound(self, tid):
        self._post(self._cancel_inbound_task(tid))

    async def _cancel_inbound_task(self, tid):
        for key, ib in list(self.inbounds.items()):
            if ib.tid == tid:
                conn = self.conns.get(ib.peer_id)
                if conn and conn.alive:
                    try:
                        await conn.send_json({"type": P.T_CANCEL, "tid": tid})
                    except Exception:
                        pass
                ib.canceled = True
                self._cleanup_inbound(ib, drop_state=True)
                self.emit(self._recv_evt(ib, "cancelled", reason="已取消接收"))
                return

    # ============================ 连接调度 ============================

    def _ensure_connected(self, peer: Peer, force=False):
        if self._stopping or not peer or peer.id == self.device_id:
            return
        now = time.time()
        c = self.conns.get(peer.id)
        if c and c.alive and not c.replaced:
            return
        if peer.connecting:
            return
        if not force and now < peer.next_retry:
            return
        if not force and (now - peer.last_seen) > 120 and not peer.manual:
            return
        peer.connecting = True
        try:
            asyncio.get_running_loop().create_task(self._connect_peer(peer))
        except RuntimeError:
            peer.connecting = False

    async def _connect_peer(self, peer: Peer):
        try:
            for ip in list(peer.ips):
                c = self.conns.get(peer.id)
                if c and c.alive and not c.replaced:
                    return
                try:
                    reader, writer = await self._open_conn(ip, peer.tcp_port, 3.0)
                except Exception:
                    continue
                conn = Conn(reader, writer, incoming=False)
                try:
                    await conn.send_json(self._hello_msg())
                except Exception:
                    await conn.close()
                    continue
                asyncio.get_running_loop().create_task(self._session(conn))
                return
            peer.retry_backoff = min(peer.retry_backoff * 2, 30.0)
            peer.next_retry = time.time() + peer.retry_backoff
        finally:
            peer.connecting = False

    # ============================ 子网扫描 ============================

    def _subnet_of(self, ip: str) -> str:
        if not ip_is_private(ip):
            return ""
        parts = ip.split(".")
        if len(parts) == 4:
            return ".".join(parts[:3]) + ".0"
        return ""

    async def scan(self, full=True):
        """扫描候选 IP 的 TCP 端口。full=True 时包含常见子网清单（深度扫描）"""
        if self._scanning:
            return
        self._scanning = True
        try:
            ports = {self.port}
            if self.port != P.DEFAULT_PORT:
                ports.add(P.DEFAULT_PORT)
            subnets = set()
            hosts = set()
            for iface in netinfo.get_local_ifaces():
                if iface.subnet:
                    subnets.add(iface.subnet)
            for gw in netinfo.get_gateways():
                hosts.add(gw)
                parts = gw.split(".")
                if len(parts) == 4:
                    subnets.add(".".join(parts[:3]) + ".0")
            for s in (self.cfg["known_subnets"] or []):
                subnets.add(s)
            hosts.add("127.0.0.1")
            if full:
                subnets.update(COMMON_SUBNETS)
            busy = set()
            for c in self.conns.values():
                if c.alive:
                    for port in ports:
                        busy.add((c.remote_ip, port))
            busy.add(("127.0.0.1", self.port))  # 自己的监听端口（HELLO 自检会关闭）

            sem = asyncio.Semaphore(256)
            found = 0
            loop = asyncio.get_running_loop()

            async def probe(ip, port):
                nonlocal found
                if (ip, port) in busy:
                    return
                try:
                    reader, writer = await self._open_conn(ip, port, 0.45)
                except Exception:
                    return
                conn = Conn(reader, writer, incoming=False)
                try:
                    await conn.send_json(self._hello_msg())
                except Exception:
                    await conn.close()
                    return
                found += 1
                loop.create_task(self._session(conn))

            coros = []
            seen = set()
            for sn in subnets:
                parts = sn.split(".")
                if len(parts) != 4:
                    continue
                prefix = ".".join(parts[:3])
                for i in range(1, 255):
                    ip = f"{prefix}.{i}"
                    for port in ports:
                        if (ip, port) not in seen:
                            seen.add((ip, port))
                            coros.append(self._lim(sem, probe(ip, port)))
            for h in hosts:
                for port in ports:
                    if (h, port) not in seen:
                        seen.add((h, port))
                        coros.append(self._lim(sem, probe(h, port)))
            if coros:
                await asyncio.gather(*coros, return_exceptions=True)
            self.emit({"event": "scan_done", "full": full, "found": found})
            self._notify_peers()
        except Exception as e:
            self.emit({"event": "log", "level": "warn", "msg": f"扫描异常: {e}"})
        finally:
            self._scanning = False

    @staticmethod
    async def _lim(sem, coro):
        async with sem:
            return await coro

    def rescan(self, full=True):
        self._post(self.scan(full=full))

    def connect_manual(self, host: str, port: int):
        """UI 线程调用：手动连接。返回 concurrent future"""
        if self.loop and self.loop.is_running():
            return asyncio.run_coroutine_threadsafe(
                self._connect_manual_task(host, port), self.loop)
        return None

    async def _connect_manual_task(self, host, port):
        try:
            reader, writer = await self._open_conn(host, port, 4.0)
        except Exception as e:
            return (False, f"连接失败: {e}")
        conn = Conn(reader, writer, incoming=False)
        try:
            await conn.send_json(self._hello_msg())
        except Exception:
            await conn.close()
            return (False, "握手失败")
        hello = await self._recv_hello(conn)
        if not hello:
            await conn.close()
            return (False, "对端无响应")
        if hello.get("id") == self.device_id:
            await conn.close()
            return (False, "不能添加自己")
        ok = await self._register_conn(conn, hello)
        if not ok:
            return (False, "已存在更优连接")
        peer = self.peers.get(hello["id"])
        if peer:
            peer.manual = True
            if peer.ips and host not in peer.ips:
                peer.ips.insert(0, host)
        self._notify_peers()
        asyncio.get_running_loop().create_task(self._reader_loop(conn))
        return (True, peer.name if peer else hello["id"][:8])

    # ============================ 查询 ============================

    def peers_snapshot(self):
        return [p.snapshot(self.conns) for p in self.peers.values()]

    def online_peer_ids(self):
        return [p.id for p in self.peers.values() if p.online(self.conns)]

    def set_name(self, name: str):
        self.name = name

    def update_config(self):
        """端口等配置变更后由 UI 调用（需重启节点）"""
        pass
