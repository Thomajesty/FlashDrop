package com.flashdrop.app;

import android.app.Application;
import android.app.NotificationManager;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/** 全局 Application：持有 Node/Prefs 单例 */
public class FlashApp extends Application {
    private static FlashApp inst;
    private Prefs prefs;
    private FlashNode node;
    /** 设置页清空聊天记录后通知 MainActivity 重载 */
    public volatile boolean historyCleared = false;
    /** 设备身份合并后通知 MainActivity 重载聊天记录 */
    public volatile boolean historyMerged = false;
    /** 前台界面的事件监听（MainActivity 可见时设置）；为空时由 NodeService 发系统通知 */
    public volatile FlashNode.Listener uiListener;

    // ---------- ★ v1.18.30：消息通知 id 登记（回前台统一 cancel） ----------
    //
    // 背景 bug：桌面图标常亮红 1。两个来源：
    //   1. 后台服务常驻通知渠道默认 setShowBadge(true)，国产 ROM 把它计入
    //      未读 → 没收到消息也亮角标（NodeService 已改 setShowBadge(false)）；
    //   2. 消息通知在"只点桌面图标回应用"时不会自动取消，角标残留。
    // 这里登记后台发出的消息通知 id；onResume 统一 cancel。
    // 常驻服务通知（id=1001）不登记，不受影响。
    private final java.util.Set<Integer> activeNotifIds =
            java.util.Collections.synchronizedSet(new java.util.HashSet<>());

    public void addActiveNotifId(int id) {
        activeNotifIds.add(id);
    }

    /** 取消全部消息通知并清空登记（MainActivity.onResume 调用） */
    public void clearMessageNotifications() {
        try {
            NotificationManager nm = getSystemService(NotificationManager.class);
            for (Integer id : activeNotifIds) {
                nm.cancel(id);
            }
        } catch (Exception ignored) {}
        activeNotifIds.clear();
    }

    // ---------- ★ v1.18.15：待发队列可靠投递 ----------
    //
    // 背景 bug：flushPendingSends() 调 sendText()（**异步**，内部还要 waitConn
    // 最多等 15s TCP 连接 + 12s ack）之后，**立刻**把条目从 pendingSends 移除
    // 并落盘。设备刚上线时 UDP 层已判在线 → 触发 flush，但 TCP 往往还没建好，
    // 于是 waitConn 失败 → text_state=failed → **条目已经没了，消息永久丢失**：
    // 接收端收不到，发送端只看到"发送失败"。而队列本身没有任何重试机制
    // （定时器只跑 announce/expire），所以即使留着也不会自动补发。
    //
    // 修法三条：
    //   1. 确认送达（收到 ack）才移除条目；失败/超时一律保留
    //   2. flush 放到后台线程执行（sendTextSync 会阻塞，不能压 UI）
    //   3. 队列非空且有在线设备时，每 10s 自动重试一次；队列空了自动停

    /** 待发补发的工作线程（sendTextSync 阻塞，必须离开 UI 线程） */
    private final java.util.concurrent.ExecutorService flushPool =
            java.util.concurrent.Executors.newSingleThreadExecutor(r -> {
                Thread t = new Thread(r, "fd-flush-pending");
                t.setDaemon(true);
                return t;
            });

    /** 把结果与界面回调送回主线程 */
    private final android.os.Handler mainHandler =
            new android.os.Handler(android.os.Looper.getMainLooper());

    /** 周期重试间隔 */
    private static final long RETRY_INTERVAL_MS = 10_000L;

    /** 防重入：同一时刻只跑一轮 flush */
    private final java.util.concurrent.atomic.AtomicBoolean flushing =
            new java.util.concurrent.atomic.AtomicBoolean(false);

    private final Runnable retryTask = new Runnable() {
        @Override
        public void run() {
            boolean more = false;
            try {
                if (!pendingSends.isEmpty() && !node().onlinePeerIds().isEmpty()) {
                    flushPendingSendsAsync(null, null, null);
                }
                // ★ v1.18.17 审计修复：队列空了就**不再自我续期**。
                //   原实现无条件 postDelayed，等于每 10 秒永久唤醒一次 CPU ——
                //   在安卓上这是实打实的耗电，还可能顶住后台休眠。
                //   现在队列空即停止；重新入队 / 界面回前台 / 设备上线
                //   都会再次调用 schedulePendingRetry() 把它挂上。
                more = !pendingSends.isEmpty();
            } catch (Throwable ignored) {
                more = !pendingSends.isEmpty();
            }
            if (more) {
                mainHandler.postDelayed(this, RETRY_INTERVAL_MS);
            }
        }
    };

    /**
     * ★ v1.13.1：后台接收消息落库。
     *
     * 背景 bug：应用退到后台（uiListener 为空）时收到文件，NodeService 只弹了
     * 系统通知，既没把这条消息写进内存列表、也没写进 history/*.jsonl ——
     * 文件本体由 FlashNode 底层正常落盘，但"聊天记录"这条腿是断的。
     * 用户点通知回到界面后 loadHistory() 从磁盘读不到任何东西 → 对话框空白。
     *
     * 修复：把与前台 onNodeEvent 完全一致的入库动作（写 jsonl + 写内存）抽到这里，
     * 后台路径也走一遍。前台回到界面时 loadHistory() 会自然读出这些记录；
     * 若界面正好在内存中（未被回收），下面也会直接补进 msgs 并通知刷新。
     *
     * 幂等性：以 (peerId, tid) / (peerId, mid) 为键去重，同一传输的
     * offer/started/progress/done 多次事件只会落一条（后续事件为更新）。
     */
    public void persistInboundEvent(JSONObject e) {
        try {
            String ev = e.optString("event");
            String peerId = e.optString("peer_id");
            if (peerId == null || peerId.isEmpty()) return;   // 无来源设备无法归档
            boolean isText = "text".equals(ev);
            boolean isRecv = "transfer".equals(ev) && "recv".equals(e.optString("kind"));
            if (!isText && !isRecv) return;

            // ★ v1.18.7（关键修复）：后台落库**只认终态**。
            //
            // 旧实现把中间态也落库，并用下面的 bgSeenKeys 按 tid 去重 ——
            // 而一次文件接收会产生 offer → confirm → started → progress → done
            // 一连串事件。于是"第一条事件"（offer）被写进历史并占住了 key，
            // 真正代表结果的 done 反而被去重**跳过**。
            //
            // 后果：用户回到前台时读到的是 state=offer 的记录 → 判定为未完成
            // → 界面显示"接收失败"，而文件其实**已经完整落盘**（这也是为什么
            // 电脑端显示"已送达"、手机 Download 里也能找到文件，唯独状态不对）。
            //
            // 中间态在后台没有落库价值（后台通知只关心 done），只落终态即可，
            // 根因随之消失。
            String st = e.optString("state");
            if (isRecv) {
                boolean terminal = "done".equals(st) || "failed".equals(st)
                        || "refused".equals(st) || "cancelled".equals(st);
                if (!terminal) return;
            }

            synchronized (bgHistoryLock) {
                JSONObject rec = new JSONObject();
                rec.put("kind", isText ? "text" : "file");
                rec.put("dir", "in");
                rec.put("peer_id", peerId);
                rec.put("peer_name", e.optString("name"));
                if (isText) {
                    rec.put("mid", e.optString("mid"));
                    rec.put("text", e.optString("text"));
                } else {
                    rec.put("tid", e.optString("tid"));
                    rec.put("file", e.optString("file"));
                    rec.put("mime", e.optString("mime"));
                    rec.put("state", st);
                    rec.put("path", e.optString("path"));
                    rec.put("size", e.optLong("size"));
                    rec.put("transferred", e.optLong("transferred"));
                }
                String sc = e.optString("scheme");
                if (sc != null && !sc.isEmpty()) rec.put("peer_scheme", sc);
                long ts = e.optLong("ts", 0L);
                rec.put("ts", ts > 0 ? ts : System.currentTimeMillis());

                // 去重：同 tid（文件）/ 同 mid（文本）在同一设备下只保留一条
                String key = peerId + "|" + (isText ? ("m" + e.optString("mid"))
                        : ("t" + e.optString("tid")));
                if (bgSeenKeys.contains(key)) return;
                bgSeenKeys.add(key);
                if (bgSeenKeys.size() > 2000) bgSeenKeys.clear();   // 防止无限增长

                FdUtil.appendHistory(this, peerId, rec);
                // 界面可能还在内存中：直接补进去并标记待刷新
                bgPendingReloadCount++;
            }
        } catch (Exception ignored) {}
    }

    /** 后台落库期间产生的记录数（界面 onResume 时据此决定是否重载） */
    public volatile int bgPendingReloadCount = 0;
    private final Object bgHistoryLock = new Object();
    private final java.util.Set<String> bgSeenKeys =
            java.util.Collections.synchronizedSet(new java.util.HashSet<>());

    /** 待发队列条目：目标离线时保存，任一目标上线后自动发送（v1.9.0 文本与文件统一） */
    public static class PendingSend {
        public final List<String> uris;     // type=file
        public final String text;           // type=text
        public final String type;           // "file" | "text"
        public final List<String> targets;
        /** 群发语义（"全部设备"视图发送）：上线即发给当时所有在线设备 */
        public final boolean broadcast;
        /** 入队时间戳（ms），管理窗口按时间展示 */
        public final long ts;
        /** ★ v1.18.18：已自动补发失败次数（供管理窗口显示"已重试 n 次"） */
        public int attempt = 0;
        /** ★ v1.18.18：最近一次补发失败原因（供管理窗口显示"为什么还在队列里"） */
        public String lastError = "";
        public PendingSend(List<String> u, List<String> t) { this(u, t, null, false); }
        public PendingSend(List<String> u, List<String> t, String text, boolean broadcast) {
            uris = u == null ? new ArrayList<>() : u;
            targets = t == null ? new ArrayList<>() : t;
            this.text = text;
            this.type = (text != null && !text.isEmpty()) ? "text" : "file";
            this.broadcast = broadcast;
            this.ts = System.currentTimeMillis();
        }
        public boolean isText() { return "text".equals(type); }
        /** 气泡与管理窗口用的可读摘要（与 Windows 端 _entry_text 同口径） */
        public String summary() {
            if (isText()) return text == null ? "" : text;
            StringBuilder sb = new StringBuilder();
            int n = Math.min(3, uris.size());
            for (int i = 0; i < n; i++) {
                String name = FdUtil.uriDisplayName(uris.get(i));
                if (name == null || name.isEmpty()) continue;
                if (sb.length() > 0) sb.append("、");
                sb.append(name);
            }
            if (sb.length() == 0) return "待发送文件";
            if (uris.size() > 3) sb.append(" 等 ").append(uris.size()).append(" 个文件");
            return sb.toString();
        }
    }

    public final List<PendingSend> pendingSends = new ArrayList<>();

    @Override
    public void onCreate() {
        super.onCreate();
        inst = this;
        CrashTrap.install(this);
        prefs = new Prefs(this);
        String defName = FdUtil.defaultDeviceName(this);
        // 首次启动写入默认设备名（setName 才是写入；name() 是读取）
        if (prefs.name(defName).isEmpty()) prefs.setName(defName);
        node = new FlashNode(this, prefs.deviceId(), prefs.name(defName),
                prefs.port(FdProto.DEFAULT_PORT), prefs);
        loadPendingSends();
    }

    public static FlashApp get() { return inst; }
    public Prefs prefs() { return prefs; }
    public FlashNode node() { return node; }

    // ---------------- 待发队列持久化 ----------------

    public void savePendingSends() {
        try {
            JSONArray arr = new JSONArray();
            for (PendingSend p : pendingSends) {
                JSONObject o = new JSONObject()
                        .put("uris", new JSONArray(p.uris))
                        .put("targets", new JSONArray(p.targets))
                        .put("broadcast", p.broadcast);
                if (p.text != null) o.put("text", p.text);
                // ★ v1.18.18：失败原因/重试次数也要落盘，
                //   否则重启后"已重试 n 次 · 原因"全部丢失，
                //   用户看到的是"从没发过的旧内容"而没有任何解释
                if (p.attempt > 0) o.put("attempt", p.attempt);
                if (p.lastError != null && !p.lastError.isEmpty())
                    o.put("last_error", p.lastError);
                arr.put(o);
            }
            prefs.setPendingSends(arr.toString());
        } catch (Exception ignored) {}
    }

    public void loadPendingSends() {
        pendingSends.clear();
        try {
            JSONArray arr = new JSONArray(prefs.pendingSends());
            for (int i = 0; i < arr.length(); i++) {
                JSONObject o = arr.getJSONObject(i);
                List<String> u = new ArrayList<>(), t = new ArrayList<>();
                JSONArray ua = o.optJSONArray("uris"), ta = o.optJSONArray("targets");
                if (ua != null) for (int j = 0; j < ua.length(); j++) u.add(ua.optString(j));
                if (ta != null) for (int j = 0; j < ta.length(); j++) t.add(ta.optString(j));
                String text = o.optString("text", "");
                boolean bc = o.optBoolean("broadcast", false);
                if (!u.isEmpty() || !text.isEmpty()) {
                    PendingSend ps = new PendingSend(u, t, text, bc);
                    ps.attempt = o.optInt("attempt", 0);
                    ps.lastError = o.optString("last_error", "");
                    pendingSends.add(ps);
                }
            }
        } catch (Exception ignored) {}
    }

    /**
     * 有设备上线时冲队列：返回已发送的条目数（0=未发送）。
     * 群发条目（broadcast 或无指定目标）发给当时所有在线设备；
     * 定向条目只发给其中已上线的目标；都不满足则继续保留。
     */
    public int flushPendingSends() {
        return flushPendingSends(null);
    }

    /** flush 的核心实现；onSent 可用于把文本补发结果回填到主界面 */
    public int flushPendingSends(java.util.function.Consumer<PendingSend> onSent) {
        return flushPendingSends(onSent, null);
    }

    /**
     * ★ v1.18.9：补发文本时把 **真实 mid** 回传给界面。
     *
     * 旧实现里 `onSent` 只拿到 PendingSend，界面为了"发出去要有气泡"只能
     * 自己 new 一条 Msg 并把 `mid` 置为 null —— 结果 ack / text_state
     * 回来时按 mid 查不到这条消息（`byMid.get(mid)` miss），
     * 状态**永久卡在「发送中」**，而接收端其实早就收到了。
     *
     * 这里把 sendText 的返回值（真实 mid）透出去，界面用它建气泡即可
     * 正常收到 ack 并把状态推进到「已送达」。
     */
    public int flushPendingSends(java.util.function.Consumer<PendingSend> onSent,
                                 java.util.function.BiConsumer<PendingSend, String> onTextSent) {
        // ★ v1.18.15：同步版本已不安全（会在 send 结果未知时丢条目），
        //   统一改走异步的确认式补发；这里保留签名只为兼容旧调用点。
        flushPendingSendsAsync(null, onSent, onTextSent);
        return 0;
    }

    /**
     * ★ v1.18.15：**确认送达才移除**的待发补发（后台线程执行）。
     *
     * <p>与 v1.18.13 的关键差别：条目只有在**收到 ack** 后才从队列移除；
     * 连接失败 / 超时的条目<b>保留在队列里</b>，交给周期重试（每 10s）再发，
     * 绝不会再出现"发失败 → 条目已删 → 消息永久丢失"。
     *
     * <p>另外补一个 v1.18.13 就有的坑：flush 期间用户可能又新加了待发条目，
     * 旧实现 flush 结束时直接 {@code clear() + addAll(remain)}，
     * 会把**发送过程中新增**的条目一起清掉。这里按"快照内外的区分"处理。
     *
     * @param onDone    主线程回调：本次成功送达的条数
     * @param onSent    主线程回调：文件条目已发出
     * @param onTextSent主线程回调：(条目, 真实 mid) —— 界面据此建可收到 ack 的气泡
     */
    public void flushPendingSendsAsync(java.util.function.Consumer<Integer> onDone,
                                       java.util.function.Consumer<PendingSend> onSent,
                                       java.util.function.BiConsumer<PendingSend, String> onTextSent) {
        if (pendingSends.isEmpty()) return;
        if (!flushing.compareAndSet(false, true)) return;   // 防重入
        // 本轮要处理的快照（只动这些；期间新增的条目不在快照里）
        final List<PendingSend> snapshot = new ArrayList<>(pendingSends);
        flushPool.execute(() -> {
            List<PendingSend> failed = new ArrayList<>();
            int sent = 0;
            try {
                List<String> online = node().onlinePeerIds();
                if (!online.isEmpty()) {
                    for (PendingSend ps : snapshot) {
                        List<String> targets = resolveTargets(ps, online);
                        if (targets.isEmpty()) {
                            // ★ v1.18.18：记录原因，让管理窗口能解释"为什么还没发出去"
                            ps.lastError = "目标设备不在线";
                            failed.add(ps);          // 目标还没上线，继续等
                            continue;
                        }
                        if (ps.isText()) {
                            Object[] r = node().sendTextSync(targets, ps.text, 15000, 12000);
                            String mid = (String) r[0];
                            java.util.Map<?, ?> res = (java.util.Map<?, ?>) r[1];
                            boolean anyOk = false;
                            if (res != null) {
                                for (String pid : targets) {
                                    if ("ok".equals(res.get(pid))) { anyOk = true; break; }
                                }
                            }
                            if (!anyOk) {
                                ps.attempt++;        // ★ 失败保留，等重试
                                ps.lastError = "发送失败或未收到回执";
                                failed.add(ps);
                                continue;
                            }
                            sent++;
                            final String fmid = mid;
                            mainHandler.post(() -> {
                                if (onTextSent != null) {
                                    try { onTextSent.accept(ps, fmid); } catch (Exception ignored) {}
                                }
                            });
                        } else {
                            // ★ v1.18.18：改用同步版本 + 确认送达才移除。
                            //   旧实现 sendFiles 后立即当作成功（fire-and-forget），
                            //   文件传输一旦失败，条目照样出队 —— 内容永久丢失，
                            //   与 v1.18.15 修复前的文本待发同款 bug。
                            //   sendFileSync 内部含最多 3 次自动重试（断点续传），
                            //   全部目标都失败时条目保留，记下原因与次数供 UI 显示。
                            java.util.Map<String, String> fres =
                                    node().sendFileSync(targets, ps.uris);
                            boolean fileOk = false;
                            StringBuilder errs = new StringBuilder();
                            for (String pid : targets) {
                                if ("ok".equals(fres.get(pid))) { fileOk = true; break; }
                            }
                            if (!fileOk) {
                                ps.attempt++;
                                for (String pid : targets) {
                                    String r = fres.get(pid);
                                    if (r != null && !"ok".equals(r)
                                            && errs.indexOf(r) < 0) {
                                        if (errs.length() > 0) errs.append("；");
                                        errs.append(r);
                                    }
                                }
                                ps.lastError = errs.length() > 0
                                        ? errs.toString() : "目标设备未收到";
                                failed.add(ps);       // ★ 失败保留，等重试
                                continue;
                            }
                            sent += ps.uris.size();
                        }
                        mainHandler.post(() -> {
                            if (onSent != null) {
                                try { onSent.accept(ps); } catch (Exception ignored) {}
                            }
                        });
                    }
                } else {
                    failed.addAll(snapshot);
                }
            } catch (Throwable ignored) {
                failed.clear();
                failed.addAll(snapshot);               // 异常时保守：全部保留
            }
            final List<PendingSend> keep = failed;
            final int fsent = sent;
            mainHandler.post(() -> {
                try {
                    // 只移除"快照里且本轮成功送达"的条目；
                    // 快照之外新增的条目原样保留（不被误删）。
                    List<PendingSend> next = new ArrayList<>();
                    for (PendingSend p : pendingSends) {
                        if (snapshot.contains(p)) {
                            if (!keep.contains(p)) continue;   // 成功 → 移除
                        }
                        next.add(p);                            // 失败 或 本轮新增 → 保留
                    }
                    pendingSends.clear();
                    pendingSends.addAll(next);
                    savePendingSends();
                } finally {
                    flushing.set(false);
                    if (onDone != null) {
                        try { onDone.accept(fsent); } catch (Exception ignored) {}
                    }
                    // 队列还剩东西 → 继续周期重试
                    if (!pendingSends.isEmpty()) schedulePendingRetry();
                }
            });
        });
    }

    /** 启动/续上待发队列的周期重试（幂等，重复调用只是重置计时） */
    public void schedulePendingRetry() {
        try {
            mainHandler.removeCallbacks(retryTask);
            mainHandler.postDelayed(retryTask, RETRY_INTERVAL_MS);
        } catch (Throwable ignored) {}
    }

    /** 计算某待发条目此刻应发往的目标；空列表表示继续等待 */
    public List<String> resolveTargets(PendingSend ps, List<String> online) {
        List<String> out = new ArrayList<>();
        if (ps.broadcast || ps.targets.isEmpty()) {
            out.addAll(online);          // 群发：所有在线设备
        } else {
            for (String t : ps.targets) if (online.contains(t)) out.add(t);
        }
        return out;
    }
}
