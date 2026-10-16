package com.flashdrop.app;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;

/** 前台服务：保持节点常驻（息屏仍可接收）。
 *  - 常驻通知：设置"显示常驻通知"关闭时降为无声音量（不在通知栏显示）；
 *  - 消息通知：界面不在前台（uiListener 为空）时，收到消息/文件弹系统通知，
 *    点击通知回到聊天界面。 */
public class NodeService extends Service {
    private static final String CH_ID = "flashdrop_service";
    private static final String CH_ID_HIDDEN = "flashdrop_service_hidden";
    private static final String CH_MSG = "flashdrop_msg";
    private static volatile boolean listenerInstalled = false;

    @Override
    public void onCreate() {
        super.onCreate();
        // ★ v1.18.15：服务一起来就把待发队列的周期重试挂上（幂等）。
        //   这样即使界面没开、也不再有 peers 事件，待发内容仍能被自动补发。
        FlashApp.get().schedulePendingRetry();
        installNotificationChannels();
        showServiceNotification();
        installEventDispatcher();
    }

    private void installNotificationChannels() {
        if (Build.VERSION.SDK_INT < 26) return;
        NotificationManager nm = getSystemService(NotificationManager.class);
        NotificationChannel ch = new NotificationChannel(CH_ID, "闪传后台服务",
                NotificationManager.IMPORTANCE_MIN);
        ch.setDescription("保持局域网传输服务在线");
        // ★ v1.18.30：后台服务通知**不参与桌面角标**。
        //   通知渠道默认 setShowBadge(true)，国产 ROM（MIUI/华为/OPPO 等）
        //   把这条常驻通知计入未读 → 桌面图标常亮红 1，
        //   而用户根本没收到任何消息（bug：未收到消息也显示红 1）。
        ch.setShowBadge(false);
        nm.createNotificationChannel(ch);
        NotificationChannel chH = new NotificationChannel(CH_ID_HIDDEN,
                "闪传后台服务（静默）", NotificationManager.IMPORTANCE_NONE);
        chH.setDescription("保持局域网传输服务在线（不显示通知）");
        chH.setShowBadge(false);
        nm.createNotificationChannel(chH);
        NotificationChannel chM = new NotificationChannel(CH_MSG, "收到消息提醒",
                NotificationManager.IMPORTANCE_HIGH);
        chM.setDescription("息屏或离开应用时收到消息/文件的通知");
        // 只有真实收到的消息/文件才亮角标
        chM.setShowBadge(true);
        nm.createNotificationChannel(chM);
    }

    private void showServiceNotification() {
        boolean show = FlashApp.get().prefs().showServiceNotification();
        Notification.Builder b;
        if (Build.VERSION.SDK_INT >= 26) {
            b = new Notification.Builder(this, show ? CH_ID : CH_ID_HIDDEN);
        } else {
            b = new Notification.Builder(this);
            if (!show) b.setPriority(Notification.PRIORITY_MIN);
        }
        b.setContentTitle("闪传运行中")
                .setContentText("局域网互传服务保持在线")
                .setSmallIcon(R.drawable.ic_notif)
                .setOngoing(true);
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(1001, b.build(),
                    android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
        } else {
            startForeground(1001, b.build());
        }
    }

    /** 常驻事件分发：前台界面在 → 转发给界面；否则按设置发系统通知 */
    private void installEventDispatcher() {
        if (listenerInstalled) return;
        listenerInstalled = true;
        FlashApp.get().node().setListener(e -> {
            FlashNode.Listener ui = FlashApp.get().uiListener;
            if (ui != null) {
                try { ui.onEvent(e); } catch (Exception ignored) {}
                return;
            }
            handleBackgroundEvent(e);
        });
    }

    private void handleBackgroundEvent(org.json.JSONObject e) {
        try {
            String ev = e.optString("event");
            if ("peers".equals(ev)) {
                // ★ v1.18.15：改为确认送达才移除的异步补发（失败会留在队列里重试）
                FlashApp.get().flushPendingSendsAsync(null, null, null);
                FlashApp.get().schedulePendingRetry();
                return;
            }
            // ★ v1.13.1：无论"收到消息提醒"开关是否打开，都必须先把记录落库。
            // 旧代码把落库这件事整个漏掉了：后台收到文件只弹通知、不写历史，
            // 用户点通知进来聊天界面一片空白（文件其实已经存进手机文件夹）。
            FlashApp.get().persistInboundEvent(e);
            Prefs prefs = FlashApp.get().prefs();
            if (!prefs.notifyOnReceive()) return;
            if ("text".equals(ev)) {
                notifyMessage(e.optString("name", "新消息"),
                        e.optString("text", ""),
                        (e.optString("mid", String.valueOf(System.currentTimeMillis()))).hashCode());
            } else if ("transfer".equals(ev) && "recv".equals(e.optString("kind"))
                    && "done".equals(e.optString("state"))) {
                notifyMessage(e.optString("name", "新消息"),
                        "发来文件：" + e.optString("file", ""),
                        ("f" + e.optString("tid", "")).hashCode());
            }
        } catch (Exception ignored) {}
    }

    private void notifyMessage(String title, String body, int id) {
        try {
            NotificationManager nm = getSystemService(NotificationManager.class);
            Intent it = new Intent(this, MainActivity.class);
            it.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
            PendingIntent pi = PendingIntent.getActivity(this, 0, it,
                    PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
            Notification.Builder b = Build.VERSION.SDK_INT >= 26
                    ? new Notification.Builder(this, CH_MSG)
                    : new Notification.Builder(this);
            Notification.Style style = null;
            if (Build.VERSION.SDK_INT >= 26 && body != null && !body.isEmpty()) {
                Notification.BigTextStyle bs = new Notification.BigTextStyle();
                bs.bigText(body);
                b.setStyle(bs);
            }
            b.setContentTitle(title)
                    .setContentText(body)
                    .setSmallIcon(R.drawable.ic_notif)
                    .setContentIntent(pi)
                    .setAutoCancel(true);
            int nid = Math.abs(id == 0 ? (title + body).hashCode() : id);
            nm.notify(nid, b.build());
            // ★ v1.18.30：记下通知 id，回前台时统一 cancel。
            //   只从桌面图标进应用（没点通知）时通知不会自动消失，
            //   角标会一直亮着——读到的消息不该继续显示未读。
            FlashApp.get().addActiveNotifId(nid);
        } catch (Exception ignored) {}
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        return START_STICKY;
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }
}
