# -*- coding: utf-8 -*-
"""聊天记录持久化：每个 peer 一个 JSONL 文件（%APPDATA%\\FlashDrop\\history）"""

import hashlib
import json
import os
import threading
import time

from ..config import app_data_dir


def _now_ms():
    return int(time.time() * 1000)


class History:
    #★ v1.18.18：文件名只是"安全化后的 peer_id"，不可逆。
    #   而 all_peer_ids()（搜索范围、历史列表、设备列表补全都依赖它）
    #   只能拿回文件名 —— 对含非法字符的 peer_id 就会**丢失/错位**。
    #   所以额外维护一张 safe_name -> real_id 映射表，保证能还原真实 id。
    INDEX = "_index.json"

    def __init__(self, max_per_peer=500):
        self.dir = os.path.join(app_data_dir(), "history")
        os.makedirs(self.dir, exist_ok=True)
        self.max = max_per_peer
        self._cache = {}
        self._cache_n = {}      # peer_id -> 已缓存条数上限（懒加载判定）
        self._lock = threading.Lock()
        self._idx_lock = threading.Lock()   # 独立锁：_index_save 可能在持锁区被调
        self._index = {}
        self._load_index()

    # ---------- 安全文件名<->真实 peer_id 映射 ----------

    @staticmethod
    def _safe_name(peer_id: str) -> str:
        return "".join(c for c in (peer_id or "")
                       if c.isalnum() or c in "-_")[:64]

    def _index_path(self):
        return os.path.join(self.dir, self.INDEX)

    def _load_index(self):
        try:
            with open(self._index_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._index = {str(k): str(v) for k, v in data.items()}
        except Exception:
            self._index = {}

    def _index_put(self, peer_id: str):
        """记录 safe_name -> peer_id

        ★ 不加锁：本方法会在调用方已持有 self._lock 时被调用
        （append 内部就是先 with self._lock 再 _path()）。
        threading.Lock 不可重入，这里再加锁会直接死锁。
        """
        if not peer_id:
            return
        safe = self._safe_name(peer_id)
        if not safe:
            safe = "id_" + hashlib.md5(peer_id.encode("utf-8")).hexdigest()
        self._index[safe] = peer_id

    def _index_save(self):
        """落盘映射表（用**独立**锁：可能被持有 self._lock 的调用方触发）"""
        try:
            data = dict(self._index)
        except Exception:
            return
        try:
            with self._idx_lock:
                tmp = self._index_path() + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
                os.replace(tmp, self._index_path())
        except Exception:
            pass

    def _path(self, peer_id):
        safe = self._safe_name(peer_id)
        if not safe:
            # ★ 全部字符都被过滤掉时不能退回 ".jsonl"：
            #   那会让所有这类设备共用一个文件，历史互相覆盖、
            #   且 all_peer_ids() 完全查不到。必须用哈希分桶。
            safe = "id_" + hashlib.md5((peer_id or "").encode("utf-8")
                                       ).hexdigest()
        self._index_put(peer_id)
        return os.path.join(self.dir, safe + ".jsonl")

    @staticmethod
    def _read_tail(path: str, n_lines: int, chunk: int = 65536) -> list:
        """★ v1.18.18 性能 P1：只读文件尾部 n_lines 行，不再全文件 readlines。

        旧实现把整个 jsonl 一次读进内存（100MB 记录就是 100MB 字符串 +
        全量 split），而调用方只消费尾部几十~几百行。
        现在从文件尾向前按 64KB 块找换行符，凑够 n_lines 个就停 ——
        IO 量从"整个文件"降到"尾部几十 KB"。

        二进制模式 + 手工 decode：文本模式的 f.seek(offset) 在多字节
        UTF-8 边界上是未定义行为，二进制块没有这个问题。
        n_lines <= 0 表示全量（保持旧行为，走 readlines）。
        """
        if n_lines is None or n_lines <= 0:
            with open(path, "r", encoding="utf-8") as f:
                return f.readlines()
        try:
            with open(path, "rb") as f:
                f.seek(0, os.SEEK_END)
                end = f.tell()
                want = n_lines + 1          # 尾部可能残缺一行，多要一行兜底
                buf = bytearray()
                pos = end
                found = 0
                while pos > 0 and found < want:
                    step = min(chunk, pos)
                    pos -= step
                    f.seek(pos)
                    block = f.read(step)
                    found += block.count(b"\n")
                    buf[:0] = block         # 前插保持顺序
                text = buf.decode("utf-8", errors="replace")
                lines = text.splitlines()
                # 丢弃首行（可能是被切断的半行）——除非已读到文件头
                if pos > 0 and lines:
                    lines = lines[1:]
                return lines[-n_lines:]
        except Exception:
            return []

    def load(self, peer_id, limit=None):
        """返回消息列表副本（不返回内部缓存对象，避免调用方与缓存共享同一列表）。
        limit 用于懒加载场景（只读最近 N 条），None 表示全量（上限 max）"""
        keep_n = min(limit or self.max, self.max)
        with self._lock:
            cached = self._cache.get(peer_id)
            if cached is not None and self._cache_n.get(peer_id, 0) >= keep_n:
                return list(cached)
        msgs = []
        try:
            tail = self._read_tail(self._path(peer_id), keep_n * 2)
            for line in tail:
                line = line.strip()
                if not line:
                    continue
                try:
                    msgs.append(json.loads(line))
                except Exception:
                    pass
        except Exception:
            pass
        msgs = msgs[-keep_n:]
        # 幽灵传输清理：重启后未完成的传输无法恢复，统一标记为中断
        ACTIVE = ("sending", "started", "progress", "offer", "confirm")
        for m in msgs:
            if m.get("kind") == "file" and m.get("state") in ACTIVE:
                m["state"] = "failed"
                m["reason"] = "应用重启，传输中断"
        with self._lock:
            self._cache[peer_id] = list(msgs)
            self._cache_n[peer_id] = keep_n
        return msgs

    def append(self, peer_id, msg: dict):
        msg.setdefault("ts", _now_ms())
        with self._lock:
            cache = self._cache.setdefault(peer_id, [])
            cache.append(msg)
            if len(cache) > self.max * 2:
                del cache[:self.max]
            try:
                with open(self._path(peer_id), "a", encoding="utf-8") as f:
                    f.write(json.dumps(msg, ensure_ascii=False) + "\n")
                # v1.18.18：写盘后更新 safe->真实id 映射，
                # 否则 all_peer_ids() 只能拿回安全化文件名
                self._index_save()
            except Exception:
                pass

    def clear(self, peer_id: str):
        with self._lock:
            self._cache.pop(peer_id, None)
        try:
            os.remove(self._path(peer_id))
        except Exception:
            pass
        safe = self._safe_name(peer_id) or (
            "id_" + hashlib.md5((peer_id or "").encode("utf-8")).hexdigest())
        if self._index.pop(safe, None) is not None:
            self._index_save()

    def upsert(self, peer_id, msg: dict):
        """★ v1.14.0：就地更新磁盘上已有的一条记录（按 mid / tid 定位）。

        背景：状态变更（sending→ok、progress→done）原先只改内存 dict，
        不写盘 —— 重启后 load 回来又变成"发送中"，用户以为消息没发出去。
        与 append 的区别是覆盖而非追加，不会产生重复行。
        命中失败时退化为 append（宁可多一条，也不丢状态）。
        """
        key_mid = msg.get("mid") or ""
        key_tid = msg.get("tid") or ""
        with self._lock:
            path = self._path(peer_id)
            hit = False
            try:
                if os.path.exists(path):
                    keep = []
                    with open(path, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                o = json.loads(line)
                            except Exception:
                                keep.append(line)
                                continue
                            same = False
                            if key_mid:
                                same = (o.get("mid") or "") == key_mid
                            elif key_tid:
                                same = ((o.get("tid") or "") == key_tid
                                        and o.get("dir") == msg.get("dir")
                                        and o.get("kind") == msg.get("kind"))
                            if same and not hit:
                                keep.append(json.dumps(msg, ensure_ascii=False))
                                hit = True
                            else:
                                keep.append(line)
                    if hit:
                        with open(path, "w", encoding="utf-8") as f:
                            f.write("\n".join(keep) + "\n")
            except Exception:
                hit = False
            # 同步内存缓存里的同一条（保证界面与磁盘一致）
            for x in self._cache.get(peer_id, []):
                if x is msg:
                    continue
                if key_mid and (x.get("mid") or "") == key_mid:
                    x.update(msg)
                    break
                if key_tid and (x.get("tid") or "") == key_tid \
                        and x.get("dir") == msg.get("dir") \
                        and x.get("kind") == msg.get("kind"):
                    x.update(msg)
                    break
        if not hit:
            # 磁盘上没有对应行（例如该条是本次会话新建但还没落盘）→ 追加
            try:
                with self._lock:
                    with open(path, "a", encoding="utf-8") as f:
                        f.write(json.dumps(msg, ensure_ascii=False) + "\n")
            except Exception:
                pass

    def clear_all(self):
        """清空全部聊天记录"""
        try:
            files = os.listdir(self.dir)
        except Exception:
            return
        for fn in files:
            if fn.endswith(".jsonl"):
                try:
                    os.remove(os.path.join(self.dir, fn))
                except Exception:
                    pass
        with self._lock:
            self._cache.clear()

    def purge_orphan_files(self) -> int:
        """★ v1.18.27：删除「失效文件卡片」—— 收到的文件已不在磁盘上的记录。

        成因：用户在资源管理器里删了接收目录里的文件（或清理过接收目录），
        但聊天记录还留着 → 卡片仍显示"已保存"，点开却打不开。
        与安卓端 FdUtil.purgeOrphanFileMsgs 同一口径：
        只看 kind=file / dir=in / state in (done, ok) / path 存在但文件已不在。

        返回删除条数。
        """
        removed = 0
        try:
            files = os.listdir(self.dir)
        except Exception:
            return 0
        for fn in files:
            if not fn.endswith(".jsonl"):
                continue
            path = os.path.join(self.dir, fn)
            try:
                keep = []
                drop = 0
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        s = line.strip()
                        if not s:
                            continue
                        try:
                            o = json.loads(s)
                        except Exception:
                            keep.append(s)
                            continue
                        if (o.get("kind") == "file" and o.get("dir") == "in"
                                and o.get("state") in ("done", "ok")):
                            p = o.get("path") or ""
                            # 没有路径信息 / 文件还在 → 保留（保守，不误删）
                            if p and not os.path.isfile(p):
                                drop += 1
                                continue
                        keep.append(s)
                if not drop:
                    continue
                tmp = path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    for s in keep:
                        f.write(s + "\n")
                os.replace(tmp, path)
                removed += drop
            except Exception:
                continue
        if removed:
            with self._lock:
                self._cache.clear()
        return removed

    def all_peer_ids(self) -> list:
        """历史记录中存在的所有 peer id（**真实 id**，不是文件名）

        ★ 必须还原：文件名是安全化/哈希后的结果，直接当 peer_id 用会错位。
        """
        out = []
        try:
            files = os.listdir(self.dir)
        except Exception:
            return []
        for fn in files:
            if not fn.endswith(".jsonl"):
                continue
            stem = fn[:-6]
            out.append(self._index.get(stem, stem))
        return out

    # ---------------- 消息搜索（v1.18.18） ----------------

    @staticmethod
    def snippet(text: str, kw: str, width=42) -> str:
        """截取命中位置附近的上下文（首尾用… 标示截断）"""
        t = (text or "").replace("\n", " ").replace("\r", " ").strip()
        if not t:
            return ""
        k = (kw or "").strip()
        i = t.lower().find(k.lower()) if k else -1
        if i < 0:
            return t[:width] + ("…" if len(t) > width else "")
        a = max(0, i - width // 2)
        b = min(len(t), i + len(k) + width // 2)
        return ("…" if a > 0 else "") + t[a:b] + ("…" if b < len(t) else "")

    def search(self, keyword: str, peer_ids=None, limit=300,
               scan_limit=5000) -> list:
        """搜索聊天记录，返回 [{peer_id, msg, ts, snippet}]，按时间倒序。

        ★ 设计取舍：
        - **直读 jsonl 文件**而不是走 load()：load() 会把整个文件塞进内存缓存，
          全局搜索遍历所有 peer 时会把全部历史常驻内存（几十万条级别会明显吃内存）。
        - `scan_limit` 限制每个 peer 参与匹配的**尾部条数**，
          避免极端大文件让 UI 卡住（配合 UI 侧工作线程调用）。
        - 命中后**不写入 _cache**：搜索不该改变懒加载状态机。
        """
        kw = (keyword or "").strip()
        if not kw:
            return []
        low = kw.lower()
        try:
            pids = list(peer_ids) if peer_ids else self.all_peer_ids()
        except Exception:
            pids = []
        hits = []
        for pid in pids:
            try:
                with open(self._path(pid), "r", encoding="utf-8") as f:
                    lines = f.readlines()[-scan_limit:]
            except Exception:
                continue
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    m = json.loads(line)
                except Exception:
                    continue
                # 文本消息搜正文，文件消息搜文件名
                hay = m.get("text") or ""
                if not hay:
                    hay = m.get("file") or ""
                if low not in (hay or "").lower():
                    continue
                hits.append({"peer_id": pid, "msg": m,
                             "ts": m.get("ts") or 0,
                             "snippet": self.snippet(hay, kw)})
                if len(hits) >= limit:
                    hits.sort(key=lambda x: x["ts"], reverse=True)
                    return hits
        hits.sort(key=lambda x: x["ts"], reverse=True)
        return hits

    def merge(self, old_id: str, new_id: str):
        """设备身份合并：旧 peer 的聊天记录去重后并入新 peer（跨版本迁移）"""
        if not old_id or not new_id or old_id == new_id:
            return
        with self._lock:
            old_msgs = self._cache.get(old_id)
        if old_msgs is None:
            old_msgs = []
            try:
                with open(self._path(old_id), "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                old_msgs.append(json.loads(line))
                            except Exception:
                                pass
            except Exception:
                pass
        if old_msgs:
            existing = {self.identity(m) for m in self.load(new_id)}
            for m in old_msgs:
                if self.identity(m) not in existing:
                    self.append(new_id, m)
        with self._lock:
            self._cache.pop(old_id, None)
        try:
            os.remove(self._path(old_id))
        except Exception:
            pass

    # ---------------- 按标识删除 ----------------

    @staticmethod
    def identity(m: dict):
        """消息唯一标识：时间 + mid/tid + 方向 + 类型"""
        return (m.get("ts"), m.get("mid") or m.get("tid") or "",
                m.get("dir"), m.get("kind"))

    def delete_by_identities(self, identities: set) -> int:
        """从所有历史文件中删除指定标识的消息，返回删除条数"""
        if not identities:
            return 0
        removed = 0
        try:
            files = os.listdir(self.dir)
        except Exception:
            return 0
        for fn in files:
            if not fn.endswith(".jsonl"):
                continue
            path = os.path.join(self.dir, fn)
            keep = []
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except Exception:
                            continue
                        if self.identity(obj) in identities:
                            removed += 1
                        else:
                            keep.append(line)
            except Exception:
                continue
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write("\n".join(keep) + ("\n" if keep else ""))
            except Exception:
                continue
        # 同步内存缓存
        with self._lock:
            for pid, lst in self._cache.items():
                self._cache[pid] = [m for m in lst
                                    if self.identity(m) not in identities]
        return removed
