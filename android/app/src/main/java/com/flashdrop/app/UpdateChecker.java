package com.flashdrop.app;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * 软件更新检查（v1.18.30 新增，与 Windows 端 app/updater.py 对称）。
 *
 * 数据源：GitHub Releases latest（仓库 Thomajesty/FlashDrop，公开可访问）。
 * Windows exe 与 Android apk 都挂在 Release 附件上，本类负责查最新版本、
 * 语义比较、挑出 apk 安装包直链；UI 由调用方（SettingsActivity /
 * MainActivity 静默检查）决定。
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
                "下载 Android 版", "稍后再说",
                () -> {
                    String url = apk != null ? apk.optString("url", "")
                            : info.optString("html_url", RELEASES_PAGE);
                    if (url.isEmpty()) url = RELEASES_PAGE;
                    try {
                        a.startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
                    } catch (Throwable ignored) {
                        Toast.makeText(a, "无法打开浏览器，请手动访问 " + RELEASES_PAGE,
                                Toast.LENGTH_LONG).show();
                    }
                },
                null, false);
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
