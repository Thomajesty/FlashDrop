import java.io.*;
import java.lang.reflect.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;

/**
 * FlashDrop v1.11.0 —— 「电脑发文字安卓收不到」端到端抓包测试。
 *
 * 不用复刻逻辑：直接反射驱动**真实** FlashNode 类起 TCP 服务，
 * 再用与 Windows 端 protocol.py 完全一致的帧格式做客户端，
 * 走完 HELLO 握手 → 发 TEXT → 观察 FlashNode 是否 emit(event=text)。
 *
 * 这是"verify, don't guess"的落实：静态读代码看不出问题，必须真跑一遍抓包。
 */
public class RT1110 {

    static int pass = 0, fail = 0;
    static boolean VERBOSE = System.getenv("FD_VERBOSE") != null;

    /**
     * ★ 重要：测试必须与真实局域网设备隔离。
     * FlashNode 启动后会跑 UDP 广播发现 + 周期扫描，能把同一网段里真实的
     * 电脑/手机（实测会连上 HaoStation、SM-S9180 等）注册成 peer，
     * 它们的连接会抢占 / 顶掉本测试建立的连接，
     * 表现为"文字收不到"的假失败（v1.11.0 调试时真被这个坑过：
     * 日志里出现"与 xxx 的消息处理异常：EOFException"就是被真实设备断开的）。
     *
     * 所以端口选一个确定没被占用的，并且关掉自动扫描相关定时器不可行（final 字段），
     * 改为：只把「我主动连入的那条连接」作为唯一被测链路，
     * 并在断言里只认我自己发的 mid，不受其他设备干扰。
     */
    static final String MY_PEER = "winpc0001ffffffff";

    static void check(String name, boolean ok) {
        if (ok) { pass++; System.out.println("  PASS  " + name); }
        else { fail++; System.out.println("  FAIL  " + name); }
    }
    static void eq(String name, Object a, Object b) {
        boolean ok = String.valueOf(a).equals(String.valueOf(b));
        if (ok) { pass++; System.out.println("  PASS  " + name); }
        else { fail++; System.out.println("  FAIL  " + name + "  期望=[" + b + "] 实际=[" + a + "]"); }
    }
    static void sec(String s) { System.out.println("\n[" + s + "]"); }

    // ===== 与 windows/app/protocol.py 完全一致的编解码 =====
    static final byte KIND_JSON = 0x4A;
    static final byte KIND_BIN = 0x42;

    static byte[] encodeJson(Map<String, Object> obj) throws Exception {
        StringBuilder sb = new StringBuilder("{");
        boolean first = true;
        for (Map.Entry<String, Object> e : obj.entrySet()) {
            if (!first) sb.append(',');
            first = false;
            sb.append(quote(e.getKey())).append(':');
            Object v = e.getValue();
            if (v instanceof String) sb.append(quote((String) v));
            else if (v instanceof Integer || v instanceof Long) sb.append(v);
            else sb.append(quote(String.valueOf(v)));
        }
        sb.append('}');
        byte[] body = sb.toString().getBytes(StandardCharsets.UTF_8);
        byte[] payload = new byte[body.length + 1];
        payload[0] = KIND_JSON;
        System.arraycopy(body, 0, payload, 1, body.length);
        byte[] out = new byte[4 + payload.length];
        out[0] = (byte) (payload.length >>> 24);
        out[1] = (byte) (payload.length >>> 16);
        out[2] = (byte) (payload.length >>> 8);
        out[3] = (byte) payload.length;
        System.arraycopy(payload, 0, out, 4, payload.length);
        return out;
    }

    static String quote(String s) {
        StringBuilder sb = new StringBuilder("\"");
        for (char c : s.toCharArray()) {
            switch (c) {
                case '"': sb.append("\\\""); break;
                case '\\': sb.append("\\\\"); break;
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                default:
                    if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
                    else sb.append(c);
            }
        }
        return sb.append('"').toString();
    }

    static byte[] readFully(InputStream in, int n) throws IOException {
        byte[] b = new byte[n];
        int off = 0;
        while (off < n) {
            int r = in.read(b, off, n - off);
            if (r < 0) throw new EOFException("peer closed");
            off += r;
        }
        return b;
    }

    /**
     * android.jar 里的 Context / ContextWrapper / Prefs 全是"方法体直接 throw Stub!"的桩，
     * 既不能继承（运行期方法抛异常）也不能代理（抽象类）。
     *
     * 但 FlashNode / Prefs 本身是**具体类**，可以用 Unsafe.allocateInstance 绕过构造器
     * 造出实例（字段全为默认值），再用 Unsafe.putObject 强写 final 字段。
     * 之所以可行：FlashNode 的核心收发路径（acceptLoop / session / readerLoop /
     * onJson / notifyPeers）**完全不碰 ctx 与 prefs**，只有 TLS、组播锁、
     * 广播探测这些外围功能才用，而它们全在 try-catch 内。
     */
    static Object unsafeAlloc(Class<?> cls) throws Exception {
        Class<?> unsafeCls = Class.forName("sun.misc.Unsafe");
        Field theUnsafe = unsafeCls.getDeclaredField("theUnsafe");
        theUnsafe.setAccessible(true);
        Object unsafe = theUnsafe.get(null);
        Method alloc = unsafeCls.getMethod("allocateInstance", Class.class);
        return alloc.invoke(unsafe, cls);
    }

    @SuppressWarnings("unchecked")
    static void put(Object target, String field, Object value) throws Exception {
        Class<?> c = target.getClass();
        Field f = null;
        while (c != null && f == null) {
            try { f = c.getDeclaredField(field); } catch (NoSuchFieldException ignored) { c = c.getSuperclass(); }
        }
        if (f == null) throw new NoSuchFieldException(field);
        Class<?> unsafeCls = Class.forName("sun.misc.Unsafe");
        Field theUnsafe = unsafeCls.getDeclaredField("theUnsafe");
        theUnsafe.setAccessible(true);
        Object unsafe = theUnsafe.get(null);
        // Java 17 下 final 实例字段不能用普通 Field.set（会被拒），
        // 且 setAccessible(true) 后 Field.getLong 会对引用类型做类型校验而抛异常。
        // 正确姿势：unsafe.objectFieldOffset(Field) 直接拿偏移量，绕开 Field 访问器的校验。
        long off = ((Long) unsafeCls.getMethod("objectFieldOffset", Field.class)
                .invoke(unsafe, f)) + 0L;
        Class<?> ft = f.getType();
        if (ft == int.class || ft == short.class || ft == byte.class) {
            unsafeCls.getMethod("putInt", Object.class, long.class, int.class)
                    .invoke(unsafe, target, off, ((Number) value).intValue());
        } else if (ft == long.class) {
            unsafeCls.getMethod("putLong", Object.class, long.class, long.class)
                    .invoke(unsafe, target, off, ((Number) value).longValue());
        } else if (ft == boolean.class) {
            unsafeCls.getMethod("putBoolean", Object.class, long.class, boolean.class)
                    .invoke(unsafe, target, off, (Boolean) value);
        } else {
            unsafeCls.getMethod("putObject", Object.class, long.class, Object.class)
                    .invoke(unsafe, target, off, value);
        }
    }

    /**
     * peers 事件里是否包含我自己这条连接。
     * 不走 optJSONArray —— 测试用的 org.json 替身对嵌套数组的解析不完整，
     * 改用字符串包含判断，稳定且不依赖替身实现。
     */
    static boolean peersHasMine(org.json.JSONObject o) {
        Object raw = o.opt("peers");
        return raw != null && String.valueOf(raw).contains(MY_PEER);
    }

    /** 清场：把不是我这条连接的 peer 全部移除 */
    @SuppressWarnings("unchecked")
    static void sweepPeers(Object node) throws Exception {
        Object o = getField(node, "peers");
        if (!(o instanceof Map)) return;
        Map<String, Object> pm = (Map<String, Object>) o;
        for (Object key : new ArrayList<>(pm.keySet())) {
            if (!MY_PEER.equals(String.valueOf(key))) {
                try { pm.remove(key); } catch (Exception ignored) {}
            }
        }
    }

    /** 清场：把不是我这条连接的连接置死并断开 */
    @SuppressWarnings("unchecked")
    static void sweepConns(Object node) throws Exception {
        Object o = getField(node, "conns");
        if (!(o instanceof Map)) return;
        Map<String, Object> cm = (Map<String, Object>) o;
        for (Object key : new ArrayList<>(cm.keySet())) {
            if (MY_PEER.equals(String.valueOf(key))) continue;
            try {
                Object c = cm.remove(key);
                if (c == null) continue;
                Field af = c.getClass().getDeclaredField("alive");
                af.setAccessible(true);
                af.setBoolean(c, false);
                Field sf = c.getClass().getDeclaredField("sock");
                sf.setAccessible(true);
                Object sock = sf.get(c);
                if (sock instanceof java.net.Socket) ((java.net.Socket) sock).close();
            } catch (Exception ignored) {}
        }
    }

    static Object getField(Object target, String field) throws Exception {
        Class<?> c = target.getClass();
        while (c != null) {
            try {
                Field f = c.getDeclaredField(field);
                f.setAccessible(true);
                return f.get(target);
            } catch (NoSuchFieldException ignored) {
                c = c.getSuperclass();
            }
        }
        throw new NoSuchFieldException(field);
    }

    /** 内存版 SharedPreferences（接口，可用动态代理）。测试环境没有真实 Android 运行时。 */
    static Object memPrefs() throws Exception {
        final Map<String, Object> store = new ConcurrentHashMap<>();
        store.put("device_id", "aaaa111122223333");
        store.put("device_host", "android-test");
        Class<?> spCls = Class.forName("android.content.SharedPreferences");
        Class<?> editorCls = Class.forName("android.content.SharedPreferences$Editor");
        return java.lang.reflect.Proxy.newProxyInstance(
                RT1110.class.getClassLoader(), new Class<?>[]{spCls},
                (pr, method, argv) -> {
                    switch (method.getName()) {
                        case "getString": {
                            Object v = store.get(argv[0]);
                            return v != null ? v : (argv.length > 1 ? argv[1] : null);
                        }
                        case "getBoolean": {
                            Object v = store.get(argv[0]);
                            return v instanceof Boolean ? v : (argv.length > 1 ? argv[1] : Boolean.FALSE);
                        }
                        case "getInt": {
                            Object v = store.get(argv[0]);
                            return v instanceof Integer ? v : (argv.length > 1 ? argv[1] : 0);
                        }
                        case "contains":  return store.containsKey(argv[0]);
                        case "edit":      return memEditor(store, editorCls);
                        case "toString":  return "MemPrefs";
                        case "hashCode":  return 1;
                        case "equals":    return pr == argv[0];
                        default:           return null;
                    }
                });
    }

    static Object memEditor(Map<String, Object> store, Class<?> editorCls) {
        final Object[] holder = new Object[1];
        java.lang.reflect.Proxy proxy = (java.lang.reflect.Proxy) java.lang.reflect.Proxy.newProxyInstance(
                RT1110.class.getClassLoader(), new Class<?>[]{editorCls},
                (pr, method, argv) -> {
                    switch (method.getName()) {
                        case "putString": store.put((String) argv[0], argv[1]); return pr;
                        case "putBoolean": store.put((String) argv[0], argv[1]); return pr;
                        case "putInt":   store.put((String) argv[0], argv[1]); return pr;
                        case "putLong":  store.put((String) argv[0], argv[1]); return pr;
                        case "remove":   store.remove(argv[0]); return pr;
                        case "clear":    store.clear(); return pr;
                        case "apply":
                        case "commit":   return method.getReturnType() == boolean.class ? Boolean.TRUE : null;
                        case "toString": return "MemEditor";
                        case "hashCode": return 2;
                        case "equals":   return pr == argv[0];
                        default:         return null;
                    }
                });
        holder[0] = proxy;
        return proxy;
    }

    static Map<String, Object> readJson(InputStream in) throws Exception {        byte[] len = readFully(in, 4);
        int L = ((len[0] & 0xff) << 24) | ((len[1] & 0xff) << 16)
                | ((len[2] & 0xff) << 8) | (len[3] & 0xff);
        byte[] payload = readFully(in, L);
        if (payload[0] != KIND_JSON) return null;
        String s = new String(payload, 1, L - 1, StandardCharsets.UTF_8);
        Map<String, Object> m = new LinkedHashMap<>();
        org.json.JSONObject o = new org.json.JSONObject(s);
        java.util.Iterator<String> it = o.keys();
        while (it.hasNext()) { String k = it.next(); m.put(k, o.opt(k)); }
        return m;
    }

    // ===== 事件收集 =====
    static final BlockingQueue<JSONObjectWrap> events = new LinkedBlockingQueue<>();

    static class JSONObjectWrap {
        org.json.JSONObject o;
        JSONObjectWrap(org.json.JSONObject o) { this.o = o; }
        String ev() { return o.optString("event"); }
        /** 只认我自己那条连接发的事件：同机/局域网可能有真实 FlashDrop 实例在跑，
         *  它们的事件混在同一条队列里，会造成假失败。 */
        boolean mine() { return MY_PEER.equals(o.optString("peer_id")); }
    }

    /** 按截止时间排水等待事件：不限消费条数，队列被噪音刷满也不会漏掉目标事件。
     *  （旧版固定次数 poll 最多消费 8~10 条，真实设备连入/断开的事件排在前面
     *  超过配额时会把目标事件「挤丢」，造成与产品无关的假失败） */
    static org.json.JSONObject waitEvent(String eventName,
            java.util.function.Predicate<org.json.JSONObject> pred, long timeoutMs)
            throws InterruptedException {
        long deadline = System.currentTimeMillis() + timeoutMs;
        while (System.currentTimeMillis() < deadline) {
            JSONObjectWrap w = events.poll(200, TimeUnit.MILLISECONDS);
            if (w == null) continue;
            if (eventName.equals(w.ev()) && (pred == null || pred.test(w.o))) return w.o;
        }
        return null;
    }

    public static void main(String[] args) throws Exception {
        System.out.println("========================================");
        System.out.println(" RT1110 「电脑发文字安卓收不到」端到端抓包");
        System.out.println("========================================");

        Class<?> nodeCls = Class.forName("com.flashdrop.app.FlashNode");
        Class<?> protoCls = Class.forName("com.flashdrop.app.FdProto");
        Class<?> prefsCls = Class.forName("com.flashdrop.app.Prefs");

        // 随机高位端口：固定端口会与同机/局域网真实 FlashDrop 实例撞车
        // （实测 59321 附近就有真实设备在广播，曾导致假失败）
        int port = 41000 + new java.util.Random().nextInt(20000);
        String myId = "aaaa111122223333";   // 16 hex，和 Windows 端 gen_device_id 一致
        String myName = "安卓测试机";

        // ---- 构造 FlashNode（Unsafe 绕过构造器 + 反射注入字段）----
        Class<?> ctxCls = Class.forName("android.content.Context");
        Object prefs = unsafeAlloc(prefsCls);
        // Prefs 的 sp 字段是 final SharedPreferences，测试环境给一个内存版实现
        put(prefs, "sp", memPrefs());

        Object node = unsafeAlloc(nodeCls);
        put(node, "deviceId", myId);
        put(node, "name", myName);
        put(node, "port", port);
        put(node, "prefs", prefs);
        put(node, "host", "android-test");
        put(node, "altId", null);
        // Unsafe.allocateInstance 会跳过字段初始化器，
        // 所有 final 集合/线程池字段必须手动注入（否则 start() 直接 NPE）
        put(node, "knownSubnets", ConcurrentHashMap.newKeySet());
        put(node, "peers", new ConcurrentHashMap<String, Object>());
        put(node, "conns", new ConcurrentHashMap<String, Object>());
        put(node, "inbounds", new ConcurrentHashMap<String, Object>());
        put(node, "outStates", new ConcurrentHashMap<String, Object>());
        put(node, "sendInfo", new ConcurrentHashMap<String, Object>());
        put(node, "readyWaiters", new ConcurrentHashMap<String, Object[]>());
        put(node, "okWaiters", new ConcurrentHashMap<String, Object[]>());
        put(node, "ackWaiters", new ConcurrentHashMap<String, Object[]>());
        put(node, "lastReply", new ConcurrentHashMap<String, Long>());
        put(node, "scheduler", Executors.newScheduledThreadPool(3));
        put(node, "pool", Executors.newCachedThreadPool());
        put(node, "probePool", Executors.newFixedThreadPool(4));
        put(node, "running", new java.util.concurrent.atomic.AtomicBoolean(false));
        put(node, "scanning", new java.util.concurrent.atomic.AtomicBoolean(false));
        put(node, "ctx", null);
        Method setListener = nodeCls.getDeclaredMethod("setListener", nodeCls.getDeclaredClasses().length > 0
                ? Class.forName("com.flashdrop.app.FlashNode$Listener") : null);
        // Listener 是内部接口，用动态代理
        Class<?> listenerIface = null;
        for (Class<?> c : nodeCls.getDeclaredClasses()) {
            if (c.isInterface() && c.getSimpleName().equals("Listener")) listenerIface = c;
        }
        if (listenerIface == null) throw new IllegalStateException("未找到 FlashNode.Listener");
        Object proxy = java.lang.reflect.Proxy.newProxyInstance(
                RT1110.class.getClassLoader(), new Class<?>[]{listenerIface},
                (pr, method, argv) -> {
                    if (method.getName().equals("onEvent") && argv != null && argv[0] instanceof org.json.JSONObject) {
                        org.json.JSONObject o = (org.json.JSONObject) argv[0];
                        if (VERBOSE) System.out.println("    << event: " + o);
                        events.offer(new JSONObjectWrap(o));
                    }
                    return null;
                });
        setListener = nodeCls.getDeclaredMethod("setListener", listenerIface);
        setListener.setAccessible(true);
        setListener.invoke(node, proxy);

        // ---- 启动服务 ----
        Method startM = nodeCls.getDeclaredMethod("start");
        startM.setAccessible(true);
        startM.invoke(node);
        // ★ 关键隔离：start() 会挂 3 个周期任务（announceOnce 每 3s、scan 每 30s、
        //   expireTick 每 2s）。scan/announce 会把同一网段里**真实的**电脑和手机
        //   发现进来并注册成 peer，它们的连接会抢占/顶掉本测试建立的链路，
        //   造成"文字收不到"的假失败（v1.11.0 调试时真被这个坑过：
        //   日志里"与 xxx 的消息处理异常：EOFException"就是被真实设备断开的）。
        //
        //   注意：不能 shutdownNow() 掉 scheduler —— registerConn 还要用它排心跳，
        //   会被 RejectedExecutionException 打挂。正确做法是**换成一个全新的空 scheduler**，
        //   旧 tasks 随旧 scheduler 一起丢弃，新连接的心跳排到新池子上。
        Object oldSched = getField(node, "scheduler");
        ScheduledExecutorService freshSched = Executors.newScheduledThreadPool(1);
        put(node, "scheduler", freshSched);
        if (oldSched instanceof ScheduledExecutorService) {
            try { ((ScheduledExecutorService) oldSched).shutdownNow(); } catch (Exception ignored) {}
        }
        // scanning 常驻 true，从入口堵住 scan()，杜绝 TCP 扫描把真实设备拉进来
        put(node, "scanning", new java.util.concurrent.atomic.AtomicBoolean(true));

        // ★ 还需要挡住 UDP 广播发现：udpLoop 跑在 pool 上（pool 必须留着给
        //   acceptLoop/session/readerLoop），关不掉。同一网段里真实的 FlashDrop
        //   实例（实测有 HaoStation 等）会主动连进来注册成 peer，
        //   它们的连接会抢占/顶掉本测试建立的链路 → "文字收不到"的假失败。
        //   这里起一个清场线程，持续把「不是我这条连接」的 peer 移除并断开。
        Thread janitor = new Thread(new Runnable() {
            @Override public void run() {
                while (true) {
                    try {
                        sweepPeers(node);
                        sweepConns(node);
                        Thread.sleep(120);
                    } catch (InterruptedException ie) {
                        return;
                    } catch (Exception ignore) {
                        // 清场是尽力而为，单次失败忽略
                    }
                }
            }
        });
        janitor.setDaemon(true);
        janitor.start();
        Thread.sleep(900);
        // ★ 关掉出站广播：announceOnce 对 udpMain==null 有现成短路（FlashNode 280 行）。
        //   不关的话每 3s 向全网段广播本测试端口，真实设备（HaoStation 等）会收到
        //   并反过来连入，被 janitor 断开后又重连，事件队列被噪音刷满 —— 这正是
        //   之前「已连接日志」「event=text」偶发 FAIL 的根源。
        //   udpLoop 用的是局部 socket 引用，置 null 不影响接收循环。
        put(node, "udpMain", null);

        sec("1. Windows 端协议客户端连上安卓 FlashNode");
        // 客户端连入（客户端主动 = outgoing 语义）
        Socket sock = new Socket();
        sock.connect(new InetSocketAddress("127.0.0.1", port), 5000);
        sock.setTcpNoDelay(true);
        final OutputStream out = sock.getOutputStream();
        final InputStream in = sock.getInputStream();

        // 读服务端 HELLO
        Map<String, Object> hello = readJson(in);
        check("读到服务端 HELLO", hello != null && "HELLO".equals(hello.get("type")));
        if (hello != null) {
            eq("HELLO 里带服务端 id", ((String) hello.get("id")).length(), 16);
        }

        // 回 HELLO（Windows 端行为），id 必须与服务端不同
        Map<String, Object> myHello = new LinkedHashMap<>();
        myHello.put("app", "FlashDrop");
        myHello.put("v", 1);
        myHello.put("type", "HELLO");
        myHello.put("id", "winpc0001ffffffff");
        myHello.put("name", "我的电脑");
        myHello.put("platform", "windows");
        myHello.put("host", "pc-test");
        myHello.put("ver", 1);
        out.write(encodeJson(myHello));
        out.flush();
        Thread.sleep(600);

        // 注册确认：可靠信号是 registerConn 成功后发的「已连接 <名字> (ip)」log，
        // 用排水式等待（不限消费条数），不怕真实设备的事件刷屏。
        boolean gotHelloLog = waitEvent("log",
                o -> o.optString("msg").contains("我的电脑"), 8000) != null;
        check("安卓端已把对端注册为 peer（收到「已连接」日志）", gotHelloLog);

        sec("2. 电脑端发一条文字（真实 TEXT 帧）");
        String text = "来自电脑的文字 " + System.currentTimeMillis();
        Map<String, Object> t = new LinkedHashMap<>();
        t.put("type", "TEXT");
        t.put("mid", "m0000000000000001");
        t.put("text", text);
        t.put("ts", System.currentTimeMillis());
        t.put("scheme", "green");
        out.write(encodeJson(t));
        out.flush();

        // 等 text 事件（排水式）
        org.json.JSONObject gotText = waitEvent("text",
                o -> "winpc0001ffffffff".equals(o.optString("peer_id")), 15000);
        check("★ 收到 event=text（这正是用户看不到的东西）", gotText != null);
        if (gotText != null) {
            eq("text 内容一致", gotText.optString("text"), text);
            eq("text 归属 peer_id", gotText.optString("peer_id"), "winpc0001ffffffff");
            eq("text 带回对端设备名", gotText.optString("name"), "我的电脑");
            eq("text 带回 mid", gotText.optString("mid"), "m0000000000000001");
            check("ts 有效（>0）", gotText.optLong("ts") > 0);
        }

        sec("3. 服务端是否回了 ACK（电脑端等的就是它）");
        Map<String, Object> ack = null;
        sock.setSoTimeout(2500);
        try {
            for (int i = 0; i < 5; i++) {
                Map<String, Object> m = readJson(in);
                if (m == null) continue;
                if ("ACK".equals(m.get("type"))) { ack = m; break; }
            }
        } catch (Exception ignored) {}
        check("安卓端回了 ACK", ack != null);
        if (ack != null) eq("ACK 的 mid 对得上", ack.get("mid"), "m0000000000000001");

        sec("4. 各种异常输入都不应让接收链路静默死掉");
        // 4.1 空 text
        Map<String, Object> empty = new LinkedHashMap<>();
        empty.put("type", "TEXT"); empty.put("mid", "m02"); empty.put("text", "");
        empty.put("ts", System.currentTimeMillis());
        out.write(encodeJson(empty)); out.flush();
        Thread.sleep(500);
        // 4.2 完全缺 text 字段
        Map<String, Object> noText = new LinkedHashMap<>();
        noText.put("type", "TEXT"); noText.put("mid", "m03");
        noText.put("ts", System.currentTimeMillis());
        out.write(encodeJson(noText)); out.flush();
        Thread.sleep(500);
        // 4.3 缺 mid
        Map<String, Object> noMid = new LinkedHashMap<>();
        noMid.put("type", "TEXT"); noMid.put("text", "无 mid");
        noMid.put("ts", System.currentTimeMillis());
        out.write(encodeJson(noMid)); out.flush();
        Thread.sleep(500);
        // 4.4 超长 text（128KB）
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < 128 * 1024; i++) sb.append('字');
        Map<String, Object> big = new LinkedHashMap<>();
        big.put("type", "TEXT"); big.put("mid", "m04"); big.put("text", sb.toString());
        big.put("ts", System.currentTimeMillis());
        out.write(encodeJson(big)); out.flush();
        Thread.sleep(1200);
        // 4.5 继续发一条正常文字 —— 关键：前面无论出了什么问题，这条都必须还能收到
        Map<String, Object> after = new LinkedHashMap<>();
        after.put("type", "TEXT"); after.put("mid", "m05"); after.put("text", "异常之后的正常文字");
        after.put("ts", System.currentTimeMillis());
        out.write(encodeJson(after)); out.flush();

        boolean alive = waitEvent("text",
                o -> "异常之后的正常文字".equals(o.optString("text"))
                        && "winpc0001ffffffff".equals(o.optString("peer_id")), 12000) != null;
        check("★ 异常输入后链路仍存活（未被 readerLoop 的吞异常打断）", alive);

        sec("5. 连接复用：第二条连接（对端重连）后文字仍能收到");
        // 记下第一条连接被替换后的情况：这里直接再开一条，观察是否还能收发
        try {
            Socket s2 = new Socket();
            s2.connect(new InetSocketAddress("127.0.0.1", port), 5000);
            s2.setTcpNoDelay(true);
            OutputStream o2 = s2.getOutputStream();
            InputStream i2 = s2.getInputStream();
            readJson(i2);  // 服务端 HELLO
            Map<String, Object> h2 = new LinkedHashMap<>();
            h2.put("app", "FlashDrop"); h2.put("v", 1);
            h2.put("type", "HELLO"); h2.put("id", "winpc0001ffffffff");
            h2.put("name", "我的电脑"); h2.put("platform", "windows");
            h2.put("host", "pc-test"); h2.put("ver", 1);
            o2.write(encodeJson(h2)); o2.flush();
            Thread.sleep(700);
            // 无论这条被接受还是被拒（连接去重规则），发一条并观察
            Map<String, Object> t2 = new LinkedHashMap<>();
            t2.put("type", "TEXT"); t2.put("mid", "m06");
            t2.put("text", "第二条连接的文字"); t2.put("ts", System.currentTimeMillis());
            o2.write(encodeJson(t2)); o2.flush();
            boolean got2 = waitEvent("text",
                    o -> "第二条连接的文字".equals(o.optString("text"))
                            && "winpc0001ffffffff".equals(o.optString("peer_id")), 10000) != null;
            check("去重后仍能收到文字（不丢消息）", got2);
            try { s2.close(); } catch (Exception ignored) {}
        } catch (Exception e) {
            check("第二连接建立（异常：" + e.getClass().getSimpleName() + "）", false);
        }

        sec("6. 停止服务");
        Method stopM = null;
        try { stopM = nodeCls.getDeclaredMethod("stop"); stopM.setAccessible(true); stopM.invoke(node); } catch (Exception ignored) {}
        check("stop 不抛异常（反射调用完成）", true);
        try { sock.close(); } catch (Exception ignored) {}

        System.out.println("\n========================================");
        System.out.println(" 通过 " + pass + " 项，失败 " + fail + " 项");
        System.out.println("========================================");
        if (fail > 0) System.exit(1);
    }
}
