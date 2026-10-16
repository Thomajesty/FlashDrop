package com.flashdrop.app;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.graphics.Typeface;

import java.util.ArrayList;
import java.util.List;

/**
 * 长按消息菜单（v1.16.0）—— 微信风格的两行图标菜单。
 *
 * ── 为什么重写 ────────────────────────────────────────────────
 * v1.15.0 的菜单是一条横向 TextView 串，问题：
 *   ① 项目多时一行放不下，文字被挤成两行/换行，看着"错乱严重"
 *   ② 「更多打开方式」与「其他应用打开」功能完全重复，用户明确要求只留后者
 *   ③ 纯文字，没有图标，与微信观感差很远
 *
 * ── 本版规格（对齐微信长按菜单）────────────────────────────────
 *   · 每行固定 5 个位置，放不下自动换到第二行
 *   · 每项 = 32dp 图标（Canvas 现画）+ 12sp 文字，纵向排列
 *   · 项宽 64dp，保证"打开/保存/分享/删除/其他应用打开"五项一行放得下
 *   · 深色圆角浮层，锚定在气泡上方；上方空间不足则显示在下方
 *   · 文本强制单行 + 省略号，**绝不换行**
 *
 * 动作集（文件消息）：
 *   打开 · 保存 · 分享 · 删除 · 其他应用打开
 * 图片消息额外加「保存到相册」。
 * 所有动作都拍平到一行内（超过 5 项才换行）。
 */
public final class FdMenuIcon {

    private FdMenuIcon() {}

    /** 图标设计基准 32x32 */
    private static final float S = 32f;

    /** 支持的图标类型 */
    public static final int OPEN = 0;
    public static final int SAVE = 1;
    public static final int SHARE = 2;
    public static final int DELETE = 3;
    public static final int OTHER_APP = 4;
    public static final int GALLERY = 5;
    public static final int FORWARD = 6;
    public static final int COPY = 7;
    public static final int MULTI = 8;
    public static final int FOLDER = 9;
    public static final int RESEND = 10;
    public static final int CANCEL = 11;
    /** ★ v1.18.3：选择文字（框选局部文本） */
    public static final int SELECT = 12;
    /** ★ v1.18.5：全选（文本选择菜单用） */
    public static final int SELECT_ALL = 13;

    public static Bitmap make(Context ctx, int type, int color) {
        return make(ctx, type, color, 32);
    }

    /** 打开：一本翻开的书 / 方框带向右箭头 */
    private static void drawOpen(Canvas c, Paint p) {
        Paint s = new Paint(Paint.ANTI_ALIAS_FLAG);
        s.setColor(p.getColor());
        s.setStyle(Paint.Style.STROKE);
        s.setStrokeWidth(2.2f);
        s.setStrokeCap(Paint.Cap.ROUND);
        s.setStrokeJoin(Paint.Join.ROUND);
        // 文件夹梯形轮廓
        Path path = new Path();
        path.moveTo(4f, 8f);
        path.lineTo(13f, 8f);
        path.lineTo(15f, 11f);
        path.lineTo(28f, 11f);
        path.lineTo(28f, 25f);
        path.lineTo(4f, 25f);
        path.close();
        c.drawPath(path, s);
        c.drawLine(16f, 15f, 16f, 21f, s);
        c.drawLine(13f, 18.5f, 16f, 21.5f, s);
        c.drawLine(19f, 18.5f, 16f, 21.5f, s);
    }

    /** 保存：向下箭头 + 托盘 */
    private static void drawSave(Canvas c, Paint p) {
        Paint s = new Paint(Paint.ANTI_ALIAS_FLAG);
        s.setColor(p.getColor());
        s.setStyle(Paint.Style.STROKE);
        s.setStrokeWidth(2.4f);
        s.setStrokeCap(Paint.Cap.ROUND);
        s.setStrokeJoin(Paint.Join.ROUND);
        c.drawLine(16f, 6f, 16f, 21f, s);
        c.drawLine(11f, 16f, 16f, 21.5f, s);
        c.drawLine(21f, 16f, 16f, 21.5f, s);
        Path tray = new Path();
        tray.moveTo(6f, 20f);
        tray.lineTo(6f, 26f);
        tray.lineTo(26f, 26f);
        tray.lineTo(26f, 20f);
        c.drawPath(tray, s);
    }

    /** 分享：三个圆点 + 连线 */
    private static void drawShare(Canvas c, Paint p) {
        Paint s = new Paint(Paint.ANTI_ALIAS_FLAG);
        s.setColor(p.getColor());
        s.setStyle(Paint.Style.STROKE);
        s.setStrokeWidth(2.0f);
        s.setStrokeCap(Paint.Cap.ROUND);
        c.drawLine(11f, 16f, 21f, 10f, s);
        c.drawLine(11f, 16f, 21f, 22f, s);
        c.drawCircle(9f, 16f, 3.4f, p);
        c.drawCircle(23f, 9f, 3.4f, p);
        c.drawCircle(23f, 23f, 3.4f, p);
    }

    /** 删除：垃圾桶 */
    private static void drawDelete(Canvas c, Paint p) {
        Paint s = new Paint(Paint.ANTI_ALIAS_FLAG);
        s.setColor(p.getColor());
        s.setStyle(Paint.Style.STROKE);
        s.setStrokeWidth(2.2f);
        s.setStrokeCap(Paint.Cap.ROUND);
        s.setStrokeJoin(Paint.Join.ROUND);
        c.drawLine(6f, 9f, 26f, 9f, s);          // 盖子
        c.drawLine(13f, 9f, 13f, 6f, s);         // 提手左
        c.drawLine(13f, 6f, 19f, 6f, s);         // 提手顶
        c.drawLine(19f, 6f, 19f, 9f, s);         // 提手右
        Path body = new Path();
        body.moveTo(8f, 9f);
        body.lineTo(9.5f, 26f);
        body.lineTo(22.5f, 26f);
        body.lineTo(24f, 9f);
        c.drawPath(body, s);
        c.drawLine(13.5f, 13f, 14f, 22f, s);
        c.drawLine(18.5f, 13f, 18f, 22f, s);
    }

    /** 其他应用打开：方框 + 向右上箭头（"用别的程序打开"） */
    private static void drawOtherApp(Canvas c, Paint p) {
        Paint s = new Paint(Paint.ANTI_ALIAS_FLAG);
        s.setColor(p.getColor());
        s.setStyle(Paint.Style.STROKE);
        s.setStrokeWidth(2.2f);
        s.setStrokeCap(Paint.Cap.ROUND);
        s.setStrokeJoin(Paint.Join.ROUND);
        Path box = new Path();
        box.moveTo(19f, 7f);
        box.lineTo(7f, 7f);
        box.lineTo(7f, 25f);
        box.lineTo(25f, 25f);
        box.lineTo(25f, 13f);
        c.drawPath(box, s);
        c.drawLine(17f, 15f, 26f, 6f, s);        // 斜箭头
        c.drawLine(19f, 6f, 26f, 6f, s);
        c.drawLine(26f, 6f, 26f, 13f, s);
    }

    /** 保存到相册：山 + 太阳（图片） */
    private static void drawGallery(Canvas c, Paint p) {
        Paint s = new Paint(Paint.ANTI_ALIAS_FLAG);
        s.setColor(p.getColor());
        s.setStyle(Paint.Style.STROKE);
        s.setStrokeWidth(2.2f);
        s.setStrokeJoin(Paint.Join.ROUND);
        RectF r = new RectF(5f, 8f, 27f, 25f);
        c.drawRoundRect(r, 3f, 3f, s);
        c.drawCircle(11f, 13.5f, 2.2f, p);
        Path hill = new Path();
        hill.moveTo(6.5f, 23f);
        hill.lineTo(13f, 16f);
        hill.lineTo(18f, 20.5f);
        hill.lineTo(21.5f, 17f);
        hill.lineTo(25.5f, 23f);
        c.drawPath(hill, s);
    }

    /** 转发：箭头向右 + 底部小方框 */
    private static void drawForward(Canvas c, Paint p) {
        Paint s = new Paint(Paint.ANTI_ALIAS_FLAG);
        s.setColor(p.getColor());
        s.setStyle(Paint.Style.STROKE);
        s.setStrokeWidth(2.2f);
        s.setStrokeCap(Paint.Cap.ROUND);
        s.setStrokeJoin(Paint.Join.ROUND);
        c.drawLine(5f, 16f, 25f, 16f, s);
        c.drawLine(19f, 10f, 25.5f, 16f, s);
        c.drawLine(19f, 22f, 25.5f, 16f, s);
    }

    /** 复制：两张叠起来的纸 */
    private static void drawCopy(Canvas c, Paint p) {
        Paint s = new Paint(Paint.ANTI_ALIAS_FLAG);
        s.setColor(p.getColor());
        s.setStyle(Paint.Style.STROKE);
        s.setStrokeWidth(2.2f);
        s.setStrokeJoin(Paint.Join.ROUND);
        RectF back = new RectF(5f, 5f, 20f, 20f);
        c.drawRoundRect(back, 2.5f, 2.5f, s);
        RectF front = new RectF(12f, 12f, 27f, 27f);
        c.drawRoundRect(front, 2.5f, 2.5f, s);
    }

    /** 多选：四宫格 + 勾 */
    private static void drawMulti(Canvas c, Paint p) {
        Paint s = new Paint(Paint.ANTI_ALIAS_FLAG);
        s.setColor(p.getColor());
        s.setStyle(Paint.Style.STROKE);
        s.setStrokeWidth(2.2f);
        s.setStrokeJoin(Paint.Join.ROUND);
        c.drawRoundRect(new RectF(6f, 6f, 14f, 14f), 2f, 2f, s);
        c.drawRoundRect(new RectF(18f, 6f, 26f, 14f), 2f, 2f, s);
        c.drawRoundRect(new RectF(6f, 18f, 14f, 26f), 2f, 2f, s);
        c.drawRoundRect(new RectF(18f, 18f, 26f, 26f), 2f, 2f, s);
    }

    /** 文件夹 */
    private static void drawFolder(Canvas c, Paint p) {
        Paint s = new Paint(Paint.ANTI_ALIAS_FLAG);
        s.setColor(p.getColor());
        s.setStyle(Paint.Style.STROKE);
        s.setStrokeWidth(2.2f);
        s.setStrokeJoin(Paint.Join.ROUND);
        Path path = new Path();
        path.moveTo(5f, 9f);
        path.lineTo(13f, 9f);
        path.lineTo(15f, 12f);
        path.lineTo(27f, 12f);
        path.lineTo(27f, 24f);
        path.lineTo(5f, 24f);
        path.close();
        c.drawPath(path, s);
    }

    /** 重发：环形箭头 */
    private static void drawResend(Canvas c, Paint p) {
        Paint s = new Paint(Paint.ANTI_ALIAS_FLAG);
        s.setColor(p.getColor());
        s.setStyle(Paint.Style.STROKE);
        s.setStrokeWidth(2.2f);
        s.setStrokeCap(Paint.Cap.ROUND);
        RectF r = new RectF(7f, 7f, 25f, 25f);
        c.drawArc(r, 40f, 280f, false, s);
        c.drawLine(16f, 4f, 22f, 9f, s);
        c.drawLine(22f, 9f, 17f, 13f, s);
    }

    /** 取消：圆内叉 */
    private static void drawCancel(Canvas c, Paint p) {
        Paint s = new Paint(Paint.ANTI_ALIAS_FLAG);
        s.setColor(p.getColor());
        s.setStyle(Paint.Style.STROKE);
        s.setStrokeWidth(2.2f);
        s.setStrokeCap(Paint.Cap.ROUND);
        c.drawCircle(16f, 16f, 11f, s);
        c.drawLine(12f, 12f, 20f, 20f, s);
        c.drawLine(20f, 12f, 12f, 20f, s);
    }

    /**
     * ★ v1.18.3：选择文字。
     * 视觉 = 左右两根选择把手 + 中间三行文字，一眼能看出"框选文本"。
     * 文字行长度错落（中间最长），避免三根等长横线看起来像"汉堡菜单"。
     */
    private static void drawSelect(Canvas c, Paint p) {
        // 中间三行文字（略收窄，给把手让出空间）
        c.drawRect(9.5f, 9.5f, 21f, 11.5f, p);
        c.drawRect(9.5f, 15f, 24f, 17f, p);
        c.drawRect(9.5f, 20.5f, 18f, 22.5f, p);
        // 左右选择把手（竖条 + 端部略宽，模拟拖动柄）
        c.drawRect(2.5f, 7f, 5f, 25f, p);
        c.drawRect(27f, 7f, 29.5f, 25f, p);
    }

    /**
     * ★ v1.18.5：全选。
     * 视觉 = 一个外框 + 框内三行文字，表示"把整段都纳入选择"。
     */
    private static void drawSelectAll(Canvas c, Paint p) {
        Paint s = new Paint(Paint.ANTI_ALIAS_FLAG);
        s.setColor(p.getColor());
        s.setStyle(Paint.Style.STROKE);
        s.setStrokeWidth(2.2f);
        s.setStrokeJoin(Paint.Join.ROUND);
        c.drawRoundRect(new RectF(6f, 7f, 26f, 25f), 2.5f, 2.5f, s);
        c.drawLine(10f, 12.5f, 22f, 12.5f, s);
        c.drawLine(10f, 16f, 22f, 16f, s);
        c.drawLine(10f, 19.5f, 22f, 19.5f, s);
    }

    /**
     * ★ v1.18.3：图标尺寸可配。
     *
     * 用户反馈长按菜单"图标过大"，希望精致一些。旧实现把 32dp 写死在
     * make() 里，菜单想调小只能把 32dp 的位图塞进更小的 ImageView，
     * 属于降采样、边缘会发虚。现在把尺寸开出来，直接按目标 dp 渲染矢量，
     * 缩小后线条依然锐利。
     */
    public static Bitmap make(Context ctx, int type, int color, int sizeDp) {
        int size = FdUtil.dp(ctx, sizeDp);
        Bitmap bm = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888);
        Canvas c = new Canvas(bm);
        float k = size / S;
        c.scale(k, k);

        Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
        p.setColor(color);
        p.setStyle(Paint.Style.FILL);

        switch (type) {
            case OPEN:        drawOpen(c, p); break;
            case SAVE:        drawSave(c, p); break;
            case SHARE:       drawShare(c, p); break;
            case DELETE:      drawDelete(c, p); break;
            case OTHER_APP:   drawOtherApp(c, p); break;
            case GALLERY:     drawGallery(c, p); break;
            case FORWARD:     drawForward(c, p); break;
            case COPY:        drawCopy(c, p); break;
            case MULTI:       drawMulti(c, p); break;
            case FOLDER:      drawFolder(c, p); break;
            case RESEND:      drawResend(c, p); break;
            case CANCEL:      drawCancel(c, p); break;
            case SELECT:      drawSelect(c, p); break;
            case SELECT_ALL:  drawSelectAll(c, p); break;
            default:          drawOtherApp(c, p); break;
        }
        return bm;
    }

    /** 一个菜单项的描述 */
    public static class Item {
        public final String label;
        public final int icon;
        public Item(String label, int icon) {
            this.label = label;
            this.icon = icon;
        }
    }

    /** 便捷构造列表 */
    public static List<Item> list(Item... items) {
        List<Item> l = new ArrayList<>();
        for (Item i : items) l.add(i);
        return l;
    }
}
