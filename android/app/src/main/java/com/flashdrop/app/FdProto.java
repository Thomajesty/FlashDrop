package com.flashdrop.app;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;

/**
 * FlashDrop 协议 v1（与 Windows 端一致，见 PROTOCOL.md）
 *
 * 帧格式: [4 字节大端 长度 L][L 字节 payload]
 * payload[0]: 0x4A 'J' JSON; 0x42 'B' 二进制块 [2B tidLen][tid][8B dataLen][data]
 */
public final class FdProto {
    public static final String APP = "FlashDrop";
    public static final int PROTO_VERSION = 1;
    public static final int DEFAULT_PORT = 58899;
    public static final String MULTICAST_GROUP = "239.255.0.5";
    public static final int CHUNK_SIZE = 512 * 1024;
    /**
     * ★ v1.18.18：帧上限必须按**最大帧头**算。
     * 0x43 比 0x42 多了 4 字节块号，若沿用旧值（1+2+64+8+CHUNK），
     * 编出来的满块帧会被 readFrame 的 `len > MAX_FRAME` 判成协议错误 ——
     * 表现为"大文件一到最后一块就断线"，且只在特定大小才复现，极难定位。
     */
    public static final int MAX_FRAME = 1 + 2 + 64 + 4 + 8 + CHUNK_SIZE;

    public static final byte KIND_JSON = 0x4A;
    public static final byte KIND_BIN = 0x42;
    /**
     * ★ v1.18.18：带序号的分块（断点续传）。
     * 0x42 是"顺序流"语义 —— 接收端只能靠追加写，断线后已收数据无法复用。
     * 0x43 在 tid 与数据之间多一个 4 字节大端块号，接收端据此 seek 写入，
     * 重连后只补发缺失块（真正的断点续传）。
     * 兼容策略：只有双方协商成功（FILE_START 带 idx=1 且 RECV_READY 回 idx=1）
     * 才使用 0x43；否则双方自动退回 0x42 老路径，旧版本互操作不受影响。
     */
    public static final byte KIND_CHUNK = 0x43;

    public static final String T_HELLO = "HELLO";
    public static final String T_DISC = "DISC";
    public static final String T_BYE = "BYE";
    public static final String T_PING = "PING";
    public static final String T_PONG = "PONG";
    public static final String T_TEXT = "TEXT";
    public static final String T_ACK = "ACK";
    public static final String T_FILE_START = "FILE_START";
    public static final String T_RECV_READY = "RECV_READY";
    public static final String T_FILE_END = "FILE_END";
    public static final String T_FILE_OK = "FILE_OK";
    public static final String T_FILE_FAIL = "FILE_FAIL";
    public static final String T_REFUSE = "REFUSE";
    public static final String T_CANCEL = "CANCEL";
    /**
     * ★ v1.16.0：回读确认同步（read-back confirmation）。
     * 接收方落盘后回读文件（存在 + 大小一致），把结果回给发送方，
     * 发送方据此把"已发送"纠正为"已确收"，消除两端状态不一致。
     * 用户主动删除（删消息/清空）不参与本同步。
     */
    public static final String T_SYNC = "SYNC";

    // ================= v1.18.18：断点续传与传输重试 =================
    /**
     * 接收方 -> 发送方：已收到的块位图（断点信息）。
     * v1.18.18 的实现走RECV_READY 的 have 字段承载区间表示，
     * 此常量仅作协议占位，与 Windows 端 protocol.py 保持同名。
     */
    public static final String T_CHUNK_ACK = "CHUNK_ACK";
    /** 发送方 -> 接收方：本次为第 n 次重试（仅用于对端日志/UI）；实际用 FILE_START.attempt */
    public static final String T_RETRY = "RETRY";
    /** 设备备注/别名（name 为备注，空串表示清除）。v1.18.18 **不做自动同步**，仅预留 */
    public static final String T_ALIAS = "ALIAS";

    private FdProto() {}

    private static byte[] frame(byte[] payload) {
        return ByteBuffer.allocate(4 + payload.length)
                .putInt(payload.length).put(payload).array();
    }

    public static byte[] encodeJson(JSONObject o) {
        return frame(join(new byte[]{KIND_JSON},
                o.toString().getBytes(StandardCharsets.UTF_8)));
    }

    private static byte[] join(byte[] a, byte[] b) {
        byte[] r = new byte[a.length + b.length];
        System.arraycopy(a, 0, r, 0, a.length);
        System.arraycopy(b, 0, r, a.length, b.length);
        return r;
    }

    public static byte[] encodeBin(String tid, byte[] data) throws IOException {
        byte[] tb = tid.getBytes(StandardCharsets.UTF_8);
        if (tb.length > 64 || data.length > CHUNK_SIZE)
            throw new IOException("bin frame too large");
        ByteBuffer bb = ByteBuffer.allocate(1 + 2 + tb.length + 8 + data.length);
        bb.put(KIND_BIN).putShort((short) tb.length).put(tb).putLong(data.length).put(data);
        return frame(bb.array());
    }

    /**
     * 编码一个**带块号**的二进制块帧（断点续传用）。
     *
     * <p>格式：[KIND_CHUNK][2 字节 tid 长度][tid][4 字节大端 块号][8 字节大端 长度][数据]
     * 与 0x42 的唯一区别是 tid 之后多一个 4 字节块号 —— 字节布局必须与
     * Windows 端 protocol.encode_chunk 逐字节一致，否则两端无法互通。
     */
    public static byte[] encodeChunk(String tid, int index, byte[] data) throws IOException {
        byte[] tb = tid.getBytes(StandardCharsets.UTF_8);
        if (tb.length > 64 || data.length > CHUNK_SIZE)
            throw new IOException("chunk frame too large");
        if (index < 0) throw new IOException("chunk index negative");
        ByteBuffer bb = ByteBuffer.allocate(1 + 2 + tb.length + 4 + 8 + data.length);
        bb.put(KIND_CHUNK).putShort((short) tb.length).put(tb)
          .putInt(index).putLong(data.length).put(data);
        return frame(bb.array());
    }

    public static byte[] discPacket(String id, String name, String platform, int tcpPort) {
        return discPacket(id, name, platform, tcpPort, "", "");
    }

    /** host: 设备唯一标识（跨版本身份合并用）；altId: 旧版本使用过的设备 ID */
    public static byte[] discPacket(String id, String name, String platform, int tcpPort,
                                    String host, String altId) {
        try {
            JSONObject o = new JSONObject();
            o.put("app", APP);
            o.put("v", PROTO_VERSION);
            o.put("type", T_DISC);
            o.put("id", id);
            o.put("name", name);
            o.put("platform", platform);
            o.put("tcp", tcpPort);
            if (host != null && !host.isEmpty()) o.put("host", host);
            if (altId != null && !altId.isEmpty()) o.put("alt", new JSONArray().put(altId));
            return o.toString().getBytes(StandardCharsets.UTF_8);
        } catch (Exception e) {
            return new byte[0];
        }
    }

    /** 返回 Object[3]: [0]=kind(Byte), [1]=JSONObject 或 tid(String), [2]=data(byte[] 或 null) */
    public static Object[] readFrame(DataInputStream in) throws IOException {
        byte[] h = new byte[4];
        in.readFully(h);
        int len = ((h[0] & 255) << 24) | ((h[1] & 255) << 16) | ((h[2] & 255) << 8) | (h[3] & 255);
        if (len <= 1 || len > MAX_FRAME) throw new IOException("bad frame length " + len);
        byte[] payload = new byte[len];
        in.readFully(payload);
        byte kind = payload[0];
        if (kind == KIND_JSON) {
            try {
                JSONObject o = new JSONObject(new String(payload, 1, len - 1, StandardCharsets.UTF_8));
                return new Object[]{KIND_JSON, o, null};
            } catch (Exception e) {
                throw new IOException("bad json frame");
            }
        } else if (kind == KIND_BIN) {
            if (len < 1 + 2 + 1 + 8) throw new IOException("bin frame short");
            int n = ((payload[1] & 255) << 8) | (payload[2] & 255);
            if (len < 1 + 2 + n + 8) throw new IOException("bin tid short");
            String tid = new String(payload, 3, n, StandardCharsets.UTF_8);
            long m = 0;
            for (int i = 0; i < 8; i++) m = (m << 8) | (payload[3 + n + i] & 255);
            // 上界校验：块长度不能超过本帧实际剩余字节，否则会 NegativeArraySize/OOM
            if (m < 0 || m > len - 3 - n - 8) throw new IOException("bad chunk length " + m);
            byte[] data = new byte[(int) m];
            System.arraycopy(payload, 3 + n + 8, data, 0, (int) m);
            return new Object[]{KIND_BIN, tid, data};
        } else if (kind == KIND_CHUNK) {
            // ★ v1.18.18：[KIND][2B n][tid][4B index][8B m][data]
            //   比 0x42 多一个 4 字节块号，所有偏移量从 3+n 变成 7+n。
            if (len < 1 + 2 + 1 + 4 + 8) throw new IOException("chunk frame short");
            int n = ((payload[1] & 255) << 8) | (payload[2] & 255);
            if (len < 1 + 2 + n + 4 + 8) throw new IOException("chunk tid short");
            String tid = new String(payload, 3, n, StandardCharsets.UTF_8);
            long idx = 0;
            for (int i = 0; i < 4; i++) idx = (idx << 8) | (payload[3 + n + i] & 255);
            long m = 0;
            for (int i = 0; i < 8; i++) m = (m << 8) | (payload[7 + n + i] & 255);
            // 上界校验：块长度不能超过本帧实际剩余字节，否则会 NegativeArraySize/OOM
            if (m < 0 || m > len - 7 - n - 8) throw new IOException("bad chunk length " + m);
            byte[] data = new byte[(int) m];
            System.arraycopy(payload, 7 + n + 8, data, 0, (int) m);
            // ★ [1] 放 Object[]{tid, index}，与 Windows 端
            //   protocol.read_frame 返回 (tid, idx) 元组对齐。
            //   调用方 readerLoop 必须按 kind 分支取，不能直接当 String 强转。
            return new Object[]{KIND_CHUNK, new Object[]{tid, (int) idx}, data};
        }
        throw new IOException("unknown frame kind " + kind);
    }

    /** 解析 UDP DISC 报文，非法返回 null */
    public static JSONObject parseDisc(byte[] data) {
        try {
            JSONObject o = new JSONObject(new String(data, StandardCharsets.UTF_8));
            if (APP.equals(o.optString("app")) && T_DISC.equals(o.optString("type"))
                    && o.optString("id").length() > 0)
                return o;
        } catch (Exception ignored) {}
        return null;
    }

    /** 简单 JSON 构造 */
    public static JSONObject obj(Object... kv) {
        JSONObject o = new JSONObject();
        for (int i = 0; i + 1 < kv.length; i += 2) {
            try { o.put((String) kv[i], kv[i + 1]); } catch (Exception ignored) {}
        }
        return o;
    }
}
