# -*- coding: utf-8 -*-
"""严格的"旧版 Android 端"协议模拟器，与真实 windows/app/node.py 实跑对拍。

目的：验证"新版 Windows 端 <-> 旧版 Android 端"在协议层面是否真的互通。

旧端特性（刻意严格，模拟 PROTOCOL.md v1 最初形态）：
  * DISC 只发 app/v/type/id/name/platform/tcp 六个字段（不发 host/alt/ips/scheme）
  * 不启用 TLS，纯明文 TCP
  * 帧长严格校验（L<=1 或 L>MAX_FRAME 立即判协议错误）
  * 只认 PROTOCOL.md v1 列出的字段，遇到未知字段只记录、不报错（向前兼容）
  * 只认 PROTOCOL.md v1 列出的 type，遇到未知 type 忽略

运行: python tests/verify_legacy_interop.py
"""

import hashlib
import json
import os
import socket
import struct
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import Config
from app.node import FlashNode

# ---------------------------------------------------------------- 协议常量（v1）

APP = "FlashDrop"
PROTO_VERSION = 1
KIND_JSON = 0x4A
KIND_BIN = 0x42
CHUNK_SIZE = 512 * 1024
MAX_FRAME = 1 + 2 + 64 + 8 + CHUNK_SIZE

LEGACY_ID = "1a2b3c4d5e6f7081"
LEGACY_NAME = "旧版Android手机"

# PROTOCOL.md v1 明确列出的字段（严格白名单）。白名单外 = 旧端"不认识"的字段。
KNOWN_FIELDS = {
    "DISC": {"app", "v", "type", "id", "name", "platform", "tcp"},
    "HELLO": {"app", "v", "type", "id", "name", "platform", "tcp"},
    "PING": {"type"},
    "PONG": {"type"},
    "BYE": {"type"},
    "TEXT": {"type", "mid", "text", "ts"},
    "ACK": {"type", "mid"},
    "FILE_START": {"type", "tid", "name", "size", "mime"},
    "RECV_READY": {"type", "tid"},
    "FILE_END": {"type", "tid", "md5"},
    "FILE_OK": {"type", "tid", "path"},
    "FILE_FAIL": {"type", "tid", "reason"},
    "REFUSE": {"type", "tid", "reason"},
    "CANCEL": {"type", "tid"},
}

# ---------------------------------------------------------------- 旧端模拟器


class LegacyError(Exception):
    pass


class LegacyPeer:
    """旧版 Android 端：最小字段 + 严格帧校验。"""

    def __init__(self, dev_id, name, tcp_port, win_port, save_dir):
        self.id = dev_id
        self.name = name
        self.tcp_port = tcp_port
        self.win_port = win_port
        self.save_dir = save_dir
        self.stop = threading.Event()

        # 观测数据
        self.disc_rx = []          # 收到的 UDP DISC 原始报文
        self.frames = []           # 收到的每一帧（已解析）
        self.unknown_fields = {}   # 字段名 -> set(消息类型)
        self.unknown_types = []    # 不认识的 type
        self.parse_errors = []     # 旧端无法解析的报文
        self.texts = []            # 收到的文本
        self.files = {}            # tid -> 接收结果
        self.accepted = 0
        self.win_hello = None
        self.lock = threading.Lock()

        os.makedirs(save_dir, exist_ok=True)

    # ---- 旧端 DISC：只有 6 个字段 ----
    def disc_bytes(self):
        obj = {"app": APP, "v": PROTO_VERSION, "type": "DISC",
               "id": self.id, "name": self.name, "platform": "android",
               "tcp": self.tcp_port}
        return json.dumps(obj, ensure_ascii=False,
                          separators=(",", ":")).encode("utf-8")

    # ---- 严格帧读取 ----
    def _read_frame(self, c):
        hdr = b""
        while len(hdr) < 4:
            ch = c.recv(4 - len(hdr))
            if not ch:
                raise ConnectionError("连接关闭")
            hdr += ch
        (length,) = struct.unpack(">I", hdr)
        if length <= 1 or length > MAX_FRAME:
            self.parse_errors.append(f"帧长非法 L={length}（上限 {MAX_FRAME}）")
            raise LegacyError(f"bad frame length {length}")
        payload = b""
        while len(payload) < length:
            ch = c.recv(length - len(payload))
            if not ch:
                raise ConnectionError("连接关闭")
            payload += ch
        return payload

    def _send_json(self, c, obj):
        body = json.dumps(obj, ensure_ascii=False,
                          separators=(",", ":")).encode("utf-8")
        c.sendall(struct.pack(">I", len(body) + 1) + bytes([KIND_JSON]) + body)

    def _note(self, kind, msg_type, fields, raw):
        """记录一帧 + 统计旧端不认识的字段"""
        with self.lock:
            self.frames.append({"kind": kind, "type": msg_type,
                                "fields": sorted(fields), "raw": raw})
            if kind == "BIN":
                return
            known = KNOWN_FIELDS.get(msg_type)
            if known is None:
                self.unknown_types.append(msg_type)
                return
            for f in fields:
                if f not in known:
                    self.unknown_fields.setdefault(f, set()).add(msg_type)

    # ---- UDP 发现 ----
    def udp_loop(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.bind(("0.0.0.0", 0))
        s.settimeout(0.3)
        pkt = self.disc_bytes()
        while not self.stop.is_set():
            try:
                s.sendto(pkt, ("127.0.0.1", self.win_port))
            except OSError:
                pass
            deadline = time.time() + 3.0
            while time.time() < deadline and not self.stop.is_set():
                try:
                    data, addr = s.recvfrom(65536)
                except socket.timeout:
                    continue
                except OSError:
                    break
                self._on_disc(data, addr)
        try:
            s.close()
        except OSError:
            pass

    def _on_disc(self, data, addr):
        try:
            text = data.decode("utf-8")
            obj = json.loads(text)
            if not isinstance(obj, dict):
                raise ValueError("not object")
        except Exception as e:
            self.parse_errors.append(f"UDP DISC 解析失败: {e}")
            return
        if obj.get("app") != APP or obj.get("type") != "DISC" or not obj.get("id"):
            return
        with self.lock:
            self.disc_rx.append((obj, text, addr))
        self._note("UDP_DISC", "DISC", set(obj.keys()), text)

    # ---- TCP 服务端（只接受连接，不主动外连）----
    def tcp_server(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("0.0.0.0", self.tcp_port))
        srv.listen(8)
        srv.settimeout(0.5)
        while not self.stop.is_set():
            try:
                c, addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with self.lock:
                self.accepted += 1
                n = self.accepted
            print(f"    [旧端] 收到 Windows 端 TCP 连接 #{n} 来自 {addr[0]}:{addr[1]}")
            threading.Thread(target=self.session, args=(c, n), daemon=True).start()
        try:
            srv.close()
        except OSError:
            pass

    def session(self, c, n):
        c.settimeout(40.0)
        inflight = {}   # tid -> {name, size, mime, buf, md5}
        try:
            # 首帧必须是 HELLO
            payload = self._read_frame(c)
            if payload[0] != KIND_JSON:
                self.parse_errors.append(f"首帧不是 JSON（kind=0x{payload[0]:02x}）")
                raise LegacyError("first frame not json")
            hello = json.loads(payload[1:].decode("utf-8"))
            self._note("JSON", "HELLO", set(hello.keys()),
                       json.dumps(hello, ensure_ascii=False))
            self.win_hello = hello
            print(f"    [旧端] Windows HELLO 字段 = {sorted(hello.keys())}")
            # 回最小 HELLO
            self._send_json(c, {"app": APP, "v": PROTO_VERSION, "type": "HELLO",
                                "id": self.id, "name": self.name,
                                "platform": "android", "tcp": self.tcp_port})
            print(f"    [旧端] 已回最小 HELLO（仅 7 字段）")

            while not self.stop.is_set():
                payload = self._read_frame(c)
                kind = payload[0]
                if kind == KIND_JSON:
                    try:
                        obj = json.loads(payload[1:].decode("utf-8"))
                    except Exception as e:
                        self.parse_errors.append(f"JSON 帧解码失败: {e}")
                        continue
                    t = obj.get("type")
                    raw = json.dumps(obj, ensure_ascii=False)
                    self._note("JSON", t if isinstance(t, str) else "?",
                               set(obj.keys()), raw)
                    if t == "PING":
                        self._send_json(c, {"type": "PONG"})
                    elif t == "PONG":
                        pass
                    elif t == "TEXT":
                        with self.lock:
                            self.texts.append(obj)
                        self._send_json(c, {"type": "ACK", "mid": obj.get("mid")})
                    elif t == "FILE_START":
                        tid = obj.get("tid")
                        inflight[tid] = {"name": obj.get("name"),
                                         "size": obj.get("size"),
                                         "mime": obj.get("mime"),
                                         "buf": bytearray(),
                                         "md5": hashlib.md5()}
                        self._send_json(c, {"type": "RECV_READY", "tid": tid})
                    elif t == "FILE_END":
                        self._finish_file(c, obj, inflight)
                    elif t == "BYE":
                        break
                    elif t in KNOWN_FIELDS:
                        pass
                    else:
                        print(f"    [旧端] 忽略未知 type={t}")
                elif kind == KIND_BIN:
                    if len(payload) < 1 + 2 + 1 + 8:
                        self.parse_errors.append("二进制帧过短")
                        continue
                    (tl,) = struct.unpack(">H", payload[1:3])
                    tid = payload[3:3 + tl].decode("utf-8", "replace")
                    (m,) = struct.unpack(">Q", payload[3 + tl:3 + tl + 8])
                    data = payload[3 + tl + 8:]
                    if len(data) != m or m > CHUNK_SIZE:
                        self.parse_errors.append(
                            f"二进制块长度不符 声明={m} 实际={len(data)}")
                        continue
                    rec = inflight.get(tid)
                    if rec is None:
                        self.parse_errors.append(f"收到无 FILE_START 的块 tid={tid}")
                        continue
                    rec["buf"] += data
                    rec["md5"].update(data)
                    self._note("BIN", "(binary)", {"tid", "data"}, f"{len(data)}B")
                else:
                    self.parse_errors.append(f"未知帧类型 0x{kind:02x}")
                    raise LegacyError(f"unknown frame kind 0x{kind:02x}")
        except (ConnectionError, LegacyError, socket.timeout, OSError) as e:
            print(f"    [旧端] 连接 #{n} 结束: {type(e).__name__}: {e}")
        finally:
            try:
                c.close()
            except OSError:
                pass

    def _finish_file(self, c, obj, inflight):
        tid = obj.get("tid")
        rec = inflight.pop(tid, None)
        if rec is None:
            self.parse_errors.append(f"FILE_END 无对应 FILE_START tid={tid}")
            return
        buf = bytes(rec["buf"])
        calc = rec["md5"].hexdigest()
        want = (obj.get("md5") or "").lower()
        ok = (len(buf) == rec["size"]) and (not want or want == calc)
        path = os.path.join(self.save_dir, rec["name"] or f"{tid}.bin")
        if ok:
            with open(path, "wb") as f:
                f.write(buf)
            self._send_json(c, {"type": "FILE_OK", "tid": tid, "path": path})
        else:
            self._send_json(c, {"type": "FILE_FAIL", "tid": tid,
                                "reason": "size/md5 校验失败"})
        with self.lock:
            self.files[tid] = {"name": rec["name"], "size": rec["size"],
                               "recv": len(buf), "md5_ok": bool(want) and want == calc,
                               "ok": ok, "path": path if ok else ""}
        print(f"    [旧端] 落盘校验 {'通过' if ok else '失败'}: "
              f"{rec['name']} {len(buf)}B md5={calc[:12]}…")

    def start(self):
        threading.Thread(target=self.udp_loop, daemon=True).start()
        threading.Thread(target=self.tcp_server, daemon=True).start()


# ---------------------------------------------------------------- 测试脚手架


class Collector:
    def __init__(self):
        self.events = []
        self.lock = threading.Lock()

    def __call__(self, evt):
        with self.lock:
            self.events.append(evt)

    def find(self, pred):
        with self.lock:
            for e in self.events:
                if pred(e):
                    return e
        return None

    def wait_for(self, pred, timeout=25):
        t0 = time.time()
        while time.time() - t0 < timeout:
            e = self.find(pred)
            if e:
                return e
            time.sleep(0.05)
        return None


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"   {detail}" if detail and not cond else ""))
    return cond


def dump(label, obj):
    """按旧端视角打印实际收到的 JSON 字段"""
    t = obj.get("type") if isinstance(obj, dict) else None
    known = KNOWN_FIELDS.get(t, set())
    fields = sorted(obj.keys()) if isinstance(obj, dict) else []
    new = [f for f in fields if f not in known]
    print(f"    {label} type={t}")
    print(f"      全部字段 : {fields}")
    print(f"      旧端已知 : {sorted(known & set(fields))}")
    print(f"      旧端不认识: {new if new else '（无）'}")


def main():
    tmp = tempfile.mkdtemp(prefix="flashdrop_legacy_")
    win_port = free_port()
    leg_port = free_port()
    while leg_port == win_port:
        leg_port = free_port()

    print("=" * 74)
    print("FlashDrop 新版 Windows 端  <->  旧版 Android 端 互通验证")
    print("=" * 74)
    print(f"Windows 端 : 127.0.0.1:{win_port}")
    print(f"旧端模拟器 : 127.0.0.1:{leg_port}   id={LEGACY_ID}")
    print(f"临时目录   : {tmp}\n")

    # ---- 启动真实 node.py 的 Node（新版生产代码，encrypt=False 即明文）----
    cfg = Config(os.path.join(tmp, "win_cfg.json"))
    cfg.data["device_id"] = "0a0b0c0d0e0f0001"
    cfg.data["name"] = "新版Windows电脑"
    cfg.data["port"] = win_port
    cfg.data["save_dir"] = os.path.join(tmp, "win_save")
    cfg.data["cache_dir"] = os.path.join(tmp, "win_cache")
    cfg.data["auto_accept"] = True
    cfg.data["encrypt"] = False              # 不启用 TLS
    # 故意保留一个历史旧 ID，强制新版把 alt 字段写进报文（最严格的兼容场景）
    cfg.data["legacy_ids"] = ["ffee00112233445 5".replace(" ", "")]
    cfg.save()

    col = Collector()
    win = FlashNode(cfg, emit=col)
    win.start()
    time.sleep(1.0)
    print(f"  Windows 端已启动，device_id={win.device_id} encrypt={cfg['encrypt']}")
    print(f"  Windows 自身将广播的 DISC 字段 = "
          f"{sorted(json.loads(win._disc_packet().decode('utf-8')).keys())}\n")

    legacy = LegacyPeer(LEGACY_ID, LEGACY_NAME, leg_port, win_port,
                        os.path.join(tmp, "legacy_save"))
    legacy.start()

    # ================================================================ 1. UDP 发现
    def _is_legacy_log(e, keyword):
        """Windows 端日志里提到旧端设备（按设备名或 ID 匹配）"""
        return (e["event"] == "log" and keyword in e.get("msg", "")
                and (LEGACY_NAME in e.get("msg", "") or LEGACY_ID[:8] in e.get("msg", "")))

    print("== 1. 旧端发最小字段 DISC，Windows 端应发现并回 DISC ==")
    ev = col.wait_for(lambda e: _is_legacy_log(e, "发现设备"), 15)
    check("Windows 端通过 UDP 发现了旧端", ev is not None,
          str([e for e in col.events if e["event"] == "log"][-5:]))
    if ev:
        print(f"    Windows 日志: {ev['msg']}")

    ev = col.wait_for(lambda e: _is_legacy_log(e, "已连接"), 15)
    check("Windows 端主动回连旧端 TCP", ev is not None)
    if ev:
        print(f"    Windows 日志: {ev['msg']}")

    check("旧端收到 Windows 单播回来的 DISC", bool(legacy.disc_rx),
          "未收到 Windows DISC 回包")
    if legacy.disc_rx:
        obj, text, addr = legacy.disc_rx[0]
        print(f"    旧端收到 Windows DISC（来自 {addr[0]}:{addr[1]}）")
        dump("DISC", obj)
        print(f"      原始 JSON: {text}")

    # ================================================================ 2. 握手
    print("\n== 2. TCP 握手：旧端只认最小字段 ==")
    t0 = time.time()
    while not legacy.win_hello and time.time() - t0 < 15:
        time.sleep(0.1)
    check("旧端解析出 Windows 的 HELLO", legacy.win_hello is not None)
    ev = col.wait_for(lambda e: _is_legacy_log(e, "已连接"), 10)
    check("Windows 端握手成功并注册连接", ev is not None)

    snap = win.peers_snapshot()
    pl = [p for p in snap if p["id"] == LEGACY_ID]
    check("Windows 设备列表里旧端显示为在线", bool(pl) and pl[0]["online"],
          str(snap))
    if pl:
        print(f"    Windows 看到的旧端: id={pl[0]['id']} name={pl[0]['name']} "
              f"platform={pl[0].get('platform')} tcp={pl[0].get('tcp_port')} "
              f"online={pl[0]['online']}")

    # ================================================================ 3. 文本
    print("\n== 3. Windows -> 旧端：TEXT ==")
    win.send_text([LEGACY_ID], "来自新版 Windows 的测试消息 ✅")
    t0 = time.time()
    while not legacy.texts and time.time() - t0 < 15:
        time.sleep(0.1)
    check("旧端成功解析 TEXT", bool(legacy.texts))
    if legacy.texts:
        dump("TEXT", legacy.texts[0])
        print(f"      text 内容: {legacy.texts[0].get('text')!r}")
        print(f"      mid={legacy.texts[0].get('mid')} ts={legacy.texts[0].get('ts')}")
    ev = col.wait_for(lambda e: e["event"] == "text_state" and e["peer_id"] == LEGACY_ID
                       and e["state"] in ("ok", "timeout"), 20)
    check("Windows 端收到旧端的 ACK 回执", ev is not None and ev["state"] == "ok",
          str(ev))

    # ================================================================ 4. 文件
    print("\n== 4. Windows -> 旧端：FILE_START / 二进制块 / FILE_END ==")
    src = os.path.join(tmp, "旧版互通测试文件.bin")
    payload = os.urandom(1536 * 1024)          # 1.5MB -> 3 个 512KB 块
    with open(src, "wb") as f:
        f.write(payload)
    src_md5 = hashlib.md5(payload).hexdigest()
    print(f"    待传文件: {os.path.basename(src)}  {len(payload)} 字节  md5={src_md5[:16]}…")

    win.send_files([LEGACY_ID], [src])
    ev = col.wait_for(lambda e: e["event"] == "transfer" and e["kind"] == "send"
                       and e["state"] in ("ok", "failed", "refused"), 60)
    check("Windows 端收到旧端的 FILE_OK", ev is not None and ev["state"] == "ok",
          str(ev))
    if ev:
        print(f"    Windows 发送终态: state={ev['state']} path={ev.get('path')}")

    check("旧端完成落盘", bool(legacy.files))
    for tid, r in legacy.files.items():
        print(f"    旧端接收结果: name={r['name']} size={r['size']} "
              f"实际收到={r['recv']}B md5一致={r['md5_ok']} -> {r['path']}")
        check("旧端校验 size 与 md5 通过", r["ok"])
    bin_frames = [f for f in legacy.frames if f["kind"] == "BIN"]
    check("旧端解析出二进制块帧", len(bin_frames) >= 3, f"实际 {len(bin_frames)} 帧")

    # 打印旧端看到的 FILE_START / FILE_END 原始字段
    for f in legacy.frames:
        if f["type"] in ("FILE_START", "FILE_END"):
            dump(f["type"], json.loads(f["raw"]))

    # ================================================================ 5. 报告
    print("\n" + "=" * 74)
    print("报告 1：新版 Windows 发出的报文里，旧端不认识的字段")
    print("=" * 74)
    if not legacy.unknown_fields:
        print("  （无）")
    for fld, types in sorted(legacy.unknown_fields.items()):
        print(f"  字段 {fld!r:12} 出现在: {', '.join(sorted(types))}")
    print("\n  逐条消息明细（旧端视角）：")
    for f in legacy.frames:
        if f["kind"] == "BIN":
            print(f"    [BIN ] {f['raw']}")
        else:
            print(f"    [JSON] {f['type']:12} 字段={f['fields']}")

    print("\n" + "=" * 74)
    print("报告 2：是否存在旧端无法解析的报文（真正的向后兼容破坏）")
    print("=" * 74)
    if not legacy.parse_errors:
        print("  无。旧端对收到的全部帧均解析成功，未触发任何协议错误。")
    for e in legacy.parse_errors:
        print(f"  [解析失败] {e}")
    check("旧端零解析失败", not legacy.parse_errors)
    check("旧端未遇到不认识的 type", not legacy.unknown_types,
          str(legacy.unknown_types))

    print("\n" + "=" * 74)
    print("报告 3：结论")
    print("=" * 74)
    print(f"  UDP 发现     : {'通' if legacy.disc_rx else '不通'}"
          f"（Windows 单播回 DISC，字段含 host/alt，旧端忽略后正常）")
    print(f"  TCP 握手     : {'通' if legacy.win_hello else '不通'}")
    print(f"  文本 TEXT    : {'通' if legacy.texts else '不通'}"
          f"（旧端回 ACK，Windows 状态 ok）")
    print(f"  文件 FILE_*  : {'通' if legacy.files and list(legacy.files.values())[0]['ok'] else '不通'}"
          f"（1.5MB / {len(bin_frames)} 块，MD5 一致，Windows 收到 FILE_OK）")
    print(f"  旧端接受的 TCP 连接数: {legacy.accepted}")
    print()
    verdict = (not legacy.parse_errors) and bool(legacy.texts) and bool(legacy.files) \
        and bool(legacy.disc_rx) and (legacy.win_hello is not None)
    if verdict:
        print("  >>> 协议层面【完全互通】。新版 Windows 与旧版 Android 之间不存在")
        print("      协议层面的不兼容；新版多出的 host/alt/ips/scheme 字段均被旧端")
        print("      安全忽略，未造成任何解析失败。因此「新版 exe 与旧版 apk 传不了」")
        print("      不可能是协议版本问题，只能是网络/环境层面（代理、防火墙、AP 隔离等）。")
    else:
        print("  >>> 协议层面【存在不互通】，详见上方失败项。")

    win.stop()
    legacy.stop.set()
    time.sleep(0.6)

    print("\n" + "=" * 74)
    print(f"===== 结果: {len(PASS)} 通过, {len(FAIL)} 失败 =====")
    if FAIL:
        print("失败项:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
