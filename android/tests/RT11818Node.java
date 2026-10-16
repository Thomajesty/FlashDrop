package com.flashdrop.app;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.DataInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.PipedInputStream;
import java.io.PipedOutputStream;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.net.ServerSocket;
import java.net.Socket;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * v1.18.18 —— Android 端传输状态机**端到端**测试（真实 readerLoop + 内存管道）。
 *
 * ★ 为什么必须做这个测试：
 *   Windows 端同一功能的两个致命 bug（skip 语义写反导致首次传输零块发送、
 *   md5 只喂跳过块导致摘要恒空）都是纯算法测试发现不了的 ——
 *   算法对、接线错，只有把真实 readerLoop → onFileStart → beginInbound →
 *   onBin → onFileEnd 全链路跑起来才能暴露。
 *
 * 测试环境（为什么不用真 socket 传数据）：
 *   - 本机可能跑着真 FlashDrop 实例，会通过 UDP/子网扫描连上测试节点
 *     抢占 conns（Windows 端已实际踩到，断言失败但代码看起来没错）。
 *   - 因此：sock 用一对**闲置的本地 socket**（只为 setSoTimeout/close 可调用），
 *     数据走 PipedInputStream/PipedOutputStream 内存管道，
 *     且小缓冲（8KB）形成自然背压 —— A 写 512KB 块会阻塞到 B 消费，
 *     这让"收满 3 块后掐断管道"成为精确可控的断链手段。
 *   - 不调 start()：UDP 发现/扫描/心跳全部不跑，网络环境零干扰。
 *
 * 运行见 tools/run_rt11818_node.sh
 */
public class RT11818Node {

    static int pass = 0, fail = 0;
    static final List<JSONObject> LOG = new ArrayList<>();

    static void check(String name, boolean ok, String extra) {
        if (ok) { pass++; System.out.println("  PASS  " + name); }
        else {
            fail++;
            System.out.println("  FAIL  " + name
                    + (extra != null && !extra.isEmpty() ? "   " + extra : ""));
        }
    }

    static void check(String name, boolean ok) { check(name, ok, null); }

    static void eqm(String name, Object a, Object b) {
        boolean ok = String.valueOf(a).equals(String.valueOf(b));
        check(name, ok, ok ? "" : "期望=[" + b + "] 实际=[" + a + "]");
    }

    static void sec(String s) { System.out.println("\n=== " + s + " ==="); }

    // ---------------- 反射工具 ----------------

    static Object fieldOf(Object o, String name) throws Exception {
        Class<?> c = o.getClass();
        while (c != null) {
            try {
                Field f = c.getDeclaredField(name);
                f.setAccessible(true);
                return f.get(o);
            } catch (NoSuchFieldException e) {
                c = c.getSuperclass();
            }
        }
        throw new NoSuchFieldException(name);
    }

    static Object invoke(Object o, String method, Class<?>[] pt, Object[] args)
            throws Exception {
        Class<?> c = o.getClass();
        while (c != null) {
            try {
                Method m = c.getDeclaredMethod(method, pt);
                m.setAccessible(true);
                return m.invoke(o, args);
            } catch (NoSuchMethodException e) {
                c = c.getSuperclass();
            }
        }
        throw new NoSuchMethodException(method);
    }

    // ---------------- 测试替身 ----------------

    static class FakeContext extends android.content.Context {
        @Override
        public java.io.File getCacheDir() { return new File("."); }
    }

    static class FakePrefs extends Prefs {
        volatile boolean auto = true;
        volatile String alias = "";

        FakePrefs() { super(new FakeContext()); }

        @Override public String deviceHost() { return "testhost"; }
        @Override public String legacyDeviceId() { return ""; }
        @Override public JSONArray knownSubnets() { return new JSONArray(); }
        @Override public boolean autoAccept() { return auto; }
        @Override public String bubbleScheme() { return "blue"; }
        @Override public String getAlias(String peerId) { return alias; }
    }

    /** 一个测试节点：真构造器 + 真字段初始化，不 start()（无网络栈） */
    static class TNode {
        FlashNode node;
        FakePrefs prefs;
        String id;
        FlashNode.Conn conn;          // 本节点视角的连接
        final List<JSONObject> evts = new ArrayList<>();
        volatile boolean readerStarted;

        /** readerLoop 的唯一输入流：conn.in 读它，对方 conn.out 写它 */
        PipedInputStream readerIn;

        TNode(String tag) throws Exception {
            prefs = new FakePrefs();
            node = new FlashNode(new FakeContext(), tag + tag + tag + tag, tag, 0, prefs);
            node.setListener(e -> {
                synchronized (evts) { evts.add(e); }
            });
            // 不调 start()。readerLoop 的 while 条件要求 running=true，
            // 单独打开它（不启动 server/UDP/扫描）
            ((AtomicBoolean) fieldOf(node, "running")).set(true);
            // 读端在构造时就建好，connectTo 只做"我的 writer 连对方 readerIn"
            readerIn = new PipedInputStream(8192);
        }

        /**
         * 与对方建立一条内存双向链路。
         *
         * ★ 接线规则（上一版在这里翻车）：
         *   我.conn.out（我写）→ **对方**.readerIn（对方 readerLoop 读）。
         *   上一版用了两套互不相接的管道（conn.in 读 pipeIn、对方写 externalIn），
         *   结果"连上了但一个字节都到不了" —— 与真实 TCP 排障一模一样的表象。
         */
        void connectTo(TNode other) throws Exception {
            // sock：一对闲置本地 socket（仅 close/setSoTimeout 可调用）
            try (ServerSocket ss = new ServerSocket(0)) {
                Socket s1 = new Socket("127.0.0.1", ss.getLocalPort());
                Socket s2 = ss.accept();
                s2.close();
                ss.close();
                conn = new FlashNode.Conn();
                conn.sock = s1;
                conn.in = new DataInputStream(readerIn);
                // 我写 → 对方的 readerIn（对方 readerLoop 消费）。
                // ★ PipedInputStream 只允许**一个** writer connect，
                //   重连必须给对方换新流（旧流给旧 readerLoop 挂着等，无害）
                other.readerIn = new PipedInputStream(8192);
                conn.out = new PipedOutputStream(other.readerIn);
                conn.peerId = other.id;
                conn.helloGot = true;
                Map<String, FlashNode.Conn> conns =
                        (Map<String, FlashNode.Conn>) fieldOf(node, "conns");
                conns.put(conn.peerId, conn);
                // ★ 不在这里起 readerLoop：对端 connectTo 还会换本节点的新流，
                //   必须等两端全部接好、由 main 显式 startReader()
                //   （上一版在这里起，导致 conn.in 绑定到将被丢弃的旧流
                //     —— "对方写了我永远收不到"，又是真实 TCP 的表象）。
            }
        }

        /**
         * 换新读流并返回写端 —— 给"外部直接喂数据"的场景用（§5 老端模拟）。
         * PipedInputStream 单 writer，复用旧流必抛 Already connected。
         */
        PipedOutputStream freshInlet() throws Exception {
            readerIn = new PipedInputStream(8192);
            conn.in = new DataInputStream(readerIn);
            return new PipedOutputStream(readerIn);
        }

        /** 两端都 connectTo 完毕后调用：绑定最新 readerIn 并启动真实 readerLoop */
        void startReader() {
            conn.in = new DataInputStream(readerIn);
            Thread t = new Thread(() -> {
                try {
                    invoke(node, "readerLoop", new Class[]{FlashNode.Conn.class},
                            new Object[]{conn});
                } catch (Exception ignored) {
                }
                readerStarted = true;
            }, "reader-" + id);
            t.setDaemon(true);
            t.start();
        }

        @SuppressWarnings("unchecked")
        Map<String, FlashNode.Inbound> inbounds() throws Exception {
            return (Map<String, FlashNode.Inbound>) fieldOf(node, "inbounds");
        }

        List<JSONObject> evtsOf(String state) {
            synchronized (evts) {
                List<JSONObject> out = new ArrayList<>();
                for (JSONObject e : evts) {
                    if ("transfer".equals(e.optString("event"))
                            && state.equals(e.optString("state"))) out.add(e);
                }
                return out;
            }
        }

        List<JSONObject> logs() {
            synchronized (evts) {
                List<JSONObject> out = new ArrayList<>();
                for (JSONObject e : evts) {
                    if ("log".equals(e.optString("event"))) out.add(e);
                }
                return out;
            }
        }
    }

    // ---------------- 工具 ----------------

    static String md5Of(File f) throws Exception {
        MessageDigest md = MessageDigest.getInstance("MD5");
        try (FileInputStream fis = new FileInputStream(f)) {
            byte[] buf = new byte[1 << 16];
            int n;
            while ((n = fis.read(buf)) > 0) md.update(buf, 0, n);
        }
        StringBuilder sb = new StringBuilder();
        for (byte b : md.digest()) sb.append(String.format("%02x", b));
        return sb.toString();
    }

    static void waitCond(String what, java.util.concurrent.Callable<Boolean> c,
                         long timeoutMs) throws Exception {
        long deadline = System.currentTimeMillis() + timeoutMs;
        while (System.currentTimeMillis() < deadline) {
            if (Boolean.TRUE.equals(c.call())) return;
            Thread.sleep(30);
        }
        System.out.println("  !! 等待超时: " + what);
    }

    /** 造测试文件（伪随机内容，MD5 确定） */
    static File makeFile(File dir, String name, long size, byte seed) throws Exception {
        File f = new File(dir, name);
        MessageDigest md = MessageDigest.getInstance("MD5");
        try (java.io.FileOutputStream fos = new java.io.FileOutputStream(f)) {
            long left = size;
            byte[] block = new byte[4096];
            java.util.Arrays.fill(block, seed);
            while (left > 0) {
                int n = (int) Math.min(block.length, left);
                fos.write(block, 0, n);
                md.update(block, 0, n);
                left -= n;
            }
        }
        return f;
    }

    static void dumpEvts(String tag, List<JSONObject> evts) {
        System.out.println("  ---- " + tag + " 事件 (" + evts.size() + ") ----");
        synchronized (evts) {
            for (JSONObject e : evts) {
                String msg = e.optString("msg", null);
                System.out.println("    " + e.opt("event") + " kind=" + e.opt("kind")
                        + " state=" + e.opt("state")
                        + " reason=" + e.opt("reason")
                        + (msg != null ? " msg=" + msg : ""));
            }
        }
    }

    static boolean waitForEvt(List<JSONObject> evts, String kind, String state, long ms) {
        long deadline = System.currentTimeMillis() + ms;
        while (System.currentTimeMillis() < deadline) {
            synchronized (evts) {
                for (JSONObject e : evts) {
                    if (kind.equals(e.optString("event"))
                            && state.equals(e.optString("state"))) return true;
                }
            }
            try { Thread.sleep(30); } catch (InterruptedException e) { return false; }
        }
        return false;
    }

    // ============================ 主流程 ============================

    public static void main(String[] args) throws Exception {
        System.out.println("================================================");
        System.out.println(" RT11818-Node 传输状态机端到端测试");
        System.out.println("================================================");

        File tmp = new File(System.getProperty("java.io.tmpdir"),
                "fd_rt11818n_" + System.nanoTime());
        File cache = new File(tmp, "cache");
        File save = new File(tmp, "save");
        cache.mkdirs();
        save.mkdirs();
        System.setProperty("fd.cache.dir", cache.getAbsolutePath());
        System.setProperty("fd.save.dir", save.getAbsolutePath());

        // ============ §1 一次成功传输（chunk 模式） ============
        sec("§1 一次成功传输（chunk 模式，5 块）");
        TNode a = new TNode("nodeA");
        TNode b = new TNode("nodeB");
        a.id = a.node.getDeviceId();
        b.id = b.node.getDeviceId();
        // 交叉接线：A.conn.out 写进 B 的 inlet；B.conn.out 写进 A 的 inlet
        a.connectTo(b);
        b.connectTo(a);
        a.startReader();
        b.startReader();

        long size = 4L * FdResume.RESUME_CHUNK + 1234;
        File src = makeFile(tmp, "f1.bin", size, (byte) 0x11);
        String md5 = md5Of(src);

        a.node.sendFiles(new ArrayList<>(List.of(b.id)),
                new ArrayList<>(List.of(src.getAbsolutePath())));

        check("B 收到 done", waitForEvt(b.evts, "transfer", "done", 20000));
        check("A 收到 ok", waitForEvt(a.evts, "transfer", "ok", 20000));
        List<JSONObject> doneEvts = b.evtsOf("done");
        if (!doneEvts.isEmpty()) {
            JSONObject done = doneEvts.get(doneEvts.size() - 1);
            String savedPath = done.optString("path", "");
            File saved = new File(savedPath);
            check("B 落盘文件存在", saved.isFile(), savedPath);
            if (saved.isFile()) {
                eqm("B 落盘 MD5 与源一致", md5Of(saved), md5);
                eqm("B 落盘大小一致", saved.length(), size);
            }
            eqm("done 事件带块数", done.optInt("total_chunks", -1),
                    FdResume.totalChunks(size));
        }
        check("协商为 chunk 模式（有 total_chunks）",
                !doneEvts.isEmpty() && doneEvts.get(0).optInt("total_chunks", 0) > 0);
        dumpEvts("A", a.evts);
        dumpEvts("B", b.evts);
        // 成功后位图/指纹应清理（直接检查缓存目录无残留）
        int total = FdResume.totalChunks(size);
        File[] residue = cache.listFiles(
                (d, nm) -> nm.endsWith(".bmp") || nm.endsWith(".fp"));
        check("缓存无 .bmp/.fp 残留", residue == null || residue.length == 0,
                residue == null ? "" : java.util.Arrays.toString(residue));

        // ============ §2 断链 → 接收端保留断点 ============
        sec("§2 传输中断 → 接收端保留断点");
        a.evts.clear();
        b.evts.clear();
        File src2 = makeFile(tmp, "f2.bin", size, (byte) 0x22);
        String md5_2 = md5Of(src2);
        // ★ 确定性掐断（上一版用轮询 cmap.count()>=3 再关管道 ——
        //   B 消费太快，轮询赶到时文件已经 done，竞态必输）：
        //   给 b.conn.in 包一层过滤器，放行 1.5 块的字节后一律抛 IOException
        //   —— readerLoop 的 readFrame 会炸出异常走 finally，
        //   正是产品代码"连接中断保留断点"的真实路径。
        final long cutAfter = (long) (FdResume.RESUME_CHUNK * 1.5) + 4096;
        java.io.FilterInputStream cut = new java.io.FilterInputStream(b.conn.in) {
            long passed = 0;
            private void tick(int n) throws java.io.IOException {
                passed += n;
                if (passed > cutAfter)
                    throw new java.io.IOException("simulated network break");
            }
            @Override public int read() throws java.io.IOException {
                tick(0); return super.read();
            }
            @Override public int read(byte[] b2, int off, int len)
                    throws java.io.IOException {
                tick(0);           // 每次调用先检查是否已越界
                int n = super.read(b2, off, len);
                if (n > 0) {
                    if (passed + n > cutAfter) {
                        // 只放行到限额，剩余丢弃 —— 断在帧中间
                        long allow = cutAfter - passed;
                        passed = cutAfter + 1;
                        if (allow > 0) return (int) allow;
                        throw new java.io.IOException("simulated network break");
                    }
                    passed += n;
                }
                return n;
            }
        };
        b.conn.in = new DataInputStream(cut);

        a.node.sendFiles(new ArrayList<>(List.of(b.id)),
                new ArrayList<>(List.of(src2.getAbsolutePath())));

        // B readerLoop 因过滤器异常退出 → finally flush+cleanup(false)+paused
        check("B 收到 paused（连接中断可续传）",
                waitForEvt(b.evts, "transfer", "paused", 20000));
        // A 端写入会因管道关闭而失败并进入重试
        check("A 进入 retrying（自动重试）",
                waitForEvt(a.evts, "transfer", "retrying", 20000));
        // 等 A 的重试循环彻底失败退出（3 次退避 ≈ 7s，留裕量）
        check("A 端最终失败（管道未恢复）",
                waitForEvt(a.evts, "transfer", "failed", 60000));
        Thread.sleep(300);

        // 断点文件必须保留 —— 查**产品真实 cacheDir**（cache/flashdrop/，
        //   FdUtil.cacheDir 会在注入目录下再建 flashdrop 子目录）
        File realCache = FdUtil.cacheDir(new FakeContext());
        System.out.println("  realCache=" + realCache
                + " 内容=" + java.util.Arrays.toString(realCache.listFiles()));
        File[] bmps = realCache.listFiles((d, nm) -> nm.endsWith(".bmp"));
        check("B 侧留有位图文件", bmps != null && bmps.length >= 1,
                bmps == null ? "null" : String.valueOf(bmps.length));
        if (bmps != null && bmps.length > 0) {
            String tid = bmps[0].getName().replace(".bmp", "");
            FdResume.ChunkMap cm = FdResume.ChunkMap.load(realCache, tid, total);
            check("断点保留 >= 1 块", cm.count() >= 1, String.valueOf(cm.count()));
            check("断点未完成", !cm.complete());
        }
        dumpEvts("A-2", a.evts);
        dumpEvts("B-2", b.evts);

        // ============ §3 同 tid 重发 → 只补缺失块 → 完成 ============
        sec("§3 同 tid 重发 → 只补缺失块 → 完成");
        // 重新接线（两端 readerLoop 已死）
        a.evts.clear();
        b.evts.clear();
        // 把 §2 的位图 tid 找出来，用**同一个 tid** 手动触发续传：
        // 直接走产品路径 —— A 端 sendFileTo 用同 tid 重发。
        // sendFiles 会生成新 tid，所以这里用反射直接调 sendFileTo 指定 tid。
        File realCache3 = FdUtil.cacheDir(new FakeContext());
        File[] bmps3 = realCache3.listFiles((d, nm) -> nm.endsWith(".bmp"));
        if (bmps3 == null || bmps3.length == 0) {
            check("§3 前置：有断点位图", false, "无位图可续传");
        } else {
            String tid2 = bmps3[0].getName().replace(".bmp", "");
            FdResume.ChunkMap before = FdResume.ChunkMap.load(realCache3, tid2, total);
            int haveBefore = before.count();
            // 重建连接并重启读循环
            a.connectTo(b);
            b.connectTo(a);
            a.startReader();
            b.startReader();
            // 同 tid 重发（产品代码路径：sendFileTo）
            invoke(a.node, "sendFileTo",
                    new Class[]{String.class, String.class, String.class,
                            String.class, long.class, String.class},
                    new Object[]{b.id, tid2, src2.getAbsolutePath(),
                            "f2.bin", size, "application/octet-stream"});
            check("续传后 B 收到 done", waitForEvt(b.evts, "transfer", "done", 20000));
            List<JSONObject> done2 = b.evtsOf("done");
            if (!done2.isEmpty()) {
                File saved = new File(done2.get(done2.size() - 1).optString("path", ""));
                check("续传落盘存在", saved.isFile(), saved.getPath());
                if (saved.isFile()) {
                    eqm("续传落盘 MD5 正确", md5Of(saved), md5_2);
                    eqm("续传落盘大小正确", saved.length(), size);
                }
            }
            // A 端日志出现"跳过已收"
            boolean logged = false;
            for (JSONObject e : a.logs()) {
                String m = e.optString("msg", "");
                if (m.contains("断点续传") && m.contains("跳过已收")) { logged = true; break; }
            }
            check("A 端出现断点续传日志", logged,
                    a.logs().isEmpty() ? "无日志" : a.logs().get(a.logs().size() - 1)
                            .optString("msg"));
            // ★ 掐断点设在 1.5 块（见 §2 cutAfter），所以断点保留的是 1 块
            eqm("续传前位图块数符合预期（>=1）", haveBefore >= 1, true);
            // 成功后断点清理
            File[] residue3 = realCache3.listFiles((d, nm) -> nm.endsWith(".bmp")
                    || nm.endsWith(".fp"));
            check("成功后断点已清理", residue3 == null || residue3.length == 0,
                    residue3 == null ? "" : String.valueOf(residue3.length));
        }

        // ============ §4 拒绝 → 不重试 ============
        sec("§4 对方拒绝 → 立即失败不重试");
        // §2 的断链把 A、B 两端 readerLoop 都弄死了 —— 双方全部重建
        a.connectTo(b);
        b.connectTo(a);
        a.startReader();
        b.startReader();
        b.prefs.auto = false;
        a.evts.clear();
        b.evts.clear();
        File src4 = makeFile(tmp, "f4.bin", 100, (byte) 0x44);
        // 缩短 ok 等待不影响 —— 拒绝会立刻回 REFUSE
        // 监视：B 出现待确认条目后立即拒绝（模拟用户点"拒绝"）
        Thread rej = new Thread(() -> {
            try {
                long dl = System.currentTimeMillis() + 15000;
                while (System.currentTimeMillis() < dl) {
                    Map<String, FlashNode.Inbound> ibs = b.inbounds();
                    for (FlashNode.Inbound ib : ibs.values()) {
                        if (!ib.started && !ib.done) {
                            b.node.rejectInbound(ib.tid);
                            return;
                        }
                    }
                    Thread.sleep(30);
                }
            } catch (Exception ignored) {}
        });
        rej.setDaemon(true);
        rej.start();
        a.node.sendFiles(new ArrayList<>(List.of(b.id)),
                new ArrayList<>(List.of(src4.getAbsolutePath())));
        check("A 收到 refused", waitForEvt(a.evts, "transfer", "refused", 15000));
        check("B 进入 confirm 态", waitForEvt(b.evts, "transfer", "confirm", 15000));
        // 拒绝后 A 不应有 retrying
        Thread.sleep(1500);
        eqm("拒绝后无重试", a.evtsOf("retrying").size(), 0);
        b.prefs.auto = true;

        // ============ §5 顺序流回退（老端兼容） ============
        sec("§5 顺序流回退（0x42，老端兼容）");
        // 直接往 B 的管道喂"老端三步"：FILE_START(无 idx) + 0x42 块 + FILE_END
        b.evts.clear();
        // B 重建连接（复用 A 做回写对端 —— B 回 FILE_OK 时 A 的旧 readerLoop 还活着会读掉）
        b.connectTo(a);
        b.startReader();
        PipedOutputStream toB = b.freshInlet();
        String tid5 = "tidstream01";
        File src5 = makeFile(tmp, "f5.bin", size, (byte) 0x55);
        String md5_5 = md5Of(src5);
        new Thread(() -> {
            try {
                toB.write(FdProto.encodeJson(FdProto.obj(
                        "type", FdProto.T_FILE_START, "tid", tid5,
                        "name", "f5.bin", "size", size,
                        "mime", "application/octet-stream")));
                // 老端：0x42 顺序块
                try (FileInputStream fis = new FileInputStream(src5)) {
                    byte[] buf = new byte[FdProto.CHUNK_SIZE];
                    int n;
                    while ((n = fis.read(buf)) > 0) {
                        toB.write(FdProto.encodeBin(tid5,
                                java.util.Arrays.copyOf(buf, n)));
                    }
                }
                toB.write(FdProto.encodeJson(FdProto.obj(
                        "type", FdProto.T_FILE_END, "tid", tid5,
                        "md5", md5_5)));
                toB.flush();
            } catch (Exception ignored) {
            }
        }).start();
        check("顺序流：B 收到 done", waitForEvt(b.evts, "transfer", "done", 20000));
        List<JSONObject> done5 = b.evtsOf("done");
        if (!done5.isEmpty()) {
            File saved = new File(done5.get(done5.size() - 1).optString("path", ""));
            if (saved.isFile()) eqm("顺序流落盘 MD5 正确", md5Of(saved), md5_5);
        }

        System.out.println("\n================================================");
        System.out.println("RT11818-Node：通过 " + pass + " 项，失败 " + fail + " 项");
        System.out.println("================================================");
        if (fail > 0) {
            System.out.println("失败项：");
            System.out.println("（见上方 FAIL 行）");
        }
        System.exit(fail > 0 ? 1 : 0);
    }
}