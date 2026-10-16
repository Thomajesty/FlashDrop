package com.flashdrop.app;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;

import java.io.File;
import java.io.FileNotFoundException;
import java.net.URLDecoder;
import java.util.Arrays;

/**
 * 轻量文件提供器（无 AndroidX 依赖）：
 *   content://com.flashdrop.app.files/cache/<相对缓存目录路径>
 *   content://com.flashdrop.app.files/files/<相对内部存储路径>
 *   content://com.flashdrop.app.files/abs/<URL编码的绝对路径>
 * 用于相机拍照输出、以及打开接收到的文件（API<29 file:// 被禁用）。
 */
public class FdFileProvider extends ContentProvider {

    public static final String AUTHORITY = "com.flashdrop.app.files";

    public static Uri uriForCache(Context ctx, String relativePath) {
        return Uri.parse("content://" + AUTHORITY + "/cache/" + relativePath);
    }

    public static Uri uriForAbsolute(String absolutePath) {
        try {
            return Uri.parse("content://" + AUTHORITY + "/abs/"
                    + java.net.URLEncoder.encode(absolutePath, "UTF-8"));
        } catch (Exception e) {
            return Uri.fromFile(new File(absolutePath));
        }
    }

    private static File resolve(Uri uri) throws FileNotFoundException {
        String path = uri.getPath() == null ? "" : uri.getPath();
        Context ctx = FlashApp.get();
        if (path.startsWith("/cache/")) {
            return new File(FdUtil.cacheDir(ctx), path.substring("/cache/".length()));
        }
        if (path.startsWith("/files/")) {
            return new File(ctx.getFilesDir(), path.substring("/files/".length()));
        }
        if (path.startsWith("/abs/")) {
            try {
                return new File(URLDecoder.decode(path.substring("/abs/".length()), "UTF-8"));
            } catch (Exception e) {
                throw new FileNotFoundException("bad path");
            }
        }
        throw new FileNotFoundException("unsupported path: " + path);
    }

    private static int parseMode(String mode) throws FileNotFoundException {
        boolean w = mode != null && mode.contains("w");
        boolean r = mode != null && mode.contains("r");
        if (w && r) return ParcelFileDescriptor.MODE_READ_WRITE
                | ParcelFileDescriptor.MODE_CREATE
                | ParcelFileDescriptor.MODE_TRUNCATE;
        if (w) return ParcelFileDescriptor.MODE_WRITE_ONLY
                | ParcelFileDescriptor.MODE_CREATE
                | ParcelFileDescriptor.MODE_TRUNCATE;
        if (r) return ParcelFileDescriptor.MODE_READ_ONLY;
        throw new FileNotFoundException("bad mode");
    }

    @Override
    public boolean onCreate() {
        // 关键：ContentProvider.onCreate 是进程内**最早**执行的用户代码
        //（早于 Application.onCreate）。在这里装崩溃捕获，才能抓到
        // "Application 初始化阶段就崩溃" 这类日志完全抓不到的场景。
        try {
            CrashTrap.install(getContext());
        } catch (Throwable ignored) {}
        return true;
    }

    @Override
    public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        File f = resolve(uri);
        File parent = f.getParentFile();
        if (parent != null && !parent.exists()) parent.mkdirs();
        return ParcelFileDescriptor.open(f, parseMode(mode));
    }

    @Override
    public Cursor query(Uri uri, String[] projection, String selection,
                        String[] selectionArgs, String sortOrder) {
        File f;
        try { f = resolve(uri); } catch (FileNotFoundException e) { return null; }
        if (projection == null) {
            projection = new String[]{OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE};
        }
        MatrixCursor c = new MatrixCursor(projection);
        Object[] row = new Object[projection.length];
        for (int i = 0; i < projection.length; i++) {
            String col = projection[i];
            if (OpenableColumns.DISPLAY_NAME.equals(col)) row[i] = f.getName();
            else if (OpenableColumns.SIZE.equals(col)) row[i] = f.length();
            else row[i] = null;
        }
        c.addRow(row);
        return c;
    }

    @Override
    public String getType(Uri uri) {
        try {
            File f = resolve(uri);
            return FdUtil.guessMime(f.getName());
        } catch (Exception e) {
            return "application/octet-stream";
        }
    }

    @Override
    public Uri insert(Uri uri, ContentValues values) { return null; }

    @Override
    public int delete(Uri uri, String selection, String[] selectionArgs) { return 0; }

    @Override
    public int update(Uri uri, ContentValues values, String selection, String[] selectionArgs) {
        return 0;
    }
}
