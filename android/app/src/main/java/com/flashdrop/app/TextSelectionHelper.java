package com.flashdrop.app;

import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Rect;
import android.os.Handler;
import android.os.Looper;
import android.text.Layout;
import android.text.Selection;
import android.text.Spannable;
import android.text.Spanned;
import android.text.style.BackgroundColorSpan;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.widget.PopupWindow;
import android.widget.TextView;

/**
 * 聊天气泡内**局部文本选择**助手（v1.18.10）。
 *
 * ── 为什么自己实现，而不是继续用系统 textIsSelectable ──────────────
 *
 * 用户连续三个版本反馈「长按选文字没反应 / 只能全选不能局部选」。
 * 根因是系统选择模式要同时满足三个条件，任一被 ROM 破坏就静默失效：
 *   ① ListView 的 item 里 TextView 必须处于 focusable 且 focusableInTouchMode
 *   ② 父容器（气泡 / 行）不能是 clickable / longClickable
 *   ③ `mText instanceof Spannable && isEnabled()` 在**触摸那一刻**成立
 * 条件 ③ 尤其脆弱：`setTextIsSelectable(true)` 会把文字包成 Spannable，
 * 但 convertView 复用、setText() 重写、主题重绘都会把它换回普通 String，
 * 于是框架认为「这段文本不支持选择」直接放弃 —— 表现就是长按毫无反应。
 *
 * 主流做法（微信 / 各大 IM 的"自由复制"实现）都是**不依赖框架**，
 * 自己在 TextView 上做三件事：
 *   1. 用一个 BackgroundColorSpan 表示选区（可见高亮）
 *   2. 监听触摸，把手指位置换算成字符下标（Layout#getOffsetForHorizontal）
 *   3. 自绘左右两个圆形手柄，拖动时更新选区
 *
 * 本类即上述方案的最小完整实现：**长按即全选（保证"有反应"），
 * 随后可拖动左右手柄把选区收窄到任意片段**，松手后弹出自建菜单复制。
 *
 * 用法：
 *   TextSelectionHelper.attach(textView, () -> showTextMenu(...));
 */
public final class TextSelectionHelper {

    /** 选区高亮色（半透明蓝，与气泡底色兼容） */
    private static final int SEL_COLOR = 0x553B82F6;
    /** 手柄半径（dp） */
    private static final int HANDLE_R = 7;
    /** 手柄中心距文字行的垂直偏移（dp），让圆点压在行基线附近 */
    private static final int HANDLE_DY = 2;

    /** 选区变化回调（松手后弹菜单用） */
    public interface OnSelectionSettled { void run(); }

    private final TextView tv;
    private final OnSelectionSettled onSettled;
    private final Paint handlePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint handleStroke = new Paint(Paint.ANTI_ALIAS_FLAG);

    private BackgroundColorSpan span;
    private int selStart = -1, selEnd = -1;
    /** 当前拖的是哪个手柄：0 无 / 1 左 / 2 右 */
    private int dragging = 0;
    private boolean selectionActive = false;
    private boolean handlesVisible = false;

    private final Handler ui = new Handler(Looper.getMainLooper());

    private TextSelectionHelper(TextView tv, OnSelectionSettled cb) {
        this.tv = tv;
        this.onSettled = cb;
        handlePaint.setStyle(Paint.Style.FILL);
        handlePaint.setColor(0xFF3B82F6);
        handleStroke.setStyle(Paint.Style.FILL);
        handleStroke.setColor(0xFFFFFFFF);
    }

    /**
     * 给正文 TextView 挂上局部选择能力。
     *
     * 注意**不要**再调 `setTextIsSelectable(true)` —— 那会启用系统选择模式，
     * 与我们的自绘手柄争夺触摸事件（两套选区会互相覆盖）。本方案完全自持，
     * 只要求 TextView 在触摸时能拿到 Layout（非空即可）。
     */
    public static TextSelectionHelper attach(TextView tv, OnSelectionSettled cb) {
        if (tv == null) return null;
        final TextSelectionHelper h = new TextSelectionHelper(tv, cb);
        tv.setOnLongClickListener(v -> {
            try {
                v.performHapticFeedback(
                        android.view.HapticFeedbackConstants.LONG_PRESS);
            } catch (Throwable ignored) {}
            h.selectAll();
            return true;
        });
        tv.setOnTouchListener((v, ev) -> h.onTouch(ev));
        return h;
    }

    // ==================== 选区操作 ====================

    /** 全选：长按入口。保证"长按一定有可见反馈"。 */
    public void selectAll() {
        CharSequence t = tv.getText();
        if (t == null || t.length() == 0) return;
        applySelection(0, t.length());
    }

    public void clear() {
        CharSequence t = tv.getText();
        if (t instanceof Spannable && span != null) {
            ((Spannable) t).removeSpan(span);
        }
        span = null;
        selStart = selEnd = -1;
        selectionActive = false;
        handlesVisible = false;
        dragging = 0;
        tv.invalidate();
    }

    public boolean isActive() { return selectionActive; }
    public String selectedText() {
        if (!selectionActive) return tv.getText() == null ? "" : tv.getText().toString();
        CharSequence t = tv.getText();
        if (t == null) return "";
        int a = Math.max(0, Math.min(selStart, selEnd));
        int b = Math.min(t.length(), Math.max(selStart, selEnd));
        if (a >= b) return t.toString();
        return t.subSequence(a, b).toString();
    }

    private void applySelection(int a, int b) {
        CharSequence t = tv.getText();
        if (!(t instanceof Spannable)) return;
        Spannable sp = (Spannable) t;
        int len = sp.length();
        int s = Math.max(0, Math.min(a, len));
        int e = Math.max(0, Math.min(b, len));
        if (s > e) { int tmp = s; s = e; e = tmp; }

        if (span != null) sp.removeSpan(span);
        span = new BackgroundColorSpan(SEL_COLOR);
        if (e > s) {
            // SPAN_EXCLUSIVE_EXCLUSIVE：不把 span 粘到相邻字符上
            sp.setSpan(span, s, e, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        }
        selStart = s;
        selEnd = e;
        selectionActive = (e > s);
        handlesVisible = selectionActive;
        // 同步系统选区，让「复制」等既有路径也能取到（无害的额外保险）
        try { Selection.setSelection(sp, s, e); } catch (Throwable ignored) {}
        tv.invalidate();
    }

    // ==================== 触摸：拖手柄 ====================

    private boolean onTouch(MotionEvent ev) {
        if (!selectionActive) return false;
        final float x = ev.getX(), y = ev.getY();
        switch (ev.getActionMasked()) {
            case MotionEvent.ACTION_DOWN: {
                int hit = hitHandle(x, y);
                if (hit != 0) {
                    dragging = hit;
                    tv.getParent().requestDisallowInterceptTouchEvent(true);
                    return true;
                }
                return false;
            }
            case MotionEvent.ACTION_MOVE: {
                if (dragging == 0) return false;
                int off = offsetFor(x, y);
                if (off < 0) return true;
                if (dragging == 1) applySelection(off, selEnd);
                else               applySelection(selStart, off);
                return true;
            }
            case MotionEvent.ACTION_UP:
            case MotionEvent.ACTION_CANCEL: {
                if (dragging != 0) {
                    dragging = 0;
                    tv.getParent().requestDisallowInterceptTouchEvent(false);
                    if (onSettled != null) ui.post(onSettled::run);
                    return true;
                }
                return false;
            }
        }
        return false;
    }

    /** 判断触点是否落在某个手柄上（带 1.6 倍手指容差） */
    private int hitHandle(float x, float y) {
        Layout ly = tv.getLayout();
        if (ly == null) return 0;
        float tol = dp(14);
        float[] l = handleCenter(selStart, ly);
        float[] r = handleCenter(selEnd, ly);
        if (l != null && Math.abs(x - l[0]) <= tol && Math.abs(y - l[1]) <= tol) return 1;
        if (r != null && Math.abs(x - r[0]) <= tol && Math.abs(y - r[1]) <= tol) return 2;
        // 退路：点在上半行拖左、下半行拖右（窄文本时手柄重叠的兜底）
        if (l != null && r != null && Math.abs(l[0] - r[0]) < dp(6)
                && Math.abs(x - l[0]) <= tol) {
            float mid = (ly.getHeight()) / 2f + tv.getTotalPaddingTop();
            return y < mid ? 1 : 2;
        }
        return 0;
    }

    /** 手柄圆心（TextView 本地坐标）：字符下标 -> (x, y) */
    private float[] handleCenter(int off, Layout ly) {
        int len = ly.getText().length();
        int o = Math.max(0, Math.min(off, len));
        int line = ly.getLineForOffset(o);
        float x = ly.getPrimaryHorizontal(o);
        // 用该行 top/bottom 的中点，再下移一点，让圆点压在字形下沿
        float yBase = ly.getLineBottom(line);
        return new float[]{tv.getTotalPaddingLeft() + x,
                           tv.getTotalPaddingTop() + yBase + dp(HANDLE_DY)};
    }

    /** 触点 -> 字符下标（越界返回 -1） */
    private int offsetFor(float x, float y) {
        Layout ly = tv.getLayout();
        if (ly == null) return -1;
        float lx = x - tv.getTotalPaddingLeft();
        float lyy = y - tv.getTotalPaddingTop() - dp(HANDLE_DY);
        int line = ly.getLineForVertical((int) Math.max(0, lyy));
        float clamped = Math.max(0, Math.min(lx, ly.getLineRight(line)));
        return ly.getOffsetForHorizontal(line, clamped);
    }

    // ==================== 绘制手柄 ====================

    /**
     * 由 TextView 的 onDraw 调用（见 BdTextView）。
     * 坐标系与 getPrimaryHorizontal 一致，需自行叠加 padding。
     */
    void drawHandles(Canvas c) {
        if (!handlesVisible || !selectionActive) return;
        Layout ly = tv.getLayout();
        if (ly == null) return;
        float r = dp(HANDLE_R);
        drawOne(c, handleCenter(selStart, ly), r);
        drawOne(c, handleCenter(selEnd, ly), r);
    }

    private void drawOne(Canvas c, float[] p, float r) {
        if (p == null) return;
        // 白色描边 + 蓝色实心：在深/浅两种气泡底色上都清晰
        c.drawCircle(p[0], p[1], r + dp(1.5f), handleStroke);
        c.drawCircle(p[0], p[1], r, handlePaint);
    }

    private float dp(float v) {
        return TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v,
                tv.getResources().getDisplayMetrics());
    }

    // ==================== 供 TextView 子类调用 ====================

    /** 是否需要在 onDraw 里画手柄 */
    boolean wantsHandles() { return handlesVisible && selectionActive; }

    /**
     * ★ v1.18.12：原先这里是 `public static class BdTextView`，已**提取为
     *   顶层类** {@link BdTextView}。
     *
     * 原因：嵌套类的 dex 名带 `$`（`TextSelectionHelper$BdTextView`），
     * 而 XML 元素名既不允许裸 `$`（aapt2: not well-formed），也不允许
     * 字符引用 `&#36;`；LayoutInflater 的 Class.forName 又不会把点号
     * 改写成 `$` —— 三面夹击之下「在布局里引用嵌套 View 子类」无解，
     * 直接导致点进任何有历史的会话都 Error inflating class 闪退。
     * 提为顶层类后 XML 写 `com.flashdrop.app.BdTextView` 即可。
     */
}
