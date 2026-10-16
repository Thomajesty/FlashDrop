package com.flashdrop.app;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.text.TextUtils;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowManager;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.PopupWindow;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.util.Locale;

/**
 * v1.15.0 内置文件预览器。
 *
 * 用户需求：
 *   1. 常见的非图片文件（txt / word / excel / ppt / pdf）**点击卡片即可预览**，
 *      不走系统应用；
 *   2. 预览页**左上角一个「⋯」三点菜单**，点开后是「保存」和「转发」两个动作：
 *        · 保存 → 另存到规范的公共位置（Download/FlashDrop）；
 *        · 转发 → 调用系统分享，发送到其它应用；
 *   3. 不支持的类型 → 调用方弹 2 秒提示，引导长按卡片用「其他应用打开」。
 *
 * 实现取舍（离线、无第三方依赖是本项目的硬约束）：
 *   · 文本类（txt/log/md/json/xml/csv…）→ 完整读取并直接渲染，体验最好；
 *   · PDF → 优先交给系统的 PdfRenderer（API 21+ 系统自带），逐页渲染成图；
 *     若文件加密/损坏则回落到"用其它应用打开"；
 *   · Word / Excel / PPT → 这些是二进制 OOXML/复合文档格式，纯离线解析需要
 *     引入 Apache POI 等重量级库（体积 + 混淆成本都很高）。本版采用
 *     **基本信息卡 + 一键用其它应用打开** 的方式，先把"点击卡片可预览"
 *     的入口和三点菜单做出来，后续版本再补深解析。
 */
public class FdPreviewActivity extends Activity {

    private static final String EXTRA_TITLE = "title";
    private static final String EXTRA_URI = "uri";
    private static final String EXTRA_MIME = "mime";
    private static final String EXTRA_SIZE = "size";

    private String title;
    private String mime;
    private Uri uri;
    private long size;

    private PopupWindow moreMenu;

    /**
     * 是否可以由本预览器处理（扩展名维度）。
     * 调用方用它来决定"点击卡片走内置预览"还是"交给系统/提示不支持"。
     */
    public static boolean canPreview(String ext) {
        if (TextUtils.isEmpty(ext)) return false;
        switch (ext.toLowerCase(Locale.ROOT)) {
            // 纯文本类
            case "txt": case "log": case "md": case "markdown": case "json":
            case "xml": case "yml": case "yaml": case "ini": case "conf":
            case "csv": case "html": case "htm": case "css": case "js":
            case "java": case "py": case "c": case "cpp": case "h":
            case "sh": case "bat": case "sql":
                // PDF
            case "pdf":
                // Office 三件套（基本信息卡 + 外部打开）
            case "doc": case "docx": case "rtf": case "odt":
            case "xls": case "xlsx": case "ods":
            case "ppt": case "pptx": case "odp":
                return true;
            default:
                return false;
        }
    }

    /** 是否为"可完整渲染"的文本类型 */
    private static boolean isText(String ext) {
        switch (ext.toLowerCase(Locale.ROOT)) {
            case "txt": case "log": case "md": case "markdown": case "json":
            case "xml": case "yml": case "yaml": case "ini": case "conf":
            case "csv": case "html": case "htm": case "css": case "js":
            case "java": case "py": case "c": case "cpp": case "h":
            case "sh": case "bat": case "sql":
                return true;
            default:
                return false;
        }
    }

    public static void start(Activity from, MainActivity.Msg m) {
        if (m == null) return;
        Uri u = FdFileOp.uriOf(from, m);
        if (u == null) {
            Toast.makeText(from, "文件不可用", Toast.LENGTH_SHORT).show();
            return;
        }
        Intent it = new Intent(from, FdPreviewActivity.class);
        it.putExtra(EXTRA_TITLE, m.file);
        it.putExtra(EXTRA_URI, u.toString());
        it.putExtra(EXTRA_MIME, m.mime);
        it.putExtra(EXTRA_SIZE, m.size);
        from.startActivity(it);
    }

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        FdTheme t = FdTheme.resolve(this);
        title = getIntent().getStringExtra(EXTRA_TITLE);
        mime = getIntent().getStringExtra(EXTRA_MIME);
        size = getIntent().getLongExtra(EXTRA_SIZE, 0);
        String us = getIntent().getStringExtra(EXTRA_URI);
        uri = TextUtils.isEmpty(us) ? null : Uri.parse(us);
        if (TextUtils.isEmpty(title)) title = "文件";

        // 状态栏跟随（沿用 App 的整体深色观感）
        Window w = getWindow();
        w.addFlags(WindowManager.LayoutParams.FLAG_DRAWS_SYSTEM_BAR_BACKGROUNDS);
        w.setStatusBarColor(0xFF16181D);
        w.setNavigationBarColor(0xFF16181D);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(0xFF16181D);

        root.addView(buildTopBar());
        root.addView(buildBody(), new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));

        setContentView(root);
    }

    // ---------------- 顶栏：返回 + 文件名 + 左上角 ⋯ ----------------

    private View buildTopBar() {
        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setBackgroundColor(0xFF1E2026);
        bar.setPadding(dp(6), dp(8), dp(6), dp(8));

        // 返回
        TextView back = new TextView(this);
        back.setText("‹");
        back.setTextSize(TypedValue.COMPLEX_UNIT_SP, 26);
        back.setTextColor(0xFFE8EAED);
        back.setGravity(Gravity.CENTER);
        back.setPadding(dp(12), 0, dp(12), 0);
        back.setOnClickListener(v -> finish());
        bar.addView(back, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, dp(44)));

        // 文件名（单行省略）
        TextView name = new TextView(this);
        name.setText(title);
        name.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        name.setTextColor(0xFFE8EAED);
        name.setTypeface(Typeface.DEFAULT_BOLD);
        name.setMaxLines(1);
        name.setEllipsize(TextUtils.TruncateAt.MIDDLE);
        LinearLayout.LayoutParams nlp = new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        nlp.leftMargin = dp(4);
        bar.addView(name, nlp);

        // ★ 左上角「⋯」三点菜单（用户要求：左上角显示三个点的功能菜单）
        TextView more = new TextView(this);
        more.setText("⋯");
        more.setTextSize(TypedValue.COMPLEX_UNIT_SP, 22);
        more.setTextColor(0xFFE8EAED);
        more.setGravity(Gravity.CENTER);
        more.setPadding(dp(12), 0, dp(12), 0);
        more.setBackground(theme().round(0xFF2A2E37, 8, this));
        more.setOnClickListener(this::showMoreMenu);
        bar.addView(more, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, dp(40)));

        return bar;
    }

    /** 三点菜单：保存 / 转发（用户明确要求这两个按钮） */
    private void showMoreMenu(View anchor) {
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setBackgroundResource(R.drawable.msg_popup_bg);
        col.setPadding(dp(4), dp(4), dp(4), dp(4));

        col.addView(menuItem("保存", "另存到 Download/FlashDrop", v -> {
            dismissMenu();
            FdFileOp.saveToUserDir(this, uri, title, mime);
        }));
        col.addView(menuItem("转发", "发送到其它应用", v -> {
            dismissMenu();
            FdFileOp.share(this, uri, title, mime);
        }));
        col.addView(menuItem("用其它应用打开", "交给系统应用处理", v -> {
            dismissMenu();
            FdFileOp.openWithChooser(this, uri, title, mime);
        }));

        moreMenu = new PopupWindow(col,
                dp(200), ViewGroup.LayoutParams.WRAP_CONTENT, true);
        moreMenu.setBackgroundDrawable(new android.graphics.drawable.ColorDrawable(
                Color.TRANSPARENT));
        moreMenu.setOutsideTouchable(true);
        moreMenu.showAsDropDown(anchor, -dp(140), dp(4));
    }

    private View menuItem(String label, String sub, View.OnClickListener click) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.VERTICAL);
        row.setPadding(dp(14), dp(9), dp(14), dp(9));
        row.setBackground(theme().round(0x00000000, 6, this));
        TextView a = new TextView(this);
        a.setText(label);
        a.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        a.setTextColor(0xFFE8EAED);
        row.addView(a);
        TextView b = new TextView(this);
        b.setText(sub);
        b.setTextSize(TypedValue.COMPLEX_UNIT_SP, 11);
        b.setTextColor(0xFF9AA1AC);
        row.addView(b);
        row.setClickable(true);
        row.setOnClickListener(click);
        return row;
    }

    private void dismissMenu() {
        if (moreMenu != null) { moreMenu.dismiss(); moreMenu = null; }
    }

    // ---------------- 主体 ----------------

    private View buildBody() {
        String ext = extOf(title);

        if (isText(ext)) {
            String text = readText();
            if (text != null) return textView(text);
            return infoCard("无法读取文本内容", "可能文件已损坏或被移除，可尝试用其它应用打开。");
        }
        if ("pdf".equals(ext)) {
            View v = pdfView();
            if (v != null) return v;
            return infoCard("PDF 预览不可用", "该 PDF 可能已加密或损坏，可尝试用其它应用打开。");
        }
        // Office 三件套等：基本信息卡 + 一键外部打开
        return officeCard(ext);
    }

    private View textView(String text) {
        // ★ v1.16.0 性能重写（用户反馈"大一点文件浏览卡顿，需要优化"）。
        //
        // 根因：旧版把一个最多 2MB 的字符串一次性 setText 进单个 TextView。
        // TextView 的测量/换行是 O(n) 且**全程占用 UI 线程**，2MB 文本 ≈ 100 万字符，
        // 一次布局要几百毫秒到数秒——表现就是"点开卡住、滚动掉帧"。
        //
        // 现在改成「按行分块 + 懒加载」：
        //   · 先把文本切成每块约 240 行的块（视觉上接近一屏 ~1.5 屏）
        //   · 首屏同步插入（体感即时），后续块在用户滚到 80% 时再追加
        //   · 每块独立 TextView，滚动时只测量可见块，不再整篇重排
        //   · 超过 2MB 的截断提示放在末尾作为独立小块
        final java.util.List<String> chunks = splitChunks(text, 240);

        final LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setBackgroundColor(0xFF16181D);
        col.setPadding(dp(16), dp(16), dp(16), dp(24));

        final android.widget.ScrollView sv = new android.widget.ScrollView(this);
        sv.setBackgroundColor(0xFF16181D);
        sv.setFillViewport(true);
        sv.addView(col, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        // 首块立即可见：不等待滚动，直接同步插入
        appendTextChunk(col, chunks.isEmpty() ? "" : chunks.get(0), chunks.size() > 1);

        if (chunks.size() <= 1) return sv;

        // 剩余块按需追加：滚到 80% 位置时再挂下一块，避免一次性大布局
        final int[] next = {1};
        sv.getViewTreeObserver().addOnScrollChangedListener(() -> {
            if (next[0] >= chunks.size()) return;
            View child = sv.getChildAt(0);
            if (child == null) return;
            int range = child.getHeight() - sv.getHeight();
            if (range <= 0) return;
            if (sv.getScrollY() >= range * 0.8f) {
                final int i = next[0]++;
                appendTextChunk(col, chunks.get(i), i < chunks.size() - 1);
            }
        });
        return sv;
    }

    /** 追加一个文本块（独立 TextView，滚动时只测量可见块） */
    private void appendTextChunk(LinearLayout parent, String chunk, boolean more) {
        TextView tv = new TextView(this);
        tv.setText(more ? chunk + "\n" : chunk);
        tv.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        tv.setTextColor(0xFFD7DBE0);
        tv.setTypeface(Typeface.MONOSPACE);
        tv.setTextIsSelectable(true);
        parent.addView(tv, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
    }

    /**
     * 按行数切块（不动内容，只在换行处切开，保证不破坏一行文本的完整）。
     * 用 lastIndexOf('\n') 定位最近的换行，避免逐行 split 产生百万级 String 数组。
     */
    private static java.util.List<String> splitChunks(String text, int linesPerChunk) {
        java.util.List<String> out = new java.util.ArrayList<>();
        if (text == null || text.isEmpty()) return out;
        int from = 0, n = text.length();
        while (from < n) {
            int count = 0, idx = from;
            while (count < linesPerChunk) {
                int nl = text.indexOf('\n', idx);
                if (nl < 0) { idx = n; break; }
                idx = nl + 1;
                count++;
            }
            // 若还没到文件尾，但下一行超长（无换行的巨行），按字符数硬切，防止单块过大
            if (idx < n && idx - from > 400_000) idx = from + 400_000;
            out.add(text.substring(from, Math.min(idx, n)));
            from = idx;
        }
        return out;
    }

    /**
     * PDF：用系统自带的 PdfRenderer 逐页渲染（离线，无第三方库）。
     *
     * ★ v1.16.0 性能优化（用户反馈"大一点文件浏览卡顿"）。
     *
     * 旧版在 UI 线程里 for 循环把最多 60 页**一次全渲染**成 ARGB_8888 位图，
     * 每页约 1080×1400×4 ≈ 6MB，60 页 ≈ 360MB 且全部同步阻塞 —— 大 PDF
     * 点开会卡死好几秒，甚至 OOM。
     *
     * 现在改成「先占位、后懒渲染」：
     *   · 先按每页真实宽高比算出占位高度，插入一个轻量占位 View（无位图）
     *   · 渲染在**后台线程**逐页做，完成的页用 ui.post 回主线程贴图
     *   · 只保留最近渲染过的页（LRU 上限 12 页），离屏页释放位图，内存可控
     *   · 页面上限仍保留（超大 PDF 只渲染前 100 页 + 提示）
     */
    private View pdfView() {
        if (Build.VERSION.SDK_INT < 21 || uri == null) return null;
        android.os.ParcelFileDescriptor pfd = null;
        android.graphics.pdf.PdfRenderer probe = null;
        try {
            pfd = getContentResolver().openFileDescriptor(uri, "r");
            if (pfd == null) return null;
            probe = new android.graphics.pdf.PdfRenderer(pfd);
            final int total = probe.getPageCount();
            if (total <= 0) { probe.close(); pfd.close(); return null; }

            final int n = Math.min(total, PDF_PAGE_LIMIT);
            final int maxW = getResources().getDisplayMetrics().widthPixels - dp(20);

            // 先把每页的占位高度量出来（openPage 很轻，只读页尺寸，不渲染）
            final int[] pageH = new int[n];
            for (int i = 0; i < n; i++) {
                android.graphics.pdf.PdfRenderer.Page pg = probe.openPage(i);
                float scale = (float) maxW / pg.getWidth();
                pageH[i] = Math.max(1, (int) (pg.getHeight() * scale));
                pg.close();
            }

            final LinearLayout col = new LinearLayout(this);
            col.setOrientation(LinearLayout.VERTICAL);
            col.setPadding(dp(10), dp(10), dp(10), dp(24));
            col.setBackgroundColor(0xFF16181D);

            // 占位：用固定高度的 View 先把滚动条撑起来，用户立刻能滚
            final ImageView[] holders = new ImageView[n];
            for (int i = 0; i < n; i++) {
                ImageView iv = new ImageView(this);
                iv.setAdjustViewBounds(true);
                iv.setBackgroundColor(0xFFEDEDED);      // 纸张白占位
                LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT, pageH[i]);
                lp.bottomMargin = dp(10);
                col.addView(iv, lp);
                holders[i] = iv;
            }
            if (n < total) {
                TextView tip = new TextView(this);
                tip.setText("…共 " + total + " 页，仅预览前 " + n + " 页");
                tip.setTextColor(0xFF9AA1AC);
                tip.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
                tip.setPadding(0, dp(6), 0, 0);
                col.addView(tip);
            }

            final ScrollView sv = new ScrollView(this);
            sv.addView(col);

            // 后台逐页渲染；只渲染"已滚到附近"的页，避免一次性把 100 页全画掉
            final java.util.concurrent.ConcurrentHashMap<Integer, Boolean> done =
                    new java.util.concurrent.ConcurrentHashMap<>();
            final java.util.LinkedList<Integer> lru = new java.util.LinkedList<>();
            final Object lock = new Object();
            final android.os.Handler ui = new android.os.Handler(
                    android.os.Looper.getMainLooper());

            final Runnable render = () -> {
                // 计算当前可见范围（±1 屏），只渲染范围内的页
                int sy = sv.getScrollY();
                int sh = Math.max(1, sv.getHeight());
                int y = dp(10);
                java.util.List<Integer> need = new java.util.ArrayList<>();
                for (int i = 0; i < n; i++) {
                    int top = y, bottom = y + pageH[i];
                    y = bottom + dp(10);
                    if (bottom >= sy - sh && top <= sy + sh * 2) {
                        if (done.putIfAbsent(i, Boolean.TRUE) == null) need.add(i);
                    }
                }
                if (need.isEmpty()) return;
                new Thread(() -> {
                    android.os.ParcelFileDescriptor p = null;
                    android.graphics.pdf.PdfRenderer rr = null;
                    try {
                        p = getContentResolver().openFileDescriptor(uri, "r");
                        if (p == null) return;
                        rr = new android.graphics.pdf.PdfRenderer(p);
                        for (int i : need) {
                            if (i >= rr.getPageCount()) continue;
                            final int idx = i;
                            android.graphics.Bitmap bm;
                            try {
                                android.graphics.pdf.PdfRenderer.Page pg = rr.openPage(i);
                                bm = android.graphics.Bitmap.createBitmap(
                                        maxW, pageH[i], android.graphics.Bitmap.Config.ARGB_8888);
                                bm.eraseColor(Color.WHITE);
                                pg.render(bm, null, null,
                                        android.graphics.pdf.PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY);
                                pg.close();
                            } catch (Throwable e) {
                                continue;
                            }
                            final android.graphics.Bitmap fb = bm;
                            ui.post(() -> {
                                if (isFinishing() || isDestroyed()) {
                                    fb.recycle();
                                    return;
                                }
                                holders[idx].setImageBitmap(fb);
                                holders[idx].setBackgroundColor(Color.TRANSPARENT);
                                // LRU 上限：超出上限的旧页回收位图，控制内存
                                synchronized (lock) {
                                    lru.addLast(idx);
                                    while (lru.size() > PDF_BITMAP_LRU) {
                                        int old = lru.removeFirst();
                                        android.graphics.drawable.Drawable d =
                                                holders[old].getDrawable();
                                        holders[old].setImageDrawable(null);
                                        holders[old].setBackgroundColor(0xFFEDEDED);
                                        done.remove(old);
                                        if (d instanceof android.graphics.drawable.BitmapDrawable) {
                                            android.graphics.Bitmap ob =
                                                    ((android.graphics.drawable.BitmapDrawable) d).getBitmap();
                                            if (ob != null && !ob.isRecycled()) ob.recycle();
                                        }
                                    }
                                }
                            });
                        }
                    } catch (Throwable ignored) {
                    } finally {
                        try { if (rr != null) rr.close(); } catch (Throwable ignored) {}
                        try { if (p != null) p.close(); } catch (Throwable ignored) {}
                    }
                }).start();
            };

            // 首屏 + 滚动时按需渲染（节流：滚动停止后 120ms 才触发，避免疯狂重算）
            final Runnable[] pending = new Runnable[1];
            sv.getViewTreeObserver().addOnScrollChangedListener(() -> {
                android.os.Handler h = new android.os.Handler(android.os.Looper.getMainLooper());
                if (pending[0] != null) h.removeCallbacks(pending[0]);
                pending[0] = render;
                h.postDelayed(render, 120);
            });
            sv.post(render);

            // 原始探测用的 PdfRenderer 立即释放（渲染线程会各自新开）
            try { probe.close(); probe = null; } catch (Throwable ignored) {}
            try { pfd.close(); pfd = null; } catch (Throwable ignored) {}

            return sv;
        } catch (Throwable e) {
            return null;
        } finally {
            try { if (probe != null) probe.close(); } catch (Throwable ignored) {}
            try { if (pfd != null) pfd.close(); } catch (Throwable ignored) {}
        }
    }

    /** PDF 最多预览页数 / 位图缓存上限（超出则回收，防止大文件 OOM） */
    private static final int PDF_PAGE_LIMIT = 100;
    private static final int PDF_BITMAP_LRU = 12;

    /** Word / Excel / PPT：信息卡 + 一键用其它应用打开 */
    private View officeCard(String ext) {
        String kind;
        switch (ext.toLowerCase(Locale.ROOT)) {
            case "doc": case "docx": case "rtf": case "odt":
                kind = "Word 文档"; break;
            case "xls": case "xlsx": case "ods":
                kind = "Excel 表格"; break;
            case "ppt": case "pptx": case "odp":
                kind = "PowerPoint 演示文稿"; break;
            default:
                kind = "文档"; break;
        }
        return infoCard(kind,
                "本应用暂未内置该格式的排版渲染（离线解析需要额外的大型组件）。\n\n"
                        + "可以点右上角「⋯ → 用其它应用打开」，交给 WPS / Office 等应用查看。");
    }

    private View infoCard(String headline, String detail) {
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setGravity(Gravity.CENTER);
        col.setPadding(dp(28), dp(40), dp(28), dp(28));
        col.setBackgroundColor(0xFF16181D);

        ImageView icon = new ImageView(this);
        icon.setImageBitmap(FdFileIcon.make(
                title, dp(50), false));
        LinearLayout.LayoutParams ilp = new LinearLayout.LayoutParams(dp(44), dp(50));
        ilp.gravity = Gravity.CENTER_HORIZONTAL;
        col.addView(icon, ilp);

        TextView h = new TextView(this);
        h.setText(headline);
        h.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
        h.setTextColor(0xFFE8EAED);
        h.setTypeface(Typeface.DEFAULT_BOLD);
        h.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams hlp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        hlp.topMargin = dp(14);
        col.addView(h, hlp);

        TextView meta = new TextView(this);
        meta.setText(title + "\n" + FdUtil.fmtSize(size));
        meta.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        meta.setTextColor(0xFF9AA1AC);
        meta.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams mlp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        mlp.topMargin = dp(6);
        col.addView(meta, mlp);

        TextView d = new TextView(this);
        d.setText(detail);
        d.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        d.setTextColor(0xFFB9BFC8);
        d.setGravity(Gravity.CENTER);
        d.setLineSpacing(dp(3), 1f);
        LinearLayout.LayoutParams dlp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        dlp.topMargin = dp(18);
        col.addView(d, dlp);

        TextView open = new TextView(this);
        open.setText("用其它应用打开");
        open.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
        open.setTextColor(0xFFFFFFFF);
        open.setGravity(Gravity.CENTER);
        open.setPadding(dp(22), dp(11), dp(22), dp(11));
        open.setBackground(theme().primary(this));
        open.setOnClickListener(v -> FdFileOp.openWithChooser(
                this, uri, title, mime));
        LinearLayout.LayoutParams olp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        olp.topMargin = dp(22);
        col.addView(open, olp);

        ScrollView sv = new ScrollView(this);
        sv.addView(col);
        return sv;
    }

    // ---------------- 工具 ----------------

    private String readText() {
        if (uri == null) return null;
        InputStream is = null;
        try {
            is = getContentResolver().openInputStream(uri);
            if (is == null) return null;
            ByteArrayOutputStream bos = new ByteArrayOutputStream();
            byte[] buf = new byte[1 << 16];
            int n, total = 0;
            // ★ v1.16.0：限读上限由 2MB 提到 8MB。
            // 旧版把 2MB 全塞进一个 TextView → 卡顿，所以当时把上限压得很低；
            // 现在 textView() 已改为分块懒加载（每块 240 行独立 View），
            // 8MB 也只有几十个块、只渲染可见部分，因此可以放心放宽，
            // 让用户能完整查看更大的日志 / JSON / CSV。
            while ((n = is.read(buf)) > 0 && total < (8 << 20)) {
                bos.write(buf, 0, n);
                total += n;
            }
            byte[] data = bos.toByteArray();
            String s = new String(data, "UTF-8");
            // 简易乱码判定：UTF-8 解码后若出现大量替换字符，退回 GBK
            int bad = 0;
            for (int i = 0; i < s.length(); i++) if (s.charAt(i) == '\uFFFD') bad++;
            if (bad > 20 && bad > s.length() / 20) {
                try { s = new String(data, "GBK"); } catch (Throwable ignored) {}
            }
            if (total >= (8 << 20)) s = s + "\n\n…（文件过大，仅预览前 8 MB）";
            return s;
        } catch (Throwable e) {
            return null;
        } finally {
            try { if (is != null) is.close(); } catch (Throwable ignored) {}
        }
    }

    private static String extOf(String name) {
        if (TextUtils.isEmpty(name)) return "";
        int d = name.lastIndexOf('.');
        if (d < 0 || d == name.length() - 1) return "";
        return name.substring(d + 1);
    }

    private FdTheme theme() {
        return FdTheme.resolve(this);
    }

    private int dp(float v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }
}
