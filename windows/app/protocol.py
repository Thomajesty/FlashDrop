# -*- coding: utf-8 -*-
"""FlashDrop 协议 v1：帧编解码与消息常量。

帧格式（TCP 流）:
    [4 字节大端 长度 L][L 字节 payload]
payload 第 1 字节为类型:
    0x4A 'J' -> JSON 消息（UTF-8）
    0x42 'B' -> 二进制块: [2字节 tid 长度 n][n 字节 tid][8字节大端 数据长度 m][m 字节数据]
"""

import json
import struct

APP = "FlashDrop"
PROTO_VERSION = 1
DEFAULT_PORT = 58899
MULTICAST_GROUP = "239.255.0.5"

CHUNK_SIZE = 512 * 1024          # 单个二进制块数据上限
MAX_FRAME = 1 + 2 + 64 + 4 + 8 + CHUNK_SIZE   # 帧大小上限（按最大帧头算）
MAX_JSON = 16 * 1024 * 1024      # 单条 JSON 上限（保护）

KIND_JSON = 0x4A
KIND_BIN = 0x42
# ★ v1.18.18：带序号的分块（断点续传）。
# 0x42 是"顺序流"语义 —— 接收端只能靠追加写，断线后已收的数据无法复用。
# 0x43 在 tid 与数据之间多一个 4 字节大端块号，接收端据此 seek 写入，
# 重连后只补发缺失块（真正的断点续传）。
# 兼容策略：只有双方协商成功（FILE_START 带 idx=1 且 RECV_READY 回 idx=1）
# 才使用 0x43；否则双方自动退回 0x42 老路径，旧版本互操作不受影响。
KIND_CHUNK = 0x43

# JSON 消息类型
T_HELLO = "HELLO"
T_DISC = "DISC"
T_BYE = "BYE"
T_PING = "PING"
T_PONG = "PONG"
T_TEXT = "TEXT"
T_ACK = "ACK"
T_FILE_START = "FILE_START"
T_RECV_READY = "RECV_READY"
T_FILE_END = "FILE_END"
T_FILE_OK = "FILE_OK"
T_FILE_FAIL = "FILE_FAIL"
T_REFUSE = "REFUSE"
T_CANCEL = "CANCEL"

# ★ v1.18.18：断点续传与传输重试
T_CHUNK_ACK = "CHUNK_ACK"   # 接收方 -> 发送方：已收到的块位图（断点信息）
T_RETRY = "RETRY"           # 发送方 -> 接收方：本次为第 n 次重试（仅用于对端日志/UI）
T_ALIAS = "ALIAS"           # 双向：设备备注/别名（name 为备注，空串表示清除）

# ★ v1.16.0：回读确认同步（read-back confirmation）。
# 传输双方都在线时，接收方在落盘后回读一次文件（存在 + 大小一致），
# 把结果随 FILE_OK 一起回给发送方；发送方据此把状态从"已发送"纠正为
# "已确收"。用于消除"发送端显示已发送、接收端其实失败"的不一致。
# 主动删除（用户手动删消息/清空）不参与本同步 —— 那是用户意图，不是传输异常。
T_SYNC = "SYNC"          # 接收方 -> 发送方：回读确认结果


class ProtocolError(Exception):
    pass


def encode_json(obj: dict) -> bytes:
    """编码一条 JSON 消息为完整帧"""
    body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) + 1 > MAX_JSON:
        raise ProtocolError("json too large")
    payload = bytes([KIND_JSON]) + body
    return struct.pack(">I", len(payload)) + payload


def encode_bin(tid: str, data: bytes) -> bytes:
    """编码一个二进制块帧"""
    if len(data) > CHUNK_SIZE:
        raise ProtocolError("chunk too large")
    tb = tid.encode("utf-8")
    if len(tb) > 64:
        raise ProtocolError("tid too long")
    payload = (bytes([KIND_BIN]) + struct.pack(">H", len(tb)) + tb
               + struct.pack(">Q", len(data)) + data)
    return struct.pack(">I", len(payload)) + payload


def encode_chunk(tid: str, index: int, data: bytes) -> bytes:
    """编码一个**带块号**的二进制块帧（断点续传用）。

    格式：[KIND_CHUNK][2 字节 tid 长度][tid][4 字节大端 块号][8 字节大端 长度][数据]
    """
    if len(data) > CHUNK_SIZE:
        raise ProtocolError("chunk too large")
    tb = tid.encode("utf-8")
    if len(tb) > 64:
        raise ProtocolError("tid too long")
    payload = (bytes([KIND_CHUNK]) + struct.pack(">H", len(tb)) + tb
               + struct.pack(">I", index)
               + struct.pack(">Q", len(data)) + data)
    return struct.pack(">I", len(payload)) + payload


def encode_disc_msg(dev_id: str, name: str, platform: str, tcp_port: int,
                    host: str = "", alt_ids=None) -> bytes:
    """构造 UDP DISC 数据报（无帧头，直接 JSON）。
    host: 设备唯一标识（主机名/ANDROID_ID 派生），供对端合并同机多版本身份；
    alt_ids: 该设备历史版本使用过的旧 ID 列表。旧版忽略未知字段，向前兼容。"""
    obj = {"app": APP, "v": PROTO_VERSION, "type": T_DISC, "id": dev_id,
           "name": name, "platform": platform, "tcp": tcp_port}
    if host:
        obj["host"] = host
    if alt_ids:
        obj["alt"] = list(alt_ids)
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


async def read_frame(reader) -> tuple:
    """从 asyncio StreamReader 读取一帧，返回 (kind, a, b)。

    kind == KIND_JSON 时: (KIND_JSON, dict, None)
    kind == KIND_BIN  时: (KIND_BIN, tid_str, bytes)
    kind == KIND_CHUNK 时: (KIND_CHUNK, (tid_str, index), bytes)
                         —— a 是 (tid, 块号) 元组，调用方据此 seek 写入实现断点续传
    流结束时抛 asyncio.IncompleteReadError / 返回 None（调用方处理）
    """
    hdr = await reader.readexactly(4)
    (length,) = struct.unpack(">I", hdr)
    if length <= 1 or length > MAX_FRAME:
        raise ProtocolError(f"bad frame length {length}")
    payload = await reader.readexactly(length)
    kind = payload[0]
    if kind == KIND_JSON:
        obj = json.loads(payload[1:].decode("utf-8"))
        if not isinstance(obj, dict):
            raise ProtocolError("json not object")
        return KIND_JSON, obj, None
    elif kind == KIND_BIN:
        if length < 1 + 2 + 1 + 8:
            raise ProtocolError("bin frame too short")
        (n,) = struct.unpack(">H", payload[1:3])
        if length < 1 + 2 + n + 8:
            raise ProtocolError("bin frame truncated")
        tid = payload[3:3 + n].decode("utf-8", "replace")
        (m,) = struct.unpack(">Q", payload[3 + n:3 + n + 8])
        data = payload[3 + n + 8:]
        if len(data) != m:
            raise ProtocolError("bin length mismatch")
        return KIND_BIN, tid, data
    elif kind == KIND_CHUNK:
        # [KIND][2B n][tid][4B index][8B m][data]
        if length < 1 + 2 + 1 + 4 + 8:
            raise ProtocolError("chunk frame too short")
        (n,) = struct.unpack(">H", payload[1:3])
        if length < 1 + 2 + n + 4 + 8:
            raise ProtocolError("chunk frame truncated")
        tid = payload[3:3 + n].decode("utf-8", "replace")
        (idx,) = struct.unpack(">I", payload[3 + n:3 + n + 4])
        (m,) = struct.unpack(">Q", payload[7 + n:7 + n + 8])
        data = payload[7 + n + 8:]
        if len(data) != m:
            raise ProtocolError("chunk length mismatch")
        return KIND_CHUNK, (tid, idx), data
    else:
        raise ProtocolError(f"unknown frame kind 0x{kind:02x}")


def parse_disc(data: bytes):
    """解析 UDP DISC 数据报，非法返回 None"""
    try:
        obj = json.loads(data.decode("utf-8"))
        if (isinstance(obj, dict) and obj.get("app") == APP
                and obj.get("type") == T_DISC and obj.get("id")):
            return obj
    except Exception:
        pass
    return None
