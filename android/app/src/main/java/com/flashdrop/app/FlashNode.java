package com.flashdrop.app;

import android.content.Context;
import android.media.MediaScannerConnection;
import android.net.wifi.WifiManager;
import android.os.Build;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.DataInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.OutputStream;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InterfaceAddress;
import java.net.NetworkInterface;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.SocketAddress;
import java.net.SocketTimeoutException;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * FlashDrop 核心节点（Android 版，线程模型）。
 * 协议见 PROTOCOL.md；连接去重规则与 Windows 端一致：
 * 设备 ID 大者为首选发起方；单向可达时保留唯一可用连接。
 */
public class FlashNode {

    // ---------------- 事件监听 ----------------
    public interface Listener { void onEvent(JSONObject e); }
    private volatile Listener listener;

    // ---------------- 配置 ----------------
    private final Context ctx;
    private final String deviceId;
    private final String host;          // 设备唯一标识（跨版本合并身份用）
    private final String altId;         // 旧版本使用过的设备 ID
    private volatile String name;
    private final int port;
    private final Prefs prefs;

    // ---------------- 状态 ----------------
    public static class Peer {
        String id; volatile String name = ""; volatile String platform = "";
        volatile String host = "";
        volatile int tcpPort = FdProto.DEFAULT_PORT;
        final List<String> ips = new CopyOnWriteArrayList<>();
        volatile long lastSeen = 0; volatile boolean manual = false;
        volatile boolean connecting = false; volatile long nextRetry = 0;
        volatile double backoff = 1.0;
        boolean online() {
            return (System.currentTimeMillis() - lastSeen) < 15000;
        }
    }

    static class Conn {
        Socket sock; DataInputStream in; OutputStream out;
        boolean incoming; volatile boolean alive = true; volatile boolean replaced = false;
        volatile String peerId; volatile boolean helloGot = false; volatile boolean closed = false;
        volatile long lastRecv = System.currentTimeMillis();
        String remoteIp; int remotePort;
    }

    static class Inbound {
        String peerId, tid, name; long size; String mime;
        /** 原始文件名（未经 safeFileName 处理）—— 续传指纹必须用原始名，
         *  否则同名不同内容的文件可能被错误判定为"同一个文件"而拼接出坏文件 */
        String rawName = "";
        String scheme = "";            // 发送方气泡配色（全局气泡）
        File partFile; java.io.FileOutputStream out;   // 顺序流模式：追加写
        long received = 0; volatile boolean started = false;
        volatile boolean done = false; volatile boolean canceled = false;
        MessageDigest md5; long t0 = System.currentTimeMillis();

        // ---------- v1.18.18 断点续传 ----------
        /** "chunk"=带块号分块（可续传）；"stream"=顺序流（老端/降级） */
        volatile String mode = "stream";
        /** chunk 模式用随机访问写（seek），stream 模式用 out 追加 */
        java.io.RandomAccessFile raf;
        /** 块位图：第 i 位=第 i 块已落盘 */
        FdResume.ChunkMap cmap;
        /** 发送方本次是否支持 0x43（协商结果，只对本次传输有效） */
        boolean resumeSupported;
        /** 已尝试自动重试次数（UI 用） */
        int attempt;
        // 位图落盘节流：每 N 块或每 T 秒落一次，避免每块都 fsync
        private long lastBmpSave = 0;
        private int sinceBmp = 0;

        /** 位图是否需要强制落盘（块数或时间到位） */
        boolean bitmapDue(long now) {
            return ++sinceBmp >= BITMAP_FLUSH_CHUNKS
                    || now - lastBmpSave > BITMAP_FLUSH_MS;
        }

        void markBmpSaved(long now) {
            lastBmpSave = now;
            sinceBmp = 0;
        }
    }

    private final Map<String, Peer> peers = new ConcurrentHashMap<>();
    private final Map<String, Conn> conns = new ConcurrentHashMap<>();   // peerId -> Conn
    private final Map<String, Inbound> inbounds = new ConcurrentHashMap<>(); // peerId|tid -> Inbound

    // ================= v1.18.18：断点续传与传输重试 =================
    /** 单目标最大重试次数（不含首次） */
    private static final int SEND_MAX_RETRY = 3;
    /** 退避基数秒（指数增长，上限 30s），与 Windows 端 node.SEND_RETRY_BASE 一致 */
    private static final double SEND_RETRY_BASE = 1.5;
    private static final double SEND_RETRY_CAP = 30.0;
    /** 位图落盘节流：每收满这么多块 */
    private static final int BITMAP_FLUSH_CHUNKS = 16;
    /** 位图落盘节流：距上次落盘超过这么久 */
    private static final long BITMAP_FLUSH_MS = 2000L;
    /** 断点残留保留天数（超过则 GC 清理） */
    private static final long RESUME_TTL_MS = 7L * 86400L * 1000L;
    /** 断点 GC 周期 */
    private static final long RESUME_GC_MS = 5L * 60L * 1000L;
    private final Map<String, Map<String, String>> outStates = new ConcurrentHashMap<>(); // tid -> {peer: state}
    private final Map<String, JSONObject> sendInfo = new ConcurrentHashMap<>();
    private final Map<String, Object[]> readyWaiters = new ConcurrentHashMap<>(); // peerId|tid -> result slot
    private final Map<String, Object[]> okWaiters = new ConcurrentHashMap<>();
    private final Map<String, Object[]> ackWaiters = new ConcurrentHashMap<>();  // peerId|mid
    private final Map<String, Long> lastReply = new ConcurrentHashMap<>();
    private final Set<String> knownSubnets = ConcurrentHashMap.newKeySet();

    private ServerSocket server;
    private DatagramSocket udpMain, udpAlt;
    private final ScheduledExecutorService scheduler = Executors.newScheduledThreadPool(3);
    private final ExecutorService pool = Executors.newCachedThreadPool();
    // 扫描探测用的共享线程池：一次性创建复用。
    // 此前每次 probeAll 都 newFixedThreadPool(96)，而 scan 由定时器周期调用，
    // 会反复创建/销毁 96 线程 —— 低端机上易触发 OOM/ANR，并被 CrashTrap 记为崩溃。
    private static final int PROBE_THREADS = 24;
    private final ExecutorService probePool =
            Executors.newFixedThreadPool(PROBE_THREADS, r -> {
                Thread t = new Thread(r, "fd-probe");
                t.setDaemon(true);
                return t;
            });
    private final AtomicBoolean running = new AtomicBoolean(false);
    private final AtomicBoolean scanning = new AtomicBoolean(false);
    private volatile MulticastLockHolder mcl;
    /** ★ v1.16.0：WiFi 高性能锁 —— 息屏/锁屏时系统会把 WiFi 降到省电档甚至休眠，
     *  导致包收不到、连接被拖死（用户反馈"锁屏收不到文件，发送端显示已发送、
     *  接收端显示失败"）。持有 WifiLock 后 WiFi 无线电保持活跃。 */
    private volatile WifiLockHolder wfl;
    /** ★ v1.16.0：息屏时是否正在传输（决定是否申请 CPU 唤醒窗口） */
    private final AtomicBoolean transferringNow = new AtomicBoolean(false);
    private volatile android.os.PowerManager.WakeLock wakeLock;
    /** 心跳宽限：正常 30s；息屏/有传输时放宽到 90s，避免被系统冻结误判为掉线 */
    private static final long HEARTBEAT_GRACE_MS = 30000;
    private static final long HEARTBEAT_GRACE_IDLE_MS = 90000;

    private static final String PLATFORM = "android";

    public FlashNode(Context ctx, String deviceId, String name, int port, Prefs prefs) {
        this.ctx = ctx.getApplicationContext();
        this.deviceId = deviceId;
        this.name = name;
        this.port = port;
        this.prefs = prefs;
        this.host = prefs.deviceHost();
        this.altId = prefs.legacyDeviceId();
        try {
            JSONArray arr = prefs.knownSubnets();
            for (int i = 0; i < arr.length(); i++) knownSubnets.add(arr.getString(i));
        } catch (Exception ignored) {}
    }

    public void setListener(Listener l) { this.listener = l; }
    public void setName(String n) { this.name = n; }
    public String getDeviceId() { return deviceId; }
    public boolean isRunning() { return running.get(); }

    private void emit(JSONObject e) {
        Listener l = listener;
        if (l != null) { try { l.onEvent(e); } catch (Exception ignored) {} }
    }

    private void log(String msg) {
        emit(FdProto.obj("event", "log", "level", "info", "msg", msg));
    }

    // ============================ 生命周期 ============================

    public synchronized void start() {
        if (!running.compareAndSet(false, true)) return;
        try {
            server = new ServerSocket(port);
            server.setReuseAddress(true);
        } catch (Exception e) {
            emit(FdProto.obj("event", "log", "level", "error",
                    "msg", "TCP 端口 " + port + " 绑定失败: " + e));
            server = null;
        }
        try {
            udpMain = new DatagramSocket(port);
            udpMain.setBroadcast(true);
        } catch (Exception e) {
            emit(FdProto.obj("event", "log", "level", "error",
                    "msg", "UDP 端口 " + port + " 绑定失败: " + e));
            udpMain = null;
        }
        if (udpMain != null && port != FdProto.DEFAULT_PORT) {
            try {
                udpAlt = new DatagramSocket(FdProto.DEFAULT_PORT);
                udpAlt.setBroadcast(true);
            } catch (Exception ignored) { udpAlt = null; }
        }
        // 组播锁
        try {
            WifiManager wm = (WifiManager) ctx.getApplicationContext()
                    .getSystemService(Context.WIFI_SERVICE);
            if (wm != null) {
                WifiManager.MulticastLock lock = wm.createMulticastLock("flashdrop");
                lock.setReferenceCounted(false);
                lock.acquire();
                mcl = new MulticastLockHolder(lock);
            }
        } catch (Exception ignored) {}
        // ★ v1.16.0：WiFi 高性能锁（息屏保活的关键）。
        // WIFI_MODE_FULL_HIGH_PERF 会让 WiFi 无线电在息屏时保持全速，
        // 是"锁屏仍能收文件"的必要条件；只加 MulticastLock 不够。
        try {
            WifiManager wm = (WifiManager) ctx.getApplicationContext()
                    .getSystemService(Context.WIFI_SERVICE);
            if (wm != null) {
                WifiManager.WifiLock lock = wm.createWifiLock(
                        WifiManager.WIFI_MODE_FULL_HIGH_PERF, "flashdrop:perf");
                lock.setReferenceCounted(false);
                lock.acquire();
                wfl = new WifiLockHolder(lock);
            }
        } catch (Exception ignored) {}

        if (server != null) pool.execute(this::acceptLoop);
        if (udpMain != null) pool.execute(() -> udpLoop(udpMain));
        if (udpAlt != null) pool.execute(() -> udpLoop(udpAlt));
        scheduler.execute(this::announceOnce);          // 启动即广播
        scheduler.scheduleAtFixedRate(this::announceOnce, 3, 3, TimeUnit.SECONDS);
        scheduler.scheduleAtFixedRate(this::expireTick, 2, 2, TimeUnit.SECONDS);
        scheduler.scheduleWithFixedDelay(() -> { if (!scanning.get()) scan(false); },
                10, 30, TimeUnit.SECONDS);
        // ★ v1.18.18：断点残留 GC（超 7 天且无在途任务）。
        //   不清理的话长期不用会把 cache 目录撑满。
        scheduler.scheduleWithFixedDelay(this::gcResumeState,
                RESUME_GC_MS, RESUME_GC_MS, TimeUnit.MILLISECONDS);
        log("服务已启动 port=" + port);
        scheduler.execute(() -> scan(false));
    }

    public synchronized void stop() {
        if (!running.compareAndSet(true, false)) return;
        for (Conn c : conns.values()) {
            try { sendJson(c, FdProto.obj("type", FdProto.T_BYE)); } catch (Exception ignored) {}
            closeConn(c);
        }
        try { if (server != null) server.close(); } catch (Exception ignored) {}
        try { if (udpMain != null) udpMain.close(); } catch (Exception ignored) {}
        try { if (udpAlt != null) udpAlt.close(); } catch (Exception ignored) {}
        if (mcl != null) mcl.release();
        if (wfl != null) wfl.release();
        releaseWakeLock();
        scheduler.shutdownNow();
        pool.shutdownNow();
    }

    private static class MulticastLockHolder {
        final WifiManager.MulticastLock lock;
        MulticastLockHolder(WifiManager.MulticastLock l) { lock = l; }
        void release() { try { lock.release(); } catch (Exception ignored) {} }
    }

    private static class WifiLockHolder {
        final WifiManager.WifiLock lock;
        WifiLockHolder(WifiManager.WifiLock l) { lock = l; }
        void release() { try { lock.release(); } catch (Exception ignored) {} }
    }

    // ==================== v1.16.0：息屏保活 ====================

    /**
     * 进入/退出「正在传输」状态。
     *
     * 传输期间申请一个带超时的 CPU 唤醒窗口（PARTIAL_WAKE_LOCK）：
     * 锁屏后 CPU 会被挂起，Socket 读线程拿不到时间片，
     * 发送端把数据推完却等不到接收端的 FILE_OK，最终双方都显示超时/失败。
     * 有了唤醒窗口，传输过程不会被系统冻结打断。
     *
     * 用超时锁（而非永久锁）是刻意的：即使某次传输异常退出忘了 release，
     * 锁也会在超时后自动释放，不会永久耗电。
     */
    private void setTransferring(boolean on) {
        transferringNow.set(on);
        if (on) acquireWakeLock(10 * 60 * 1000L);
        else releaseWakeLock();
    }

    private synchronized void acquireWakeLock(long timeoutMs) {
        try {
            if (wakeLock != null && wakeLock.isHeld()) return;
            android.os.PowerManager pm = (android.os.PowerManager)
                    ctx.getApplicationContext()
                            .getSystemService(Context.POWER_SERVICE);
            if (pm == null) return;
            wakeLock = pm.newWakeLock(
                    android.os.PowerManager.PARTIAL_WAKE_LOCK, "flashdrop:transfer");
            wakeLock.setReferenceCounted(false);
            wakeLock.acquire(timeoutMs);
        } catch (Throwable ignored) {}
    }

    private synchronized void releaseWakeLock() {
        try {
            if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
        } catch (Throwable ignored) {}
        wakeLock = null;
    }

    /** 当前是否处于"息屏/不可交互"状态（决定心跳宽限取哪一档） */
    private boolean screenOff() {
        try {
            android.os.PowerManager pm = (android.os.PowerManager)
                    ctx.getApplicationContext()
                            .getSystemService(Context.POWER_SERVICE);
            return pm != null && !pm.isInteractive();
        } catch (Throwable t) {
            return false;
        }
    }

    // ============================ 网络信息 ============================

    private static List<InterfaceAddress> ifaceAddrs() {
        List<InterfaceAddress> out = new ArrayList<>();
        try {
            for (NetworkInterface nif : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                if (!nif.isUp() || nif.isLoopback()) continue;
                for (InterfaceAddress ia : nif.getInterfaceAddresses()) {
                    if (ia.getAddress() instanceof Inet4Address) out.add(ia);
                }
            }
        } catch (Exception ignored) {}
        return out;
    }

    private static boolean privateIp(String ip) {
        if (ip.startsWith("10.") || ip.startsWith("192.168.")) return true;
        if (ip.startsWith("172.")) {
            try {
                int second = Integer.parseInt(ip.split("\\.")[1]);
                return second >= 16 && second <= 31;
            } catch (Exception e) { return false; }
        }
        return ip.startsWith("127.");
    }

    private String subnetOf(String ip) {
        if (!privateIp(ip)) return "";
        String[] p = ip.split("\\.");
        if (p.length == 4) return p[0] + "." + p[1] + "." + p[2] + ".0";
        return "";
    }

    private void rememberSubnet(String subnet) {
        if (subnet == null || subnet.isEmpty() || !knownSubnets.add(subnet)) return;
        JSONArray arr = new JSONArray(knownSubnets);
        while (arr.length() > 32) arr.remove(0);
        prefs.knownSubnets(arr);
    }

    // ============================ 广播发现 ============================

    private void announceOnce() {
        if (!running.get()) return;
        byte[] pkt = FdProto.discPacket(deviceId, name, PLATFORM, port, host, altId);
        Set<Integer> ports = new HashSet<>();
        ports.add(port);
        ports.add(FdProto.DEFAULT_PORT);
        List<InetAddress> targets = new ArrayList<>();
        try { targets.add(InetAddress.getByName("255.255.255.255")); } catch (Exception ignored) {}
        for (InterfaceAddress ia : ifaceAddrs()) {
            InetAddress bc = ia.getBroadcast();
            if (bc != null) targets.add(bc);
        }
        try { targets.add(InetAddress.getByName(FdProto.MULTICAST_GROUP)); } catch (Exception ignored) {}
        try { targets.add(InetAddress.getByName("127.0.0.1")); } catch (Exception ignored) {}
        DatagramSocket sendSock = udpMain != null ? udpMain : null;
        if (sendSock == null) return;
        for (InetAddress t : targets) {
            for (int p : ports) {
                try {
                    udpMain.send(new DatagramPacket(pkt, pkt.length, t, p));
                } catch (Exception ignored) {}
            }
        }
    }

    private void udpLoop(DatagramSocket sock) {
        byte[] buf = new byte[65536];
        while (running.get()) {
            try {
                DatagramPacket pkt = new DatagramPacket(buf, buf.length);
                sock.receive(pkt);
                JSONObject msg = FdProto.parseDisc(
                        java.util.Arrays.copyOfRange(pkt.getData(), pkt.getOffset(),
                                pkt.getOffset() + pkt.getLength()));
                if (msg == null) continue;
                String pid = msg.optString("id");
                String ip = pkt.getAddress().getHostAddress();
                if (pid.equals(deviceId)) continue;
                Peer peer = touchPeer(msg, ip);
                long now = System.currentTimeMillis();
                Long last = lastReply.get(pid);
                if (last == null || now - last > 10000) {
                    lastReply.put(pid, now);
                    try {
                        byte[] rp = FdProto.discPacket(deviceId, name, PLATFORM, port,
                                host, altId);
                        udpMain.send(new DatagramPacket(rp, rp.length,
                                pkt.getAddress(), pkt.getPort()));
                    } catch (Exception ignored) {}
                }
                ensureConnected(peer, false);
            } catch (Exception e) {
                if (!running.get()) return;
                try { Thread.sleep(200); } catch (InterruptedException ie) { return; }
            }
        }
    }

    private Peer touchPeer(JSONObject msg, String ip) {
        String pid = msg.optString("id");
        String mergedFrom = mergeCandidate(pid, msg);
        if (mergedFrom != null) mergePeer(mergedFrom, pid);
        Peer peer = peers.get(pid);
        boolean isNew = false;
        if (peer == null) {
            peer = new Peer(); peer.id = pid; peers.put(pid, peer); isNew = true;
        }
        String nm = msg.optString("name", "");
        if (!nm.isEmpty()) peer.name = nm;
        String pf = msg.optString("platform", "");
        if (!pf.isEmpty()) peer.platform = pf;
        String mh = msg.optString("host", "");
        if (!mh.isEmpty()) peer.host = mh;
        int tp = msg.optInt("tcp", 0);
        if (tp > 0) peer.tcpPort = tp;
        if (ip != null && !ip.isEmpty() && !peer.ips.contains(ip)) {
            peer.ips.add(0, ip);
            while (peer.ips.size() > 8) peer.ips.remove(peer.ips.size() - 1);
        }
        peer.lastSeen = System.currentTimeMillis();
        if (isNew) log("发现设备 " + (peer.name.isEmpty() ? pid.substring(0, 8) : peer.name) + " (" + ip + ")");
        return peer;
    }

    /** 判断是否与已有 peer 为同一台设备（跨版本身份）：host 相同或 id 命中对方 alt 列表。
     *  仅合并离线条目：同机多实例（调试）都在线，不应合并 */
    private String mergeCandidate(String pid, JSONObject msg) {
        String mh = msg.optString("host", "");
        String alt = msg.optString("alt", "");
        if (mh.isEmpty() && alt.isEmpty()) return null;
        for (Peer p : peers.values()) {
            if (p.id.equals(pid) || p.online()) continue;
            if ((!mh.isEmpty() && !p.host.isEmpty() && p.host.equals(mh))
                    || (!alt.isEmpty() && alt.contains(p.id))) {
                return p.id;
            }
        }
        return null;
    }

    /** 同机跨版本设备身份合并：旧条目并入新条目，连接改键，通知 UI 迁移聊天记录 */
    private void mergePeer(String oldId, String newId) {
        Peer old = peers.get(oldId);
        if (old == null) return;
        Peer peer = peers.get(newId);
        if (peer == null) {
            peer = new Peer(); peer.id = newId; peers.put(newId, peer);
        }
        for (String ip : old.ips.toArray(new String[0])) {
            if (!peer.ips.contains(ip)) peer.ips.add(ip);
        }
        while (peer.ips.size() > 8) peer.ips.remove(peer.ips.size() - 1);
        if (!old.name.isEmpty() && peer.name.isEmpty()) peer.name = old.name;
        if (!old.platform.isEmpty() && peer.platform.isEmpty()) peer.platform = old.platform;
        if (!old.host.isEmpty()) peer.host = old.host;
        peer.manual = peer.manual || old.manual;
        peer.lastSeen = Math.max(peer.lastSeen, old.lastSeen);
        peers.remove(oldId);
        Conn c = conns.get(oldId);
        if (c != null) {
            conns.remove(oldId);
            conns.put(newId, c);
            c.peerId = newId;
        }
        log("设备身份已合并：" + oldId.substring(0, 8) + " → " + newId.substring(0, 8));
        emit(FdProto.obj("event", "peer_merged", "old", oldId, "new", newId));
    }

    private void expireTick() {
        long now = System.currentTimeMillis();
        boolean changed = false;
        for (Peer p : new ArrayList<>(peers.values())) {
            Conn c = conns.get(p.id);
            if (c != null && c.alive && !c.replaced) {
                p.lastSeen = Math.max(p.lastSeen, now - 1000);
            }
            if (!p.online() && !p.manual && now - p.lastSeen > 1800000) {
                peers.remove(p.id);
                changed = true;
            }
        }
        notifyPeers();
    }

    /** 发送设备列表快照事件 */
    public void notifyPeers() {
        try {
            JSONArray arr = new JSONArray();
            List<JSONObject> list = new ArrayList<>();
            for (Peer p : peers.values()) list.add(peerSnapshot(p));
            list.sort((a, b) -> {
                if (a.optBoolean("online") != b.optBoolean("online"))
                    return a.optBoolean("online") ? -1 : 1;
                return a.optString("name").compareTo(b.optString("name"));
            });
            for (JSONObject o : list) arr.put(o);
            emit(FdProto.obj("event", "peers", "peers", arr));
        } catch (Exception ignored) {}
    }

    public JSONObject peerSnapshot(Peer p) {
        Conn c = conns.get(p.id);
        boolean connected = c != null && c.alive && !c.replaced;
        JSONArray ips = new JSONArray();
        if (connected) ips.put(c.remoteIp);
        for (String ip : p.ips) {
            if (ips.length() >= 4) break;
            if (!ip.equals(c != null ? c.remoteIp : null)) ips.put(ip);
        }
        return FdProto.obj("id", p.id, "name",
                p.name.isEmpty() ? p.id.substring(0, 8) : p.name,
                "platform", p.platform.isEmpty() ? "unknown" : p.platform,
                "tcp_port", p.tcpPort, "ips", ips,
                "online", p.online() || connected, "connected", connected,
                "manual", p.manual);
    }

    public List<Peer> peerList() { return new ArrayList<>(peers.values()); }
    public Peer findPeer(String id) { return peers.get(id); }

    /** 最近活跃的在线设备（系统分享"发送给最近设备"用）；无在线设备返回 null */
    public String recentOnlinePeerId() {
        Peer best = null;
        for (Peer p : peers.values()) {
            if (!isPeerOnline(p.id)) continue;
            if (best == null || p.lastSeen > best.lastSeen) best = p;
        }
        return best != null ? best.id : null;
    }

    // ============================ 连接管理 ============================

    private void acceptLoop() {
        while (running.get()) {
            try {
                Socket sock = server.accept();
                // 预读 1 字节识别 TLS ClientHello（0x16），自动升级加密连接
                int first = -1;
                try {
                    sock.setSoTimeout(6000);
                    first = sock.getInputStream().read();
                } catch (Exception ignored) {}
                try { sock.setSoTimeout(0); } catch (Exception ignored) {}
                Conn conn = newConn(sock, true, first);
                pool.execute(() -> session(conn));
            } catch (Exception e) {
                if (running.get()) {
                    try { Thread.sleep(300); } catch (InterruptedException ie) { return; }
                }
            }
        }
    }

    // ============================ 传输加密（TLS） ============================

    private javax.net.ssl.SSLContext tlsCtx;

    /** TLS 上下文：服务端用内嵌证书，客户端信任局域网对端（点对点工具） */
    private synchronized javax.net.ssl.SSLContext tlsContext() throws Exception {
        if (tlsCtx != null) return tlsCtx;
        javax.net.ssl.KeyManager[] kms = null;
        try {
            java.io.InputStream is = ctx.getResources().openRawResource(R.raw.fd_tls);
            java.security.KeyStore ks = java.security.KeyStore.getInstance("PKCS12");
            ks.load(is, "flashdrop123".toCharArray());
            javax.net.ssl.KeyManagerFactory kmf = javax.net.ssl.KeyManagerFactory.getInstance(
                    javax.net.ssl.KeyManagerFactory.getDefaultAlgorithm());
            kmf.init(ks, "flashdrop123".toCharArray());
            kms = kmf.getKeyManagers();
        } catch (Exception ignored) {}
        javax.net.ssl.TrustManager[] tms = new javax.net.ssl.TrustManager[]{
            new javax.net.ssl.X509TrustManager() {
                public void checkClientTrusted(java.security.cert.X509Certificate[] c, String a) {}
                public void checkServerTrusted(java.security.cert.X509Certificate[] c, String a) {}
                public java.security.cert.X509Certificate[] getAcceptedIssuers() {
                    return new java.security.cert.X509Certificate[0];
                }
            }
        };
        javax.net.ssl.SSLContext c = javax.net.ssl.SSLContext.getInstance("TLS");
        c.init(kms, tms, null);
        tlsCtx = c;
        return c;
    }

    /** 建立出站连接：开启加密时优先 TLS，对端不支持（明文）自动回退 */
    private Conn openConn(String host, int port, int timeoutMs) throws Exception {
        Socket raw = new Socket();
        raw.connect(new java.net.InetSocketAddress(host, port), timeoutMs);
        raw.setTcpNoDelay(true);
        if (prefs.encrypt()) {
            try {
                javax.net.ssl.SSLSocket ssl = (javax.net.ssl.SSLSocket) tlsContext()
                        .getSocketFactory().createSocket(raw, host, port, false);
                ssl.setUseClientMode(true);
                ssl.setTcpNoDelay(true);
                ssl.startHandshake();
                return newConn(ssl, false, -1);
            } catch (Exception e) {
                try { raw.close(); } catch (Exception ignored) {}
                // 对端未开加密：回退明文重连
                raw = new Socket();
                raw.connect(new java.net.InetSocketAddress(host, port), timeoutMs);
                raw.setTcpNoDelay(true);
            }
        }
        return newConn(raw, false, -1);
    }

    private Conn newConn(Socket sock, boolean incoming) throws Exception {
        return newConn(sock, incoming, -1);
    }

    private Conn newConn(Socket sock, boolean incoming, int firstByte) throws Exception {
        if (firstByte == 0x16 && prefs.encrypt()) {
            // TLS ClientHello：升级为 TLS（服务端）
            javax.net.ssl.SSLSocket ssl = (javax.net.ssl.SSLSocket) tlsContext()
                    .getSocketFactory().createSocket(sock,
                            sock.getInetAddress().getHostAddress(), sock.getPort(), false);
            ssl.setUseClientMode(false);
            ssl.setTcpNoDelay(true);
            ssl.startHandshake();
            sock = ssl;
        }
        Conn c = new Conn();
        c.sock = sock;
        java.io.InputStream base = sock.getInputStream();
        if (firstByte >= 0 && !(sock instanceof javax.net.ssl.SSLSocket)) {
            // 已预读 1 字节，回退给流
            java.io.PushbackInputStream pb = new java.io.PushbackInputStream(base, 1);
            pb.unread(firstByte);
            base = pb;
        }
        c.in = new DataInputStream(new BufferedInputStream(base, 65536));
        c.out = new BufferedOutputStream(sock.getOutputStream(), 65536);
        c.incoming = incoming;
        SocketAddress ra = sock.getRemoteSocketAddress();
        if (ra instanceof java.net.InetSocketAddress) {
            c.remoteIp = ((java.net.InetSocketAddress) ra).getAddress().getHostAddress();
            c.remotePort = ((java.net.InetSocketAddress) ra).getPort();
        } else { c.remoteIp = "?"; c.remotePort = 0; }
        sock.setTcpNoDelay(true);
        return c;
    }

    private void sendRaw(Conn c, byte[] frame) throws Exception {
        if (!c.alive) throw new Exception("conn closed");
        synchronized (c) {
            c.out.write(frame);
            c.out.flush();
        }
    }

    private void sendJson(Conn c, JSONObject o) throws Exception {
        sendRaw(c, FdProto.encodeJson(o));
    }

    private JSONObject helloMsg() {
        JSONArray ips = new JSONArray();
        for (InterfaceAddress ia : ifaceAddrs()) ips.put(ia.getAddress().getHostAddress());
        JSONObject o = FdProto.obj("app", FdProto.APP, "v", FdProto.PROTO_VERSION,
                "type", FdProto.T_HELLO, "id", deviceId, "name", name,
                "platform", PLATFORM, "tcp", port, "ips", ips);
        try {
            if (host != null && !host.isEmpty()) o.put("host", host);
            if (altId != null && !altId.isEmpty())
                o.put("alt", new JSONArray().put(altId));
        } catch (Exception ignored) {}
        return o;
    }

    /** 读取首帧 HELLO；非法返回 null */
    private JSONObject readHello(Conn c, int timeoutMs) {
        try {
            c.sock.setSoTimeout(timeoutMs);
            Object[] fr = FdProto.readFrame(c.in);
            if (((Byte) fr[0]) != FdProto.KIND_JSON) return null;
            JSONObject o = (JSONObject) fr[1];
            if (!FdProto.APP.equals(o.optString("app")) || o.optString("id").isEmpty())
                return null;
            return o;
        } catch (Exception e) {
            return null;
        }
    }

    /** 新连接会话：等 HELLO、注册去重、进入读循环 */
    private void session(Conn conn) {
        try { sendJson(conn, helloMsg()); } catch (Exception e) { closeConn(conn); return; }
        JSONObject hello = readHello(conn, 6000);
        try { conn.sock.setSoTimeout(0); } catch (Exception ignored) {}
        if (hello == null || hello.optString("id").equals(deviceId)) {
            closeConn(conn); return;
        }
        if (!registerConn(conn, hello)) return;
        readerLoop(conn);
    }

    private boolean connPreferred(Conn c, String peerId) {
        int cmp = peerId.compareTo(deviceId);
        return c.incoming ? cmp > 0 : cmp < 0;
    }

    private synchronized boolean registerConn(Conn conn, JSONObject hello) {
        String pid = hello.optString("id");
        conn.peerId = pid;
        conn.helloGot = true;
        conn.lastRecv = System.currentTimeMillis();

        String mergedFrom = mergeCandidate(pid, hello);
        if (mergedFrom != null) mergePeer(mergedFrom, pid);

        Peer peer = peers.get(pid);
        if (peer == null) { peer = new Peer(); peer.id = pid; peers.put(pid, peer); }
        String nm = hello.optString("name", "");
        if (!nm.isEmpty()) peer.name = nm;
        String pf = hello.optString("platform", "");
        if (!pf.isEmpty()) peer.platform = pf;
        String mh = hello.optString("host", "");
        if (!mh.isEmpty()) peer.host = mh;
        int tp = hello.optInt("tcp", 0);
        if (tp > 0) peer.tcpPort = tp;
        peer.lastSeen = System.currentTimeMillis();
        if (conn.remoteIp != null && !peer.ips.contains(conn.remoteIp)) {
            peer.ips.add(0, conn.remoteIp);
            while (peer.ips.size() > 8) peer.ips.remove(peer.ips.size() - 1);
        }

        Conn existing = conns.get(pid);
        if (existing != null && existing != conn && existing.alive && !existing.replaced) {
            // v1.11.0 修复「连着但收不到电脑发来的文字」：
            // 原逻辑只看 incoming 方向偏好（connPreferred），**同方向的两条连接
            // newPref == oldPref**，于是走进 else 把"新来的"这条 closeConn 掉。
            // 但对端重连 / 双向同时互连时，真实情况恰恰是新连接才是活的那条 ——
            // 丢掉它 = 这条链路上后续所有 TEXT 都被对端读不到（对端 _wait_conn
            // 拿到的正是这条被丢弃的连接），表现为"已连接却收不到文字"，
            // 而文件因为会走重试/另一条链路所以还能收到，极具迷惑性。
            //
            // 现在的规则：
            //   1) 方向不同 → 仍按原偏好规则，保留偏好方向那条（跨 NAT 单向可达时需要）
            //   2) 方向相同 → **新连接接管旧连接**（更新的握手更可信，且旧连接多半已半死）
            boolean newPref = connPreferred(conn, pid);
            boolean oldPref = connPreferred(existing, pid);
            if (newPref != oldPref) {
                if (newPref) {
                    // 新连接方向更优：替换
                    existing.replaced = true;
                    conns.put(pid, conn);
                    closeConn(existing);
                    log("与 " + (peer.name.isEmpty() ? pid.substring(0, 8) : peer.name)
                            + " 的连接已切换为首选链路");
                } else {
                    // 旧连接方向更优：丢弃新来的
                    closeConn(conn);
                    return false;
                }
            } else {
                // 同方向重复连接：新接管旧（v1.11.0 修复点）
                existing.replaced = true;
                conns.put(pid, conn);
                closeConn(existing);
                log("与 " + (peer.name.isEmpty() ? pid.substring(0, 8) : peer.name)
                        + " 的连接已更新为最新链路");
            }
        } else {
            conns.put(pid, conn);
        }

        rememberSubnet(subnetOf(conn.remoteIp));
        // 心跳
        final Conn hc = conn;
        scheduler.scheduleWithFixedDelay(() -> heartbeatTick(hc), 10, 10, TimeUnit.SECONDS);
        log("已连接 " + (peer.name.isEmpty() ? pid.substring(0, 8) : peer.name)
                + " (" + conn.remoteIp + ")");
        notifyPeers();
        return true;
    }

    private void heartbeatTick(Conn c) {
        if (!c.alive || c.replaced || !running.get()) return;
        long now = System.currentTimeMillis();
        // ★ v1.16.0：息屏或有活跃传输时放宽心跳宽限。
        // 旧逻辑固定 30s 无收包就断链 —— 息屏后系统冻结进程，
        // 对端 ping 没能及时被处理，连接被自己误判为掉线并 closeConn，
        // 正在传的文件随即中断，发送端却因为数据已推完而显示"已发送"，
        // 接收端显示"失败"（用户实测的正是这个现象）。
        long grace = HEARTBEAT_GRACE_MS;
        if (screenOff() || transferringNow.get() || !inbounds.isEmpty()) {
            grace = HEARTBEAT_GRACE_IDLE_MS;
        }
        if (now - c.lastRecv > grace) { closeConn(c); return; }
        try { sendJson(c, FdProto.obj("type", FdProto.T_PING)); } catch (Exception e) { closeConn(c); }
    }

    private void closeConn(Conn c) {
        if (c.closed) return;
        c.closed = true;
        c.alive = false;
        try { c.sock.close(); } catch (Exception ignored) {}
        String pid = c.peerId;
        if (pid != null && conns.get(pid) == c) {
            conns.remove(pid);
            Peer p = peers.get(pid);
            if (p != null) {
                long now = System.currentTimeMillis();
                p.nextRetry = now + (long) (p.backoff * 1000);
                p.backoff = Math.min(p.backoff * 2, 30);
                ensureConnected(p, true);
            }
            notifyPeers();
        }
    }

    private void readerLoop(Conn conn) {
        try {
            conn.sock.setSoTimeout(0);
            while (conn.alive && running.get()) {
                Object[] fr = FdProto.readFrame(conn.in);
                conn.lastRecv = System.currentTimeMillis();
                byte kind = (Byte) fr[0];
                if (kind == FdProto.KIND_CHUNK) {
                    // ★ v1.18.18：带块号分块。replaced 连接仍要处理数据帧，
                    // 否则切链路瞬间在途的块会丢。
                    if (conn.peerId != null) {
                        Object[] ti = (Object[]) fr[1];
                        onBin(conn, (String) ti[0], (byte[]) fr[2], (Integer) ti[1]);
                    }
                    continue;
                }
                if (conn.replaced) {
                    if (kind == FdProto.KIND_BIN)
                        onBin(conn, (String) fr[1], (byte[]) fr[2], -1);
                    continue;
                }
                if (kind == FdProto.KIND_JSON) onJson(conn, (JSONObject) fr[1]);
                else onBin(conn, (String) fr[1], (byte[]) fr[2], -1);
            }
        } catch (Exception e) {
            // v1.11.0：原来这里是 catch (Exception ignored) 完全静默，
            // 任何一帧解析/处理异常都会让整条读循环无声死掉，
            // 表现为"连接还在（心跳正常）但消息再也收不到"，且毫无线索。
            // 现在：正常关闭（主动 close / 链路结束）不打日志，
            // 真正的解析或处理异常必须留痕，便于定位。
            if (conn.alive && running.get()) {
                log("与 " + (conn.peerId == null ? "对端"
                        : conn.peerId.substring(0, Math.min(8, conn.peerId.length())))
                        + " 的消息处理异常：" + e.getClass().getSimpleName()
                        + (e.getMessage() == null ? "" : " · " + e.getMessage()));
            }
        } finally {
            closeConn(conn);
            // ★ v1.18.18：连接断开会**保留**该连接上的接收断点
            //   （.part + 位图），等发送方重连后用同 tid 续传。
            String pid = conn.peerId;
            if (pid != null) {
                for (Map.Entry<String, Inbound> e : inboundsSnapshot()) {
                    Inbound ib = e.getValue();
                    if (!pid.equals(ib.peerId) || !ib.started || ib.done) continue;
                    flushBitmap(ib, true);
                    cleanupInbound(ib, false);
                    emitRecv2(ib, "paused", "连接中断，可断点续传", null);
                }
            }
        }
    }

    // ============================ 消息分发 ============================

    private void onJson(Conn conn, JSONObject o) {
        String t = o.optString("type");
        String pid = conn.peerId;
        try {
            switch (t) {
                case FdProto.T_HELLO:
                    return;
                case FdProto.T_PING:
                    sendJson(conn, FdProto.obj("type", FdProto.T_PONG));
                    return;
                case FdProto.T_PONG:
                    return;
                case FdProto.T_BYE: {
                    Peer p = peers.get(pid);
                    if (p != null) p.lastSeen = 0;
                    closeConn(conn);
                    notifyPeers();
                    return;
                }
                case FdProto.T_TEXT: {
                    String mid = o.optString("mid", FdUtil.shortUid());
                    Peer p = peers.get(pid);
                    emit(FdProto.obj("event", "text", "peer_id", pid,
                            "name", displayName(pid),
                            "mid", mid, "text", o.optString("text", ""),
                            "ts", o.optLong("ts", FdUtil.nowMs()),
                            "scheme", o.optString("scheme", "")));
                    sendJson(conn, FdProto.obj("type", FdProto.T_ACK, "mid", mid));
                    return;
                }
                case FdProto.T_ACK: {
                    String mid = o.optString("mid");
                    resolveWaiter(ackWaiters, pid + "|" + mid, new Object[]{"ok", null});
                    emit(FdProto.obj("event", "ack", "peer_id", pid, "mid", mid));
                    return;
                }
                case FdProto.T_FILE_START:
                    onFileStart(conn, o);
                    return;
                case FdProto.T_RECV_READY:
                    // ★ v1.18.18：把**断点信息**（已收块位图 / 总块数 / 已收字节）
                    //   一并回传给发送任务 —— 它据此只补缺失块。
                    //   老端不带这些字段，发送端 idxMode=false，自动走顺序流。
                    resolveWaiter(readyWaiters, pid + "|" + o.optString("tid"),
                            new Object[]{"ready",
                                    o.optInt("idx", 0) == 1 ? o : null});
                    return;
                case FdProto.T_FILE_END:
                    onFileEnd(conn, o);
                    return;
                case FdProto.T_FILE_OK:
                    // ★ v1.16.0：把接收方的**回读确认**结果一起带上。
                    // verified=false 说明对方虽然回了 OK 但文件没真正落盘，
                    // 此时应标记为失败而不是显示"已送达"，避免两端说法不一。
                    if (o.has("verified") && !o.optBoolean("verified", true)) {
                        onSendFinal(pid, o.optString("tid"), "fail", "对方未能写入文件");
                    } else {
                        onSendFinal(pid, o.optString("tid"), "ok", o.optString("path", ""));
                    }
                    return;
                case FdProto.T_FILE_FAIL:
                    onSendFinal(pid, o.optString("tid"), "fail", o.optString("reason", "对方接收失败"));
                    return;
                case FdProto.T_REFUSE: {
                    String tid = o.optString("tid");
                    String key = pid + "|" + tid;
                    resolveWaiter(readyWaiters, key, new Object[]{"refuse", null});
                    resolveWaiter(okWaiters, key, new Object[]{"refuse", null});
                    markSendState(tid, pid, "refuse", o.optString("reason", "对方拒绝接收"));
                    return;
                }
                case FdProto.T_CANCEL: {
                    String tid = o.optString("tid");
                    String key = pid + "|" + tid;
                    Inbound ib = inbounds.get(key);
                    if (ib != null) {
                        // ★ 取消 = 明确不要了，续传状态无意义 -> 彻底清理
                        cleanupInbound(ib, true);
                        emitRecv(ib, "cancelled", "对方已取消", null);
                        return;
                    }
                    resolveWaiter(readyWaiters, key, new Object[]{"cancel", null});
                    resolveWaiter(okWaiters, key, new Object[]{"cancel", null});
                    markSendState(tid, pid, "cancel", "对方已取消");
                    return;
                }
                default:
                    // 未知类型忽略（向前兼容）
            }
        } catch (Exception ignored) {}
    }

    private void onSendFinal(String pid, String tid, String result, String extra) {
        String key = pid + "|" + tid;
        resolveWaiter(okWaiters, key, new Object[]{result, extra});
        Map<String, String> st = outStates.get(tid);
        if (st != null && st.containsKey(pid)) {
            st.put(pid, result);
            JSONObject info = sendInfo.get(tid);
            if ("ok".equals(result)) {
                emitSendState(tid, pid, "ok", null, extra);
            } else {
                emitSendState(tid, pid, "failed",
                        extra == null || extra.isEmpty() ? "对方接收失败" : extra, null);
            }
        }
    }

    private void markSendState(String tid, String pid, String state, String reason) {
        Map<String, String> st = outStates.get(tid);
        if (st == null || !st.containsKey(pid)) return;
        String cur = st.get(pid);
        if ("ok".equals(cur) || "fail".equals(cur) || "refuse".equals(cur) || "cancel".equals(cur))
            return;
        st.put(pid, state);
        String uiState = "refuse".equals(state) ? "refused"
                : "cancel".equals(state) ? "cancelled" : "failed";
        emitSendState(tid, pid, uiState, reason, null);
    }

    // ---------------- 等待器（阻塞结果槽） ----------------

    private static void resolveWaiter(Map<String, Object[]> map, String key, Object[] result) {
        Object[] slot = map.remove(key);
        if (slot == null) return;
        synchronized (slot) {
            slot[0] = result[0];
            slot[1] = result[1];
            slot.notifyAll();
        }
    }

    /** 创建等待槽：Object[2] {null, null}；等待结果 {state, extra} */
    private static Object[] newSlot() { return new Object[]{null, null}; }

    private static Object[] waitSlot(Object[] slot, long timeoutMs) {
        long deadline = System.currentTimeMillis() + timeoutMs;
        synchronized (slot) {
            while (slot[0] == null) {
                long remain = deadline - System.currentTimeMillis();
                if (remain <= 0) return new Object[]{"timeout", null};
                try { slot.wait(remain); } catch (InterruptedException e) {
                    return new Object[]{"timeout", null};
                }
            }
            return new Object[]{slot[0], slot[1]};
        }
    }

    private void dropSlot(Map<String, Object[]> map, String key) { map.remove(key); }

    // ============================ 接收 ============================

    private void onFileStart(Conn conn, JSONObject o) {
        String tid = o.optString("tid");
        if (tid.isEmpty()) return;
        String key = conn.peerId + "|" + tid;
        if (inbounds.containsKey(key)) return;
        Inbound ib = new Inbound();
        ib.peerId = conn.peerId;
        ib.tid = tid;
        ib.name = FdUtil.safeFileName(o.optString("name", "file"));
        ib.rawName = o.optString("name", "");
        ib.size = o.optLong("size", 0);
        ib.mime = o.optString("mime", "application/octet-stream");
        ib.scheme = o.optString("scheme", "");
        // ★ v1.18.18：能力协商 + 尝试次数
        ib.resumeSupported = o.optInt("idx", 0) == 1;
        ib.attempt = o.optInt("attempt", 0);
        ib.mode = ib.resumeSupported ? "chunk" : "stream";
        inbounds.put(key, ib);
        emitRecv(ib, "offer", null, null);
        if (prefs.autoAccept()) {
            beginInbound(ib);
            if (ib.started) {
                try { sendRecvReady(conn, ib); }
                catch (Exception ignored) {}
            }
        } else {
            emitRecv(ib, "confirm", null, null);
            final Conn fc = conn;
            final Inbound fib = ib;
            scheduler.schedule(() -> {
                if (fib.started || fib.done) return;
                if (inbounds.get(fib.peerId + "|" + fib.tid) != fib) return;
                // ★ 手动确认超时：彻底清掉续传状态（用户没接收，不留断点）
                cleanupInbound(fib, true);
                emitRecv(fib, "refused", "确认超时，已自动拒绝", null);
                try { sendJson(fc, FdProto.obj("type", FdProto.T_REFUSE, "tid", fib.tid,
                        "reason", "timeout")); } catch (Exception ignored) {}
            }, 35, TimeUnit.SECONDS);
        }
    }

    /**
     * 回 RECV_READY。
     *
     * ★ v1.18.18：chunk 模式下携带**已收块位图**（紧凑区间）、总块数、已收字节，
     * 发送方据此只补缺失块 —— 这是断点续传真正生效的关键。
     * 老端看不到这些字段，自动退回顺序流，行为与旧版本一致。
     */
    private void sendRecvReady(Conn conn, Inbound ib) throws Exception {
        if (ib.mode == "chunk" && ib.cmap != null) {
            int total = FdResume.totalChunks(ib.size);
            org.json.JSONArray have = new org.json.JSONArray();
            for (int[] r : ib.cmap.toCompact()) {
                have.put(new org.json.JSONArray().put(r[0]).put(r[1]));
            }
            sendJson(conn, FdProto.obj("type", FdProto.T_RECV_READY, "tid", ib.tid,
                    "idx", 1,
                    "have", have,
                    "total", total,
                    "recv", ib.cmap.receivedBytes(ib.size)));
        } else {
            sendJson(conn, FdProto.obj("type", FdProto.T_RECV_READY, "tid", ib.tid));
        }
    }

    /**
     * ★ v1.18.18：开始/恢复一个接收任务。
     *
     * 断点恢复的判定条件（三者必须一致才恢复，否则全部清理重来）：
     *   1. .fp 指纹 == md5(size + "|" + name)  → 防止同名不同内容被错误拼接
     *   2. .part 实际大小 == size              → 预分配过才能对上
     *   3. .bmp 位图可读
     *
     * 首次或重置后：<b>预分配 .part 到完整 size</b>，
     * 使 part_size == size 恒成立，后续块直接 seek 写入。
     */
    private void beginInbound(Inbound ib) {
        if (ib.started) return;
        try {
            File dir = FdUtil.cacheDir(ctx);
            ib.partFile = new File(dir, ib.tid + ".part");
            int total = FdResume.totalChunks(ib.size);
            boolean resumed = false;

            if (ib.mode == "chunk" && ib.partFile.isFile() && ib.partFile.length() == ib.size) {
                String fp = FdResume.loadFingerprint(dir, ib.tid);
                String want = FdResume.resumeFingerprint(ib.size, ib.rawName);
                if (!fp.isEmpty() && fp.equals(want)) {
                    FdResume.ChunkMap cm = FdResume.ChunkMap.load(dir, ib.tid, total);
                    if (cm.count() > 0 && cm.count() < total) {
                        ib.cmap = cm;
                        resumed = true;
                    }
                }
            }
            if (!resumed) {
                // 重来：清干净旧状态 + 预分配
                FdResume.dropResumeState(dir, ib.tid);
                if (ib.partFile.exists() && !ib.partFile.delete()) {
                    // 删不掉就退位另起一个，避免把旧数据混进新文件
                    ib.partFile = new File(dir, ib.tid + ".part.new");
                }
                ib.cmap = ib.mode == "chunk" ? new FdResume.ChunkMap(total) : null;
                FdResume.saveFingerprint(dir, ib.tid, ib.size, ib.rawName);
                try (java.io.RandomAccessFile rw =
                             new java.io.RandomAccessFile(ib.partFile, "rw")) {
                    // ★ 预分配：断点续传判定依赖 part_size == size
                    rw.setLength(ib.size);
                }
            }
            if (ib.mode == "chunk") {
                ib.raf = new java.io.RandomAccessFile(ib.partFile, "rw");
                // chunk 模式的 md5 要等全部块到齐后整体算（块可乱序到达，
                // 增量摘要无意义）—— 故这里不建 MessageDigest。
                ib.md5 = null;
                ib.received = ib.cmap.receivedBytes(ib.size);
            } else {
                ib.out = new FileOutputStream(ib.partFile);
                ib.md5 = MessageDigest.getInstance("MD5");
                ib.received = 0;
            }
            ib.started = true;
            // ★ v1.16.0：接收开始即申请 CPU 唤醒窗口，
            // 否则锁屏后接收线程被冻结，数据到不了盘 → 双方都失败。
            setTransferring(true);
            if (resumed) {
                int have = ib.cmap.count();
                emitRecv2(ib, "resumed", "断点续传，已收 " + have + "/" + total + " 块", null);
            }
            emitRecv(ib, "started", null, null);
        } catch (Exception e) {
            cleanupInbound(ib, true);
            emitRecv(ib, "failed", "无法创建缓存文件: " + e, null);
        }
    }

    /** 位图落盘（节流：块数或时间到位；force 用于断线/结束等关键节点） */
    private void flushBitmap(Inbound ib, boolean force) {
        if (ib.cmap == null) return;
        long now = System.currentTimeMillis();
        if (!force && !ib.bitmapDue(now)) return;
        if (ib.cmap.save(FdUtil.cacheDir(ctx), ib.tid)) ib.markBmpSaved(now);
    }

    /**
     * 收到一个数据块。index >= 0 表示带块号的分块（断点续传路径）。
     *
     * ★ 幂等：重复块直接丢弃（重发不会写坏文件）。
     * ★ 已收字节数**按位图推导**，不累加 —— 累加会在重复块时漂移。
     */
    private void onBin(Conn conn, String tid, byte[] data, int index) {
        Inbound ib = inbounds.get(conn.peerId + "|" + tid);
        if (ib == null || ib.done || !ib.started || ib.canceled) return;
        try {
            if (index >= 0 && "chunk".equals(ib.mode)) {
                // 重复块：直接返回（幂等 —— 重发不会写坏文件）
                if (ib.cmap.has(index)) return;
                int want = FdResume.chunkLen(index, ib.size);
                if (data.length != want) {
                    // 块长对不上 -> 降级为顺序流（对方可能用了不同分块大小）。
                    // ★ v1.18.18 审计修复：降级后必须把**当前块**也写入 ——
                    //   原实现只建了流和 md5 就落下去，当前帧的数据被静默丢弃，
                    //   最终 md5 校验必失败且 blame 无从查起。
                    ib.mode = "stream";
                    ib.out = new FileOutputStream(ib.partFile, true);
                    ib.md5 = MessageDigest.getInstance("MD5");
                    ib.out.write(data);
                    if (ib.md5 != null) ib.md5.update(data);
                    ib.received += data.length;
                } else {
                    ib.raf.seek(FdResume.chunkOffset(index));
                    ib.raf.write(data);
                    ib.cmap.add(index);
                    ib.received = ib.cmap.receivedBytes(ib.size);
                }
            } else {
                // 顺序流路径（含"chunk 模式降级后继续收带块号的帧"）
                ib.out.write(data);
                if (ib.md5 != null) ib.md5.update(data);
                ib.received += data.length;
            }
        } catch (Exception e) {
            cleanupInbound(ib, true);
            emitRecv(ib, "failed", "写入失败: " + e, null);
            try { sendJson(conn, FdProto.obj("type", FdProto.T_FILE_FAIL, "tid", tid,
                    "reason", String.valueOf(e))); } catch (Exception ignored) {}
            return;
        }
        if (ib.received > ib.size) {
            cleanupInbound(ib, true);
            emitRecv(ib, "failed", "数据超出声明大小", null);
            return;
        }
        long now = System.currentTimeMillis();
        if (now - ib.t0 > 0 && (ib.received % (512 * 1024) < data.length)) {
            double dt = (now - ib.t0) / 1000.0;
            emitRecv2(ib, "progress", null, dt > 0.1 ? ib.received / dt : 0);
        }
        if ("chunk".equals(ib.mode)) flushBitmap(ib, false);
    }

    private void onFileEnd(Conn conn, JSONObject o) {
        String tid = o.optString("tid");
        Inbound ib = inbounds.get(conn.peerId + "|" + tid);
        if (ib == null || !ib.started || ib.done) return;
        ib.done = true;
        try {
            if (ib.out != null) ib.out.close();
        } catch (Exception ignored) {}
        ib.out = null;
        try {
            if (ib.raf != null) ib.raf.close();
        } catch (Exception ignored) {}
        ib.raf = null;
        boolean chunkMode = "chunk".equals(ib.mode);

        // ★ v1.18.18：chunk 模式必须先确认位图完整 —— 预分配已经把 .part 撑到
        //   size，所以 size 校验在续传场景**形同虚设**（.part 永远是满的）。
        //   真正的完整性判据是"所有块都到齐"。
        if (chunkMode && ib.cmap != null) {
            flushBitmap(ib, true);
            if (!ib.cmap.complete()) {
                int missing = ib.cmap.missing().size();
                cleanupInbound(ib, false);   // 保留断点，可续传
                emitRecv(ib, "failed",
                        "缺少数据块（" + missing + " 块未收，可续传）", null);
                try { sendJson(conn, FdProto.obj("type", FdProto.T_FILE_FAIL,
                        "tid", tid, "reason", "missing chunks")); } catch (Exception ignored) {}
                return;
            }
        }
        if (ib.received != ib.size) {
            cleanupInbound(ib, chunkMode);
            emitRecv(ib, "failed",
                    chunkMode ? "文件大小校验失败（可续传）" : "文件大小校验失败", null);
            try { sendJson(conn, FdProto.obj("type", FdProto.T_FILE_FAIL, "tid", tid,
                    "reason", "size mismatch")); } catch (Exception ignored) {}
            return;
        }
        String expect = o.optString("md5", "");
        if (!expect.isEmpty()) {
            // ★ 两种校验模式：
            //   chunk 模式 —— 块可乱序/跨重连到达，必须整体读文件算摘要
            //   stream 模式 —— 沿用接收过程中的增量摘要
            String actual;
            if (chunkMode) {
                actual = md5OfFile(ib.partFile);
            } else if (ib.md5 != null) {
                StringBuilder sb = new StringBuilder();
                for (byte b : ib.md5.digest()) sb.append(String.format("%02x", b));
                actual = sb.toString();
            } else {
                actual = null;
            }
            if (actual != null && !actual.equals(expect.toLowerCase(Locale.US))) {
                // MD5 失败 = 文件内容不可信，续传状态也失去意义 -> 全部清理
                cleanupInbound(ib, true);
                emitRecv(ib, "failed", "MD5 校验失败", null);
                try { sendJson(conn, FdProto.obj("type", FdProto.T_FILE_FAIL, "tid", tid,
                        "reason", "md5 mismatch")); } catch (Exception ignored) {}
                return;
            }
        }
        // 校验通过 -> 续传状态全部清理
        if (chunkMode) FdResume.dropResumeState(FdUtil.cacheDir(ctx), ib.tid);
        // 落盘
        String[] saved;  // [0]=展示路径 [1]=可打开 Uri（可为 ""）
        try {
            saved = saveToDownloads(ib.name, ib.mime, ib.partFile, peerNameOf(ib.peerId));
            // ★ v1.18.28：刚落盘的文件必须让"已接收文件索引"失效 ——
            //   否则 UI 拿旧快照去判存在性，会把刚收到的文件显示成"文件已删除"。
            FdUtil.invalidateSavedIndex();
        } catch (Exception e) {
            // 落盘失败：内容还在 .part 里，保留断点（chunk）让重试能续传
            cleanupInbound(ib, chunkMode);
            emitRecv(ib, "failed", "保存失败: " + e, null);
            try { sendJson(conn, FdProto.obj("type", FdProto.T_FILE_FAIL, "tid", tid,
                    "reason", "save error")); } catch (Exception ignored) {}
            return;
        }
        inbounds.remove(conn.peerId + "|" + tid);
        double dt = Math.max((System.currentTimeMillis() - ib.t0) / 1000.0, 0.001);
        // ★ v1.18.18：done 事件带块数（UI 显示"共 N 块"）
        int doneTotal = 0, doneHave = 0;
        if ("chunk".equals(ib.mode) && ib.cmap != null) {
            doneTotal = FdResume.totalChunks(ib.size);
            doneHave = ib.cmap.count();
        }
        emitRecv(ib, "done", null, ib.size / dt, saved[0], saved[1],
                doneTotal, doneHave);
        // ★ v1.16.0：落盘后**回读确认**（read-back）。
        // 前面只保证"写进 MediaStore 没抛异常"，但文件是否真的可见/大小对不对
        // 并没有验证。用户实测过"发送端显示已发送、接收端显示失败"，根因之一
        // 就是这类假成功。这里回读一次，把真实结果一起回给发送方。
        boolean verified = verifySavedFile(ib, saved);
        try {
            sendJson(conn, FdProto.obj("type", FdProto.T_FILE_OK, "tid", tid,
                    "path", saved[0],
                    "verified", verified,
                    "size", ib.size));
        } catch (Exception ignored) {}
        // 本地已无在途接收时释放唤醒窗口
        if (inbounds.isEmpty()) setTransferring(false);
    }

    /**
     * ★ v1.16.0：回读确认 —— 落盘后重新查一次文件，确认真的存在且大小一致。
     *
     * 为什么要回读：MediaStore 的 insert + IS_PENDING 两段式写入在某些机型上
     * 会出现"insert 成功、文件实际未落盘"的情况；此前只依据"没抛异常"就回
     * FILE_OK，于是发送端显示"已发送"，而接收端稍后读文件时才发现是空的。
     *
     * @param saved [0]=展示路径 [1]=content Uri（低版本为空）
     */
    private boolean verifySavedFile(Inbound ib, String[] saved) {
        try {
            if (Build.VERSION.SDK_INT >= 29) {
                String uriStr = saved.length > 1 ? saved[1] : "";
                if (uriStr != null && uriStr.startsWith("content:")) {
                    android.net.Uri u = android.net.Uri.parse(uriStr);
                    android.database.Cursor cur = ctx.getContentResolver().query(u,
                            new String[]{android.provider.MediaStore.MediaColumns.SIZE},
                            null, null, null);
                    if (cur != null) {
                        boolean ok = false;
                        if (cur.moveToFirst()) {
                            long sz = cur.getLong(0);
                            ok = sz == ib.size;
                        }
                        cur.close();
                        if (ok) return true;
                    }
                }
                // 降级：按文件名回查 MediaStore
                android.net.Uri again = FdUtil.findInDownloads(ctx, ib.name);
                return again != null;
            }
            // API <29：直接看文件
            if (saved.length > 0 && saved[0] != null) {
                File f = new File(saved[0]);
                return f.exists() && f.length() == ib.size;
            }
        } catch (Throwable ignored) {}
        return false;
    }

    /**
     * ★ v1.18.18：设备显示名 —— <b>备注优先</b>，其次设备自报名，最后 id 前 8 位。
     *
     * <p>备注只存在本机（Prefs.peer_aliases），<b>不改写对端自报名</b>：
     * 若两端互相回传备注，用户在 A 端改名会把 B 端的备注也冲掉。
     *
     * <p>所有会显示给用户的取名都必须走这里 —— 设备列表、气泡、托盘、
     * 接收文件夹名。漏一处就会出现"备注改了但某个地方还是旧名"。
     */
    public String displayName(String peerId) {
        try {
            String alias = getAlias(peerId);
            if (alias != null && !alias.trim().isEmpty()) return alias.trim();
        } catch (Throwable ignored) {}
        return peerNameOf(peerId);
    }

    /** 设置/清除设备备注（空串 = 清除，恢复显示设备自报名） */
    public void setAlias(String peerId, String alias) {
        try {
            prefs.setAlias(peerId, alias);
            notifyPeers();
        } catch (Throwable ignored) {}
    }

    public String getAlias(String peerId) {
        try {
            return prefs.getAlias(peerId);
        } catch (Throwable t) {
            return "";
        }
    }

    /**
     * ★ v1.18.18：断点残留 GC —— 清理超过 7 天且当前无在途任务的
     * .part / .bmp / .fp。否则长期不用会把缓存目录撑爆。
     */
    private void gcResumeState() {
        try {
            File dir = FdUtil.cacheDir(ctx);
            File[] fs = dir.listFiles();
            if (fs == null) return;
            long now = System.currentTimeMillis();
            for (File f : fs) {
                String n = f.getName();
                if (!(n.endsWith(".part") || n.endsWith(".bmp") || n.endsWith(".fp")))
                    continue;
                String tid = n.substring(0, n.lastIndexOf('.'));
                boolean busy = false;
                for (Inbound ib : inbounds.values()) {
                    if (tid.equals(ib.tid)) { busy = true; break; }
                }
                if (busy) continue;
                if (now - f.lastModified() > RESUME_TTL_MS) {
                    try { f.delete(); } catch (Throwable ignored) {}
                }
            }
        } catch (Throwable ignored) {}
    }

    /** 设备名（用于接收文件分文件夹）；查不到时回退到 id 前 8 位 */
    private String peerNameOf(String peerId) {
        Peer p = peerId == null ? null : peers.get(peerId);
        if (p != null && p.name != null && !p.name.isEmpty()) return p.name;
        if (peerId == null || peerId.isEmpty()) return "未知设备";
        return peerId.substring(0, Math.min(8, peerId.length()));
    }

    /**
     * 将 .part 保存为 Download/FlashDrop/<设备名>/<name>（按设备分文件夹）。
     * 返回 [展示路径, 可打开 Uri 字符串]
     */
    private String[] saveToDownloads(String name, String mime, File partFile,                                     String peerName) throws Exception {
        String folder = FdUtil.folderNameOf(peerName);
        if (Build.VERSION.SDK_INT >= 29) {
            android.content.ContentValues cv = new android.content.ContentValues();
            cv.put(android.provider.MediaStore.Downloads.DISPLAY_NAME, name);
            cv.put(android.provider.MediaStore.Downloads.MIME_TYPE, mime);
            cv.put(android.provider.MediaStore.Downloads.RELATIVE_PATH,
                    android.os.Environment.DIRECTORY_DOWNLOADS + "/FlashDrop/" + folder);
            cv.put(android.provider.MediaStore.Downloads.IS_PENDING, 1);
            android.net.Uri uri = ctx.getContentResolver().insert(
                    android.provider.MediaStore.Downloads.EXTERNAL_CONTENT_URI, cv);
            if (uri == null) throw new Exception("MediaStore 拒绝写入");
            try (java.io.OutputStream os = ctx.getContentResolver().openOutputStream(uri);
                 java.io.FileInputStream fis = new java.io.FileInputStream(partFile)) {
                byte[] buf = new byte[1 << 16];
                int n;
                while ((n = fis.read(buf)) > 0) os.write(buf, 0, n);
            }
            android.content.ContentValues done = new android.content.ContentValues();
            done.put(android.provider.MediaStore.Downloads.IS_PENDING, 0);
            ctx.getContentResolver().update(uri, done, null, null);
            return new String[]{"Download/FlashDrop/" + folder + "/" + name, uri.toString()};
        } else {
            File dir = FdUtil.legacySaveDir();
            File sub = new File(dir, folder);   // 按设备分子目录
            if (!sub.exists()) sub.mkdirs();
            File dst = uniqueFile(sub, name);
            try (java.io.FileInputStream fis = new java.io.FileInputStream(partFile);
                 java.io.FileOutputStream fos = new java.io.FileOutputStream(dst)) {
                byte[] buf = new byte[1 << 16];
                int n;
                while ((n = fis.read(buf)) > 0) fos.write(buf, 0, n);
            }
            MediaScannerConnection.scanFile(ctx, new String[]{dst.getAbsolutePath()}, null, null);
            return new String[]{dst.getAbsolutePath(), ""};
        }
    }

    private static File uniqueFile(File dir, String name) {
        File f = new File(dir, name);
        if (!f.exists()) return f;
        String base = name, ext = "";
        int d = name.lastIndexOf('.');
        if (d > 0) { base = name.substring(0, d); ext = name.substring(d); }
        int i = 1;
        while (f.exists()) { f = new File(dir, base + " (" + i + ")" + ext); i++; }
        return f;
    }

    /**
     * 结束一个接收任务。
     *
     * @param dropState
     *   false —— <b>保留</b> .part 与位图（连接中断 / 缺块 / 落盘失败）：
     *            发送方重连后用同 tid 再来即可续传。
     *   true  —— <b>彻底删除</b>续传状态（MD5 失败 / 取消 / 拒绝 / 确认超时）：
     *            内容已不可信，留着只会占空间并可能误判为可续传。
     */
    private void cleanupInbound(Inbound ib, boolean dropState) {
        inbounds.remove(ib.peerId + "|" + ib.tid);
        try { if (ib.out != null) ib.out.close(); } catch (Exception ignored) {}
        ib.out = null;
        try { if (ib.raf != null) ib.raf.close(); } catch (Exception ignored) {}
        ib.raf = null;
        if (dropState) {
            try { if (ib.partFile != null) ib.partFile.delete(); } catch (Exception ignored) {}
            FdResume.dropResumeState(FdUtil.cacheDir(ctx), ib.tid);
        }
        // ★ v1.16.0：本地已无在途接收任务时释放唤醒窗口（发送侧可能仍在传，稍后会各自释放）
        if (inbounds.isEmpty() && !transferringNow.get()) releaseWakeLock();
    }

    /** inbounds 的安全快照（避免遍历时被并发修改） */
    private java.util.List<Map.Entry<String, Inbound>> inboundsSnapshot() {
        try {
            return new java.util.ArrayList<>(inbounds.entrySet());
        } catch (Throwable t) {
            return java.util.Collections.emptyList();
        }
    }

    /** 整体读文件计算 MD5（chunk 模式：块可乱序/跨重连到达，不能用增量摘要） */
    private String md5OfFile(File f) {
        if (f == null || !f.isFile()) return null;
        try (java.io.FileInputStream fis = new java.io.FileInputStream(f)) {
            MessageDigest md = MessageDigest.getInstance("MD5");
            byte[] buf = new byte[1 << 16];
            int n;
            while ((n = fis.read(buf)) > 0) md.update(buf, 0, n);
            StringBuilder sb = new StringBuilder();
            for (byte b : md.digest()) sb.append(String.format("%02x", b));
            return sb.toString();
        } catch (Exception e) {
            return null;
        }
    }

    private void emitRecv(Inbound ib, String state, String reason, Double speed) {
        emitRecv(ib, state, reason, speed, null, null);
    }

    private void emitRecv(Inbound ib, String state, String reason, Double speed, String path,
                          String openUri) {
        emitRecv(ib, state, reason, speed, path, openUri, 0, 0);
    }

    private void emitRecv(Inbound ib, String state, String reason, Double speed, String path,
                          String openUri, int haveChunks, int totalChunks) {
        emit(FdProto.obj("event", "transfer", "kind", "recv", "tid", ib.tid,
                "peer_id", ib.peerId,
                // ★ v1.18.18：走 displayName，否则用户给设备起的备注对气泡不生效
                "name", displayName(ib.peerId),
                "file", ib.name, "size", ib.size, "mime", ib.mime,
                "transferred", ib.received, "state", state,
                "reason", reason == null ? "" : reason,
                "path", path == null ? "" : path,
                "open", openUri == null ? "" : openUri,
                "scheme", ib.scheme == null ? "" : ib.scheme,
                "total_chunks", totalChunks,
                "have_chunks", haveChunks,
                "attempt", ib.attempt,
                "speed", speed == null ? 0 : speed));
    }

    /** 带断点信息的 recv 事件（自动带上 have/total 块数） */
    private void emitRecv2(Inbound ib, String state, String reason, Double speed) {
        int total = 0, have = 0;
        if ("chunk".equals(ib.mode) && ib.cmap != null) {
            total = FdResume.totalChunks(ib.size);
            have = ib.cmap.count();
        }
        emitRecv(ib, state, reason, speed, null, null, have, total);
    }

    private void emitSendState(String tid, String pid, String state, String reason, String path) {
        emitSendState(tid, pid, state, reason, path, 0);
    }

    /** ★ v1.18.18：多带一个 attempt（自动重试次数），UI 用来显示"重试中（第 n 次）" */
    private void emitSendState(String tid, String pid, String state, String reason,
                               String path, int attempt) {
        JSONObject info = sendInfo.get(tid);
        if (info == null) return;
        emit(FdProto.obj("event", "transfer", "kind", "send", "tid", tid,
                "peer_id", pid, "file", info.optString("name"),
                "size", info.optLong("size"), "mime", info.optString("mime"),
                "state", state,
                "reason", reason == null ? "" : reason,
                "path", path == null ? "" : path,
                "transferred", "ok".equals(state) ? info.optLong("size") : 0,
                "attempt", attempt,
                "targets", info.optJSONArray("targets") == null ? new JSONArray()
                        : info.optJSONArray("targets")));
    }

    // ============================ 发送 ============================

    /** 发送文本；返回 mid。事件: text_state */
    public String sendText(List<String> targetIds, String text) {
        final String mid = FdUtil.shortUid();
        pool.execute(() -> {
            for (String pid : targetIds) {
                Conn c = waitConn(pid, 15000);
                if (c == null) {
                    emit(FdProto.obj("event", "text_state", "peer_id", pid, "mid", mid,
                            "state", "failed", "reason", "设备不在线"));
                    continue;
                }
                Object[] slot = newSlot();
                ackWaiters.put(pid + "|" + mid, slot);
                try {
                    sendJson(c, FdProto.obj("type", FdProto.T_TEXT, "mid", mid,
                            "text", text, "ts", FdUtil.nowMs(),
                            "scheme", prefs.bubbleScheme()));
                } catch (Exception e) {
                    dropSlot(ackWaiters, pid + "|" + mid);
                    emit(FdProto.obj("event", "text_state", "peer_id", pid, "mid", mid,
                            "state", "failed", "reason", String.valueOf(e)));
                    continue;
                }
                Object[] r = waitSlot(slot, 12000);
                dropSlot(ackWaiters, pid + "|" + mid);
                emit(FdProto.obj("event", "text_state", "peer_id", pid, "mid", mid,
                        "state", "ok".equals(r[0]) ? "ok" : "timeout"));
            }
        });
        return mid;
    }

    /**
     * ★ v1.18.15：<b>同步</b>发送文本并等到每个目标都有结论。
     *
     * <p>与 {@link #sendText} 的区别：sendText 立即返回、结果只通过 text_state
     * 事件异步通知；而它内部要 {@code waitConn}（最多 15s 等 TCP 连接 + hello）
     * 再等 ack（12s）。「待发队列」必须知道结果才能决定条目去留，所以需要这个
     * 阻塞版本。
     *
     * <p><b>必须在工作线程调用</b>（会阻塞）。
     *
     * @return Object[]{mid, Map&lt;peerId, "ok"/"failed"/"timeout"&gt;}
     */
    public Object[] sendTextSync(List<String> targetIds, String text,
                                 long connTimeoutMs, long ackTimeoutMs) {
        final String mid = FdUtil.shortUid();
        java.util.Map<String, String> res = new java.util.concurrent.ConcurrentHashMap<>();
        if (targetIds == null) return new Object[]{mid, res};
        for (String pid : targetIds) {
            Conn c = waitConn(pid, connTimeoutMs);
            if (c == null) {
                res.put(pid, "failed");
                emit(FdProto.obj("event", "text_state", "peer_id", pid, "mid", mid,
                        "state", "failed", "reason", "设备不在线"));
                continue;
            }
            Object[] slot = newSlot();
            ackWaiters.put(pid + "|" + mid, slot);
            try {
                sendJson(c, FdProto.obj("type", FdProto.T_TEXT, "mid", mid,
                        "text", text, "ts", FdUtil.nowMs(),
                        "scheme", prefs.bubbleScheme()));
            } catch (Exception e) {
                dropSlot(ackWaiters, pid + "|" + mid);
                res.put(pid, "failed");
                emit(FdProto.obj("event", "text_state", "peer_id", pid, "mid", mid,
                        "state", "failed", "reason", String.valueOf(e)));
                continue;
            }
            Object[] r = waitSlot(slot, ackTimeoutMs);
            dropSlot(ackWaiters, pid + "|" + mid);
            String st = "ok".equals(r[0]) ? "ok" : "timeout";
            res.put(pid, st);
            emit(FdProto.obj("event", "text_state", "peer_id", pid, "mid", mid,
                    "state", st));
        }
        return new Object[]{mid, res};
    }

    /**
     * ★ v1.18.18：<b>同步</b>发送文件并等到每个目标都有结论。
     *
     * <p>与 {@link #sendFiles} 的区别：sendFiles 起线程后立即返回、
     * 结果只能从事件流里猜；而待发队列必须知道每个目标是否真正送达
     * 才能决定条目去留（确认送达才移除 —— 否则文件传失败会被永久丢掉，
     * 与 v1.18.15 修复前的文本待发同款 bug）。
     *
     * <p><b>必须在工作线程调用</b>（内部 sendFileTo 会阻塞直至结论，
     * 含最多 3 次自动重试；失败同样保留断点，重试时只补缺失块）。
     *
     * @return Map&lt;peerId, "ok"|"fail"&gt; —— 任一文件送达即记 ok
     */
    public java.util.Map<String, String> sendFileSync(List<String> targetIds,
                                                      List<String> paths) {
        java.util.Map<String, String> res = new java.util.HashMap<>();
        if (targetIds == null || paths == null) return res;
        for (String pid : targetIds) res.put(pid, "fail");
        for (String path : paths) {
            String name = fileNameOf(path);
            if (name == null) continue;
            long size = fileSizeOf(path);
            if (size < 0) continue;
            String tid = FdUtil.shortUid();
            String mime = FdUtil.guessMime(name);
            sendInfo.put(tid, FdProto.obj("name", name, "size", size, "mime", mime,
                    "targets", new JSONArray(targetIds), "src", path));
            Map<String, String> st = new java.util.concurrent.ConcurrentHashMap<>();
            for (String pid : targetIds) st.put(pid, "sending");
            outStates.put(tid, st);
            // sendFileTo 本身是同步方法（阻塞到结论），直接在当前线程串行调
            for (String pid : targetIds) {
                sendFileTo(pid, tid, path, name, size, mime);
            }
            Map<String, String> fin = outStates.remove(tid);
            sendInfo.remove(tid);
            if (fin == null) continue;
            for (String pid : targetIds) {
                if ("ok".equals(fin.get(pid))) res.put(pid, "ok");
            }
        }
        return res;
    }

    /** 发送文件（路径或 content Uri 字符串） */
    public void sendFiles(List<String> targetIds, List<String> paths) {        pool.execute(() -> {
            for (String path : paths) {
                String name = fileNameOf(path);
                if (name == null) continue;
                long size = fileSizeOf(path);
                if (size < 0) continue;
                String tid = FdUtil.shortUid();
                String mime = FdUtil.guessMime(name);
                JSONArray targets = new JSONArray(targetIds);
                sendInfo.put(tid, FdProto.obj("name", name, "size", size, "mime", mime,
                        "targets", targets, "src", path));
                Map<String, String> st = new ConcurrentHashMap<>();
                for (String pid : targetIds) st.put(pid, "sending");
                outStates.put(tid, st);
                for (String pid : targetIds) {
                    emit(FdProto.obj("event", "transfer", "kind", "send", "tid", tid,
                            "peer_id", pid, "file", name, "size", size, "mime", mime,
                            "state", "started", "transferred", 0, "targets", targets,
                            "src", path));
                }
                List<Thread> ts = new ArrayList<>();
                for (String pid : targetIds) {
                    Thread t = new Thread(() -> sendFileTo(pid, tid, path, name, size, mime));
                    ts.add(t);
                    t.start();
                }
                for (Thread t : ts) {
                    try { t.join(); } catch (InterruptedException ignored) {}
                }
            }
        });
    }

    private String fileNameOf(String path) {
        try {
            if (path.startsWith("content:")) {
                android.net.Uri uri = android.net.Uri.parse(path);
                try (android.database.Cursor cur = ctx.getContentResolver().query(uri, null, null, null, null)) {
                    if (cur != null && cur.moveToFirst()) {
                        int idx = cur.getColumnIndex(android.provider.OpenableColumns.DISPLAY_NAME);
                        if (idx >= 0) {
                            String nm = cur.getString(idx);
                            if (nm != null) return FdUtil.safeFileName(nm);
                        }
                    }
                }
                return "file";
            }
            return new File(path).getName();
        } catch (Exception e) { return null; }
    }

    private long fileSizeOf(String path) {
        try {
            if (path.startsWith("content:")) {
                android.net.Uri uri = android.net.Uri.parse(path);
                try (android.database.Cursor cur = ctx.getContentResolver().query(uri, null, null, null, null)) {
                    if (cur != null && cur.moveToFirst()) {
                        int idx = cur.getColumnIndex(android.provider.OpenableColumns.SIZE);
                        if (idx >= 0 && !cur.isNull(idx)) return cur.getLong(idx);
                    }
                }
                // 未声明大小时流式获取
                try (java.io.InputStream is = ctx.getContentResolver().openInputStream(uri)) {
                    if (is == null) return -1;
                    byte[] buf = new byte[1 << 16];
                    long total = 0; int n;
                    while ((n = is.read(buf)) > 0) total += n;
                    return total;
                }
            }
            return new File(path).length();
        } catch (Exception e) { return -1; }
    }

    private java.io.InputStream openSrc(String path) throws Exception {
        if (path.startsWith("content:"))
            return ctx.getContentResolver().openInputStream(android.net.Uri.parse(path));
        return new FileInputStream(path);
    }

    /**
     * ★ v1.18.18：发送单个文件到单个目标（外层带自动重试）。
     *
     * <p>失败分两类：
     * <ul>
     *   <li><b>可重试</b>（设备不在线 / 连接中断 / 等待超时）：指数退避后重试，
     *       <b>沿用同一个 tid</b> —— 接收端凭 tid 找回 .part 与位图，只补缺失块，
     *       这就是断点续传真正生效的地方。</li>
     *   <li><b>不可重试</b>（对方拒绝 / 已取消 / 源文件读不了）：立即失败，
     *       避免对着一个已拒绝的连接反复敲。</li>
     * </ul>
     */
    private void sendFileTo(String pid, String tid, String path, String name,
                            long size, String mime) {
        int attempt = 0;
        while (true) {
            Object[] r = sendFileOnce(pid, tid, path, name, size, mime, attempt);
            String result = (String) r[0];
            String reason = (String) r[1];
            boolean retryable = Boolean.TRUE.equals(r[2]);
            if ("ok".equals(result)) return;
            if (!retryable || attempt >= SEND_MAX_RETRY) {
                Map<String, String> st = outStates.get(tid);
                if (st != null) st.put(pid, "fail");
                emitSendState(tid, pid, "failed", reason, null, attempt);
                return;
            }
            attempt++;
            double delay = FdResume.nextBackoff(attempt, SEND_RETRY_BASE, SEND_RETRY_CAP);
            log("发送 " + name + " 给 " + displayName(pid) + " 失败（" + reason
                    + "），" + FdUtil.secondsText(delay) + "后第 " + attempt
                    + " 次重试（断点续传）");
            emitSendState(tid, pid, "retrying", reason, null, attempt);
            try {
                // ★ 用 sleep 而不是 scheduler：sendFileTo 本身已跑在 pool 线程里，
                //   scheduler 只有 3 线程且承担心跳/扫描/清理，不能拿来睡觉。
                Thread.sleep((long) (delay * 1000));
            } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                return;
            }
        }
    }

    /**
     * 单次发送尝试。返回 Object[]{result, reason, retryable}。
     * result ∈ {"ok","fail"}。
     */
    private Object[] sendFileOnce(String pid, String tid, String path, String name,
                                  long size, String mime, int attempt) {
        Conn c = waitConn(pid, 15000);
        if (c == null) return new Object[]{"fail", "设备不在线", Boolean.TRUE};
        String key = pid + "|" + tid;
        Object[] readySlot = newSlot();
        Object[] okSlot = newSlot();
        readyWaiters.put(key, readySlot);
        okWaiters.put(key, okSlot);
        MessageDigest md5;
        try { md5 = MessageDigest.getInstance("MD5"); } catch (Exception e) { md5 = null; }
        long t0 = System.currentTimeMillis();
        long lastEvt = 0;
        // ★ v1.16.0：进入传输态（申请 CPU 唤醒窗口，防止息屏被冻结打断）
        setTransferring(true);
        try {
            sendJson(c, FdProto.obj("type", FdProto.T_FILE_START, "tid", tid, "name", name,
                    "size", size, "mime", mime, "scheme", prefs.bubbleScheme(),
                    // ★ v1.18.18：声明支持带块号分块 + 本次是第几次尝试
                    "idx", 1,
                    "attempt", attempt));
            Object[] r = waitSlot(readySlot, 45000);
            // 不可重试：对方明确拒绝 / 已取消
            if ("refuse".equals(r[0])) return new Object[]{"fail", "对方拒绝接收", Boolean.FALSE};
            if ("cancel".equals(r[0])) return new Object[]{"fail", "对方已取消", Boolean.FALSE};
            if (!"ready".equals(r[0])) {
                return new Object[]{"fail", "等待对方确认超时", Boolean.TRUE};
            }

            // ★ v1.18.18：断点信息（仅 chunk 模式携带）
            boolean idxMode = false;
            java.util.Set<Integer> skip = new java.util.HashSet<>();
            int total = FdResume.totalChunks(size);
            org.json.JSONObject ready = (r.length > 1 && r[1] instanceof JSONObject)
                    ? (JSONObject) r[1] : null;
            if (ready != null && ready.optInt("idx", 0) == 1) {
                idxMode = true;
                FdResume.ChunkMap cm =
                        FdResume.ChunkMap.fromCompactJson(ready.optJSONArray("have"), total);
                // ★ 跳过集合 = 已收到的块 = 全部块 - missing()。
                //   把 missing()（待发块）当跳过集 -> 首次传输一个块都不发。
                java.util.Set<Integer> todo = new java.util.HashSet<>(cm.missing());
                skip = new java.util.HashSet<>();
                for (int i = 0; i < total; i++) if (!todo.contains(i)) skip.add(i);
                if (!skip.isEmpty()) {
                    log("断点续传 " + name + " → " + displayName(pid)
                            + "：跳过已收 " + skip.size() + "/" + total + " 块");
                }
            }

            try (java.io.InputStream is = new BufferedInputStream(openSrc(path), 1 << 16)) {
                byte[] buf = new byte[FdProto.CHUNK_SIZE];
                // 进度基准：续传时对方已有一部分，从中间起算，否则进度条倒退
                long baseDone = 0;
                for (int i : skip) baseDone += FdResume.chunkLen(i, size);
                long done = baseDone;
                long sent = 0;
                int n, idx = 0;
                while ((n = is.read(buf)) > 0) {
                    byte[] chunk = java.util.Arrays.copyOf(buf, n);
                    if (idxMode) {
                        if (!skip.contains(idx)) {
                            sendRaw(c, FdProto.encodeChunk(tid, idx, chunk));
                            sent += n;
                        }
                    } else {
                        sendRaw(c, FdProto.encodeBin(tid, chunk));
                        sent += n;
                    }
                    // ★ MD5 必须覆盖**全部**块（无论本轮发没发）。
                    //   接收端按整文件校验，摘要必须来自全量数据；
                    //   续传时跳过的块也要喂进去，否则摘要只覆盖本轮实际发出的部分，
                    //   接收端 MD5 校验必失败。
                    if (md5 != null) md5.update(chunk);
                    done += n;
                    idx++;
                    long now = System.currentTimeMillis();
                    if (now - lastEvt > 150) {
                        lastEvt = now;
                        double dt = (now - t0) / 1000.0;
                        emit(FdProto.obj("event", "transfer", "kind", "send", "tid", tid,
                                "peer_id", pid, "file", name, "size", size, "mime", mime,
                                "state", "progress", "transferred", Math.min(done, size),
                                "attempt", attempt,
                                "speed", dt > 0.1 ? sent / dt : 0));
                    }
                }
            }
            StringBuilder sb = new StringBuilder();
            if (md5 != null) for (byte b : md5.digest()) sb.append(String.format("%02x", b));
            sendJson(c, FdProto.obj("type", FdProto.T_FILE_END, "tid", tid, "md5", sb.toString()));
            // ★ v1.16.0：等对方落盘确认的超时由 180s 放宽到 300s。
            // 收端落盘（MediaStore 写入 + MD5 校验）在息屏低电模式下可能明显变慢，
            // 旧超时会让"其实已经成功"的传输被判失败。
            Object[] rr = waitSlot(okSlot, 300000);
            if ("timeout".equals(rr[0])) {
                return new Object[]{"fail", "等待对方确认超时", Boolean.TRUE};
            }
            if ("fail".equals(rr[0])) {
                return new Object[]{"fail",
                        rr.length > 1 && rr[1] != null ? String.valueOf(rr[1])
                                : "对方接收失败", Boolean.TRUE};
            }
            return new Object[]{"ok", "", Boolean.FALSE};
        } catch (java.io.FileNotFoundException e) {
            // 源文件读不了 -> 重试也没用
            return new Object[]{"fail", "源文件不可读: " + name, Boolean.FALSE};
        } catch (Exception e) {
            return new Object[]{"fail", "连接中断: " + e, Boolean.TRUE};
        } finally {
            // ★ v1.16.0：退出传输态（释放 CPU 唤醒窗口）
            setTransferring(false);
            dropSlot(readyWaiters, key);
            dropSlot(okWaiters, key);
        }
    }

    public void cancelSend(String tid) {
        pool.execute(() -> {
            Map<String, String> st = outStates.get(tid);
            if (st == null) return;
            for (String pid : st.keySet().toArray(new String[0])) {
                String cur = st.get(pid);
                if ("ok".equals(cur) || "fail".equals(cur) || "refuse".equals(cur)
                        || "cancel".equals(cur)) continue;
                Conn c = conns.get(pid);
                if (c != null && c.alive) {
                    try { sendJson(c, FdProto.obj("type", FdProto.T_CANCEL, "tid", tid)); }
                    catch (Exception ignored) {}
                }
                String key = pid + "|" + tid;
                resolveWaiter(readyWaiters, key, new Object[]{"cancel", null});
                resolveWaiter(okWaiters, key, new Object[]{"cancel", null});
                st.put(pid, "cancel");
                emitSendState(tid, pid, "cancelled", "已取消", null);
            }
        });
    }

    public void acceptInbound(String tid) {
        pool.execute(() -> {
            for (Inbound ib : inbounds.values()) {
                if (ib.tid.equals(tid) && !ib.started && !ib.done) {
                    beginInbound(ib);
                    if (ib.started) {
                        Conn c = conns.get(ib.peerId);
                        if (c != null && c.alive) {
                            // ★ v1.18.18：走 sendRecvReady，续传时带上已收位图
                            try { sendRecvReady(c, ib); }
                            catch (Exception ignored) {}
                        }
                    }
                    return;
                }
            }
        });
    }

    public void rejectInbound(String tid) {
        pool.execute(() -> {
            for (Inbound ib : inbounds.values()) {
                if (ib.tid.equals(tid) && !ib.started && !ib.done) {
                    Conn c = conns.get(ib.peerId);
                    if (c != null && c.alive) {
                        try { sendJson(c, FdProto.obj("type", FdProto.T_REFUSE, "tid", tid,
                                "reason", "对方拒绝接收")); } catch (Exception ignored) {}
                    }
                    cleanupInbound(ib, true);   // 拒绝 -> 彻底清理
                    emitRecv(ib, "refused", "已拒绝", null);
                    return;
                }
            }
        });
    }

    public void cancelInbound(String tid) {
        pool.execute(() -> {
            for (Inbound ib : inbounds.values()) {
                if (ib.tid.equals(tid)) {
                    Conn c = conns.get(ib.peerId);
                    if (c != null && c.alive) {
                        try { sendJson(c, FdProto.obj("type", FdProto.T_CANCEL, "tid", tid)); }
                        catch (Exception ignored) {}
                    }
                    ib.canceled = true;
                    cleanupInbound(ib, true);   // 取消 -> 彻底清理
                    emitRecv(ib, "cancelled", "已取消接收", null);
                    return;
                }
            }
        });
    }

    // ============================ 连接调度 ============================

    private void ensureConnected(Peer p, boolean force) {
        if (!running.get() || p == null || p.id.equals(deviceId)) return;
        Conn c = conns.get(p.id);
        if (c != null && c.alive && !c.replaced) return;
        if (p.connecting) return;
        long now = System.currentTimeMillis();
        if (!force && now < p.nextRetry) return;
        if (!force && now - p.lastSeen > 120000 && !p.manual) return;
        p.connecting = true;
        pool.execute(() -> {
            try {
                for (String ip : p.ips.toArray(new String[0])) {
                    Conn cc = conns.get(p.id);
                    if (cc != null && cc.alive && !cc.replaced) return;
                    try {
                        Conn conn = openConn(ip, p.tcpPort, 3000);
                        sendJson(conn, helloMsg());
                        pool.execute(() -> session(conn));
                        return;
                    } catch (Exception ignored) { }
                }
                p.backoff = Math.min(p.backoff * 2, 30);
                p.nextRetry = System.currentTimeMillis() + (long) (p.backoff * 1000);
            } finally {
                p.connecting = false;
            }
        });
    }

    private Conn waitConn(String peerId, long timeoutMs) {
        long deadline = System.currentTimeMillis() + timeoutMs;
        Peer p = peers.get(peerId);
        if (p != null) ensureConnected(p, true);
        while (System.currentTimeMillis() < deadline) {
            Conn c = conns.get(peerId);
            if (c != null && c.alive && !c.replaced && c.helloGot) return c;
            try { Thread.sleep(200); } catch (InterruptedException e) { return null; }
        }
        return null;
    }

    /** 手动连接；阻塞，返回 [ok, info]（须在工作线程调用） */
    public Object[] connectManual(String host, int portNum) {
        try {
            Conn conn = openConn(host, portNum, 4000);
            sendJson(conn, helloMsg());
            JSONObject hello = readHello(conn, 6000);
            if (hello == null) { closeConn(conn); return new Object[]{false, "对端无响应"}; }
            if (hello.optString("id").equals(deviceId)) {
                closeConn(conn); return new Object[]{false, "不能添加自己"};
            }
            conn.sock.setSoTimeout(0);
            if (!registerConn(conn, hello)) return new Object[]{false, "已存在更优连接"};
            Peer p = peers.get(hello.optString("id"));
            if (p != null) {
                p.manual = true;
                if (!p.ips.contains(host)) p.ips.add(0, host);
            }
            pool.execute(() -> readerLoop(conn));
            notifyPeers();
            return new Object[]{true, p != null ? p.name : hello.optString("id").substring(0, 8)};
        } catch (Exception e) {
            return new Object[]{false, "连接失败: " + e};
        }
    }

    // ============================ 子网扫描 ============================

    private static final String[] COMMON_SUBNETS = buildCommonSubnets();

    private static String[] buildCommonSubnets() {
        List<String> l = new ArrayList<>();
        for (int i = 0; i < 32; i++) l.add("192.168." + i + ".0");
        l.add("10.0.0.0"); l.add("10.0.1.0"); l.add("10.0.2.0");
        l.add("10.1.0.0"); l.add("10.8.0.0");
        l.add("172.16.0.0"); l.add("172.17.0.0"); l.add("172.20.0.0"); l.add("172.30.0.0");
        l.add("100.64.0.0");
        return l.toArray(new String[0]);
    }

    /** 扫描候选网段（full=深度扫描）；在后台线程调用 */
    public void scan(boolean full) {
        if (!running.get() || !scanning.compareAndSet(false, true)) return;
        try {
            Set<String> subnets = new HashSet<>(knownSubnets);
            for (InterfaceAddress ia : ifaceAddrs()) {
                String ip = ia.getAddress().getHostAddress();
                short prefix = ia.getNetworkPrefixLength();
                if (prefix >= 8 && prefix <= 32) {
                    String subnet = cidrSubnet(ip, prefix);
                    if (subnet != null) subnets.add(subnet);
                }
            }
            if (full) Collections.addAll(subnets, COMMON_SUBNETS);
            List<String> ips = new ArrayList<>();
            for (String sn : subnets) {
                String[] p = sn.split("\\.");
                if (p.length != 4) continue;
                String prefix = p[0] + "." + p[1] + "." + p[2] + ".";
                for (int i = 1; i < 255; i++) ips.add(prefix + i);
            }
            ips.add("127.0.0.1");
            final int found = probeAll(ips, port);
            emit(FdProto.obj("event", "scan_done", "full", full, "found", found));
            notifyPeers();
        } catch (Exception ignored) {
        } finally {
            scanning.set(false);
        }
    }

    private static String cidrSubnet(String ip, short prefix) {
        try {
            if (prefix < 8) return null;
            String[] p = ip.split("\\.");
            if (p.length != 4) return null;
            if (prefix >= 24) return p[0] + "." + p[1] + "." + p[2] + ".0";
            if (prefix >= 16) return p[0] + "." + p[1] + ".0.0";
            return p[0] + ".0.0.0";
        } catch (Exception e) { return null; }
    }

    private int probeAll(List<String> ips, int portNum) {
        final int[] found = {0};
        List<java.util.concurrent.Future<?>> futs = new ArrayList<>();
        // 端口扫描统一只探本端端口（对端端口在 HELLO 后由 peer.tcpPort 维护）
        for (String ip : ips) {
            futs.add(probePool.submit(() -> {
                if (!running.get()) return;
                try {
                    Conn conn = openConn(ip, portNum, 450);
                    sendJson(conn, helloMsg());
                    int f = found[0];
                    found[0] = f + 1;
                    pool.execute(() -> session(conn));
                } catch (Exception ignored) {}
            }));
        }
        for (java.util.concurrent.Future<?> f : futs) {
            try { f.get(6, TimeUnit.SECONDS); } catch (Exception ignored) {}
        }
        return found[0];
    }

    public void rescan(boolean full) {
        pool.execute(() -> scan(full));
    }

    // ============================ 查询 ============================

    public boolean isPeerOnline(String pid) {
        Peer p = peers.get(pid);
        if (p == null) return false;
        Conn c = conns.get(pid);
        return p.online() || (c != null && c.alive && !c.replaced);
    }

    public List<String> onlinePeerIds() {
        List<String> out = new ArrayList<>();
        for (Peer p : peers.values()) if (isPeerOnline(p.id)) out.add(p.id);
        return out;
    }
}
