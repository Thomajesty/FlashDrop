package com.flashdrop.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/**
 * 全局崩溃捕获：任何未捕获异常都（1）落盘到 filesDir/crash.log，
 * （2）在下次打开时用弹窗直接展示给用户，不再"打开就静默退出"。
 * 这样无需 adb/logcat 也能定位崩溃原因。
 */
public final class CrashTrap {
    private static final String FILE = "crash.log";
    /** 公共下载目录中的文件名（用户用文件管理器直接打开） */
    private static final String PUBLIC_NAME = "闪传崩溃日志.txt";
    private static final String PREF_LAST = "last_crash";
    private static volatile boolean installed = false;

    private CrashTrap() {}

    public static void install(Context ctx) {
        if (installed) return;
        installed = true;
        final Context app = ctx.getApplicationContext();
        final Thread.UncaughtExceptionHandler prev =
                Thread.getDefaultUncaughtExceptionHandler();
        Thread.setDefaultUncaughtExceptionHandler((t, e) -> {
            try {
                StringWriter sw = new StringWriter();
                e.printStackTrace(new PrintWriter(sw));
                String body = buildReport(app, t, e, sw.toString());
                // 优先写私有目录（最快，保证一定落盘），公共目录失败不影响
                try {
                    File f = new File(app.getFilesDir(), FILE);
                    java.io.FileOutputStream fos = new java.io.FileOutputStream(f, false);
                    try { fos.write(body.getBytes("UTF-8")); } finally { fos.close(); }
                } catch (Throwable ignored) {}
                // 再写公共下载目录（用户可直接在文件管理器查看）
                writePublic(app, body);
                // 记录异常类型摘要，供下次启动时判断"上次是否闪退"
                try {
                    app.getSharedPreferences("flashdrop_prefs", Context.MODE_PRIVATE)
                            .edit().putString(PREF_LAST,
                                    e.getClass().getName() + " @ "
                                            + firstFrame(e)).apply();
                } catch (Throwable ignored) {}
            } catch (Throwable ignored) {
            }
            // 交给系统默认处理器，保持原有"闪退"行为（但日志已落盘）
            if (prev != null) prev.uncaughtException(t, e);
            else {
                android.os.Process.killProcess(android.os.Process.myPid());
                System.exit(1);
            }
        });
    }

    private static String firstFrame(Throwable e) {
        try {
            StackTraceElement[] st = e.getStackTrace();
            for (StackTraceElement s : st) {
                if (s.getClassName().startsWith("com.flashdrop")) {
                    return s.getClassName().substring(s.getClassName().lastIndexOf('.') + 1)
                            + "." + s.getMethodName() + ":" + s.getLineNumber();
                }
            }
            if (st.length > 0) {
                return st[0].getClassName() + "." + st[0].getMethodName();
            }
        } catch (Throwable ignored) {}
        return "?";
    }

    private static String buildReport(Context ctx, Thread t, Throwable e, String stack) {
        StringBuilder sb = new StringBuilder();
        sb.append("时间: ").append(new SimpleDateFormat("yyyy-MM-dd HH:mm:ss",
                Locale.getDefault()).format(new Date())).append('\n');
        sb.append("线程: ").append(t == null ? "?" : t.getName()).append('\n');
        sb.append("设备: ").append(Build.MANUFACTURER).append(' ')
                .append(Build.MODEL).append('\n');
        sb.append("Android: ").append(Build.VERSION.RELEASE)
                .append(" (API ").append(Build.VERSION.SDK_INT).append(")\n");
        sb.append("版本: ").append(FdUtil.APP_VERSION).append('\n');
        sb.append("---- 崩溃堆栈 ----\n").append(stack);
        return sb.toString();
    }

    /**
     * 崩溃日志写两份：
     *  - 私有目录 filesDir/crash.log（应用内查看用）
     *  - **公共下载目录 Download/FlashDrop/闪传崩溃日志.txt**（关键！App 闪退进不去时，
     *    用户仍可用文件管理器直接打开查看，无需 root/adb）
     */
    private static void write(Context ctx, String body) {
        // 1) 私有目录（兜底）
        try {
            File f = new File(ctx.getFilesDir(), FILE);
            java.io.FileOutputStream fos = new java.io.FileOutputStream(f, false);
            try { fos.write(body.getBytes("UTF-8")); } finally { fos.close(); }
        } catch (Throwable ignored) {}
        // 2) 公共下载目录（用户可直接在文件管理器里找到）
        writePublic(ctx, body);
    }

    /** 写入公共目录：API 29+ 走 MediaStore，24-28 直接写 File（需存储权限） */
    private static void writePublic(Context ctx, String body) {
        byte[] bytes;
        try { bytes = body.getBytes("UTF-8"); } catch (Throwable e) { return; }
        String rel = android.os.Environment.DIRECTORY_DOWNLOADS + "/FlashDrop";
        if (Build.VERSION.SDK_INT >= 29) {
            // 分区存储：必须用 MediaStore，不能直接 File 写公共目录
            try {
                android.content.ContentResolver cr = ctx.getContentResolver();
                android.content.ContentValues cv = new android.content.ContentValues();
                cv.put(android.provider.MediaStore.Downloads.DISPLAY_NAME, PUBLIC_NAME);
                cv.put(android.provider.MediaStore.Downloads.MIME_TYPE, "text/plain");
                cv.put(android.provider.MediaStore.Downloads.RELATIVE_PATH, rel);
                // 同名覆盖：先删旧记录
                try {
                    android.database.Cursor cur = cr.query(
                            android.provider.MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                            new String[]{android.provider.MediaStore.MediaColumns._ID},
                            android.provider.MediaStore.MediaColumns.RELATIVE_PATH + " LIKE ? AND "
                                    + android.provider.MediaStore.MediaColumns.DISPLAY_NAME + "=?",
                            new String[]{rel + "%", PUBLIC_NAME}, null);
                    if (cur != null) {
                        java.util.ArrayList<Long> ids = new java.util.ArrayList<>();
                        while (cur.moveToNext()) ids.add(cur.getLong(0));
                        cur.close();
                        for (long id : ids) {
                            try {
                                cr.delete(android.content.ContentUris.withAppendedId(
                                        android.provider.MediaStore.Downloads.EXTERNAL_CONTENT_URI, id),
                                        null, null);
                            } catch (Throwable ignored) {}
                        }
                    }
                } catch (Throwable ignored) {}
                android.net.Uri uri = cr.insert(
                        android.provider.MediaStore.Downloads.EXTERNAL_CONTENT_URI, cv);
                if (uri != null) {
                    java.io.OutputStream os = cr.openOutputStream(uri);
                    if (os != null) {
                        try { os.write(bytes); } finally { os.close(); }
                    }
                }
            } catch (Throwable ignored) {}
        } else {
            // API 24-28：直接写 File
            try {
                File d = new File(android.os.Environment.getExternalStoragePublicDirectory(
                        android.os.Environment.DIRECTORY_DOWNLOADS), "FlashDrop");
                if (!d.exists()) d.mkdirs();
                java.io.FileOutputStream fos =
                        new java.io.FileOutputStream(new File(d, PUBLIC_NAME), false);
                try { fos.write(bytes); } finally { fos.close(); }
                // 同时留一份带时间戳的历史，避免连续闪退互相覆盖
                String ts = new SimpleDateFormat("yyyyMMdd-HHmmss", Locale.getDefault())
                        .format(new Date());
                java.io.FileOutputStream hf = new java.io.FileOutputStream(
                        new File(d, "闪传崩溃日志-" + ts + ".txt"), false);
                try { hf.write(bytes); } finally { hf.close(); }
            } catch (Throwable ignored) {}
        }
    }

    /** 上次崩溃摘要（供 Application 启动时判断是否需要弹窗） */
    public static String lastCrash(Context ctx) {
        try {
            String s = ctx.getSharedPreferences("flashdrop_prefs", Context.MODE_PRIVATE)
                    .getString(PREF_LAST, "");
            return s == null ? "" : s;
        } catch (Throwable e) {
            return "";
        }
    }

    public static void clearLastCrash(Context ctx) {
        try {
            ctx.getSharedPreferences("flashdrop_prefs", Context.MODE_PRIVATE)
                    .edit().putString(PREF_LAST, "").apply();
        } catch (Throwable ignored) {}
    }

    public static String readLog(Context ctx) {
        try {
            File f = new File(ctx.getFilesDir(), FILE);
            if (!f.exists()) return "";
            java.io.FileInputStream fis = new java.io.FileInputStream(f);
            java.io.ByteArrayOutputStream bos = new java.io.ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = fis.read(buf)) > 0) bos.write(buf, 0, n);
            fis.close();
            return bos.toString("UTF-8");
        } catch (Throwable e) {
            return "";
        }
    }

    /** 在 Activity 里弹出崩溃详情（必须在 UI 线程调用） */
    public static void showDialog(final Activity act) {
        final String body = readLog(act);
        if (body.isEmpty()) {
            toast(act, "没有找到崩溃日志（若仍未闪退，说明本次没崩）");
            return;
        }
        act.runOnUiThread(() -> {
            try {
                int dp = (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, 1,
                        act.getResources().getDisplayMetrics());
                LinearLayout box = new LinearLayout(act);
                box.setOrientation(LinearLayout.VERTICAL);
                box.setPadding(20 * dp, 20 * dp, 20 * dp, 20 * dp);

                TextView title = new TextView(act);
                title.setText("崩溃日志");
                title.setTextColor(Color.parseColor("#E53935"));
                title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 17);
                title.setTypeface(Typeface.DEFAULT_BOLD);
                box.addView(title);

                TextView sub = new TextView(act);
                sub.setText("点「复制并关闭」把堆栈复制到剪贴板，再粘贴发给开发者：");
                sub.setTextColor(Color.parseColor("#E5E7EB"));
                sub.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
                sub.setPadding(0, 8 * dp, 0, 12 * dp);
                box.addView(sub);

                ScrollView sv = new ScrollView(act);
                TextView log = new TextView(act);
                log.setText(body);
                log.setTextColor(Color.parseColor("#B0BEC5"));
                log.setTextSize(TypedValue.COMPLEX_UNIT_SP, 10);
                log.setTextIsSelectable(true);
                sv.addView(log);
                box.addView(sv, new LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));

                new AlertDialog.Builder(act)
                        .setView(box)
                        .setPositiveButton("复制并关闭", (d, w) -> {
                            copy(act, body);   // 复制后弹窗自动关闭
                            clearLastCrash(act);
                        })
                        .setNegativeButton("关闭", (d, w) -> clearLastCrash(act))
                        .show();
            } catch (Throwable ignored) {}
        });
    }

    /** 一键复制崩溃日志到剪贴板（供设置页按钮调用，用户无需 root 访问私有目录） */
    public static boolean copyLog(final Context ctx) {
        final String body = readLog(ctx);
        if (body.isEmpty()) {
            toast(ctx, "没有崩溃日志");
            return false;
        }
        copy(ctx, body);
        return true;
    }

    private static void copy(final Context ctx, final String body) {
        try {
            android.content.ClipboardManager cm =
                    (android.content.ClipboardManager) ctx.getSystemService(Context.CLIPBOARD_SERVICE);
            cm.setPrimaryClip(android.content.ClipData.newPlainText("crash", body));
            toast(ctx, "已复制到剪贴板");
        } catch (Throwable t) {
            toast(ctx, "复制失败");
        }
    }

    private static void toast(final Context ctx, final String s) {
        try {
            new Handler(Looper.getMainLooper()).post(() ->
                    Toast.makeText(ctx, s, Toast.LENGTH_SHORT).show());
        } catch (Throwable ignored) {}
    }
}