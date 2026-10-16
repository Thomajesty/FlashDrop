# -*- coding: utf-8 -*-
"""模拟对端设备：UDP 广播发现 + TCP 应答（HELLO/ACK/PONG），供真机 GUI 验证。
用法: python fake_peer.py  ->  设备"测试对端"(deadbeef12345678) 端口 58999
Ctrl+C 退出。收到 TEXT 打印并回 ACK，使真实端气泡显示"已送达"。"""
import json
import socket
import struct
import sys
import threading
import time

DEV_ID = "deadbeef12345678"
NAME = "测试对端"
TCP_PORT = 58999
UDP_PORT = 58899

disc = json.dumps({"app": "FlashDrop", "v": 1, "type": "DISC", "id": DEV_ID,
                   "name": NAME, "platform": "windows", "tcp": TCP_PORT,
                   "host": "FakeHost-Test"}).encode("utf-8")

stop = threading.Event()


def announce():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    while not stop.is_set():
        for target in [("127.0.0.1", UDP_PORT), ("192.168.1.255", UDP_PORT),
                       ("255.255.255.255", UDP_PORT)]:
            try:
                s.sendto(disc, target)
            except Exception:
                pass
        time.sleep(1.0)


def read_frame(r):
    hdr = b""
    while len(hdr) < 4:
        c = r.recv(4 - len(hdr))
        if not c:
            raise ConnectionError("closed")
        hdr += c
    (length,) = struct.unpack(">I", hdr)
    payload = b""
    while len(payload) < length:
        c = r.recv(length - len(payload))
        if not c:
            raise ConnectionError("closed")
        payload += c
    return payload


def send_json(w, obj):
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    w.sendall(struct.pack(">I", len(body) + 1) + b"J" + body)


def tcp_server():
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", TCP_PORT))
    srv.listen(5)
    while not stop.is_set():
        try:
            srv.settimeout(1.0)
            c, addr = srv.accept()
        except socket.timeout:
            continue
        print(f"[+] 真实端已连接 {addr}", flush=True)
        threading.Thread(target=session, args=(c,), daemon=True).start()


def session(c):
    hello_sent = False
    try:
        while not stop.is_set():
            payload = read_frame(c)
            kind = payload[0:1]
            if kind == b"J":
                obj = json.loads(payload[1:].decode("utf-8"))
                t = obj.get("type")
                if t == "HELLO":
                    print(f"[HELLO] 对端: id={obj.get('id')} name={obj.get('name')}", flush=True)
                    send_json(c, {"app": "FlashDrop", "v": 1, "type": "HELLO",
                                  "id": DEV_ID, "name": NAME, "platform": "windows",
                                  "tcp": TCP_PORT, "ips": ["127.0.0.1"]})
                    hello_sent = True
                elif t == "TEXT":
                    print(f"[TEXT] 收到: {obj.get('text')!r}", flush=True)
                    send_json(c, {"type": "ACK", "mid": obj.get("mid")})
                elif t == "PING":
                    send_json(c, {"type": "PONG"})
                elif t in ("FILE_START",):
                    print(f"[FILE_START] {obj.get('name')} {obj.get('size')}B", flush=True)
                    send_json(c, {"type": "RECV_READY", "tid": obj.get("tid")})
                else:
                    print(f"[{t}]", flush=True)
            elif kind == b"B":
                print(f"[BIN] {len(payload)}B", flush=True)
    except Exception as e:
        print(f"[-] 连接结束: {e}", flush=True)
    finally:
        c.close()


if __name__ == "__main__":
    threading.Thread(target=announce, daemon=True).start()
    print(f"模拟设备 {NAME}({DEV_ID}) 启动，TCP={TCP_PORT}，广播 UDP={UDP_PORT}", flush=True)
    try:
        tcp_server()
    except KeyboardInterrupt:
        stop.set()
