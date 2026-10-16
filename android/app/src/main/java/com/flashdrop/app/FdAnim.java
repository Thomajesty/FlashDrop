package com.flashdrop.app;

import android.animation.Animator;
import android.animation.AnimatorListenerAdapter;
import android.animation.ValueAnimator;
import android.app.Activity;
import android.app.Dialog;
import android.content.Context;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowManager;
import android.view.animation.AccelerateDecelerateInterpolator;
import android.view.animation.DecelerateInterpolator;
import android.view.animation.PathInterpolator;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * v1.11.0 动效基础设施。
 *
 * 设计原则（对齐 Material Motion 3 / 微信观感）：
 *   1. **时长**：进入 220ms，退出 180ms，位移/淡入 160~220ms，
 *      缩放类 200ms。不做超过 300ms 的动画 —— 局域网工具要的是"跟手"，不是"炫技"。
 *   2. **曲线**：进入用 Decelerate（快进慢停，元素尽快到位），退出用 Accelerate（慢起快走，干脆离开）。
 *   3. **可关闭**：设置里"减少动画"或系统动画关闭时，一律瞬时完成，不给用户强行动画。
 *   4. **不打断交互**：动画期间禁用重复点击，避免连点导致的动画叠加与状态错乱。
 */
public final class FdAnim {

    private FdAnim() {}

    // ---------------- Material Motion 时长与曲线 ----------------
    public static final int DURATION_FAST = 140;   // 微反馈：按下、涟漪
    public static final int DURATION_ENTER = 220;  // 进入：页面、弹窗、预览图
    public static final int DURATION_EXIT = 180;   // 退出
    public static final int DURATION_MOVE = 200;   // 布局位移、列表项

    /** 移动减速曲线（Material 3 emphasized decelerate 的简化版） */
    public static final PathInterpolator CURVE_DECELERATE =
            new PathInterpolator(0.05f, 0.7f, 0.1f, 1.0f);
    /** 移动加速曲线（exits 时用，快走） */
    public static final PathInterpolator CURVE_ACCELERATE =
            new PathInterpolator(0.3f, 0.0f, 0.8f, 0.15f);
    /** 标准缓入缓出（原地淡入淡出、缩放） */
    public static final PathInterpolator CURVE_STANDARD =
            new PathInterpolator(0.2f, 0.0f, 0.0f, 1.0f);

    /**
     * 系统是否允许动画（尊重系统「移除动画」/ 开发者选项动画时长 = 0）。
     * 这一层与应用内开关无关：系统都禁了，应用不该强行再动。
     */
    public static boolean enabled(Context ctx) {
        try {
            if (ctx == null) return true;
            float scale = android.provider.Settings.Global.getFloat(
                    ctx.getContentResolver(),
                    android.provider.Settings.Global.ANIMATOR_DURATION_SCALE, 1f);
            return scale > 0.01f;
        } catch (Throwable ignored) {
            return true;
        }
    }

    /**
     * 应用内动效总开关 = 系统允许 && 用户没在设置里关掉。
     * 所有动效方法统一走这里判断，调用方不需要自己拼两个条件。
     */
    public static boolean on(Context ctx) {
        if (!enabled(ctx)) return false;
        try {
            if (ctx == null) return true;
            return prefOf(ctx).animations();
        } catch (Throwable ignored) {
            return true;
        }
    }

    /** 供 View 版判断（等价于 on(v.getContext())） */
    public static boolean on(View v) {
        return v != null && on(v.getContext());
    }

    // ---------------- 页面转场 ----------------

    /**
     * Activity 进入动效：内容整体上移淡入 + 轻微缩放。
     * 在 onCreate 里 setContentView 之后调用。
     */
    public static void activityEnter(final View root) {
        if (root == null || !on(root)) return;
        root.setAlpha(0f);
        root.setTranslationY(dp(root, 18));
        root.setScaleX(0.985f);
        root.setScaleY(0.985f);
        root.animate()
                .alpha(1f).translationY(0f).scaleX(1f).scaleY(1f)
                .setDuration(DURATION_ENTER)
                .setInterpolator(CURVE_DECELERATE)
                .start();
    }

    /**
     * Activity 退出动效：内容淡出下移，返回后再 finish。
     * 必须在 finish() 之前调用，并等动画结束再 finish，否则会"闪一下"。
     */
    public static void activityExit(final Activity act, final View root, final Runnable after) {
        if (act == null) return;
        if (root == null || !on(act)) {
            if (after != null) after.run();
            act.finish();
            return;
        }
        root.animate()
                .alpha(0f).translationY(dp(root, 14)).scaleX(0.99f).scaleY(0.99f)
                .setDuration(DURATION_EXIT)
                .setInterpolator(CURVE_ACCELERATE)
                .setListener(new AnimatorListenerAdapter() {
                    @Override public void onAnimationEnd(Animator a) {
                        if (after != null) after.run();
                        act.finish();
                    }
                })
                .start();
    }

    // ---------------- 弹窗 ----------------

    /**
     * Dialog 弹出：从底部滑入 + 淡入。
     * 注意：要用 onShow 之后才能拿到 dialog.getWindow()，所以传 Dialog 进来。
     */
    public static void dialogEnter(final Dialog dlg, final View content) {
        if (dlg == null || content == null) return;
        if (!on(dlg.getContext())) return;
        Window w = dlg.getWindow();
        if (w != null) w.setDimAmount(0f);   // 自己做渐变遮罩，避免系统突兀的纯黑
        content.setAlpha(0f);
        content.setTranslationY(dp(content, 28));
        content.animate()
                .alpha(1f).translationY(0f)
                .setDuration(DURATION_ENTER)
                .setInterpolator(CURVE_DECELERATE)
                .start();
        if (w != null) animateDim(w, 0f, 0.55f, DURATION_ENTER);
    }

    /** Dialog 关闭：淡出下沉，动画结束后再 dismiss */
    public static void dialogExit(final Dialog dlg, final View content, final Runnable after) {
        if (dlg == null) {
            if (after != null) after.run();
            return;
        }
        if (content == null || !on(dlg.getContext())) {
            if (after != null) after.run();
            dlg.dismiss();
            return;
        }
        Window w = dlg.getWindow();
        if (w != null) animateDim(w, 0.55f, 0f, DURATION_EXIT);
        content.animate()
                .alpha(0f).translationY(dp(content, 24))
                .setDuration(DURATION_EXIT)
                .setInterpolator(CURVE_ACCELERATE)
                .setListener(new AnimatorListenerAdapter() {
                    @Override public void onAnimationEnd(Animator a) {
                        if (after != null) after.run();
                        dlg.dismiss();
                    }
                })
                .start();
    }

    private static void animateDim(final Window w, float from, float to, long dur) {
        try {
            android.view.WindowManager.LayoutParams lp = w.getAttributes();
            ValueAnimator va = ValueAnimator.ofFloat(from, to);
            va.setDuration(dur);
            va.setInterpolator(to > from ? CURVE_DECELERATE : CURVE_ACCELERATE);
            va.addUpdateListener(new ValueAnimator.AnimatorUpdateListener() {
                @Override public void onAnimationUpdate(ValueAnimator a) {
                    android.view.WindowManager.LayoutParams p = w.getAttributes();
                    p.dimAmount = (float) a.getAnimatedValue();
                    w.setAttributes(p);
                }
            });
            va.start();
        } catch (Throwable ignored) {}
    }

    // ---------------- 列表项 / 气泡 ----------------

    /**
     * 消息气泡入场：淡入 + 轻微上移 + 缩放。
     * 列表滚动中不调用，否则会抖动。
     */
    public static void bubbleEnter(final View v) {
        if (v == null) return;
        View parent = (View) v.getParent();
        if (parent instanceof android.widget.ListView) {
            android.widget.ListView lv = (android.widget.ListView) parent;
            if (lv.getFirstVisiblePosition() > 0
                    && lv.getFirstVisiblePosition() < lv.getChildCount()) return;
        }
        if (!on(v)) return;
        v.setAlpha(0f);
        v.setTranslationY(dp(v, 10));
        v.animate()
                .alpha(1f).translationY(0f)
                .setDuration(DURATION_MOVE)
                .setInterpolator(CURVE_DECELERATE)
                .start();
    }

    /** 列表项按下反馈：轻微缩小（微信/QQ 都有） */
    public static void pressDown(View v) {
        if (v == null || !on(v)) return;
        v.animate().scaleX(0.97f).scaleY(0.97f).setDuration(DURATION_FAST)
                .setInterpolator(CURVE_STANDARD).start();
    }

    public static void pressUp(View v) {
        if (v == null || !on(v)) return;
        v.animate().scaleX(1f).scaleY(1f).setDuration(DURATION_FAST)
                .setInterpolator(CURVE_STANDARD).start();
    }

    // ---------------- 淡入淡出 ----------------

    public static void fadeIn(View v, long dur) {
        if (v == null) return;
        v.setAlpha(0f);
        v.animate().alpha(1f).setDuration(
                on(v) ? (dur > 0 ? dur : DURATION_ENTER) : 0)
                .setInterpolator(CURVE_DECELERATE).start();
    }

    public static void fadeOut(View v, long dur) {
        if (v == null) return;
        v.animate().alpha(0f).setDuration(
                on(v) ? (dur > 0 ? dur : DURATION_EXIT) : 0)
                .setInterpolator(CURVE_ACCELERATE).start();
    }

    /** 顶部/底部条滑动进入（预览页的标题栏、底部操作栏） */
    public static void slideInFromTop(View v) {
        if (v == null || !on(v)) return;
        v.setAlpha(0f);
        v.setTranslationY(-dp(v, 20));
        v.animate().alpha(1f).translationY(0f).setDuration(DURATION_ENTER)
                .setInterpolator(CURVE_DECELERATE).start();
    }

    public static void slideInFromBottom(View v) {
        if (v == null || !on(v)) return;
        v.setAlpha(0f);
        v.setTranslationY(dp(v, 26));
        v.animate().alpha(1f).translationY(0f).setDuration(DURATION_ENTER)
                .setInterpolator(CURVE_DECELERATE).start();
    }

    // ---------------- 工具 ----------------

    public static int dp(View v, float d) {
        return v == null ? (int) d : FdUtil.dp(v.getContext(), d);
    }

    /**
     * 动效开关统一存在 Prefs 的 flashdrop_prefs 里（和设置页写的是同一份）。
     *
     * 注意：早前这里另开了一个 "motion" 独立文件，导致设置页把开关写进
     * flashdrop_prefs、这里却去读 motion，开关永远读到默认值（=永远开），
     * 用户的"关闭动效"完全无效。现在统一走 Prefs。
     *
     * 带一份静态缓存：动画判断在触摸/滚动里调用非常频繁，
     * 每次 new Prefs（内部 getSharedPreferences）会拖慢低端机。
     * setAnimations() 里会主动清缓存。
     */
    private static Prefs cachedPrefs;

    private static Prefs prefOf(Context ctx) {
        if (ctx == null) return null;
        try {
            if (cachedPrefs == null) {
                cachedPrefs = new Prefs(ctx.getApplicationContext());
            }
            return cachedPrefs;
        } catch (Throwable ignored) {
            return null;
        }
    }

    /** 设置页改完开关后调用，让缓存立即失效（否则要等下次进程启动） */
    public static void invalidatePrefCache() {
        cachedPrefs = null;
    }
}
