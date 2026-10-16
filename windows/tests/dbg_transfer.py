# -*- coding: utf-8 -*-
import os, sys, tempfile, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TMP = tempfile.mkdtemp(prefix="fd_dbg_")
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

A = make_node("A", "aaaaaaaaaaaaaaaa", 58970, False)
B = make_node("B", "bbbbbbbbbbbbbbbb", 58971, False)
evA, evB = [], []
A.emit = lambda e: (evA.append(e), print("[A]", e.get("event"), e.get("state", ""), e.get("msg", "")))
B.emit = lambda e: (evB.append(e), print("[B]", e.get("event"), e.get("state", ""), e.get("msg", "")))
A.start(); B.start()
time.sleep(2)
fut = A.connect_manual("127.0.0.1", 58971)
print("connect:", fut.result(15))
src = os.path.join(_TMP, "dbg.bin")
open(src, "wb").write(os.urandom(2 * 1024 * 1024))
print("target check:", A.online_peer_ids())
A.send_files(["bbbbbbbbbbbbbbbb"], [src])
for i in range(40):
    time.sleep(0.5)
    done = [e for e in evB if e.get("event") == "transfer" and e.get("state") == "done"]
    if done:
        print("DONE at", i * 0.5, "s ->", done[-1].get("path"))
        break
else:
    print("NOT DONE. evB transfers:", [(e.get("kind"), e.get("state"), e.get("reason")) for e in evB if e.get("event") == "transfer"])
    print("A out_states:", dict(A.out_states))
A.stop(); B.stop()
