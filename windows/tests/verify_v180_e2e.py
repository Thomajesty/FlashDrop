# -*- coding: utf-8 -*-
"""v1.8.0 端到端：接收文件按设备分文件夹（真实 TCP 传输后校验落盘路径）。

用两个真实节点跑完整协议（UDP 发现 / TCP 握手 / FILE_START / 分块 / MD5），
然后断言接收端落盘路径形如 <save_dir>/<设备名>/<文件名>。
"""
import os
import sys
import tempfile
import time
import hashlib
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import Config  # noqa: E402
from app.node import FlashNode  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [PASS] %s%s" % (name, ("  " + extra) if extra else ""))
    else:
        FAIL += 1
        print("  [FAIL] %s%s" % (name, ("  " + extra) if extra else ""))


def make_node(tmp, dev_id, port, name):
    cfg = Config(os.path.join(tmp, "cfg_%s.json" % dev_id))
    cfg.data["device_id"] = dev_id
    cfg.data["name"] = name
    cfg.data["port"] = port
    cfg.data["save_dir"] = os.path.join(tmp, "%s_save" % dev_id)
    cfg.data["cache_dir"] = os.path.join(tmp, "%s_cache" % dev_id)
    cfg.data["auto_accept"] = True
    cfg.save()
    events = []
    return FlashNode(cfg, emit=events.append), events


def wait_for(events, pred, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        for e in events:
            if pred(e):
                return e
        time.sleep(0.1)
    return None


def main():
    print("=" * 66)
    print("v1.8.0 端到端验证：接收文件按设备分文件夹")
    print("=" * 66)
    tmp = tempfile.mkdtemp(prefix="fd180e2e_")
    try:
        # A 设备名故意带 Windows 非法字符（: 和 /），验证目录名净化生效
        a, ev_a = make_node(tmp, "dev-A", 59411, "小米: 14/Pro")
        b, ev_b = make_node(tmp, "dev-B", 59412, "华为 P60")
        a.start()
        b.start()
        try:
            print("\n== 1. 局域网自动发现 ==")
            ev = wait_for(ev_a, lambda e: e.get("event") == "peers" and any(
                p.get("id") == "dev-B" and p.get("online")
                for p in e.get("peers", [])), 25)
            check("A 发现 B 在线", ev is not None)

            print("\n== 2. 文件传输（真实分块 + MD5）==")
            src = os.path.join(tmp, "报告 v1.8.pdf")
            data = os.urandom(300 * 1024)
            with open(src, "wb") as f:
                f.write(data)
            md5 = hashlib.md5(data).hexdigest()
            a.send_files(["dev-B"], [src])

            d = wait_for(ev_b, lambda e: e.get("event") == "transfer"
                         and e.get("kind") == "recv" and e.get("state") == "done", 40)
            check("B 接收完成", d is not None)
            if d is None:
                return fin()
            path = d.get("path") or ""
            print("  落盘路径: %s" % path)
            check("文件真实存在", os.path.isfile(path))

            print("\n== 3. 按设备分文件夹校验 ==")
            save_dir = b.cfg["save_dir"]
            expect_folder = "小米_ 14_Pro"      # ':' 与 '/' → '_'
            expect_dir = os.path.join(save_dir, expect_folder)
            check("按设备名建了子目录", os.path.isdir(expect_dir), expect_dir)
            check("文件在设备子目录内",
                  os.path.isfile(os.path.join(expect_dir, "报告 v1.8.pdf")))
            check("未落在 save_dir 根目录（隔离生效）",
                  not os.path.isfile(os.path.join(save_dir, "报告 v1.8.pdf")))

            print("\n== 4. 内容与目录名合法性 ==")
            with open(path, "rb") as f:
                got_md5 = hashlib.md5(f.read()).hexdigest()
            check("MD5 与源一致", got_md5 == md5, got_md5[:12])
            folder = os.path.basename(os.path.dirname(path))
            check("目录名已净化（无 : / \\ * ? \" < > |）",
                  not any(c in folder for c in ':/\\*?"<>|'), folder)
        finally:
            a.stop()
            b.stop()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return fin()


def fin():
    print()
    print("===== 结果: %d 通过, %d 失败 =====" % (PASS, FAIL))
    print("ALL_OK" if FAIL == 0 else "HAS_FAILURE")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
