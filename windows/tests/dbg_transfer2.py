# -*- coding: utf-8 -*-
import os, sys, tempfile, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TMP = tempfile.mkdtemp(prefix="fd_dbg2_")
os.environ["FLASHDROP_DATA_DIR"] = _TMP
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Config
from app.node import FlashNode

def make_node(name, pid, port, encrypt):
    cfg = Config(os.path.join(_TMP, f"{pid}.json"))
    cfg.data.update({"device_id": pid, "name": name, "port": port,
                     "save_dir": os.path.join(_TMP, pid + "_save"),
                     "cache_dir": os.path.join(_TMP, pid + "_cache"),
                     "encrypt": encrypt})
    cfg.save()
    return FlashNode(cfg)

A = make_node("A", "aaaaaaaaaaaaaaaa", 58980, False)
B = make_node("B", "bbbbbbbbbbbbbbbb", 58981, False)
evA, evB = [], []
A.emit = lambda e: evA.append(e)
B.emit = lambda e: evB.append(e)
A.start(); B.start()
time.sleep(2)
fut = A.connect_manual("127.0.0.1", 58981)
print("connect:", fut.result(15))
time.sleep(1)

def dump(tag):
    print(tag, "A.conns:", {k: (v.alive, v.replaced, v.hello_got, v.remote_port)
                            for k, v in A.conns.items()})
    print(tag, "B.conns:", {k: (v.alive, v.replaced, v.hello_got, v.remote_port)
                            for k, v in B.conns.items()})

dump("before-text")
mid = A.send_text(["bbbbbbbbbbbbbbbb"], "hello")
time.sleep(3)
txt = [e for e in evB if e.get("event") == "text"]
print("B got text:", bool(txt))
tsA = [e for e in evA if e.get("event") == "text_state"]
print("A text_state:", [(e.get("state"), e.get("reason")) for e in tsA])
dump("after-text")

src = os.path.join(_TMP, "dbg.bin")
open(src, "wb").write(os.urandom(2 * 1024 * 1024))
A.send_files(["bbbbbbbbbbbbbbbb"], [src])
time.sleep(17)
print("evA transfers:", [(e.get("state"), e.get("reason")) for e in evA if e.get("event") == "transfer"])
print("evB transfers:", [(e.get("state"), e.get("reason")) for e in evB if e.get("event") == "transfer"])
dump("after-file")
A.stop(); B.stop()
