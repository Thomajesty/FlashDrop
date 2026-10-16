# -*- coding: utf-8 -*-
"""FlashDrop 断点续传核心：块位图（chunk bitmap）与分块规划。

设计要点
--------
1. **纯算法、零 IO**：本模块只负责"哪些块还需要传"的判断，
   落盘/回读由node.py / FlashNode.java 各自实现（两端文件访问方式不同）。
   这样位图逻辑可以独立跑 JVM / Python 测试，不必起真实网络。

2. **固定块长**：块长 RESUME_CHUNK 固定，因此"块号 -> 文件偏移"是纯乘法，
   接收端可以 seek 到任意块，无需顺序写。大文件与顺序写同等效率。

3. **接收端预留空间**：预分配 size 大小的 .part 文件，
   收到的块直接 seek 写入。位图单独持久化（<cache>/<tid>.bmp）。

4. **末块可短**：最后一个块长度 = size - (n-1)*CHUNK，其余块满长。
   位图里"已收到"即代表该块已落盘；总字节数由块号推导，不依赖累加。

与 Android 端 FdResume.java 保持完全相同的算法与文件名，
保证两端互相重连时能识别对方的续传状态。
"""

import base64
import hashlib
import os

RESUME_CHUNK = 512 * 1024       # 与 protocol.CHUNK_SIZE 一致
RESUME_VERSION = 1


def total_chunks(size: int) -> int:
    """总块数（size=0 视为 1 块，避免除零与"零块"歧义）"""
    if size <= 0:
        return 1
    return (size + RESUME_CHUNK - 1) // RESUME_CHUNK


def chunk_offset(index: int) -> int:
    """块号 -> 文件偏移"""
    return index * RESUME_CHUNK


def chunk_len(index: int, size: int) -> int:
    """块号 -> 该块应有长度（末块可能不足满块）"""
    off = chunk_offset(index)
    if size <= 0:
        return 0
    return min(RESUME_CHUNK, size - off)


def _b64_pad(s: str) -> str:
    """补齐 base64 填充（=）。

    ★ Android 端 FdResume.B64.encode() 输出**带填充**，
      而 Python 的 base64.b64decode 对**无填充**输入直接抛
      `binascii.Error: Incorrect padding`。若两端任何一方发出无填充串，
      对方就解不出来（表现为"对方说没收到任何块，续传退化成全量重传"）。
      这里做防御性补齐，两种形式都能吃。
    """
    s = (s or "").strip()
    r = len(s) % 4
    if r == 0:
        return s
    if r == 1:          # 非法长度，直接原样返回让解码器报错
        return s
    return s + "=" * (4 - r)


class ChunkMap:
    """块位图：第 i 位表示第 i 块是否已收到。内部用 bytearray 存位。"""

    __slots__ = ("n", "_bits")

    def __init__(self, n: int):
        self.n = max(1, int(n))
        self._bits = bytearray((self.n + 7) // 8)

    # ---------- 基本操作 ----------

    def has(self, i: int) -> bool:
        if i < 0 or i >= self.n:
            return False
        return bool(self._bits[i >> 3] & (1 << (i & 7)))

    def add(self, i: int) -> bool:
        """标记已收到；返回 True 表示这是**新**块（重复块返回 False）"""
        if i < 0 or i >= self.n:
            return False
        byte = i >> 3
        mask = 1 << (i & 7)
        if self._bits[byte] & mask:
            return False
        self._bits[byte] |= mask
        return True

    def count(self) -> int:
        return sum(bin(b).count("1") for b in self._bits)

    def complete(self) -> bool:
        return self.count() >= self.n

    def received_bytes(self, size: int) -> int:
        """已落盘字节数（按块号推导，不做累加，避免计数漂移）"""
        tot = 0
        for i in range(self.n):
            if self.has(i):
                tot += chunk_len(i, size)
        return tot

    def missing(self) -> list:
        """缺失块号列表（升序）"""
        return [i for i in range(self.n) if not self.has(i)]

    # ---------- 序列化（跨进程 / 跨端共享） ----------

    def to_b64(self) -> str:
        """base64 位图。

        ★ **带 '=' 填充**（与 Android 端 FdResume.B64.encode 一致）：
          Python 的 b64decode 不接受无填充串，统一成有填充才能跨端互解。
        """
        return base64.b64encode(bytes(self._bits)).decode("ascii")

    @staticmethod
    def from_b64(s: str, n: int) -> "ChunkMap":
        cm = ChunkMap(n)
        try:
            raw = base64.b64decode(_b64_pad(s or "").encode("ascii"),
                                   validate=False)
        except Exception:
            return cm
        m = min(len(raw), len(cm._bits))
        for k in range(m):
            cm._bits[k] = raw[k]
        # 超出 n 的多余位清零，避免 count() 多算
        extra = cm.n
        if extra & 7:
            cm._bits[extra >> 3] &= (1 << (extra & 7)) - 1
        return cm

    def to_compact(self) -> list:
        """紧凑区间表示：[[0,12],[15,15]] —— 连续已收块合并。

        大多数情况是"前 n 块已收"，区间表示只有 1 项，
        JSON 体积远小于base64 位图；用于 CHUNK_ACK 报文与 UI 展示。
        """
        out = []
        start = -1
        for i in range(self.n):
            if self.has(i):
                if start < 0:
                    start = i
            elif start >= 0:
                out.append([start, i - 1])
                start = -1
        if start >= 0:
            out.append([start, self.n - 1])
        return out

    @staticmethod
    def from_compact(ranges, n: int) -> "ChunkMap":
        cm = ChunkMap(n)
        for r in (ranges or []):
            try:
                a, b = int(r[0]), int(r[1])
            except Exception:
                continue
            for i in range(max(0, a), min(cm.n - 1, b) + 1):
                cm.add(i)
        return cm

    # ---------- 落盘 ----------

    @staticmethod
    def path_for(cache_dir: str, tid: str) -> str:
        return os.path.join(cache_dir, tid + ".bmp")

    def save(self, cache_dir: str, tid: str) -> bool:
        """位图落盘（原子写：tmp + replace），断电/崩溃不产生半截位图"""
        try:
            os.makedirs(cache_dir, exist_ok=True)
            p = self.path_for(cache_dir, tid)
            tmp = p + ".tmp"
            with open(tmp, "wb") as f:
                f.write(self._bits)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, p)
            return True
        except Exception:
            return False

    @staticmethod
    def load(cache_dir: str, tid: str, n: int) -> "ChunkMap":
        """读回位图；文件不存在/损坏/长度不符一律按"全缺"处理（安全重传）"""
        try:
            p = ChunkMap.path_for(cache_dir, tid)
            with open(p, "rb") as f:
                raw = f.read()
            cm = ChunkMap(n)
            m = min(len(raw), len(cm._bits))
            cm._bits[:m] = raw[:m]
            extra = cm.n
            if extra & 7:
                cm._bits[extra >> 3] &= (1 << (extra & 7)) - 1
            return cm
        except Exception:
            return ChunkMap(n)


def resume_fingerprint(size: int, name: str) -> str:
    """续传指纹：文件大小 + 名称的短摘要。

    用途：接收端重启后校验"这个 .part 是不是同一个文件的残留"，
    防止同名不同内容的文件被错误拼接（那会得到一个损坏文件）。
    """
    return hashlib.md5(f"{int(size)}|{name or ''}".encode("utf-8")).hexdigest()[:16]


def fp_path(cache_dir: str, tid: str) -> str:
    return os.path.join(cache_dir, tid + ".fp")


def save_fingerprint(cache_dir: str, tid: str, size: int, name: str) -> bool:
    try:
        os.makedirs(cache_dir, exist_ok=True)
        p = fp_path(cache_dir, tid)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(resume_fingerprint(size, name))
        os.replace(tmp, p)
        return True
    except Exception:
        return False


def load_fingerprint(cache_dir: str, tid: str) -> str:
    try:
        with open(fp_path(cache_dir, tid), "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def drop_resume_state(cache_dir: str, tid: str):
    """传输成功/取消/拒绝后清理位图与指纹（.part 由调用方处理）"""
    for p in (ChunkMap.path_for(cache_dir, tid), fp_path(cache_dir, tid)):
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass


def next_backoff(attempt: int, base=1.5, cap=30.0) -> float:
    """指数退避：1.5, 2.25, 3.4 ... 上限 cap 秒。attempt 从 1 开始。"""
    try:
        a = max(1, int(attempt))
    except Exception:
        a = 1
    return float(min(cap, base ** a))