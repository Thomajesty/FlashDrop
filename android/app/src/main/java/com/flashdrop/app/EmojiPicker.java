package com.flashdrop.app;

import android.content.Context;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.BaseAdapter;
import android.widget.FrameLayout;
import android.widget.GridView;
import android.widget.HorizontalScrollView;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.Charset;
import java.util.ArrayList;
import java.util.List;

/**
 * Fluent Emoji 表情选择面板（Android 端）。
 *
 * <p>数据来源：Microsoft Fluent Emoji（MIT），已随 APK 内置
 * assets/emoji_catalog.json + res/drawable-nodpi/e_&lt;slug&gt;.png。
 *
 * <h3>v1.18.12 改版（用户第 3 条，参照微信）</h3>
 * <ul>
 *   <li><b>常用表情行</b>：网格上方常驻一排「最近使用」（最多 8 个，持久化到
 *       SharedPreferences），对应微信面板顶部那排高频表情。</li>
 *   <li><b>分组列表恒定</b>：原实现把「最近」混在页签里，切走后会丢；
 *       现在「最近」独立成行，页签只放真实分组，切分类不再丢常用。</li>
 *   <li><b>高度对齐全屏键盘区</b>：见 {@link #getHeight()}，按屏幕高度与
 *       输入法量级估算，尽量占满底部键盘区域（微信同款观感）。</li>
 * </ul>
 */
public class EmojiPicker {

    public interface OnPick {
        void onPick(String emoji);
    }

    private static final int COLS = 8;
    private static final int CELL_DP = 40;
    /** 「常用表情」一行最多保留个数（与微信一排 8 个对齐） */
    private static final int RECENT_MAX = 8;
    /** 常用表情持久化键 */
    private static final String PREF_FILE = "fd_emoji";
    private static final String PREF_RECENT = "recent_slugs";

    /** 分类中文名 */
    private static final String[][] GROUP_CN = {
            {"Smileys & Emotion", "表情"},
            {"People & Body", "人物"},
            {"Animals & Nature", "动物"},
            {"Food & Drink", "食物"},
            {"Travel & Places", "旅行"},
            {"Activities", "活动"},
            {"Objects", "物品"},
            {"Symbols", "符号"},
            {"Flags", "旗帜"},
            // ★ v1.18.13（用户第 4 条）：「安卓版点击底部的表情包 表情包里面的
            //   其他 文案 改为全部表情」。这里的分组名同时用于页签文案，
            //   改这一个映射即可全局生效（页签 + 标题 + 空态提示）。
            {"Other", "全部表情"},
    };

    private static List<JSONObject> CACHE;   // 全量拍平后的条目，进程内只解析一次
    private static List<Entry> RECENT = null; // 常用表情（进程内缓存，持久化在 prefs）

    public static class Entry {
        public final String slug, ch, cn, group;
        Entry(String slug, String ch, String cn, String group) {
            this.slug = slug; this.ch = ch; this.cn = cn; this.group = group;
        }
    }

    private final Context ctx;
    private final FdTheme theme;
    private final OnPick onPick;
    private final LinearLayout root;
    private final GridView grid;
    private final LinearLayout tabs;
    private final TextView hint;
    /** 「常用表情」区（标题 + 一行格子），无常用时整块隐藏 */
    private final LinearLayout recentWrap;
    private final LinearLayout recentRow;

    private final List<Entry> all = new ArrayList<>();
    private final List<String> groupNames = new ArrayList<>();
    private final List<List<Entry>> groupEmoji = new ArrayList<>();
    private final List<TextView> tabViews = new ArrayList<>();

    private int sel = 0;
    private EmojiAdapter adapter;

    public EmojiPicker(Context ctx, FdTheme theme, OnPick onPick) {
        this.ctx = ctx;
        this.theme = theme;
        this.onPick = onPick;
        loadCatalog();
        loadRecent();

        root = new LinearLayout(ctx);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(theme.bar);
        int pad = dp(8);
        root.setPadding(dp(6), pad, dp(6), pad);

        // —— ① 常用表情（最近使用，一行 8 个）——
        // ★ v1.18.12（用户第 3 条）：对齐微信面板顶部那排高频表情。
        recentWrap = new LinearLayout(ctx);
        recentWrap.setOrientation(LinearLayout.VERTICAL);
        recentRow = new LinearLayout(ctx);
        recentRow.setOrientation(LinearLayout.HORIZONTAL);
        recentWrap.addView(recentRow, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));
        root.addView(recentWrap, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));

        // —— ② 分类页签（横向滚动）——
        HorizontalScrollView hs = new HorizontalScrollView(ctx);
        hs.setHorizontalScrollBarEnabled(false);
        tabs = new LinearLayout(ctx);
        tabs.setOrientation(LinearLayout.HORIZONTAL);
        hs.addView(tabs, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));
        LinearLayout.LayoutParams hlp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        hlp.topMargin = dp(4);
        root.addView(hs, hlp);

        // —— ③ 网格 ——
        grid = new GridView(ctx);
        grid.setNumColumns(COLS);
        grid.setVerticalScrollBarEnabled(false);
        grid.setSelector(new android.graphics.drawable.ColorDrawable(Color.TRANSPARENT));
        adapter = new EmojiAdapter();
        grid.setAdapter(adapter);
        LinearLayout.LayoutParams glp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0);
        glp.weight = 1f;
        glp.topMargin = dp(4);
        root.addView(grid, glp);

        // —— ④ 底部提示 ——
        hint = new TextView(ctx);
        hint.setTextSize(TypedValue.COMPLEX_UNIT_SP, 11);
        hint.setTextColor(theme.dim);
        hint.setPadding(dp(4), dp(4), dp(4), 0);
        root.addView(hint, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        buildTabs();
        selectGroup(0);
        refreshRecent();
        // ★ v1.18.29：目录加载失败（缺失/解析错）时**明确提示**，
        //   不再静默显示一块空白面板。正常流程 groupNames 必有内容
        //   （10 个 CLDR 分组），为空只可能是 assets 没打进包。
        if (groupNames.isEmpty()) {
            hint.setText("表情加载失败，请重启应用或向开发者反馈");
        }
    }

    // ==================== 目录加载 ====================

    private void loadCatalog() {
        if (CACHE != null) return;
        CACHE = new ArrayList<>();
        try {
            InputStream is = ctx.getAssets().open("emoji_catalog.json");
            BufferedReader br = new BufferedReader(
                    new InputStreamReader(is, Charset.forName("UTF-8")));
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = br.readLine()) != null) sb.append(line);
            br.close();
            JSONObject rootObj = new JSONObject(sb.toString());
            JSONArray groups = rootObj.optJSONArray("groups");
            if (groups == null) return;
            for (int i = 0; i < groups.length(); i++) {
                JSONObject grp = groups.getJSONObject(i);
                JSONArray arr = grp.optJSONArray("emojis");
                if (arr == null) continue;
                // ★ v1.18.29：catalog 的条目本身**不带 group 字段**
                //   （分组只由 groups[].name 的数组归属隐含，见
                //   assets/emoji_catalog.json）。拍平时必须把组名注入条目，
                //   否则 buildTabs() 的 optString("group", "Other") 会把
                //   全部 1592 个条目归到「全部表情」→ 页签只剩一个，
                //   顶部分类栏（HorizontalScrollView）形同虚设。
                String gname = grp.optString("name", "Other");
                for (int j = 0; j < arr.length(); j++) {
                    JSONObject e = arr.getJSONObject(j);
                    JSONObject copy = new JSONObject();
                    java.util.Iterator<String> it = e.keys();
                    while (it.hasNext()) {
                        String k = it.next();
                        copy.put(k, e.get(k));
                    }
                    copy.put("group", gname);
                    CACHE.add(copy);
                }
            }
        } catch (Throwable e) {
            // ★ v1.18.29：目录缺失/解析失败必须**留痕**。
            //   v1.18.22~v1.18.28 曾因构建脚本漏打 assets/emoji_catalog.json，
            //   这里静默失败 → 面板全空白、用户看到"表情包不显示"却无任何线索。
            //   现在至少 logcat 里能看到 stacktrace（构造函数收尾另有可见提示）。
            android.util.Log.e("EmojiPicker", "load emoji_catalog.json failed", e);
            // 目录缺失时 all 为空，UI 会显示占位提示（见构造函数收尾）
        }
    }

    private String cnOf(String group) {
        for (String[] g : GROUP_CN) if (g[0].equals(group)) return g[1];
        // ★ v1.18.13：兜底也统一为「全部表情」——「其他」文案已全站废弃（用户第 4 条）
        return group == null || group.isEmpty() ? "全部表情" : group;
    }

    // ==================== 常用表情（最近使用） ====================

    /** 从 SharedPreferences 读常用表情 slug 列表（进程内只读一次） */
    private void loadRecent() {
        if (RECENT != null) return;
        RECENT = new ArrayList<>();
        try {
            String csv = ctx.getSharedPreferences(PREF_FILE, Context.MODE_PRIVATE)
                    .getString(PREF_RECENT, "");
            if (csv == null || csv.isEmpty()) return;
            for (String s : csv.split(",")) {
                if (s.isEmpty()) continue;
                Entry e = findBySlug(s);
                if (e != null) RECENT.add(e);
                if (RECENT.size() >= RECENT_MAX) break;
            }
        } catch (Throwable ignored) {}
    }

    private Entry findBySlug(String slug) {
        if (slug == null) return null;
        for (JSONObject o : CACHE) {
            if (slug.equals(o.optString("slug"))) {
                return new Entry(o.optString("slug"), o.optString("char"),
                        o.optString("cn"), o.optString("group", "Other"));
            }
        }
        return null;
    }

    /** 把某表情置顶到常用列表首位并持久化 */
    private void pushRecent(Entry e) {
        if (e == null || e.slug == null || e.slug.isEmpty()) return;
        if (RECENT == null) RECENT = new ArrayList<>();
        // 去重后插到最前
        for (int i = RECENT.size() - 1; i >= 0; i--) {
            if (e.slug.equals(RECENT.get(i).slug)) RECENT.remove(i);
        }
        RECENT.add(0, e);
        while (RECENT.size() > RECENT_MAX) RECENT.remove(RECENT.size() - 1);
        try {
            StringBuilder sb = new StringBuilder();
            for (Entry x : RECENT) {
                if (sb.length() > 0) sb.append(',');
                sb.append(x.slug);
            }
            ctx.getSharedPreferences(PREF_FILE, Context.MODE_PRIVATE)
                    .edit().putString(PREF_RECENT, sb.toString()).apply();
        } catch (Throwable ignored) {}
    }

    /**
     * 重建「常用表情」一行。
     *
     * ★ v1.18.12：无常用记录时**整块隐藏**（不占位），避免新用户看到
     *   一行空白；有记录时显示标题 + 最多 8 个格子，点一下同样插入光标处。
     */
    private void refreshRecent() {
        if (recentWrap == null || recentRow == null) return;
        recentRow.removeAllViews();
        if (RECENT == null || RECENT.isEmpty()) {
            recentWrap.setVisibility(View.GONE);
            return;
        }
        recentWrap.setVisibility(View.VISIBLE);
        recentRow.removeAllViews();

        TextView title = new TextView(ctx);
        title.setText("常用表情");
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 11);
        title.setTextColor(theme.dim);
        title.setPadding(dp(4), 0, dp(4), dp(4));
        // 标题单独占一行，格子在其下
        recentWrap.removeAllViews();
        recentWrap.addView(title, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));
        recentWrap.addView(recentRow, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));

        for (Entry e : RECENT) {
            FrameLayout cell = new FrameLayout(ctx);
            LinearLayout.LayoutParams clp = new LinearLayout.LayoutParams(
                    0, dp(CELL_DP), 1f);
            ImageView iv = new ImageView(ctx);
            int s = dp(30);
            FrameLayout.LayoutParams ilp = new FrameLayout.LayoutParams(s, s);
            ilp.gravity = Gravity.CENTER;
            cell.addView(iv, ilp);

            int resId = ctx.getResources().getIdentifier(
                    "e_" + e.slug.replace('-', '_'), "drawable", ctx.getPackageName());
            if (resId != 0) iv.setImageResource(resId);

            final String ch = e.ch;
            final Entry fe = e;
            cell.setOnClickListener(v -> {
                if (onPick == null || ch == null || ch.isEmpty()) return;
                pushRecent(fe);
                onPick.onPick(ch);
            });
            recentRow.addView(cell, clp);
        }
    }

    // ==================== 页签 ====================

    private void buildTabs() {
        // 先按 CLDR 顺序归组
        List<String> order = new ArrayList<>();
        for (String[] g : GROUP_CN) order.add(g[0]);
        for (JSONObject o : CACHE) {
            String g = o.optString("group", "Other");
            if (!order.contains(g)) order.add(g);
        }
        for (String g : order) {
            List<Entry> bucket = new ArrayList<>();
            for (JSONObject o : CACHE) {
                if (g.equals(o.optString("group", "Other"))) {
                    bucket.add(new Entry(o.optString("slug"), o.optString("char"),
                            o.optString("cn"), g));
                }
            }
            if (!bucket.isEmpty()) {
                groupNames.add(g);
                groupEmoji.add(bucket);
                all.addAll(bucket);
            }
        }

        for (int i = 0; i < groupNames.size(); i++) {
            final int idx = i;
            TextView t = new TextView(ctx);
            t.setText(cnOf(groupNames.get(i)));
            t.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
            t.setPadding(dp(12), dp(6), dp(12), dp(6));
            t.setGravity(Gravity.CENTER);
            t.setTypeface(Typeface.DEFAULT);
            t.setOnClickListener(v -> selectGroup(idx));
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT);
            lp.rightMargin = dp(2);
            tabs.addView(t, lp);
            tabViews.add(t);
        }
        styleTabs();
    }

    private void styleTabs() {
        for (int i = 0; i < tabViews.size(); i++) {
            TextView t = tabViews.get(i);
            boolean on = (i == sel);
            GradientDrawable bg = new GradientDrawable();
            bg.setCornerRadius(dp(8));
            bg.setColor(on ? theme.card : Color.TRANSPARENT);
            t.setBackground(bg);
            t.setTextColor(on ? theme.text : theme.dim);
            t.setTypeface(on ? Typeface.DEFAULT_BOLD : Typeface.DEFAULT);
        }
    }

    private void selectGroup(int idx) {
        if (idx < 0 || idx >= groupNames.size()) return;
        sel = idx;
        styleTabs();
        adapter.setData(groupEmoji.get(idx));
        hint.setText(cnOf(groupNames.get(idx)) + " · 共 " + groupEmoji.get(idx).size() + " 个");
        grid.setSelection(0);
    }

    // ==================== 适配器 ====================

    private class EmojiAdapter extends BaseAdapter {
        private List<Entry> data = new ArrayList<>();

        void setData(List<Entry> d) {
            data = (d == null) ? new ArrayList<>() : d;
            notifyDataSetChanged();
        }

        @Override public int getCount() { return data.size(); }
        @Override public Object getItem(int p) { return data.get(p); }
        @Override public long getItemId(int p) { return p; }

        @Override
        public View getView(int pos, View convert, ViewGroup parent) {
            FrameLayout cell;
            if (convert instanceof FrameLayout) {
                cell = (FrameLayout) convert;
            } else {
                cell = new FrameLayout(ctx);
                cell.setLayoutParams(new android.widget.AbsListView.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT, dp(CELL_DP)));
                ImageView iv = new ImageView(ctx);
                iv.setId(1001);
                int s = dp(30);
                FrameLayout.LayoutParams ilp = new FrameLayout.LayoutParams(s, s);
                ilp.gravity = Gravity.CENTER;
                cell.addView(iv, ilp);
            }
            ImageView iv = cell.findViewById(1001);
            Entry e = data.get(pos);

            int resId = ctx.getResources().getIdentifier(
                    "e_" + e.slug.replace('-', '_'), "drawable", ctx.getPackageName());
            if (resId != 0) {
                iv.setImageResource(resId);
            } else {
                iv.setImageDrawable(null);
            }
            final String ch = e.ch;
            final Entry fe = e;
            cell.setOnClickListener(v -> {
                if (onPick == null || ch == null || ch.isEmpty()) return;
                // ★ v1.18.12：点过的表情进「常用表情」并立即刷新那一行
                pushRecent(fe);
                refreshRecent();
                onPick.onPick(ch);
            });
            return cell;
        }
    }

    // ==================== 对外接口 ====================

    public View getView() { return root; }

    /**
     * 面板高度（兜底值）。
     *
     * ★ v1.18.12（用户第 3 条）：用户要求「表情包显示区域为底部键盘区域」。
     * ★ v1.18.13（用户第 5 条）：「表情包展开的高度太高 可以参照微信来修正」。
     *
     * <p>实际使用时 MainActivity 会优先传**真实 IME 高度**（见 panelHeight()），
     * 本方法只在拿不到 IME 高度时兜底。旧版用屏幕高 42%，实测比微信安卓
     * 键盘（约占 36%~40%）明显偏高，故下调到 36%。
     */
    public int getHeight() {
        int screenH = 0;
        try {
            screenH = ctx.getResources().getDisplayMetrics().heightPixels;
        } catch (Throwable ignored) {}
        // 微信安卓键盘实测约占屏高 36%~40%，取 36% 作为兜底
        int byKeyboard = (int) (screenH * 0.36f);
        int byContent = dp(34) + dp(CELL_DP) * 5 + dp(26) + dp(16);
        // 常用表情一行（标题 + 40dp）
        int recentH = (RECENT != null && !RECENT.isEmpty()) ? dp(16) + dp(CELL_DP) : 0;
        int want = Math.max(byContent, byKeyboard);
        // ★ v1.18.14：上限由 50% 收到 45%（实测键盘约占屏高 36%~40%，
        //   50% 会让面板比键盘高一整行）。注意：实际高度由
        //   MainActivity.panelHeight() 通过 LayoutParams 指定，这里只是兜底。
        int cap = (int) (screenH * 0.45f);
        return Math.min(want, cap) + recentH;
    }

    public void refresh() {
        // 主题切换后重建样式（面板通常随即重建，这里只兜底）
        root.setBackgroundColor(theme.bar);
        styleTabs();
        hint.setTextColor(theme.dim);
        adapter.notifyDataSetChanged();
        refreshRecent();
    }

    private int dp(int v) {
        return (int) (v * ctx.getResources().getDisplayMetrics().density + 0.5f);
    }
}
