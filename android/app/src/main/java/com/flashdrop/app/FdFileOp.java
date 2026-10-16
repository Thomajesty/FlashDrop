package com.flashdrop.app;

import android.app.Activity;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;
import android.text.TextUtils;
import android.widget.Toast;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;

/**
 * v1.15.0：文件操作公共帮助类。
 *
 * 「打开 / 保存 / 分享 / 更多打开方式」这几件事在**聊天页卡片菜单**和
 * **内置预览器三点菜单**里都要用，抽到一处避免两套逻辑分叉
 * （分叉是之前几轮 bug 的常见来源）。
 *
 * ★ v1.16.0 保存位置变更（用户明确要求）：
 *   统一落到 **Download/FlashDrop/保存的文件/**，与按设备分的接收文件夹**同级**：
 *     Download/FlashDrop/
 *         ├── <设备名>/        ← 自动接收的文件
 *         └── 保存的文件/       ← 用户手动「保存」的文件（受保护，清理不碰）
 *   · API 29+ → MediaStore，无需存储权限；
 *   · API <29 → 公共外部存储目录，需 WRITE_EXTERNAL_STORAGE（清单已声明）。
 * 重名时自动追加 -1 / -2 …，不覆盖用户已有文件。
 */
public final class FdFileOp {

    private FdFileOp() {}

    /** 用户可见的保存目录描述（提示文案用） */
    public static final String SAVE_DIR_DESC = FdUtil.userSavePathDesc();

    /** MediaStore 用的相对路径：Download/FlashDrop/保存的文件 */
    private static final String SAVE_REL_PATH =
            Environment.DIRECTORY_DOWNLOADS + "/FlashDrop/" + FdUtil.USER_SAVE_DIR;

    // ---------------- Uri 解析 ----------------

    /**
     * 解析消息对应的可打开 Uri：content:// 优先，其次 FileProvider，
     * 最后按文件名回查公共下载目录（重启后句柄失效的兜底）。
     */
    public static Uri uriOf(Context ctx, MainActivity.Msg m) {
        if (m == null) return null;
        if (!TextUtils.isEmpty(m.open) && m.open.startsWith("content:")) {
            return Uri.parse(m.open);
        }
        if (!TextUtils.isEmpty(m.path)) {
            if (m.path.startsWith("content:")) return Uri.parse(m.path);
            File f = new File(m.path);
            if (f.exists()) return FdFileProvider.uriForAbsolute(m.path);
        }
        if (!TextUtils.isEmpty(m.file)) {
            Uri u = FdUtil.findInDownloads(ctx, m.file);
            if (u != null) return u;
        }
        return null;
    }

    // ---------------- 打开 ----------------

    /**
     * 强制弹**系统应用选择器**（「其他应用打开」）。
     *
     * ★ v1.16.0 重写。
     *
     * 用户反馈"文件预览界面『用其他应用打开』缺少最常用的 WPS 等文本处理软件，
     * 应该交给系统级处理"。根因有两层：
     *
     *   ① 旧实现直接 `createChooser(ACTION_VIEW)`，**没有先探测**。部分国产 ROM
     *      在没有候选 Activity 时 chooser 会显示空列表（用户看到"缺少应用"）。
     *   ② MIME 由 `mimeOf()` **猜出来**的（按扩展名硬编码），猜错（比如 docx
     *      被猜成 application/octet-stream）时 WPS **不会**声明匹配该 MIME，
     *      于是不出现在列表里。
     *
     * 现在的策略 —— 逐级放宽，直到系统有候选为止：
     *   ① 精确 MIME（真实 mime 优先，猜的次之）
     *   ② 通配 {@code &#42;/&#42;}（让所有能"打开文件"的应用都进候选，WPS 必然在内）
     *   ③ 不带 MIME，只给 uri（靠 ContentProvider 的 getType / scheme 推断）
     *
     * 每一级都先 `resolveActivity` 探测，保证 chooser 里一定有内容。
     */
    public static void openWithChooser(Activity a, Uri uri, String name, String mime) {
        if (uri == null) { toast(a, "文件不可用"); return; }
        String real = effectiveMime(a, uri, name, mime);

        // ① 精确 MIME
        if (probeAndChoose(a, uri, real)) return;
        // ② 通配 MIME —— 关键一步：让 WPS / Office / 各类阅读器都能进候选
        if (probeAndChoose(a, uri, "*/*")) return;
        // ③ 不带 MIME
        try {
            Intent it = new Intent(Intent.ACTION_VIEW);
            it.setData(uri);
            it.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                    | Intent.FLAG_ACTIVITY_NEW_TASK);
            a.startActivity(Intent.createChooser(it, "选择打开方式"));
        } catch (Throwable t) {
            toast(a, "没有可打开此文件的应用");
        }
    }

    /** 探测某个 MIME 是否有候选；有则弹 chooser 并返回 true */
    private static boolean probeAndChoose(Activity a, Uri uri, String mime) {
        try {
            Intent it = new Intent(Intent.ACTION_VIEW);
            it.setDataAndType(uri, mime);
            it.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                    | Intent.FLAG_ACTIVITY_NEW_TASK);
            if (it.resolveActivity(a.getPackageManager()) == null) return false;
            Intent chooser = Intent.createChooser(it, "选择打开方式");
            chooser.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                    | Intent.FLAG_ACTIVITY_NEW_TASK);
            a.startActivity(chooser);
            return true;
        } catch (Throwable t) {
            return false;
        }
    }

    /**
     * 取"最可信"的 MIME：
     * 调用方传来的真实 MIME（协议里带过来的）优先；
     * 其次问 ContentResolver（MediaStore 记录的）；
     * 最后才用扩展名硬猜。
     */
    private static String effectiveMime(Activity a, Uri uri, String name, String mime) {
        if (!TextUtils.isEmpty(mime) && mime.contains("/")) return mime;
        try {
            String r = a.getContentResolver().getType(uri);
            if (!TextUtils.isEmpty(r) && r.contains("/")) return r;
        } catch (Throwable ignored) {}
        return mimeOf(mime, name);
    }

    /** 交给系统应用直接打开。返回是否成功发起。 */
    public static boolean tryOpen(Activity a, Uri uri, String name, String mime) {
        if (uri == null) { toast(a, "文件不可用"); return false; }
        // 先按精确 MIME 试；不行再退到 */*（避免"文件关联缺失"直接失败）
        if (tryOpenWith(a, uri, effectiveMime(a, uri, name, mime))) return true;
        return tryOpenWith(a, uri, "*/*");
    }

    private static boolean tryOpenWith(Activity a, Uri uri, String mime) {
        try {
            Intent it = new Intent(Intent.ACTION_VIEW);
            it.setDataAndType(uri, mime);
            it.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                    | Intent.FLAG_ACTIVITY_NEW_TASK);
            if (it.resolveActivity(a.getPackageManager()) == null) return false;
            a.startActivity(it);
            return true;
        } catch (Throwable e) {
            return false;
        }
    }

    // ---------------- 分享 ----------------

    public static void share(Activity a, Uri uri, String name, String mime) {
        if (uri == null) { toast(a, "文件不可用"); return; }
        try {
            Intent it = new Intent(Intent.ACTION_SEND);
            it.setType(mimeOf(mime));
            it.putExtra(Intent.EXTRA_STREAM, uri);
            it.putExtra(Intent.EXTRA_SUBJECT, name == null ? "" : name);
            it.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            a.startActivity(Intent.createChooser(it, "发送到"));
        } catch (Throwable t) {
            toast(a, "分享失败：" + t.getMessage());
        }
    }

    // ---------------- 保存 ----------------

    /** 把 uri 指向的文件另存到公共 Download/FlashDrop/保存的文件/ */
    public static void saveToUserDir(Activity a, Uri src, String name, String mime) {
        if (src == null) { toast(a, "文件不可用"); return; }
        if (TextUtils.isEmpty(name)) name = "文件";
        try {
            if (Build.VERSION.SDK_INT >= 29) {
                String saveName = uniqueDownloadName(a, name);
                ContentValues cv = new ContentValues();
                cv.put(MediaStore.Downloads.DISPLAY_NAME, saveName);
                cv.put(MediaStore.Downloads.MIME_TYPE, mimeOf(mime));
                cv.put(MediaStore.Downloads.RELATIVE_PATH, SAVE_REL_PATH);
                cv.put(MediaStore.Downloads.IS_PENDING, 1);
                Uri dst = a.getContentResolver().insert(
                        MediaStore.Downloads.EXTERNAL_CONTENT_URI, cv);
                if (dst == null) { toast(a, "保存失败"); return; }
                InputStream is = null;
                OutputStream os = null;
                try {
                    is = a.getContentResolver().openInputStream(src);
                    os = a.getContentResolver().openOutputStream(dst);
                    if (is == null || os == null) throw new IOException("流不可用");
                    copy(is, os);
                } finally {
                    close(is);
                    close(os);
                }
                ContentValues done = new ContentValues();
                done.put(MediaStore.Downloads.IS_PENDING, 0);
                a.getContentResolver().update(dst, done, null, null);
                toast(a, "已保存到 " + SAVE_DIR_DESC + "/" + saveName);
            } else {
                File dir = FdUtil.legacyUserSaveDir();
                File out = new File(dir, uniqueNameIn(dir, name));
                InputStream is = null;
                OutputStream os = null;
                try {
                    is = a.getContentResolver().openInputStream(src);
                    os = new FileOutputStream(out);
                    if (is == null) throw new IOException("流不可用");
                    copy(is, os);
                } finally {
                    close(is);
                    close(os);
                }
                toast(a, "已保存到 " + SAVE_DIR_DESC + "/" + out.getName());
            }
        } catch (Throwable e) {
            toast(a, "保存失败：" + e.getMessage());
        }
    }

    // ---------------- 内部工具 ----------------

    public static String mimeOf(String mime) {
        return TextUtils.isEmpty(mime) ? "application/octet-stream" : mime;
    }

    /**
     * 带文件名兜底的 MIME 推断（v1.16.0）。
     *
     * 为什么不直接用 `application/octet-stream`：WPS / Office 等应用在
     * AndroidManifest 里声明的是**精确 MIME**（如
     * `application/vnd.openxmlformats-officedocument.wordprocessingml.document`），
     * 传 octet-stream 时它们不匹配，用户在"其他应用打开"里就看不到 WPS。
     *
     * 这里按扩展名补齐最常见的办公 / 文档 / 压缩包类型；未收录的仍退到
     * octet-stream（此时 openWithChooser 的第二级 `*&#47;*` 会兜住）。
     */
    public static String mimeOf(String mime, String fileName) {
        if (!TextUtils.isEmpty(mime) && mime.contains("/")) return mime;
        String ext = "";
        if (!TextUtils.isEmpty(fileName)) {
            int d = fileName.lastIndexOf('.');
            if (d > 0 && d < fileName.length() - 1) {
                ext = fileName.substring(d + 1).toLowerCase(java.util.Locale.ROOT);
            }
        }
        switch (ext) {
            // ---- Microsoft Office / WPS ----
            case "doc":  return "application/msword";
            case "docx": return "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
            case "xls":  return "application/vnd.ms-excel";
            case "xlsx": return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
            case "ppt":  return "application/vnd.ms-powerpoint";
            case "pptx": return "application/vnd.openxmlformats-officedocument.presentationml.presentation";
            // ---- WPS 自有格式 ----
            case "wps":  return "application/vnd.ms-works";
            case "et":   return "application/vnd.ms-excel";
            case "dps":  return "application/vnd.ms-powerpoint";
            // ---- 纯文本 / 标记 ----
            case "txt":  return "text/plain";
            case "md":   return "text/markdown";
            case "csv":  return "text/csv";
            case "json": return "application/json";
            case "xml":  return "text/xml";
            case "log":  return "text/plain";
            // ---- PDF / 电子书 ----
            case "pdf":  return "application/pdf";
            case "epub": return "application/epub+zip";
            // ---- 压缩包 ----
            case "zip":  return "application/zip";
            case "rar":  return "application/x-rar-compressed";
            case "7z":   return "application/x-7z-compressed";
            case "tar":  return "application/x-tar";
            case "gz":   return "application/gzip";
            // ---- 音频 / 视频 ----
            case "mp3":  return "audio/mpeg";
            case "m4a":  return "audio/mp4";
            case "wav":  return "audio/wav";
            case "flac": return "audio/flac";
            case "mp4":  return "video/mp4";
            case "mkv":  return "video/x-matroska";
            case "avi":  return "video/x-msvideo";
            case "mov":  return "video/quicktime";
            // ---- 图片 ----
            case "jpg": case "jpeg": return "image/jpeg";
            case "png":  return "image/png";
            case "gif":  return "image/gif";
            case "webp": return "image/webp";
            case "bmp":  return "image/bmp";
            case "heic": return "image/heic";
            // ---- 安卓 ----
            case "apk":  return "application/vnd.android.package-archive";
            default:     return "application/octet-stream";
        }
    }

    private static void copy(InputStream is, OutputStream os) throws IOException {
        byte[] buf = new byte[1 << 16];
        int n;
        while ((n = is.read(buf)) > 0) os.write(buf, 0, n);
        os.flush();
    }

    private static void close(java.io.Closeable c) {
        try { if (c != null) c.close(); } catch (Throwable ignored) {}
    }

    private static String uniqueDownloadName(Context ctx, String name) {
        String stem = name, ext = "";
        int d = name.lastIndexOf('.');
        if (d > 0) { stem = name.substring(0, d); ext = name.substring(d); }
        String cand = name;
        for (int i = 1; i < 200 && downloadNameExists(ctx, cand); i++) {
            cand = stem + "-" + i + ext;
        }
        return cand;
    }

    private static boolean downloadNameExists(Context ctx, String name) {
        try {
            android.database.Cursor cur = ctx.getContentResolver().query(
                    MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                    new String[]{MediaStore.MediaColumns._ID},
                    MediaStore.MediaColumns.DISPLAY_NAME + "=? AND "
                            + MediaStore.MediaColumns.RELATIVE_PATH + " LIKE ?",
                    new String[]{name, SAVE_REL_PATH + "%"},
                    null);
            boolean has = cur != null && cur.moveToFirst();
            if (cur != null) cur.close();
            return has;
        } catch (Throwable t) {
            return false;
        }
    }

    private static String uniqueNameIn(File dir, String name) {
        if (!new File(dir, name).exists()) return name;
        String stem = name, ext = "";
        int d = name.lastIndexOf('.');
        if (d > 0) { stem = name.substring(0, d); ext = name.substring(d); }
        for (int i = 1; i < 200; i++) {
            String cand = stem + "-" + i + ext;
            if (!new File(dir, cand).exists()) return cand;
        }
        return name;
    }

    private static void toast(Context c, String s) {
        Toast.makeText(c, s, Toast.LENGTH_SHORT).show();
    }
}
