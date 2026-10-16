package com.flashdrop.app;

import java.io.File;
import java.io.FileOutputStream;
import java.io.RandomAccessFile;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.List;

/**
 * FlashDrop 断点续传核心：块位图（chunk bitmap）与分块规划。
 *
 * <p>与 Windows 端 {@code windows/app/resume.py} 是**逐行对应的同一套算法**，
 * 且文件名（.part/.bmp/.fp）与位图字节布局完全一致，
 * 保证两端互相重连时能识别对方的续传状态。
 *
 * <p>设计要点：
 * <ol>
 *   <li><b>固定块长</b>：块长 RESUME_CHUNK 固定，因此"块号 -> 文件偏移"是纯乘法，
 *       接收端可以 seek 到任意块，无需顺序写。大文件与顺序写同等效率。</li>
 *   <li><b>位图单独持久化</b>：.part 只存数据，.bmp 存"哪些块已落盘"。
 *       两者分离的好处是 .part 只需 truncate 一次，后续块直接 seek 覆盖。</li>
 *   <li><b>末块可短</b>：最后一个块长度 = size - (n-1)*CHUNK。
 *       位图里"已收到"即代表该块已落盘；总字节数由块号推导，不依赖累加
 *       —— 累加会在收到重复块时漂移。</li>
 * </ol>
 */
public class FdResume {

    /** 块长：与 FdProto.CHUNK_SIZE 一致 */
    public static final int RESUME_CHUNK = 512 * 1024;
    public static final int RESUME_VERSION = 1;

    private FdResume() {
    }

    /** 总块数（size=0 视为 1 块，避免除零与"零块"歧义） */
    public static int totalChunks(long size) {
        if (size <= 0) return 1;
        long n = (size + RESUME_CHUNK - 1) / RESUME_CHUNK;
        return (int) Math.max(1, Math.min(n, Integer.MAX_VALUE));
    }

    /** 块号 -> 文件偏移 */
    public static long chunkOffset(int index) {
        return (long) index * RESUME_CHUNK;
    }

    /** 块号 -> 该块应有长度（末块可能不足满块） */
    public static int chunkLen(int index, long size) {
        long off = chunkOffset(index);
        if (size <= 0) return 0;
        long len = Math.min((long) RESUME_CHUNK, size - off);
        return (int) Math.max(0, len);
    }

    /**
 * Base64 编解码（位图在 JSON 里的紧凑表示）。
 *
 * <p>为什么不直接用 android.util.Base64：单元测试跑在 JDK 上（android.jar 里
 * 的方法体全是 {@code throw new RuntimeException("Stub!")}），直接用会崩。
 * 这里内联一份纯 Java 实现（RFC 4648 标准字母表），
 * 字节层面与 android.util.Base64 完全等价，且两端（Python/Java）互相可解。
 */
static final class B64 {
        private static final char[] TBL =
                "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
                        .toCharArray();

        private B64() {
        }

        static String encode(byte[] in) {
            if (in == null || in.length == 0) return "";
            StringBuilder sb = new StringBuilder(((in.length + 2) / 3) * 4);
            int i = 0;
            for (; i + 2 < in.length; i += 3) {
                int v = ((in[i] & 255) << 16) | ((in[i + 1] & 255) << 8) | (in[i + 2] & 255);
                sb.append(TBL[(v >> 18) & 63]).append(TBL[(v >> 12) & 63])
                        .append(TBL[(v >> 6) & 63]).append(TBL[v & 63]);
            }
            int rem = in.length - i;
            if (rem == 1) {
                int v = (in[i] & 255) << 16;
                sb.append(TBL[(v >> 18) & 63]).append(TBL[(v >> 12) & 63]).append("==");
            } else if (rem == 2) {
                int v = ((in[i] & 255) << 16) | ((in[i + 1] & 255) << 8);
                sb.append(TBL[(v >> 18) & 63]).append(TBL[(v >> 12) & 63])
                        .append(TBL[(v >> 6) & 63]).append('=');
            }
            return sb.toString();
        }

        static byte[] decode(String s) {
            if (s == null || s.isEmpty()) return new byte[0];
            int[] rev = new int[128];
            java.util.Arrays.fill(rev, -1);
            for (int i = 0; i < TBL.length; i++) rev[TBL[i]] = i;
            int pad = 0;
            int end = s.length();
            while (end > 0 && s.charAt(end - 1) == '=') { pad++; end--; }
            int outLen = (end * 6) / 8;
            byte[] out = new byte[outLen];
            int bits = 0, acc = 0, oi = 0;
            for (int i = 0; i < end; i++) {
                char c = s.charAt(i);
                int v = (c < 128) ? rev[c] : -1;
                if (v < 0) return null;          // 非法字符 -> 视为损坏
                acc = (acc << 6) | v;
                bits += 6;
                if (bits >= 8) {
                    bits -= 8;
                    if (oi < out.length) out[oi++] = (byte) ((acc >> bits) & 255);
                }
            }
            if (oi == out.length) return out;
            byte[] cut = new byte[oi];
            System.arraycopy(out, 0, cut, 0, oi);
            return cut;
        }
    }

    /**
     * 块位图：第 i 位表示第 i 块是否已收到。
     *
     * <p>内部用 byte[] 存位 —— 与 Python 端 {@code bytearray((n+7)//8)} 布局一致，
     * 保证两端 .bmp 文件互相可读。
     */
    public static class ChunkMap {
        public final int n;
        private final byte[] bits;

        public ChunkMap(int n) {
            this.n = Math.max(1, n);
            this.bits = new byte[(this.n + 7) / 8];
        }

        private ChunkMap(int n, byte[] raw) {
            this.n = Math.max(1, n);
            this.bits = raw;
        }

        /** 取值（越界返回 false） */
        public boolean has(int i) {
            if (i < 0 || i >= n) return false;
            return (bits[i >> 3] & (1 << (i & 7))) != 0;
        }

        /** 标记已收到；返回 true 表示这是**新**块（重复块返回 false） */
        public boolean add(int i) {
            if (i < 0 || i >= n) return false;
            int b = i >> 3;
            int mask = 1 << (i & 7);
            if ((bits[b] & mask) != 0) return false;
            bits[b] |= (byte) mask;
            return true;
        }

        public int count() {
            int c = 0;
            for (byte b : bits) {
                // 补零不影响计数：负数字节的高位是符号位，
                // 用 Integer.bitCount(b & 0xFF) 统一按 8 位统计
                c += Integer.bitCount(b & 0xFF);
            }
            return c;
        }

        public boolean complete() {
            return count() >= n;
        }

        /** 已落盘字节数（按块号推导，不做累加，避免计数漂移） */
        public long receivedBytes(long size) {
            long tot = 0;
            for (int i = 0; i < n; i++) {
                if (has(i)) tot += chunkLen(i, size);
            }
            return tot;
        }

        /** 缺失块号列表（升序） */
        public List<Integer> missing() {
            List<Integer> out = new ArrayList<>();
            for (int i = 0; i < n; i++) if (!has(i)) out.add(i);
            return out;
        }

        /** 已收块号列表（升序）—— 发送端据此算"跳过集合" */
        public List<Integer> present() {
            List<Integer> out = new ArrayList<>();
            for (int i = 0; i < n; i++) if (has(i)) out.add(i);
            return out;
        }

        // ---------- 序列化（跨端共享） ----------

        public byte[] toBytes() {
            return bits;
        }

        public String toB64() {
            return B64.encode(bits);
        }

        public static ChunkMap fromB64(String s, int n) {
            ChunkMap cm = new ChunkMap(n);
            byte[] raw = B64.decode(s == null ? "" : s);
            if (raw == null || raw.length == 0) return cm;
            int m = Math.min(raw.length, cm.bits.length);
            System.arraycopy(raw, 0, cm.bits, 0, m);
            cm.trim();
            return cm;
        }

        /**
         * 紧凑区间表示：[[0,12],[15,15]] —— 连续已收块合并。
         * 大多数情况是"前 n 块已收"，区间表示只有 1 项，
         * JSON 体积远小于 base64 位图；用于 RECV_READY.have 与 UI 展示。
         */
        public List<int[]> toCompact() {
            List<int[]> out = new ArrayList<>();
            int start = -1;
            for (int i = 0; i < n; i++) {
                if (has(i)) {
                    if (start < 0) start = i;
                } else if (start >= 0) {
                    out.add(new int[]{start, i - 1});
                    start = -1;
                }
            }
            if (start >= 0) out.add(new int[]{start, n - 1});
            return out;
        }

        /** 从紧凑区间还原（跨端解析 RECV_READY.have） */
        public static ChunkMap fromCompact(List<int[]> ranges, int n) {
            ChunkMap cm = new ChunkMap(n);
            if (ranges == null) return cm;
            for (int[] r : ranges) {
                if (r == null || r.length < 2) continue;
                int a = Math.max(0, r[0]);
                int b = Math.min(n - 1, r[1]);
                for (int i = a; i <= b; i++) cm.add(i);
            }
            return cm;
        }

        /** 解析 JSON 里的 [[0,2],[5,5]] 形式 */
        public static ChunkMap fromCompactJson(org.json.JSONArray arr, int n) {
            ChunkMap cm = new ChunkMap(n);
            if (arr == null) return cm;
            try {
                for (int i = 0; i < arr.length(); i++) {
                    org.json.JSONArray r = arr.optJSONArray(i);
                    if (r == null || r.length() < 2) continue;
                    int a = Math.max(0, r.optInt(0));
                    int b = Math.min(n - 1, r.optInt(1));
                    for (int k = a; k <= b; k++) cm.add(k);
                }
            } catch (Throwable t) {
                // 解析失败按"全缺"处理（安全重传）
            }
            return cm;
        }

        /** 超出 n 的多余位清零，避免 count() 多算 */
        private void trim() {
            int extra = n;
            if ((extra & 7) != 0 && (extra >> 3) < bits.length) {
                bits[extra >> 3] &= (byte) ((1 << (extra & 7)) - 1);
            }
        }

        // ---------- 落盘 ----------

        public static File pathFor(File cacheDir, String tid) {
            return new File(cacheDir, tid + ".bmp");
        }

        /** 位图落盘（原子写：tmp + rename），断电/崩溃不产生半截位图 */
        public boolean save(File cacheDir, String tid) {
            try {
                if (!cacheDir.exists() && !cacheDir.mkdirs()) return false;
                File p = pathFor(cacheDir, tid);
                File tmp = new File(p.getAbsolutePath() + ".tmp");
                try (FileOutputStream f = new FileOutputStream(tmp)) {
                    f.write(bits);
                    f.flush();
                    f.getFD().sync();
                }
                if (!tmp.renameTo(p)) {
                    // 部分文件系统 renameTo 不覆盖已存在文件
                    if (p.exists() && !p.delete()) return false;
                    return tmp.renameTo(p);
                }
                return true;
            } catch (Throwable t) {
                return false;
            }
        }

        /** 读回位图；文件不存在/损坏/长度不符一律按"全缺"处理（安全重传） */
        public static ChunkMap load(File cacheDir, String tid, int n) {
            try {
                File p = pathFor(cacheDir, tid);
                if (!p.isFile()) return new ChunkMap(n);
                RandomAccessFile raf = new RandomAccessFile(p, "r");
                try {
                    byte[] raw = new byte[(int) Math.min(raf.length(), 1 << 20)];
                    raf.readFully(raw);
                    ChunkMap cm = new ChunkMap(n);
                    int m = Math.min(raw.length, cm.bits.length);
                    System.arraycopy(raw, 0, cm.bits, 0, m);
                    cm.trim();
                    return cm;
                } finally {
                    raf.close();
                }
            } catch (Throwable t) {
                return new ChunkMap(n);
            }
        }
    }

    /**
     * 续传指纹：文件大小 + 名称的短摘要。
     *
     * <p>用途：接收端重启后校验"这个 .part 是不是同一个文件的残留"，
     * 防止同名不同内容的文件被错误拼接（那会得到一个损坏文件）。
     * 与 Python 端 {@code md5(f"{size}|{name}")[:16]} 完全一致。
     */
    public static String resumeFingerprint(long size, String name) {
        try {
            MessageDigest md = MessageDigest.getInstance("MD5");
            md.update((size + "|" + (name == null ? "" : name)).getBytes("UTF-8"));
            StringBuilder sb = new StringBuilder();
            for (byte b : md.digest()) sb.append(String.format("%02x", b));
            return sb.substring(0, 16);
        } catch (Throwable t) {
            return Long.toHexString(size) + "_" + (name == null ? "" : name.hashCode());
        }
    }

    public static File fpPath(File cacheDir, String tid) {
        return new File(cacheDir, tid + ".fp");
    }

    public static boolean saveFingerprint(File cacheDir, String tid, long size, String name) {
        try {
            if (!cacheDir.exists() && !cacheDir.mkdirs()) return false;
            File p = fpPath(cacheDir, tid);
            File tmp = new File(p.getAbsolutePath() + ".tmp");
            try (FileOutputStream f = new FileOutputStream(tmp)) {
                f.write(resumeFingerprint(size, name).getBytes("UTF-8"));
                f.flush();
            }
            if (!tmp.renameTo(p)) {
                if (p.exists() && !p.delete()) return false;
                return tmp.renameTo(p);
            }
            return true;
        } catch (Throwable t) {
            return false;
        }
    }

    public static String loadFingerprint(File cacheDir, String tid) {
        try {
            File p = fpPath(cacheDir, tid);
            if (!p.isFile()) return "";
            RandomAccessFile raf = new RandomAccessFile(p, "r");
            try {
                byte[] b = new byte[(int) Math.min(raf.length(), 256)];
                raf.readFully(b);
                return new String(b, "UTF-8").trim();
            } finally {
                raf.close();
            }
        } catch (Throwable t) {
            return "";
        }
    }

    /** 传输成功/取消/拒绝后清理位图与指纹（.part 由调用方处理） */
    public static void dropResumeState(File cacheDir, String tid) {
        try {
            File p = ChunkMap.pathFor(cacheDir, tid);
            if (p.exists()) p.delete();
        } catch (Throwable ignored) {
        }
        try {
            File p = fpPath(cacheDir, tid);
            if (p.exists()) p.delete();
        } catch (Throwable ignored) {
        }
    }

    /** 指数退避：1.5, 2.25, 3.4 ... 上限 cap 秒。attempt 从 1 开始。 */
    public static double nextBackoff(int attempt, double base, double cap) {
        int a = Math.max(1, attempt);
        return Math.min(cap, Math.pow(base, a));
    }
}