package com.flashdrop.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.Bundle;
import android.text.TextUtils;
import android.text.util.Linkify;
import android.util.TypedValue;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.util.ArrayList;

/** 设置页（紧凑单屏）：设备名 / 主题+配色 / 开关 / 端口 / 记录管理 / 关于 */
public class SettingsActivity extends Activity {

    /** 隐藏入口：连点"关于卡"多少次打开崩溃日志 */
    private static final int HIDE_TAPS = 10;

    private FdTheme theme;
    /** v1.11.0：根 ScrollView，进出场动效作用在它上面 */
    private ScrollView rootScroll;
    private EditText nameEdit, portEdit;
    private Switch autoSwitch, notifySwitch, notifShowSwitch, autoStartSwitch, encryptSwitch;
    // ★ v1.18.9 新增：离线聊天（视图层） / 保存聊天（数据层），二者正交
    private Switch offlineChatSwitch, keepHistorySwitch;
    // ★ v1.18.0：animSwitch 已移除 —— 界面动效不再提供设置开关，
    // 默认全局启用（用户要求「界面动效不需要预留设置开关，默认就是全局使用」）。
    private final java.util.List<android.net.Uri> pendingDeleteUris = new java.util.ArrayList<>();
    private static final int REQ_CONFIRM_DELETE = 31;
    private Spinner themeSpinner, schemeSpinner;

    private int dp(float v) {
        return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP,
                v, getResources().getDisplayMetrics());
    }

    private TextView label(String s) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextColor(theme.dim);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        t.setPadding(0, dp(14), 0, dp(6));
        return t;
    }

    /**
     * 设置项之间的**轻度分隔线**（v1.18.0）。
     *
     * 用户反馈：「设置里面的选项没有界限区分，应该加一个轻度的界限来区分各设置项」。
     * 此前所有开关（自动接收 / 提示 / 常驻通知 / 开机自启 / 传输加密）都是
     * 上下紧贴的整行文本 + Switch，视觉上连成一片，用户分不清哪一行算一项。
     *
     * 做法（对齐微信 / 系统设置的"分组列表"观感）：
     *   · 一条 **1px** 高、**左右缩进 2dp**、颜色取主题 border 的细线；
     *   · 线色不额外加深，直接用 theme.border —— 浅色下是 #E2E4E8，
     *     深色下是 #33363D，都是"刚好能看见但不抢眼"的轻度界限；
     *   · 上下各留 0 间距，让线紧贴相邻两项，形成明确的分隔而不撑高页面。
     *
     * 注意：**不是**每两项之间都塞 —— 只在语义分组处插线（见 onCreate），
     * 否则整页会变成"斑马纹"，反而更乱。
     */
    private View divider() {
        View line = new View(this);
        line.setBackgroundColor(theme.border);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, Math.max(1, dp(1)));
        lp.leftMargin = dp(2);
        lp.rightMargin = dp(2);
        line.setLayoutParams(lp);
        return line;
    }

    private GradientDrawable inputBg() {
        return theme.round(theme.card, 10, this);
    }

    private Switch makeSwitch(String s) {
        Switch sw = new Switch(this);
        sw.setText(s);
        sw.setTextColor(theme.text);
        sw.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
        sw.setPadding(0, dp(10), 0, dp(10));
        sw.setSwitchMinWidth(dp(48));
        return sw;
    }

    /**
     * 单行输入类控件的内容高度基准（dp）。
     *
     * ★ v1.17.0 新增：统一「下拉框」与「输入框」的高度。
     *
     * 用户反馈「选择框的高度与设备名称填充的框高度不一致」。
     * 根因：两者各自算高度 ——
     *   EditText：14sp 文字 + 上下各 11dp 内边距 → 约 46dp
     *   Spinner ：14sp 文字 + 上下各 6dp 内边距，但**下拉项 View**
     *             (getView 里的 tv.setPadding(4,8,4,8)) 又会顶大它的
     *             测量高度，且 Spinner 自身还带系统默认的最小高度 →
     *             最终约 40dp，比输入框矮一截，并排就明显不齐。
     *
     * 修法：给两者一个**共同的最小高度**，并让 Spinner 的 item View
     * 不再叠加额外上下内边距（只留左右），高度就完全由本常量决定。
     */
    private static final int ROW_MIN_DP = 46;

    private Spinner makeSpinner(String[] items) {
        Spinner sp = new Spinner(this);
        ArrayAdapter<String> sa = new ArrayAdapter<>(this,
                android.R.layout.simple_spinner_dropdown_item, items) {
            @Override
            public View getView(int position, View convertView, ViewGroup parent) {
                TextView tv = (TextView) super.getView(position, convertView, parent);
                tv.setTextColor(theme.text);
                tv.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
                // ★ v1.17.0：合并模式下不再加**上下**内边距 ——
                // 高度交给外层 Spinner 的 minHeight 统一决定，
                // 否则这里的 padding 会把 Spinner 顶得比输入框高/矮。
                tv.setPadding(dp(4), 0, dp(4), 0);
                tv.setMinHeight(0);
                tv.setMinimumHeight(0);
                return tv;
            }
            @Override
            public View getDropDownView(int position, View convertView, ViewGroup parent) {
                TextView tv = (TextView) super.getDropDownView(position, convertView, parent);
                tv.setTextColor(theme.text);
                // 弹层里保留宽松的行高，便于点选
                tv.setPadding(dp(12), dp(12), dp(12), dp(12));
                return tv;
            }
        };
        sp.setAdapter(sa);
        sp.setBackground(inputBg());
        // 左右 10dp + 上下 0（高度由 minHeight 统一）
        sp.setPadding(dp(10), 0, dp(10), 0);
        sp.setMinimumHeight(dp(ROW_MIN_DP));
        sp.setPopupBackgroundDrawable(theme.round(theme.card, 10, this));
        return sp;
    }

    private EditText makeInput() {
        EditText e = new EditText(this);
        e.setTextColor(theme.text);
        e.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
        e.setBackground(inputBg());
        e.setPadding(dp(12), dp(11), dp(12), dp(11));
        // ★ v1.17.0：与 Spinner 共用同一最小高度，两框并排严丝合缝
        e.setMinimumHeight(dp(ROW_MIN_DP));
        return e;
    }

    /** 危险操作按钮（红色描边） */
    private Button mkDangerButton(String text) {
        Button b = new Button(this);
        b.setText(text);
        b.setTextColor(theme.red);
        b.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        GradientDrawable dg = theme.round(0x00000000, 10, this);
        dg.setStroke(dp(1), theme.red);
        b.setBackground(dg);
        b.setPadding(0, dp(11), 0, dp(11));
        return b;
    }

    /**
     * v1.10.1：原「打开保存位置」（直接跳文件管理器）改为「查看保存位置」。
     *
     * 为什么不能直接跳（用户实测"选了文件管理器又弹回设置"，已确认无法修复）：
     *   接收目录是公共 Download/FlashDrop。本应用无权用 FileProvider 暴露它 ——
     *   FdFileProvider 只能 openFile 单个文件，不支持目录浏览；
     *   唯一可行的跳转是把 content://com.android.externalstorage.documents/...
     *   交给目标应用，而国产 ROM 的第三方文件管理器普遍不实现 DocumentsContract，
     *   于是"能打开文件管理器、随即立刻弹回本应用"，比不提供更糟。
     * 改为：明确展示真实路径 + 列出各设备子目录及文件数 + 一键复制路径，
     * 用户在任意文件管理器地址栏粘贴即可直达，100% 可用。
     */
    private void showSaveLocation() {
        final String root = FdUtil.saveRootDesc();
        // 列出 Download/FlashDrop 下已有的设备子目录（用户最关心"文件在哪台设备名下"）
        java.util.List<String> folders = new ArrayList<>();
        try {
            File dir = FdUtil.legacySaveDir();
            File[] fs = dir == null ? null : dir.listFiles();
            if (fs != null) {
                for (File f : fs) {
                    if (!f.isDirectory()) continue;
                    int[] c = FdUtil.countSavedFiles(this, f.getName());
                    folders.add(f.getName() + "（" + c[0] + " 个文件）");
                }
            }
        } catch (Exception ignored) {}
        java.util.Collections.sort(folders);

        StringBuilder sb = new StringBuilder();
        sb.append("接收的文件保存在：\n\n").append(root).append("/<设备名>\n\n");
        if (folders.isEmpty()) {
            sb.append("还没有收到过文件。\n\n");
        } else {
            sb.append("已有目录：\n");
            for (String f : folders) sb.append("· ").append(f).append('\n');
            sb.append('\n');
        }
        sb.append("点「复制路径」后，在任意文件管理器的地址栏粘贴即可打开。");

        // ★ v1.16.0：换成微信风格对话框
        FdDialog.show(this, "保存位置", sb.toString(),
                "复制路径", "关闭", () -> copySavePath(root), null, false);
    }

    /** 把接收目录的绝对路径复制到剪贴板，供文件管理器地址栏粘贴 */
    private void copySavePath(String rootDesc) {
        String abs = android.os.Environment.getExternalStoragePublicDirectory(
                android.os.Environment.DIRECTORY_DOWNLOADS).getAbsolutePath() + "/FlashDrop";
        try {
            android.content.ClipboardManager cm =
                    (android.content.ClipboardManager) getSystemService(
                            android.content.Context.CLIPBOARD_SERVICE);
            if (cm == null) throw new IllegalStateException("no clipboard");
            // 优先复制绝对路径（各 ROM 都能粘贴）；失败则退回相对目录名
            cm.setPrimaryClip(android.content.ClipData.newPlainText("savepath", abs));
            Toast.makeText(this, "已复制路径：" + abs + "\n在文件管理器地址栏粘贴即可打开",
                    Toast.LENGTH_LONG).show();
        } catch (Exception e) {
            try {
                android.content.ClipboardManager cm =
                        (android.content.ClipboardManager) getSystemService(
                                android.content.Context.CLIPBOARD_SERVICE);
                if (cm == null) throw new IllegalStateException("no clipboard");
                cm.setPrimaryClip(android.content.ClipData.newPlainText("savepath", "FlashDrop"));
                Toast.makeText(this, "已复制「FlashDrop」，在文件管理器里搜索即可",
                        Toast.LENGTH_LONG).show();
            } catch (Exception e2) {
                Toast.makeText(this, "复制失败，请手动查找：" + rootDesc,
                        Toast.LENGTH_LONG).show();
            }
        }
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        Prefs prefs = FlashApp.get().prefs();
        theme = FdTheme.resolve(this);

        ScrollView scroll = new ScrollView(this);
        scroll.setBackgroundColor(theme.bg);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(20), dp(14), dp(20), dp(28));

        TextView title = new TextView(this);
        title.setText("设置");
        title.setTextColor(theme.text);
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 20);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setPadding(0, 0, 0, dp(10));
        root.addView(title);

        root.addView(label("设备名称"));
        nameEdit = makeInput();
        nameEdit.setText(prefs.name(FdUtil.defaultDeviceName(this)));
        root.addView(nameEdit);

        // 主题 + 配色 同一行
        //
        // ★ v1.17.0 修正文案：原来写的是「界面主题　／　气泡配色（…）」——
        // 两个词之间用了全角空格(U+3000) + 全角斜杠(／) + 全角空格，
        // 三个全角字符叠加在一起，字面上就是"界面主题　　　／　　　气泡配色"，
        // 渲染出来两个词被拉开一大截（用户反馈"中间的斜杠显示有问题，
        // 导致两个文案距离过远"）。
        // 改为半角「/」加两个普通空格，间距恢复正常、与其余标签风格一致。
        root.addView(label("界面主题 / 气泡配色（发送的消息将带上你的配色）"));
        LinearLayout spinRow = new LinearLayout(this);
        spinRow.setOrientation(LinearLayout.HORIZONTAL);
        // ★ v1.17.0：两个下拉框都按 ROW_MIN_DP 等高（与设备名称输入框一致），
        // 行容器也固定同高，避免因子 View 高度差异导致上下留白不匀。
        spinRow.setMinimumHeight(dp(ROW_MIN_DP));
        themeSpinner = makeSpinner(new String[]{"跟随系统", "深色", "浅色"});
        themeSpinner.setSelection("dark".equals(prefs.theme()) ? 1
                : "light".equals(prefs.theme()) ? 2 : 0);
        spinRow.addView(themeSpinner, new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        schemeSpinner = makeSpinner(FdTheme.SCHEME_NAMES);
        schemeSpinner.setSelection(FdTheme.schemeIndex(prefs.bubbleScheme()));
        LinearLayout.LayoutParams slp = new LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        slp.leftMargin = dp(10);
        spinRow.addView(schemeSpinner, slp);
        root.addView(spinRow);

        autoSwitch = makeSwitch("自动接收文件");
        autoSwitch.setChecked(prefs.autoAccept());
        root.addView(autoSwitch);
        root.addView(divider());

        notifySwitch = makeSwitch("收到消息时提示");
        notifySwitch.setChecked(prefs.notifyOnReceive());
        root.addView(notifySwitch);
        root.addView(divider());

        notifShowSwitch = makeSwitch("显示常驻通知（关闭后服务仍保持在线）");
        notifShowSwitch.setChecked(prefs.showServiceNotification());
        root.addView(notifShowSwitch);
        root.addView(divider());

        autoStartSwitch = makeSwitch("开机自启（手机重启后自动恢复接收服务）");
        autoStartSwitch.setChecked(prefs.autoStart());
        root.addView(autoStartSwitch);
        root.addView(divider());

        encryptSwitch = makeSwitch("传输加密（TLS）：两端都开启时加密通信，未开启自动回退明文");
        encryptSwitch.setChecked(prefs.encrypt());
        root.addView(encryptSwitch);
        root.addView(divider());

        // ★ v1.18.9 新增（用户第 5 条需求）：「离线聊天」开关。
        //
        // 与「保存聊天」并存，两者职责正交（见 Prefs.offlineChat 注释）：
        //   · 保存聊天 → 数据层：是否把聊天记录写盘
        //   · 离线聊天 → 视图/交互层：是否展示并使用离线能力
        //     开启后：不在同一网络的设备仍留在设备选择框（灰色状态点），
        //             点进去能看历史、能发离线消息，设备上线自动送达。
        //     关闭后：只显示当前在线设备，界面更干净。
        offlineChatSwitch = makeSwitch("离线聊天（保留对话框：显示离线设备、可发离线消息、可看历史）");
        offlineChatSwitch.setChecked(prefs.offlineChat());
        root.addView(offlineChatSwitch);
        root.addView(divider());

        keepHistorySwitch = makeSwitch("保存聊天（关闭后不再记录新的聊天内容）");
        keepHistorySwitch.setChecked(prefs.keepHistory());
        root.addView(keepHistorySwitch);

        // ★ v1.18.0：**移除「界面动效」开关**。
        //
        // 用户要求：「界面动效不需要预留设置开关，默认就是全局使用」。
        // 原来的 animSwitch 已删除；FdAnim 侧仍走 Prefs.animations()，
        // 那里默认值就是 true（见 Prefs.animations() 的 getBoolean 默认参），
        // 且**保存设置时不再写入**该键，于是动效恒定全局开启。
        // 系统层面已关动画（开发者选项 → 动画时长 = 0）时，
        // FdAnim.enabled() 会自行尊重，无需应用内再给开关。

        // 端口 + 保存位置说明 同一段
        root.addView(label("服务端口（修改后需重启应用） · 接收文件保存在 下载/FlashDrop"));
        LinearLayout portRow = new LinearLayout(this);
        portRow.setOrientation(LinearLayout.HORIZONTAL);
        portRow.setGravity(android.view.Gravity.CENTER_VERTICAL);
        portEdit = makeInput();
        portEdit.setInputType(android.text.InputType.TYPE_CLASS_NUMBER);
        portEdit.setText(String.valueOf(prefs.port(FdProto.DEFAULT_PORT)));
        LinearLayout.LayoutParams plp = new LinearLayout.LayoutParams(0,
                ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        portRow.addView(portEdit, plp);
        TextView saveDesc = new TextView(this);
        saveDesc.setText("保存位置\n由系统管理");
        saveDesc.setTextColor(theme.dim);
        saveDesc.setTextSize(TypedValue.COMPLEX_UNIT_SP, 11);
        saveDesc.setPadding(dp(14), 0, 0, 0);
        portRow.addView(saveDesc, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.MATCH_PARENT));
        root.addView(portRow);

        // 数据清理：v1.10.0 把原来四个按钮（清空聊天记录/删除下载文件/删除下载图片/打开保存目录）
        // 合并成一个「数据清理」，点击后弹窗多选三类 + 全选 + 取消/删除。
        // 之前四个按钮"点了没反应"的真实原因：mkDangerButton 用 setBackground 覆盖了
        // 系统 Button 背景后没有配套 setClickable/前景色，部分 ROM 上自定义
        // GradientDrawable 按钮的点击态不响应；这里改用带标题的整行卡片式按钮，
        // 并保证 setOnClickListener 在设置背景之后再挂一次。
        root.addView(label("数据清理 · 接收的文件按设备分文件夹保存在 "
                + FdUtil.saveRootDesc() + "/<设备名>"));

        final Button clean = mkDangerButton("数据清理");
        clean.setText("数据清理 （聊天记录 / 下载文件 / 接收图片）");
        clean.setOnClickListener(v -> onDataClean());
        LinearLayout.LayoutParams clp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        clp.topMargin = dp(2);
        root.addView(clean, clp);

        // 保存位置：不再是清理动作，独立成一个低调的文字入口
        TextView openDir = new TextView(this);
        openDir.setText("查看保存位置（" + FdUtil.saveRootDesc() + "）");
        openDir.setTextColor(theme.accent);
        openDir.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        openDir.setPadding(dp(2), dp(14), dp(2), dp(4));
        openDir.setClickable(true);
        openDir.setOnClickListener(v -> showSaveLocation());
        root.addView(openDir);

        // 关于卡（与电脑端一致：名称版本 + 说明 + 作者联系，邮箱可点击）
        TextView about = new TextView(this);
        about.setText("闪传 FlashDrop v" + FdUtil.APP_VERSION
                + "\n局域网文件与消息互传工具\n"
                + "作者：" + FdUtil.APP_AUTHOR + "\n联系：" + FdUtil.APP_CONTACT);
        about.setTextColor(theme.text);
        about.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        about.setLineSpacing(dp(2), 1f);
        about.setPadding(dp(14), dp(12), dp(14), dp(12));
        about.setBackground(theme.round(theme.card, 10, this));
        about.setAutoLinkMask(Linkify.EMAIL_ADDRESSES);
        about.setLinkTextColor(theme.accent);
        LinearLayout.LayoutParams alp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        alp.topMargin = dp(18);
        root.addView(about, alp);

        // 隐藏入口：连续点击"关于卡"10 次打开崩溃日志（普通用户不会触发）
        about.setClickable(true);
        final int[] taps = {0};
        final long[] lastTap = {0};
        about.setOnClickListener(v -> {
            long now = System.currentTimeMillis();
            // 间隔超过 3 秒视为重新开始，避免日常误触累积计数
            if (now - lastTap[0] > 3000) taps[0] = 0;
            lastTap[0] = now;
            taps[0]++;
            if (taps[0] >= HIDE_TAPS) {
                taps[0] = 0;          // 触发后计数归零，再点 10 次可再次打开
                CrashTrap.showDialog(SettingsActivity.this);
            } else if (HIDE_TAPS - taps[0] <= 3) {
                // 最后 3 次给轻微提示，避免用户以为按钮坏了
                Toast.makeText(this,
                        "再点击 " + (HIDE_TAPS - taps[0]) + " 次…",
                        Toast.LENGTH_SHORT).show();
            }
        });

        // ★ v1.18.30：检查更新（GitHub Releases，与 Windows 端同源）
        final Button btnUpdate = new Button(this);
        btnUpdate.setText("检查更新");
        btnUpdate.setTextColor(theme.accent);
        btnUpdate.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
        btnUpdate.setAllCaps(false);
        btnUpdate.setBackground(theme.round(theme.card, 10, this));
        btnUpdate.setPadding(dp(14), dp(10), dp(14), dp(10));
        LinearLayout.LayoutParams ulp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        ulp.topMargin = dp(10);
        root.addView(btnUpdate, ulp);
        btnUpdate.setOnClickListener(v -> onCheckUpdate(btnUpdate));

        Button save = new Button(this);
        save.setText("保存设置");
        save.setTextColor(0xFFFFFFFF);
        save.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        save.setTypeface(Typeface.DEFAULT_BOLD);
        save.setBackground(theme.primary(this));
        save.setPadding(0, dp(12), 0, dp(12));
        LinearLayout.LayoutParams blp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        blp.topMargin = dp(24);
        root.addView(save, blp);
        // v1.11.0：保存键按压反馈
        save.setOnTouchListener((v, ev) -> {
            int a = ev.getActionMasked();
            if (a == android.view.MotionEvent.ACTION_DOWN) FdAnim.pressDown(v);
            else if (a == android.view.MotionEvent.ACTION_UP
                    || a == android.view.MotionEvent.ACTION_CANCEL) FdAnim.pressUp(v);
            return false;
        });
        save.setOnClickListener(v -> onSave());

        scroll.addView(root);
        setContentView(scroll);
        rootScroll = scroll;

        // v1.11.0：设置页进入动效（淡入 + 轻微上移落位）
        try {
            scroll.post(() -> FdAnim.activityEnter(scroll));
        } catch (Throwable ignored) {}
    }

    /**
     * v1.11.0：返回时先播退出动效再 finish，避免"啪"一下硬切。
     * 返回键（onBackPressed）与左上角返回按钮共用。
     */
    @Override
    public void onBackPressed() {
        try {
            FdAnim.activityExit(this, rootScroll, null);
        } catch (Throwable t) {
            super.onBackPressed();
        }
    }

    /** 清理分类：与主界面删除弹窗同一套口径 */
    private static final int CAT_FILE = 0, CAT_IMAGE = 1, CAT_CHAT = 2, CAT_ORPHAN = 3;
    private static final String[] CAT_NAMES = {
            "下载文件", "接收图片（未保存到图库）", "聊天记录",
            "失效文件卡片（文件已被删除）"};

    /**
     * 「数据清理」：全局作用域（app 内所有连接设备），三类多选 + 全选 + 取消/删除。
     * v1.10.0 把 v1.8.0 的四个独立按钮合并到这里。
     */
    private void onDataClean() {
        // 实时统计：让用户看得见每一类到底有多少条，避免"点了没反应也不知道删了什么"
        // ★ v1.18.27：第四类「失效文件卡片」—— 文件已经被删掉（文件管理器 / 上一次
        //   清理 / 系统清理），但聊天记录还留着的空卡片。用户实测：清理完文件后
        //   这些卡片还在、并且仍显示"已保存"，必须能一并清掉。
        final int[] disk = FdUtil.countSavedFiles(this, null);
        final int chatN = FdUtil.countHistory(this, true);
        final int orphanN = FdUtil.countOrphanFileMsgs(this);
        final int[] counts = new int[]{
                disk[0] - disk[1],   // 非图片文件
                disk[1],             // 图片
                chatN,
                orphanN};            // 失效的文件卡片
        int total = counts[0] + counts[1] + counts[2] + counts[3];
        if (total == 0) {
            FdDialog.info(this, "数据清理",
                    "本机暂无聊天记录，也没有已接收的文件。", "知道了", null);
            return;
        }

        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(20), dp(10), dp(20), 0);

        final android.widget.CheckBox[] checks = new android.widget.CheckBox[4];
        for (int c = 0; c < 4; c++) {
            android.widget.CheckBox cb = new android.widget.CheckBox(this);
            cb.setText(CAT_NAMES[c] + "（" + counts[c] + "）");
            cb.setTextColor(theme.text);
            cb.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
            cb.setPadding(0, dp(6), 0, dp(6));
            cb.setChecked(false);            // 默认不选择
            cb.setEnabled(counts[c] > 0);    // 没有内容的分类不可勾选
            if (counts[c] == 0) cb.setTextColor(theme.dim);
            checks[c] = cb;
            box.addView(cb);
        }

        TextView tip = new TextView(this);
        tip.setText("清理范围：本机所有连接设备的聊天记录与已接收文件，不可恢复");
        tip.setTextColor(theme.dim);
        tip.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        tip.setPadding(dp(2), dp(10), dp(2), 0);
        box.addView(tip);

        // 全选按钮：只切换勾选态，不直接删除
        final Button btnAll = new Button(this);
        btnAll.setText("全选");
        btnAll.setTextColor(theme.accent);
        btnAll.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        GradientDrawable abg = theme.round(0x00000000, 8, this);
        abg.setStroke(dp(1), theme.accent);
        btnAll.setBackground(abg);
        btnAll.setPadding(0, dp(8), 0, dp(8));
        final boolean[] allOn = {false};
        btnAll.setOnClickListener(v -> {
            allOn[0] = !allOn[0];
            for (int c = 0; c < 4; c++) {
                if (counts[c] > 0) checks[c].setChecked(allOn[0]);
            }
            btnAll.setText(allOn[0] ? "取消全选" : "全选");
        });
        LinearLayout.LayoutParams allLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        allLp.topMargin = dp(8);
        box.addView(btnAll, allLp);

        FdDialog.custom(this, "数据清理", null, box, "删除", "取消", true, () -> {
            final boolean delFile = checks[CAT_FILE].isChecked();
            final boolean delImg = checks[CAT_IMAGE].isChecked();
            final boolean delChat = checks[CAT_CHAT].isChecked();
            final boolean delOrphan = checks[CAT_ORPHAN].isChecked();
            if (!delFile && !delImg && !delChat && !delOrphan) {
                Toast.makeText(this, "请先勾选要清理的内容", Toast.LENGTH_SHORT).show();
                return;
            }
            StringBuilder what = new StringBuilder();
            if (delFile) what.append("· 下载文件 ").append(counts[CAT_FILE]).append(" 个\n");
            if (delImg) what.append("· 接收图片 ").append(counts[CAT_IMAGE]).append(" 个\n");
            if (delChat) what.append("· 聊天记录 ").append(counts[CAT_CHAT]).append(" 条\n");
            // 删文件后必然产生失效卡片，一并清掉（不再留"显示已保存却打不开"的空卡片）
            if (delOrphan || delFile || delImg) {
                what.append("· 失效文件卡片（文件已删除的记录，自动清理）\n");
            }
            FdDialog.danger(this, "再次确认",
                    "确定清理以下内容吗？\n\n" + what + "\n删除后不可恢复。",
                    "删除", () -> runDataClean(delFile, delImg, delChat, delOrphan));
        });
    }

    /** 执行全局清理：聊天记录清空 + 按类型删已接收文件 + 清失效文件卡片 */
    private void runDataClean(boolean delFile, boolean delImg, boolean delChat,
                              boolean delOrphan) {
        pendingDeleteUris.clear();
        new Thread(() -> {
            int orphan = 0;
            if (delChat) {
                FdUtil.clearAllHistory(this);
                FlashApp.get().historyCleared = true;
            }
            int files = 0;
            boolean failed = false;
            if (delFile) {
                int[] r = FdUtil.deleteSavedFiles(this, null, Boolean.FALSE, pendingDeleteUris);
                if (r[0] < 0) failed = true; else files += r[0];
            }
            if (delImg) {
                int[] r = FdUtil.deleteSavedFiles(this, null, Boolean.TRUE, pendingDeleteUris);
                if (r[0] < 0) failed = true; else files += r[0];
            }
            // ★ v1.18.27：文件删掉后对应的记录就成了"空文件卡片" —— 一并清掉。
            //   只要勾了文件/图片/失效卡片任一项都执行（删文件必然产生失效卡片）。
            if (delOrphan || delFile || delImg) {
                // ★ v1.18.28：文件刚被删 → 索引快照已过期，必须重建后再判失效，
                //   否则会把"还在的文件"误判成失效、把记录错删掉。
                FdUtil.invalidateSavedIndex();
                orphan = FdUtil.purgeOrphanFileMsgs(this);
                if (orphan > 0) FlashApp.get().historyCleared = true;   // 回主界面重载
            }
            final int nOrphan = orphan;
            final int nf = files;
            final boolean f = failed;
            runOnUiThread(() -> {
                // 非本应用创建的文件需要系统确认才能删（Android 11+）
                if (!pendingDeleteUris.isEmpty() && android.os.Build.VERSION.SDK_INT >= 30) {
                    try {
                        android.app.PendingIntent pi =
                                android.provider.MediaStore.createDeleteRequest(
                                        getContentResolver(),
                                        new java.util.ArrayList<>(pendingDeleteUris));
                        startIntentSenderForResult(pi.getIntentSender(),
                                REQ_CONFIRM_DELETE, null, 0, 0, 0);
                    } catch (Exception e) {
                        Toast.makeText(this, "部分文件删除失败：" + e,
                                Toast.LENGTH_LONG).show();
                    }
                    return;
                }
                StringBuilder sb = new StringBuilder("清理完成：");
                if (nf > 0) sb.append(nf).append(" 个文件");
                if (delChat) {
                    if (nf > 0 || nOrphan > 0) sb.append("、");
                    sb.append("全部聊天记录");
                }
                if (nOrphan > 0) {
                    if (nf > 0 || delChat) sb.append("、");
                    sb.append(nOrphan).append(" 条失效文件卡片");
                }
                if (nf == 0 && !delChat && nOrphan == 0) {
                    Toast.makeText(this, "未找到可清理的内容", Toast.LENGTH_LONG).show();
                } else if (f) {
                    Toast.makeText(this, sb + "（部分文件删除失败，请检查存储权限）",
                            Toast.LENGTH_LONG).show();
                } else {
                    Toast.makeText(this, sb, Toast.LENGTH_LONG).show();
                }
            });
        }).start();
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, android.content.Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQ_CONFIRM_DELETE) {
            if (resultCode == RESULT_OK) {
                Toast.makeText(this, "已删除全部文件", Toast.LENGTH_LONG).show();
            } else {
                Toast.makeText(this, "已取消，部分文件未删除", Toast.LENGTH_LONG).show();
            }
        }
    }


    // ---------- ★ v1.18.30：检查更新（GitHub Releases） ----------

    /** 手动检查：失败明确提示（不静默），有新版本弹更新对话框。 */
    private void onCheckUpdate(Button btn) {
        btn.setEnabled(false);
        btn.setText("正在检查…");
        UpdateChecker.check(info -> {
            btn.setEnabled(true);
            btn.setText("检查更新");
            if (info == null) {
                // 国内直连 GitHub 常超时/被限流：明确告知，不静默吞掉
                Toast.makeText(this,
                        "检查失败：网络不可达或 GitHub 限流，请稍后重试",
                        Toast.LENGTH_LONG).show();
                return;
            }
            String ver = info.optString("version", "");
            if (!UpdateChecker.isNewer(ver, FdUtil.APP_VERSION)) {
                FdDialog.info(this, "检查更新",
                        "当前已是最新版本 v" + FdUtil.APP_VERSION, "知道了", null);
                return;
            }
            UpdateChecker.showUpdateDialog(this, info);
        });
    }

    private void onSave() {
        Prefs prefs = FlashApp.get().prefs();
        String name = nameEdit.getText().toString().trim();
        if (!name.isEmpty()) {
            prefs.setName(name);
            FlashApp.get().node().setName(name);
        }
        String themeSel = themeSpinner.getSelectedItemPosition() == 1 ? "dark"
                : themeSpinner.getSelectedItemPosition() == 2 ? "light" : "system";
        prefs.setTheme(themeSel);
        prefs.setBubbleScheme(FdTheme.SCHEME_KEYS[
                Math.max(0, schemeSpinner.getSelectedItemPosition())]);
        prefs.setAutoAccept(autoSwitch.isChecked());
        prefs.setNotifyOnReceive(notifySwitch.isChecked());
        prefs.setAutoStart(autoStartSwitch.isChecked());
        prefs.setEncrypt(encryptSwitch.isChecked());
        // ★ v1.18.9：两个新开关（正交，各自独立保存）
        prefs.setOfflineChat(offlineChatSwitch.isChecked());
        prefs.setKeepHistory(keepHistorySwitch.isChecked());
        // ★ v1.18.0：不再写入动效开关。
        // 界面动效已改为全局常开（Prefs.animations() 默认 true），
        // 这里刻意**不调用 setAnimations**，让该偏好保持默认值。
        // 若用户曾装过旧版本并关过动效，其 sp 里遗留的 anim_enabled=false
        // 会继续生效 —— 所以下面主动清一次，确保升级用户也拿到全局动效。
        prefs.setAnimations(true);
        // 常驻通知开关变化 → 重启前台服务使通知立即切换
        boolean showNotif = notifShowSwitch.isChecked();
        if (showNotif != prefs.showServiceNotification()) {
            prefs.setShowServiceNotification(showNotif);
            Intent it = new Intent(this, NodeService.class);
            stopService(it);
            if (Build.VERSION.SDK_INT >= 26) startForegroundService(it);
            else startService(it);
        }
        try {
            int port = Integer.parseInt(portEdit.getText().toString().trim());
            if (port >= 1024 && port <= 65535 && port != prefs.port(FdProto.DEFAULT_PORT)) {
                prefs.setPort(port);
                Toast.makeText(this, "端口已保存，重启应用后生效", Toast.LENGTH_LONG).show();
            }
        } catch (NumberFormatException ignored) {}
        Toast.makeText(this, "已保存", Toast.LENGTH_SHORT).show();
        finish();
    }
}
