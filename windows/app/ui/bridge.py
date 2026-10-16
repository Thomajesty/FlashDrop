# -*- coding: utf-8 -*-
"""节点事件桥：把 asyncio 线程中的事件安全投递到 Qt 主线程。"""

import queue
import threading

from PySide6.QtCore import QObject, QTimer, Signal

from ..node import FlashNode


class NodeBridge(QObject):
    """封装 FlashNode，所有事件转为 Qt 信号（在 UI 线程发出）"""

    peersChanged = Signal(list)          # [{id,name,platform,online,connected,ips...}]
    textReceived = Signal(dict)          # {peer_id,name,mid,text,ts}
    textState = Signal(dict)             # {peer_id,mid,state,reason}
    ackReceived = Signal(str, str)       # peer_id, mid
    transferEvent = Signal(dict)         # {kind,tid,peer_id,file,size,state,...}
    logMessage = Signal(str, str)        # level, msg
    scanDone = Signal(dict)              # {full, found}
    peerMerged = Signal(str, str)        # 同机跨版本身份合并：old_id, new_id
    # ★ v1.18.15：待发队列补发结果（工作线程 → UI 线程）
    #   payload = {"snapshot": [...], "remain": [...], "ok": [(entry, mid)], "sent": n}
    pendingFlushDone = Signal(dict)

    def __init__(self, node: FlashNode, parent=None):
        super().__init__(parent)
        self.node = node
        self._q = queue.Queue()
        self._timer = QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._drain)
        self._lock = threading.Lock()
        node.emit = self._on_evt

    def start(self):
        self.node.start()
        self._timer.start()

    def stop(self):
        self._timer.stop()
        self.node.stop()

    def _on_evt(self, evt: dict):
        """在 node 线程调用"""
        with self._lock:
            self._q.put(evt)

    def _drain(self):
        batch = []
        with self._lock:
            while True:
                try:
                    batch.append(self._q.get_nowait())
                except queue.Empty:
                    break
        if not batch:
            return
        # 进度事件节流：同一 (kind,tid,peer) 只保留最后一个 progress；
        # 若同批已有终态事件（done/ok/failed/refused/cancelled），丢弃 progress，
        # 防止终态被旧进度覆盖。
        TERMINAL = {"done", "ok", "failed", "refused", "cancelled"}
        terminal_keys = set()
        for e in batch:
            if e.get("event") == "transfer" and e.get("state") in TERMINAL:
                terminal_keys.add((e.get("kind"), e.get("tid"), e.get("peer_id")))
        seen_prog = {}
        others = []
        for e in batch:
            if e.get("event") == "transfer" and e.get("state") == "progress":
                key = (e.get("kind"), e.get("tid"), e.get("peer_id"))
                if key in terminal_keys:
                    continue
                seen_prog[key] = e
            else:
                others.append(e)
        events = others + list(seen_prog.values())
        for e in events:
            ev = e.get("event")
            if ev == "peers":
                self.peersChanged.emit(e["peers"])
            elif ev == "text":
                self.textReceived.emit(e)
            elif ev == "text_state":
                self.textState.emit(e)
            elif ev == "ack":
                self.ackReceived.emit(e["peer_id"], e["mid"])
            elif ev == "transfer":
                self.transferEvent.emit(e)
            elif ev == "log":
                self.logMessage.emit(e.get("level", "info"), e.get("msg", ""))
            elif ev == "scan_done":
                self.scanDone.emit(e)
            elif ev == "peer_merged":
                self.peerMerged.emit(e.get("old", ""), e.get("new", ""))

    # ---- 便捷转发（线程安全） ----
    def send_text(self, targets, text):
        return self.node.send_text(targets, text)

    # ★ v1.18.15：待发队列用 —— 阻塞到每个目标都有结论（须在工作线程调用）
    def send_text_sync(self, targets, text, timeout=45.0):
        return self.node.send_text_sync(targets, text, timeout)

    def send_files_sync(self, targets, paths, timeout=1800.0):
        """★ v1.18.20：同步文件发送（待发队列补发用，确认送达才移除条目）"""
        return self.node.send_files_sync(targets, paths, timeout)

    def emit_pending_flush_done(self, payload: dict):
        """工作线程调用：把补发结果投递回 UI 线程"""
        self.pendingFlushDone.emit(payload)

    def send_files(self, targets, paths):
        self.node.send_files(targets, paths)

    def accept_inbound(self, tid):
        self.node.accept_inbound(tid)

    def reject_inbound(self, tid):
        self.node.reject_inbound(tid)

    def cancel_inbound(self, tid):
        self.node.cancel_inbound(tid)

    def cancel_send(self, tid):
        self.node.cancel_send(tid)

    def rescan(self, full=True):
        self.node.rescan(full=full)

    def connect_manual(self, host, port):
        return self.node.connect_manual(host, port)

    def set_name(self, name):
        self.node.set_name(name)

    def online_peer_ids(self):
        return self.node.online_peer_ids()
