package com.flashdrop.app;

import android.content.Context;
import android.content.SharedPreferences;
import android.provider.Settings;

import org.json.JSONArray;

import java.security.MessageDigest;

/** SharedPreferences 封装 */
public class Prefs {
    private static final String FILE = "flashdrop_prefs";
    private final SharedPreferences sp;
    private final Context ctx;

    public Prefs(Context ctx) {
        this.ctx = ctx.getApplicationContext();
        sp = this.ctx.getSharedPreferences(FILE, Context.MODE_PRIVATE);
    }

    /** 稳定设备 ID：由 ANDROID_ID 派生，跨版本升级保持不变（避免同机多版本被识别为多设备） */
    private volatile String legacyId = "";

    private String stableId() {
        try {
            String aid = Settings.Secure.getString(ctx.getContentResolver(),
                    Settings.Secure.ANDROID_ID);
            if (aid == null || aid.isEmpty() || "9774d56d682e549c".equals(aid))
                aid = FdUtil.genId();
            MessageDigest md = MessageDigest.getInstance("MD5");
            byte[] d = md.digest(("FlashDrop|" + aid).getBytes("UTF-8"));
            StringBuilder sb = new StringBuilder();
            for (byte b : d) sb.append(String.format("%02x", b));
            return sb.substring(0, 16);
        } catch (Exception e) {
            return FdUtil.genId();
        }
    }

    public String deviceId() {
        // 每次以稳定 ID 为准（覆盖历史随机 ID，统一跨版本身份）
        String id = stableId();
        String prev = sp.getString("device_id", "");
        if (!prev.isEmpty() && !prev.equals(id)) legacyId = prev;
        if (!id.equals(prev)) {
            sp.edit().putString("device_id", id).apply();
        }
        return id;
    }

    /** 升级前旧版本使用的随机设备 ID（供广播 alt 字段，让对端合并同机身份） */
    public String legacyDeviceId() { return legacyId; }

    /** 设备唯一标识（host 字段，跨版本不变；用于对端合并同机多版本身份） */
    public String deviceHost() {
        try {
            String aid = Settings.Secure.getString(ctx.getContentResolver(),
                    Settings.Secure.ANDROID_ID);
            if (aid != null && !aid.isEmpty() && !"9774d56d682e549c".equals(aid))
                return "android-" + aid;
        } catch (Exception ignored) {}
        return stableId();
    }

    public String name(String def) { return sp.getString("name", def); }
    public void setName(String v) { sp.edit().putString("name", v).apply(); }

    public int port(int def) { return sp.getInt("port", def); }
    public void setPort(int v) { sp.edit().putInt("port", v).apply(); }

    public boolean autoAccept() { return sp.getBoolean("auto_accept", true); }
    public void setAutoAccept(boolean v) { sp.edit().putBoolean("auto_accept", v).apply(); }

    public boolean notifyOnReceive() { return sp.getBoolean("notify", true); }
    public void setNotifyOnReceive(boolean v) { sp.edit().putBoolean("notify", v).apply(); }

    /** 是否显示常驻通知（关闭后服务静默运行，通知不在通知栏显示） */
    public boolean showServiceNotification() { return sp.getBoolean("show_service_notif", true); }
    public void setShowServiceNotification(boolean v) { sp.edit().putBoolean("show_service_notif", v).apply(); }

    /** 开机自启（默认关闭；开启后开机恢复局域网接收服务） */
    public boolean autoStart() { return sp.getBoolean("auto_start", false); }
    public void setAutoStart(boolean v) { sp.edit().putBoolean("auto_start", v).apply(); }

    /** 传输加密（TLS）：与开启加密的设备自动加密通信，未开启的自动回退明文 */
    public boolean encrypt() { return sp.getBoolean("encrypt", false); }
    public void setEncrypt(boolean v) { sp.edit().putBoolean("encrypt", v).apply(); }

    /** ★ v1.18.30：软件更新（GitHub Releases，与 Windows 端对称）。
     *  last_update_check：上次启动静默检查日期（YYYY-MM-DD），每天最多一次；
     *  skipped_version：用户选择跳过此版本的版本号。 */
    public String lastUpdateCheck() { return sp.getString("last_update_check", ""); }
    public void setLastUpdateCheck(String v) { sp.edit().putString("last_update_check", v).apply(); }
    public String skippedVersion() { return sp.getString("skipped_version", ""); }
    public void setSkippedVersion(String v) { sp.edit().putString("skipped_version", v).apply(); }

    /** 待发文件队列（JSON），目标离线时保存，上线自动发送 */
    public String pendingSends() { return sp.getString("pending_sends", "[]"); }
    public void setPendingSends(String v) { sp.edit().putString("pending_sends", v).apply(); }

    /** 主题：dark / light / system（跟随系统） */
    public String theme() { return sp.getString("theme", "system"); }
    public void setTheme(String v) { sp.edit().putString("theme", v).apply(); }

    /** 气泡配色方案 key：blue/green/purple/orange/pink */
    public String bubbleScheme() { return sp.getString("bubble_scheme", "blue"); }
    public void setBubbleScheme(String v) { sp.edit().putString("bubble_scheme", v).apply(); }

    /**
     * v1.11.0：界面动效开关（默认开）。
     * 关闭后所有过渡动画（页面进入/退出、弹窗、气泡入场、按钮按压）全部改为瞬时，
     * 适合低端机提速或对动画敏感的用户。系统层面若已关动画
     * （开发者选项 → 动画时长 = 0），FdAnim 会自动尊重，不需要在这里设置。
     */
    public boolean animations() { return sp.getBoolean("anim_enabled", true); }
    public void setAnimations(boolean v) {
        sp.edit().putBoolean("anim_enabled", v).apply();
        // FdAnim 缓存了 Prefs 实例用于高频判断，这里必须让它重新读，否则开关点了不生效
        FdAnim.invalidatePrefCache();
    }

    public JSONArray knownSubnets() {
        try { return new JSONArray(sp.getString("known_subnets", "[]")); }
        catch (Exception e) { return new JSONArray(); }
    }

    public void knownSubnets(JSONArray arr) {
        sp.edit().putString("known_subnets", arr.toString()).apply();
    }

    // ================= v1.18.9 新增 =================

    /**
     * 「离线聊天」开关（默认开启）。
     *
     * 用户第 5 条需求：设置页新增一个与「保存聊天」并存的开关，
     * 用来**展示和使用**离线功能 —— 保留对话框、能发离线消息、
     * 能看发送过的历史。关闭后设备列表只显示当前在线设备。
     *
     * 与「保存聊天」（history_keep）的关系：两者正交互不冲突 ——
     *   · 保存聊天：控制**是否落盘**聊天记录（关掉就不再持久化）
     *   · 离线聊天：控制**是否展示/可用**离线设备与历史
     * 即：保存聊天 = 数据层，离线聊天 = 视图/交互层。
     */
    public boolean offlineChat() { return sp.getBoolean("offline_chat", true); }
    public void setOfflineChat(boolean v) { sp.edit().putBoolean("offline_chat", v).apply(); }

    /**
     * 是否保存聊天记录（默认开启）。关闭后不再写 history 文件。
     * 与 offlineChat 配合：只关保存、保留离线聊天，可看旧记录但不再新增。
     */
    public boolean keepHistory() { return sp.getBoolean("history_keep", true); }
    public void setKeepHistory(boolean v) { sp.edit().putBoolean("history_keep", v).apply(); }

    /**
     * 「全部设备」是否按**纯群聊视图**呈现（默认开启，v1.18.9）。
     *
     * 用户第 6 条需求：全部设备里只展示**在里面发过消息**的设备；
     * 端到端私聊的内容不汇入这里。这是一个「群聊」聚合视图，
     * 不参与任何私聊记录的展示。
     */
    public boolean groupOnlyView() { return sp.getBoolean("group_only_view", true); }
    public void setGroupOnlyView(boolean v) { sp.edit().putBoolean("group_only_view", v).apply(); }

    /**
     * 已知设备档案（JSON 数组）。独立于 UDP 实时发现 ——
     * 离线设备从列表消失后，靠它仍能恢复到设备选择框里，
     * 从而让「发送过的聊天记录」不会因为跨网络/离线而"看不见"。
     */
    public JSONArray knownPeers() {
        try { return new JSONArray(sp.getString("known_peers", "[]")); }
        catch (Exception e) { return new JSONArray(); }
    }

    public void knownPeers(JSONArray arr) {
        sp.edit().putString("known_peers", arr.toString()).apply();
    }

    /**
     * 记录/更新一台已知设备（name / platform / ips / last_seen）。
     * 由发现回调与「发过消息」时机调用。
     */
    public void rememberPeer(String id, String name, String platform, long ts) {
        if (id == null || id.isEmpty()) return;
        try {
            JSONArray arr = knownPeers();
            JSONArray out = new JSONArray();
            boolean found = false;
            for (int i = 0; i < arr.length(); i++) {
                org.json.JSONObject o = arr.optJSONObject(i);
                if (o == null) continue;
                if (id.equals(o.optString("id"))) {
                    o.put("name", name == null ? o.optString("name") : name);
                    if (platform != null) o.put("platform", platform);
                    o.put("last_seen", ts);
                    found = true;
                }
                out.put(o);
            }
            if (!found) {
                org.json.JSONObject o = new org.json.JSONObject();
                o.put("id", id);
                o.put("name", name == null ? "" : name);
                o.put("platform", platform == null ? "android" : platform);
                o.put("last_seen", ts);
                // 新设备插到最前，列表天然按「最近活跃」排序
                JSONArray head = new JSONArray();
                head.put(o);
                for (int i = 0; i < out.length(); i++) head.put(out.opt(i));
                out = head;
            }
            knownPeers(out);
        } catch (Throwable ignored) {}
    }

    /** 从档案中删除某设备（删除会话时调用，避免它继续以离线设备占位） */
    public void forgetPeer(String id) {
        if (id == null || id.isEmpty()) return;
        try {
            JSONArray arr = knownPeers();
            JSONArray out = new JSONArray();
            for (int i = 0; i < arr.length(); i++) {
                org.json.JSONObject o = arr.optJSONObject(i);
                if (o != null && id.equals(o.optString("id"))) continue;
                out.put(o);
            }
            knownPeers(out);
        } catch (Throwable ignored) {}
    }

    // ================= v1.18.31 新增：已删除（不再显示）的设备 =================

    /**
     * 「已删除的设备」名单（JSON 数组，元素 {id, name, ts}）。
     *
     * ★ 为什么删除会话光靠 forgetPeer 不够：
     *   设备只要还在同一网段，UDP 广播发现 + rebuildSpinner 里的 rememberPeer
     *   会把它**立刻加回列表** —— 用户看到的就是"连接过的设备删不掉"。
     *   删除必须同时落一份持久屏蔽名单，节点层（广播/连接/收发事件）与
     *   UI 层（设备列表/搜索）都按它过滤，删完才真正不再出现。
     * ★ 可恢复：设置页「已删除的设备」里可解除屏蔽，设备重新出现在列表。
     */
    public JSONArray blockedPeers() {
        try { return new JSONArray(sp.getString("blocked_peers", "[]")); }
        catch (Exception e) { return new JSONArray(); }
    }

    public void blockedPeers(JSONArray arr) {
        sp.edit().putString("blocked_peers", arr == null ? "[]" : arr.toString()).apply();
    }

    /** 该设备是否已被删除（屏蔽） */
    public boolean isBlocked(String id) {
        if (id == null || id.isEmpty()) return false;
        try {
            JSONArray arr = blockedPeers();
            for (int i = 0; i < arr.length(); i++) {
                org.json.JSONObject o = arr.optJSONObject(i);
                if (o != null && id.equals(o.optString("id"))) return true;
            }
        } catch (Throwable ignored) {}
        return false;
    }

    /** 加入屏蔽名单（幂等；同设备重复删除只保留一条，时间刷新） */
    public void blockPeer(String id, String name) {
        if (id == null || id.isEmpty()) return;
        try {
            JSONArray arr = blockedPeers();
            JSONArray out = new JSONArray();
            for (int i = 0; i < arr.length(); i++) {
                org.json.JSONObject o = arr.optJSONObject(i);
                if (o == null || id.equals(o.optString("id"))) continue;   // 去重
                out.put(o);
            }
            org.json.JSONObject o = new org.json.JSONObject();
            o.put("id", id);
            o.put("name", name == null ? "" : name);
            o.put("ts", System.currentTimeMillis());
            // 新删的插到最前，设置页列表天然按「最近删除」排序
            JSONArray head = new JSONArray();
            head.put(o);
            for (int i = 0; i < out.length(); i++) head.put(out.opt(i));
            blockedPeers(head);
        } catch (Throwable ignored) {}
    }

    /** 解除屏蔽（设置页「恢复设备」用） */
    public void unblockPeer(String id) {
        if (id == null || id.isEmpty()) return;
        try {
            JSONArray arr = blockedPeers();
            JSONArray out = new JSONArray();
            for (int i = 0; i < arr.length(); i++) {
                org.json.JSONObject o = arr.optJSONObject(i);
                if (o != null && id.equals(o.optString("id"))) continue;
                out.put(o);
            }
            blockedPeers(out);
        } catch (Throwable ignored) {}
    }

    /** ================= v1.18.18 新增 ================= */

    /**
     * 设备备注 {peer_id: 名称}。
     *
     * ★ 只影响本机显示，**不改写对端自报名** —— 若两端互相回传备注，
     *   用户在 A 端改名会把 B 端的备注也冲掉。
     * ★ 用 JSON 对象存（与 known_peers 同样的范式）；
     *   注意测试桩 org.json.JSONObject **没有 remove()**，
     *   所以清除走"重建并跳过该 key"的写法，不能直接 remove。
     */
    public org.json.JSONObject peerAliases() {
        try {
            return new org.json.JSONObject(sp.getString("peer_aliases", "{}"));
        } catch (Exception e) {
            return new org.json.JSONObject();
        }
    }

    public void peerAliases(org.json.JSONObject o) {
        sp.edit().putString("peer_aliases", o == null ? "{}" : o.toString()).apply();
    }

    /** 设置/清除设备备注（alias 为空串 = 清除） */
    public void setAlias(String peerId, String alias) {
        if (peerId == null || peerId.isEmpty()) return;
        try {
            String a = alias == null ? "" : alias.trim();
            if (a.length() > 40) a = a.substring(0, 40);
            org.json.JSONObject old = peerAliases();
            org.json.JSONObject out = new org.json.JSONObject();
            boolean found = false;
            java.util.Iterator<String> it = old.keys();
            while (it.hasNext()) {
                String k = it.next();
                if (peerId.equals(k)) {
                    found = true;
                    if (a.isEmpty()) continue;      // 清除：跳过这个 key
                }
                out.put(k, old.optString(k, ""));
            }
            if (!a.isEmpty() && !found) out.put(peerId, a);
            peerAliases(out);
        } catch (Throwable ignored) {}
    }

    public String getAlias(String peerId) {
        if (peerId == null || peerId.isEmpty()) return "";
        try {
            return peerAliases().optString(peerId, "").trim();
        } catch (Exception e) {
            return "";
        }
    }

    /** 单例缓存（避免每次 new 都读一遍 SharedPreferences） */
    private static Prefs INSTANCE;

    public static synchronized Prefs get(Context ctx) {
        if (INSTANCE == null) INSTANCE = new Prefs(ctx);
        return INSTANCE;
    }
}
