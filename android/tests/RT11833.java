package com.flashdrop.app;

import org.json.JSONObject;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * v1.18.33 —— 「离线待发图片不显示」修复的行为测试。
 *
 * <p>用户反馈两条：
 * <ol>
 *   <li>相册发图片、对方离线 → 待发送气泡不含图片信息（渲染成普通文件卡片，
 *       看不出待发的是什么图，用户以为没加上而反复重发 —— 同一张图在
 *       电脑端"显示两遍"的根源）。</li>
 *   <li>上线补发成功后，手机端气泡不能显示图片、点开提示"图片不可用"。
 *       根因：离线队列补发走 {@code sendFileSync}，它不发 started 事件，
 *       第一个事件来自 {@code emitSendState}，而 emitSendState 事件里
 *       <b>没有 src 字段</b> → 气泡没有图片源。</li>
 * </ol>
 *
 * <p>本测试用真 FlashNode（不 start()，无网络栈）驱动事件层：
 * <pre>
 *   A 区  emitSendState 事件必须带 src（反射注入 sendInfo 后捕获 emit）
 *   B 区  sendFiles 与 sendFileSync 的 sendInfo 都要登记 src（静态结构保证）
 * </pre>
 * rebuildPendingMsgs 照片模式 / photoMode 状态行保留 ⏳ 待发送 标记为
 * MainActivity UI 逻辑，由静态断言套件 verify_v11833_gallery_fix.py 把关。
 *
 * <p>运行见 {@code tools/run_rt11833.sh}。与 RT11831 同一套反射套路。
 */
public class RT11833 {

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

    static void sec(String s) { System.out.println("\n=== " + s + " ==="); }

    static Object fieldOf(Object o, String name) throws Exception {
        Field f = o.getClass().getDeclaredField(name);
        f.setAccessible(true);
        return f.get(o);
    }

    /** FlashNode 用的 Prefs：只提供节点构造与查询所需的几个方法 */
    static class NPrefs extends Prefs {
        NPrefs(android.content.Context c) { super(c); }
        @Override public boolean isBlocked(String id) { return false; }
    }

    /** 内存版 SharedPreferences（stub 接口的内存实现，同 RT11831） */
    static class FakeSP implements android.content.SharedPreferences {
        final java.util.HashMap<String, String> m = new java.util.HashMap<>();
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

    public static void main(String[] args) throws Exception {
        System.out.println("RT11833 离线待发图片修复 行为测试");

        // ---------------- A 区：emitSendState 带 src ----------------
        sec("A. emitSendState 事件带 src（图片气泡的图片源）");
        FlashNode node = new FlashNode(new SPContext(), "self000000000000", "我", 0,
                new NPrefs(new SPContext()));
        final List<JSONObject> events = new ArrayList<>();
        node.setListener(events::add);

        // 反射注入 sendInfo / outStates（sendFileSync/sendFiles 正常路径下会登记）
        @SuppressWarnings("unchecked")
        Map<String, JSONObject> sendInfo =
                (Map<String, JSONObject>) fieldOf(node, "sendInfo");
        @SuppressWarnings("unchecked")
        Map<String, Map<String, String>> outStates =
                (Map<String, Map<String, String>>) fieldOf(node, "outStates");

        final String TID = "tid0000000000001";
        final String PID = "peer0000000000001";
        final String SRC = "content://media/external/images/media/12345";
        sendInfo.put(TID, FdProto.obj("name", "1789220342941.png",
                "size", 290548L, "mime", "image/png",
                "targets", new org.json.JSONArray(java.util.Arrays.asList(PID)),
                "src", SRC));
        Map<String, String> st = new ConcurrentHashMap<>();
        st.put(PID, "sending");
        outStates.put(TID, st);

        Method m6 = FlashNode.class.getDeclaredMethod("emitSendState",
                String.class, String.class, String.class, String.class,
                String.class, int.class);
        m6.setAccessible(true);
        m6.invoke(node, TID, PID, "started", null, null, 0);

        boolean gotStarted = false, hasSrc = false, srcOk = false, hasMime = false;
        for (JSONObject e : events) {
            if ("transfer".equals(e.optString("event"))
                    && "send".equals(e.optString("kind"))
                    && "started".equals(e.optString("state"))) {
                gotStarted = true;
                hasSrc = e.has("src") && !e.optString("src").isEmpty();
                srcOk = SRC.equals(e.optString("src"));
                hasMime = "image/png".equals(e.optString("mime"));
            }
        }
        check("A1 emitSendState 发出 started 事件", gotStarted);
        check("A2 started 事件带非空 src 字段", hasSrc);
        check("A3 src 值 = sendInfo 登记的源地址", srcOk);
        check("A4 事件同时带 mime（UI 照片模式判定依赖）", hasMime);

        // 终态事件同样要带 src（失败/重试路径建的气泡也能拿到源）
        events.clear();
        m6.invoke(node, TID, PID, "failed", "对方接收失败", null, 1);
        boolean failedHasSrc = false;
        for (JSONObject e : events) {
            if ("failed".equals(e.optString("state"))) {
                failedHasSrc = SRC.equals(e.optString("src"));
            }
        }
        check("A5 failed 事件同样带 src", failedHasSrc);

        // 6 参重载的 5 参便捷版也要带 src
        events.clear();
        Method m5 = FlashNode.class.getDeclaredMethod("emitSendState",
                String.class, String.class, String.class, String.class, String.class);
        m5.setAccessible(true);
        m5.invoke(node, TID, PID, "retrying", "连接中断", null);
        boolean retryHasSrc = false;
        for (JSONObject e : events) {
            if ("retrying".equals(e.optString("state"))) {
                retryHasSrc = SRC.equals(e.optString("src"));
            }
        }
        check("A6 retrying 事件（5 参重载）带 src", retryHasSrc);

        // ---------------- B 区：sendInfo 登记完整性 ----------------
        sec("B. sendInfo 登记 src（sendFiles / sendFileSync 共用数据源）");
        // sendFileSync 与 sendFiles 都往 sendInfo 里 put "src"（源码级保证，
        // 这里验证登记后的 emitSendState 全链路）—— B 区做行为级验证：
        // 用一个完整的 tid 生命周期（登记→started→ok）检查每条事件都有 src。
        final String T2 = "tid0000000000002";
        sendInfo.put(T2, FdProto.obj("name", "1000404252.jpg",
                "size", 290548L, "mime", "image/jpeg",
                "targets", new org.json.JSONArray(java.util.Arrays.asList(PID)),
                "src", "file:///storage/emulated/0/Pictures/x.jpg"));
        Map<String, String> st2 = new ConcurrentHashMap<>();
        st2.put(PID, "sending");
        outStates.put(T2, st2);
        events.clear();
        m6.invoke(node, T2, PID, "started", null, null, 0);
        m6.invoke(node, T2, PID, "ok", null, "file:///storage/emulated/0/Pictures/x.jpg", 0);
        int transferN = 0, withSrc = 0;
        for (JSONObject e : events) {
            if ("transfer".equals(e.optString("event"))
                    && "send".equals(e.optString("kind"))) {
                transferN++;
                if (!e.optString("src").isEmpty()) withSrc++;
            }
        }
        check("B1 一次发送生命周期产生 2 条 transfer 事件", transferN == 2,
                "实际 " + transferN);
        check("B2 每条事件都带 src", transferN > 0 && withSrc == transferN,
                withSrc + "/" + transferN);

        // sendInfo 缺 src（异常数据）时不抛异常、事件仍发出（src 为空串）
        final String T3 = "tid0000000000003";
        sendInfo.put(T3, FdProto.obj("name", "a.txt", "size", 1, "mime", "text/plain",
                "targets", new org.json.JSONArray(java.util.Arrays.asList(PID))));
        Map<String, String> st3 = new ConcurrentHashMap<>();
        st3.put(PID, "sending");
        outStates.put(T3, st3);
        events.clear();
        boolean threw = false;
        try {
            m6.invoke(node, T3, PID, "started", null, null, 0);
        } catch (Throwable t) {
            threw = true;
        }
        check("B3 sendInfo 无 src 时容错（不抛异常）", !threw);
        check("B4 sendInfo 无 src 时事件仍发出", !events.isEmpty());

        System.out.println("\n结果: " + pass + " 通过, " + fail + " 失败");
        if (fail > 0) System.exit(1);
    }
}
