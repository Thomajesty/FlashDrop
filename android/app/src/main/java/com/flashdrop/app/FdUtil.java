package com.flashdrop.app;

import android.content.Context;
import android.os.Build;
import android.os.Environment;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

/** 通用工具：设备 ID、名称、文件名安全、唯一路径、MIME、历史记录存储 */
public final class FdUtil {
    private FdUtil() {}

    public static final String APP_VERSION = "1.18.31";
    public static final String APP_AUTHOR = "Thomajesty";
    public static final String APP_CONTACT = "Thomajesty@163.com";

    public static String genId() {
        return UUID.randomUUID().toString().replace("-", "");
    }

    public static String shortUid() {
        return UUID.randomUUID().toString().replace("-", "");
    }

    public static String defaultDeviceName(Context ctx) {
        String model = Build.MODEL == null ? "Android" : Build.MODEL;
        return model + "（安卓）";
    }

    public static String fmtSize(long n) {
        if (n < 1024) return n + " B";
        double v = n;
        String[] u = {"KB", "MB", "GB", "TB"};
        int i = -1;
        while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
        return String.format(java.util.Locale.US, "%.1f %s", v, u[i]);
    }

    public static String fmtSpeed(double bps) {
        if (bps <= 0) return "0 B/s";
        return fmtSize((long) bps) + "/s";
    }

    /** 过滤文件名非法字符，防目录穿越 */
    /** 从 content:// 或 file:// URI 中取出用于展示的文件名（已净化） */
    public static String uriDisplayName(String uriStr) {
        if (uriStr == null || uriStr.isEmpty()) return null;
        try {
            String p = android.net.Uri.parse(uriStr).getPath();
            String raw = null;
            if (p != null && !p.isEmpty()) {
                int i = p.lastIndexOf('/');
                raw = (i >= 0 ? p.substring(i + 1) : p);
            }
            if (raw == null || raw.isEmpty()) {
                String seg = uriStr.substring(uriStr.lastIndexOf('/') + 1);
                int q = seg.indexOf('?');
                raw = (q >= 0 ? seg.substring(0, q) : seg);
            }
            if (raw == null || raw.isEmpty()) return null;
            return safeFileName(raw);
        } catch (Exception e) {
            return null;
        }
    }

    public static String safeFileName(String name) {
        if (name == null) return "file";
        String s = name.replace("\\", "_").replace("/", "_")
                .replaceAll("[\\x00-\\x1f:*?\"<>|]", "").trim();
        while (s.startsWith(".")) s = s.substring(1);
        if (s.isEmpty()) s = "file";
        if (s.length() > 200) s = s.substring(0, 200);
        return s;
    }

    public static String guessMime(String name) {
        String ext = "";
        int d = name == null ? -1 : name.lastIndexOf('.');
        if (d >= 0) ext = name.substring(d + 1).toLowerCase(java.util.Locale.US);
        switch (ext) {
            case "png": return "image/png";
            case "jpg": case "jpeg": return "image/jpeg";
            case "gif": return "image/gif";
            case "bmp": return "image/bmp";
            case "webp": return "image/webp";
            case "mp4": return "video/mp4";
            case "mkv": return "video/x-matroska";
            case "mov": return "video/quicktime";
            case "mp3": return "audio/mpeg";
            case "flac": return "audio/flac";
            case "wav": return "audio/wav";
            case "aac": return "audio/aac";
            case "pdf": return "application/pdf";
            case "txt": return "text/plain";
            case "md": return "text/markdown";
            case "doc": return "application/msword";
            case "xls": return "application/vnd.ms-excel";
            case "ppt": return "application/vnd.ms-powerpoint";
            case "zip": return "application/zip";
            case "rar": return "application/vnd.rar";
            case "7z": return "application/x-7z-compressed";
            case "apk": return "application/vnd.android.package-archive";
            case "json": return "application/json";
            case "csv": return "text/csv";
            case "html": case "htm": return "text/html";
            default: return "application/octet-stream";
        }
    }

    public static boolean isImageMime(String mime) {
        return mime != null && mime.startsWith("image/") && !mime.contains("svg");
    }

    /**
     * ★ v1.16.0：用户「长按 → 保存」的落盘目录名（受保护，不参与任何清理）。
     *
     * 目录结构（用户明确要求）：
     *   Download/FlashDrop/
     *       ├── <设备名>/          ← 自动接收的文件按设备分文件夹
     *       ├── <设备名>/
     *       └── 保存的文件/         ← 用户手动「保存」的文件，与设备文件夹**同级**
     *
     * 「保存的文件」目录必须与设备文件夹同级，且**不能被设置页 / 聊天页的
     * 删除键删掉**，否则用户一键清空时会把手动留存的文件一起清光。
     * 因此所有删除路径（deleteSavedFiles / deleteSavedByRelPath /
     * deleteByIdentities / deleteRecursively）都要显式跳过它。
     */
    public static final String USER_SAVE_DIR = "保存的文件";

    /** 「保存的文件」的完整展示路径：Download/FlashDrop/保存的文件 */
    public static String userSavePathDesc() {
        return "Download/FlashDrop/" + USER_SAVE_DIR;
    }

    /** 该相对路径是否落在受保护的「保存的文件」目录内 */
    public static boolean isProtectedPath(String relPath) {
        if (relPath == null || relPath.isEmpty()) return false;
        String s = relPath.replace('\\', '/');
        if (s.startsWith("Download/")) s = s.substring("Download/".length());
        return s.startsWith("FlashDrop/" + USER_SAVE_DIR);
    }

    /** MediaStore 查询排除受保护目录的 SQL 片段（配合 relPathPattern 使用） */
    private static String notProtectedClause() {
        return " AND " + android.provider.MediaStore.MediaColumns.RELATIVE_PATH
                + " NOT LIKE ?";
    }

    /** 与 notProtectedClause 配套的参数：Download/FlashDrop/保存的文件% */
    private static String notProtectedArg() {
        return Environment.DIRECTORY_DOWNLOADS + "/FlashDrop/" + USER_SAVE_DIR + "%";
    }

    /** 公共下载目录 FlashDrop（API < 29 需要存储权限） */
    public static File legacySaveDir() {
        // ★ v1.18.18：测试注入点（同 cacheDir）——
        //   JVM 单测里 Environment.getExternalStoragePublicDirectory 返回
        //   /sdcard 之类不可写路径，mkdirs 静默失败 → saveToDownloads 全挂。
        //   生产环境此属性恒为空，走原路径。
        String ov = System.getProperty("fd.save.dir", "");
        File base = (ov != null && !ov.isEmpty())
                ? new File(ov)
                : Environment.getExternalStoragePublicDirectory(
                        Environment.DIRECTORY_DOWNLOADS);
        File d = new File(base, "FlashDrop");
        if (!d.exists()) d.mkdirs();
        return d;
    }

    /** 「保存的文件」目录（API < 29 用；API 29+ 走 MediaStore） */
    public static File legacyUserSaveDir() {
        File d = new File(legacySaveDir(), USER_SAVE_DIR);
        if (!d.exists()) d.mkdirs();
        return d;
    }

    public static String publicSavePathDesc() {
        return "Download/FlashDrop";
    }

    /** 传输缓存目录 */
    public static File cacheDir(Context ctx) {
        // ★ v1.18.18：测试注入点（与 Windows 端 FLASHDROP_DATA_DIR 同构）。
        //   传输状态机的单元测试跑在 JVM 上（没有 Android Context），
        //   通过 -Dfd.cache.dir=... 重定向 .part/.bmp/.fp 的落盘位置，
        //   生产环境此属性恒为空，走原路径。
        String ov = System.getProperty("fd.cache.dir", "");
        File base;
        if (ov != null && !ov.isEmpty()) {
            base = new File(ov);
        } else {
            File cd = ctx.getCacheDir();
            if (cd == null) return new File("flashdrop-cache");
            base = cd;
        }
        File d = new File(base, "flashdrop");
        if (!d.exists()) d.mkdirs();
        return d;
    }

    /** 兜底读取已接收文件（Download/FlashDrop 按文件名查询 MediaStore），
     *  用于 content Uri 授权失效后仍能加载预览图；API<29 返回 null */
    public static java.io.InputStream openSavedStream(Context ctx, String name) {
        if (Build.VERSION.SDK_INT < 29) return null;
        if (name == null || name.isEmpty()) return null;
        try {
            android.content.ContentResolver cr = ctx.getContentResolver();
            android.database.Cursor cur = cr.query(
                    android.provider.MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                    new String[]{android.provider.MediaStore.MediaColumns._ID},
                    android.provider.MediaStore.MediaColumns.RELATIVE_PATH + " LIKE ? AND "
                            + android.provider.MediaStore.MediaColumns.DISPLAY_NAME + "=?",
                    // 前缀匹配 Download/FlashDrop% 覆盖按设备分的子目录
                    new String[]{Environment.DIRECTORY_DOWNLOADS + "/FlashDrop%", name},
                    null);
            if (cur != null) {
                while (cur.moveToNext()) {
                    long id = cur.getLong(0);
                    android.net.Uri uri = android.content.ContentUris.withAppendedId(
                            android.provider.MediaStore.Downloads.EXTERNAL_CONTENT_URI, id);
                    try {
                        java.io.InputStream is = cr.openInputStream(uri);
                        if (is != null) return is;
                    } catch (Exception ignored) {}
                }
                cur.close();
            }
        } catch (Exception ignored) {}
        return null;
    }

    /**
     * ★ v1.15.0：兜底查找已接收文件在公共 Download/FlashDrop 下的 MediaStore Uri。
     *
     * 场景：消息里保存的 content:// 句柄在重启或权限回收后可能失效，
     * 但文件其实已经落在 Download/FlashDrop/<设备>/ 里了。打开 / 分享 /
     * 另存都需要一个可用的 Uri，这里按文件名回查一次。
     */
    public static android.net.Uri findInDownloads(Context ctx, String name) {
        if (Build.VERSION.SDK_INT < 29) return null;
        if (name == null || name.isEmpty()) return null;
        try {
            android.content.ContentResolver cr = ctx.getContentResolver();
            android.database.Cursor cur = cr.query(
                    android.provider.MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                    new String[]{android.provider.MediaStore.MediaColumns._ID},
                    android.provider.MediaStore.MediaColumns.RELATIVE_PATH + " LIKE ? AND "
                            + android.provider.MediaStore.MediaColumns.DISPLAY_NAME + "=?",
                    new String[]{Environment.DIRECTORY_DOWNLOADS + "/FlashDrop%", name},
                    null);
            if (cur != null) {
                if (cur.moveToFirst()) {
                    long id = cur.getLong(0);
                    cur.close();
                    return android.content.ContentUris.withAppendedId(
                            android.provider.MediaStore.Downloads.EXTERNAL_CONTENT_URI, id);
                }
                cur.close();
            }
        } catch (Throwable ignored) {}
        return null;
    }

    // ---------------- 历史记录（filesDir/history/<id>.jsonl） ----------------
    public static File historyFile(Context ctx, String peerId) {
        File dir = new File(ctx.getFilesDir(), "history");
        if (!dir.exists()) dir.mkdirs();
        String safe = peerId.replaceAll("[^A-Za-z0-9_-]", "");
        if (safe.length() > 64) safe = safe.substring(0, 64);
        return new File(dir, safe + ".jsonl");
    }

    public static List<JSONObject> loadHistory(Context ctx, String peerId, int limit) {
        List<JSONObject> out = new ArrayList<>();
        try {
            FileInputStream fis = new FileInputStream(historyFile(ctx, peerId));
            ByteArrayOutputStream bos = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = fis.read(buf)) > 0) bos.write(buf, 0, n);
            fis.close();
            String[] lines = bos.toString("UTF-8").split("\n");
            int start = Math.max(0, lines.length - limit);
            for (int i = start; i < lines.length; i++) {
                String line = lines[i].trim();
                if (line.isEmpty()) continue;
                try { out.add(new JSONObject(line)); } catch (Exception ignored) {}
            }
        } catch (Exception ignored) {}
        return out;
    }

    public static void appendHistory(Context ctx, String peerId, JSONObject msg) {
        try {
            FileOutputStream fos = new FileOutputStream(historyFile(ctx, peerId), true);
            fos.write((msg.toString() + "\n").getBytes(StandardCharsets.UTF_8));
            fos.close();
        } catch (Exception ignored) {}
    }

    public static void clearHistory(Context ctx, String peerId) {
        historyFile(ctx, peerId).delete();
    }

    /** 设备身份合并：旧 peer 的聊天记录去重后并入新 peer，删除旧文件（跨版本迁移） */
    public static void mergeHistory(Context ctx, String oldId, String newId) {
        if (oldId == null || newId == null || oldId.equals(newId)) return;
        if (oldId.replaceAll("[^A-Za-z0-9_-]", "")
                .equals(newId.replaceAll("[^A-Za-z0-9_-]", ""))) return;
        List<JSONObject> oldMsgs = loadHistory(ctx, oldId, Integer.MAX_VALUE);
        if (!oldMsgs.isEmpty()) {
            java.util.Set<String> existing = new java.util.HashSet<>();
            for (JSONObject o : loadHistory(ctx, newId, Integer.MAX_VALUE)) {
                existing.add(identityOf(o));
            }
            try {
                FileOutputStream fos = new FileOutputStream(historyFile(ctx, newId), true);
                for (JSONObject o : oldMsgs) {
                    if (existing.contains(identityOf(o))) continue;
                    fos.write((o.toString() + "\n").getBytes(StandardCharsets.UTF_8));
                }
                fos.close();
            } catch (Exception ignored) {}
        }
        historyFile(ctx, oldId).delete();
    }

    /** 清空全部聊天记录 */
    public static void clearAllHistory(Context ctx) {
        File dir = new File(ctx.getFilesDir(), "history");
        File[] files = dir.listFiles();
        if (files != null) for (File f : files) f.delete();
    }

    /** 消息唯一标识：ts|mid或tid|dir|kind */
    public static String identityOf(JSONObject o) {
        String id = o.optString("mid", "");
        if (id.isEmpty()) id = o.optString("tid", "");
        return o.optLong("ts", 0) + "|" + id + "|"
                + o.optString("dir", "") + "|" + o.optString("kind", "");
    }

    /**
     * ★ v1.13.1：按 (mid) 或 (tid + dir + kind) 就地更新历史中已有的一条记录。
     *
     * 场景：发送状态从 sending → ok，或接收进度 done，需要把状态持久化，
     * 否则重启后状态退回 sending、界面永远显示"发送中…"。
     * 与 appendHistory 的区别：这是覆盖式更新，不会产生重复行。
     *
     * @return 是否命中原记录（未命中时不写入，交由调用方决定是否 append）
     */
    public static boolean upsertHistory(Context ctx, String peerId, String keyMid,
                                        String keyTid, JSONObject rec) {
        if (peerId == null || peerId.isEmpty()) return false;
        File f = historyFile(ctx, peerId);
        if (!f.exists()) return false;
        try {
            java.io.BufferedReader br = new java.io.BufferedReader(
                    new java.io.InputStreamReader(new FileInputStream(f), "UTF-8"));
            StringBuilder out = new StringBuilder();
            String line;
            boolean hit = false;
            while ((line = br.readLine()) != null) {
                if (line.trim().isEmpty()) continue;
                boolean matched = false;
                try {
                    JSONObject o = new JSONObject(line);
                    if (keyMid != null && !keyMid.isEmpty()) {
                        matched = keyMid.equals(o.optString("mid", ""));
                    } else if (keyTid != null && !keyTid.isEmpty()) {
                        matched = keyTid.equals(o.optString("tid", ""))
                                && rec.optString("dir", "").equals(o.optString("dir", ""))
                                && rec.optString("kind", "").equals(o.optString("kind", ""));
                    }
                } catch (Exception ignored) {}
                if (matched && !hit) {
                    out.append(rec.toString()).append('\n');   // 覆盖最新状态
                    hit = true;
                } else {
                    out.append(line).append('\n');
                }
            }
            br.close();
            if (!hit) return false;
            FileOutputStream fos = new FileOutputStream(f, false);
            fos.write(out.toString().getBytes(StandardCharsets.UTF_8));
            fos.close();
            return true;
        } catch (Exception ignored) {
            return false;
        }
    }

    /** 从历史文件中删除指定标识的消息（重写文件） */
    public static void deleteByIdentities(Context ctx, java.util.Set<String> keys) {
        if (keys == null || keys.isEmpty()) return;
        File dir = new File(ctx.getFilesDir(), "history");
        File[] files = dir.listFiles();
        if (files == null) return;
        for (File f : files) {
            try {
                java.io.BufferedReader br = new java.io.BufferedReader(
                        new java.io.InputStreamReader(new FileInputStream(f), "UTF-8"));
                StringBuilder keep = new StringBuilder();
                String line;
                while ((line = br.readLine()) != null) {
                    if (line.trim().isEmpty()) continue;
                    try {
                        JSONObject o = new JSONObject(line);
                        if (keys.contains(identityOf(o))) continue;
                    } catch (Exception ignored) {}
                    keep.append(line).append('\n');
                }
                br.close();
                FileOutputStream fos = new FileOutputStream(f, false);
                fos.write(keep.toString().getBytes(StandardCharsets.UTF_8));
                fos.close();
            } catch (Exception ignored) {}
        }
    }

    public static long nowMs() {
        return System.currentTimeMillis();
    }

    /** 秒数 -> "1.5 秒" / "3 秒"（日志文案用；v1.18.18 退避提示） */
    public static String secondsText(double sec) {
        if (sec <= 0) return "0 秒";
        if (Math.abs(sec - Math.rint(sec)) < 0.05) return String.format("%d 秒", (long) Math.rint(sec));
        return String.format("%.1f 秒", sec);
    }

    private static final java.util.regex.Pattern URL_RE = java.util.regex.Pattern.compile(
            "(https?://[^\\s，。；！？、（）【】《》\"'<>]+|www\\.[^\\s，。；！？、（）【】《》\"'<>]+)",
            java.util.regex.Pattern.CASE_INSENSITIVE);

    /** 提取文本中的第一个链接（www.* 自动补 http://），无链接返回 null */
    public static String firstUrl(String text) {
        if (text == null) return null;
        try {
            java.util.regex.Matcher m = URL_RE.matcher(text);
            if (!m.find()) return null;
            String u = trimTrailingPunctuation(m.group(1));
            if (u.isEmpty()) return null;
            return u.toLowerCase(java.util.Locale.US).startsWith("http")
                    ? u : "http://" + u;
        } catch (Throwable e) {
            // 链接识别是展示层增强，绝不能因它导致消息列表渲染失败
            return null;
        }
    }

    /**
     * 剥掉链接末尾的标点（句末语气符号/括号/句点），并保留 URL 必需的尾字符。
     * 用纯字符判断而非正则：正则一旦写错（如字符类后跟锚点符号）会在 Android 的
     * ICU 引擎上抛 PatternSyntaxException，直接导致渲染列表时崩溃且每次启动复现。
     */
    private static String trimTrailingPunctuation(String url) {
        if (url == null) return "";
        String s = url;
        while (s.length() > 0) {
            char c = s.charAt(s.length() - 1);
            // URL 中有意义的尾部字符：$ 与 # （$ 允许出现在路径/查询中）
            if (c == '$' || c == '#') break;
            if (c == '.' || c == ',' || c == ';' || c == ':' || c == '!'
                    || c == '?' || c == ')' || c == ']' || c == '}'
                    || c == '）' || c == '】' || c == '》' || c == '"'
                    || c == '\'' || c == '，' || c == '。' || c == '；'
                    || c == '：' || c == '！' || c == '？' || c == ' ') {
                s = s.substring(0, s.length() - 1);
            } else {
                break;
            }
        }
        return s;
    }

    public static String shortUrl(String url, int maxlen) {
        if (url == null) return "";
        return url.length() <= maxlen ? url : url.substring(0, maxlen - 1) + "…";
    }

    // ==================== 按设备分文件夹 ====================

    /**
    /**
     * 设备名 → 安全的文件夹名。
     * Windows 非法字符集比 Android 宽，这里取两者并集统一替换成 '_'，
     * 与 Windows 端 util.safe_folder 规则严格一致 ——
     * 同一台设备在手机和电脑上必须落到同名文件夹，否则跨端查找会很混乱。
     */
    public static String folderNameOf(String peerName) {
        String s = peerName == null ? "" : peerName.trim();
        if (s.isEmpty()) return "未知设备";
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            boolean bad = c < 0x20 || "\\/:*?\"<>|".indexOf(c) >= 0;
            sb.append(bad ? '_' : c);
        }
        s = sb.toString().trim();
        // 去掉尾部的空格与点（Windows 不允许目录名以点结尾）
        int end = s.length();
        while (end > 0 && (s.charAt(end - 1) == ' ' || s.charAt(end - 1) == '.')) end--;
        s = s.substring(0, end);
        while (s.startsWith(".")) s = s.substring(1);
        if (s.isEmpty()) s = "未知设备";
        if (s.length() > 40) s = s.substring(0, 40);
        return s;
    }

    /** 接收文件根目录（下载目录下按设备分文件夹） */
    public static String saveRootDesc() {
        return "Download/FlashDrop";
    }

    /** 单台设备的接收目录相对路径：Download/FlashDrop/<设备名> */
    public static String peerSavePathDesc(String peerName) {
        return saveRootDesc() + "/" + folderNameOf(peerName);
    }

    /**
     * 按"展示用相对路径"删除已接收文件（如 Download/FlashDrop/手机/1.jpg）。
     * API 29+ 走 MediaStore（Downloads 表按 RELATIVE_PATH + DISPLAY_NAME 匹配），
     * 低版本在 Download 目录下按相对路径拼 File 删除。
     * 返回是否删掉。
     */
    public static boolean deleteSavedByRelPath(Context ctx, String relDesc) {
        if (relDesc == null || relDesc.isEmpty()) return false;
        String rel = relDesc.trim();
        if (rel.startsWith("Download/")) rel = rel.substring("Download/".length());
        if (rel.isEmpty()) return false;
        // ★ v1.16.0：受保护的「保存的文件」目录内的文件不允许被删除
        if (isProtectedPath(rel)) return false;
        boolean deleted = false;
        if (Build.VERSION.SDK_INT >= 29) {
            try {
                android.content.ContentResolver cr = ctx.getContentResolver();
                android.database.Cursor cur = cr.query(
                        android.provider.MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                        new String[]{android.provider.MediaStore.MediaColumns._ID},
                        android.provider.MediaStore.MediaColumns.RELATIVE_PATH + "=? AND "
                                + android.provider.MediaStore.MediaColumns.DISPLAY_NAME + "=?",
                        new String[]{rel, baseNameOf(rel)}, null);
                if (cur != null) {
                    while (cur.moveToNext()) {
                        long id = cur.getLong(0);
                        android.net.Uri uri = android.content.ContentUris.withAppendedId(
                                android.provider.MediaStore.Downloads.EXTERNAL_CONTENT_URI, id);
                        try {
                            if (cr.delete(uri, null, null) > 0) deleted = true;
                        } catch (Exception ignored) {}
                    }
                    cur.close();
                }
            } catch (Exception ignored) {}
            return deleted;
        }
        // API 24-28：直接 File
        try {
            File f = new File(Environment.getExternalStoragePublicDirectory(
                    Environment.DIRECTORY_DOWNLOADS), rel);
            if (f.exists()) return f.delete();
        } catch (Exception ignored) {}
        return false;
    }

    private static String baseNameOf(String relPath) {
        int i = relPath.lastIndexOf('/');
        return i >= 0 ? relPath.substring(i + 1) : relPath;
    }

    // ==================== 按分类 / 按设备删除已接收文件 ====================

    /** 转义 LIKE 通配符，避免设备名里的 _ % 误匹配到别的设备目录 */
    private static String likeEscaped(String s) {
        if (s == null) return "";
        return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_");
    }

    /** RELATIVE_PATH 的 LIKE 模式：folder 为空 = 全部设备 */
    private static String relPathPattern(String folder) {
        String base = Environment.DIRECTORY_DOWNLOADS + "/FlashDrop";
        if (folder == null || folder.isEmpty()) return base + "%";
        return base + "/" + likeEscaped(folder) + "%";
    }

    /**
     * 统计已接收文件数量（v1.10.0：删除弹窗需要先显示各类实际条数）。
     * @param folder 设备文件夹名；null / "" = 全部设备
     * @return [文件总数, 其中图片数]
     */
    public static int[] countSavedFiles(Context ctx, String folder) {
        int total = 0, imgs = 0;
        // ★ v1.16.0：统计口径与删除口径严格一致 —— 都排除「保存的文件」
        // 受保护目录，否则弹窗显示的条数会大于实际可删数量，用户会以为删漏了。
        if (folder != null && USER_SAVE_DIR.equals(folder)) return new int[]{0, 0};
        if (Build.VERSION.SDK_INT >= 29) {
            try {
                android.content.ContentResolver cr = ctx.getContentResolver();
                android.database.Cursor cur = cr.query(
                        android.provider.MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                        new String[]{android.provider.MediaStore.MediaColumns.MIME_TYPE},
                        android.provider.MediaStore.MediaColumns.RELATIVE_PATH + " LIKE ?"
                                + notProtectedClause(),
                        new String[]{relPathPattern(folder), notProtectedArg()}, null);
                if (cur == null) return new int[]{0, 0};
                while (cur.moveToNext()) {
                    total++;
                    if (isImageMime(cur.getString(0))) imgs++;
                }
                cur.close();
            } catch (Exception ignored) {}
            return new int[]{total, imgs};
        }
        return countRecursively(folderRoot(folder));
    }

    private static int[] countRecursively(File dir) {
        int total = 0, imgs = 0;
        File[] fs = dir == null ? null : dir.listFiles();
        if (fs == null) return new int[]{0, 0};
        for (File f : fs) {
            if (f.isDirectory()) {
                int[] r = countRecursively(f);
                total += r[0];
                imgs += r[1];
            } else {
                total++;
                if (isImageMime(guessMime(f.getName()))) imgs++;
            }
        }
        return new int[]{total, imgs};
    }

    /** 指定设备目录；folder 为空时返回 FlashDrop 根目录 */
    private static File folderRoot(String folder) {
        File root = legacySaveDir();
        return (folder == null || folder.isEmpty()) ? root : new File(root, folder);
    }

    /**
     * 删除 Download/FlashDrop 下已接收的文件（v1.10.0 统一入口，替代旧的两处实现）。
     * @param folder 设备文件夹名；null / "" = 全部设备（设置页的全局清理）
     * @param imagesOnly TRUE=只删图片；FALSE=只删非图片文件；null=两类都删
     * @param needConfirm 收集需系统二次确认的 Uri（可为 null）
     * @return [直接删除数, 需系统确认数]；首项 -1 表示查询失败
     */
    public static int[] deleteSavedFiles(Context ctx, String folder, Boolean imagesOnly,
                                         List<android.net.Uri> needConfirm) {
        int n = 0;
        // ★ v1.16.0：受保护目录本身不允许被删（防止用户误把"保存的文件"当设备名传进来）
        if (folder != null && USER_SAVE_DIR.equals(folder)) return new int[]{0, 0};
        if (Build.VERSION.SDK_INT >= 29) {
            try {
                android.content.ContentResolver cr = ctx.getContentResolver();
                android.database.Cursor cur = cr.query(
                        android.provider.MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                        new String[]{android.provider.MediaStore.MediaColumns._ID,
                                android.provider.MediaStore.MediaColumns.MIME_TYPE},
                        android.provider.MediaStore.MediaColumns.RELATIVE_PATH + " LIKE ?"
                                + notProtectedClause(),
                        new String[]{relPathPattern(folder), notProtectedArg()}, null);
                if (cur == null) return new int[]{-1, 0};
                while (cur.moveToNext()) {
                    long id = cur.getLong(0);
                    String mime = cur.getString(1);
                    // 与 isImageMime 同口径（svg 归"文件"不归"图片"），
                    // 否则删除数量与弹窗里显示的分类条数对不上
                    if (imagesOnly != null && isImageMime(mime) != imagesOnly) continue;
                    android.net.Uri uri = android.content.ContentUris.withAppendedId(
                            android.provider.MediaStore.Downloads.EXTERNAL_CONTENT_URI, id);
                    try {
                        if (cr.delete(uri, null, null) > 0) n++;
                    } catch (Exception e) {
                        if (needConfirm != null) needConfirm.add(uri);
                    }
                }
                cur.close();
                return new int[]{n, needConfirm == null ? 0 : needConfirm.size()};
            } catch (Exception e) {
                return new int[]{-1, 0};
            }
        }
        try {
            n = deleteRecursively(folderRoot(folder), imagesOnly);
            if (folder != null && !folder.isEmpty()) removeIfEmpty(folderRoot(folder));
            return new int[]{n, 0};
        } catch (Exception e) {
            return new int[]{-1, 0};
        }
    }

    /** 删空目录，避免设备多了留一堆空壳文件夹 */
    private static void removeIfEmpty(File dir) {
        try {
            File[] left = dir.listFiles();
            if (left != null && left.length == 0) dir.delete();
        } catch (Exception ignored) {}
    }

    /** 统计本机全部聊天记录条数（设置页全局清理用）。
     *  @param chatsOnly true 只算文本消息（"聊天记录"），false 含文件/图片消息 */
    public static int countHistory(Context ctx, boolean chatsOnly) {
        int n = 0;
        File dir = new File(ctx.getFilesDir(), "history");
        File[] files = dir == null ? null : dir.listFiles();
        if (files == null) return 0;
        for (File f : files) {
            if (!f.isFile()) continue;
            try {
                java.io.BufferedReader br = new java.io.BufferedReader(
                        new java.io.InputStreamReader(new FileInputStream(f), "UTF-8"));
                String line;
                while ((line = br.readLine()) != null) {
                    if (line.trim().isEmpty()) continue;
                    if (chatsOnly && "file".equals(optStringQuiet(line, "kind"))) continue;
                    n++;
                }
                br.close();
            } catch (Exception ignored) {}
        }
        return n;
    }

    // ==================== ★ v1.18.27：失效文件卡片（文件已被删，记录还在） ====================
    //
    // 成因：用户在文件管理器 / 设置里删掉了已接收的文件，但聊天记录还留着 →
    // 卡片仍显示「已保存」，点进去却打不开（用户实测"文件状态未同步显示"）。
    // 这类记录既没用又占地方，数据清理必须能把它清掉。

    /** 已接收文件索引（键 = "相对目录/文件名" 小写）；null = 尚未建立 */
    private static volatile java.util.Set<String> savedIndex = null;

    /** 上一次查询失败的时间戳（避免每次渲染都重试查询） */
    private static volatile long savedIndexFailedAt = 0L;

    /** 让索引失效（回到前台 / 刚收完文件 / 清理之后都要调，否则会拿到旧快照） */
    public static void invalidateSavedIndex() {
        savedIndex = null;
        savedIndexFailedAt = 0L;
    }

    /**
     * **阻塞式**建立已接收文件索引 —— 只能在**后台线程**调用。
     * UI 线程只准读缓存（savedFileExists），绝不能在 bindView 里查 MediaStore。
     */
    public static void buildSavedIndex(Context ctx) {
        savedIndex(ctx);
    }

    /**
     * 把消息里存的 path 描述拆成 [相对目录(带尾斜杠), 文件名]。
     *
     * 兼容三种历史写法：
     *   API≥29：  "Download/FlashDrop/设备名/a.jpg"（**展示用相对描述，不是真实路径**）
     *   API<29：  "/sdcard/Download/FlashDrop/设备名/a.jpg"（绝对路径）
     *   早期数据： "FlashDrop/设备名/a.jpg"（不带 Download 前缀）
     * 统一归一化为不含 "Download/" 前缀的相对目录，便于与索引比对。
     */
    private static String[] splitSavedDesc(String desc) {
        if (desc == null) return null;
        String s = desc.trim().replace('\\', '/');
        if (s.isEmpty()) return null;
        int i = s.indexOf("/Download/");
        if (i >= 0) s = s.substring(i + 1);                 // 绝对路径 → Download/...
        if (s.startsWith("Download/")) s = s.substring("Download/".length());
        if (s.startsWith("/")) s = s.substring(1);
        int p = s.lastIndexOf('/');
        if (p < 0) return null;                             // 没有目录信息，无法判定
        return new String[]{s.substring(0, p + 1), s.substring(p + 1)};
    }

    /** 递归收集目录下的文件（API<29 走真实目录时用） */
    private static void collectFiles(File dir, String prefix,
                                     java.util.Set<String> out) {
        File[] fs = dir == null ? null : dir.listFiles();
        if (fs == null) return;
        for (File f : fs) {
            if (f.isDirectory()) {
                collectFiles(f, prefix + f.getName() + "/", out);
            } else if (f.isFile()) {
                out.add((prefix + f.getName()).toLowerCase(java.util.Locale.ROOT));
            }
        }
    }

    /**
     * 建立（并缓存）已接收文件索引：键 = "FlashDrop/设备名/文件名" 小写。
     * @return 索引；**null 表示查不到**（游标为 null / 权限异常），此时不能判定失效。
     */
    private static java.util.Set<String> savedIndex(Context ctx) {
        java.util.Set<String> idx = savedIndex;
        if (idx != null) return idx;
        // 上次查询刚失败过 → 短时间内不重试（否则每次 bindView 都查库，滚动会卡）
        if (savedIndexFailedAt != 0L
                && System.currentTimeMillis() - savedIndexFailedAt < 5000L) {
            return null;
        }
        idx = new java.util.HashSet<>();
        if (Build.VERSION.SDK_INT >= 29) {
            android.database.Cursor cur = null;
            try {
                cur = ctx.getContentResolver().query(
                        android.provider.MediaStore.Downloads.EXTERNAL_CONTENT_URI,
                        new String[]{
                                android.provider.MediaStore.MediaColumns.RELATIVE_PATH,
                                android.provider.MediaStore.MediaColumns.DISPLAY_NAME},
                        android.provider.MediaStore.MediaColumns.RELATIVE_PATH
                                + " LIKE ?",
                        new String[]{Environment.DIRECTORY_DOWNLOADS
                                + "/FlashDrop%"},
                        null);
            } catch (Throwable ignored) {}
            if (cur == null) {
                // 查不到（没权限 / 异常）→ 无法判定，调用方必须保守处理
                savedIndexFailedAt = System.currentTimeMillis();
                return null;
            }
            try {
                while (cur.moveToNext()) {
                    String rp = cur.getString(0);
                    String dn = cur.getString(1);
                    if (rp == null || dn == null) continue;
                    if (rp.startsWith("Download/")) rp = rp.substring("Download/".length());
                    if (!rp.endsWith("/")) rp = rp + "/";
                    idx.add((rp + dn).toLowerCase(java.util.Locale.ROOT));
                }
            } catch (Throwable ignored) {}
            try { cur.close(); } catch (Throwable ignored) {}
        } else {
            collectFiles(legacySaveDir(), "FlashDrop/", idx);
        }
        savedIndex = idx;
        return idx;
    }

    /**
     * 已接收的文件是否还在。
     *
     * ★ v1.18.28 修正：v1.18.27 用 File.exists() 判定，方向**完全错了** ——
     *   ① API≥29 存的 path 只是 "Download/FlashDrop/设备名/xx.jpg" 这种
     *      **展示用相对描述**，拼出来的 File 根本不存在；
     *   ② 即便拼对，Android 11+ 分区存储下没有存储权限时 File.exists() 也常
     *      返回 false。结果是"还在文件夹的文件也被显示成已删除"。
     *   这里改为 **以 MediaStore 索引为准**（与 deleteSavedByRelPath 同口径），
     *   并且：查不到索引（游标 null）/ content Uri / 无路径 → **一律保守当作还在**。
     */
    public static boolean savedFileExists(Context ctx, String desc) {
        if (desc == null || desc.isEmpty()) return true;       // 没路径 → 保守
        if (desc.startsWith("content:")) return true;          // Uri 无法 stat
        String[] dn = splitSavedDesc(desc);
        if (dn == null) return true;                           // 解析不出 → 保守
        // ★ 只读缓存：绝不在 UI 线程查 MediaStore（建索引走后台 buildSavedIndex）
        java.util.Set<String> idx = savedIndex;
        if (idx == null) return true;                          // 还没建好 → 保守
        return idx.contains((dn[0] + dn[1]).toLowerCase(java.util.Locale.ROOT));
    }

    /** 一条记录是否是"失效文件卡片"：收到的文件已完成，且**能确定**本地文件已不在 */
    private static boolean isOrphanFileMsg(Context ctx, JSONObject o) {
        if (o == null) return false;
        if (!"file".equals(o.optString("kind", ""))) return false;
        if (!"in".equals(o.optString("dir", ""))) return false;
        String st = o.optString("state", "");
        if (!"done".equals(st) && !"ok".equals(st)) return false;
        return !savedFileExists(ctx, o.optString("path", ""));
    }

    /** 统计失效文件卡片条数（设置页「数据清理」展示用） */
    public static int countOrphanFileMsgs(Context ctx) {
        int n = 0;
        savedIndex(ctx);      // 先确保索引已建立（调用方线程内同步建一次）
        File dir = new File(ctx.getFilesDir(), "history");
        File[] files = dir == null ? null : dir.listFiles();
        if (files == null) return 0;
        for (File f : files) {
            if (!f.isFile()) continue;
            try {
                BufferedReader br = new BufferedReader(
                        new InputStreamReader(new FileInputStream(f), "UTF-8"));
                String line;
                while ((line = br.readLine()) != null) {
                    if (line.trim().isEmpty()) continue;
                    try {
                        if (isOrphanFileMsg(ctx, new JSONObject(line))) n++;
                    } catch (Exception ignored) {}
                }
                br.close();
            } catch (Exception ignored) {}
        }
        return n;
    }

    /**
     * 删除失效文件卡片：重写 history/*.jsonl，跳过「文件已不在」的接收记录。
     * 先写 .tmp 再 rename，避免写一半崩掉丢记录。
     * @return 实际删除条数
     */
    public static int purgeOrphanFileMsgs(Context ctx) {
        int n = 0;
        savedIndex(ctx);      // 先确保索引已建立（必须在后台线程调用）
        File dir = new File(ctx.getFilesDir(), "history");
        File[] files = dir == null ? null : dir.listFiles();
        if (files == null) return 0;
        for (File f : files) {
            if (!f.isFile()) continue;
            try {
                List<String> keep = new ArrayList<>();
                int drop = 0;
                BufferedReader br = new BufferedReader(
                        new InputStreamReader(new FileInputStream(f), "UTF-8"));
                String line;
                while ((line = br.readLine()) != null) {
                    String t = line.trim();
                    if (t.isEmpty()) continue;
                    boolean orphan = false;
                    try {
                        orphan = isOrphanFileMsg(ctx, new JSONObject(t));
                    } catch (Exception ignored) {}
                    if (orphan) { drop++; continue; }
                    keep.add(t);
                }
                br.close();
                if (drop == 0) continue;
                File tmp = new File(f.getParentFile(), f.getName() + ".tmp");
                BufferedWriter bw = new BufferedWriter(new OutputStreamWriter(
                        new FileOutputStream(tmp, false), StandardCharsets.UTF_8));
                for (String k : keep) {
                    bw.write(k);
                    bw.write("\n");
                }
                bw.close();
                if (tmp.renameTo(f)) {
                    n += drop;
                } else {
                    try { tmp.delete(); } catch (Throwable ignored) {}
                }
            } catch (Exception ignored) {}
        }
        return n;
    }

    /** 统计某个 peerId 的聊天记录条数 */
    public static int countHistoryOf(Context ctx, String peerId, boolean chatsOnly) {
        if (peerId == null || peerId.isEmpty()) return 0;
        int n = 0;
        try {
            java.io.BufferedReader br = new java.io.BufferedReader(
                    new java.io.InputStreamReader(
                            new FileInputStream(historyFile(ctx, peerId)), "UTF-8"));
            String line;
            while ((line = br.readLine()) != null) {
                if (line.trim().isEmpty()) continue;
                if (chatsOnly && "file".equals(optStringQuiet(line, "kind"))) continue;
                n++;
            }
            br.close();
        } catch (Exception ignored) {}
        return n;
    }

    /** 单行 JSON 静默取字符串字段（历史文件可能有脏行，不能因解析失败中断统计） */
    private static String optStringQuiet(String jsonLine, String key) {
        try {
            return new JSONObject(jsonLine).optString(key, "");
        } catch (Exception e) {
            return "";
        }
    }

    private static int deleteRecursively(File dir, Boolean imagesOnly) {
        int n = 0;
        File[] fs = dir == null ? null : dir.listFiles();
        if (fs == null) return 0;
        for (File f : fs) {
            // ★ v1.16.0：受保护目录「保存的文件」整个跳过 ——
            // 既不删里面的文件，也不删这个空目录本身（它是用户的留存区）。
            if (f.isDirectory() && USER_SAVE_DIR.equals(f.getName())) continue;
            if (f.isDirectory()) {
                n += deleteRecursively(f, imagesOnly);
                // 空目录清掉，避免设备多了留一堆空壳
                File[] left = f.listFiles();
                if (left != null && left.length == 0) f.delete();
            } else {
                if (imagesOnly != null && isImageMime(guessMime(f.getName())) != imagesOnly)
                    continue;
                if (f.delete()) n++;
            }
        }
        return n;
    }

    // ==================== v1.11.0：动效基础设施 ====================

    /** dp -> px（FdAnim / 图片预览器等处统一走这里，避免各写各的换算） */
    public static int dp(Context ctx, float v) {
        if (ctx == null) return (int) v;
        return (int) android.util.TypedValue.applyDimension(
                android.util.TypedValue.COMPLEX_UNIT_DIP, v,
                ctx.getResources().getDisplayMetrics());
    }

    // ==================== v1.18.10：按钮尺寸归一 ====================

    /**
     * 把系统 Button 的"隐形内缩"彻底清零。
     *
     * ★ 用户第 3 条：安卓版「取消」按钮显示不完整（文字被截掉）。
     *
     * 根因不是宽度不够，而是 **Android 默认 Button 样式自带四件事**：
     *   ① `minWidth`（主题里通常是 64~88dp）—— 看着够宽，但它同时
     *   ② `minHeight` 与 ③ 背景 Drawable 的 `inset`（左右各 4dp 起，
     *      Material 主题下更多），内缩会**吃掉**我们设的 paddingLeft/Right；
     *   ④ `setIncludeFontPadding(true)` 让行高比字面高出一截。
     *
     * 结果是 2 个汉字的按钮：我们给 12dp 左右 padding，被 inset 吃掉后
     * 实际可用宽度只剩 "文字宽度 + 极少量余量"，中文字形又比拉丁字母宽，
     * 于是「取消」被截成「取…」或半个字。
     *
     * 修法：显式把 minWidth/minHeight 归零，关闭 stateListAnimator 的
     * 高度动画干扰，并清掉 includeFontPadding —— 让按钮**严格由
     * padding + 文字**决定尺寸。
     */
    public static void normalizeButton(android.widget.Button b) {
        if (b == null) return;
        b.setMinWidth(0);
        b.setMinimumWidth(0);
        b.setMinHeight(0);
        b.setMinimumHeight(0);
        b.setIncludeFontPadding(false);
        // 默认 Button 会强制大写（allCaps），中文虽不受影响，
        // 但混排英文时会出现"看着被拉宽"的错觉，一并关掉保持一致。
        b.setAllCaps(false);
        // 背景由调用方按主题设置；这里只负责清掉系统背景带来的 inset
        b.setPadding(b.getPaddingLeft(), b.getPaddingTop(),
                b.getPaddingRight(), b.getPaddingBottom());
    }

    /** 同上，但直接指定水平内边距（气泡内的小按钮统一用 14dp，2 汉字刚好不挤） */
    public static void normalizeButton(android.widget.Button b, int padH, int padV) {
        normalizeButton(b);
        if (b != null) b.setPadding(padH, padV, padH, padV);
    }
}
