package com.flashdrop.app;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Build;

/** 开机自启（设置内开关，默认关闭）：开机后恢复局域网接收服务 */
public class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        try {
            if (!Intent.ACTION_BOOT_COMPLETED.equals(intent.getAction())) return;
            if (!FlashApp.get().prefs().autoStart()) return;
            Intent it = new Intent(context, NodeService.class);
            if (Build.VERSION.SDK_INT >= 26) context.startForegroundService(it);
            else context.startService(it);
        } catch (Exception ignored) {}
    }
}
