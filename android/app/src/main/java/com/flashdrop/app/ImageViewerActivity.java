package com.flashdrop.app;

import android.animation.Animator;
import android.animation.AnimatorListenerAdapter;
import android.animation.ValueAnimator;
import android.app.Activity;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Matrix;
import android.graphics.RectF;
import android.graphics.drawable.BitmapDrawable;
import android.graphics.drawable.Drawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.text.TextUtils;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.ScaleGestureDetector;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.util.ArrayList;
import java.util.List;

/**
 * v1.11.0 图片全屏预览器（参照微信图片查看器交互）。
 *
 * 解决用户的三个问题：
 *   1. **不能放大预览** → 双指捏合缩放（1x~5x）、放大后双指拖动、双击放大/还原、
 *      缩放时以双指中心为锚点（微信同款手感）。
 *   2. **底部保存/转发按钮布局不好看** → 重做为**等宽等高的卡片按钮**，
 *      用 weight 均分 + 固定高度 + 统一间距 + 底部安全区，
 *      图标在上、文字在下（微信同款竖排），不再是"图标+文字横向拼贴"。
 *   3. **不能长按保存/删除** → 加**长按浮层菜单**（保存到相册 / 转发 / 删除），
 *      同时在聊天列表里长按图片气泡也能唤出。
 *
 * 另外补上进入/退出动效：淡入 + 轻微缩放进入，拖动下拉关闭（跟手），底部栏依次上滑。
 */
public class ImageViewerActivity extends Activity {

    /** 缩放上下限 */
    private static final float MIN_SCALE = 1.0f;
    private static final float MAX_SCALE = 5.0f;
    /** 判定为"下拉关闭"的位移阈值（px） */
    private static final float DISMISS_DISTANCE = 160f;
    /** 判定为"下拉关闭"的速度阈值（px/ms） */
    private static final float DISMISS_VELOCITY = 0.6f;

    private final List<MainActivity.Msg> images = new ArrayList<>();
    private int index = 0;

    private FrameLayout root;
    private ImageView iv;
    private View topBar;
    private View bottomBar;
    private TextView titleView;
    private TextView pageView;
    private LinearLayout bottomRow;

    /** 缩放状态 */
    private float scale = 1f;
    private float baseScale = 1f;   // fit 时的基准缩放（相对图片原始像素）
    private float transX = 0f, transY = 0f;
    private final Matrix matrix = new Matrix();
    private final float[] vals = new float[9];

    private ScaleGestureDetector scaleDetector;
    /** 手势状态 */
    private float downX, downY, lastX, lastY;
    private boolean dragging = false;
    private boolean doubleTapPending = false;
    private long lastTapTime = 0;
    private int activePointerId = -1;
    /** 长按检测（见 attachGestures）：自己打计时器，因为 onTouchListener 吃掉了全部事件 */
    private final android.os.Handler handler =
            new android.os.Handler(android.os.Looper.getMainLooper());
    private boolean pendingLongPress = false;
    private final Runnable longPressRunnable = () -> {
        if (pendingLongPress) {
            pendingLongPress = false;
            // 加触觉反馈（部分机型无震动器，静默失败）。
            // 注意：performHapticFeedback 是 View 的方法，Activity 没有 —— 传根视图。
            try {
                if (root != null) {
                    root.performHapticFeedback(android.view.HapticFeedbackConstants.LONG_PRESS);
                }
            } catch (Throwable ignored) {}
            onLongPressImage();
        }
    };

    private void cancelLongPress() {
        pendingLongPress = false;
        try { handler.removeCallbacks(longPressRunnable); } catch (Throwable ignored) {}
    }

    @Override protected void onDestroy() {
        cancelLongPress();
        super.onDestroy();
    }

    /** 图片来源（本地 uri / 绝对路径 / 缓存文件），异步解码后填充 */
    private final List<String> srcs = new ArrayList<>();
    private final List<String> names = new ArrayList<>();
    private final List<String> mimes = new ArrayList<>();
    private final List<Bitmap> bitmaps = new ArrayList<>();
    private MainActivity.Msg cur;

    public static void start(Activity from, java.util.List<MainActivity.Msg> all, int at) {
        if (from == null || all == null || all.isEmpty()) return;
        at = Math.max(0, Math.min(at, all.size() - 1));
        Intent it = new Intent(from, ImageViewerActivity.class);
        // v1.11.0：传**真实 Msg 对象**而不是 srcs/names/mimes 三组字符串。
        // 原因：删除功能需要 keyOf(m)（ts|mid|dir|kind）才能让主界面同步摘掉记录，
        //      还需要 m.path / m.open 才能精准删这一张 —— 只给字符串做不到，
        //      早前版本退化成"按设备删整个文件夹"，会把同设备其它图片一起删掉。
        it.putExtra("msgs", new ArrayList<MainActivity.Msg>(all));
        it.putExtra("index", at);
        // 用 ForResult：删除后要把 key 回传给主界面同步清记录
        if (from instanceof MainActivity) from.startActivityForResult(it, MainActivity.REQ_VIEWER);
        else from.startActivity(it);
        // 与微信一致：图片全屏页不缩放，避免系统自动做页面缩放动画干扰自定义转场
        if (from instanceof MainActivity) from.overridePendingTransition(0, 0);
    }

    /** 取一张图片的可读来源：content uri 优先，其次文件绝对路径 */
    static String imageSrcOf(MainActivity.Msg m) {
        if (m == null) return "";
        if (!TextUtils.isEmpty(m.open)) return m.open;
        if (!TextUtils.isEmpty(m.src)) return m.src;
        if (!TextUtils.isEmpty(m.path) && new File(m.path).isAbsolute()) return m.path;
        return "";
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        requestWindowFeature(Window.FEATURE_NO_TITLE);
        Window w = getWindow();
        if (w != null) {
            w.setBackgroundDrawable(new android.graphics.drawable.ColorDrawable(0xFF000000));
            w.addFlags(WindowManager.LayoutParams.FLAG_TRANSLUCENT_NAVIGATION);
        }

        // 反序列化真实消息列表（Activity 被系统回收重建时也走这条路）
        ArrayList<MainActivity.Msg> got =
                (ArrayList<MainActivity.Msg>) getIntent().getSerializableExtra("msgs");
        if (got != null) images.addAll(got);
        // 过滤掉没有可读来源的条目，避免出现空白页
        for (MainActivity.Msg x : images) {
            srcs.add(imageSrcOf(x));
            names.add(x.file == null ? "" : x.file);
            mimes.add(x.mime == null ? "" : x.mime);
        }
        while (!images.isEmpty() && TextUtils.isEmpty(srcs.get(0))) {
            images.remove(0); srcs.remove(0); names.remove(0); mimes.remove(0);
        }
        if (images.isEmpty()) {           // 一张都读不到，直接关掉，不要停在黑屏
            finish();
            return;
        }
        index = Math.max(0, Math.min(getIntent().getIntExtra("index", 0),
                Math.max(0, srcs.size() - 1)));

        buildUi();
        showIndex(index, true);
    }

    // ==================== 界面 ====================

    private int dp(float v) { return FdUtil.dp(this, v); }

    private void buildUi() {
        root = new FrameLayout(this);
        root.setBackgroundColor(0xFF000000);

        // ---- 图片层 ----
        iv = new ImageView(this);
        iv.setScaleType(ImageView.ScaleType.MATRIX);
        FrameLayout.LayoutParams ilp = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT);
        root.addView(iv, ilp);
        iv.setOnClickListener(v -> onSingleTap());
        attachGestures();

        // ---- 顶部栏：返回 + 标题 + 计数 ----
        topBar = buildTopBar();
        root.addView(topBar);

        // ---- 底部栏：保存 / 转发（等宽卡片，严格对齐）----
        bottomBar = buildBottomBar();
        root.addView(bottomBar);

        setContentView(root);

        // 进入动效：整层淡入 + 图片轻微放大落位（微信同款）
        if (FdAnim.on(this)) {
            root.setAlpha(0f);
            iv.setScaleX(0.94f);
            iv.setScaleY(0.94f);
            root.animate().alpha(1f).setDuration(FdAnim.DURATION_ENTER)
                    .setInterpolator(FdAnim.CURVE_DECELERATE).start();
            iv.animate().scaleX(1f).scaleY(1f).setDuration(FdAnim.DURATION_ENTER)
                    .setInterpolator(FdAnim.CURVE_DECELERATE).start();
            FdAnim.slideInFromTop(topBar);
            FdAnim.slideInFromBottom(bottomBar);
        }
    }

    private View buildTopBar() {
        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setPadding(dp(6), dp(8), dp(12), dp(8));
        bar.setBackgroundColor(0x66000000);

        // 返回
        ImageView back = new ImageView(this);
        back.setImageResource(R.drawable.ic_collapse);
        back.setPadding(dp(9), dp(9), dp(9), dp(9));
        back.setOnClickListener(v -> closeWithAnim());
        bar.addView(back, new LinearLayout.LayoutParams(dp(42), dp(42)));

        // 标题（文件名 + 大小），单行省略，不换行 —— 避免长文件名把布局撑乱
        titleView = new TextView(this);
        titleView.setTextColor(0xFFFFFFFF);
        titleView.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        titleView.setSingleLine(true);
        titleView.setEllipsize(android.text.TextUtils.TruncateAt.MIDDLE);
        LinearLayout.LayoutParams tlp = new LinearLayout.LayoutParams(0,
                ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        tlp.leftMargin = dp(4);
        bar.addView(titleView, tlp);

        // 计数 "3/12"（仅多图时显示）
        pageView = new TextView(this);
        pageView.setTextColor(0xB3FFFFFF);
        pageView.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        pageView.setVisibility(View.GONE);
        bar.addView(pageView);

        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(58));
        lp.gravity = Gravity.TOP;
        return wrap(bar, lp);
    }

    /**
     * 底部操作栏：**这是用户点名要重做的部分**。
     *
     * 之前的问题：两个按钮用 WRAP_CONTENT 横向拼贴（图标 + 文字各一个 View），
     * 按钮大小随文字长度变化 → 两边不对称、间距不均、整体不居中。
     *
     * 现在的做法（微信同款）：
     *   - 外层固定高度 + 底部安全区（适配手势条/虚拟键）
     *   - 内层用 weight=1 均分，每个按钮是一个**竖排卡片**（图标在上、文字在下）
     *   - 卡片圆角、背景色统一，两个按钮宽度**严格相等**
     */
    private View buildBottomBar() {
        LinearLayout outer = new LinearLayout(this);
        outer.setOrientation(LinearLayout.VERTICAL);
        outer.setBackgroundColor(0x99000000);
        // 底部内边距留出手势条空间，避免被系统虚拟键压住
        outer.setPadding(dp(16), dp(10), dp(16), dp(12) + safeBottom());

        bottomRow = new LinearLayout(this);
        bottomRow.setOrientation(LinearLayout.HORIZONTAL);
        bottomRow.setGravity(Gravity.CENTER);
        outer.addView(bottomRow, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(60)));

        bottomRow.addView(actionCard(R.drawable.ic_save_down, "保存到相册", v -> onSave()));
        bottomRow.addView(actionCard(R.drawable.ic_share, "转发", v -> onShare()));

        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.gravity = Gravity.BOTTOM;
        // ★ v1.13.0 修复：这里必须把 lp 应用到 outer 再返回。
        // 旧代码直接 `return outer;`，lp 创建后被丢弃 → gravity=BOTTOM 从未生效，
        // outer 用默认 LayoutParams（gravity=TOP|LEFT）加到 FrameLayout 上，
        // 结果底栏被塞到图片层左上角、高度塌成 wrap_content，
        // 用户看到的就是"保存/转发按钮根本不在底部（甚至看不见）"。
        return wrap(outer, lp);
    }

    /** 底部导航栏/手势条高度（px），用于避让 */
    private int safeBottom() {
        try {
            int id = getResources().getIdentifier("navigation_bar_height", "dimen", "android");
            if (id > 0) return getResources().getDimensionPixelSize(id);
        } catch (Throwable ignored) {}
        return dp(8);
    }

    /**
     * 一个竖排操作卡片：图标在上、文字在下。
     * weight 由调用方给，保证多个按钮**等宽**。
     */
    private View actionCard(int iconRes, String label, View.OnClickListener onClick) {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setGravity(Gravity.CENTER);
        card.setBackground(theme().round(0x22FFFFFF, 12, this));
        card.setClickable(true);
        card.setFocusable(true);
        // 按下反馈：缩放 + 高亮
        card.setOnTouchListener((v, e) -> {
            if (e.getActionMasked() == MotionEvent.ACTION_DOWN) {
                FdAnim.pressDown(card);
                v.setBackground(theme().round(0x33FFFFFF, 12, this));
            } else if (e.getActionMasked() == MotionEvent.ACTION_UP
                    || e.getActionMasked() == MotionEvent.ACTION_CANCEL) {
                FdAnim.pressUp(card);
                v.setBackground(theme().round(0x22FFFFFF, 12, this));
            }
            return false;
        });
        card.setOnClickListener(onClick);
        // 长按卡片 = 同样的操作（微信里长按和点击同效），这里保持一致
        card.setOnLongClickListener(v -> { onClick.onClick(v); return true; });

        ImageView ic = new ImageView(this);
        ic.setImageResource(iconRes);
        ic.setColorFilter(0xFFFFFFFF);
        card.addView(ic, new LinearLayout.LayoutParams(dp(24), dp(24)));

        TextView tx = new TextView(this);
        tx.setText(label);
        tx.setTextColor(0xE6FFFFFF);
        tx.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        tx.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams tlp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        tlp.topMargin = dp(5);
        card.addView(tx, tlp);

        LinearLayout.LayoutParams clp = new LinearLayout.LayoutParams(0,
                ViewGroup.LayoutParams.MATCH_PARENT, 1f);
        // 两个卡片之间留 12dp 间距：给第一个加右边距即可，避免多卡片时重复加
        if (bottomRow.getChildCount() > 0) clp.leftMargin = dp(12);
        card.setLayoutParams(clp);
        return card;
    }

    private FdTheme theme() {
        return FdTheme.resolve(this);
    }

    private View wrap(View v, FrameLayout.LayoutParams lp) {
        v.setLayoutParams(lp);
        return v;
    }

    // ==================== 图片加载与矩阵 ====================

    private void showIndex(int i, boolean first) {
        index = i;
        resetMatrix();
        cur = null;
        iv.setImageDrawable(null);

        String src = index < srcs.size() ? srcs.get(index) : "";
        String name = index < names.size() ? names.get(index) : "";
        String mime = index < mimes.size() ? mimes.get(index) : "";

        titleView.setText(TextUtils.isEmpty(name) ? "图片" : name);
        boolean multi = srcs.size() > 1;
        pageView.setVisibility(multi ? View.VISIBLE : View.GONE);
        pageView.setText((index + 1) + " / " + srcs.size());

        if (bitmaps.size() > index && bitmaps.get(index) != null) {
            applyBitmap(bitmaps.get(index), name, mime);
            return;
        }
        // ★ v1.13.0：占位图不再用 loadThumb（那是按 inSampleSize=8 给聊天列表用的
        // 小图，1440x3088 的截图只有 180x386，占位必然糊且一旦高清图加载失败就永远糊）。
        // 改为按"屏幕适配"采样解码一张过渡图：清晰度够、解码也快。
        if (!TextUtils.isEmpty(src)) {
            Bitmap placeholder = decodeForScreen(src);
            if (placeholder != null) applyBitmap(placeholder, name, mime);
        }
        final int at = index;
        new Thread(() -> {
            Bitmap bm = decode(src, 4096);
            runOnUiThread(() -> {
                if (at != index) return;      // 已经滑走了，丢弃
                while (bitmaps.size() <= at) bitmaps.add(null);
                bitmaps.set(at, bm);
                if (bm != null && at == index) applyBitmap(bm, name, mime);
            });
        }).start();
    }

    /**
     * v1.13.0：按屏幕尺寸采样解码一张"过渡图"，作为全屏查看器的占位。
     * 与 decode(src, 4096) 的区别：采样上限取屏幕长边（约 2400px），
     * 大图解码更快，且不会出现"占位是 1/8 缩略图、糊得看不清"的问题。
     */
    private Bitmap decodeForScreen(String src) {
        try {
            if (TextUtils.isEmpty(src)) return null;
            float[] vs = viewSize();
            int target = (int) Math.max(vs[0], vs[1]);
            if (target <= 0) target = 1080;
            return decode(src, Math.max(target, 1080));
        } catch (Throwable ignored) {
            return null;
        }
    }

    private void applyBitmap(Bitmap bm, String name, String mime) {
        if (bm == null) return;
        // v1.11.0：用列表里的**真实 Msg**，删除时才能拿到 keyOf(m) / m.path / m.open
        cur = index < images.size() ? images.get(index) : null;
        if (cur == null) {
            cur = new MainActivity.Msg();
            cur.file = name; cur.mime = mime; cur.path = srcs.get(index);
        }
        iv.setImageBitmap(bm);
        // 记录图片原始尺寸：用户要"能放大"，必须知道原始分辨率才能算最大缩放
        fitToScreen(bm.getWidth(), bm.getHeight());
        // onCreate 阶段 root 还没 layout（width=0），居中量按屏幕算的；
        // layout 完成后重算一次，保证首帧就严格居中
        if (root.getWidth() == 0) {
            root.post(() -> {
                int[] sz = curSize();
                if (sz[0] > 0) fitToScreen(sz[0], sz[1]);
            });
        }
    }

    /** 计算 fit 到屏幕的基准缩放并应用 */
    private void fitToScreen(int bw, int bh) {
        if (bw <= 0 || bh <= 0) { baseScale = 1f; }
        else {
            float[] vs = viewSize();
            baseScale = Math.min(vs[0] / bw, vs[1] / bh);
            // ★ v1.13.0 修复：不再把 baseScale 封顶到 1.0。
            // 旧代码 `if (baseScale > 1f) baseScale = 1f;`（"别把小图放成马赛克"）
            // 听上去合理，实际是用户看到的"截图打开还是小的"的元凶：
            //   showIndex 会先用 loadThumb(inSampleSize=8) 的缩略图占位，
            //   1440x3088 的截图 → 180x386，baseScale = 6.0 → 被砍成 1.0
            //   → 图片按原始 180x386 显示，只占屏 16.7%（与用户截图完全一致）。
            // 图片查看器的职责是"尽量铺满可视区"，放大模糊远好于小得看不清；
            // 用户仍可捏合缩小回 1.0 倍看原始像素。
        }
        scale = 1f; transX = 0f; transY = 0f;
        applyMatrix(bw, bh);
    }

    /** 视图尺寸（root 未 layout 时退回屏幕尺寸） */
    private float[] viewSize() {
        if (root.getWidth() > 0 && root.getHeight() > 0)
            return new float[]{root.getWidth(), root.getHeight()};
        return new float[]{getResources().getDisplayMetrics().widthPixels,
                getResources().getDisplayMetrics().heightPixels};
    }

    /** v1.12.0：图片在当前缩放下的居中偏移量。
     *  ★ 修复"图片显示不正确"：旧 applyMatrix 缩放后没有居中平移，图片左上角
     *  钉在 (0,0)，竖长图显示在屏幕上半部、下半黑（用户实测现象）。
     *  transX/transY 保持「相对居中偏移」语义，clampTrans 无需改动。 */
    private float[] centerOffset(int bw, int bh, float s) {
        float[] vs = viewSize();
        return new float[]{(vs[0] - bw * s) / 2f, (vs[1] - bh * s) / 2f};
    }

    private void applyMatrix(int bw, int bh) {
        if (bw <= 0 || bh <= 0) { iv.setImageMatrix(matrix); return; }
        float s = baseScale * scale;
        float[] c = centerOffset(bw, bh, s);
        matrix.reset();
        matrix.postScale(s, s);
        matrix.postTranslate(c[0] + transX, c[1] + transY);
        iv.setImageMatrix(matrix);
    }

    private void resetMatrix() {
        scale = 1f; transX = 0f; transY = 0f;
        matrix.reset();
        if (iv != null) iv.setImageMatrix(matrix);
    }

    /** 当前显示图的实际像素尺寸 */
    private int[] curSize() {
        Drawable d = iv.getDrawable();
        if (d instanceof BitmapDrawable) {
            Bitmap b = ((BitmapDrawable) d).getBitmap();
            return new int[]{b.getWidth(), b.getHeight()};
        }
        return new int[]{0, 0};
    }

    // ==================== 手势：缩放 / 拖动 / 双击 / 下拉关闭 ====================

    private void attachGestures() {
        scaleDetector = new ScaleGestureDetector(this,
                new ScaleGestureDetector.SimpleOnScaleGestureListener() {
                    @Override public boolean onScale(ScaleGestureDetector det) {
                        float f = det.getScaleFactor();
                        float ns = clampScale(scale * f);
                        // 以双指中心为锚点缩放手感（微信同款）：
                        // 锚点在缩放前后应保持不动（公式含居中偏移项）
                        float fx = det.getFocusX(), fy = det.getFocusY();
                        int[] sz = curSize();
                        float k = ns / Math.max(scale, 0.0001f);
                        float[] co = centerOffset(sz[0], sz[1], baseScale * scale);
                        float[] cn = centerOffset(sz[0], sz[1], baseScale * ns);
                        transX = fx - cn[0] - (fx - co[0] - transX) * k;
                        transY = fy - cn[1] - (fy - co[1] - transY) * k;
                        scale = ns;
                        clampTrans();
                        applyMatrix(sz[0], sz[1]);
                        return true;
                    }
                });

        iv.setOnTouchListener((v, e) -> {
            int action = e.getActionMasked();
            // 双指交给 ScaleGestureDetector
            scaleDetector.onTouchEvent(e);

            switch (action) {
                case MotionEvent.ACTION_DOWN:
                    activePointerId = e.getPointerId(0);
                    downX = lastX = e.getX();
                    downY = lastY = e.getY();
                    dragging = false;
                    // 双击检测：200ms 内的第二次按下
                    long now = System.currentTimeMillis();
                    if (now - lastTapTime < 260) {
                        doubleTapPending = true;
                    }
                    lastTapTime = now;
                    // v1.11.0：长按唤出「保存 / 转发 / 删除」菜单（用户明确要求）。
                    // View 没有 setOnLongClickListener 的自动处理（我们把 onTouch 全吃掉了），
                    // 所以自己用 Handler 打一个 420ms 的计时器，到点还没抬手就算长按。
                    cancelLongPress();
                    if (cur != null) {
                        pendingLongPress = true;
                        handler.postDelayed(longPressRunnable, 420);
                    }
                    break;
                case MotionEvent.ACTION_POINTER_DOWN:
                    // 进入多指：停止单指拖动
                    dragging = false;
                    break;
                case MotionEvent.ACTION_MOVE:
                    if (pendingLongPress
                            && (Math.abs(e.getX() - downX) > 10
                                || Math.abs(e.getY() - downY) > 10)) {
                        cancelLongPress();     // 移动了就不是长按
                    }
                    if (e.getPointerCount() == 1 && scaleDetector.isInProgress()) break;
                    if (e.getPointerCount() == 1) {
                        float dx = e.getX() - lastX;
                        float dy = e.getY() - lastY;
                        if (!dragging && scale > 1.01f) {
                            if (Math.abs(e.getX() - downX) > 6 || Math.abs(e.getY() - downY) > 6) {
                                dragging = true;
                            }
                        } else if (scale <= 1.01f) {
                            // 未放大时垂直下拉 → 关闭（微信同款）
                            float totalY = e.getY() - downY;
                            float totalX = e.getX() - downX;
                            if (totalY > 8 && Math.abs(totalY) > Math.abs(totalX)) {
                                applyDismissOffset(totalY);
                                dragging = true;
                            }
                        }
                        if (dragging && scale > 1.01f) {
                            transX += dx;
                            transY += dy;
                            clampTrans();
                            int[] sz = curSize();
                            applyMatrix(sz[0], sz[1]);
                        } else if (dragging) {
                            lastX = e.getX(); lastY = e.getY();
                            return true;
                        }
                        lastX = e.getX(); lastY = e.getY();
                    }
                    break;
                case MotionEvent.ACTION_UP:
                case MotionEvent.ACTION_CANCEL:
                    boolean longFired = pendingLongPress;
                    cancelLongPress();
                    if (longFired) {
                        // 长按已触发过：这一抬手不能再当成单击（否则菜单弹完又闪一下界面）
                        if (action == MotionEvent.ACTION_UP) onLongPressImage();
                        return true;
                    }
                    if (dragging) {
                        if (scale <= 1.01f) {
                            // 下拉：跟手位移 + 淡出，松手按位移/速度决定是否关闭
                            float totalY = lastY - downY;
                            float vy = 0;
                            try {
                                android.view.VelocityTracker vt =
                                        android.view.VelocityTracker.obtain();
                                vt.addMovement(e);
                                vt.computeCurrentVelocity(1000);
                                vy = vt.getYVelocity();
                                vt.recycle();
                            } catch (Throwable ignored) {}
                            boolean shouldClose = totalY > DISMISS_DISTANCE || vy > DISMISS_VELOCITY;
                            if (shouldClose) {
                                closeWithAnim();
                            } else {
                                // 回弹
                                iv.animate().translationY(0f).alpha(1f)
                                        .setDuration(FdAnim.DURATION_ENTER)
                                        .setInterpolator(FdAnim.CURVE_DECELERATE)
                                        .start();
                            }
                            return true;
                        }
                        dragging = false;
                    }
                    if (doubleTapPending) {
                        doubleTapPending = false;
                        toggleZoomAt(e.getX(), e.getY());
                    } else if (action == MotionEvent.ACTION_UP
                            && !wasDragging(e)) {
                        onSingleTap();
                    }
                    break;
            }
            return true;
        });
    }

    private boolean wasDragging(MotionEvent e) {
        return Math.abs(e.getX() - downX) > 12 || Math.abs(e.getY() - downY) > 12;
    }

    /** 下拉过程中整层跟手下移 + 变透明 */
    private void applyDismissOffset(float dy) {
        iv.setTranslationY(dy);
        float alpha = 1f - Math.min(0.7f, dy / 700f);
        root.setAlpha(alpha);
    }

    private float clampScale(float s) {
        return Math.max(MIN_SCALE, Math.min(MAX_SCALE, s));
    }

    /** 放大后限制平移范围：图片边缘不能拖出屏幕太多，也不能完全拖离视野 */
    private void clampTrans() {
        int[] sz = curSize();
        if (sz[0] <= 0 || sz[1] <= 0) return;
        float s = baseScale * scale;
        int vw = root.getWidth(), vh = root.getHeight();
        float dw = sz[0] * s, dh = sz[1] * s;
        float maxX = Math.max(0, (dw - vw) / 2f);
        float maxY = Math.max(0, (dh - vh) / 2f);
        transX = Math.max(-maxX, Math.min(maxX, transX));
        transY = Math.max(-maxY, Math.min(maxY, transY));
    }

    /** 双击：以点击点为中心放大到 2.5x 或还原（微信同款） */
    private void toggleZoomAt(float fx, float fy) {
        int[] sz = curSize();
        if (scale > 1.05f) {
            resetMatrix();
            applyMatrix(sz[0], sz[1]);
        } else {
            float target = 2.5f;
            float k = target / scale;
            float[] co = centerOffset(sz[0], sz[1], baseScale * scale);
            float[] cn = centerOffset(sz[0], sz[1], baseScale * target);
            transX = fx - cn[0] - (fx - co[0] - transX) * k;
            transY = fy - cn[1] - (fy - co[1] - transY) * k;
            scale = target;
            clampTrans();
            applyMatrix(sz[0], sz[1]);
        }
        // 缩放动画：微信是平滑过渡，这里用 180ms 补间（无 ObjectAnimator 直接改 matrix，
        // 用短时 ValueAnimator 插值 scale/trans）
        animateTo(scale, transX, transY, sz);
    }

    private void animateTo(final float targetScale, final float tx, final float ty, final int[] sz) {
        if (!FdAnim.on(this)) { applyMatrix(sz[0], sz[1]); return; }
        final float s0 = scale, x0 = transX, y0 = transY;
        ValueAnimator va = ValueAnimator.ofFloat(0f, 1f);
        va.setDuration(FdAnim.DURATION_MOVE);
        va.setInterpolator(FdAnim.CURVE_DECELERATE);
        va.addUpdateListener(new ValueAnimator.AnimatorUpdateListener() {
            @Override public void onAnimationUpdate(ValueAnimator a) {
                float t = (float) a.getAnimatedValue();
                scale = s0 + (targetScale - s0) * t;
                transX = x0 + (tx - x0) * t;
                transY = y0 + (ty - y0) * t;
                applyMatrix(sz[0], sz[1]);
            }
        });
        va.start();
    }

    /** 单击：切换顶栏/底栏显隐（微信同款，全屏沉浸） */
    private void onSingleTap() {
        boolean vis = topBar.getVisibility() == View.VISIBLE;
        if (vis) {
            FdAnim.fadeOut(topBar, FdAnim.DURATION_FAST);
            FdAnim.fadeOut(bottomBar, FdAnim.DURATION_FAST);
            topBar.postDelayed(() -> {
                topBar.setVisibility(View.GONE);
                bottomBar.setVisibility(View.GONE);
            }, FdAnim.DURATION_FAST);
        } else {
            topBar.setVisibility(View.VISIBLE);
            bottomBar.setVisibility(View.VISIBLE);
            topBar.setAlpha(0f); bottomBar.setAlpha(0f);
            FdAnim.fadeIn(topBar, FdAnim.DURATION_FAST);
            FdAnim.fadeIn(bottomBar, FdAnim.DURATION_FAST);
        }
    }

    // ==================== 长按菜单 ====================

    /**
     * 长按图片：弹出浮层菜单（保存 / 转发 / 删除）。
     * 用户明确要求"图片能长按保存、删除"。
     */
    private void onLongPressImage() {
        if (cur == null) { toast("图片加载中…"); return; }
        final String name = cur.file;
        final String mime = cur.mime;
        final String src = srcs.get(index);
        final Bitmap bm = bitmaps.size() > index ? bitmaps.get(index) : null;

        String[] items = {"保存到相册", "转发", "删除"};
        new android.app.AlertDialog.Builder(this)
                .setItems(items, (d, which) -> {
                    if (which == 0) onSave();
                    else if (which == 1) onShare();
                    else confirmDelete();
                })
                .show();
    }

    private void confirmDelete() {
        if (cur == null) { toast("图片加载中…"); return; }
        new android.app.AlertDialog.Builder(this)
                .setTitle("删除这张图片？")
                .setMessage("将从「" + FdUtil.peerSavePathDesc(cur.peerName) + "」移除该图片，"
                        + "聊天记录也会一并删除。")
                .setNegativeButton("取消", null)
                .setPositiveButton("删除", (d, w) -> doDeleteCurrent())
                .show();
    }

    /**
     * 删除当前这张：磁盘文件 + 聊天记录，**只删这一张**。
     *
     * v1.11.0 修正：早前这里调的是 FdUtil.deleteSavedFiles(folder, imagesOnly=true)，
     * 那是"按设备删整个文件夹的图片"的全局接口 —— 在查看器里点一次删除，
     * 会把该设备收到的**所有**图片都删掉，属于严重的误删。
     * 现在改成：
     *   1) 只按 m.open / m.path 删这一个文件（语义与主界面 deleteLocalFileOf 完全一致）；
     *   2) 用 keyOf(m) 把 key 回传主界面，由主界面 detachMsgs 同步摘记录 + 删文件，
     *      保证"文件与记录成对删除"（v1.10.1 建立的语义不被绕过）。
     */
    private void doDeleteCurrent() {
        final MainActivity.Msg m = cur;
        if (m == null) { finish(); return; }
        final String key = keyOfMsg(m);
        new Thread(() -> {
            boolean fileGone = deleteFileOf(m);
            runOnUiThread(() -> {
                toast(fileGone ? "已删除" : "已删除记录（文件未找到）");
                setResult(RESULT_OK, new Intent().putExtra("del_key", key));
                finish();
            });
        }).start();
    }

    /** 与 MainActivity.keyOf 严格一致：ts|midOrTid|dir|kind */
    static String keyOfMsg(MainActivity.Msg m) {
        return m.ts + "|" + (m.mid != null ? m.mid : (m.tid != null ? m.tid : ""))
                + "|" + m.dir + "|" + m.kind;
    }

    /** 精准删这一个文件；语义对齐 MainActivity.deleteLocalFileOf */
    private boolean deleteFileOf(MainActivity.Msg m) {
        try {
            // 1) content:// Uri 直接删
            if (!TextUtils.isEmpty(m.open) && m.open.startsWith("content://")) {
                try {
                    if (getContentResolver().delete(Uri.parse(m.open), null, null) > 0) return true;
                } catch (Exception ignored) {}
            }
            // 2) 绝对路径
            if (!TextUtils.isEmpty(m.path) && new File(m.path).isAbsolute()) {
                File f = new File(m.path);
                if (f.exists()) return f.delete();
            }
            // 3) 展示用相对路径（Download/FlashDrop/<设备>/<name>）→ 查 MediaStore 按名删
            if (!TextUtils.isEmpty(m.path) && m.path.contains("/")) {
                return FdUtil.deleteSavedByRelPath(this, m.path);
            }
            // 4) 兜底：按「设备文件夹 + 文件名」定位
            if (!TextUtils.isEmpty(m.file)) {
                String rel = FdUtil.peerSavePathDesc(m.peerName) + "/" + m.file;
                if (FdUtil.deleteSavedByRelPath(this, rel)) return true;
            }
        } catch (Throwable ignored) {}
        return false;
    }

    // ==================== 保存 / 转发 ====================

    private void onSave() {
        Bitmap bm = bitmaps.size() > index ? bitmaps.get(index) : null;
        if (bm == null) { toast("图片加载中…"); return; }
        String name = index < names.size() ? names.get(index) : null;
        String mime = index < mimes.size() ? mimes.get(index) : null;
        Uri saved = saveBitmap(bm, name, mime);
        if (saved != null) {
            toast("已保存到 相册/Pictures/FlashDrop");
            // 保存成功给个短促的缩放反馈
            if (FdAnim.on(this) && bottomRow != null) {
                bottomRow.animate().scaleX(1.03f).scaleY(1.03f).setDuration(90).withEndAction(
                        () -> bottomRow.animate().scaleX(1f).scaleY(1f)
                                .setDuration(FdAnim.DURATION_FAST).start()).start();
            }
        } else {
            toast("保存失败");
        }
    }

    private void onShare() {
        Bitmap bm = bitmaps.size() > index ? bitmaps.get(index) : null;
        Uri shareUri = !TextUtils.isEmpty(srcs.get(index)) ? Uri.parse(srcs.get(index)) : null;
        if (shareUri == null || !canRead(shareUri)) {
            if (bm == null) { toast("图片加载中…"); return; }
            shareUri = saveBitmap(bm,
                    index < names.size() ? names.get(index) : null,
                    index < mimes.size() ? mimes.get(index) : null);
        }
        if (shareUri == null) { toast("转发失败"); return; }
        Intent it = new Intent(Intent.ACTION_SEND);
        String mime = index < mimes.size() ? mimes.get(index) : "image/jpeg";
        it.setType(FdUtil.isImageMime(mime) ? mime : "image/jpeg");
        it.putExtra(Intent.EXTRA_STREAM, shareUri);
        it.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        try {
            startActivity(Intent.createChooser(it, "转发图片到…"));
        } catch (Exception e) {
            toast("没有可用的分享应用");
        }
    }

    private boolean canRead(Uri u) {
        try {
            if ("file".equals(u.getScheme())) return new File(u.getPath()).canRead();
            getContentResolver().openAssetFileDescriptor(u, "r");
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    /** 保存到系统相册 Pictures/FlashDrop */
    private Uri saveBitmap(Bitmap bm, String name, String mime) {
        try {
            if (TextUtils.isEmpty(name)) name = "flashdrop_" + System.currentTimeMillis() + ".jpg";
            if (!name.contains(".")) name = name + ".jpg";
            String mt = FdUtil.isImageMime(mime) ? mime : "image/jpeg";
            if (Build.VERSION.SDK_INT >= 29) {
                android.content.ContentValues cv = new android.content.ContentValues();
                cv.put(android.provider.MediaStore.Images.Media.DISPLAY_NAME, name);
                cv.put(android.provider.MediaStore.Images.Media.MIME_TYPE, mt);
                cv.put(android.provider.MediaStore.Images.Media.RELATIVE_PATH,
                        android.os.Environment.DIRECTORY_PICTURES + "/FlashDrop");
                Uri u = getContentResolver().insert(
                        android.provider.MediaStore.Images.Media.EXTERNAL_CONTENT_URI, cv);
                if (u == null) return null;
                java.io.OutputStream os = getContentResolver().openOutputStream(u);
                if (os == null) return null;
                bm.compress(Bitmap.CompressFormat.JPEG, 92, os);
                os.close();
                return u;
            }
            File dir = new File(android.os.Environment.getExternalStoragePublicDirectory(
                    android.os.Environment.DIRECTORY_PICTURES), "FlashDrop");
            if (!dir.exists() && !dir.mkdirs()) return null;
            File f = new File(dir, name);
            java.io.FileOutputStream fo = new java.io.FileOutputStream(f);
            bm.compress(Bitmap.CompressFormat.JPEG, 92, fo);
            fo.close();
            return Uri.fromFile(f);
        } catch (Exception e) {
            return null;
        }
    }

    // ==================== 关闭动效 ====================

    private void closeWithAnim() {
        if (!FdAnim.on(this)) { finish(); return; }
        // 整层淡出下移 + 图片轻微缩小（微信的"往回一收"）
        root.animate().alpha(0f).translationY(FdUtil.dp(this, 30)).setDuration(FdAnim.DURATION_EXIT)
                .setInterpolator(FdAnim.CURVE_ACCELERATE)
                .setListener(new AnimatorListenerAdapter() {
                    @Override public void onAnimationEnd(Animator a) {
                        finish();
                        overridePendingTransition(0, 0);
                    }
                }).start();
    }

    @Override
    public void finish() {
        iv.setTranslationY(0f);
        root.setAlpha(1f);
        super.finish();
    }

    @Override
    public void onBackPressed() {
        closeWithAnim();
    }

    private void toast(String s) {
        Toast.makeText(this, s, Toast.LENGTH_SHORT).show();
    }

    // ==================== 解码 ====================

    /** 优先小图占位，避免大图解码前白屏 */
    private Bitmap loadThumb(String src) {
        try {
            if (TextUtils.isEmpty(src)) return null;
            BitmapFactoryOptionsHolder h = new BitmapFactoryOptionsHolder();
            Bitmap b = android.graphics.BitmapFactory.decodeStream(
                    openStream(src), null, h.small());
            return b;
        } catch (Throwable ignored) {
            return null;
        }
    }

    private java.io.InputStream openStream(String src) throws Exception {
        Uri u = Uri.parse(src);
        if (TextUtils.isEmpty(u.getScheme())) return new java.io.FileInputStream(src);
        if ("file".equals(u.getScheme())) return new java.io.FileInputStream(u.getPath());
        return getContentResolver().openInputStream(u);
    }

    private Bitmap decode(String src, int maxPx) {
        if (TextUtils.isEmpty(src)) return null;
        try {
            // 先读尺寸
            BitmapFactoryOptionsHolder h = new BitmapFactoryOptionsHolder();
            android.graphics.BitmapFactory.Options opt = new android.graphics.BitmapFactory.Options();
            opt.inJustDecodeBounds = true;
            try (java.io.InputStream is = openStream(src)) {
                if (is == null) return null;
                android.graphics.BitmapFactory.decodeStream(is, null, opt);
            }
            int w = opt.outWidth, hh = opt.outHeight;
            if (w <= 0 || hh <= 0) return null;
            int sample = 1;
            while (Math.max(w / sample, hh / sample) > maxPx) sample *= 2;
            android.graphics.BitmapFactory.Options o2 = new android.graphics.BitmapFactory.Options();
            o2.inSampleSize = sample;
            Bitmap bm;
            try (java.io.InputStream is = openStream(src)) {
                if (is == null) return null;
                bm = android.graphics.BitmapFactory.decodeStream(is, null, o2);
            }
            // v1.12.0：EXIF 旋转校正——手机竖拍/部分截图的 jpg 带 orientation 标记，
            // 不转正会侧躺或倒置（"图片打开显示不正确"的另一常见根因）
            if (bm != null) bm = applyExifRotation(src, bm);
            return bm;
        } catch (Throwable ignored) {
            return null;
        }
    }

    /** 按 EXIF orientation 把 Bitmap 转正（无标记/读失败时原样返回） */
    private Bitmap applyExifRotation(String src, Bitmap bm) {
        try {
            int orientation;
            try (java.io.InputStream is = openStream(src)) {
                if (is == null) return bm;
                android.media.ExifInterface ex = new android.media.ExifInterface(is);
                orientation = ex.getAttributeInt(
                        android.media.ExifInterface.TAG_ORIENTATION,
                        android.media.ExifInterface.ORIENTATION_NORMAL);
            }
            int deg;
            switch (orientation) {
                case android.media.ExifInterface.ORIENTATION_ROTATE_90:  deg = 90;  break;
                case android.media.ExifInterface.ORIENTATION_ROTATE_180: deg = 180; break;
                case android.media.ExifInterface.ORIENTATION_ROTATE_270: deg = 270; break;
                default: return bm;
            }
            if (deg == 0) return bm;
            android.graphics.Matrix mx = new android.graphics.Matrix();
            mx.postRotate(deg);
            Bitmap rot = Bitmap.createBitmap(bm, 0, 0, bm.getWidth(), bm.getHeight(), mx, true);
            if (rot != bm) bm.recycle();
            return rot;
        } catch (Throwable ignored) {
            return bm;
        }
    }

    /** 小占位图参数 */
    static class BitmapFactoryOptionsHolder {
        android.graphics.BitmapFactory.Options small() {
            android.graphics.BitmapFactory.Options o = new android.graphics.BitmapFactory.Options();
            o.inSampleSize = 8;
            return o;
        }
    }
}
