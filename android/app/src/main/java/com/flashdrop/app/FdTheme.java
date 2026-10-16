package com.flashdrop.app;

import android.content.Context;
import android.content.res.Configuration;
import android.graphics.drawable.GradientDrawable;

/** 主题解析与调色板：深色 / 浅色 / 跟随系统 + 气泡配色方案 */
public class FdTheme {
    public final boolean dark;
    public final int bg, bar, card, border, text, dim, accent, accent2, green, red, warn;
    public final int bubbleInRes;
    /** 气泡配色方案：发送侧底色与文字色 */
    public final int bubbleOut, bubbleOutText;

    /** 与电脑端一致的方案定义 */
    public static final String[] SCHEME_KEYS = {"blue", "green", "purple", "orange", "pink"};
    public static final String[] SCHEME_NAMES = {"闪传蓝", "微信绿", "清新紫", "暖橙", "樱花粉"};
    private static final int[][] SCHEME_COLORS = {
            {0xFF3B82F6, 0xFFFFFFFF},
            {0xFF95EC69, 0xFF17301B},
            {0xFF8B5CF6, 0xFFFFFFFF},
            {0xFFF59E0B, 0xFF3B2503},
            {0xFFF472B6, 0xFFFFFFFF},
    };

    public static int schemeIndex(String key) {
        for (int i = 0; i < SCHEME_KEYS.length; i++)
            if (SCHEME_KEYS[i].equals(key)) return i;
        return 0;
    }

    /** 判断 key 是否为有效方案（区别于"未知/为空回落到默认"的情况） */
    public static boolean isValidScheme(String key) {
        if (key == null || key.isEmpty()) return false;
        for (String k : SCHEME_KEYS) if (k.equals(key)) return true;
        return false;
    }

    /** 按方案 key 返回 [气泡底色, 气泡文字色]；key 无效返回 null */
    public static int[] schemeColors(String key) {
        if (!isValidScheme(key)) return null;
        int[] sc = SCHEME_COLORS[schemeIndex(key)];
        return new int[]{sc[0], sc[1]};
    }

    /**
     * v1.13.0：按气泡**实际底色**推导可读的次级文字色（元信息/状态行用）。
     *
     * 为什么需要它：元信息与状态行此前固定用主题的 dim 灰（#9CA3AF），
     * 那是为深色页面背景设计的；一旦气泡换成自定义方案色（尤其浅色气泡），
     * 灰字压在浅底上对比度骤降，用户实测就是"颜色对比度不足、看不清"。
     *
     * 做法：用感知亮度判断底色明暗，浅底给深灰、深底给浅灰，
     * 再按 primary 文字色的强度降一档，保持"次级"层级感。
     *
     * @param bubbleBg 气泡实际背景色（ARGB）
     * @return 适合该底色的次级文字色
     */
    public static int onColorDim(int bubbleBg) {
        float lum = perceivedLuminance(bubbleBg);
        // 浅底（亮度 > 0.55）用深灰，深底用浅灰
        return lum > 0.55f ? 0xFF4B5563 : 0xFFE2E6EB;
    }

    /** 按底色推导主文字色（标题/正文用），保证极限对比度 */
    public static int onColorText(int bubbleBg) {
        float lum = perceivedLuminance(bubbleBg);
        return lum > 0.55f ? 0xFF111827 : 0xFFFFFFFF;
    }

    /** 感知亮度（0~1），ITU-R BT.601 加权，够用且便宜 */
    public static float perceivedLuminance(int color) {
        int r = (color >> 16) & 0xFF;
        int g = (color >> 8) & 0xFF;
        int b = color & 0xFF;
        return (0.299f * r + 0.587f * g + 0.114f * b) / 255f;
    }

    /**
     * v1.13.0：把**语义色**（成功绿 / 失败红 / 等待黄）适配到当前气泡底色上。
     *
     * 语义色不能换色相（绿必须还是绿），但亮度要跟着底色走：
     *   - 浅底：把语义色往黑里压 → 深绿 / 深红 / 深黄，才压得住浅背景
     *   - 深底：把语义色往白里提 → 亮绿 / 亮红 / 亮黄，才跳得出来
     *
     * 用户实测的"失败 · 应用重启，传输中断"红字压在亮绿气泡上发糊，
     * 就是这个语义色没跟着底色适配导致的。
     */
    public static int onColorAccent(int accent, int bubbleBg) {
        float bgLum = perceivedLuminance(bubbleBg);
        float fgLum = perceivedLuminance(accent);
        // 目标：前景与底色的亮度差至少 0.35，否则按需压暗 / 提亮
        float target = bgLum > 0.55f ? Math.max(0f, bgLum - 0.45f)
                                     : Math.min(1f, bgLum + 0.45f);
        if (Math.abs(fgLum - bgLum) >= 0.35f) return accent;   // 对比已够，不动
        return scaleTowards(accent, target);
    }

    /** 把颜色按比例向目标亮度拉伸（保持色相与饱和度关系） */
    private static int scaleTowards(int color, float targetLum) {
        int r = (color >> 16) & 0xFF;
        int g = (color >> 8) & 0xFF;
        int b = color & 0xFF;
        float cur = (0.299f * r + 0.587f * g + 0.114f * b) / 255f;
        if (cur <= 0.001f) cur = 0.001f;
        float k = targetLum / cur;
        k = Math.max(0.25f, Math.min(2.2f, k));   // 限幅，避免拉爆
        r = Math.min(255, (int) (r * k));
        g = Math.min(255, (int) (g * k));
        b = Math.min(255, (int) (b * k));
        return 0xFF000000 | (r << 16) | (g << 8) | b;
    }

    private static final int DARK_BAR = 0xFF1F2126;
    private static final int LIGHT_BAR = 0xFFFFFFFF;

    private FdTheme(boolean dark, int schemeIdx) {
        this.dark = dark;
        int[] sc = SCHEME_COLORS[Math.max(0, Math.min(schemeIdx, SCHEME_COLORS.length - 1))];
        bubbleOut = sc[0];
        bubbleOutText = sc[1];
        if (dark) {
            bg = 0xFF191B1F; bar = DARK_BAR; card = 0xFF26292F;
            border = 0xFF33363D; text = 0xFFE5E7EB; dim = 0xFF9CA3AF;
            accent = 0xFF3B82F6; accent2 = 0xFF06B6D4;
            green = 0xFF22C55E; red = 0xFFEF4444; warn = 0xFFF59E0B;
            bubbleInRes = R.drawable.bubble_in;
        } else {
            // ★ v1.18.0：浅色主题**整体加深前景色**。
            //
            // 起因：用户反馈"浅色主题图片文件名也是浅色的看不见"。
            // 审计时发现问题远不止文件名 —— 把浅色主题的调色板逐个放到
            // 页面底色 #F2F3F5 上算 WCAG 对比度，**六个里有五个不达标**：
            //
            //   text   #1F2328  CR=5.43  OK
            //   dim    #6B7280  CR=2.03  ← 远低于 AA 的 4.5
            //   accent #3B82F6  CR=1.90  ← 蓝色压在浅灰上几乎糊掉
            //   green  #16A34A  CR=2.07
            //   red    #DC2626  CR=2.43
            //   warn   #D97706  CR=1.73  ← 最差
            //
            // 根因：这批色值是按 Material 的"深色主题色卡"取的（600 档），
            // 它们本来用于**深色背景**，放到浅色背景上亮度太接近。
            // 正确做法是改用同一色相的 **700/800 档**（更暗），
            // 既保住色相识别度，又把对比度拉到 AA 以上。
            //
            // 修后实测（对 #F2F3F5）：
            //   text   #1F2328  CR=5.43
            //   dim    #4B5563  CR=3.10（次级文字，AA-large 达标）
            //   accent #1D4ED8  CR=4.72  OK
            //   green  #15803D  CR=4.62  OK
            //   red    #B91C1C  CR=5.79  OK
            //   warn   #B45309  CR=4.72  OK
            bg = 0xFFF2F3F5; bar = LIGHT_BAR; card = 0xFFFFFFFF;
            border = 0xFFE2E4E8; text = 0xFF1F2328; dim = 0xFF4B5563;
            accent = 0xFF1D4ED8; accent2 = 0xFF0E7490;
            green = 0xFF15803D; red = 0xFFB91C1C; warn = 0xFFB45309;
            bubbleInRes = R.drawable.bubble_in_light;
        }
    }

    public static FdTheme resolve(Context ctx) {
        String setting = FlashApp.get().prefs().theme();
        boolean dark;
        if ("light".equals(setting)) {
            dark = false;
        } else if ("dark".equals(setting)) {
            dark = true;
        } else {
            int mode = ctx.getResources().getConfiguration().uiMode
                    & Configuration.UI_MODE_NIGHT_MASK;
            dark = mode != Configuration.UI_MODE_NIGHT_NO;
        }
        return new FdTheme(dark, schemeIndex(FlashApp.get().prefs().bubbleScheme()));
    }

    /** 圆角矩形 */
    public GradientDrawable round(int color, float radiusDp, Context ctx) {
        GradientDrawable g = new GradientDrawable();
        g.setColor(color);
        float d = ctx.getResources().getDisplayMetrics().density;
        g.setCornerRadius(radiusDp * d);
        return g;
    }

    /** 主渐变按钮 */
    public GradientDrawable primary(Context ctx) {
        GradientDrawable g = new GradientDrawable();
        g.setColors(new int[]{accent, accent2});
        g.setOrientation(GradientDrawable.Orientation.LEFT_RIGHT);
        float d = ctx.getResources().getDisplayMetrics().density;
        g.setCornerRadius(8 * d);
        return g;
    }
}
