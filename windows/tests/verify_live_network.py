# -*- coding: utf-8 -*-
"""真实局域网环境下的发现 + 互通自检（v1.7.1 新增）。

用途：当场验证"这台电脑"当前的代理/网卡/防火墙环境下 FlashDrop 能否正常发现与互通，
用于回答"新版 exe 与旧版 apk 能否通讯 / 是不是代理的问题"。

运行: python tests/verify_live_network.py
"""
import os
import sys
import tempfile
import time
import hashlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import Config
from app.node import FlashNode
from app import netinfo

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{('  ' + extra) if extra else ''}")


def make_node(tmp, dev_id, port, name):
    cfg = Config(os.path.join(tmp, f"cfg_{dev_id}.json"))
    cfg.data["device_id"] = dev_id
    cfg.data["name"] = name
    cfg.data["port"] = port
    cfg.data["save_dir"] = os.path.join(tmp, f"{dev_id}_save")
    cfg.data["cache_dir"] = os.path.join(tmp, f"{dev_id}_cache")
    cfg.data["auto_accept"] = True
    cfg.save()
    events = []
    lock = [False]

    def emit(e):
        events.append(e)

    node = FlashNode(cfg, emit=emit)
    return node, events, lock


def wait_for(events, pred, timeout=25):
    t0 = time.time()
    while time.time() - t0 < timeout:
        for e in events:
            if pred(e):
                return e
        time.sleep(0.1)
    return None


def main():
    print("=" * 66)
    print("FlashDrop 真实网络环境自检（发现 / 连接 / 文本 / 文件）")
    print("=" * 66)

    print("\n== 0. 本机网络环境 ==")
    ifs = netinfo.get_local_ifaces()
    for i in ifs:
        print(f"  物理网卡: {i.ip}  {i.desc}")
    check("至少识别到 1 张可用物理网卡", len(ifs) >= 1, f"共 {len(ifs)} 张")
    # 虚拟网卡必须已被过滤（代理/TUN/VPN 不会干扰发现）
    descs = " ".join((i.desc or "") for i in ifs).lower()
    check("已过滤虚拟/隧道网卡（代理软件不影响发现）",
          not any(k in descs for k in ("tun", "tap", "wintun", "virtual", "vmware", "hyper-v")))

    tmp = tempfile.mkdtemp(prefix="fd_live_")
    P1, P2 = 59301, 59302
    a, ev_a, _ = make_node(tmp, "live-A", P1, "自检A")
    b, ev_b, _ = make_node(tmp, "live-B", P2, "自检B")
    a.start()
    b.start()
    try:
        print("\n== 1. 局域网自动发现 ==")
        got = wait_for(ev_a, lambda e: e.get("event") == "peers"
                       and any(p.get("id") == "live-B" for p in e.get("peers", [])), 20)
        check("A 通过 UDP 广播发现 B", got is not None)
        got2 = wait_for(ev_b, lambda e: e.get("event") == "peers"
                        and any(p.get("id") == "live-A" for p in e.get("peers", [])), 20)
        check("B 通过 UDP 广播发现 A", got2 is not None)

        print("\n== 2. TCP 连接 ==")
        conn_ev = wait_for(ev_a, lambda e: e.get("event") == "peers"
                           and any(p.get("id") == "live-B" and p.get("online")
                                   for p in e.get("peers", [])), 20)
        check("B 在 A 的设备列表中显示为在线", conn_ev is not None)

        print("\n== 3. 文本互发 ==")
        a.send_text(["live-B"], "真实网络互通测试")
        t = wait_for(ev_b, lambda e: e.get("event") == "text"
                     and e.get("text") == "真实网络互通测试", 15)
        check("B 收到 A 的文本", t is not None)
        if t:
            check("文本回执 ACK 返回 A", wait_for(
                ev_a, lambda e: e.get("event") == "ack"
                and e.get("mid") == t.get("mid"), 10) is not None)

        print("\n== 4. 文件传输（含 MD5 校验）==")
        src = os.path.join(tmp, "live_test.bin")
        with open(src, "wb") as f:
            f.write(os.urandom(600 * 1024))
        h = hashlib.md5(open(src, "rb").read()).hexdigest()
        a.send_files(["live-B"], [src])
        d = wait_for(ev_b, lambda e: e.get("event") == "transfer"
                     and e.get("kind") == "recv" and e.get("state") == "done", 30)
        check("B 接收完成", d is not None)
        if d:
            p = d.get("path")
            ok = p and os.path.exists(p) and \
                hashlib.md5(open(p, "rb").read()).hexdigest() == h
            check("落盘文件 MD5 与源一致", ok, f"{os.path.basename(str(p))} ({os.path.getsize(str(p))}B)")
    finally:
        a.stop()
        b.stop()

    print(f"\n===== 结果: {len(PASS)} 通过, {len(FAIL)} 失败 =====")
    if FAIL:
        print("失败项: " + "; ".join(FAIL))
        print("\n排查建议：")
        print("  1) 确认设备与本机处于同一 Wi-Fi/局域网，且非访客网络")
        print("  2) 若设备列表为空：把 FlashDrop.exe 放回本目录运行，"
              "或在 设置→网络 点一次“允许 Windows 防火墙入站”")
        print("     （Windows 防火墙规则按 exe 完整路径绑定，换路径后旧规则失效）")
        print("  3) 检查路由器是否开启 AP/客户端隔离")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
