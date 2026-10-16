import java.io.ByteArrayInputStream;
import java.io.DataInputStream;
import java.io.IOException;

import org.json.JSONObject;

import com.flashdrop.app.FdProto;
import com.flashdrop.app.FdResume;

/**
 * v1.18.18 —— Android 端协议帧（0x43 带块号分块）测试
 *
 * ★ 最关键的是**与 Windows 端逐字节一致**：两端协议字节布局不同就完全没法互通。
 * 下面的 hex 基准值都是从 windows/app/protocol.py 实跑出来的，不是手算的。
 *
 * 运行见 tools/run_rt11818_proto.sh
 */
public class RT11818Proto {

    static int pass = 0, fail = 0;

    static void check(String name, boolean ok, String extra) {
        if (ok) {
            pass++;
            System.out.println("  PASS  " + name);
        } else {
            fail++;
            System.out.println("  FAIL  " + name
                    + (extra != null && !extra.isEmpty() ? "   " + extra : ""));
        }
    }

    static void check(String name, boolean ok) {
        check(name, ok, null);
    }

    static void eqm(String name, Object a, Object b) {
        boolean ok = String.valueOf(a).equals(String.valueOf(b));
        check(name, ok, ok ? "" : "期望=[" + b + "] 实际=[" + a + "]");
    }

    static void sec(String s) {
        System.out.println("\n=== " + s + " ===");
    }

    static String hex(byte[] b) {
        StringBuilder sb = new StringBuilder();
        for (byte x : b) sb.append(String.format("%02x", x));
        return sb.toString();
    }

    static Object[] read(byte[] frame) throws IOException {
        return FdProto.readFrame(new DataInputStream(new ByteArrayInputStream(frame)));
    }

    /** 取 payload（去掉 4 字节长度头） */
    static byte[] payloadOf(byte[] frame) {
        byte[] p = new byte[frame.length - 4];
        System.arraycopy(frame, 4, p, 0, p.length);
        return p;
    }

    public static void main(String[] args) throws Exception {
        System.out.println("========================================");
        System.out.println(" RT11818-Proto 0x43 帧编解码测试");
        System.out.println("========================================");

        // ---------------- 常量 ----------------
        sec("协议常量");
        eqm("KIND_CHUNK = 0x43", FdProto.KIND_CHUNK, (byte) 0x43);
        eqm("KIND_BIN = 0x42", FdProto.KIND_BIN, (byte) 0x42);
        eqm("KIND_JSON = 0x4A", FdProto.KIND_JSON, (byte) 0x4A);
        // ★ MAX_FRAME 必须容纳 0x43 的最大帧头（多 4 字节块号）
        eqm("MAX_FRAME 容纳新帧头",
                FdProto.MAX_FRAME, 1 + 2 + 64 + 4 + 8 + FdProto.CHUNK_SIZE);
        check("MAX_FRAME 比 0x42 的头部大 4 字节",
                FdProto.MAX_FRAME > 1 + 2 + 64 + 8 + FdProto.CHUNK_SIZE);
        check("预留了 T_CHUNK_ACK", FdProto.T_CHUNK_ACK != null
                && FdProto.T_CHUNK_ACK.equals("CHUNK_ACK"));
        check("预留了 T_RETRY", FdProto.T_RETRY != null
                && FdProto.T_RETRY.equals("RETRY"));
        check("预留了 T_ALIAS", FdProto.T_ALIAS != null
                && FdProto.T_ALIAS.equals("ALIAS"));

        // ---------------- 跨端字节一致性（最关键） ----------------
        sec("★ 与 Windows 端逐字节一致");
        // 基准来自：python -c "protocol.encode_chunk('t1', 7, b'hello')[4:].hex()"
        byte[] hello = "hello".getBytes("UTF-8");
        byte[] f1 = FdProto.encodeChunk("t1", 7, hello);
        eqm("chunk 帧 payload hex 与 Python 端一致",
                hex(payloadOf(f1)), "430002743100000007000000000000000568656c6c6f");
        eqm("总帧长与 Python 端一致（26）", f1.length, 26);
        // 0x42 老帧不受影响
        byte[] b1 = FdProto.encodeBin("t1", hello);
        eqm("老帧 payload hex 与 Python 端一致",
                hex(payloadOf(b1)), "4200027431000000000000000568656c6c6f");
        eqm("老帧长度与 Python 端一致（22）", b1.length, 22);

        // ---------------- 解码往返 ----------------
        sec("chunk 帧解码往返");
        Object[] r = read(f1);
        eqm("kind 正确", r[0], FdProto.KIND_CHUNK);
        check("[1] 是 Object[]（与 Python 元组对齐）", r[1] instanceof Object[],
                String.valueOf(r[1] == null ? "null" : r[1].getClass()));
        Object[] ti = (Object[]) r[1];
        eqm("tid 正确", ti[0], "t1");
        eqm("块号正确", ti[1], 7);
        eqm("数据正确", new String((byte[]) r[2], "UTF-8"), "hello");

        // 块号 0 与大块号
        Object[] r0 = read(FdProto.encodeChunk("x", 0, new byte[]{1, 2, 3}));
        eqm("块号 0 往返", ((Object[]) r0[1])[1], 0);
        eqm("块号 0 数据", ((byte[]) r0[2]).length, 3);
        Object[] rBig = read(FdProto.encodeChunk("tid-long", 1000000, new byte[]{9}));
        eqm("大块号往返", ((Object[]) rBig[1])[1], 1000000);
        eqm("长 tid 往返", ((Object[]) rBig[1])[0], "tid-long");

        // 空数据块（不应崩溃）
        Object[] rEmpty = read(FdProto.encodeChunk("t", 1, new byte[0]));
        eqm("空数据块往返长度", ((byte[]) rEmpty[2]).length, 0);

        // 满块（用真 MAX_FRAME 边界验证）
        byte[] full = new byte[FdProto.CHUNK_SIZE];
        java.util.Arrays.fill(full, (byte) 0x5A);
        byte[] fFull = FdProto.encodeChunk("t", 5, full);
        check("满块帧长度 == MAX_FRAME",
                fFull.length == 4 + 1 + 2 + 1 + 4 + 8 + FdProto.CHUNK_SIZE,
                "len=" + fFull.length);
        Object[] rFull = read(fFull);
        eqm("满块数据长度", ((byte[]) rFull[2]).length, FdProto.CHUNK_SIZE);
        eqm("满块数据首字节", ((byte[]) rFull[2])[0], (byte) 0x5A);
        eqm("满块末字节", ((byte[]) rFull[2])[FdProto.CHUNK_SIZE - 1], (byte) 0x5A);

        // ---------------- 老帧不受影响 ----------------
        sec("老帧（0x42 / JSON）互操作");
        Object[] rb = read(b1);
        eqm("老帧 kind", rb[0], FdProto.KIND_BIN);
        eqm("老帧 tid", rb[1], "t1");
        eqm("老帧数据", new String((byte[]) rb[2], "UTF-8"), "hello");
        check("老帧 [1] 仍是 String（不是 Object[]）", rb[1] instanceof String);

        JSONObject o = FdProto.obj("type", "TEXT", "mid", "m1", "text", "你好");
        Object[] rj = read(FdProto.encodeJson(o));
        eqm("JSON 帧 kind", rj[0], FdProto.KIND_JSON);
        eqm("JSON type", ((JSONObject) rj[1]).optString("type"), "TEXT");
        eqm("JSON 中文不乱码", ((JSONObject) rj[1]).optString("text"), "你好");
        check("JSON 帧 [2] 为 null", rj[2] == null);

        // 连续多帧（模拟真实流）
        sec("连续多帧");
        java.io.ByteArrayOutputStream bos = new java.io.ByteArrayOutputStream();
        bos.write(FdProto.encodeJson(FdProto.obj("type", "FILE_START", "tid", "T", "idx", 1)));
        for (int i = 0; i < 4; i++) {
            bos.write(FdProto.encodeChunk("T", i, new byte[]{(byte) i, 1, 2}));
        }
        bos.write(FdProto.encodeJson(FdProto.obj("type", "FILE_END", "tid", "T")));
        DataInputStream din = new DataInputStream(new ByteArrayInputStream(bos.toByteArray()));
        int gotChunk = 0, gotJson = 0;
        boolean order_ok = true;
        int expectIdx = 0;
        while (din.available() > 0) {
            Object[] fr = FdProto.readFrame(din);
            if ((Byte) fr[0] == FdProto.KIND_CHUNK) {
                gotChunk++;
                Object[] ti2 = (Object[]) fr[1];
                if ((Integer) ti2[1] != expectIdx) order_ok = false;
                expectIdx++;
            } else {
                gotJson++;
            }
        }
        eqm("连读 JSON 帧数", gotJson, 2);
        eqm("连读 chunk 帧数", gotChunk, 4);
        check("块号按 0..3 顺序到达", order_ok);

        // ---------------- 非法输入 ----------------
        sec("非法帧必须抛异常（不能静默）");
        // 未知 kind
        try {
            read(new byte[]{0, 0, 0, 2, (byte) 0x99, 0});
            check("未知 kind 抛异常", false, "未抛");
        } catch (IOException e) {
            check("未知 kind 抛异常", true);
        }
        // 长度超上限
        try {
            read(new byte[]{(byte) 0x7F, (byte) 0xFF, (byte) 0xFF, (byte) 0xFF, 0});
            check("超长帧抛异常", false, "未抛");
        } catch (IOException e) {
            check("超长帧抛异常", true);
        }
        // 长度 0
        try {
            read(new byte[]{0, 0, 0, 0});
            check("长度 0 抛异常", false, "未抛");
        } catch (IOException e) {
            check("长度 0 抛异常", true);
        }
        // chunk 声明长度超过帧内实际字节（防 OOM）
        try {
            byte[] bad = FdProto.encodeChunk("t", 0, new byte[10]);
            // 篡改 m 为超大值
            int n = 1;
            byte[] p = payloadOf(bad);
            for (int i = 7 + n; i < 15 + n; i++) p[i] = (byte) 0x7F;
            byte[] frame2 = new byte[4 + p.length];
            System.arraycopy(p, 0, frame2, 4, p.length);
            frame2[0] = (byte) ((p.length >> 24) & 255);
            frame2[1] = (byte) ((p.length >> 16) & 255);
            frame2[2] = (byte) ((p.length >> 8) & 255);
            frame2[3] = (byte) (p.length & 255);
            read(frame2);
            check("块长超界抛异常（防 OOM）", false, "未抛");
        } catch (IOException e) {
            check("块长超界抛异常（防 OOM）", true);
        }
        // encode 参数校验
        try {
            FdProto.encodeChunk("t", -1, new byte[1]);
            check("负块号抛异常", false, "未抛");
        } catch (IOException e) {
            check("负块号抛异常", true);
        }
        try {
            FdProto.encodeChunk("t", 0, new byte[FdProto.CHUNK_SIZE + 1]);
            check("超长块抛异常", false, "未抛");
        } catch (IOException e) {
            check("超长块抛异常", true);
        }
        // tid 过长
        try {
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < 70; i++) sb.append('x');
            FdProto.encodeChunk(sb.toString(), 0, new byte[1]);
            check("tid 过长抛异常", false, "未抛");
        } catch (IOException e) {
            check("tid 过长抛异常", true);
        }

        System.out.println("\n========================================");
        System.out.println("RT11818-Proto：通过 " + pass + " 项，失败 " + fail + " 项");
        System.out.println("========================================");
        System.exit(fail > 0 ? 1 : 0);
    }
}