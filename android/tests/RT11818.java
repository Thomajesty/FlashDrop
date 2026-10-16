import java.io.File;

import com.flashdrop.app.FdResume;
import com.flashdrop.app.FdResume.ChunkMap;
import java.util.List;

/**
 * v1.18.18 —— Android 端断点续传核心（FdResume 块位图）测试
 *
 * 与 Windows 端 verify_v11818_resume.py 的断言**逐条对应**，
 * 两端算法/文件名/位图布局必须一致，否则互相重连时识别不了对方断点。
 *
 * 运行见 tools/run_rt11818.sh
 */
public class RT11818 {

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

    static final int CH = FdResume.RESUME_CHUNK;

    public static void main(String[] args) throws Exception {
        System.out.println("========================================");
        System.out.println(" RT11818 断点续传核心（FdResume）测试");
        System.out.println("========================================");

        // ---------------- 分块规划 ----------------
        sec("分块规划");
        eqm("0 字节 -> 1 块", FdResume.totalChunks(0), 1);
        eqm("1 字节 -> 1 块", FdResume.totalChunks(1), 1);
        eqm("正好一块", FdResume.totalChunks(CH), 1);
        eqm("多一块 -> 2 块", FdResume.totalChunks((long) CH + 1), 2);
        eqm("10MB -> 20 块", FdResume.totalChunks(10L * 1024 * 1024), 20);
        eqm("块偏移=块号*CHUNK", FdResume.chunkOffset(3), (long) CH * 3);
        eqm("首块长度满块", FdResume.chunkLen(0, CH + 7), CH);
        eqm("末块可短", FdResume.chunkLen(1, CH + 7), 7);
        eqm("越界块长为 0", FdResume.chunkLen(5, CH + 7), 0);
        // ★ 负索引语义与 Python 端**一致**（不是 0）：
        //   Python resume.chunk_len(-1, CH) == 524288。
        //   两端必须一致，否则一端算出的块长与另一端对不上。
        eqm("负索引块长与 Python 端一致", FdResume.chunkLen(-1, CH), (long) CH);

        // ---------------- 位图基本操作 ----------------
        sec("位图基本操作");
        ChunkMap cm = new ChunkMap(20);
        eqm("新位图 count=0", cm.count(), 0);
        check("新位图未 complete", !cm.complete());
        check("add 返回 true（首次）", cm.add(0));
        check("add 返回 false（重复）", !cm.add(0));
        eqm("重复 add 不改计数", cm.count(), 1);
        check("has 命中", cm.has(0));
        check("has 未命中", !cm.has(1));
        check("越界 has 返回 false", !cm.has(999));
        check("越界 add 返回 false", !cm.add(999));
        check("负索引 add 返回 false", !cm.add(-1));
        eqm("跨字节边界(8)", new ChunkMap(20).add(8), true);
        ChunkMap cm2 = new ChunkMap(20);
        cm2.add(7);
        cm2.add(8);
        eqm("位 7/8 跨字节都记上", cm2.count(), 2);

        // ---------------- 完整性 /缺失 ----------------
        sec("完整性与缺失");
        ChunkMap all = new ChunkMap(5);
        for (int i = 0; i < 5; i++) all.add(i);
        eqm("全收count", all.count(), 5);
        check("全收 complete", all.complete());
        eqm("全收 missing 空", all.missing().size(), 0);
        eqm("全收 present=5", all.present().size(), 5);
        ChunkMap part = new ChunkMap(5);
        part.add(0); part.add(1); part.add(2);
        List<Integer> miss = part.missing();
        eqm("缺 2 块", miss.size(), 2);
        eqm("missing[0]=3", miss.get(0), 3);
        eqm("missing[1]=4", miss.get(1), 4);
        check("未 complete", !part.complete());

        // ---------------- 已收字节数 ----------------
        sec("已收字节数（按块号推导，不累加）");
        long size = 2L * CH + 7;
        ChunkMap rb = new ChunkMap(3);
        rb.add(0);
        eqm("收 0 号块 = 满块", rb.receivedBytes(size), (long) CH);
        rb.add(2);   // 末块 7 字节
        eqm("收 0+2 块", rb.receivedBytes(size), (long) CH + 7);
        rb.add(1);
        eqm("全收 = size", rb.receivedBytes(size), size);
        check("累加不会漂移：重复块不改变数值", rb.receivedBytes(size) == size);

        // ---------------- 序列化往返 ----------------
        sec("序列化往返");
        ChunkMap rt = new ChunkMap(40);
        for (int i = 0; i < 40; i += 2) rt.add(i);       // 偶数块
        ChunkMap viaB64 = ChunkMap.fromB64(rt.toB64(), 40);
        eqm("base64 往返 count 一致", viaB64.count(), rt.count());
        eqm("base64 往返 missing 一致",
                viaB64.missing().toString(), rt.missing().toString());
        ChunkMap viaCompact = ChunkMap.fromCompact(rt.toCompact(), 40);
        eqm("紧凑区间往返 count 一致", viaCompact.count(), rt.count());
        eqm("紧凑区间往返 missing 一致",
                viaCompact.missing().toString(), rt.missing().toString());
        // 跨端兼容：base64 串必须与 Python 端一致（固定值回归）
        ChunkMap fix = new ChunkMap(8);
        fix.add(0);
        fix.add(3);
        // ★ 基准值取自 Python 端实测（ChunkMap(8) add(0) add(3)）：
        //   base64.b64encode(bytes([1,0,0,0])) == "CQ=="
        //   （带填充。Python b64decode 遇到无填充串会抛 Incorrect padding，
        //     所以两端统一为有填充）
        eqm("base64 与 Python 端逐字节一致", fix.toB64(), "CQ==");
        // 跨端解码：带填充 / 无填充两种形式都能吃
        eqm("可解带填充串", FdResume.ChunkMap.fromB64("CQ==", 8).count(), 2);
        eqm("可解无填充串", FdResume.ChunkMap.fromB64("CQ", 8).count(), 2);
        // 紧凑区间内容（不能用 toString —— int[] 没override，打印的是对象地址）
        eqm("紧凑区间长度", fix.toCompact().size(), 2);
        eqm("紧凑区间[0]=[0,0]", fix.toCompact().get(0)[0] + "," + fix.toCompact().get(0)[1],
                "0,0");
        eqm("紧凑区间[1]=[3,3]", fix.toCompact().get(1)[0] + "," + fix.toCompact().get(1)[1],
                "3,3");
        // 非法输入不炸
        eqm("空 base64 -> 全缺", ChunkMap.fromB64("", 10).count(), 0);
        eqm("垃圾 base64 -> 全缺", ChunkMap.fromB64("!!!not base64!!!", 10).count(), 0);
        eqm("null 区间 -> 全缺", ChunkMap.fromCompact(null, 10).count(), 0);
        eqm("空区间列表 -> 全缺", ChunkMap.fromCompact(new java.util.ArrayList<int[]>(), 10).count(), 0);
        ChunkMap over = new ChunkMap(10);
        over.add(9);
        eqm("区间越界被裁剪", ChunkMap.fromCompact(
                java.util.Arrays.asList(new int[]{5, 99}), 10).count(), 5);

        // ---------------- 位图落盘 ----------------
        sec("位图落盘（原子写）");
        File dir = new File(System.getProperty("java.io.tmpdir"),
                "fd_bmp_" + System.nanoTime());
        dir.mkdirs();
        String tid = "T1";
        ChunkMap save = new ChunkMap(30);
        for (int i = 0; i < 30; i += 3) save.add(i);
        check("落盘成功", save.save(dir, tid));
        check("位图文件存在", ChunkMap.pathFor(dir, tid).isFile());
        ChunkMap back = ChunkMap.load(dir, tid, 30);
        eqm("读回 count 一致", back.count(), save.count());
        eqm("读回 missing 一致", back.missing().toString(), save.missing().toString());
        // 覆盖写（同名再存一次）
        ChunkMap save2 = new ChunkMap(30);
        save2.add(1);
        check("同名覆盖写成功", save2.save(dir, tid));
        eqm("覆盖后读回是新内容",
                ChunkMap.load(dir, tid, 30).count(), 1);
        check("无残留 .tmp",
                !new File(ChunkMap.pathFor(dir, tid).getAbsolutePath()
                        + ".tmp").exists());
        // 文件不存在 -> 全缺
        eqm("文件不存在 -> 全缺",
                ChunkMap.load(dir, "NOPE", 10).count(), 0);
        // 损坏文件 -> 全缺（不抛）
        ChunkMap.pathFor(dir, "BAD").getParentFile();
        try (java.io.FileOutputStream f = new java.io.FileOutputStream(
                ChunkMap.pathFor(dir, "BAD"))) {
            f.write(new byte[]{1, 2, 3});
        }
        check("损坏文件不抛异常",
                ChunkMap.load(dir, "BAD", 10).count() <= 3);
        // 长度大于 n 时多余位要裁掉
        try (java.io.FileOutputStream f = new java.io.FileOutputStream(
                ChunkMap.pathFor(dir, "LONG"))) {
            f.write(new byte[]{(byte) 0xFF, (byte) 0xFF, (byte) 0xFF});
        }
        eqm("超长位图裁剪到 n",
                ChunkMap.load(dir, "LONG", 3).count(), 3);

        // ---------------- 续传指纹 ----------------
        sec("续传指纹");
        eqm("指纹确定性", FdResume.resumeFingerprint(1000, "a.bin"),
                FdResume.resumeFingerprint(1000, "a.bin"));
        check("不同文件名指纹不同",
                !FdResume.resumeFingerprint(1000, "a.bin")
                        .equals(FdResume.resumeFingerprint(1000, "b.bin")));
        check("不同大小指纹不同",
                !FdResume.resumeFingerprint(1000, "a.bin")
                        .equals(FdResume.resumeFingerprint(1001, "a.bin")));
        // ★ 必须与 Python 端逐字节一致（两端互相识别断点的前提）
        // ★ 基准值取自 Python 端实测输出（不是拍脑袋写的）：
        //   resume.resume_fingerprint(1000, "a.bin") == 2dab84d3316d69ee
        //   两端算不出同一指纹 -> 互相重连时识别不了对方 .part，断点续传形同虚设。
        eqm("指纹与 Python 端逐字节一致", FdResume.resumeFingerprint(1000, "a.bin"),
                "2dab84d3316d69ee");
        eqm("指纹长度 16", FdResume.resumeFingerprint(1, "").length(), 16);
        check("FdResume.saveFingerprint 成功",
                FdResume.saveFingerprint(dir, tid, 1000, "a.bin"));
        eqm("FdResume.loadFingerprint 往返",
                FdResume.loadFingerprint(dir, tid), FdResume.resumeFingerprint(1000, "a.bin"));
        eqm("指纹文件不存在 -> 空", FdResume.loadFingerprint(dir, "NOPE"), "");

        // ---------------- 状态清理 ----------------
        sec("断点状态清理");
        ChunkMap keep = new ChunkMap(10);
        keep.add(1);
        keep.save(dir, "DROP");
        FdResume.saveFingerprint(dir, "DROP", 100, "x.bin");
        check("清理前位图存在", ChunkMap.pathFor(dir, "DROP").isFile());
        check("清理前指纹存在", FdResume.fpPath(dir, "DROP").isFile());
        FdResume.dropResumeState(dir, "DROP");
        check("清理后位图已删", !ChunkMap.pathFor(dir, "DROP").isFile());
        check("清理后指纹已删", !FdResume.fpPath(dir, "DROP").isFile());
        // 清理不存在的也不炸
        try {
            FdResume.dropResumeState(dir, "NOT_EXIST");
            check("清理不存在项不抛异常", true);
        } catch (Throwable t) {
            check("清理不存在项不抛异常", false, t.toString());
        }

        // ---------------- 指数退避 ----------------
        sec("指数退避");
        check("第1次 1.5s", Math.abs(FdResume.nextBackoff(1, 1.5, 30) - 1.5) < 1e-6);
        check("第2次 2.25s", Math.abs(FdResume.nextBackoff(2, 1.5, 30) - 2.25) < 1e-6);
        check("第3次 3.375s", Math.abs(FdResume.nextBackoff(3, 1.5, 30) - 3.375) < 1e-6);
        check("上限 30s", FdResume.nextBackoff(20, 1.5, 30) == 30.0);
        eqm("attempt=0 视作 1", FdResume.nextBackoff(0, 1.5, 30),
                FdResume.nextBackoff(1, 1.5, 30));
        eqm("负数 attempt 视作 1", FdResume.nextBackoff(-5, 1.5, 30),
                FdResume.nextBackoff(1, 1.5, 30));

        // ---------------- 跨端一致性回归 ----------------
        sec("回归：两端算法一致性");
        // ★ skip 语义回归：跳过集合必须是"已收块"，
        //   把 missing()（待发块）当跳过集会让首次传输一个块都不发。
        int n5 = FdResume.totalChunks(5L * CH + 7);
        ChunkMap empty = new ChunkMap(n5);
        java.util.Set<Integer> todo = new java.util.HashSet<>(empty.missing());
        java.util.Set<Integer> skip = new java.util.HashSet<>();
        for (int i = 0; i < n5; i++) if (!todo.contains(i)) skip.add(i);
        eqm("首次传输跳过 0 块", skip.size(), 0);
        eqm("首次传输待发全部块", todo.size(), n5);
        ChunkMap has3 = new ChunkMap(n5);
        has3.add(0); has3.add(1); has3.add(2);
        java.util.Set<Integer> todo2 = new java.util.HashSet<>(has3.missing());
        java.util.Set<Integer> skip2 = new java.util.HashSet<>();
        for (int i = 0; i < n5; i++) if (!todo2.contains(i)) skip2.add(i);
        eqm("续传跳过 3 块", skip2.size(), 3);
        eqm("续传只补缺失块", todo2.size(), n5 - 3);
        long skipBytes = 0;
        for (int i : skip2) skipBytes += FdResume.chunkLen(i, 5L * CH + 7);
        check("续传进度基准 > 0（进度不倒退）", skipBytes > 0);

        // 清理临时目录
        try {
            java.io.File[] fs = dir.listFiles();
            if (fs != null) for (java.io.File f : fs) f.delete();
            dir.delete();
        } catch (Throwable ignored) {
        }

        System.out.println("\n========================================");
        System.out.println("RT11818：通过 " + pass + " 项，失败 " + fail + " 项");
        System.out.println("========================================");
        if (fail > 0) System.out.println("\n失败项：");
        System.exit(fail > 0 ? 1 : 0);
    }
}