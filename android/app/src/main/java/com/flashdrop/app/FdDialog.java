package com.flashdrop.app;

import android.app.Activity;
import android.app.Dialog;
import android.graphics.Color;
import android.graphics.drawable.ColorDrawable;
import android.graphics.drawable.GradientDrawable;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowManager;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * 微信风格对话框（v1.16.0）。
 *
 * ── 为什么重写 ────────────────────────────────────────────────
 * 用户反馈："聊天界面的删除按钮和设置的删除按钮弹窗太普通，
 * 需要优化匹配成微信风格"。系统 AlertDialog 在深色主题下是
 * Material 造型（左对齐标题 + 右对齐按钮），与整体风格割裂。
 *
 * ── 微信规格 ──────────────────────────────────────────────────
 *   · 宽约屏宽 78%，圆角 12dp，深色底 #2E2E2E / 浅色底 #FFFFFF
 *   · 标题居中、15sp、半粗
 *   · 正文居中、14sp、次级灰（可省略；无正文时只显示标题）
 *   · 按钮**上下堆叠**（不是左右并排），中间 1px 分隔线
 *   · 主按钮（确定）用微信绿 #07C160；次要按钮（取消）用中性灰字
 *   · 危险操作（删除）主按钮用微信红 #FA5151
 *   · 点击外部不关闭（微信不响应外部点击），返回键可关
 */
public final class FdDialog {

    private FdDialog() {}

    public interface OnOk { void run(); }

    /** 主题色常量（与微信一致，不跟随 App 气泡配色） */
    private static final int WX_GREEN = 0xFF07C160;
    private static final int WX_RED = 0xFFFA5151;

    /** 普通确认（绿色主按钮） */
    public static void confirm(Activity a, String title, String message,
                               String okText, OnOk onOk) {
        show(a, title, message, okText, "取消", onOk, null, false);
    }

    /** 危险确认（红色主按钮，用于删除类操作） */
    public static void danger(Activity a, String title, String message,
                              String okText, OnOk onOk) {
        show(a, title, message, okText, "取消", onOk, null, true);
    }

    /** 危险确认 + 取消回调（用户点「取消」时也要做事，比如退出多选模式） */
    public static void danger(Activity a, String title, String message,
                              String okText, OnOk onOk, OnOk onCancel) {
        show(a, title, message, okText, "取消", onOk, onCancel, true);
    }

    /** 只有"知道了"的单按钮提示（不显示取消） */
    public static void info(Activity a, String title, String message,
                            String okText, OnOk onOk) {
        show(a, title, message, okText, null, onOk, null, false);
    }

    /**
     * 自定义内容区（设置页"删除内容"的三类勾选面板等）。
     * 按钮区仍是微信风格：上下堆叠 + 1px 分隔线。
     */
    public static void custom(Activity a, String title, String message,
                              View content, String okText, String cancelText,
                              boolean isDanger, OnOk onOk) {
        if (a == null || a.isFinishing()) return;
        FdTheme t = FdTheme.resolve(a);
        int bg = t.dark ? 0xFF2E2E2E : 0xFFFFFFFF;
        int mainText = t.dark ? 0xFFEDEDED : 0xFF1A1A1A;
        int subText = t.dark ? 0xFF9A9A9A : 0xFF888888;
        int divider = t.dark ? 0xFF3E3E3E : 0xFFE5E5E5;

        Dialog d = new Dialog(a);
        d.requestWindowFeature(Window.FEATURE_NO_TITLE);
        LinearLayout root = new LinearLayout(a);
        root.setOrientation(LinearLayout.VERTICAL);
        GradientDrawable rbg = new GradientDrawable();
        rbg.setColor(bg);
        rbg.setCornerRadius(dp(a, 12));
        root.setBackground(rbg);

        TextView tvTitle = new TextView(a);
        tvTitle.setText(title == null ? "" : title);
        tvTitle.setTextColor(mainText);
        tvTitle.setTextSize(16);
        tvTitle.setGravity(Gravity.CENTER);
        tvTitle.setPadding(dp(a, 22), dp(a, 22), dp(a, 22), dp(a, 8));
        root.addView(tvTitle);

        if (message != null && !message.isEmpty()) {
            TextView tvMsg = new TextView(a);
            tvMsg.setText(message);
            tvMsg.setTextColor(subText);
            tvMsg.setTextSize(13);
            tvMsg.setGravity(Gravity.CENTER);
            tvMsg.setPadding(dp(a, 22), 0, dp(a, 22), dp(a, 10));
            root.addView(tvMsg);
        }

        if (content != null) {
            root.addView(content, new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        }

        View hr = new View(a);
        hr.setBackgroundColor(divider);
        root.addView(hr, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, Math.max(1, dp(a, 1))));

        addButton(a, root, okText == null ? "确定" : okText,
                isDanger ? WX_RED : WX_GREEN, true, v -> {
                    d.dismiss();
                    if (onOk != null) onOk.run();
                });

        if (cancelText != null) {
            View hr2 = new View(a);
            hr2.setBackgroundColor(divider);
            root.addView(hr2, new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, Math.max(1, dp(a, 1))));
            addButton(a, root, cancelText, mainText, false, v -> d.dismiss());
        }

        d.setContentView(root);
        d.setCanceledOnTouchOutside(false);
        Window w = d.getWindow();
        if (w != null) w.setBackgroundDrawable(new ColorDrawable(Color.TRANSPARENT));
        d.show();
        if (w != null) {
            w.setLayout((int) (a.getResources().getDisplayMetrics().widthPixels * 0.82f),
                    ViewGroup.LayoutParams.WRAP_CONTENT);
        }
    }

    /** 列表型对话框：每行一个可点选项（微信风格行 + 分隔线） */
    public static void list(Activity a, String title, String message,
                            java.util.List<String> rows,
                            java.util.function.IntConsumer onPick) {
        if (a == null || a.isFinishing()) return;
        FdTheme t = FdTheme.resolve(a);
        int bg = t.dark ? 0xFF2E2E2E : 0xFFFFFFFF;
        int mainText = t.dark ? 0xFFEDEDED : 0xFF1A1A1A;
        int subText = t.dark ? 0xFF9A9A9A : 0xFF888888;
        int divider = t.dark ? 0xFF3E3E3E : 0xFFE5E5E5;

        Dialog d = new Dialog(a);
        d.requestWindowFeature(Window.FEATURE_NO_TITLE);
        LinearLayout root = new LinearLayout(a);
        root.setOrientation(LinearLayout.VERTICAL);
        GradientDrawable rbg = new GradientDrawable();
        rbg.setColor(bg);
        rbg.setCornerRadius(dp(a, 12));
        root.setBackground(rbg);

        if (title != null && !title.isEmpty()) {
            TextView tvTitle = new TextView(a);
            tvTitle.setText(title);
            tvTitle.setTextColor(mainText);
            tvTitle.setTextSize(16);
            tvTitle.setGravity(Gravity.CENTER);
            tvTitle.setPadding(dp(a, 22), dp(a, 22), dp(a, 22),
                    message == null || message.isEmpty() ? dp(a, 16) : dp(a, 8));
            root.addView(tvTitle);
        }
        if (message != null && !message.isEmpty()) {
            TextView tvMsg = new TextView(a);
            tvMsg.setText(message);
            tvMsg.setTextColor(subText);
            tvMsg.setTextSize(13);
            tvMsg.setGravity(Gravity.CENTER);
            tvMsg.setPadding(dp(a, 22), 0, dp(a, 22), dp(a, 14));
            root.addView(tvMsg);
        }

        for (int i = 0; i < rows.size(); i++) {
            final int idx = i;
            View hr = new View(a);
            hr.setBackgroundColor(divider);
            root.addView(hr, new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, Math.max(1, dp(a, 1))));
            TextView row = new TextView(a);
            row.setText(rows.get(i));
            row.setTextColor(mainText);
            row.setTextSize(15);
            row.setGravity(Gravity.CENTER);
            row.setPadding(dp(a, 22), dp(a, 16), dp(a, 22), dp(a, 16));
            row.setClickable(true);
            android.util.TypedValue out = new android.util.TypedValue();
            a.getTheme().resolveAttribute(android.R.attr.selectableItemBackground, out, true);
            if (out.resourceId != 0) row.setBackgroundResource(out.resourceId);
            row.setOnClickListener(v -> {
                d.dismiss();
                if (onPick != null) onPick.accept(idx);
            });
            root.addView(row, new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        }

        View hr = new View(a);
        hr.setBackgroundColor(divider);
        root.addView(hr, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, Math.max(1, dp(a, 1))));
        addButton(a, root, "取消", mainText, false, v -> d.dismiss());

        d.setContentView(root);
        d.setCanceledOnTouchOutside(false);
        Window w = d.getWindow();
        if (w != null) w.setBackgroundDrawable(new ColorDrawable(Color.TRANSPARENT));
        d.show();
        if (w != null) {
            w.setLayout((int) (a.getResources().getDisplayMetrics().widthPixels * 0.82f),
                    ViewGroup.LayoutParams.WRAP_CONTENT);
        }
    }

    /** 完整形态：可带取消按钮回调 */
    public static void show(Activity a, String title, String message,
                            String okText, String cancelText,
                            OnOk onOk, OnOk onCancel, boolean isDanger) {
        if (a == null || a.isFinishing()) return;
        FdTheme t = FdTheme.resolve(a);
        int bg = t.dark ? 0xFF2E2E2E : 0xFFFFFFFF;
        int mainText = t.dark ? 0xFFEDEDED : 0xFF1A1A1A;
        int subText = t.dark ? 0xFF9A9A9A : 0xFF888888;
        int divider = t.dark ? 0xFF3E3E3E : 0xFFE5E5E5;

        Dialog d = new Dialog(a);
        d.requestWindowFeature(Window.FEATURE_NO_TITLE);

        LinearLayout root = new LinearLayout(a);
        root.setOrientation(LinearLayout.VERTICAL);
        GradientDrawable rbg = new GradientDrawable();
        rbg.setColor(bg);
        rbg.setCornerRadius(dp(a, 12));
        root.setBackground(rbg);

        // ---- 标题 ----
        TextView tvTitle = new TextView(a);
        tvTitle.setText(title == null ? "" : title);
        tvTitle.setTextColor(mainText);
        tvTitle.setTextSize(16);
        tvTitle.setGravity(Gravity.CENTER);
        tvTitle.setPadding(dp(a, 22), dp(a, 22), dp(a, 22),
                message == null || message.isEmpty() ? dp(a, 22) : dp(a, 8));
        root.addView(tvTitle);

        // ---- 正文 ----
        if (message != null && !message.isEmpty()) {
            TextView tvMsg = new TextView(a);
            tvMsg.setText(message);
            tvMsg.setTextColor(subText);
            tvMsg.setTextSize(14);
            tvMsg.setGravity(Gravity.CENTER);
            tvMsg.setLineSpacing(dp(a, 3), 1f);
            tvMsg.setPadding(dp(a, 24), 0, dp(a, 24), dp(a, 22));
            root.addView(tvMsg);
        }

        // ---- 按钮区：上下堆叠 + 1px 分隔线（微信造型）----
        View hr = new View(a);
        hr.setBackgroundColor(divider);
        root.addView(hr, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, Math.max(1, dp(a, 1))));

        addButton(a, root, okText == null ? "确定" : okText,
                isDanger ? WX_RED : WX_GREEN, true, v -> {
                    d.dismiss();
                    if (onOk != null) onOk.run();
                });

        if (cancelText != null) {
            View hr2 = new View(a);
            hr2.setBackgroundColor(divider);
            root.addView(hr2, new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, Math.max(1, dp(a, 1))));
            addButton(a, root, cancelText, mainText, false, v -> {
                d.dismiss();
                if (onCancel != null) onCancel.run();
            });
        }

        d.setContentView(root);
        d.setCanceledOnTouchOutside(false);      // 微信不响应外部点击
        Window w = d.getWindow();
        if (w != null) {
            w.setBackgroundDrawable(new ColorDrawable(Color.TRANSPARENT));
            WindowManager.LayoutParams lp = w.getAttributes();
            lp.width = (int) (a.getResources().getDisplayMetrics().widthPixels * 0.78f);
            w.setAttributes(lp);
        }
        d.show();
        // show 之后再设一次宽度（部分 ROM 会在 show 时重置）
        if (w != null) {
            w.setLayout((int) (a.getResources().getDisplayMetrics().widthPixels * 0.78f),
                    ViewGroup.LayoutParams.WRAP_CONTENT);
        }
    }

    private static void addButton(Activity a, LinearLayout parent, String text,
                                  int color, boolean bold, View.OnClickListener l) {
        TextView tv = new TextView(a);
        tv.setText(text);
        tv.setTextColor(color);
        tv.setTextSize(16);
        tv.setGravity(Gravity.CENTER);
        tv.setPadding(0, dp(a, 15), 0, dp(a, 15));
        if (bold) tv.setTypeface(tv.getTypeface(), android.graphics.Typeface.BOLD);
        tv.setClickable(true);
        android.util.TypedValue out = new android.util.TypedValue();
        a.getTheme().resolveAttribute(android.R.attr.selectableItemBackground, out, true);
        if (out.resourceId != 0) tv.setBackgroundResource(out.resourceId);
        tv.setOnClickListener(l);
        parent.addView(tv, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
    }

    private static int dp(Activity a, float v) {
        return FdUtil.dp(a, v);
    }

    /**
     * 带多选行的列表型对话框（设置页"数据清理"用）。
     *
     * @param rows 每行文案，点击切换勾选
     * @param isChecked 初始勾选态
     * @param onOk 点击确定时回调，参数为当前勾选集合
     */
    public static void multiChoice(Activity a, String title, String message,
                                   java.util.List<String> rows,
                                   java.util.List<Boolean> isChecked,
                                   String okText, String cancelText,
                                   java.util.function.Consumer<java.util.List<Boolean>> onOk) {
        if (a == null || a.isFinishing()) return;
        FdTheme t = FdTheme.resolve(a);
        int bg = t.dark ? 0xFF2E2E2E : 0xFFFFFFFF;
        int mainText = t.dark ? 0xFFEDEDED : 0xFF1A1A1A;
        int subText = t.dark ? 0xFF9A9A9A : 0xFF888888;
        int divider = t.dark ? 0xFF3E3E3E : 0xFFE5E5E5;

        Dialog d = new Dialog(a);
        d.requestWindowFeature(Window.FEATURE_NO_TITLE);
        LinearLayout root = new LinearLayout(a);
        root.setOrientation(LinearLayout.VERTICAL);
        GradientDrawable rbg = new GradientDrawable();
        rbg.setColor(bg);
        rbg.setCornerRadius(dp(a, 12));
        root.setBackground(rbg);

        TextView tvTitle = new TextView(a);
        tvTitle.setText(title == null ? "" : title);
        tvTitle.setTextColor(mainText);
        tvTitle.setTextSize(16);
        tvTitle.setGravity(Gravity.CENTER);
        tvTitle.setPadding(dp(a, 22), dp(a, 22), dp(a, 22), dp(a, 8));
        root.addView(tvTitle);

        if (message != null && !message.isEmpty()) {
            TextView tvMsg = new TextView(a);
            tvMsg.setText(message);
            tvMsg.setTextColor(subText);
            tvMsg.setTextSize(13);
            tvMsg.setGravity(Gravity.CENTER);
            tvMsg.setPadding(dp(a, 22), 0, dp(a, 22), dp(a, 12));
            root.addView(tvMsg);
        }

        final java.util.List<TextView> marks = new java.util.ArrayList<>();
        for (int i = 0; i < rows.size(); i++) {
            final int idx = i;
            View hr = new View(a);
            hr.setBackgroundColor(divider);
            root.addView(hr, new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, Math.max(1, dp(a, 1))));

            LinearLayout rowBox = new LinearLayout(a);
            rowBox.setOrientation(LinearLayout.HORIZONTAL);
            rowBox.setGravity(Gravity.CENTER_VERTICAL);
            rowBox.setPadding(dp(a, 22), dp(a, 14), dp(a, 22), dp(a, 14));
            rowBox.setClickable(true);

            TextView label = new TextView(a);
            label.setText(rows.get(i));
            label.setTextColor(mainText);
            label.setTextSize(15);
            label.setLayoutParams(new LinearLayout.LayoutParams(
                    0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
            rowBox.addView(label);

            TextView mark = new TextView(a);
            mark.setTextSize(16);
            marks.add(mark);
            rowBox.addView(mark);

            Runnable refresh = () -> mark.setText(Boolean.TRUE.equals(isChecked.get(idx))
                    ? "✓" : "");
            refresh.run();
            mark.setTextColor(Boolean.TRUE.equals(isChecked.get(idx))
                    ? WX_GREEN : subText);

            rowBox.setOnClickListener(v -> {
                boolean now = !Boolean.TRUE.equals(isChecked.get(idx));
                isChecked.set(idx, now);
                mark.setText(now ? "✓" : "");
                mark.setTextColor(now ? WX_GREEN : subText);
            });

            android.util.TypedValue out = new android.util.TypedValue();
            a.getTheme().resolveAttribute(android.R.attr.selectableItemBackground, out, true);
            if (out.resourceId != 0) rowBox.setBackgroundResource(out.resourceId);

            root.addView(rowBox);
        }

        View hr = new View(a);
        hr.setBackgroundColor(divider);
        root.addView(hr, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, Math.max(1, dp(a, 1))));

        addButton(a, root, okText == null ? "确定" : okText, WX_RED, true, v -> {
            d.dismiss();
            if (onOk != null) onOk.accept(isChecked);
        });

        if (cancelText != null) {
            View hr2 = new View(a);
            hr2.setBackgroundColor(divider);
            root.addView(hr2, new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, Math.max(1, dp(a, 1))));
            addButton(a, root, cancelText, mainText, false, v -> d.dismiss());
        }

        d.setContentView(root);
        d.setCanceledOnTouchOutside(false);
        Window w = d.getWindow();
        if (w != null) {
            w.setBackgroundDrawable(new ColorDrawable(Color.TRANSPARENT));
        }
        d.show();
        if (w != null) {
            w.setLayout((int) (a.getResources().getDisplayMetrics().widthPixels * 0.82f),
                    ViewGroup.LayoutParams.WRAP_CONTENT);
        }
    }
}
