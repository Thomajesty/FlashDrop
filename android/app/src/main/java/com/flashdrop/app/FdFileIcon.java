package com.flashdrop.app;

import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.DashPathEffect;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.text.TextUtils;

import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 文件类型图标（v1.16.0）—— 严格复刻微信文件卡片图标。
 *
 * ── 形状（本版核心变更）────────────────────────────────────────
 * 前两版都画错了：
 *   v1.14.0「圆角纸张 + 右上折角」→ 被反馈"不要方的"（因为画得太大太方）
 *   v1.15.0「矩形 + 右下切角」    → 仍不对，微信根本不是缺角造型
 *
 * 本轮拿到 Clear 的微信「文件传输助手」截图（1440x3088，密度 2.2x）后
 * 逐像素比对，确认真实造型是：
 *
 *      ┌──────────┐
 *      │          ╲      ← 右上角被切掉一个直角三角（折角）
 *      │   PDF     │
 *      │           │
 *      └───────────┘      ← 整体小圆角
 *
 *   ① 主体 = 圆角矩形（圆角 ≈ 宽度的 12%）
 *   ② **右上角**切掉一个直角三角，切口边长 ≈ 宽度的 38%
 *   ③ 折角区域用略亮的同色系填充，形成"纸张被折起"的层次
 *   ④ 图标中央一个白色粗体格式文案（PDF / DOC / XLS …）
 *
 *   注意方向：是**右上**折角，不是右下缺角。
 *
 * ── 未下载 / 已下载 的区分（也是本轮修正）──────────────────────
 * 微信的做法**不是把图标变半透明**，而是：
 *   · 已下载 → 实色填充 + 白色文字
 *   · 未下载 → **同色系的虚线描边**（不填充本体，只留深色底）
 *              文字仍为实色，整体观感是"虚线的空心图标"
 * 所以本版把 dimmed 参数实现为「描边模式」，彻底替换掉旧的 alpha 虚化。
 *
 * 全部 Canvas 现画，不依赖 drawable 资源，双端共用同一套规则。
 */
public final class FdFileIcon {

    private FdFileIcon() {}

    /** 设计基准：宽 40 / 高 52（宽高比 ≈ 0.77，实测微信比例） */
    private static final float DW = 40f;
    private static final float DH = 52f;
    /** 圆角半径（占宽度 12%） */
    private static final float RADIUS = 4.8f;
    /** 右上折角边长（占宽度 38%） */
    private static final float FOLD = 15.2f;
    /** 虚线描边线宽 */
    private static final float STROKE = 2.6f;

    /**
     * ★ v1.17.0：图标 Bitmap 缓存。
     *
     * key = 扩展名 + '|' + 像素高 + '|' + 虚线态(0/1)
     * 图标只由这三者决定（与具体文件名无关），因此全应用组合数极少，
     * 一次进程生命周期内命中率接近 100%，彻底消除"每次进入都重新构建"。
     * 用 ConcurrentHashMap 是因为 ListView 的 getView 虽在主线程，
     * 但预览/分享等路径可能从子线程取图标，避免并发 put 破坏结构。
     */
    private static final ConcurrentHashMap<String, Bitmap> CACHE =
            new ConcurrentHashMap<>();

    /** 分类 → (主色, 文案)。用 LinkedHashMap 保证遍历顺序稳定 */
    private static final Map<String, String[]> EXT_MAP = new LinkedHashMap<>();
    private static final String[] FALLBACK = {"#6D7588", "?"};

    static {
        put("#E8453C", "PDF", "pdf");
        put("#2B579A", "DOC", "doc", "docx", "rtf", "odt", "wps");
        put("#217346", "XLS", "xls", "xlsx", "csv", "ods", "et");
        put("#D24726", "PPT", "ppt", "pptx", "odp", "dps");
        put("#5B6B8C", "TXT", "txt", "log", "md", "ini", "conf", "json",
                "xml", "yml", "yaml", "bat", "sh", "java", "py", "js",
                "html", "css", "c", "cpp", "h");
        put("#0E9F6E", "IMG", "jpg", "jpeg", "png", "gif", "bmp", "webp",
                "heic", "heif", "tif", "tiff", "svg", "ico");
        put("#7C3AED", "MEDIA", "mp4", "mkv", "avi", "mov", "wmv", "flv",
                "webm", "mp3", "wav", "flac", "aac", "m4a", "ogg", "ape");
        put("#B45309", "ZIP", "zip", "rar", "7z", "tar", "gz", "bz2", "xz");
        // ★ v1.16.0：安装包单独分类。用户实测反馈"apk 也标注的 exe 图标" ——
        // 旧版把 apk / exe 混在同一类里统一标 EXE，安卓端看着就不对。
        // 现在 apk 用安卓绿 + "APK"，exe / msi 才用 "EXE"。
        put("#3DDC84", "APK", "apk");
        put("#0F6FCB", "EXE", "exe", "msi", "bat", "cmd");
        put("#6D28D9", "FONT", "ttf", "otf", "woff", "woff2");
        put("#0F766E", "DB", "db", "sqlite", "sql", "mdb");
        put("#475569", "ISO", "iso", "img", "vhd", "vmdk");
    }

    private static void put(String color, String label, String... exts) {
        for (String e : exts) EXT_MAP.put(e, new String[]{color, label});
    }

    /** 取扩展名分类；返回 {颜色, 文案}，未识别返回 FALLBACK 副本 */
    public static String[] classify(String fileName) {
        return classifyExt(extOf(fileName));
    }

    /** 直接按**扩展名**分类（内部缓存路径用，省去重复解析文件名） */
    private static String[] classifyExt(String ext) {
        if (TextUtils.isEmpty(ext)) return FALLBACK.clone();
        String[] v = EXT_MAP.get(ext);
        return v == null ? FALLBACK.clone() : new String[]{v[0], v[1]};
    }

    /** 清空图标缓存（内存吃紧或主题/密度变化时可按需调用） */
    public static void clearCache() {
        CACHE.clear();
        PLACEHOLDER = null;
        PLACEHOLDER_H = 0;
    }

    /**
     * 惰性单例的**占位图标**（v1.18.0）。
     *
     * ★ 为什么必须有一张"本进程常量位图"：
     *
     * 用户反馈「安卓页面收到的文件还是短暂出现了文件卡片的错乱」。
     * 上一版（v1.17.0）已经加了 Bitmap 缓存 + "变了才写"短路，但**首帧**
     * 依然错乱，因为问题不在"画得慢"，而在 **ImageView 初始没有 drawable**。
     *
     * 复现链路（ListView 的 measure 早于任何 getView）：
     *   1. 布局里 `msg_typeicon` 是 `layout_width=40dp / height=52dp` 的固定尺寸，
     *      但 **没有 android:src**，也没有 background；
     *   2. `ListView.onMeasure()` 会先按 **当前缓存里的 convertView** 做一次测量。
     *      若缓存为空（刚进页面 / 刚切换设备会话，stub view 会被丢弃重建），
     *      这个 "scrap view" 里的 ImageView 是 **零 drawable** 状态；
     *   3. 零 drawable 的 ImageView，即使写了固定 layout_width/height，
     *      在 `wrap_content` 的父链（bubble 是 wrap_content）里参与测量时
     *      期望尺寸为 0 → 布局阶段整张卡片**先按"没有图标"排一次**；
     *   4. 紧接着 getView 返回真实 drawable，卡片被迫重排 → 一帧的
     *      错位/塌陷被用户看到，就是"短暂错乱"。
     *
     * 修法：把一张**最小透明占位位图**在布局膨胀阶段就塞进 ImageView
     * （见 MainActivity.getView 的 inflate 分支）。有了它，ImageView 在
     * 第一次测量时就有确定的 40x52 固有尺寸，卡片首帧即最终形态。
     *
     * 之所以用"透明"而不是"灰色方块"：真实位图通常在同一帧内跟进，
     * 中间态不可见；万一慢一帧，也只会看到空白而不是突兀的色块。
     */
    private static volatile Bitmap PLACEHOLDER;
    private static volatile int PLACEHOLDER_H;

    public static Bitmap placeholder(int heightPx) {
        if (heightPx < 8) heightPx = 8;
        Bitmap p = PLACEHOLDER;
        if (p != null && !p.isRecycled() && PLACEHOLDER_H == heightPx) return p;
        Bitmap bm = Bitmap.createBitmap(widthFor(heightPx), heightPx,
                Bitmap.Config.ARGB_8888);
        bm.eraseColor(Color.TRANSPARENT);
        PLACEHOLDER = bm;
        PLACEHOLDER_H = heightPx;
        return bm;
    }

    public static String extOf(String fileName) {
        if (TextUtils.isEmpty(fileName)) return "";
        int dot = fileName.lastIndexOf('.');
        if (dot < 0 || dot == fileName.length() - 1) return "";
        String e = fileName.substring(dot + 1).toLowerCase(Locale.ROOT);
        // 只接受纯字母数字扩展名（避免 "file.1"、"v1.2.3" 之类误判）
        for (int i = 0; i < e.length(); i++) {
            char c = e.charAt(i);
            if (!(c >= 'a' && c <= 'z') && !(c >= '0' && c <= '9')) return "";
        }
        return e.length() > 8 ? "" : e;
    }

    /** 图标推荐宽度（px）—— 调用方按 DW:DH 比例给 ImageView 设尺寸 */
    public static int widthFor(int heightPx) {
        return Math.max(8, Math.round(heightPx * DW / DH));
    }

    /**
     * 绘制文件图标。
     *
     * ★ v1.17.0：**加 Bitmap 缓存**。
     *
     * 为什么必须缓存（用户反馈"最开始适配度不足，过一会才能正常，
     * 而且显示不稳定、时不时会错乱，每次进去都会重新构建一样"）：
     *   ListView 每次 `getView` 都会调 `make()` 画一张新的 Bitmap。
     *   一屏文件卡片十几张、每张都要 createBitmap + Canvas 绘制路径 + 文字，
     *   滚动/回滚/切换设备会话时反复全量重画 —— 首帧来不及，就出现
     *   "过一会才正常"；而在 convertView 复用的瞬间旧图已被回收、
     *   新图尚未画完，于是出现"错乱"。
     *   实际上图标只取决于 (扩展名, 像素高, 是否虚线) 三元组，
     *   全应用最多十几种组合，缓存命中率接近 100%。
     *
     * @param name   文件名（用于取扩展名）
     * @param height 图标高度 px（宽度自动按 DW:DH 比例得出）
     * @param dimmed true = 未下载态，画成**虚线描边**（微信做法）
     */
    public static Bitmap make(String name, int height, boolean dimmed) {
        if (height < 8) height = 8;
        String ext = extOf(name);
        // 缓存 key：扩展名 + 高度 + 虚线态。不含原始文件名 ——
        // 同一扩展名图标完全一致，这样才能真正复用。
        String key = (ext.isEmpty() ? "?" : ext) + '|' + height + '|' + (dimmed ? 1 : 0);
        Bitmap hit = CACHE.get(key);
        if (hit != null && !hit.isRecycled()) return hit;
        Bitmap bm = draw(ext, height, dimmed);
        // ★ v1.18.0：用 putIfAbsent —— 并发（如后台线程+主线程同时首绘）
        // 时只保留先写入的那张，避免后写者覆盖掉已被 ImageView 持有的位图
        // 造成"某张卡片图标忽然变空白"。
        Bitmap prev = CACHE.putIfAbsent(key, bm);
        return prev != null && !prev.isRecycled() ? prev : bm;
    }

    /** 真正的绘制（不做缓存判断），仅供 make() 内部调用 */
    private static Bitmap draw(String ext, int height, boolean dimmed) {
        int w = widthFor(height);
        Bitmap bm = Bitmap.createBitmap(w, height, Bitmap.Config.ARGB_8888);
        Canvas c = new Canvas(bm);
        float k = height / DH;
        c.scale(k, k);

        String[] cls = classifyExt(ext);
        int base = Color.parseColor(cls[0]);
        String label = cls[1];

        Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
        p.setStyle(Paint.Style.FILL);

        // ---------- 主体路径：圆角矩形，右上角切掉直角三角 ----------
        // 顺时针：左上 → 右上折角起点 → 折角斜边 → 右下 → 左下
        Path body = new Path();
        body.moveTo(RADIUS, 0f);
        body.lineTo(DW - FOLD, 0f);                 // 上边到折角处
        body.lineTo(DW, FOLD);                      // 折角斜边
        body.lineTo(DW, DH - RADIUS);               // 右边
        body.quadTo(DW, DH, DW - RADIUS, DH);       // 右下圆角
        body.lineTo(RADIUS, DH);                    // 下边
        body.quadTo(0f, DH, 0f, DH - RADIUS);       // 左下圆角
        body.lineTo(0f, RADIUS);                    // 左边
        body.quadTo(0f, 0f, RADIUS, 0f);            // 左上圆角
        body.close();

        // ---------- 折角小三角（比主体略亮，形成"纸张折起"层次）----------
        Path foldTri = new Path();
        foldTri.moveTo(DW - FOLD, 0f);
        foldTri.lineTo(DW, FOLD);
        foldTri.lineTo(DW - FOLD, FOLD);
        foldTri.close();

        if (dimmed) {
            // ★ 未下载态：微信画的是**虚线描边**，不是半透明实心。
            // 主体不填色（留出底色），用同色系虚线勾出轮廓 + 折角。
            Paint stroke = new Paint(Paint.ANTI_ALIAS_FLAG);
            stroke.setStyle(Paint.Style.STROKE);
            stroke.setColor(base);
            stroke.setStrokeWidth(STROKE);
            stroke.setStrokeCap(Paint.Cap.ROUND);
            // 虚线段 ≈ 4.5，间隔 ≈ 2.6（实测微信的疏密）
            stroke.setPathEffect(new DashPathEffect(
                    new float[]{4.5f, 2.6f}, 0f));
            c.drawPath(body, stroke);
            // 折角也用虚线勾一下，保持整体一致
            c.drawLine(DW - FOLD, 0f, DW, FOLD, stroke);
        } else {
            p.setColor(base);
            c.drawPath(body, p);
            p.setColor(lighter(base, 1.45f));
            c.drawPath(foldTri, p);
        }

        // ---------- 文案：居中偏下（避开右上折角）----------
        int textColor = dimmed ? base : 0xFFFFFFFF;
        p.setColor(textColor);
        p.setTypeface(Typeface.create(Typeface.DEFAULT, Typeface.BOLD));
        p.setTextAlign(Paint.Align.CENTER);
        float cx = DW / 2f;
        float cyc = DH / 2f + 3f;      // 视觉中心略下移（上方被折角占了）
        if ("?".equals(label)) {
            p.setTextSize(22f);
        } else if (label.length() >= 5) {
            p.setTextSize(9f);
        } else if (label.length() == 4) {
            p.setTextSize(10.5f);
        } else if (label.length() == 3) {
            p.setTextSize(12.5f);
        } else {
            p.setTextSize(15f);
        }
        Paint.FontMetrics fm = p.getFontMetrics();
        c.drawText(label, cx, cyc - (fm.ascent + fm.descent) / 2f, p);

        return bm;
    }

    /** 按比例调亮（f>1 变亮），保持 alpha */
    private static int lighter(int color, float f) {
        int r = Math.min(255, (int) (((color >> 16) & 0xFF) * f));
        int g = Math.min(255, (int) (((color >> 8) & 0xFF) * f));
        int b = Math.min(255, (int) ((color & 0xFF) * f));
        return 0xFF000000 | (r << 16) | (g << 8) | b;
    }
}
