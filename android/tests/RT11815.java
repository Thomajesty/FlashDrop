import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * v1.18.15 —— 离线待发队列「确认送达才移除」行为测试。
 *
 * <p>用户反馈：安卓给电脑发离线消息，等电脑上线上「对方收不到、发送端也失败」。
 *
 * <p>已定位的根因（v1.18.13/v1.18.14 同款，两端一致）：
 * {@code flushPendingSends()} 调 {@code sendText()}（**异步**，内部还要
 * {@code waitConn} 等 TCP 最多 15s、再等 ack 12s）之后，**立刻**把条目从队列里
 * 删掉并落盘。设备刚上线时 UDP 层已判在线 → 触发 flush，但 TCP 往往还没建好
 * → wait_conn 失败 → text_state=failed → **条目已经没了，消息永久丢失**。
 * 而且队列**没有任何重试机制**，等于必丢。
 *
 * <p>本测试直接驱动**真实的 {@link FlashApp#flushPendingSendsAsync}**
 * （用 Unsafe 跳过 Application 构造，注入假的 node 与同步 Handler），
 * 覆盖 6 个场景。与 RT1110 同一套反射套路，不依赖 Android 运行时。
 *
 * <p>运行见 {@code tools/run_rt11815.sh}。
 */
public class RT11815 {

    static int pass = 0, fail = 0;

    static void check(String name, boolean ok) {
        if (ok) { pass++; System.out.println("  PASS  " + name); }
        else { fail++; System.out.println("  FAIL  " + name); }
    }

    static void eq(String name, Object a, Object b) {
        boolean ok = String.valueOf(a).equals(String.valueOf(b));
        if (ok) { pass++; System.out.println("  PASS  " + name); }
        else { fail++; System.out.println("  FAIL  " + name
                + "  期望=[" + b + "] 实际=[" + a + "]"); }
    }

    static void sec(String s) { System.out.println("\n=== " + s + " ==="); }

    // ---------------- 反射工具（与 RT1110 同一套，JDK 17 下写 final 字段要靠 Unsafe） ----------------

    static Object unsafeAlloc(Class<?> cls) throws Exception {
        Class<?> uc = Class.forName("sun.misc.Unsafe");
        Field tu = uc.getDeclaredField("theUnsafe");
        tu.setAccessible(true);
        Object u = tu.get(null);
        return uc.getMethod("allocateInstance", Class.class).invoke(u, cls);
    }

    static void put(Object target, String field, Object value) throws Exception {
        Class<?> c = target.getClass();
        Field f = null;
        while (c != null && f == null) {
            try { f = c.getDeclaredField(field); } catch (NoSuchFieldException e) { c = c.getSuperclass(); }
        }
        if (f == null) throw new NoSuchFieldException(field);
        Class<?> uc = Class.forName("sun.misc.Unsafe");
        Field tu = uc.getDeclaredField("theUnsafe");
        tu.setAccessible(true);
        Object u = tu.get(null);
        long off = (Long) uc.getMethod("objectFieldOffset", Field.class).invoke(u, f);
        Class<?> ft = f.getType();
        if (ft == boolean.class) {
            uc.getMethod("putBoolean", Object.class, long.class, boolean.class)
                    .invoke(u, target, off, (Boolean) value);
        } else {
            uc.getMethod("putObject", Object.class, long.class, Object.class)
                    .invoke(u, target, off, value);
        }
    }

    /**
     * 补发用的执行器。
     *
     * <p>不用 AbstractExecutorService —— android.jar 里虽然有它的 class 条目，
     * 但整个 java.util 包在那个 jar 里是残缺的（javac 会报 cannot find symbol），
     * 所以这里只用 Executors（可用），再用轮询等 flush 结束。
     */
    static ExecutorService flushExecutor() {
        return Executors.newSingleThreadExecutor();
    }

    /** 轮询等待本轮 flush 结束（flushing 标志由 false→true→false） */
    static void awaitFlush(Object app) throws Exception {
        for (int i = 0; i < 200; i++) {
            Field f = app.getClass().getDeclaredField("flushing");
            f.setAccessible(true);
            Object v = f.get(app);
            boolean busy = ((AtomicBoolean) v).get();
            if (!busy) return;
            Thread.sleep(10);
        }
    }

    // ---------------- 假的 node：只覆写本测试关心的两个方法 ----------------

    static int seq = 0;

    static class FakeNode extends com.flashdrop.app.FlashNode {
        List<String> online = new ArrayList<>();
        String mode = "ok";                    // ok / failed / timeout
        String capturedMid = null;
        List<String> capturedTargets = null;
        String capturedText = null;
        int callCount = 0;
        Runnable duringSend = null;            // 模拟"发送期间用户又加了一条"

        // FlashNode 没有无参构造器，而 javac 要求子类显式调用父类构造器。
        // 本测试一律用 Unsafe.allocateInstance 造实例，这个构造器**永远不会被执行**，
        // 参数只为通过编译。
        FakeNode() { super(null, "aaaa111122223333", "安卓测试机", 0, null); }

        @Override public List<String> onlinePeerIds() { return new ArrayList<>(online); }

        @Override public Object[] sendTextSync(List<String> targetIds, String text,
                                               long connTimeoutMs, long ackTimeoutMs) {
            callCount++;
            capturedTargets = new ArrayList<>(targetIds);
            capturedText = text;
            String mid = "mid-" + (++seq);
            capturedMid = mid;
            Map<String, String> res = new HashMap<>();
            for (String p : targetIds) res.put(p, mode);
            if (duringSend != null) { Runnable r = duringSend; duringSend = null; r.run(); }
            return new Object[]{ mid, res };
        }
    }

    /** 造一个可用的 FlashApp 实例（跳过 Application 构造，注入依赖） */
    static Object newApp(FakeNode node) throws Exception {
        Class<?> appCls = Class.forName("com.flashdrop.app.FlashApp");
        Object app = unsafeAlloc(appCls);
        put(app, "pendingSends", new ArrayList<>());
        put(app, "node", node);
        put(app, "flushing", new AtomicBoolean(false));
        put(app, "flushPool", flushExecutor());
        put(app, "mainHandler", new android.os.Handler());
        // retryTask 是匿名内部类（FlashApp$1），单独造并回填 this$0
        Class<?> rt = Class.forName("com.flashdrop.app.FlashApp$1");
        Object task = unsafeAlloc(rt);
        put(task, "this$0", app);
        put(app, "retryTask", task);
        return app;
    }

    @SuppressWarnings("unchecked")
    static List<Object> queue(Object app) throws Exception {
        Field f = app.getClass().getDeclaredField("pendingSends");
        f.setAccessible(true);
        return (List<Object>) f.get(app);
    }

    @SuppressWarnings("unchecked")
    static void addPending(Object app, Object ps) throws Exception {
        queue(app).add(ps);
    }

    static Object newTextSend(String text, List<String> targets, boolean broadcast)
            throws Exception {
        Class<?> c = Class.forName("com.flashdrop.app.FlashApp$PendingSend");
        return c.getConstructor(List.class, List.class, String.class, boolean.class)
                .newInstance(new ArrayList<>(), targets, text, broadcast);
    }

    @SuppressWarnings("unchecked")
    static void flush(Object app, final List<Object> textMids) throws Exception {
        Class<?> appCls = Class.forName("com.flashdrop.app.FlashApp");
        Method m = appCls.getMethod("flushPendingSendsAsync",
                java.util.function.Consumer.class,
                java.util.function.Consumer.class,
                java.util.function.BiConsumer.class);
        m.invoke(app,
                (java.util.function.Consumer<Integer>) sent -> { },
                (java.util.function.Consumer<Object>) ps -> { },
                (java.util.function.BiConsumer<Object, String>) (ps, mid) -> textMids.add(mid));
        awaitFlush(app);
    }

    static String summary(Object ps) throws Exception {
        return (String) ps.getClass().getMethod("summary").invoke(ps);
    }

    // ================= 用例 =================

    static Object app; static FakeNode node;
    static List<Object> textMids;

    static void reset(String onlineIds, String mode) throws Exception {
        // ★ 必须用 Unsafe 分配：FakeNode 的构造器只是为通过编译而存在，
        //   真跑起来会因 ctx 为 null 而 NPE。
        node = (FakeNode) unsafeAlloc(FakeNode.class);
        node.online = onlineIds.isEmpty() ? new ArrayList<>()
                : new ArrayList<>(Arrays.asList(onlineIds.split(",")));
        node.mode = mode;
        app = newApp(node);
        textMids = new ArrayList<>();
    }

    public static void main(String[] args) throws Exception {
        System.out.println("========================================================");
        System.out.println(" RT11815 离线待发队列「确认送达才移除」行为测试");
        System.out.println("========================================================");

        // ---------- §1 全部送达 → 条目移除 ----------
        sec("§1 全部送达 → 条目应被移出队列");
        reset("winpc0011", "ok");
        addPending(app, newTextSend("你好", new ArrayList<>(), true));
        flush(app, textMids);
        eq("队列已清空", queue(app).size(), 0);
        eq("确实调用了 sendTextSync", node.callCount, 1);
        check("回填了真实 mid（非 null）", !textMids.isEmpty() && textMids.get(0) != null);
        eq("冒烟：群发内容原样送达", node.capturedText, "你好");

        // ---------- §2 全部失败 → 条目必须保留（核心回归） ----------
        sec("§2 全部失败（wait_conn 失败）→ 条目必须保留，不能丢");
        reset("winpc0011", "failed");
        addPending(app, newTextSend("离线消息", new ArrayList<>(), true));
        flush(app, textMids);
        eq("★ 队列保留 1 条（v1.18.13 会错删成 0）", queue(app).size(), 1);
        eq("未回填 mid（没发出去就不该有气泡）", textMids.size(), 0);

        // ---------- §3 超时同样保留 ----------
        sec("§3 ack 超时 → 条目同样保留（等重试）");
        reset("winpc0011", "timeout");
        addPending(app, newTextSend("会超时的消息", new ArrayList<>(), true));
        flush(app, textMids);
        eq("★ 队列保留 1 条", queue(app).size(), 1);

        // ---------- §4 目标尚未上线 → 保留 ----------
        sec("§4 定向目标还没上线 → 条目保留等待");
        reset("", "ok");                       // 没有任何在线设备
        List<String> target = new ArrayList<>(Arrays.asList("winpc0011"));
        addPending(app, newTextSend("等对方上线", target, false));
        flush(app, textMids);
        eq("★ 队列保留 1 条", queue(app).size(), 1);
        eq("没有调用发送（无在线目标）", node.callCount, 0);

        // ---------- §5 flush 期间新增的条目不被误删 ----------
        sec("§5 flush 进行中用户又加了一条 → 新条目不能被误删");
        reset("winpc0011", "ok");
        addPending(app, newTextSend("第一条", new ArrayList<>(), true));
        final Object[] added = new Object[1];
        node.duringSend = () -> {
            try {
                added[0] = newTextSend("第二条(发送期间新增)", new ArrayList<>(), true);
                addPending(app, added[0]);
            } catch (Exception ignored) { }
        };
        flush(app, textMids);
        eq("★ 只剩新增的那条（旧的已送达被移除）", queue(app).size(), 1);
        if (added[0] != null) {
            eq("留下的是新增条目", summary(queue(app).get(0)),
                    "第二条(发送期间新增)");
        }

        // ---------- §6 队列非空时会安排周期重试 ----------
        sec("§6 失败后必须安排周期重试（否则永远不会再发）");
        android.os.Handler.DELAYED.clear();
        reset("winpc0011", "failed");
        addPending(app, newTextSend("需要重试", new ArrayList<>(), true));
        flush(app, textMids);
        check("★ 已安排 postDelayed 重试任务", !android.os.Handler.DELAYED.isEmpty());

        // ---------- §7 全部送达后不安排重试 ----------
        sec("§7 队列清空后不再安排重试（避免空转）");
        android.os.Handler.DELAYED.clear();
        reset("winpc0011", "ok");
        addPending(app, newTextSend("一次成功", new ArrayList<>(), true));
        flush(app, textMids);
        eq("队列空", queue(app).size(), 0);
        check("未安排多余重试", android.os.Handler.DELAYED.isEmpty());

        System.out.println("\n========================================================");
        if (fail > 0) {
            System.out.println("失败项：");
        }
        System.out.println("RT11815：通过 " + pass + " 项，失败 " + fail + " 项");
        System.out.println("========================================================");
        System.exit(fail > 0 ? 1 : 0);
    }
}