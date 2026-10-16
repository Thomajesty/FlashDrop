# -*- coding: utf-8 -*-
"""插桩复现：记录 A/B 两端 _register_conn/_on_accept/closeConn 的完整时序"""
import os, sys, tempfile, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TMP = tempfile.mkdtemp(prefix="fd_dbg3_")
os.environ["FLASHDROP_DATA_DIR"] = _TMP
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Config
from app.node import FlashNode

LOG = []
def log(who, msg):
    LOG.append(f"{time.time()%100:07.3f} [{who}] {msg}")
    print(f"{time.time()%100:07.3f} [{who}] {msg}")

def make_node(name, pid, port, encrypt):
    cfg = Config(os.path.join(_TMP, f"{pid}.json"))
    cfg.data.update({"device_id": pid, "name": name, "port": port,
                     "save_dir": os.path.join(_TMP, pid + "_save"),
                     "cache_dir": os.path.join(_TMP, pid + "_cache"),
                     "encrypt": encrypt})
    cfg.save()
    n = FlashNode(cfg)
    return n

A = make_node("A", "aaaaaaaaaaaaaaaa", 58990, False)
B = make_node("B", "bbbbbbbbbbbbbbbb", 58991, False)

# 插桩
from app.node import Conn
_orig_cc = Conn.close
def _cc(self):
    log("conn", f"close {id(self)%10000} inc={self.incoming} remote={self.remote_port}")
    return _orig_cc(self)
Conn.close = _cc

for name, node in (("A", A), ("B", B)):
    orig_reg = node._register_conn
    def reg(conn, hello, _n=name, _o=orig_reg):
        log(_n, f"register {id(conn)%10000} peer={hello.get('id','')[:4]} inc={conn.incoming} remote={conn.remote_port}")
        r = _o(conn, hello)
        log(_n, f"register {id(conn)%10000} -> {r}")
        return r
    node._register_conn = reg
    orig_accept = node._on_accept
    async def acc(reader, writer, _n=name, _o=orig_accept):
        log(_n, f"accept remote={writer.get_extra_info('peername')}")
        return await _o(reader, writer)
    node._on_accept = acc
    orig_sess = node._session
    async def sess(conn, _n=name, _o=orig_sess):
        log(_n, f"session {id(conn)%10000} inc={conn.incoming}")
        return await _o(conn)
    node._session = sess

A.start(); B.start()
time.sleep(3)
print("=== A.conns:", {k[:4]: (v.alive, v.remote_port) for k, v in A.conns.items()})
print("=== B.conns:", {k[:4]: (v.alive, v.remote_port) for k, v in B.conns.items()})
A.stop(); B.stop()
