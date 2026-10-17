package com.flashdrop.app;

import org.json.JSONArray;
import org.json.JSONObject;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

/**
 * v1.18.31 —— 「连接过的设备不能在设备列表删除」修复的行为测试。
 *
 * <p>用户反馈：安卓版里连接过的安卓手机，在设备列表删不掉。
 *
 * <p>根因有两条，本测试覆盖第一条（状态机），第二条（下拉行 ✕ 入口）由
 * 静态断言套件 {@code verify_v11831_blocklist.py} 把关：
 * <ol>
 *   <li><b>删了又复活</b>：设备还在同一网段，UDP 广播发现 +
 *       {@code rebuildSpinner} 里的 {@code rememberPeer} 会把它立刻加回列表，
 *       {@code forgetPeer} 单靠摘 known_peers 档案拦不住。</li>
 *   <li><b>没有删除入口</b>：下拉行的 ✕ 只在「有聊天记录」时出现，
 *       "连接过但从没聊过/传过"的设备行一个删除入口都没有。</li>
 * </ol>
 *
 * <p>修法 = 持久屏蔽名单（blocked_peers）+ 四层过滤：
 * <pre>
 *   Prefs.blockedPeers()      持久状态（本测试 A 区：增/删/去重/排序/重启保留）
 *   FlashNode.peerBlocked()   HELLO 级拒连（本测试 B 区）
 *   FlashNode.touchPeer()     广播级不入 peers（本测试 B 区）
 *   FlashNode.enforceBlocklist() 删除即时生效：摘 peers + 关连接（本测试 B 区）
 *   MainActivity/NodeService UI 与事件层过滤（静态断言）
 * </pre>
 *
 * <p>运行见 {@code tools/run_rt11831.sh}。与 RT11818Node 同一套反射/替身套路，
 * 不调 {@code start()}，无网络栈。
 */
public class RT11831 {

    static int pass = 0, fail = 0;

    static void check(String name, boolean ok, String extra) {
        if (ok) { pass++; System.out.println("  PASS  " + name); }
        else {
            fail++;
            System.out.println("  FAIL  " + name
                    + (extra != null && !extra.isEmpty() ? "   " + extra : ""));
        }
    }

    static void check(String name, boolean ok) { check(name, ok, null); }

    static void eq(String name, Object a, Object b) {
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

    @SuppressWarnings("unchecked")
    static <T> T invoke(Object o, String method, Class<?>[] pt, Object[] args)
            throws Exception {
        Class<?> c = o.getClass();
        while (c != null) {
            try {
                Method m = c.getDeclaredMethod(method, pt);
                m.setAccessible(true);
                return (T) m.invoke(o, args);
            } catch (NoSuchMethodException e) {
                c = c.getSuperclass();
            }
        }
        throw new NoSuchMethodException(method);
    }

    // ---------------- 测试替身 ----------------

    /** 内存版 SharedPreferences（stub 接口的内存实现） */
    static class FakeSP implements android.content.SharedPreferences {
        final Map<String, String> m = new HashMap<>();

        @Override public String getString(String k, String d) {
            String v = m.get(k); return v == null ? d : v;
        }
        @Override public int getInt(String k, int d) {
            try { return Integer.parseInt(m.get(k)); } catch (Exception e) { return d; }
        }
        @Override public boolean getBoolean(String k, boolean d) {
            String v = m.get(k); return v == null ? d : Boolean.parseBoolean(v);
        }
        @Override public long getLong(String k, long d) {
            try { return Long.parseLong(m.get(k)); } catch (Exception e) { return d; }
        }
        @Override public Editor edit() {
            return new Editor() {
                @Override public Editor putString(String k, String v) { m.put(k, v); return this; }
                @Override public Editor putInt(String k, int v) { m.put(k, String.valueOf(v)); return this; }
                @Override public Editor putBoolean(String k, boolean v) { m.put(k, String.valueOf(v)); return this; }
                @Override public Editor putLong(String k, long v) { m.put(k, String.valueOf(v)); return this; }
                @Override public void apply() {}
            };
        }
    }

    /** 返回 FakeSP 的 Context（遮蔽 android.jar 的 Stub 实现） */
    static class SPContext extends android.content.Context {
        final FakeSP sp = new FakeSP();
        @Override public android.content.SharedPreferences getSharedPreferences(String n, int mode) {
            return sp;
        }
        @Override public android.content.Context getApplicationContext() { return this; }
    }

    /** FlashNode 用的 Prefs：只覆写 isBlocked 与节点构造所需的几个方法 */
    static class FakePrefs extends Prefs {
        final Set<String> blocked = new HashSet<>();
        FakePrefs() { super(new SPContext()); }
        @Override public String deviceHost() { return "testhost"; }
        @Override public String legacyDeviceId() { return ""; }
        @Override public JSONArray knownSubnets() { return new JSONArray(); }
        @Override public boolean isBlocked(String id) { return id != null && blocked.contains(id); }
    }

    // ================= A 区：Prefs 黑名单状态机 =================

    static void testPrefsBlocklist() {
        sec("A. Prefs.blockedPeers 状态机（真实 Prefs + 内存 SharedPreferences）");

        SPContext ctx = new SPContext();
        Prefs prefs = new Prefs(ctx);

        check("初始名单为空", prefs.blockedPeers().length() == 0);
        check("未屏蔽的设备 isBlocked=false", !prefs.isBlocked("peerA"));

        prefs.blockPeer("peerA", "手机A");
        check("blockPeer 后 isBlocked=true", prefs.isBlocked("peerA"));
        eq("名单长度=1", prefs.blockedPeers().length(), 1);
        JSONObject o = prefs.blockedPeers().optJSONObject(0);
        check("条目含 id/name/ts", o != null && "peerA".equals(o.optString("id"))
                && "手机A".equals(o.optString("name")) && o.optLong("ts") > 0);

        // 幂等：重复删除同一设备只保留一条，名字刷新
        prefs.blockPeer("peerA", "手机A(改名)");
        eq("重复 blockPeer 去重后仍为 1 条", prefs.blockedPeers().length(), 1);
        eq("名字被刷新", prefs.blockedPeers().optJSONObject(0).optString("name"), "手机A(改名)");

        // 排序：后删的排最前（设置页按"最近删除"展示）
        prefs.blockPeer("peerB", "手机B");
        eq("再删一台 → 2 条", prefs.blockedPeers().length(), 2);
        eq("最近删除的排最前", prefs.blockedPeers().optJSONObject(0).optString("id"), "peerB");

        // 持久化：换一个 Prefs 实例（模拟重启进程）名单还在
        Prefs prefs2 = new Prefs(ctx);
        check("重启后名单保留", prefs2.isBlocked("peerA") && prefs2.isBlocked("peerB"));

        // 解除屏蔽
        prefs2.unblockPeer("peerA");
        check("unblockPeer 后不再屏蔽", !prefs2.isBlocked("peerA"));
        check("unblockPeer 不影响其他条目", prefs2.isBlocked("peerB"));
        eq("解除后剩 1 条", prefs2.blockedPeers().length(), 1);

        // 边界
        check("null id 不判屏蔽", !prefs2.isBlocked(null));
        check("空串 id 不判屏蔽", !prefs2.isBlocked(""));
        prefs2.blockPeer(null, "x");   // 不应崩
        prefs2.unblockPeer(null);      // 不应崩
        check("null 入参不污染名单", prefs2.blockedPeers().length() == 1);

        // 存储损坏时容错（不抛异常、不误判屏蔽）。
        // 注：真机 org.json 对 "not-json" 抛 JSONException → 被 catch → 空名单；
        //     测试桩的解析器是宽容的（会把它当成一个字符串元素），
        //     所以这里只断言"不崩 + 不误判"，空名单语义由 A 区其他用例覆盖。
        ctx.sp.edit().putString("blocked_peers", "not-json").apply();
        Prefs prefs3 = new Prefs(ctx);
        check("损坏 JSON 不抛异常", prefs3.blockedPeers() != null);
        check("损坏 JSON 时 isBlocked=false", !prefs3.isBlocked("peerB"));
        ctx.sp.edit().putString("blocked_peers", "[]").apply();
        eq("空数组文本 → 空名单", new Prefs(ctx).blockedPeers().length(), 0);
    }

    // ================= B 区：FlashNode 过滤 =================

    static void testNodeFilter() throws Exception {
        sec("B. FlashNode 广播/连接层过滤（真 FlashNode，不 start()）");

        FakePrefs prefs = new FakePrefs();
        FlashNode node = new FlashNode(new SPContext(), "self000000000000", "我", 0, prefs);
        node.setListener(e -> { });

        Map<String, FlashNode.Peer> peers =
                (Map<String, FlashNode.Peer>) fieldOf(node, "peers");

        // ---- B1. peerBlocked：HELLO 命中名单 → 拒连 ----
        prefs.blocked.add("badpeer0000000000");
        JSONObject helloBad = FdProto.obj("id", "badpeer0000000000", "name", "删掉的手机");
        Boolean r1 = invoke(node, "peerBlocked",
                new Class[]{JSONObject.class}, new Object[]{helloBad});
        check("B1 HELLO id 命中名单 → peerBlocked=true", Boolean.TRUE.equals(r1));

        JSONObject helloOk = FdProto.obj("id", "goodpeer000000000", "name", "正常手机");
        Boolean r2 = invoke(node, "peerBlocked",
                new Class[]{JSONObject.class}, new Object[]{helloOk});
        check("B1 未命中 → peerBlocked=false", Boolean.FALSE.equals(r2));

        // ---- B2. peerBlocked：跨版本身份合并（旧 ID 被删 → 新 ID 也拒） ----
        //   peers 里放一条**离线**旧设备（host=H1），对端新版以同 host 上线
        FlashNode.Peer old = new FlashNode.Peer();
        old.id = "oldpeer0000000000";
        old.host = "H1";
        old.lastSeen = 0L;                       // 离线才参与合并（mergeCandidate 只合并离线条目）
        peers.put("oldpeer0000000000", old);
        prefs.blocked.add("oldpeer0000000000");
        JSONObject helloNew = FdProto.obj("id", "newpeer0000000000", "name", "同机新版", "host", "H1");
        Boolean r3 = invoke(node, "peerBlocked",
                new Class[]{JSONObject.class}, new Object[]{helloNew});
        check("B2 合并自的旧 ID 被删 → 新 ID 也拒连", Boolean.TRUE.equals(r3));

        // ---- B3. touchPeer：命中名单 → 不入 peers，返回 null ----
        peers.clear();
        prefs.blocked.add("badpeer0000000000");
        JSONObject disc = FdProto.obj("id", "badpeer0000000000", "name", "删掉的手机");
        Object p3 = invoke(node, "touchPeer",
                new Class[]{JSONObject.class, String.class},
                new Object[]{disc, "192.168.1.50"});
        check("B3 命中名单 → touchPeer 返回 null", p3 == null);
        check("B3 命中名单 → 不进 peers", !peers.containsKey("badpeer0000000000"));

        // ---- B4. touchPeer：合并场景旧 ID 被删 → 新 ID 也不入 peers ----
        peers.clear();
        FlashNode.Peer old2 = new FlashNode.Peer();
        old2.id = "oldpeer0000000000";
        old2.host = "H1";
        old2.lastSeen = 0L;
        peers.put("oldpeer0000000000", old2);
        prefs.blocked.add("oldpeer0000000000");
        Object p4 = invoke(node, "touchPeer",
                new Class[]{JSONObject.class, String.class},
                new Object[]{FdProto.obj("id", "newpeer0000000000", "host", "H1"), "192.168.1.51"});
        check("B4 合并场景命中 → touchPeer 返回 null", p4 == null);
        check("B4 合并产生的新 ID 也不留在 peers", !peers.containsKey("newpeer0000000000"));
        check("B4 旧 ID 条目已被合并清掉", !peers.containsKey("oldpeer0000000000"));

        // ---- B5. touchPeer：正常设备照常入列（不误伤） ----
        peers.clear();
        Object p5 = invoke(node, "touchPeer",
                new Class[]{JSONObject.class, String.class},
                new Object[]{FdProto.obj("id", "goodpeer000000000", "name", "正常手机"), "192.168.1.52"});
        check("B5 正常设备 → touchPeer 返回 Peer", p5 instanceof FlashNode.Peer);
        check("B5 正常设备 → 进入 peers", peers.containsKey("goodpeer000000000"));

        // ---- B6. enforceBlocklist：删除即时生效 ----
        peers.clear();
        Map<String, FlashNode.Conn> conns =
                (Map<String, FlashNode.Conn>) fieldOf(node, "conns");
        conns.clear();

        FlashNode.Peer keep = new FlashNode.Peer();
        keep.id = "goodpeer000000000";
        keep.lastSeen = System.currentTimeMillis();
        peers.put("goodpeer000000000", keep);
        FlashNode.Conn keepConn = new FlashNode.Conn();
        keepConn.peerId = "goodpeer000000000";
        conns.put("goodpeer000000000", keepConn);

        FlashNode.Peer gone = new FlashNode.Peer();
        gone.id = "badpeer0000000000";
        gone.lastSeen = System.currentTimeMillis();
        peers.put("badpeer0000000000", gone);
        FlashNode.Conn badConn = new FlashNode.Conn();
        badConn.peerId = "badpeer0000000000";
        conns.put("badpeer0000000000", badConn);

        node.enforceBlocklist();
        check("B6 已删设备被摘出 peers", !peers.containsKey("badpeer0000000000"));
        check("B6 已删设备连接被关闭", badConn.closed && badConn.replaced);
        check("B6 已删设备连接被摘出 conns", !conns.containsKey("badpeer0000000000"));
        check("B6 正常设备 peers 保留", peers.containsKey("goodpeer000000000"));
        check("B6 正常设备连接不受影响",
                conns.containsKey("goodpeer000000000") && !keepConn.closed);

        // ---- B7. enforceBlocklist 幂等（重复调用不炸） ----
        node.enforceBlocklist();
        node.enforceBlocklist();
        check("B7 重复调用安全", !peers.containsKey("badpeer0000000000") && peers.containsKey("goodpeer000000000"));
    }

    public static void main(String[] args) throws Exception {
        System.out.println("RT11831 —— v1.18.31 删除设备（屏蔽名单）行为测试");
        testPrefsBlocklist();
        testNodeFilter();
        System.out.println("\n================================");
        System.out.println("PASS=" + pass + "  FAIL=" + fail);
        if (fail > 0) System.exit(1);
    }
}
