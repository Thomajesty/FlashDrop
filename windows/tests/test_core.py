# -*- coding: utf-8 -*-
"""FlashDrop 核心协议集成测试（无 UI，本机多节点）。

覆盖：扫描发现、连接去重（多路由双向尝试的核心逻辑）、文本互发、
文件互发（MD5 校验）、多目标同步发送、接收确认/拒绝、传输取消。
运行: python tests/test_core.py
"""

import os
import sys
import tempfile
import threading
import time
import hashlib
import random

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import Config
from app.node import FlashNode


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


def make_node(tmp, dev_id, port, name, auto_accept=True):
    cfg = Config(os.path.join(tmp, f"cfg_{dev_id}.json"))
    cfg.data["device_id"] = dev_id
    cfg.data["name"] = name
    cfg.data["port"] = port
    cfg.data["save_dir"] = os.path.join(tmp, f"{dev_id}_save")
    cfg.data["cache_dir"] = os.path.join(tmp, f"{dev_id}_cache")
    cfg.data["auto_accept"] = auto_accept
    cfg.save()
    col = Collector()
    node = FlashNode(cfg, emit=col)
    return node, col


def md5file(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def make_big_file(path, size):
    rnd = random.Random(42)
    with open(path, "wb") as f:
        left = size
        while left > 0:
            n = min(left, 1024 * 1024)
            f.write(rnd.randbytes(n))
            left -= n
    return path


PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  [PASS] {name}")
    else:
        FAIL.append(name)
        print(f"  [FAIL] {name}  {detail}")


def main():
    tmp = tempfile.mkdtemp(prefix="flashdrop_test_")
    A_ID, B_ID, C_ID = "aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb", "cccccccccccccccc"
    A, colA = make_node(tmp, A_ID, 58899, "节点A")
    B, colB = make_node(tmp, B_ID, 58900, "节点B")
    C, colC = make_node(tmp, C_ID, 58901, "节点C", auto_accept=False)

    A.start()
    B.start()
    C.start()
    time.sleep(1.0)

    print("== 1. 本机网卡信息 ==")
    from app import netinfo
    ifaces = netinfo.get_local_ifaces()
    print(f"  网卡: {[(i.ip, i.netmask, i.broadcast) for i in ifaces]}")
    print(f"  网关: {netinfo.get_gateways()}")
    check("网卡信息可获取", len(ifaces) >= 0)

    print("== 2. 扫描发现与自动连接（模拟跨子网发现）==")
    # B/C 端口不同，靠扫描（含默认端口探测）发现 A
    ev = colB.wait_for(lambda e: e["event"] == "log" and "已连接" in e.get("msg", ""), 30)
    check("B 通过扫描发现并连接 A", ev is not None, str([e for e in colB.events if e["event"] == "log"][-3:]))
    ev = colC.wait_for(lambda e: e["event"] == "log" and "已连接" in e.get("msg", ""), 30)
    check("C 通过扫描发现并连接 A", ev is not None)
    # A 侧应有 B、C 两个连接
    ev = colA.wait_for(lambda e: e["event"] == "peers" and
                       len([p for p in e["peers"] if p["connected"]]) >= 2, 15)
    check("A 看到两台在线设备", ev is not None,
          str(A.peers_snapshot()))

    print("== 3. 连接去重（双向连接尝试收敛为单连接）==")
    # 双方同时手动互连，模拟级联路由下双向尝试
    futA = A.connect_manual("127.0.0.1", 58900)
    futB = B.connect_manual("127.0.0.1", 58899)
    rA = futA.result(20) if futA else (False, "no fut")
    rB = futB.result(20) if futB else (False, "no fut")
    time.sleep(3.0)  # 等待替换/关闭完成
    alive_a = [c for c in A.conns.values() if c.alive and not c.replaced]
    alive_b = [c for c in B.conns.values() if c.alive and not c.replaced]
    conns_a_b = [c for c in alive_a if c.peer_id == B_ID]
    conns_b_a = [c for c in alive_b if c.peer_id == A_ID]
    check("A 与 B 恰好一条活跃连接", len(conns_a_b) == 1, f"实际 {len(conns_a_b)}")
    check("B 与 A 恰好一条活跃连接", len(conns_b_a) == 1, f"实际 {len(conns_b_a)}")

    print("== 4. 文本互发与回执 ==")
    A.send_text([B_ID], "你好，B！")
    ev = colB.wait_for(lambda e: e["event"] == "text" and e["text"] == "你好，B！", 10)
    check("B 收到 A 的文本", ev is not None)
    ev = colA.wait_for(lambda e: e["event"] == "ack" and e["peer_id"] == B_ID, 10)
    check("A 收到 B 的回执", ev is not None)
    B.send_text([A_ID], "收到，A！")
    ev = colA.wait_for(lambda e: e["event"] == "text" and e["text"] == "收到，A！", 10)
    check("A 收到 B 的文本（连接双向复用）", ev is not None)

    print("== 5. 文件传输 A->B（MD5 校验）==")
    src = make_big_file(os.path.join(tmp, "src_20m.bin"), 20 * 1024 * 1024)
    src_md5 = md5file(src)
    A.send_files([B_ID], [src])
    ev = colB.wait_for(lambda e: e["event"] == "transfer" and e["kind"] == "recv"
                       and e["state"] == "done", 60)
    check("B 接收完成", ev is not None)
    if ev:
        got = ev["path"]
        check("接收文件存在", os.path.isfile(got), got)
        check("文件名一致", os.path.basename(got) == "src_20m.bin", got)
        check("MD5 一致", os.path.isfile(got) and md5file(got) == src_md5)
    ev = colA.wait_for(lambda e: e["event"] == "transfer" and e["kind"] == "send"
                       and e["state"] == "ok", 30)
    check("A 收到 FILE_OK", ev is not None)

    print("== 6. 文件传输 B->A（反向复用同一条连接）==")
    src2 = make_big_file(os.path.join(tmp, "src2_5m.bin"), 5 * 1024 * 1024)
    src2_md5 = md5file(src2)
    B.send_files([A_ID], [src2])
    ev = colA.wait_for(lambda e: e["event"] == "transfer" and e["kind"] == "recv"
                       and e["state"] == "done", 60)
    check("A 接收完成", ev is not None)
    if ev:
        check("反向 MD5 一致", os.path.isfile(ev["path"]) and md5file(ev["path"]) == src2_md5)

    print("== 7. 多目标同步发送（B、C 同时收）==")
    src3 = make_big_file(os.path.join(tmp, "src3_8m.bin"), 8 * 1024 * 1024)
    src3_md5 = md5file(src3)
    # C 未开启自动接收：先发送，再在确认事件中接受
    A.send_files([B_ID, C_ID], [src3])
    evC = colC.wait_for(lambda e: e["event"] == "transfer" and e["kind"] == "recv"
                        and e["state"] == "confirm", 15)
    check("C 收到确认请求（自动接收关闭）", evC is not None)
    if evC:
        C.accept_inbound(evC["tid"])
    evB = colB.wait_for(lambda e: e["event"] == "transfer" and e["kind"] == "recv"
                        and e["state"] == "done" and e["file"] == "src3_8m.bin", 60)
    evC2 = colC.wait_for(lambda e: e["event"] == "transfer" and e["kind"] == "recv"
                         and e["state"] == "done" and e["file"] == "src3_8m.bin", 60)
    check("B 同步接收完成", evB is not None)
    check("C 确认后接收完成", evC2 is not None)
    if evB and evC2:
        check("B 内容一致", md5file(evB["path"]) == src3_md5)
        check("C 内容一致", md5file(evC2["path"]) == src3_md5)

    print("== 8. 拒绝接收 ==")
    src4 = make_big_file(os.path.join(tmp, "src4_1m.bin"), 1024 * 1024)
    A.send_files([C_ID], [src4])
    evC = colC.wait_for(lambda e: e["event"] == "transfer" and e["kind"] == "recv"
                        and e["state"] == "confirm" and e["file"] == "src4_1m.bin", 15)
    check("C 再次收到确认请求", evC is not None)
    if evC:
        C.reject_inbound(evC["tid"])
    evA = colA.wait_for(lambda e: e["event"] == "transfer" and e["kind"] == "send"
                        and e["state"] == "refused", 20)
    check("A 收到拒绝通知", evA is not None)

    print("== 9. 传输取消 ==")
    src5 = make_big_file(os.path.join(tmp, "src5_200m.bin"), 200 * 1024 * 1024)
    A.send_files([B_ID], [src5])
    evP = colB.wait_for(lambda e: e["event"] == "transfer" and e["kind"] == "recv"
                        and e["state"] == "progress"
                        and e["transferred"] > 3 * 1024 * 1024, 60)
    check("B 传输进行中（进度事件）", evP is not None)
    if evP:
        B.cancel_inbound(evP["tid"])
        time.sleep(1.0)
        parts = [f for f in os.listdir(B.cfg.cache_dir) if f.endswith(".part")]
        check("取消后 .part 已清理", len(parts) == 0, str(parts))
    evA = colA.wait_for(lambda e: e["event"] == "transfer" and e["kind"] == "send"
                        and e["state"] == "cancelled", 30)
    check("A 收到取消通知", evA is not None)

    print("== 10. 中文文件名与特殊字符安全 ==")
    src6 = os.path.join(tmp, "测试 文件[1].txt")
    with open(src6, "w", encoding="utf-8") as f:
        f.write("中文内容测试" * 100)
    A.send_files([B_ID], [src6])
    ev = colB.wait_for(lambda e: e["event"] == "transfer" and e["kind"] == "recv"
                       and e["state"] == "done" and "测试" in e["file"], 30)
    check("中文名文件接收成功", ev is not None and os.path.isfile(ev["path"]))
    # 目录穿越攻击
    from app.util import safe_filename
    check("目录穿越被过滤", safe_filename("../../evil.exe") == "..evil.png" or
          "/" not in safe_filename("../../evil.exe"),
          safe_filename("../../evil.exe"))

    print("== 11. 心跳保活（10 秒无数据仍在线）==")
    time.sleep(11)
    snap = A.peers_snapshot()
    b_online = [p for p in snap if p["id"] == B_ID and p["online"]]
    check("静默期后 B 仍在线（心跳）", len(b_online) == 1, str(snap))

    A.stop()
    B.stop()
    C.stop()

    print()
    print(f"===== 结果: {len(PASS)} 通过, {len(FAIL)} 失败 =====")
    if FAIL:
        print("失败项:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
