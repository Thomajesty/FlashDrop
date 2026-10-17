package com.flashdrop.app;

import android.app.Activity;
import android.app.Dialog;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.drawable.ColorDrawable;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * 软件更新检查与下载安装（v1.18.30 新增，v1.18.32 补应用内下载）。
 *
 * 数据源：GitHub Releases latest（仓库 Thomajesty/FlashDrop，公开可访问）。
 * Windows exe 与 Android apk 都挂在 Release 附件上，本类负责查最新版本、
 * 语义比较、挑出 apk 安装包直链、应用内下载并调起安装；UI 由调用方
 * （SettingsActivity / MainActivity 静默检查）决定。
 *
 * 下载落点：应用私有缓存 cacheDir/flashdrop/update/<附件名>，
 * 安装时经 FdFileProvider 转 content:// 直呼（API 24+ 禁用 file://）。
 * API 26+ 需用户授予「安装未知应用」——缺失时先跳系统设置引导，再下载。
 *
 * 注意：
 * - 未认证 GitHub API 限额 60 次/小时/IP；启动静默检查由 Prefs 限频每天一次。
 * - 国内直连 api.github.com 常超时：8s 超时后回调 null，由调用方提示或静默。
 */
public final class UpdateChecker {

    public static final String REPO_OWNER = "Thomajesty";
    public static final String REPO_NAME = "FlashDrop";
    private static final String API = "https://api.github.com/repos/"
            + REPO_OWNER + "/" + REPO_NAME + "/releases/latest";
    public static final String RELEASES_PAGE = "https://github.com/"
            + REPO_OWNER + "/" + REPO_NAME + "/releases";
    private static final int TIMEOUT_MS = 8000;

    public interface Callback {
        /** info 非空=有新版本可展示；null=检查失败/无新版本（调用方按需区分） */
        void onResult(JSONObject info);
    }

    private UpdateChecker() {}

    /** 后台线程查询，回调切回主线程。 */
    public static void check(Callback cb) {
        new Thread(() -> {
            JSONObject info = fetch();
            new Handler(Looper.getMainLooper()).post(() -> cb.onResult(info));
        }, "fd-update-check").start();
    }

    /** 同步查询（供测试/已在新线程的场景）；失败返回 null。 */
    public static JSONObject fetch() {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(API).openConnection();
            c.setConnectTimeout(TIMEOUT_MS);
            c.setReadTimeout(TIMEOUT_MS);
            c.setRequestMethod("GET");
            c.setRequestProperty("Accept", "application/vnd.github+json");
            c.setRequestProperty("User-Agent", "FlashDrop-Updater");
            if (c.getResponseCode() != 200) return null;
            BufferedReader r = new BufferedReader(new InputStreamReader(
                    c.getInputStream(), "UTF-8"));
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = r.readLine()) != null) sb.append(line);
            r.close();
            return parse(sb.toString());
        } catch (Exception e) {
            return null;
        } finally {
            if (c != null) c.disconnect();
        }
    }

    private static JSONObject parse(String body) {
        try {
            JSONObject root = new JSONObject(body);
            String tag = root.optString("tag_name", "");
            if (parseVersion(tag) == null) return null;   // tag 不是语义版本 → 不提示
            JSONObject out = new JSONObject();
            out.put("version", normalize(tag));
            out.put("tag", tag);
            out.put("notes", root.optString("body", ""));
            out.put("html_url", root.optString("html_url", RELEASES_PAGE));
            JSONArray assets = root.optJSONArray("assets");
            JSONArray outAssets = new JSONArray();
            if (assets != null) {
                for (int i = 0; i < assets.length(); i++) {
                    JSONObject a = assets.optJSONObject(i);
                    if (a == null) continue;
                    String name = a.optString("name", "");
                    String url = a.optString("browser_download_url", "");
                    if (name.isEmpty() || url.isEmpty()) continue;
                    JSONObject o = new JSONObject();
                    o.put("name", name);
                    o.put("url", url);
                    outAssets.put(o);
                }
            }
            out.put("assets", outAssets);
            return out;
        } catch (Exception e) {
            return null;
        }
    }

    /** 从附件里挑某个平台的安装包（".exe" / ".apk"）；找不到返回 null。 */
    public static JSONObject assetFor(JSONObject info, String suffix) {
        if (info == null) return null;
        JSONArray assets = info.optJSONArray("assets");
        if (assets == null) return null;
        String suf = suffix.toLowerCase();
        for (int i = 0; i < assets.length(); i++) {
            JSONObject a = assets.optJSONObject(i);
            if (a == null) continue;
            if (a.optString("name", "").toLowerCase().endsWith(suf)) return a;
        }
        return null;
    }

    /**
     * 发现新版本对话框（版本对比 + 更新日志 + 下载按钮）。
     * SettingsActivity 手动检查与 MainActivity 启动静默检查共用。
     */
    public static void showUpdateDialog(final Activity a, JSONObject info) {
        if (a == null || a.isFinishing() || info == null) return;
        String ver = info.optString("version", "");
        String notes = info.optString("notes", "").trim();
        StringBuilder msg = new StringBuilder();
        msg.append("当前 v").append(FdUtil.APP_VERSION)
           .append("　→　最新 v").append(ver);
        if (!notes.isEmpty()) {
            msg.append("\n\n").append(notes.length() > 1500
                    ? notes.substring(0, 1500) + "…" : notes);
        }
        final JSONObject apk = assetFor(info, ".apk");
        FdDialog.show(a, "发现新版本", msg.toString(),
                apk != null ? "下载并安装" : "打开下载页", "稍后再说",
                () -> {
                    if (apk == null) {
                        openBrowser(a, info.optString("html_url", RELEASES_PAGE));
                        return;
                    }
                    startDownload(a, apk);
                },
                null, false);
    }

    // ---------- v1.18.32：应用内下载并安装 ----------

    /** 下载进度回调（已在主线程调用）。done<0 表示进入安装阶段。 */
    public interface Progress {
        void onProgress(long done, long total);
    }

    /** 用户主动取消标志（工作线程读、主线程写，volatile 保证可见性）。 */
    private static volatile boolean sCancelled = false;

    /**
     * 应用内下载 apk 并调起安装：进度对话框（可取消）→ 私有缓存落盘 →
     * API26+ 安装授权检查 → FdFileProvider 转 content:// 呼起系统安装器。
     * 任何失败都回退「浏览器打开下载页」，绝不静默失败。
     */
    public static void startDownload(final Activity a, final JSONObject apk) {
        if (a == null || a.isFinishing() || apk == null) return;
        final String url = apk.optString("url", "");
        final String name = apk.optString("name", "");
        if (url.isEmpty() || name.isEmpty()) {
            openBrowser(a, RELEASES_PAGE);
            return;
        }
        final Handler main = new Handler(Looper.getMainLooper());

        // ---- 进度对话框（微信风格，与 FdDialog 一致）----
        FdTheme t = FdTheme.resolve(a);
        int bg = t.dark ? 0xFF2E2E2E : 0xFFFFFFFF;
        int mainText = t.dark ? 0xFFEDEDED : 0xFF1A1A1A;
        int subText = t.dark ? 0xFF9A9A9A : 0xFF888888;
        int divider = t.dark ? 0xFF3E3E3E : 0xFFE5E5E5;
        final Dialog d = new Dialog(a);
        d.requestWindowFeature(Window.FEATURE_NO_TITLE);
        LinearLayout root = new LinearLayout(a);
        root.setOrientation(LinearLayout.VERTICAL);
        GradientDrawable rbg = new GradientDrawable();
        rbg.setColor(bg);
        rbg.setCornerRadius(FdUtil.dp(a, 12));
        root.setBackground(rbg);
        TextView tvTitle = new TextView(a);
        tvTitle.setText("正在下载新版本");
        tvTitle.setTextColor(mainText);
        tvTitle.setTextSize(16);
        tvTitle.setGravity(Gravity.CENTER);
        tvTitle.setPadding(FdUtil.dp(a, 22), FdUtil.dp(a, 22),
                FdUtil.dp(a, 22), FdUtil.dp(a, 8));
        root.addView(tvTitle);
        final ProgressBar bar = new ProgressBar(a, null,
                android.R.attr.progressBarStyleHorizontal);
        bar.setMax(100);
        bar.setProgress(0);
        int pad = FdUtil.dp(a, 22);
        LinearLayout.LayoutParams blp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
        blp.setMargins(pad, FdUtil.dp(a, 10), pad, 0);
        root.addView(bar, blp);
        final TextView status = new TextView(a);
        status.setText("0%");
        status.setTextColor(subText);
        status.setTextSize(12);
        status.setGravity(Gravity.CENTER);
        status.setPadding(pad, FdUtil.dp(a, 8), pad, FdUtil.dp(a, 16));
        root.addView(status);
        View hr = new View(a);
        hr.setBackgroundColor(divider);
        root.addView(hr, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, Math.max(1, FdUtil.dp(a, 1))));
        TextView cancel = new TextView(a);
        cancel.setText("取消");
        cancel.setTextColor(mainText);
        cancel.setTextSize(16);
        cancel.setGravity(Gravity.CENTER);
        cancel.setPadding(0, FdUtil.dp(a, 15), 0, FdUtil.dp(a, 15));
        cancel.setClickable(true);
        cancel.setOnClickListener(v -> {
            sCancelled = true;
            d.dismiss();
        });
        root.addView(cancel, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));
        d.setContentView(root);
        d.setCanceledOnTouchOutside(false);
        Window w = d.getWindow();
        if (w != null) {
            w.setBackgroundDrawable(new ColorDrawable(Color.TRANSPARENT));
            w.setLayout((int) (a.getResources().getDisplayMetrics().widthPixels * 0.78f),
                    ViewGroup.LayoutParams.WRAP_CONTENT);
        }

        sCancelled = false;
        d.show();

        new Thread(() -> {
            File out = null;
            try {
                File dir = new File(FdUtil.cacheDir(a), "update");
                if (!dir.exists()) dir.mkdirs();
                out = new File(dir, name);
                downloadToFile(url, out, (done, total) -> main.post(() -> {
                    if (d.isShowing()) {
                        if (total > 0) {
                            bar.setIndeterminate(false);
                            bar.setMax(100);
                            bar.setProgress((int) (done * 100 / total));
                            status.setText(FdUtil.fmtSize(done) + " / "
                                    + FdUtil.fmtSize(total) + "（"
                                    + (done * 100 / total) + "%）");
                        } else {
                            bar.setIndeterminate(true);
                            status.setText(FdUtil.fmtSize(done));
                        }
                    }
                }));
                if (sCancelled) {
                    if (out != null) out.delete();
                    return;
                }
                final File apkFile = out;
                main.post(() -> {
                    d.dismiss();
                    installApk(a, apkFile);
                });
            } catch (Throwable tr) {
                if (out != null) out.delete();
                main.post(() -> {
                    d.dismiss();
                    Toast.makeText(a, "下载失败，已为你打开下载页", Toast.LENGTH_LONG).show();
                    openBrowser(a, url);
                });
            }
        }, "fd-update-download").start();
    }

    /**
     * 把 url 下载到 out（先写 .part 再改名，避免半包被当成品）。
     * 手动跟随重定向（assets 直链会 302 到 objects.githubusercontent.com）。
     */
    private static void downloadToFile(String urlStr, File out, Progress cb)
            throws IOException {
        HttpURLConnection c = null;
        try {
            URL url = new URL(urlStr);
            for (int i = 0; i < 6; i++) {
                c = (HttpURLConnection) url.openConnection();
                c.setInstanceFollowRedirects(true);
                c.setConnectTimeout(15000);
                c.setReadTimeout(15000);
                c.setRequestProperty("User-Agent", "FlashDrop-Updater");
                int code = c.getResponseCode();
                if (code == 301 || code == 302 || code == 303 || code == 307
                        || code == 308) {
                    String loc = c.getHeaderField("Location");
                    c.disconnect();
                    if (loc == null || loc.isEmpty()) {
                        throw new IOException("redirect without Location");
                    }
                    url = new URL(url, loc);   // 相对地址基于当前 URL 解析
                    continue;
                }
                if (code != 200) throw new IOException("HTTP " + code);
                break;
            }
            long total = c.getContentLengthLong();
            File tmp = new File(out.getAbsolutePath() + ".part");
            try (InputStream in = c.getInputStream();
                 FileOutputStream fos = new FileOutputStream(tmp)) {
                byte[] buf = new byte[16384];
                long done = 0, lastPost = 0;
                int n;
                while ((n = in.read(buf)) > 0) {
                    if (sCancelled) {
                        tmp.delete();
                        return;
                    }
                    fos.write(buf, 0, n);
                    done += n;
                    long now = System.currentTimeMillis();
                    if (cb != null && now - lastPost >= 200) {
                        lastPost = now;
                        cb.onProgress(done, total);
                    }
                }
                fos.flush();
            }
            if (!tmp.renameTo(out)) throw new IOException("rename failed");
            if (cb != null) cb.onProgress(total, total);
        } finally {
            if (c != null) c.disconnect();
        }
    }

    /**
     * 调起系统安装器。API 26+ 未授予「安装未知应用」时先跳设置引导；
     * 无安装器可用时 Toast 指明包名，回退由调用方已做的浏览器路径覆盖。
     */
    private static void installApk(Activity a, File apkFile) {
        if (a == null || apkFile == null || !apkFile.exists()) {
            Toast.makeText(a, "安装包不存在，请重新下载", Toast.LENGTH_LONG).show();
            return;
        }
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                PackageManager pm = a.getPackageManager();
                if (pm != null && !pm.canRequestPackageInstalls()) {
                    Toast.makeText(a, "请允许「安装未知应用」后再次点击下载",
                            Toast.LENGTH_LONG).show();
                    try {
                        Intent s = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                                Uri.parse("package:" + a.getPackageName()));
                        s.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                        a.startActivity(s);
                    } catch (Throwable ignored) {
                        openBrowser(a, RELEASES_PAGE);
                    }
                    return;
                }
            }
            Uri uri = FdFileProvider.uriForAbsolute(apkFile.getAbsolutePath());
            Intent it = new Intent(Intent.ACTION_VIEW);
            it.setDataAndType(uri, "application/vnd.android.package-archive");
            it.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                    | Intent.FLAG_ACTIVITY_NEW_TASK);
            a.startActivity(it);
        } catch (Throwable tr) {
            Toast.makeText(a, "无法调起安装器，安装包在 "
                    + apkFile.getAbsolutePath(), Toast.LENGTH_LONG).show();
        }
    }

    /** 用浏览器打开 url（打不开时提示手动访问 Release 页）。 */
    private static void openBrowser(Context c, String url) {
        if (url == null || url.isEmpty()) url = RELEASES_PAGE;
        try {
            c.startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
        } catch (Throwable ignored) {
            Toast.makeText(c, "无法打开浏览器，请手动访问 " + RELEASES_PAGE,
                    Toast.LENGTH_LONG).show();
        }
    }

    /** latest 是否严格新于 current；任一侧无法解析时保守返回 false（不提示）。 */
    public static boolean isNewer(String latest, String current) {
        int[] a = parseVersion(latest);
        int[] b = parseVersion(current);
        if (a == null || b == null) return false;
        for (int i = 0; i < 3; i++) {
            if (a[i] != b[i]) return a[i] > b[i];
        }
        return false;
    }

    /** "v1.18.30" → "1.18.30"（无法解析时原样返回）。 */
    public static String normalize(String tag) {
        if (tag == null) return "";
        String t = tag.trim();
        if (t.startsWith("v") || t.startsWith("V")) t = t.substring(1);
        return t;
    }

    /** 语义版本 → 三段 int；无法解析返回 null。预发布/构建后缀忽略。 */
    private static int[] parseVersion(String s) {
        if (s == null) return null;
        String t = s.trim();
        if (t.startsWith("v") || t.startsWith("V")) t = t.substring(1);
        int dash = t.indexOf('-');
        if (dash >= 0) t = t.substring(0, dash);
        int plus = t.indexOf('+');
        if (plus >= 0) t = t.substring(0, plus);
        if (t.isEmpty()) return null;
        String[] parts = t.split("\\.");
        int[] nums = new int[3];
        for (int i = 0; i < parts.length && i < 3; i++) {
            String p = parts[i];
            if (p.isEmpty()) return null;
            for (int j = 0; j < p.length(); j++) {
                if (!Character.isDigit(p.charAt(j))) return null;
            }
            nums[i] = Integer.parseInt(p);
        }
        return nums;
    }
}
