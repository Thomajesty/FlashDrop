package com.flashdrop.app;

import android.content.Context;
import android.graphics.Canvas;
import android.util.AttributeSet;
import android.widget.TextView;

/**
 * 会自绘「选区手柄」的 TextView（v1.18.10 引入，v1.18.12 提升为顶层类）。
 *
 * ── 为什么必须是**顶层类**，不能是 TextSelectionHelper 的嵌套类 ──────
 *
 * ★★ v1.18.12 崩溃修复（用户第 1 条：「点击离线设备闪退」）
 *
 * 现象：
 *   点击任何**有历史记录**的会话（离线设备尤其明显）立即闪退，堆栈为
 *       android.view.InflateException: Binary XML file line #N:
 *       Error inflating class com.flashdrop.app.TextSelectionHelper.BdTextView
 *       Caused by: java.lang.ClassNotFoundException:
 *                  com.flashdrop.app.TextSelectionHelper.BdTextView
 *       at layout/item_text_out.xml  ← MsgAdapter.getView()
 *
 * 根因（两层叠加，缺一不可）：
 *   ① 嵌套类在 dex 里的**真实类名**用 `$` 分隔，即
 *      `com.flashdrop.app.TextSelectionHelper$BdTextView`。
 *      LayoutInflater 走 `Class.forName(name)`，对**顶层类**才会做
 *      「点号 → `$`」的惰性尝试；对已经带包路径的名字不会回溯改写，
 *      于是 `...TextSelectionHelper.BdTextView` 查无此类。
 *   ② XML 元素名又**无法表达 `$`**：
 *        · 裸 `$` 不是合法的 XML Name 起始字符 → aapt2 报
 *          `not well-formed (invalid token)`
 *        · 字符引用 `&#36;` 同样不允许出现在元素名里 → 同错
 *      所以「引用嵌套类」这条路在资源布局里**根本走不通**。
 *
 * 因此唯一正确的解法是把 BdTextView 提为顶层类，XML 直接写全限定名
 * `com.flashdrop.app.BdTextView` —— 名字合法、反射可命中、无需 `$`。
 *
 * ── 为什么用 TextView 子类而不是外层叠加 View ──────────────────────
 *   手柄必须在 TextView 自己的 onDraw 里画，才能与文字共用同一套坐标，
 *   跟随滚动 / 换行 / 字号变化。用外层 View 叠加会在列表滚动时错位。
 */
public class BdTextView extends TextView {

    /** 该行文本对应的选择助手（由 MsgAdapter 在 bind 时挂上） */
    private TextSelectionHelper helper;

    public BdTextView(Context c) {
        super(c);
    }

    public BdTextView(Context c, AttributeSet a) {
        super(c, a);
    }

    public BdTextView(Context c, AttributeSet a, int defStyleAttr) {
        super(c, a, defStyleAttr);
    }

    /** 绑定选择助手（包内可见：仅 MsgAdapter / MainActivity 使用） */
    void bindHelper(TextSelectionHelper h) {
        this.helper = h;
    }

    /** 取回当前绑定的助手（MainActivity 读选区用） */
    TextSelectionHelper helper() {
        return this.helper;
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        if (helper != null && helper.wantsHandles()) {
            helper.drawHandles(canvas);
        }
    }
}
