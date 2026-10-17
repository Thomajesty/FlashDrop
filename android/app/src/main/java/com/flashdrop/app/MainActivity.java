package com.flashdrop.app;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.MediaStore;
import android.text.TextUtils;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.BaseAdapter;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.ProgressBar;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.Date;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/**
 * 主界面：微信文件助手式单列表聊天 + 目标选择（全部设备/单台）。
 * 支持：长按复制/删除、多选删除、＋弹出相册/拍照/文件、主题跟随系统。
 */
public class MainActivity extends Activity {

    private static final int REQ_PERMS = 11;
    private static final int REQ_PICK_FILES = 21;
    private static final int REQ_PICK_ALBUM = 22;
    private static final int REQ_CAMERA = 23;
    /** v1.11.0：全屏图片查看器回传（删除后同步摘记录用）。包级可见供 ImageViewerActivity.start 使用 */
    static final int REQ_VIEWER = 31;

    private final Handler ui = new Handler(Looper.getMainLooper());
    private static final SimpleDateFormat TF =
            new SimpleDateFormat("HH:mm", Locale.getDefault());

    /**
     * v1.11.0：实现 Serializable。
     * 全屏图片查看器（ImageViewerActivity）需要拿到**真实的消息对象**才能：
     *   1) 算得出 keyOf()，删除后能把记录同步摘掉（否则删了文件还留气泡）；
     *   2) 拿到 m.path / m.open 精准删这一张，而不是把整个设备文件夹的图片都删掉。
     * 字段都是 String / long / double / List / Map / boolean，天然可序列化。
     */
    static class Msg implements java.io.Serializable {
        private static final long serialVersionUID = 1L;
        String kind = "text";       // text | file
        String dir = "in";          // in | out
        String peerId, peerName, mid, tid, text, file, mime, state, reason, path, open, src;
        String peerScheme = "";     // 发送方气泡配色（全局气泡，接收侧渲染用）
        long size, transferred, ts;
        double speed;
        /** ★ v1.18.18：断点续传/自动重试（UI 显示"重试中(第n次)"/"已收 n/m 块"） */
        int attempt, haveChunks, totalChunks;
        List<String> targets;
        Map<String, String> targetStates;
        boolean dialogShown;
        boolean appended;           // 是否已上屏（offer 预告不立即上屏）
        /** ★ v1.14.0：是否已写盘（用于状态变更时决定要不要 upsert 回磁盘）。
         *  不能用 appended —— 那是入场动画标记，渲染后立刻被置回 false。 */
        boolean persisted;

        /**
         * ★ v1.18.9：消息所属「频道」。
         *
         *   "group" —— 发到「全部设备」的群聊消息
         *   "p2p"   —— 端到端私聊（目标为某一台具体设备）
         *
         * 用于实现「全部设备 = 纯群聊视图」：群聊视图只汇总 group 消息，
         * 私聊内容**不在其中体现**（用户第 6 条需求）。
         * 老数据没有该字段 → 值为 null，按 p2p 处理（保守：宁可少显示，
         * 也不把私聊内容混进群聊）。
         */
        String channel;
    }

    private final Map<String, android.graphics.Bitmap> thumbCache = new HashMap<>();
    private final Set<String> loadingThumbs = new HashSet<>();

    private final List<Msg> msgs = new ArrayList<>();
    // 当前视图可见的消息（按设备选择栏过滤后的子集）。
    // msgs 始终是全量数据源；viewMsgs 只是"当前选中设备"的投影，
    // 这样切换设备时不需要重新读盘，消息/传输状态索引也能保持完整。
    private final List<Msg> viewMsgs = new ArrayList<>();
    private final Map<String, Msg> byTidIn = new HashMap<>();
    private final Map<String, Msg> byTidOut = new HashMap<>();
    private final Map<String, Msg> byMid = new HashMap<>();
    private final Map<String, JSONObject> peerMap = new HashMap<>();

    private FdTheme theme;
    private ListView chatList;
    private MsgAdapter adapter;
    private Spinner targetSpinner;
    private EditText input;
    private TextView onlineLabel;
    private TextView selfLabel;
    private View topBar, selBar, inputBar, actionBar, inputPill;
    private TextView selectCountLbl, emptyView;
    private View btnSettings, btnCamera;
    /** v1.18.10：输入栏「＋」左侧的表情按钮（常驻，输入文字时也不隐藏） */
    private View btnEmoji;
    /** 表情面板实例（首次点击时惰性创建） */
    private EmojiPicker emojiPicker;
    /** 正在插入表情（用于屏蔽 input 焦点回调误关面板），见 insertEmoji() */
    private boolean _insertingEmoji = false;
    // ★ v1.18.23：由 ImageButton 改为**复合容器**（ImageView 图标 + TextView “搜索”）
    private android.view.View btnRescan;
    private Button btnDelete, btnPending;
    // ★ v1.18.21 / v1.18.22：微信式搜索（会话界面内联，不弹窗）。
    //   搜索控件直接放在 sel_bar 内，由 toggleSearchBar 在原地切换显隐，
    //   不另用独立搜索行。
    private android.widget.EditText searchInput;
    private android.widget.ListView searchResultList;
    private final List<JSONObject> searchHits = new ArrayList<>();
    private android.widget.BaseAdapter searchAdapter;
    // ★ v1.18.25：设备态 ⇄ 搜索态 **原地形变**（行高/槽位/锚点全固定，只让该动的动）
    /** true=搜索态（设备选择器已退场，搜索框在场） */
    private boolean searchMode = false;
    /** 形变动画当前进度：0=设备态，1=搜索态 */
    private float searchF = 0f;
    private android.animation.ValueAnimator searchAnim;
    /** 中间按钮当前是否已是「搜全局」身份（避免每帧重复 setText） */
    private boolean morphIsGlobal = false;
    /**
     * ★ v1.18.26：换字时机（进度 0~1）。宽度必须在这个点**之前**长到位，
     * 否则 3 个字的「搜全局」在半宽按钮里会折行成两排（用户实测的抽搐）。
     */
    private static final float SWAP_F = 0.5f;
    /** 形变宽度缓存：删除 / 搜全局 两个身份的按钮宽 */
    private int btnDelW = 0, btnGlbW = 0;
    private View btnPlus, btnSend, btnExpand, panel;
    private List<String> spinnerIds = new ArrayList<>();
    /** 当前设备选择栏选中的 peer id；"__all__" 表示全部设备（汇总视图） */
    private String viewPeerId = "__all__";
    private static final String ALL_ID = "__all__";
    /** v1.13.1：来源设备未知的消息归档桶（协议缺 peer_id 时不丢记录） */
    private static final String LOCAL_ARCHIVE_ID = "__local__";
    /** 抑制 Spinner 回调（rebuildSpinner 内部重设 adapter/selection 时不触发切视图） */
    private boolean suppressSpinnerCb = false;
    /** v1.13.1：上一次已知的后台落库计数，用于 onResume 判断是否需要重载历史 */
    private int lastBgReloadCount = 0;

    // 多选状态
    private boolean selectMode = false;
    private final Set<String> selectedKeys = new HashSet<>();

    // 相机输出
    private Uri cameraUri;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        // 兜底：UI 初始化阶段的异常尽量不让界面直接消失（改为提示）
        android.util.Log.e("FlashDrop", "MainActivity.onCreate begin");
        setContentView(R.layout.activity_main);
        requestNeededPermissions();
        startForegroundServiceSafely();

        theme = FdTheme.resolve(this);
        topBar = findViewById(R.id.top_bar);
        selBar = findViewById(R.id.sel_bar);
        inputBar = findViewById(R.id.input_bar);
        actionBar = findViewById(R.id.action_bar);
        chatList = findViewById(R.id.chat_list);
        targetSpinner = findViewById(R.id.target_spinner);
        input = findViewById(R.id.input);
        onlineLabel = findViewById(R.id.online_label);
        selfLabel = findViewById(R.id.self_label);
        emptyView = findViewById(R.id.empty_view);
        selectCountLbl = findViewById(R.id.select_count);
        btnSettings = findViewById(R.id.btn_settings);
        btnRescan = findViewById(R.id.btn_rescan);
        searchInput = findViewById(R.id.search_input);
        searchResultList = findViewById(R.id.search_result_list);
        btnDelete = findViewById(R.id.btn_delete);
        btnPending = findViewById(R.id.btn_pending);
        btnCamera = findViewById(R.id.btn_camera);
        btnEmoji = findViewById(R.id.btn_emoji);
        btnPlus = findViewById(R.id.btn_plus);
        btnSend = findViewById(R.id.btn_send);
        btnExpand = findViewById(R.id.btn_expand);
        panel = findViewById(R.id.panel);
        // input_bar 本身就是输入胶囊容器（不再重复 findViewById，
        // 否则 applyTheme 里先 setBackgroundColor 再 setBackground 相互覆盖）
        inputPill = inputBar;

        // v1.11.0：所有可点控件统一挂按压反馈
        pressable(btnSettings); pressable(btnRescan); pressable(btnDelete);
        pressable(btnPending); pressable(btnCamera); pressable(btnEmoji);
        pressable(btnPlus);
        pressable(btnSend); pressable(btnExpand);
        pressable(findViewById(R.id.panel_album));
        pressable(findViewById(R.id.panel_camera));
        pressable(findViewById(R.id.panel_file));

        btnSettings.setOnClickListener(v ->
                startActivity(new Intent(this, SettingsActivity.class)));
        // ★ v1.18.23：🔍搜索 按钮 = 统一入口（进入搜索态 / 搜当前设备 / 收起还原）
        // ★ v1.18.25：「搜全局」不再是独立按钮 —— 由「删除」按钮原地形变成
        //   （见 toggleSearchBar / applySearchF），点击语义在按钮监听里按模式分流
        btnRescan.setOnClickListener(v -> onSearchClick());
        // ★ v1.18.21：搜索结果点击 = 跳转到该设备会话并**定位到该记录**
        searchResultList.setOnItemClickListener((parent, view, pos, id) -> {
            if (pos < 0 || pos >= searchHits.size()) return;
            JSONObject h = searchHits.get(pos);
            String pid = h.optString("pid", "");
            String mid = h.optString("mid", "");
            if (pid.isEmpty()) return;
            toggleSearchBar();               // 先收起搜索行
            onViewPeerChanged(pid);
            locateMsg(mid);
        });
        searchInput.setOnEditorActionListener((v, actionId, ev) -> {
            if (actionId == android.view.inputmethod.EditorInfo.IME_ACTION_SEARCH
                    || actionId == android.view.inputmethod.EditorInfo.IME_NULL) {
                runSearch(false);   // 回车 = 搜当前设备
                return true;
            }
            return false;
        });
        // ★ v1.18.18：该按钮自 v1.13.0 起闲置（待发送改为气泡内行内标记），
        //   现复用为「搜索聊天记录」入口 —— 位置在顶栏，不新增布局控件
        // ★ v1.18.21：btnPending 是 0dp 隐藏占位（v1.13.0 起），
        //   搜索入口统一为顶栏 🔍 图标按钮 + 会话内联搜索行；
        //   撤掉 v1.18.18 遗留的 emoji 文字（用户要求不用表情）
        btnPending.setOnClickListener(v -> toggleSearchBar());
        btnCamera.setOnClickListener(v -> pickFromGallery());
        // ★ v1.18.10（用户第 4 条）：表情面板。占输入法位置弹出，
        //   点击表情即插入输入框光标处，**不关闭面板**（可连续选多个，
        //   与微信一致）。再次点按钮或点输入框才收起。
        btnEmoji.setOnClickListener(v -> toggleEmojiPanel());
        btnPlus.setOnClickListener(v -> togglePanel());
        btnSend.setOnClickListener(v -> sendText());
        btnExpand.setOnClickListener(v -> openFullscreenInput());

        // 底部面板三项
        findViewById(R.id.panel_album).setOnClickListener(v -> {
            hidePanel();
            pickFromGallery();
        });
        findViewById(R.id.panel_camera).setOnClickListener(v -> {
            hidePanel();
            capturePhoto();
        });
        findViewById(R.id.panel_file).setOnClickListener(v -> {
            hidePanel();
            pickDocument();
        });

        // 输入内容变化：＋ ↔ 发送切换；超 3 行显示展开键
        input.addTextChangedListener(new android.text.TextWatcher() {
            @Override public void beforeTextChanged(CharSequence s, int a, int b, int c) {}
            @Override public void onTextChanged(CharSequence s, int a, int b, int c) {}
            @Override public void afterTextChanged(android.text.Editable s) {
                updateSendPlus();
                btnExpand.setVisibility(input.getLineCount() > 3 ? View.VISIBLE : View.GONE);
            }
        });
        // 输入框获得焦点/点击时收起底部面板与表情面板
        // ★ 注意：insertEmoji() 会 requestFocus()，若不加 _insertingEmoji 保护，
        //   焦点回调会把刚打开的表情面板立刻收掉 → 用户点一次就没了。
        input.setOnFocusChangeListener((v, hasFocus) -> {
            if (hasFocus && !_insertingEmoji) {
                hidePanel();
                hideEmojiPanel();      // 内部会顺带把图标复位成「表情」
                updateEmojiIcon();
            }
        });
        input.setOnClickListener(v -> {
            hidePanel();
            if (emojiPanelVisible()) hideEmojiPanel();
            updateEmojiIcon();
        });
        // 空文本长按 = 粘贴 / 全屏输入（插入点操作菜单）
        input.setCustomInsertionActionModeCallback(new android.view.ActionMode.Callback() {
            @Override public boolean onCreateActionMode(android.view.ActionMode mode, android.view.Menu menu) {
                menu.add("粘贴");
                menu.add("全屏输入");
                return true;
            }
            @Override public boolean onPrepareActionMode(android.view.ActionMode mode, android.view.Menu menu) {
                return false;
            }
            @Override public boolean onActionItemClicked(android.view.ActionMode mode, android.view.MenuItem item) {
                String t = String.valueOf(item.getTitle());
                if ("粘贴".equals(t)) {
                    ClipboardManager cm = getSystemService(ClipboardManager.class);
                    if (cm != null && cm.getPrimaryClip() != null) {
                        CharSequence clip = cm.getPrimaryClip().getItemAt(0).getText();
                        if (!TextUtils.isEmpty(clip)) {
                            int pos = Math.max(input.getSelectionStart(), 0);
                            input.getText().insert(pos, clip);
                        }
                    }
                    mode.finish();
                    return true;
                }
                if ("全屏输入".equals(t)) {
                    openFullscreenInput();
                    mode.finish();
                    return true;
                }
                return false;
            }
            @Override public void onDestroyActionMode(android.view.ActionMode mode) {}
        });

        findViewById(R.id.btn_sel_all).setOnClickListener(v -> selectAll());
        findViewById(R.id.btn_sel_del).setOnClickListener(v -> deleteSelected());
        findViewById(R.id.btn_sel_cancel).setOnClickListener(v -> exitSelectMode());

        // 设备选择栏 = 会话切换器（微信式）：选中哪台设备，聊天区就只显示那台的内容
        targetSpinner.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int pos, long id) {
                if (suppressSpinnerCb) return;
                String sel = pos >= 0 && pos < spinnerIds.size() ? spinnerIds.get(pos) : ALL_ID;
                onViewPeerChanged(sel);
            }
            @Override
            public void onNothingSelected(AdapterView<?> parent) {}
        });
        // ★ v1.18.20：恢复原生 Spinner 下拉切换（用户要求回到原交互，
        //   含下拉行的 ✕ 删除）。
        //   v1.18.18 的"下拉点击没反应"根因是**下拉行根视图挂了长按监听**
        //   （v1.18.19 已撤掉，下拉行恢复纯净触摸链路），不是 Spinner 本身，
        //   因此原生下拉可以放心恢复。
        //   v1.18.19 的对话框方案（showDevicePicker）保留代码但不再挂接，
        //   备注入口保留「长按收起态选择器」（不碰下拉 item 触摸链路）。
        targetSpinner.setOnLongClickListener(v -> {
            try {
                v.performHapticFeedback(
                        android.view.HapticFeedbackConstants.LONG_PRESS);
            } catch (Throwable ignored) {}
            String pid = viewPeerId;
            if (pid == null || ALL_ID.equals(pid)) {
                toast("长按某台设备的会话可设置备注（先在列表中切换到该设备）");
                return true;
            }
            showPeerActions(pid, safeNameOf(pid));
            return true;
        });

        // ★ v1.18.25：同一个按钮两种身份 —— 设备态=删除会话，搜索态=搜全局
        //   （「删除」在原地形变为「搜全局」，见 toggleSearchBar / applySearchF）
        btnDelete.setOnClickListener(v -> {
            if (searchMode) runSearch(true);
            else showDeletePicker();
        });

        adapter = new MsgAdapter();
        chatList.setAdapter(adapter);

        // ★ v1.18.5：**关键修复 —— 让 ListView 把触摸事件交给 item 内可聚焦的子控件**。
        //
        // 用户反馈"还是不能局部复制"。根因有两层，缺一不可：
        //
        //   ① ListView 的 `mItemsCanFocus` **默认为 false**，意味着列表假定
        //      "item 内没有可聚焦控件"，于是**所有触摸事件都由列表自己消化**，
        //      绝不向下传递。文本正文虽然设了 setTextIsSelectable(true)
        //      （因而 focusable），长按却永远到不了它手上 —— 选择光标自然
        //      不会出现，也就无法框选局部文字。
        //
        //   ② 下面的 setOnItemLongClickListener 返回 true，把长按彻底消费掉，
        //      连"漏给子控件"的机会都没有。
        //
        // 设为 true 后，ListView 检测到 item 内有 focusable 子控件时会把事件
        // 交给它；而文本行的 row 因此 `hasFocusable() == true`，
        // AbsListView 的 CheckForLongPress 会跳过行级长按 —— 两层正好配套。
        //
        // 对文件消息**无影响**：文件卡片是自己画的 LinearLayout（clickable
        // 但不可聚焦），row 内没有可聚焦控件，事件仍由 ListView 处理，
        // 点击/长按照旧走 setOnItemClickListener / setOnItemLongClickListener。
        chatList.setItemsCanFocus(true);

        // 点击消息区域：多选模式切换选中；否则收起面板和输入法
        chatList.setOnItemClickListener((parent, view, position, id) -> {
            hidePanel();
            if (selectMode) {
                Msg m = viewMsgs.get(position);
                String k = keyOf(m);
                if (selectedKeys.contains(k)) selectedKeys.remove(k);
                else selectedKeys.add(k);
                updateSelectCount();
                adapter.notifyDataSetChanged();
            }
        });
        // 触摸聊天区即收起面板/输入法（输入框下落到最底部）
        chatList.setOnTouchListener((v, ev) -> {
            if (ev.getActionMasked() == android.view.MotionEvent.ACTION_DOWN) {
                hidePanel();
            }
            return false;
        });
        // 长按消息：统一弹出微信式菜单（复制 / 打开 / 保存 / 分享 / 删除 / 多选…）。
        //
        // ★ v1.18.2 修复「文本长按完全没反应」：
        //   旧实现里文本消息在这里 `return false`，期望由 TextView 的
        //   TextIsSelectable 接管长按进入文字选择模式。这条路径依赖 ListView 的
        //   焦点分发细节 —— TextView 被 setTextIsSelectable(true) 后变成
        //   focusable，AbsListView 据此决定长按是交给自己还是交给 child。
        //
        //   v1.18.0 为修「文件卡片短暂错乱」引入了 getItemViewType 四类分桶，
        //   convertView 从"频繁重新 inflate"变成"稳定复用"，配合 bind 里
        //   `selectableSet` 的"只设置一次"短路，部分行的 focusable 状态不再
        //   稳定建立 → 长按落到本监听器 → 文本 return false → 最终什么也没发生。
        //
        //   现在文本与文件统一走 showMsgMenu —— 该菜单早已实现文本分支
        //   （复制 / 删除 / 多选），只是此前没有任何入口调用它。
        chatList.setOnItemLongClickListener((parent, view, position, id) -> {
            showMsgMenu(viewMsgs.get(position), view);
            return true;
        });

        FlashNode node = FlashApp.get().node();
        if (!node.isRunning()) node.start();
        loadHistory();
        // ★ v1.18.28：启动后后台建一次"已接收文件"索引（用于判断文件是否还在）
        refreshSavedIndexAsync();
        updateSelfLabel();
        rebuildSpinner();
        rebuildPendingMsgs();     // 恢复上次未发出的待发送内容
        refreshPendingBtn();
        applyTheme();
        // ★ v1.18.13（用户第 5 条）：注册输入法高度监听，让表情面板
        //   与键盘**同高**，切换时布局零位移（微信效果，消除"闪一下"）。
        try {
            View rootV = findViewById(R.id.root);
            watchImeHeight(rootV != null ? rootV : findViewById(android.R.id.content));
        } catch (Throwable ignored) {}
        ui.postDelayed(() -> FlashApp.get().node().notifyPeers(), 600);
        handleShareIntent(getIntent());
        // v1.11.0：整页进入动效（内容淡入 + 轻微上移 + 微缩放落位）。
        // post 一次确保在首帧布局完成后再启动，否则动画作用在未测量的容器上会跳。
        try {
            final android.view.View decor = findViewById(android.R.id.content);
            decor.post(() -> FdAnim.activityEnter(decor));
        } catch (Throwable ignored) {}
        android.util.Log.e("FlashDrop", "MainActivity.onCreate done");
        // 崩溃日志不再自动弹窗（会暴露给普通用户）；改为设置页连点"关于卡"10 次进入
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleShareIntent(intent);
    }

    /** 系统分享入口：微信/相册/文件管理器 分享 → 闪传，直发最近在线设备 */
    private void handleShareIntent(Intent it) {
        if (it == null || isFinishing()) return;
        String action = it.getAction();
        if (!Intent.ACTION_SEND.equals(action)
                && !Intent.ACTION_SEND_MULTIPLE.equals(action)) return;
        List<String> uris = new ArrayList<>();
        String text = it.getStringExtra(Intent.EXTRA_TEXT);
        if (Intent.ACTION_SEND.equals(action)) {
            // API 33+ getParcelableExtra(String) 已废弃，需用类型安全重载，
            // 否则 extra 类型不符会抛 ClassCastException 导致闪退
            Uri u = (Build.VERSION.SDK_INT >= 33)
                    ? it.getParcelableExtra(Intent.EXTRA_STREAM, Uri.class)
                    : it.getParcelableExtra(Intent.EXTRA_STREAM);
            if (u != null) uris.add(u.toString());
        } else {
            ArrayList<Uri> list = it.getParcelableArrayListExtra(Intent.EXTRA_STREAM);
            if (list != null) for (Uri u : list) if (u != null) uris.add(u.toString());
        }
        if (uris.isEmpty() && text != null && !text.trim().isEmpty()) {
            input.setText(text.trim());
            input.setSelection(input.getText().length());
            toast("分享内容已填入，选择设备后点发送");
            return;
        }
        if (uris.isEmpty()) return;
        String target = FlashApp.get().node().recentOnlinePeerId();
        if (target == null) {
            queuePending(uris);
            return;
        }
        FlashNode.Peer p = FlashApp.get().node().findPeer(target);
        String name = p != null && !p.name.isEmpty() ? p.name : "最近设备";
        FlashApp.get().node().sendFiles(Collections.singletonList(target), uris);
        toast("正在把 " + uris.size() + " 个内容发送给 " + name);
    }

    @Override
    protected void onResume() {
        super.onResume();
        // 前台界面接管事件处理（NodeService 停止发系统通知）
        FlashApp.get().uiListener = this::onNodeEvent;
        // ★ v1.18.30：回前台即清掉后台期间的消息通知 ——
        //   只点桌面图标进应用（没点通知）时通知不会自动消失，
        //   已读的消息不该继续在桌面图标上亮角标。
        FlashApp.get().clearMessageNotifications();
        // ★ v1.18.15：回到前台也把待发队列的周期重试挂上（幂等）。
        //   覆盖"界面开着、但 peers 事件之后一直没再变化"的场景 ——
        //   那种情况下光靠 peers 事件不会再触发补发。
        FlashApp.get().schedulePendingRetry();
        // ★ v1.18.30：启动静默检查更新（每天一次；有新版本才弹窗，
        //   失败静默不打扰）。与设置页「检查更新」同一数据源。
        maybeCheckUpdate();
        // 设置里可能改了主题/名称/气泡配色：任一变化都立即刷新
        FdTheme t = FdTheme.resolve(this);
        if (theme == null || t.dark != theme.dark
                || t.bubbleOut != theme.bubbleOut
                || t.bubbleOutText != theme.bubbleOutText) {
            theme = t;
            applyTheme();
            adapter.notifyDataSetChanged();
        }
        updateSelfLabel();
        // ★ v1.18.27：回到前台**无条件**重绘一次列表。
        //   文件可能在别处被删掉（文件管理器 / 设置里的清理），而聊天记录条数没变，
        //   旧逻辑只在"条数变化/清空记录"时才刷新 → 卡片会一直显示"已保存"。
        //   notifyDataSetChanged 只重绑可见的几行，开销可忽略。
        // ★ v1.18.28：回来时**先丢掉已接收文件的索引快照** —— 文件可能在别处被删
        //   或新增，拿着旧快照会把新收的文件判成"已删除"；再后台重建一次。
        FdUtil.invalidateSavedIndex();
        refreshSavedIndexAsync();
        if (adapter != null) adapter.notifyDataSetChanged();
        // ★ v1.15.0：用户从「安装未知应用」设置页授权后回来 → 自动重试安装。
        // 不这样处理的话，系统安装器只会停在一个无动作的界面，这正是用户
        // 反馈的"能打开安装程序但打开后不执行下一步"。
        if (installApkRetry != null) {
            Uri retryUri = installApkRetry;
            installApkRetry = null;
            if (Build.VERSION.SDK_INT >= 26) {
                try {
                    if (getPackageManager().canRequestPackageInstalls()) {
                        doInstallApk(retryUri);
                    }
                } catch (Throwable ignored) {}
            }
        }
        // 设置页清空了聊天记录 → 重新加载
        if (FlashApp.get().historyCleared) {
            FlashApp.get().historyCleared = false;
            exitSelectMode();
            synchronized (msgs) { msgs.clear(); }
            byTidIn.clear();
            byTidOut.clear();
            byMid.clear();
            refreshChat();
            loadHistory();
        }
        // 设备身份合并（跨版本升级）→ 旧记录并入新 ID 后重载
        if (FlashApp.get().historyMerged) {
            FlashApp.get().historyMerged = false;
            byTidIn.clear();
            byTidOut.clear();
            byMid.clear();
            refreshChat();
            loadHistory();
        }
        // ★ v1.13.1：界面在后台期间收到了消息/文件 —— NodeService 已把记录写盘，
        // 但当前内存 msgs 里还没有（旧代码只弹通知、不落库，回来看就是空白）。
        // 只要后台期间有新记录写入，这里就重载一次历史，保证"点通知进来能看到内容"。
        int bgCount = FlashApp.get().bgPendingReloadCount;
        if (bgCount != lastBgReloadCount) {
            lastBgReloadCount = bgCount;
            loadHistory();
        }
    }

    /** ★ v1.18.30：启动静默检查更新（每天一次；有新版本才弹窗，失败静默不打扰）。
     *  与设置页「检查更新」共用 UpdateChecker 数据源与对话框。 */
    private void maybeCheckUpdate() {
        try {
            Prefs prefs = FlashApp.get().prefs();
            String today = new java.text.SimpleDateFormat("yyyy-MM-dd",
                    java.util.Locale.US).format(new java.util.Date());
            if (today.equals(prefs.lastUpdateCheck())) return;
            // 查过就记：失败也不在今天重试（国内访问 GitHub 慢，避免每次回前台都等 8s）
            prefs.setLastUpdateCheck(today);
            UpdateChecker.check(info -> {
                if (info == null) return;      // 静默失败不打扰
                String ver = info.optString("version", "");
                if (!UpdateChecker.isNewer(ver, FdUtil.APP_VERSION)) return;
                if (ver.equals(FlashApp.get().prefs().skippedVersion())) return;
                UpdateChecker.showUpdateDialog(this, info);
            });
        } catch (Throwable ignored) {}
    }

    @Override
    protected void onPause() {
        super.onPause();
        // 界面不可见：交给 NodeService 处理事件（弹系统通知）
        FlashApp.get().uiListener = null;
        // ★ v1.18.13（用户第 2 条）：切后台时收起表情面板。
        //
        //   现象：打开表情面板 → 切后台 → 再回来，表情面板与键盘**重叠**
        //         （用户截图 1000403323.jpg）。
        //   根因：切后台时若输入框仍有焦点，回到前台系统会**自动重新弹出
        //        输入法**；而表情面板仍是 VISIBLE 且占据键盘区，两者叠加。
        //   修法：onPause 时直接收起面板（不走动画，避免后台不可见状态下
        //         动画被中断留下半透明/位移残影），回到前台即为"原界面"。
        try {
            View host = findViewById(R.id.emoji_panel);
            if (host != null && host.getVisibility() == View.VISIBLE) {
                host.animate().cancel();
                host.setVisibility(View.GONE);
                host.setTranslationY(0f);
                host.setAlpha(1f);
                updateEmojiIcon();
            }
        } catch (Throwable ignored) {}
    }

    private void startForegroundServiceSafely() {
        // Android 12+（API 31/34）对前台服务启动限制极严：
        // 未处于前台或类型不匹配时会抛 ForegroundServiceStartNotAllowedException /
        // MissingForegroundServiceTypeException，直接导致"打开即闪退"。
        // 因此整段包 try，任何失败都只记录不抛出，保证界面能正常打开。
        try {
            Intent it = new Intent(this, NodeService.class);
            if (Build.VERSION.SDK_INT >= 26) startForegroundService(it);
            else startService(it);
        } catch (Throwable t) {
            android.util.Log.e("FlashDrop", "startForegroundService failed", t);
            // 兜底：节点改为由 Activity 生命周期内自启（见 onCreate 的 node.start()）
        }
    }

    private void requestNeededPermissions() {
        // 权限申请本身极少抛错，但个别 ROM 在应用刚启动时会抛，包保护避免整界面崩
        try {
        List<String> ps = new ArrayList<>();
        if (Build.VERSION.SDK_INT >= 33) {
            if (checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                    != PackageManager.PERMISSION_GRANTED)
                ps.add(Manifest.permission.POST_NOTIFICATIONS);
        }
        if (Build.VERSION.SDK_INT <= 28) {
            if (checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE)
                    != PackageManager.PERMISSION_GRANTED)
                ps.add(Manifest.permission.WRITE_EXTERNAL_STORAGE);
        }
        // 相机权限无需声明：ACTION_IMAGE_CAPTURE 由系统相机应用持有权限
        if (!ps.isEmpty()) requestPermissions(ps.toArray(new String[0]), REQ_PERMS);
        } catch (Throwable t) {
            android.util.Log.e("FlashDrop", "requestPermissions failed", t);
        }
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] res) {
        super.onRequestPermissionsResult(code, perms, res);
    }

    private int dp(float v) {
        return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP,
                v, getResources().getDisplayMetrics());
    }

    /** 按当前主题刷新所有容器与控件配色 */
    private void applyTheme() {
        if (theme == null) return;
        findViewById(R.id.root).setBackgroundColor(theme.bg);
        topBar.setBackgroundColor(theme.bar);
        selBar.setBackgroundColor(theme.bar);
        // inputBar 与 inputPill 是同一控件，背景统一在下方"输入胶囊"处设置
        actionBar.setBackgroundColor(theme.bar);
        chatList.setBackgroundColor(theme.bg);
        // ★ v1.18.24：搜索结果列表本身也要**不透明底色 + 主题化分隔线**。
        //   searchResultList 覆盖在 chatList 之上，背景透明会把聊天内容透出来；
        //   列表底用 theme.bg、行底用 theme.card（见 searchAdapter），
        //   两层都不透明，聊天内容彻底被遮住。
        //   分隔线此前在 XML 里写死 #2E3138（深色专用），浅色主题下会变成
        //   一条深线压在白卡片上 → 改为跟随 theme.border。
        searchResultList.setBackgroundColor(theme.bg);
        searchResultList.setDivider(
                new android.graphics.drawable.ColorDrawable(theme.border));
        searchResultList.setDividerHeight(Math.max(1, dp(1)));
        emptyView.setTextColor(theme.dim);
        selfLabel.setTextColor(theme.dim);
        onlineLabel.setTextColor(theme.dim);
        selectCountLbl.setTextColor(theme.accent);
        ((TextView) findViewById(R.id.app_title)).setTextColor(theme.text);
        // 按钮
        GradientDrawable smallBtn = theme.round(theme.card, 6, this);
        smallBtn.setStroke(dp(1), theme.border);
        btnRescan.setBackground(smallBtn.getConstantState().newDrawable());
        // ★ v1.18.23：按钮是「ImageView + TextView」复合容器（图标 + “搜索” 文字），
        //   图标只能 setColorFilter 着色、文字只能 setTextColor —— 两者分别处理
        tintIcon(R.id.ic_search_btn, theme.text);
        ((TextView) findViewById(R.id.tv_search_label)).setTextColor(theme.text);
        btnDelete.setBackground(smallBtn.getConstantState().newDrawable());
        // ★ v1.18.25：该按钮在搜索态形变为「搜全局」，用正文色而非警示红
        btnDelete.setTextColor(searchMode ? theme.text : theme.red);
        btnPending.setBackground(smallBtn.getConstantState().newDrawable());
        btnPending.setTextColor(theme.text);
        tintIcon(R.id.btn_settings, theme.text);
        tintIcon(R.id.btn_camera, theme.text);
        // v1.18.10：表情按钮图标着色（与左侧相册按钮同为 theme.text）
        tintIcon(R.id.btn_emoji, theme.text);
        tintIcon(R.id.btn_expand, theme.dim);
        // 输入胶囊
        GradientDrawable pill = theme.round(theme.card, 22, this);
        pill.setStroke(dp(1), theme.border);
        inputPill.setBackground(pill);
        // ★ v1.17.0：底部输入栏的**外层容器**也要跟着主题走。
        // 它此前没有 id、只在 XML 里写死 #1F2126，所以浅色主题下
        // "底部消息栏还有局部黑色未修正"（用户实测）。现在显式上色。
        View inputWrap = findViewById(R.id.input_wrap);
        if (inputWrap != null) inputWrap.setBackgroundColor(theme.bar);
        input.setTextColor(theme.text);
        input.setHintTextColor(theme.dim);
        // ★ v1.17.0：状态栏跟主题。浅色主题下原来固定 #15171B（近黑），
        // 顶部一条黑边与浅色页面割裂；改为浅色主题用 bar 色、
        // 深色主题保留略深于背景的 #15171B（与页面 bg 区分出层次）。
        getWindow().setStatusBarColor(theme.dark ? 0xFF15171B : theme.bar);
        // ★ v1.18.26：状态栏**图标/时间/电量**的颜色也要跟主题走。
        //   浅色主题下状态栏底色被设成 theme.bar（白色），而 styles.xml 里写死
        //   `windowLightStatusBar=false` —— 图标仍是白色 → **白底白字，
        //   时间、信号、电量统统看不见**，用户实测「顶部手机的导航栏不显示」就是它。
        //   现在按主题动态切：深色主题用浅色图标，浅色主题用深色图标（API 23+）。
        View decor = getWindow().getDecorView();
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            int sf = decor.getSystemUiVisibility();
            if (theme.dark) {
                sf &= ~View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;   // 深底 → 浅色图标
            } else {
                sf |= View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;    // 浅底 → 深色图标
            }
            decor.setSystemUiVisibility(sf);
        }
        // 底部面板与图标
        panel.setBackgroundColor(theme.bar);
        // v1.18.10：表情面板容器底色跟随主题
        View emojiHost = findViewById(R.id.emoji_panel);
        if (emojiHost != null) emojiHost.setBackgroundColor(theme.bar);
        tintIcon(R.id.ic_album, theme.text);
        tintIcon(R.id.ic_camera, theme.text);
        tintIcon(R.id.ic_file, theme.text);
        tintIcon(R.id.ic_plus, theme.dim);
        tintIcon(R.id.ic_send, 0xFFFFFFFF);
        tintIcon(R.id.btn_expand, theme.dim);
        GradientDrawable plusCircle = new GradientDrawable();
        plusCircle.setShape(GradientDrawable.OVAL);
        plusCircle.setColor(android.graphics.Color.TRANSPARENT);
        plusCircle.setStroke(dp(1), theme.dim);
        btnPlus.setBackground(plusCircle);
        // 底部面板卡片与标签、多选栏按钮、下拉弹层（主题跟随补全）
        GradientDrawable cardBg = theme.round(theme.card, 14, this);
        cardBg.setStroke(dp(1), theme.border);
        for (int cid : new int[]{R.id.panel_album, R.id.panel_camera, R.id.panel_file}) {
            View card = findViewById(cid);
            card.setBackground(cardBg.getConstantState().newDrawable());
            if (card instanceof ViewGroup && ((ViewGroup) card).getChildCount() > 1) {
                View lbl = ((ViewGroup) card).getChildAt(1);
                if (lbl instanceof TextView) ((TextView) lbl).setTextColor(theme.text);
            }
        }
        ((Button) findViewById(R.id.btn_sel_all)).setTextColor(theme.text);
        ((Button) findViewById(R.id.btn_sel_del)).setTextColor(theme.red);
        ((Button) findViewById(R.id.btn_sel_cancel)).setTextColor(theme.text);
        targetSpinner.setPopupBackgroundDrawable(theme.round(theme.card, 8, this));
        // ★ v1.18.10（用户第 1 条）：下拉弹层与选择框对齐。
        //   ListPopupWindow 会给弹层加一圈自带 padding，叠加到每一行上就等于
        //   "展开后的行比收起态整体右移"，与选择框描边对不齐。
        //   这里把弹层的水平内边距显式清零（反射 ListPopupWindow.mDropDownHorizontalOffset
        //   不可靠，改为让行自身撑满），行的左右起点改由适配器按 dp 精确控制。
        //   注：Spinner 的 popup 背景 Drawable 可用 setPadding 兜底消除描边内缩。
        android.graphics.drawable.Drawable popBg = targetSpinner.getPopupBackground();
        if (popBg instanceof android.graphics.drawable.GradientDrawable) {
            ((android.graphics.drawable.GradientDrawable) popBg).setPadding(0, 0, 0, 0);
        }
        // ★ v1.17.0：设备选择框（Spinner）背景按主题重设。
        // 此前只在 XML 里给了 background=@drawable/btn_small（写死深色 #2E3138），
        // applyTheme() 从未覆盖它 —— 这就是用户实测的
        // 「浅色主题下设备选择框还是黑的」。
        // 现在给它与「扫描 / 删除」按钮同一套：卡片色底 + 细描边 + 6dp 圆角。
        targetSpinner.setBackground(smallBtn.getConstantState().newDrawable());
        // ★ v1.18.13（用户第 3 条）：Spinner 自身的内边距会叠加到自绘行上，
        //   导致「收起态状态灯离右边框还差一截」（用户："全部设备后面的状态灯
        //   未在最右侧"）。这里把 Spinner 内边距清零，位置完全交给适配器里的
        //   固定槽位控制 —— 收起态与展开态的灯才能落在同一 x。
        targetSpinner.setPadding(0, 0, 0, 0);
        // Spinner 内部文字（DeviceSpinAdapter 自绘，取 theme.text，无需再设）
        adapter.notifyDataSetChanged();
    }

    /**
     * v1.11.0：给 View 加按压反馈（按下微缩 0.97，抬起复原 1.0，140ms）。
     *
     * 为什么统一走 setOnTouchListener 而不是逐个包一层 OnClick：
     * 现有按钮的 setOnClickListener 已经挂了十几个，再包一层会把逻辑搅乱。
     * 这里返回 false 让事件继续走原来的 click 逻辑，只额外"顺手"播个动画。
     */
    private <T extends View> T pressable(T v) {
        if (v == null) return v;
        v.setOnTouchListener((view, ev) -> {
            int a = ev.getActionMasked();
            if (a == android.view.MotionEvent.ACTION_DOWN) {
                FdAnim.pressDown(view);
            } else if (a == android.view.MotionEvent.ACTION_UP
                    || a == android.view.MotionEvent.ACTION_CANCEL) {
                FdAnim.pressUp(view);
            }
            return false;   // 不消费，click 照常触发
        });
        return v;
    }

    /**
     * ★ v1.18.28：后台重建"已接收文件"索引，建完让列表重绘一次。
     *
     * 索引是 MediaStore 查询的结果，**不能在主线程查**（bindView 里查会把滚动卡住），
     * 所以这里只做两件事：后台建索引 → 完成后回 UI 线程重绘。
     * 索引没建好时 savedFileExists 一律保守返回"还在"，不会误标已删除。
     */
    private void refreshSavedIndexAsync() {
        new Thread(() -> {
            FdUtil.buildSavedIndex(MainActivity.this);
            ui.post(() -> {
                if (adapter != null) adapter.notifyDataSetChanged();
            });
        }).start();
    }

    /**
     * ★ v1.18.27：**收到的**文件是否已经在本地不存在了（被用户/系统删掉）。
     * ★ v1.18.28：判定改为交给 FdUtil.savedFileExists —— **以 MediaStore 索引为准**。
     *
     * v1.18.27 用 File.exists() 直接判，方向错了：API≥29 存的 path 只是
     * "Download/FlashDrop/设备名/xx.jpg" 这种展示用相对描述，拼出来的 File 不存在，
     * 加上 Android 11+ 分区存储下没权限时 exists() 也返回 false，
     * 结果"还在文件夹的文件也被显示成已删除"（用户实测）。
     *
     * 只看 dir=in 的已完成文件 —— 发出去的文件显示的是"已送达"（指对方收到了），
     * 与本地源文件在不在无关。
     */
    private boolean fileGoneOf(Msg m) {
        if (m == null || !"in".equals(m.dir)) return false;
        // content: Uri / 无路径 / 查不到索引 → savedFileExists 一律保守返回 true
        return !FdUtil.savedFileExists(this, m.path);
    }

    private void tintIcon(int id, int color) {
        ImageView iv = findViewById(id);
        if (iv != null) iv.setColorFilter(color);
    }

    private void updateSelfLabel() {
        FlashApp app = FlashApp.get();
        String ip = "127.0.0.1";
        try {
            for (java.net.NetworkInterface nif : Collections.list(
                    java.net.NetworkInterface.getNetworkInterfaces())) {
                if (!nif.isUp() || nif.isLoopback()) continue;
                for (java.net.InterfaceAddress ia : nif.getInterfaceAddresses()) {
                    if (ia.getAddress() instanceof java.net.Inet4Address
                            && !ia.getAddress().isLoopbackAddress()) {
                        ip = ia.getAddress().getHostAddress();
                    }
                }
            }
        } catch (Exception ignored) {}
        selfLabel.setText("本机: " + app.prefs().name("")
                + " · " + ip + " · 端口 " + app.prefs().port(FdProto.DEFAULT_PORT));
    }

    // ============================ 底部面板 / 全屏输入 ============================

    private void updateSendPlus() {
        boolean hasText = input.getText().length() > 0;
        btnPlus.setVisibility(hasText ? View.GONE : View.VISIBLE);
        btnSend.setVisibility(hasText ? View.VISIBLE : View.GONE);
    }

    private void togglePanel() {
        if (panel.getVisibility() == View.VISIBLE) {
            hidePanel();
        } else {
            hideIme();
            panel.setVisibility(View.VISIBLE);
            // v1.11.0：底部面板上滑进入（微信/QQ 同款）
            FdAnim.slideInFromBottom(panel);
        }
    }

    private void hidePanel() {
        // v1.11.0：下滑退出。动画走完再隐藏，否则"瞬间消失"很生硬。
        if (!FdAnim.on(panel)) { panel.setVisibility(View.GONE); return; }
        panel.animate().translationY(FdUtil.dp(this, 26)).alpha(0f)
                .setDuration(FdAnim.DURATION_EXIT)
                .setInterpolator(FdAnim.CURVE_ACCELERATE)
                .withEndAction(() -> {
                    panel.setVisibility(View.GONE);
                    // 复位，避免下次打开时从偏移位置开始
                    panel.setTranslationY(0f);
                    panel.setAlpha(1f);
                }).start();
    }

    private void hideIme() {
        android.view.inputmethod.InputMethodManager imm =
                getSystemService(android.view.inputmethod.InputMethodManager.class);
        if (imm != null) imm.hideSoftInputFromWindow(input.getWindowToken(), 0);
    }

    // ============================ 表情面板（v1.18.10） ============================

    /**
     * 记录**真实输入法高度**（px）。0 表示尚未测得。
     *
     * ★ v1.18.13（用户第 5 条）：微信的表情面板与键盘**同高**，
     *   切换时布局完全不动 → 不会闪。要做到这一点必须先知道键盘多高，
     *   所以这里用 ViewTreeObserver 监听根布局的可见高度变化：
     *   当窗口因 adjustResize 被 IME 顶起时，根布局可用高度会变小，
     *   差值就是 IME 高度。
     */
    private int imeHeightPx = 0;

    /**
     * 注册输入法高度监听（在 main 里调一次）。
     *
     * 原理：根布局 `root`（最外层 LinearLayout）在 adjustResize 下会被 IME
     * 挤压。记录它的「未被挤压时的全局底边」与「当前可见底边」之差，
     * 即是 IME 占据的高度。
     */
    private void watchImeHeight(View root) {
        final android.view.View decor = getWindow().getDecorView();
        decor.getViewTreeObserver().addOnGlobalLayoutListener(() -> {
            try {
                // ★ v1.18.14（用户第 1 条）：优先用**官方 IME inset**（API 30+）。
                //   它直接给出键盘的精确高度，完全不受状态栏 / 导航栏 / 边到边
                //   布局的干扰 —— 这是修「面板比键盘高一行」的正解。
                int exact = imeInsetPx(decor);
                if (exact > 0) {
                    imeHeightPx = exact;
                    return;
                }
                // 兜底（API < 30）：可见区域缺口 − 导航栏。
                android.graphics.Rect r = new android.graphics.Rect();
                decor.getWindowVisibleDisplayFrame(r);
                int screenH = decor.getRootView().getHeight();
                int nav = navBarPx(decor);
                int candidate = screenH - r.bottom - nav;
                if (candidate > screenH * 0.15f) {
                    imeHeightPx = candidate;
                }
            } catch (Throwable ignored) {}
        });
    }

    /**
     * 键盘精确高度（px），取不到返回 0。
     *
     * ★ v1.18.14：v1.18.13 用的是「可见区域缺口 − 导航栏」，但
     *   {@code getWindowVisibleDisplayFrame()} 的缺口里**同时含状态栏**，
     *   只减导航栏就会把状态栏高度算进键盘 —— Galaxy S23U 上状态栏约 140px，
     *   正好等于用户看到的「面板比键盘高一行」（实测差 127~138px）。
     *   API 30+ 直接读 {@code WindowInsets.Type.ime()} 即可，一步到位。
     */
    private int imeInsetPx(android.view.View decor) {
        if (android.os.Build.VERSION.SDK_INT < 30) return 0;
        try {
            android.view.WindowInsets wi = decor.getRootWindowInsets();
            if (wi == null) return 0;
            android.graphics.Insets ins =
                    wi.getInsets(android.view.WindowInsets.Type.ime());
            return ins.bottom;
        } catch (Throwable t) {
            return 0;
        }
    }

    /** 导航栏高度（px）：先取 inset，取不到退回系统资源值，再取不到返回 0。 */
    private int navBarPx(android.view.View decor) {
        try {
            android.view.WindowInsets wi = decor.getRootWindowInsets();
            if (wi != null) {
                android.graphics.Insets ins = wi.getInsets(
                        android.view.WindowInsets.Type.navigationBars());
                if (ins.bottom > 0) return ins.bottom;
            }
        } catch (Throwable ignored) {}
        try {
            int id = getResources().getIdentifier(
                    "navigation_bar_height", "dimen", "android");
            if (id > 0) return getResources().getDimensionPixelSize(id);
        } catch (Throwable ignored) {}
        return 0;
    }

    /**
     * 展开 / 收起表情面板。
     *
     * <p>行为对齐微信：
     * <ul>
     *   <li>展开前先收起输入法 —— 面板占的就是输入法那块位置</li>
     *   <li>展开时收起「＋」底部面板，两者互斥</li>
     *   <li>图标**常驻**，输入文字后依然可点（用户明确要求
     *       「输入时不隐藏表情图标」，所以它不参与 ＋/发送 的互换）</li>
     * </ul>
     *
     * ★ v1.18.13（用户第 5 条）三项修正：
     *   ①「表情包展开的高度太高 可以参照微信来修正」
     *      → 高度改为**优先取真实 IME 高度**（imeHeightPx），拿不到时退回
     *        屏幕高的 36%（微信安卓实测约占 36%~40%，旧版 42% 偏高）。
     *   ②「与键盘切换方式改为 键盘上推 下拉 等 和微信方式保持一致」
     *      → 面板进入/退出改用 FdAnim 的位移过渡（上推进入 / 下拉退出），
     *        并去掉与 IME 动画抢帧的 alpha 渐变。
     *   ③「切换时聊天界面会闪一下 应该是底部的文本输入框会弹到最顶部
     *      然后又在下面出现 这个要调整 保持界面的一致性」
     *      → 根因：旧实现在 hideIme() 后立刻 show 面板，但 IME 收起是
     *        **异步**的（约 150~250ms）。这段窗口里窗口仍是"被 IME 顶起"
     *        的高度，此时把面板设成 VISIBLE 会把输入栏挤到屏幕中部，
     *        等 IME 真正收完再落回底部 —— 这就是用户看到的"闪一下"。
     *        修法：**等 IME 真正收完（或超时）再展开面板**，让布局只动一次。
     */
    private void toggleEmojiPanel() {
        View hostV = findViewById(R.id.emoji_panel);
        if (!(hostV instanceof FrameLayout)) return;
        FrameLayout host = (FrameLayout) hostV;
        if (host.getVisibility() == View.VISIBLE) {
            // ★ v1.18.12（用户第 3 条）：再点一次 = 切回键盘。
            //   先收起面板（下拉动画），动画结束再拉起输入法，避免同帧抢布局。
            hideEmojiPanelThen(1, () -> showIme());
            return;
        }
        hidePanel();                       // 与「＋」面板互斥
        // ★ v1.18.13：先收 IME，**等它真正收完**再展开面板（修"闪一下"）
        hideImeThen(() -> {
            if (emojiPicker == null) {
                emojiPicker = new EmojiPicker(this, theme, emoji -> insertEmoji(emoji));
            }
            int h = panelHeight();
            FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, h);
            if (emojiPicker.getView().getParent() == null) {
                host.addView(emojiPicker.getView(), lp);
            } else {
                emojiPicker.getView().setLayoutParams(lp);
                emojiPicker.refresh();
            }
            host.setVisibility(View.VISIBLE);
            // ② ★ v1.18.14：整高上推进入（微信式 —— 面板像键盘一样从底部
            //    被"顶"上来，位移量 = 面板整高，而不是旧版只挪 26dp 的轻推）。
            slidePanelIn(host);
            updateEmojiIcon();
        });
    }

    /**
     * 面板目标高度（px）。
     *
     * ★ v1.18.13（用户第 5 条）：优先用**真实键盘高度**，这样面板与键盘
     *   同高，切换时布局零位移（微信效果）。未测得时退回屏幕高的 36%
     *   （微信安卓实测键盘约占 36%~40%，旧版 42% 明显偏高，就是用户说的
     *   "高度太高"）。
     */
    private int panelHeight() {
        int screenH = getResources().getDisplayMetrics().heightPixels;
        int base = imeHeightPx > 0 ? imeHeightPx
                                   : (int) (screenH * 0.36f);
        // ★ v1.18.14：上限由 50% 收到 45%。实测键盘约占屏高 36%~40%
        //   （Galaxy S23U：1208/3088 = 39%），50% 太松会把面板放高一整行。
        int lo = (int) (screenH * 0.28f);
        int hi = (int) (screenH * 0.45f);
        return Math.max(lo, Math.min(base, hi));
    }

    /**
     * 收起输入法，并在**确认收完**后执行 after。
     *
     * ★ v1.18.13：这是修「切换时闪一下」的关键。
     *   IME 的收起是异步的；如果立刻展开表情面板，就会出现
     *   "输入栏先弹到屏幕中部、再落回底部"的两帧跳动。
     *   这里用轮询检测「窗口可见高度是否已恢复」，恢复即回调；
     *   最多等 320ms（超时也回调，保证不卡死）。
     */
    private void hideImeThen(Runnable after) {
        final android.view.View decor = getWindow().getDecorView();
        final int before = visibleBottom(decor);
        hideIme();
        final long t0 = android.os.SystemClock.uptimeMillis();
        final int[] tries = {0};
        final Runnable[] poll = new Runnable[1];
        poll[0] = () -> {
            tries[0]++;
            int now = visibleBottom(decor);
            boolean settled = now >= before;     // 可见高度已恢复 = IME 收完
            if (settled || tries[0] > 16
                    || android.os.SystemClock.uptimeMillis() - t0 > 320) {
                after.run();
                return;
            }
            decor.postDelayed(poll[0], 20);
        };
        decor.postDelayed(poll[0], 20);
    }

    /** 当前窗口可见区域底边（用于判断 IME 是否已收起）。 */
    private int visibleBottom(android.view.View decor) {
        try {
            android.graphics.Rect r = new android.graphics.Rect();
            decor.getWindowVisibleDisplayFrame(r);
            return r.bottom;
        } catch (Throwable ignored) {
            return 0;
        }
    }

    /**
     * ★ v1.18.12（用户第 3 条）：「打开表情包时要把表情包按钮改为键盘」。
     *
     * 面板可见 → 按钮显示**键盘**图标（提示"点我回到输入法"）；
     * 面板隐藏 → 恢复**表情**图标。
     * 图标统一走 tintIcon 按主题着色，浅色/深色都不会"看不见"。
     */
    private void updateEmojiIcon() {
        int res = emojiPanelVisible() ? R.drawable.ic_keyboard : R.drawable.ic_emoji;
        ImageView iv = findViewById(R.id.btn_emoji);
        if (iv == null) return;
        iv.setImageResource(res);
        tintIcon(R.id.btn_emoji, theme.text);
        iv.setContentDescription(emojiPanelVisible() ? "切换键盘" : "表情");
    }

    /**
     * 主动拉起输入法（与键盘互切用）。
     *
     * <p>和 {@link #hideIme()} 配对：那里用 InputMethodManager.hideSoftInputFromWindow
     * 收起，这里用 showSoftInput + 聚焦输入框拉起。
     */
    private void showIme() {
        try {
            input.requestFocus();
            android.view.inputmethod.InputMethodManager imm =
                    (android.view.inputmethod.InputMethodManager)
                            getSystemService(INPUT_METHOD_SERVICE);
            if (imm != null) imm.showSoftInput(input, 0);
        } catch (Throwable ignored) {}
    }

    private void hideEmojiPanel() {
        hideEmojiPanelThen(0, null);
    }

    /**
     * ★ v1.18.14（用户第 1 条）：表情面板专用「被顶上来」动效。
     *
     * 与旧的 {@code FdAnim.slideInFromBottom()} 的区别：
     *   · 旧版位移只有 26dp + alpha 淡入 → 观感是"轻轻推一下"，不像键盘；
     *   · 新版位移 = **面板整高**、不做 alpha → 与键盘上推完全同构，
     *     切换时视觉连续（面板的高度已经和键盘等高，见 panelHeight()）。
     */
    private void slidePanelIn(View host) {
        if (host == null) return;
        if (!FdAnim.on(host)) {
            host.setTranslationY(0f);
            return;
        }
        host.setTranslationY(host.getHeight());
        host.setAlpha(1f);
        host.animate().translationY(0f)
                .setDuration(FdAnim.DURATION_ENTER)
                .setInterpolator(FdAnim.CURVE_DECELERATE)
                .start();
    }

    /**
     * 收起表情面板（下拉退出），动画结束后执行 after。
     *
     * ★ v1.18.13（用户第 5 条）：去掉 alpha 渐变、只保留位移，
     *   与「上推进入」对称，动画更干脆（微信的观感）。
     * ★ v1.18.14：位移量由 26dp 改为**面板整高**，真正"滑出视野"，
     *   不再出现"面板还在、键盘已经盖上来"的重叠感。
     */
    private void hideEmojiPanelThen(int delayMs, Runnable after) {
        View host = findViewById(R.id.emoji_panel);
        if (host == null || host.getVisibility() != View.VISIBLE) {
            if (after != null) after.run();
            return;
        }
        Runnable doHide = () -> {
            if (!FdAnim.on(host)) {
                host.setVisibility(View.GONE);
                updateEmojiIcon();
                if (after != null) after.run();
                return;
            }
            host.animate().translationY(host.getHeight())
                    .setDuration(FdAnim.DURATION_EXIT)
                    .setInterpolator(FdAnim.CURVE_ACCELERATE)
                    .withEndAction(() -> {
                        host.setVisibility(View.GONE);
                        host.setTranslationY(0f);
                        host.setAlpha(1f);
                        updateEmojiIcon();       // ★ 收起后图标回到「表情」
                        if (after != null) after.run();
                    }).start();
        };
        if (delayMs > 0) host.postDelayed(doHide, delayMs);
        else doHide.run();
    }

    private boolean emojiPanelVisible() {
        View host = findViewById(R.id.emoji_panel);
        return host != null && host.getVisibility() == View.VISIBLE;
    }

    /**
     * 把表情字符插入输入框光标处。
     *
     * <p>关键：插入后**把光标移到字符之后**并重新聚焦，否则连续点第二个
     * 表情时，EditText 的光标位置可能因为失去焦点而回退到开头。
     */
    private void insertEmoji(String emoji) {
        if (emoji == null || emoji.isEmpty()) return;
        _insertingEmoji = true;
        try {
            int start = Math.max(0, input.getSelectionStart());
            int end = Math.max(0, input.getSelectionEnd());
            if (start > end) { int t = start; start = end; end = t; }
            android.text.Editable et = input.getText();
            et.replace(start, end, emoji);
            input.setSelection(start + emoji.length());
            input.requestFocus();
        } finally {
            _insertingEmoji = false;
        }
    }

    private void openFullscreenInput() {
        if (isFinishing() || isDestroyed()) return;
        hideIme();
        final android.widget.PopupWindow[] holder = new android.widget.PopupWindow[1];
        android.widget.PopupWindow win = new android.widget.PopupWindow(
                null, ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT, true);
        holder[0] = win;
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(theme.bg);
        root.setClickable(true);
        root.setFocusableInTouchMode(true);

        final EditText big = new EditText(this);
        big.setText(input.getText());
        big.setSelection(big.getText().length());
        big.setTextColor(theme.text);
        big.setHintTextColor(theme.dim);
        big.setHint("发消息…");
        big.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
        big.setGravity(android.view.Gravity.TOP | android.view.Gravity.START);
        big.setBackgroundColor(android.graphics.Color.TRANSPARENT);
        big.setPadding(dp(16), dp(54), dp(16), dp(76));
        root.addView(big, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        // 下拉关闭：文字在顶部且向下拖动时，整页跟手下移，松手超过阈值收起
        final float[] downY = {-1};
        final float[] dragY = {0};
        final boolean[] dragging = {false};
        big.setOnTouchListener((v, ev) -> {
            switch (ev.getActionMasked()) {
                case android.view.MotionEvent.ACTION_DOWN:
                    downY[0] = ev.getRawY();
                    dragging[0] = true;
                    break;
                case android.view.MotionEvent.ACTION_MOVE:
                    float dy = ev.getRawY() - downY[0];
                    // 仅当文本已滚到顶部时才允许下拉拖动
                    boolean atTop = !big.canScrollVertically(-1);
                    if (dragging[0] && dy > dp(16) && atTop) {
                        dragY[0] = Math.max(0, dy);
                        root.setTranslationY(dragY[0]);
                        root.setAlpha(Math.max(0.55f, 1f - dragY[0] / (dp(360) * 3f)));
                        return true;
                    }
                    break;
                case android.view.MotionEvent.ACTION_UP:
                case android.view.MotionEvent.ACTION_CANCEL:
                    if (dragY[0] > dp(110)) {
                        // 下拉足够：收起全屏，恢复 3 行输入
                        root.animate().translationY(root.getHeight()).alpha(0f)
                                .setDuration(180).withEndAction(() -> {
                            input.setText(big.getText());
                            input.setSelection(input.getText().length());
                            updateSendPlus();
                            win.dismiss();
                        }).start();
                        return true;
                    }
                    if (dragY[0] > 0) {
                        root.animate().translationY(0f).alpha(1f).setDuration(150).start();
                    }
                    dragging[0] = false;
                    dragY[0] = 0;
                    break;
            }
            return false;
        });

        // 顶部左侧：关闭（反向对角箭头）
        ImageView close = new ImageView(this);
        close.setImageResource(R.drawable.ic_collapse);
        close.setOnClickListener(v -> {
            input.setText(big.getText());
            input.setSelection(input.getText().length());
            updateSendPlus();
            win.dismiss();
        });
        FrameLayout.LayoutParams clp = new FrameLayout.LayoutParams(dp(30), dp(30));
        clp.gravity = android.view.Gravity.TOP | android.view.Gravity.START;
        clp.leftMargin = dp(14);
        clp.topMargin = dp(12);
        root.addView(close, clp);

        // 底部右侧：发送（圆形，固定）
        FrameLayout sendW = new FrameLayout(this);
        sendW.setBackgroundResource(R.drawable.send_circle);
        sendW.setClickable(true);
        ImageView siv = new ImageView(this);
        siv.setImageResource(R.drawable.ic_arrow_up);
        siv.setClickable(false);
        siv.setFocusable(false);
        sendW.addView(siv, new FrameLayout.LayoutParams(dp(22), dp(22),
                android.view.Gravity.CENTER));
        sendW.setOnClickListener(v -> {
            input.setText(big.getText());
            win.dismiss();
            sendText();
        });
        FrameLayout.LayoutParams slp = new FrameLayout.LayoutParams(dp(44), dp(44));
        slp.gravity = android.view.Gravity.BOTTOM | android.view.Gravity.END;
        slp.rightMargin = dp(18);
        slp.bottomMargin = dp(22);
        root.addView(sendW, slp);

        win.setContentView(root);
        win.setSoftInputMode(
                android.view.WindowManager.LayoutParams.SOFT_INPUT_STATE_VISIBLE);
        win.showAtLocation(getWindow().getDecorView(), android.view.Gravity.BOTTOM,
                0, 0);
        big.requestFocus();
        // 上推动画：整页从输入栏位置向上推起
        int h = root.getHeight();
        if (h == 0) {
            root.post(() -> {
                root.setTranslationY(root.getHeight() * 0.35f);
                root.setAlpha(0.6f);
                root.animate().translationY(0f).alpha(1f).setDuration(220)
                        .setInterpolator(new android.view.animation.DecelerateInterpolator())
                        .start();
            });
        } else {
            root.setTranslationY(h * 0.35f);
            root.setAlpha(0.6f);
            root.animate().translationY(0f).alpha(1f).setDuration(220)
                    .setInterpolator(new android.view.animation.DecelerateInterpolator())
                    .start();
        }
    }

    private void pickFromGallery() {
        Intent it = new Intent(Intent.ACTION_GET_CONTENT);
        it.addCategory(Intent.CATEGORY_OPENABLE);
        it.setType("image/*");
        it.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
        startActivityForResult(Intent.createChooser(it, "选择图片"), REQ_PICK_ALBUM);
    }

    private void pickDocument() {
        Intent it = new Intent(Intent.ACTION_OPEN_DOCUMENT);
        it.addCategory(Intent.CATEGORY_OPENABLE);
        it.setType("*/*");
        it.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
        startActivityForResult(Intent.createChooser(it, "选择要发送的文件"), REQ_PICK_FILES);
    }

    private void capturePhoto() {
        try {
            File dir = new File(FdUtil.cacheDir(this), "camera");
            if (!dir.exists()) dir.mkdirs();
            File photo = new File(dir, "photo_" + System.currentTimeMillis() + ".jpg");
            cameraUri = FdFileProvider.uriForCache(this,
                    "camera/" + photo.getName());
            Intent it = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
            it.putExtra(MediaStore.EXTRA_OUTPUT, cameraUri);
            it.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                    | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
            if (it.resolveActivity(getPackageManager()) != null) {
                startActivityForResult(it, REQ_CAMERA);
            } else {
                toast("没有可用的相机应用");
            }
        } catch (Exception e) {
            toast("无法启动相机: " + e);
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        // v1.11.0：图片查看器里删除了某张图 → 同步把这条记录摘掉。
        // 查看器已经删了磁盘文件，这里只做「摘内存记录 + 清历史文件条目」，
        // purgeMsgs 里的 deleteLocalFileOf 再调一次是幂等的，文件已不存在直接返回 false。
        if (requestCode == REQ_VIEWER) {
            if (resultCode == RESULT_OK && data != null) {
                String key = data.getStringExtra("del_key");
                if (!TextUtils.isEmpty(key)) removeMsgByKey(key);
            }
            return;
        }
        if (resultCode != RESULT_OK) return;
        List<String> uris = new ArrayList<>();
        if (requestCode == REQ_CAMERA) {
            if (cameraUri != null) uris.add(cameraUri.toString());
        } else if (data != null) {
            if (data.getData() != null) uris.add(data.getData().toString());
            ClipData clip = data.getClipData();
            if (clip != null) {
                for (int i = 0; i < clip.getItemCount(); i++) {
                    Uri u = clip.getItemAt(i).getUri();
                    if (u != null) uris.add(u.toString());
                }
            }
        }
        if (uris.isEmpty()) return;
        List<String> targets = currentTargets();
        if (targets.isEmpty()) {
            // 记录用户选中的设备（含离线），上线后定向补发给它，而不是任意设备
            queuePending(uris, currentSelectedIds());
            return;
        }
        FlashApp.get().node().sendFiles(targets, uris);
    }

    /** 下拉框当前选中的设备 id（含离线）；"全部设备"视图返回空列表 */
    private List<String> currentSelectedIds() {
        int pos = targetSpinner == null ? 0 : targetSpinner.getSelectedItemPosition();
        String sel = pos >= 0 && pos < spinnerIds.size() ? spinnerIds.get(pos) : ALL_ID;
        List<String> out = new ArrayList<>();
        if (!ALL_ID.equals(sel)) out.add(sel);
        return out;
    }

    /** 没有在线目标：加入待发队列（持久化），设备上线后自动发送 */
    private void queuePending(List<String> uris) {
        queuePending(uris, new ArrayList<>());
    }

    private void queuePending(List<String> uris, List<String> targets) {
        queuePending(uris, targets, false);
    }

    private void queuePending(List<String> uris, List<String> targets, boolean broadcast) {
        FlashApp.get().pendingSends.add(
                new FlashApp.PendingSend(uris, new ArrayList<>(targets), null, broadcast));
        FlashApp.get().savePendingSends();
        // ★ v1.18.17 审计修复：入队即挂上周期重试。
        //   重试任务在"队列空"时会自动停止（省电），所以每次新入队都要重新挂，
        //   否则新消息要等到下次 onResume / 设备上线才可能被补发。
        FlashApp.get().schedulePendingRetry();
        rebuildPendingMsgs();
        refreshPendingBtn();
        toast(broadcast
                ? "当前没有在线设备，内容已保存，上线后自动发送给全部设备"
                : "目标设备不在线，内容已保存，上线后自动发送");
    }

    /** 同步"待发送"显示消息与队列（不入历史；发送成功后由正式消息替代） */
    private String uriDisplayName(String uriStr) {
        return FdUtil.uriDisplayName(uriStr);
    }

    private void rebuildPendingMsgs() {
        synchronized (msgs) {
            java.util.Iterator<Msg> it = msgs.iterator();
            while (it.hasNext()) {
                Msg m = it.next();
                if ("pending".equals(m.state)) it.remove();   // 文本与文件待发统一重建
            }
            List<FlashApp.PendingSend> ps = FlashApp.get().pendingSends;
            for (int i = 0; i < ps.size(); i++) {
                FlashApp.PendingSend p = ps.get(i);
                Msg m = new Msg();
                m.dir = "out";
                m.state = "pending";
                m.tid = "pending#" + i;
                if (p.isText()) {
                    m.kind = "text";
                    m.mid = null;
                    m.text = p.text;
                } else {
                    m.kind = "file";
                    // 摘要由 FlashApp.PendingSend.summary() 生成（含文件名净化），
                    // 与 Windows 端 _entry_text 同口径
                    m.file = p.summary();
                }
                m.targets = new ArrayList<>(p.targets);
                m.peerId = p.targets.isEmpty() ? "" : p.targets.get(0);
                // ★ v1.18.10 修复（用户第 2 条）：**群发待发送消息越界到私聊**。
                //
                // 根因：群发待发时 targets 为空、peerId 为空，belongsToView 的
                // "规则 3（无明确目标）→ 属于任何会话" 会把它判定成属于**每一台**
                // 设备的私聊 —— 于是「全部设备」里发的待发内容，会同时出现在
                // 每一个端对端对话框里。
                //
                // 修法：给待发送消息也打上频道标记，与真实发送路径（sendText）
                // 完全同口径：broadcast / 无具体目标 / 多目标 = group；单目标 = p2p。
                m.channel = channelFor(m.targets, p.broadcast);
                // 显示目标设备名，便于确认"发给谁"
                if (!p.targets.isEmpty()) {
                    JSONObject pr = peerMap.get(p.targets.get(0));
                    if (pr != null) m.peerName = pr.optString("name", "");
                }
                m.ts = p.ts > 0 ? p.ts : FdUtil.nowMs();
                msgs.add(m);
            }
        }
        refreshChat();
    }

    // ============================ 历史 ============================

    private void loadHistory() {
        new Thread(() -> {
            File dir = new File(getFilesDir(), "history");
            File[] files = dir.listFiles();
            List<Msg> loaded = new ArrayList<>();
            if (files != null) {
                for (File f : files) {
                    try {
                        for (JSONObject o : FdUtil.loadHistory(this,
                                f.getName().replace(".jsonl", ""), 500)) {
                            Msg m = msgFromJson(o);
                            if (m != null) loaded.add(m);
                        }
                    } catch (Exception ignored) {}
                }
            }
            loaded.sort(Comparator.comparingLong(a -> a.ts));
            // ★ 按 tid 去重（file 消息）：历史上因切聊天竞态可能固化过同 tid 双记录，
            //   加载时只保留最后一条（ts 最大），把脏数据一次性清掉
            java.util.Set<String> seenTids = new java.util.HashSet<>();
            for (int i = loaded.size() - 1; i >= 0; i--) {
                Msg x = loaded.get(i);
                if ("file".equals(x.kind) && x.tid != null && !x.tid.isEmpty()) {
                    if (!seenTids.add(x.tid)) loaded.remove(i);
                }
            }
            // 幽灵传输清理：重启后未完成的传输无法恢复，标记为中断（避免无效取消键）
            for (Msg m : loaded) {
                if ("file".equals(m.kind)) {
                    String s = m.state == null ? "" : m.state;
                    if ("sending".equals(s) || "started".equals(s)
                            || "progress".equals(s) || "offer".equals(s)
                            || "confirm".equals(s)) {
                        m.state = "failed";
                        m.reason = "应用重启，传输中断";
                    }
                }
            }
            ui.post(() -> {
                synchronized (msgs) {
                    msgs.clear();
                    msgs.addAll(loaded);
                    for (Msg m : msgs) indexMsg(m);
                }
                rebuildPendingMsgs();
                refreshChat();
            });
        }).start();
    }

    private Msg msgFromJson(JSONObject o) {
        try {
            Msg m = new Msg();
            m.kind = o.optString("kind", "text");
            m.dir = o.optString("dir", "in");
            m.peerId = o.optString("peer_id");
            m.peerName = o.optString("peer_name");
            m.mid = o.optString("mid");
            m.tid = o.optString("tid");
            m.text = o.optString("text");
            m.file = o.optString("file");
            m.mime = o.optString("mime");
            m.state = o.optString("state");
            m.path = o.optString("path");
            m.open = o.optString("open");
            m.src = o.optString("src");
            m.peerScheme = o.optString("peer_scheme");
            // ★ v1.18.10（用户第 2 条）：读回频道标记。
            //   若不持久化，重启后群聊/私聊的区分就丢了 —— 群发消息会重新
            //   落进每一台设备的私聊视图（老数据兜底规则会把它当"无目标"放行）。
            String ch = o.optString("channel", "");
            m.channel = ch.isEmpty() ? null : ch;
            m.size = o.optLong("size");
            m.transferred = o.optLong("transferred");
            m.ts = o.optLong("ts");
            // 从磁盘读回来的记录本身就是已落盘状态，状态变更可直接 upsert
            m.persisted = true;
            JSONArray t = o.optJSONArray("targets");
            if (t != null) {
                m.targets = new ArrayList<>();
                for (int i = 0; i < t.length(); i++) m.targets.add(t.getString(i));
            }
            return m;
        } catch (Exception e) {
            return null;
        }
    }

    private JSONObject msgToJson(Msg m) {
        JSONObject o = new JSONObject();
        try {
            o.put("kind", m.kind); o.put("dir", m.dir);
            o.put("peer_id", m.peerId == null ? "" : m.peerId);
            o.put("peer_name", m.peerName == null ? "" : m.peerName);
            if (m.mid != null) o.put("mid", m.mid);
            if (m.tid != null) o.put("tid", m.tid);
            o.put("text", m.text == null ? "" : m.text);
            o.put("file", m.file == null ? "" : m.file);
            o.put("mime", m.mime == null ? "" : m.mime);
            o.put("state", m.state == null ? "" : m.state);
            o.put("path", m.path == null ? "" : m.path);
            o.put("open", m.open == null ? "" : m.open);
            o.put("src", m.src == null ? "" : m.src);
            if (m.peerScheme != null && !m.peerScheme.isEmpty())
                o.put("peer_scheme", m.peerScheme);
            // ★ v1.18.10（用户第 2 条）：把频道标记写盘，重启后群聊/私聊区分不丢。
            if (m.channel != null && !m.channel.isEmpty())
                o.put("channel", m.channel);
            o.put("size", m.size); o.put("transferred", m.transferred); o.put("ts", m.ts);
            if (m.targets != null) o.put("targets", new JSONArray(m.targets));
        } catch (Exception ignored) {}
        return o;
    }

    private void indexMsg(Msg m) {
        if ("file".equals(m.kind) && m.tid != null) {
            if ("in".equals(m.dir)) byTidIn.put(m.tid, m);
            else byTidOut.put(m.tid, m);
        }
        if (m.mid != null) byMid.put(m.mid, m);
    }

    private void persist(Msg m) {
        // ★ v1.13.1：peerId 为空时不再直接丢弃。
        // 旧代码 `if (m.peerId == null || m.peerId.isEmpty()) return;` 看着安全，
        // 但接收路径的 peerId 来自事件字段，协议缺字段时就是空串 ——
        // 结果是"消息上屏了、一重启就没了 / 换个入口看就是空白"。
        // 现在回落到统一的 __local__ 归档桶，宁可让它在"全部设备"里可见。
        String pid = (m.peerId == null || m.peerId.isEmpty()) ? LOCAL_ARCHIVE_ID : m.peerId;
        if (m.peerId == null || m.peerId.isEmpty()) m.peerId = LOCAL_ARCHIVE_ID;
        // ★ v1.18.9：「保存聊天」关闭后不再写盘（用户第 5 条需求的配套语义）。
        //   注意仍要置 persisted=false，让后续 persistState 也一并跳过 ——
        //   否则同一次会话里状态变更仍会追加写，等于开关没生效。
        if (!Prefs.get(this).keepHistory()) {
            m.persisted = false;
            return;
        }
        FdUtil.appendHistory(this, pid, msgToJson(m));
        m.persisted = true;   // ★ v1.14.0：标记已落盘，后续状态变更走 upsert
    }

    /**
     * ★ v1.13.1：把一条消息的最新状态写回磁盘（覆盖式）。
     *
     * 旧代码只在内存里改 m.state，不落盘 —— 于是 ack/text_state 把状态改成 ok
     * 之后重启，loadHistory 读回的还是 sending，界面上又是"发送中…"，
     * 用户看到的现象就是"消息已经发出去了，状态永远停在发送中"。
     * 命中失败时退化为追加一行（宁可多一条也不丢状态）。
     */
    private void persistState(Msg m) {
        if (m == null) return;
        String pid = (m.peerId == null || m.peerId.isEmpty()) ? LOCAL_ARCHIVE_ID : m.peerId;
        if (m.peerId == null || m.peerId.isEmpty()) m.peerId = LOCAL_ARCHIVE_ID;
        boolean hit = FdUtil.upsertHistory(this, pid,
                m.mid, m.tid, msgToJson(m));
        if (!hit) FdUtil.appendHistory(this, pid, msgToJson(m));
    }

    private String keyOf(Msg m) {
        return m.ts + "|" + (m.mid != null ? m.mid : (m.tid != null ? m.tid : ""))
                + "|" + m.dir + "|" + m.kind;
    }

    // ==================== 按设备隔离视图（类微信单会话） ====================

    /**
     * 消息是否属于指定设备会话。
     *
     * ★ v1.18.9（用户第 6 条需求）：「全部设备」改为**纯群聊视图**。
     *
     * 用户原话：
     *   「全部设备功能针对里面发了消息的才能看到；对于端到端发送的，
     *     不单独在全部设备里面体现 —— 相当于群聊，个人设备发消息就过去，
     *     端到端私聊的不在里面展示。当然没有设备在线时只能发送到全部设备。」
     *
     * 因此把两件事拆开：
     *   · 全部设备视图 = **群聊频道**（channel == "group" 的消息）
     *   · 单设备视图   = 与这台设备的私聊（原有三规则不变）
     *
     * 边界：老数据 channel 为 null。历史上「全部设备」确实混过私聊内容，
     * 若一律按 p2p 处理，老用户的群聊记录会"消失"。折中方案 ——
     * 无 channel 的 out 消息若 targets 为空或含多个目标（真正的群发特征），
     * 仍视为 group；仅当 targets 明确指向单台设备时才排除。
     */
    private boolean belongsToView(Msg m, String peerId) {
        boolean isAll = (peerId == null || ALL_ID.equals(peerId));
        if (isAll) {
            // ---- 群聊频道 ----
            if ("group".equals(m.channel)) return true;
            if ("p2p".equals(m.channel)) return false;
            // 老数据兜底：只有"明显是群发"的才进群聊视图
            //   · 入向消息带 peerId（来自某台设备）→ 私聊，不混入
            //   · 出向 targets 指向单台具体设备 → 私聊，不混入
            if ("in".equals(m.dir)) return false;
            if (m.targets != null) {
                int n = 0;
                for (String t : m.targets) if (t != null && !t.isEmpty()) n++;
                return n != 1;              // 0 个（未定向/分享直发）或 ≥2 个（群发）
            }
            return true;
        }
        // ---- 单设备私聊 ----
        // 群聊消息不属于任何单设备会话（它只存在于「全部设备」里）
        if ("group".equals(m.channel)) return false;
        // ★ v1.18.10（用户第 2 条）：待发送且无任何具体目标的**群发**内容，
        //   不得落进任何一台设备的私聊视图。老队列里 broadcast 标记可能缺失，
        //   但"targets 全空 + 非定向"这一特征已足以判定它不是给某台设备的。
        if ("pending".equals(m.state)
                && (m.targets == null || m.targets.isEmpty())
                && (m.peerId == null || m.peerId.isEmpty())) {
            return false;
        }
        // 规则 1
        if (peerId.equals(m.peerId)) return true;
        // 规则 2
        if (m.targets != null && m.targets.contains(peerId)) return true;
        // 规则 3：无明确目标
        boolean noTarget = (m.targets == null || m.targets.isEmpty())
                && (m.peerId == null || m.peerId.isEmpty());
        return noTarget;
    }

    /** 根据当前视图选择推断该消息应属频道（发送时打标用） */
    private String channelFor(List<String> targets, boolean broadcast) {
        if (broadcast) return "group";
        if (targets == null || targets.isEmpty()) return "group";
        if (targets.size() > 1) return "group";     // 勾选多台 = 群发
        return "p2p";
    }

    /** 重建当前视图消息列表（不触碰 msgs 全量数据） */
    private void rebuildView() {
        List<Msg> out = new ArrayList<>();
        synchronized (msgs) {
            for (Msg m : msgs) {
                if (belongsToView(m, viewPeerId)) out.add(m);
            }
        }
        // ★ v1.13.0：上屏前最后一道去重保险。
        // 所有渲染都汇流到这里（refreshChat → rebuildView），所以在这投影一次
        // 比在十几个改动点各修一遍可靠得多：同一 tid 的接收文件消息只保留
        // 最早建的那条（它承载最新的 state/progress，先建后更新），
        // 重复建出的副本在此被挡在屏幕之外。
        List<Msg> dedup = new ArrayList<>(out.size());
        java.util.Set<String> seenInTid = new java.util.HashSet<>();
        for (Msg m : out) {
            if ("file".equals(m.kind) && "in".equals(m.dir)
                    && !TextUtils.isEmpty(m.tid)) {
                if (!seenInTid.add(m.tid)) continue;   // 已出现过同 tid，丢弃副本
            }
            dedup.add(m);
        }
        synchronized (viewMsgs) {
            viewMsgs.clear();
            viewMsgs.addAll(dedup);
        }
        updateEmptyView();
    }

    /** 空状态提示：单设备会话与全部设备视图给不同引导文案 */
    private void updateEmptyView() {
        if (emptyView == null) return;
        if (!viewMsgs.isEmpty()) {
            emptyView.setVisibility(View.GONE);
            return;
        }
        emptyView.setVisibility(View.VISIBLE);
        if (ALL_ID.equals(viewPeerId)) {
            emptyView.setText("暂无消息\n同一 Wi-Fi 下打开电脑端闪传即可互传\n\n点 ＋ 发送图片或文件");
        } else {
            String nm = "";
            JSONObject p = peerMap.get(viewPeerId);
            if (p != null) nm = p.optString("name", "");
            emptyView.setText((nm.isEmpty() ? "该设备" : nm) + " 暂无消息\n\n"
                    + "发消息或点 ＋ 发送文件给这台设备\n发送内容会归档到该设备的独立会话");
        }
    }

    /** 切换设备视图（Spinner 选中项变化时调用） */
    private void onViewPeerChanged(String peerId) {
        if (peerId == null) peerId = ALL_ID;
        if (peerId.equals(viewPeerId)) return;
        viewPeerId = peerId;
        // 切视图时退出多选，避免把 A 会话的勾选带到 B 会话
        if (selectMode) exitSelectMode();
        selectedKeys.clear();
        refreshChat();
        // 滚到底部看最新消息
        if (!viewMsgs.isEmpty()) chatList.setSelection(viewMsgs.size() - 1);
        // 视图标题跟随设备名（标题栏下方本机信息行之上不新增控件，直接更新自机行右侧）
        updateSelfLabel();
    }

    /**
     * 统一刷新：重建视图投影 + 通知列表。
     * 所有会改动 msgs 的地方都必须走这里 —— 忘记 rebuildView 会导致
     * 新消息在"全部设备"视图正常、切到单设备却看不到。
     */
    private void refreshChat() {
        rebuildView();
        if (adapter != null) adapter.notifyDataSetChanged();
    }

    // ============================ 节点事件 ============================

    private void onNodeEvent(JSONObject e) {
        ui.post(() -> handleEvent(e));
    }

    private void handleEvent(JSONObject e) {
        String ev = e.optString("event");
        // ★ v1.18.31：已删除（屏蔽）设备的事件直接丢弃。
        //   节点层已拒连，这里是防"删除瞬间正在途中"的那一包 text/transfer
        //   又把聊天记录写回来（写完设备又会从历史里冒出来）。
        if (("text".equals(ev) || "transfer".equals(ev))
                && Prefs.get(this).isBlocked(e.optString("peer_id"))) {
            return;
        }
        switch (ev) {
            case "peers": {
                peerMap.clear();
                JSONArray arr = e.optJSONArray("peers");
                int online = 0;
                if (arr != null) {
                    for (int i = 0; i < arr.length(); i++) {
                        JSONObject p = arr.optJSONObject(i);
                        if (p == null) continue;
                        String pid = p.optString("id");
                        // ★ v1.18.31：已删除（屏蔽）的设备不进内存列表。
                        //   节点层已不发现它，这里是 UI 侧的第二道闸
                        //   （防旧快照/竞态把删掉的设备又带回来）。
                        if (Prefs.get(this).isBlocked(pid)) continue;
                        peerMap.put(pid, p);
                        if (p.optBoolean("online")) online++;
                    }
                }
                onlineLabel.setText("在线 " + online);
                rebuildSpinner();
                // 设备上线：发送待发队列（成功后由正式消息替代待发送显示）
                // ★ v1.18.9：文本补发必须沿用 sendTextSync 返回的**真实 mid**，
                //   否则 ack/text_state 按 mid 匹配不到该气泡，
                //   状态会永久卡在「发送中」（接收端其实已收到）。
                // ★ v1.18.15：改为**确认送达才移除**的异步补发 —— 失败/超时的条目
                //   会留在队列里由周期重试再发，不会再"发失败且条目已丢"。
                FlashApp.get().flushPendingSendsAsync(
                        sentN -> {
                            if (sentN != null && sentN > 0) {
                                toast("设备已上线，已自动发送 " + sentN + " 条待发送内容");
                            }
                            // 无论成功与否都重建：成功的条目已移出队列（待发送气泡消失），
                            // 失败的仍在队列里（待发送气泡保留，等重试）
                            rebuildPendingMsgs();
                            refreshPendingBtn();
                        },
                        ps -> { /* 文件补发无额外回填 */ },
                        (ps, mid) -> {
                            List<String> tg = FlashApp.get().resolveTargets(
                                    ps, FlashApp.get().node().onlinePeerIds());
                            if (tg.isEmpty()) return;
                            Msg m = new Msg();
                            m.kind = "text"; m.dir = "out"; m.text = ps.text;
                            m.mid = mid;              // ★ 关键：真实 mid，不再置 null
                            m.peerName = "我"; m.state = "sending";
                            m.ts = FdUtil.nowMs();
                            m.targets = new ArrayList<>(tg);
                            m.peerId = tg.get(0);
                            // 补发的频道与原发送时保持一致（broadcast = 群聊）
                            m.channel = ps.broadcast ? "group"
                                    : channelFor(tg, false);
                            synchronized (msgs) { msgs.add(m); }
                            indexMsg(m);
                            persist(m);
                        });
                break;
            }
            case "text": {
                Msg m = new Msg();
                m.kind = "text"; m.dir = "in";
                m.peerId = e.optString("peer_id");
                m.peerName = e.optString("name");
                m.mid = e.optString("mid");
                m.text = e.optString("text");
                m.peerScheme = e.optString("scheme");
                m.ts = e.optLong("ts", FdUtil.nowMs());
                synchronized (msgs) { msgs.add(m); }
                indexMsg(m);
                persist(m);
                notifyIfHidden(m.peerName, m.text);
                refreshChat();
                break;
            }
            case "ack": {
                // ★ v1.13.1：ack 可能在任何时刻到达，此时 byMid 未必还持有该条
                // （切会话 / 历史重载都会 clear 索引）。旧代码只查内存索引，
                // 一旦 miss 就永远停在"发送中…"——用户看到"消息明明发出去了，
                // 状态却一直是发送中"。这里补一条按 mid 回扫 msgs 的兜底，
                // 并把状态落盘（否则重启后状态又退回 sending）。
                String ackMid = e.optString("mid");
                Msg m = byMid.get(ackMid);
                if (m == null && !TextUtils.isEmpty(ackMid)) {
                    synchronized (msgs) {
                        for (Msg x : msgs) {
                            if (ackMid.equals(x.mid)) { m = x; break; }
                        }
                    }
                    if (m != null) byMid.put(ackMid, m);
                }
                if (m != null && "out".equals(m.dir) && "sending".equals(m.state)) {
                    m.state = "ok";
                    m.mid = ackMid;
                    persistState(m);
                    adapter.notifyDataSetChanged();
                }
                break;
            }
            case "text_state": {
                // 同 ack：内存索引 miss 时回扫，并落盘状态，避免"永远发送中"
                String tsMid = e.optString("mid");
                Msg m = byMid.get(tsMid);
                if (m == null && !TextUtils.isEmpty(tsMid)) {
                    synchronized (msgs) {
                        for (Msg x : msgs) {
                            if (tsMid.equals(x.mid)) { m = x; break; }
                        }
                    }
                    if (m != null) byMid.put(tsMid, m);
                }
                if (m != null && "out".equals(m.dir)) {
                    m.state = "ok".equals(e.optString("state")) ? "ok" : "failed";
                    persistState(m);
                    adapter.notifyDataSetChanged();
                }
                break;
            }
            case "transfer":
                handleTransfer(e);
                break;
            case "log":
                if ("error".equals(e.optString("level")))
                    toast(e.optString("msg"));
                break;
            case "peer_merged": {
                // 同机跨版本升级：旧 ID 聊天记录并入新 ID 后重载
                final String oldId = e.optString("old"), newId = e.optString("new");
                // ★ v1.18.31：旧 ID 被删除过 → 新 ID 一并屏蔽。
                //   否则同一台手机换个版本（新 ID）上线，设备又回到列表里，
                //   "删掉的设备"被身份合并绕回来了。
                if (Prefs.get(this).isBlocked(oldId) && !newId.isEmpty()) {
                    Prefs.get(this).blockPeer(newId, e.optString("name"));
                    try { FlashApp.get().node().enforceBlocklist(); }
                    catch (Throwable ignored) {}
                    break;
                }
                new Thread(() -> {
                    FdUtil.mergeHistory(FlashApp.get(), oldId, newId);
                    FlashApp.get().historyMerged = true;
                }).start();
                break;
            }
        }
    }

    /**
     * v1.13.0：判断一条已有消息是否就是本次 recv 事件对应的那条接收记录。
     *
     * 主判据是 tid（同一次传输的 offer/started/progress/done 共用它）。
     * 但 tid 在协议缺失时会是空串，此时**不能**把所有空 tid 的接收消息
     * 误判成同一条（那会把不同文件合并掉），退化为"文件名 + 大小"双匹配。
     */
    private boolean isSameInboundFile(Msg x, String tid, JSONObject e) {
        if (x == null) return false;
        if (!"file".equals(x.kind) || !"in".equals(x.dir)) return false;
        boolean hasTid = !TextUtils.isEmpty(tid);
        if (hasTid) return tid.equals(x.tid);
        // tid 缺失：用 文件名+大小 兜底，仅当两者都非空时才算命中
        String f = e.optString("file");
        long sz = e.optLong("size");
        return !TextUtils.isEmpty(f) && f.equals(x.file) && sz == x.size && sz > 0;
    }

    private void handleTransfer(JSONObject e) {
        String kind = e.optString("kind");
        String tid = e.optString("tid");
        String state = e.optString("state");
        Msg m;
        if ("recv".equals(kind)) {
            // ★ v1.13.0：接收侧查重改为「以 msgs 列表为唯一事实源」。
            //
            // 为什么不再只信 byTidIn：同一张图的接收过程会先后产生
            // offer → confirm → started → progress… → done 多个 recv 事件，
            // 它们共享同一个 tid，本该合并成一条气泡。但 byTidIn 是一份内存
            // 索引，会在切会话 / 加载历史时被 clear()，窗口期内后续事件
            // 找不到索引就直接 new 出第二条 —— 用户实测的"电脑发一次图，
            // 安卓收到两遍"就是这样产生的（两条文件名/大小完全相同）。
            //
            // 现在先查内存索引（快路径），未命中就无条件回扫 msgs（慢路径），
            // 命中即复用并回填索引，双路径都以 tid 为准，杜绝重复建条。
            m = byTidIn.get(tid);
            if (m == null || !isSameInboundFile(m, tid, e)) {
                synchronized (msgs) {
                    for (Msg x : msgs) {
                        if (isSameInboundFile(x, tid, e)) { m = x; break; }
                    }
                }
                if (m != null) byTidIn.put(tid, m);
            }
            if (m == null) {
                m = new Msg();
                m.kind = "file"; m.dir = "in"; m.tid = tid;
                String pid = e.optString("peer_id");
                // ★ v1.13.1：来源设备未知时不留空串（空串会让 belongsToView 的
                // 规则 1 失配、persist 又被丢），统一落到 __local__ 归档桶，
                // 保证"全部设备"视图一定能看到这条接收记录。
                m.peerId = (pid == null || pid.isEmpty()) ? LOCAL_ARCHIVE_ID : pid;
                m.peerName = e.optString("name");
                m.file = e.optString("file");
                m.size = e.optLong("size");
                m.mime = e.optString("mime");
                m.peerScheme = e.optString("scheme");
                m.ts = FdUtil.nowMs();
                byTidIn.put(tid, m);
            }
            // 方案色可能随事件更新（offer 时后端才有 scheme），保持一致
            String sc = e.optString("scheme");
            if (!TextUtils.isEmpty(sc)) m.peerScheme = sc;
            m.state = state;
            m.transferred = e.optLong("transferred");
            m.speed = e.optDouble("speed", 0);
            m.reason = e.optString("reason");
            m.path = e.optString("path");
            m.open = e.optString("open");
            // ★ v1.18.18：断点续传字段
            m.attempt = e.optInt("attempt");
            m.haveChunks = e.optInt("have_chunks");
            m.totalChunks = e.optInt("total_chunks");
            // offer 仅预告；进入实际流程后首次事件上屏（修复不显示问题）
            if (!m.appended && !"offer".equals(state)) {
                m.appended = true;
                synchronized (msgs) { msgs.add(m); }
                persist(m);
                if ("done".equals(state)) notifyIfHidden(m.peerName, "发来文件：" + m.file);
            } else if (m.appended) {
                // ★ v1.13.1：已上屏的接收条目在状态推进（progress/done/failed）
                // 时把最新状态写回磁盘，否则重启后进度/结果全部丢失。
                persistState(m);
            }
            if ("confirm".equals(state) && !FlashApp.get().prefs().autoAccept()) {
                showConfirmDialog(m);
            }
        } else {
            m = byTidOut.get(tid);
            if (m == null) {
                m = new Msg();
                m.kind = "file"; m.dir = "out"; m.tid = tid;
                m.peerName = "我";
                m.file = e.optString("file");
                m.size = e.optLong("size");
                m.mime = e.optString("mime");
                m.src = e.optString("src");
                m.ts = FdUtil.nowMs();
                JSONArray t = e.optJSONArray("targets");
                m.targets = new ArrayList<>();
                if (t != null) for (int i = 0; i < t.length(); i++) m.targets.add(t.optString(i));
                m.targetStates = new HashMap<>();
                byTidOut.put(tid, m);
                synchronized (msgs) { msgs.add(m); }
                m.peerId = m.targets.isEmpty() ? "" : m.targets.get(0);
                persist(m);
            }
            String pid = e.optString("peer_id");
            if ("progress".equals(state) || "started".equals(state)) {
                if ("progress".equals(state)) {
                    m.transferred = e.optLong("transferred");
                    m.speed = e.optDouble("speed", 0);
                }
                m.state = "progress";
            } else {
                if (m.targetStates != null) m.targetStates.put(pid, state);
                // ★ v1.14.0：多目标发送改为「首个目标成功即视为完成」。
                // 旧逻辑要求所有目标都回 ok 才置 done，只要有设备离线/拒绝，
                // 状态就永远停在"发送中…"，用户看到"消息明明发出去了却一直转圈"。
                // 现在只要有一个目标 ok 就立即置 done（已送达）。
                boolean anyOk = false;
                boolean allTerminal = m.targetStates != null && !m.targetStates.isEmpty();
                if (m.targetStates != null) {
                    for (String s : m.targetStates.values()) {
                        if ("ok".equals(s)) { anyOk = true; }
                        if (!"ok".equals(s) && !"refuse".equals(s)
                                && !"cancel".equals(s) && !"fail".equals(s)) {
                            allTerminal = false;
                        }
                    }
                }
                if (anyOk) {
                    m.state = "done";
                    m.transferred = m.size;
                } else if (allTerminal) {
                    // 全部目标都给了终态但没有一个 ok → 整体判定为失败
                    m.state = "failed";
                    m.reason = "所有目标均未接收";
                } else if ("ok".equals(state)) {
                    m.state = "progress";
                } else {
                    m.state = "refuse".equals(state) ? "refused"
                            : "cancel".equals(state) ? "cancelled"
                            : "fail".equals(state) ? "failed" : state;
                    m.reason = e.optString("reason");
                }
            }
            // ★ v1.14.0：发送侧状态同样要落盘，否则重启后回退成"发送中"。
            // 注意不能用 m.appended 判断——那是入场动画标记，getView 里会被立刻
            // 置回 false；这里用持久化专用的 persisted 标记（发送消息建条时已写盘）。
            if (m.persisted) persistState(m);
        }
        refreshChat();
    }

    private void showConfirmDialog(Msg m) {
        if (isFinishing() || isDestroyed() || m.dialogShown) return;
        m.dialogShown = true;
        // ★ v1.16.0：换成微信风格对话框（上下堆叠按钮 + 1px 分隔线）
        FdDialog.show(this, "收到文件",
                m.peerName + " 想发送：\n" + m.file
                        + "（" + FdUtil.fmtSize(m.size) + "）",
                "接收", "拒绝",
                () -> FlashApp.get().node().acceptInbound(m.tid),
                () -> FlashApp.get().node().rejectInbound(m.tid),
                false);
    }

    private void notifyIfHidden(String title, String body) {
        if (!hasWindowFocus()) toast(title + ": " + body);
    }

    // ============================ 长按菜单（微信式二级弹出）/ 多选删除 ============================

    /**
     * v1.18.9：文本消息的**专属长按菜单**（不依赖系统 ActionMode）。
     *
     * 与 `showMsgMenu` 的区别：那个是文件/兜底通用菜单；本方法专供
     * 正文 TextView 长按调用 —— 长按已由本人程序化 `selectAll()`，
     * 所以这里「复制」取的是**当前选区**（无选区则全文），必定成功。
     *
     * 复用现成的 `makeMenuItem` 视觉与 `onMenuAction` 分发，
     * 只对「复制 / 全选」做选区感知的重载，避免再写一套按钮。
     */
    private void showTextMenu(Msg m, View anchor) {
        if (selectMode) return;
        final TextView tv = (anchor instanceof TextView) ? (TextView) anchor : null;
        // ★ v1.18.10：把 anchor 上挂的局部选择助手交给菜单动作使用，
        //   「复制」由它取选区（局部选择的核心诉求）。
        this._textMenuHelper = null;
        if (tv != null) {
            Object tag = tv.getTag(R.id.tag_sel_helper);
            if (tag instanceof TextSelectionHelper) {
                this._textMenuHelper = (TextSelectionHelper) tag;
            }
        }

        List<FdMenuIcon.Item> items = new ArrayList<>();
        items.add(new FdMenuIcon.Item("复制", FdMenuIcon.COPY));
        items.add(new FdMenuIcon.Item("全选", FdMenuIcon.MULTI));
        items.add(new FdMenuIcon.Item("多选", FdMenuIcon.MULTI));
        items.add(new FdMenuIcon.Item("删除", FdMenuIcon.DELETE));

        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setBackgroundResource(R.drawable.msg_popup_bg);
        box.setPadding(dp(4), dp(8), dp(4), dp(8));
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        for (FdMenuIcon.Item it : items) {
            row.addView(makeMenuItem(it, m, true), 0);
        }
        box.addView(row);

        dismissPopup();
        msgPopup = new android.widget.PopupWindow(
                box, ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT, true);
        msgPopup.setBackgroundDrawable(new android.graphics.drawable.ColorDrawable(
                android.graphics.Color.TRANSPARENT));
        msgPopup.setOutsideTouchable(true);
        // 用现成的定位逻辑（与 showMsgMenu 一致），避免又一份重复实现
        showMenuAt(anchor, box);
    }

    private void showMsgMenu(Msg m, View anchor) {
        if (selectMode) return;
        // ★ v1.16.0：菜单重做（用户反馈"按钮错乱严重、文本换行、
        // 「更多打开方式」与「其他应用打开」重复"）。
        //   ① 去掉重复项，只保留「其他应用打开」
        //   ② 每项 = Canvas 现画的图标 + 单行文字，强制不换行
        //   ③ 每行 5 项自动排版，放不下才换第二行（不会把文字挤成两行）
        List<FdMenuIcon.Item> items = new ArrayList<>();
        boolean isFileMsg = "file".equals(m.kind);
        boolean local = isFileMsg && hasLocalContent(m);
        boolean isImg = isFileMsg && FdUtil.isImageMime(m.mime);
        boolean isDoneImage = isImg && "done".equals(m.state == null ? "" : m.state);

        if ("text".equals(m.kind)) {
            // ★ v1.18.4：正常路径下文本长按会由系统文本选择模式接管
            // （见 textSelectionCallback 的悬浮菜单），走不到这里。
            // 保留这一项作为**兜底**：万一某些 ROM 上选区没能正常拉起，
            // 长按仍能弹出菜单完成复制。
            items.add(new FdMenuIcon.Item("复制", FdMenuIcon.COPY));
        }
        if (isFileMsg) {
            if (local) {
                items.add(new FdMenuIcon.Item("打开", FdMenuIcon.OPEN));
                items.add(new FdMenuIcon.Item("保存", FdMenuIcon.SAVE));
                items.add(new FdMenuIcon.Item("分享", FdMenuIcon.SHARE));
            }
            if (isDoneImage) {
                items.add(new FdMenuIcon.Item("保存到相册", FdMenuIcon.GALLERY));
            }
            if (local) {
                // 「其他应用打开」= 强制弹系统应用选择器（WPS / 浏览器 / 其它）。
                // 旧版的「更多打开方式」与它完全等价，已按用户要求删除。
                items.add(new FdMenuIcon.Item("其他应用打开", FdMenuIcon.OTHER_APP));
            }
        }
        if (!local) {
            // 文件尚未到本地：提供重发（出侧）
            if (isFileMsg && "out".equals(m.dir) && !TextUtils.isEmpty(m.src)) {
                items.add(new FdMenuIcon.Item("重发", FdMenuIcon.RESEND));
            }
        }
        items.add(new FdMenuIcon.Item("删除", FdMenuIcon.DELETE));
        items.add(new FdMenuIcon.Item("多选", FdMenuIcon.MULTI));

        // ---- 浮层容器：垂直排版的若干行 ----
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setBackgroundResource(R.drawable.msg_popup_bg);
        // ★ v1.18.3：随图标一同收紧（原 6/10）
        box.setPadding(dp(4), dp(8), dp(4), dp(8));

        final int PER_ROW = 5;                       // 每行最多 5 项
        for (int i = 0; i < items.size(); i += PER_ROW) {
            LinearLayout row = new LinearLayout(this);
            row.setOrientation(LinearLayout.HORIZONTAL);
            int end = Math.min(i + PER_ROW, items.size());
            for (int j = i; j < end; j++) {
                FdMenuIcon.Item it = items.get(j);
                row.addView(makeMenuItem(it, m, items.size() <= PER_ROW), 0);
            }
            box.addView(row);
        }

        showMenuAt(anchor, box);
    }

    /**
     * 统一的菜单弹出定位（v1.18.9 抽出，供文本菜单与通用菜单共用）。
     *
     * 规则：水平居中于 anchor 并做左右贴边修正；垂直优先放 anchor 上方，
     * 上方空间不足时落到下方。抽出的意义是避免两份实现漂移 ——
     * 之前 {showMsgMenu} 里的这段逻辑若复制一份给文本菜单，后续改一处漏一处。
     */
    private void showMenuAt(View anchor, View box) {
        dismissPopup();
        msgPopup = new android.widget.PopupWindow(
                box, ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT,
                true);
        msgPopup.setBackgroundDrawable(new android.graphics.drawable.ColorDrawable(
                android.graphics.Color.TRANSPARENT));
        msgPopup.setOutsideTouchable(true);
        box.measure(View.MeasureSpec.UNSPECIFIED, View.MeasureSpec.UNSPECIFIED);
        int[] loc = new int[2];
        anchor.getLocationOnScreen(loc);
        int pw = box.getMeasuredWidth(), ph = box.getMeasuredHeight();
        int screenW = getResources().getDisplayMetrics().widthPixels;
        int x = loc[0] + Math.max(0, (anchor.getWidth() - pw) / 2);
        // 贴边修正：菜单不能超出屏幕左右
        x = Math.max(dp(6), Math.min(x, screenW - pw - dp(6)));
        int yAbove = loc[1] - ph - dp(6);
        if (yAbove > dp(24)) {
            msgPopup.showAtLocation(anchor, android.view.Gravity.NO_GRAVITY, x, yAbove);
        } else {
            msgPopup.showAtLocation(anchor, android.view.Gravity.NO_GRAVITY, x,
                    loc[1] + anchor.getHeight() + dp(6));
        }
    }

    /**
     * ★ v1.18.5：给 ActionMode（文本选择菜单）的菜单项挂矢量图标，
     * 对齐微信长按文本时的菜单观感。
     *
     * 说明：ActionMode 的菜单由系统渲染，**布局**（图标在上、文字在下）
     * 无法自定义；但**图标本身**可以通过 setIcon 提供，颜色与尺寸完全由
     * 我们自己的 FdMenuIcon 绘制，因此观感能贴近微信。
     */
    private void putActionIcon(android.view.MenuItem mi, int iconType) {
        mi.setIcon(new android.graphics.drawable.BitmapDrawable(
                getResources(),
                FdMenuIcon.make(this, iconType, 0xFFE9EAEC, ICON_ACTION_DP)));
        mi.setShowAsAction(android.view.MenuItem.SHOW_AS_ACTION_ALWAYS);
    }

    /**
     * 构造单个菜单项：上图标 + 下文字，整体可点。
     *
     * 关键点（对应用户"按钮文本换行、按钮大小不匹配"的反馈）：
     *   · 文字强制 singleLine，绝不允许换行
     *   · 项宽固定（一行 5 项时不额外撑开），保证图标纵向对齐
     *
     * ★ v1.18.3 精致化（用户反馈"长按弹出的图标过大，需要优化精致一点"）：
     *   · 图标 32dp → **26dp**（贴近微信长按菜单的观感，不再压过文字）
     *   · 项内边距 8/6 → **6/4**，图标与文字间距 5 → **3**
     *   · 文字 12sp → **11sp**，宽度上限 72 → **60dp**
     *   图标直接按 26dp 渲染（见 FdMenuIcon.make 的尺寸参数），
     *   不是把 32dp 位图缩进小 ImageView —— 缩放会发虚，重绘才锐利。
     */
    private View makeMenuItem(FdMenuIcon.Item it, Msg m, boolean compact) {
        LinearLayout cell = new LinearLayout(this);
        cell.setOrientation(LinearLayout.VERTICAL);
        cell.setGravity(android.view.Gravity.CENTER_HORIZONTAL);
        cell.setPadding(dp(6), dp(4), dp(6), dp(4));
        cell.setClickable(true);

        ImageView iv = new ImageView(this);
        iv.setImageBitmap(FdMenuIcon.make(this, it.icon, 0xFFE9EAEC, ICON_MENU_DP));
        int isz = dp(ICON_MENU_DP);
        iv.setLayoutParams(new LinearLayout.LayoutParams(isz, isz));
        cell.addView(iv);

        TextView tv = new TextView(this);
        tv.setText(it.label);
        tv.setTextColor(0xFFE9EAEC);
        tv.setTextSize(TypedValue.COMPLEX_UNIT_SP, 11);
        tv.setSingleLine(true);                       // ★ 绝不换行
        tv.setEllipsize(TextUtils.TruncateAt.END);
        tv.setGravity(android.view.Gravity.CENTER);
        tv.setMaxWidth(dp(60));
        LinearLayout.LayoutParams tlp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        tlp.topMargin = dp(3);
        cell.addView(tv, tlp);

        // 点击背景反馈
        android.util.TypedValue tv0 = new android.util.TypedValue();
        getTheme().resolveAttribute(android.R.attr.selectableItemBackground, tv0, true);
        if (tv0.resourceId != 0) cell.setBackgroundResource(tv0.resourceId);

        cell.setOnClickListener(v -> {
            dismissPopup();
            onMenuAction(it.label, m);
        });
        return cell;
    }

    /** 菜单动作分发（集中一处，避免散落在监听器里） */
    private void onMenuAction(String label, Msg m) {
        switch (label) {
            case "复制": {
                // ★ v1.18.10：优先复制**当前选区**（局部选择的核心诉求），
                // 无选区时回落到复制全文（文件菜单 / 未选择场景）。
                // 选区由 TextSelectionHelper 维护（自绘手柄，不依赖系统选择模式）。
                String text = m.text == null ? "" : m.text;
                TextSelectionHelper hlp = this._textMenuHelper;
                if (hlp != null) {
                    String sel = hlp.selectedText();
                    if (sel != null && !sel.isEmpty()) text = sel;
                }
                this._textMenuHelper = null;
                ClipboardManager cm = getSystemService(ClipboardManager.class);
                cm.setPrimaryClip(ClipData.newPlainText("text", text));
                toast("已复制");
                break;
            }
            case "全选": {
                // 让正文进入全选状态（选区的两个手柄会跳到首尾，可继续拖动收窄）
                TextSelectionHelper hlp = this._textMenuHelper;
                if (hlp != null) hlp.selectAll();
                this._textMenuHelper = null;
                break;
            }
            case "打开":
                openOrPreview(m);
                break;
            case "保存":
                saveFileToUserDir(m);
                break;
            case "分享":
                shareFileMsg(m);
                break;
            case "其他应用打开":
                openWithChooser(m);
                break;
            case "保存到相册":
                if (saveImageMsgToGallery(m)) toast("已保存到 相册/Pictures/FlashDrop");
                else toast("保存失败");
                break;
            case "重发":
                resendMsg(m);
                break;
            case "删除":
                confirmDeleteMessage(m);
                break;
            case "多选":
                enterSelectMode(m);
                break;
        }
    }

    /** ★ v1.16.0：删除确认走微信风格对话框 */
    private void confirmDeleteMessage(Msg m) {
        FdDialog.confirm(this, "删除消息", "删除后不可恢复，确定删除这条消息吗？",
                "删除", () -> deleteMsgs(Collections.singleton(keyOf(m))));
    }

    /** ★ v1.18.3：长按菜单图标尺寸（dp）。用户反馈旧版 32dp 过大，收到 26dp。 */
    private static final int ICON_MENU_DP = 26;

    /** ★ v1.18.5：文本选择菜单（ActionMode）的图标尺寸。
     *  参考微信长按文本的菜单，比 popup 再小一档 —— 22dp 与 11sp 文字
     *  的比例更贴近微信的观感。 */
    private static final int ICON_ACTION_DP = 22;

    private android.widget.PopupWindow msgPopup;

    /** ★ v1.18.10：文本长按菜单对应的**局部选择助手**。
     *  为什么用字段而不是闭包：菜单项统一走 onMenuAction(label, m) 分发，
     *  它拿不到 anchor；用字段传递最小、不必改分发签名。
     *  （v1.18.9 时这里存的是 TextView，v1.18.10 换成 Helper ——
     *   因为选区改由自绘手柄维护，不再读系统 getSelectionStart/End。） */
    private TextSelectionHelper _textMenuHelper;

    private void dismissPopup() {
        if (msgPopup != null && msgPopup.isShowing()) {
            try { msgPopup.dismiss(); } catch (Exception ignored) {}
        }
        msgPopup = null;
    }

    @Override
    public void onBackPressed() {
        if (msgPopup != null && msgPopup.isShowing()) {
            dismissPopup();
            return;
        }
        if (selectMode) {
            exitSelectMode();
            return;
        }
        if (panel.getVisibility() == View.VISIBLE) {
            hidePanel();
            return;
        }
        super.onBackPressed();
    }

    private void enterSelectMode(Msg first) {
        selectMode = true;
        selectedKeys.clear();
        if (first != null) selectedKeys.add(keyOf(first));
        actionBar.setVisibility(View.VISIBLE);
        updateSelectCount();
        adapter.notifyDataSetChanged();
    }

    private void exitSelectMode() {
        selectMode = false;
        selectedKeys.clear();
        actionBar.setVisibility(View.GONE);
        adapter.notifyDataSetChanged();
    }

    private void selectAll() {
        // 只全选当前设备视图内的消息（不能把别的会话一起删掉）
        synchronized (viewMsgs) {
            for (Msg m : viewMsgs) selectedKeys.add(keyOf(m));
        }
        updateSelectCount();
        adapter.notifyDataSetChanged();
    }

    private void updateSelectCount() {
        selectCountLbl.setText("已选择 " + selectedKeys.size() + " 条");
    }

    private void deleteSelected() {
        if (selectedKeys.isEmpty()) {
            toast("未选择任何消息");
            return;
        }
        final int n = selectedKeys.size();
        FdDialog.danger(this, "删除消息",
                "确定删除选中的 " + n + " 条消息吗？\n删除后不可恢复。",
                "删除", () -> {
                    deleteMsgs(new HashSet<>(selectedKeys));
                    exitSelectMode();
                }, null);
    }

    private void deleteMsgs(Set<String> keys) {
        // 先收集要删的消息（下面会把它们从 msgs 移除），用于连带删除磁盘文件
        List<Msg> gone = new ArrayList<>();
        synchronized (msgs) {
            for (Msg m : msgs) {
                if (keys.contains(keyOf(m))) gone.add(m);
            }
            msgs.removeIf(m -> keys.contains(keyOf(m)));
        }
        // 同步清理传输索引，避免删掉的消息被后续进度事件"复活"
        for (String k : keys) {
            Msg m = byMid.get(midOf(k));
            if (m != null) byMid.remove(m.mid);
        }
        new Thread(() -> FdUtil.deleteByIdentities(this, keys)).start();
        final int msgCount = gone.size();
        if (!gone.isEmpty()) {
            new Thread(() -> {
                int files = 0;
                for (Msg m : gone) {
                    if (deleteLocalFileOf(m)) files++;
                }
                final int nf = files;
                ui.post(() -> toast(nf > 0
                        ? "已删除 " + msgCount + " 条记录、" + nf + " 个文件"
                        : "已删除 " + msgCount + " 条记录"));
            }).start();
        } else {
            toast("已删除 " + keys.size() + " 条");
        }
        refreshChat();
    }

    /**
     * 删除消息对应的本地文件。
     * Android 10+ 走 MediaStore（content:// 或 Download/... 相对路径），
     * 低版本直接 File.delete()。返回是否真的删掉了一个文件。
     */
    private boolean deleteLocalFileOf(Msg m) {
        if (!"file".equals(m.kind)) return false;
        try {
            // ★ v1.16.0：用户在「保存的文件」目录里手动留存的文件受保护，
            // 不能被聊天页 / 设置页的删除键连带清掉（用户明确要求）。
            if (FdUtil.isProtectedPath(m.path) || FdUtil.isProtectedPath(m.open)) return false;
            // 1) content:// Uri 直接删
            if (!TextUtils.isEmpty(m.open) && m.open.startsWith("content://")) {
                try {
                    return getContentResolver().delete(Uri.parse(m.open), null, null) > 0;
                } catch (Exception ignored) {}
            }
            // 2) 绝对路径
            if (!TextUtils.isEmpty(m.path) && new File(m.path).isAbsolute()) {
                File f = new File(m.path);
                if (f.exists()) return f.delete();
                return false;
            }
            // 3) 展示用相对路径（Download/FlashDrop/<设备>/<name>）→ 查 MediaStore 按名删
            if (!TextUtils.isEmpty(m.path) && m.path.contains("/")) {
                return FdUtil.deleteSavedByRelPath(this, m.path);
            }
        } catch (Throwable ignored) {}
        return false;
    }

    /** 从 keyOf 生成的标识里还原 mid（key 形如 ts|midOrTid|dir|kind） */
    private static String midOf(String key) {
        int i = key.indexOf('|');
        if (i < 0) return "";
        int j = key.indexOf('|', i + 1);
        if (j < 0) return "";
        return key.substring(i + 1, j);
    }

    // ==================== 顶栏删除：弹窗勾选（下载文件 / 接收图片 / 聊天记录） ====================

    /**
     * 删除项分类（v1.10.0 按用户口径重命名）。
     * 顺序即弹窗展示顺序：下载文件 → 接收图片 → 聊天记录。
     */
    private static final int CAT_FILE = 0, CAT_IMAGE = 1, CAT_CHAT = 2;
    private static final String[] CAT_NAMES = {
            "下载文件", "接收图片（未保存到图库）", "聊天记录"};

    /**
     * 消息归类：文本 → 聊天记录；文件消息按 MIME 再分图片/文件。
     * 待发送（pending）不提供删除入口（属于队列而非会话记录），
     * 走"取消待发送"，因此这里排除。
     */
    private int categoryOf(Msg m) {
        if ("pending".equals(m.state)) return -1;
        if (!"file".equals(m.kind)) return CAT_CHAT;
        return FdUtil.isImageMime(m.mime) ? CAT_IMAGE : CAT_FILE;
    }

    private String labelOf(Msg m) {
        String who = "out".equals(m.dir) ? "发给 " + safeName(m) : safeName(m);
        if (CAT_CHAT == categoryOf(m)) {
            String t = m.text == null ? "" : m.text.replace('\n', ' ');
            if (t.length() > 40) t = t.substring(0, 40) + "…";
            return "[" + who + "] " + t;
        }
        String s = "[" + who + "] " + (m.file == null ? "" : m.file);
        if (m.size > 0) s += "　" + FdUtil.fmtSize(m.size);
        return s;
    }

    private String safeName(Msg m) {
        if (m.peerName != null && !m.peerName.isEmpty()) return m.peerName;
        JSONObject p = m.peerId == null ? null : peerMap.get(m.peerId);
        if (p != null) {
            String n = p.optString("name", "");
            if (!n.isEmpty()) return n;
        }
        return m.peerId == null ? "未知设备" : m.peerId.substring(0, Math.min(8, m.peerId.length()));
    }

    /**
     * 顶栏「删除」：三个分类的 CheckBox + 全选 + 取消/删除（二次确认）。
     * 作用域 = 当前设备选择栏选中的那台设备（viewPeerId），
     * 选「全部设备」时作用于所有设备。
     *
     * v1.10.0 修复：首版用 new java.util.List[]{} 建了长度 0 的数组，
     * 后面 checks[c] = row（c=0/1/2）必然越界抛 ArrayIndexOutOfBoundsException，
     * 表现就是"点删除键就闪退"。这里改为固定长度 3 的 CheckBox 数组。
     */
    private void showDeletePicker() {
        // 当前会话视图的消息（已按 viewPeerId 过滤）
        final List<Msg> scope;
        synchronized (viewMsgs) {
            scope = new ArrayList<>(viewMsgs);
        }
        // 三个分类的消息桶：只统计"确实有东西"的分类，避免出现 0 项
        final List<List<Msg>> buckets = new ArrayList<>();
        for (int i = 0; i < 3; i++) buckets.add(new ArrayList<>());
        for (Msg m : scope) {
            int c = categoryOf(m);
            if (c >= 0) buckets.get(c).add(m);
        }
        final boolean allScope = ALL_ID.equals(viewPeerId);
        final String scopeName = allScope ? "全部设备" : safeNameOf(viewPeerId);
        // 磁盘上该设备目录里已接收的文件/图片（消息被清过也要能删磁盘残留）
        final String folder = allScope ? null : FdUtil.folderNameOf(scopeName);
        final int[] disk = FdUtil.countSavedFiles(this, folder);
        final int chatN = FdUtil.countHistory(this, true);

        final int[] counts = new int[]{
                Math.max(buckets.get(CAT_FILE).size(), disk[0] - disk[1]),
                Math.max(buckets.get(CAT_IMAGE).size(), disk[1]),
                Math.max(buckets.get(CAT_CHAT).size(), chatN)};
        int total = counts[CAT_FILE] + counts[CAT_IMAGE] + counts[CAT_CHAT];
        if (total == 0) {
            toast("当前设备暂无可删除的内容");
            return;
        }

        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(20), dp(10), dp(20), 0);

        // 三个分类的 CheckBox（固定长度 3，v1.10.0 崩溃点已修）
        final CheckBox[] checks = new CheckBox[3];
        for (int c = 0; c < 3; c++) {
            CheckBox cb = new CheckBox(this);
            cb.setText(CAT_NAMES[c] + "（" + counts[c] + "）");
            cb.setTextColor(theme.text);
            cb.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
            cb.setPadding(0, dp(6), 0, dp(6));
            cb.setChecked(false);          // 默认不选择
            cb.setEnabled(counts[c] > 0);  // 没有内容的分类不可勾选
            if (counts[c] == 0) cb.setTextColor(theme.dim);
            checks[c] = cb;
            box.addView(cb);
        }

        // 底部提示
        TextView tip = new TextView(this);
        tip.setText("将删除「" + scopeName + "」下的所选内容，删除后不可恢复");
        tip.setTextColor(theme.dim);
        tip.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        tip.setPadding(dp(2), dp(10), dp(2), 0);
        box.addView(tip);

        // 全选按钮：在勾选区底部，只负责勾选/取消三类，不直接删除
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
            for (int c = 0; c < 3; c++) {
                if (counts[c] > 0) checks[c].setChecked(allOn[0]);
            }
            btnAll.setText(allOn[0] ? "取消全选" : "全选");
        });
        LinearLayout.LayoutParams allLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        allLp.topMargin = dp(8);
        box.addView(btnAll, allLp);

        // ★ v1.16.0：换成微信风格对话框（自定义勾选行 + 上下堆叠按钮）
        FdDialog.custom(this, "删除内容", null, box, "删除", "取消", true, () -> {
            final boolean delFile = checks[CAT_FILE].isChecked();
            final boolean delImg = checks[CAT_IMAGE].isChecked();
            final boolean delChat = checks[CAT_CHAT].isChecked();
            if (!delFile && !delImg && !delChat) {
                toast("请先勾选要删除的内容");
                return;
            }
            confirmScopedDelete(scopeName, folder, allScope,
                    delFile, delImg, delChat);
        });
    }

    /** 二次确认 → 真正执行删除（消息记录 + 磁盘文件） */
    private void confirmScopedDelete(final String scopeName, final String folder,
                                     final boolean allScope, final boolean delFile,
                                     final boolean delImg, final boolean delChat) {
        StringBuilder what = new StringBuilder();
        if (delFile) what.append("· 下载文件\n");
        if (delImg) what.append("· 接收图片\n");
        if (delChat) what.append("· 聊天记录\n");
        FdDialog.danger(this, "再次确认",
                "确定删除「" + scopeName + "」的以下内容吗？\n\n" + what
                        + "\n聊天记录将移出本机，文件将从下载目录删除，不可恢复。",
                "删除", () -> doScopedDelete(folder, allScope, delFile, delImg, delChat));
    }

    /**
     * 执行作用域删除。
     * 聊天记录：只清当前设备（全部设备视图则全清）对应的历史文件。
     * 文件/图片：只删 Download/FlashDrop/&lt;设备名&gt; 下的对应类型。
     *
     * v1.10.1 修复：原来只删磁盘文件、没把对应消息从内存 msgs 里摘掉，
     * 结果文件没了但气泡记录还在。现在统一走 detachMsgs + purgeMsgs，
     * 三类（聊天/文件/图片）都是"记录 + 磁盘文件"成对删除。
     */
    private void doScopedDelete(final String folder, final boolean allScope,
                                final boolean delFile, final boolean delImg,
                                final boolean delChat) {
        // 1) 按「作用域 + 勾选类型」挑出全部要删的消息条目
        final Set<String> keys = new LinkedHashSet<>();
        synchronized (msgs) {
            for (Msg m : msgs) {
                if (!(allScope || viewPeerId.equals(peerScopeOf(m)))) continue;
                int c = categoryOf(m);
                boolean hit = (c == CAT_CHAT) ? delChat
                        : (c == CAT_IMAGE) ? delImg
                        : (c == CAT_FILE) ? delFile : false;
                if (hit) keys.add(keyOf(m));
            }
        }
        // 2) 主线程：把消息从内存摘掉 —— 界面立刻不再显示这些记录
        final List<Msg> gone = detachMsgs(keys);
        refreshChat();
        final String scopeLabel = allScope ? "全部设备" : safeNameOf(viewPeerId);

        // 3) 后台：删对应磁盘文件 + 清历史文件（IO 慢，不能卡界面）
        new Thread(() -> {
            int files = purgeMsgs(gone, keys);
            // 磁盘残留（消息记录早先被清过、但文件还在）也一并清掉
            if (delFile) files += FdUtil.deleteSavedFiles(
                    MainActivity.this, folder, Boolean.FALSE, null)[0];
            if (delImg) files += FdUtil.deleteSavedFiles(
                    MainActivity.this, folder, Boolean.TRUE, null)[0];
            if (delChat) {
                if (allScope) FdUtil.clearAllHistory(MainActivity.this);
                else FdUtil.clearHistory(MainActivity.this, viewPeerId);
            }
            final int nf = files;
            final int nm = gone.size();
            ui.post(() -> {
                StringBuilder sb = new StringBuilder();
                if (nm > 0) sb.append(nm).append(" 条记录");
                if (nf > 0) {
                    if (sb.length() > 0) sb.append("、");
                    sb.append(nf).append(" 个文件");
                }
                toast(sb.length() == 0
                        ? "未找到可删除的内容"
                        : "已从「" + scopeLabel + "」删除 " + sb);
            });
        }).start();
    }

    /**
     * 把 keys 对应的消息从内存移除（含传输索引清理），返回被移除的消息列表。
     * 只动内存，必须在主线程调用；磁盘清理交给 purgeMsgs。
     */
    private List<Msg> detachMsgs(Set<String> keys) {
        List<Msg> gone = new ArrayList<>();
        if (keys == null || keys.isEmpty()) return gone;
        synchronized (msgs) {
            for (Msg m : msgs) {
                if (keys.contains(keyOf(m))) gone.add(m);
            }
            msgs.removeIf(m -> keys.contains(keyOf(m)));
        }
        // 同步清理传输索引，避免删掉的消息被后续进度事件"复活"
        for (String k : keys) {
            Msg m = byMid.get(midOf(k));
            if (m != null) byMid.remove(m.mid);
            byTidIn.remove(tidOf(k));
            byTidOut.remove(tidOf(k));
        }
        return gone;
    }

    /**
     * v1.11.0：按 keyOf 摘掉单条消息（供图片查看器回传调用）。
     * 走 detachMsgs + purgeMsgs 这条和批量删除完全一致的路径，
     * 保证「内存记录 / 传输索引 / 历史文件 / 磁盘文件」四处都不残留。
     */
    private void removeMsgByKey(String key) {
        if (TextUtils.isEmpty(key)) return;
        Set<String> keys = new LinkedHashSet<>();
        keys.add(key);
        final List<Msg> gone = detachMsgs(keys);
        refreshChat();
        if (gone.isEmpty()) {
            // 记录本来就不在（例如已删过），仍要确保历史文件条目被清掉
            new Thread(() -> FdUtil.deleteByIdentities(this, keys)).start();
            return;
        }
        new Thread(() -> {
            int files = purgeMsgs(gone, keys);
            ui.post(() -> toast(files > 0 ? "已删除" : "已删除记录"));
        }).start();
    }

    /** 删磁盘文件 + 删历史文件条目，返回删掉的磁盘文件数（后台线程调用） */
    private int purgeMsgs(List<Msg> gone, Set<String> keys) {
        int files = 0;
        for (Msg m : gone) {
            if (deleteLocalFileOf(m)) files++;
        }
        FdUtil.deleteByIdentities(this, keys);
        return files;
    }

    /** 从 keyOf 生成的标识里还原 tid（key 形如 ts|midOrTid|dir|kind） */
    private static String tidOf(String key) {
        int i = key.indexOf('|');
        if (i < 0) return "";
        int j = key.indexOf('|', i + 1);
        if (j < 0) return "";
        return key.substring(i + 1, j);
    }

    /** 消息所属设备（out 消息看 targets，in 消息看 peerId） */
    private String peerScopeOf(Msg m) {
        if ("in".equals(m.dir)) return m.peerId == null ? "" : m.peerId;
        if (m.targets != null && !m.targets.isEmpty()) return m.targets.get(0);
        return m.peerId == null ? "" : m.peerId;
    }

    /**
     * ★ v1.18.18：设备显示名 —— **备注优先**，其次自报名，最后 id 前 8 位。
     * 备注只存本机（Prefs.peer_aliases），不改写对端自报名。
     */
    private String displayNameOf(String pid, String selfName) {
        try {
            String alias = Prefs.get(this).getAlias(pid);
            if (!TextUtils.isEmpty(alias)) return alias;
        } catch (Throwable ignored) {}
        if (!TextUtils.isEmpty(selfName)) return selfName;
        return pid == null ? "" : pid.substring(0, Math.min(8, pid.length()));
    }

    private String safeNameOf(String peerId) {
        JSONObject p = peerMap.get(peerId);
        if (p != null) {
            String n = p.optString("name", "");
            if (!n.isEmpty()) return n;
        }
        return peerId.substring(0, Math.min(8, peerId.length()));
    }

    // ==================== 发送 ====================

    private void rebuildSpinner() {
        String prevId = viewPeerId;   // 记住当前会话，刷新列表后回到同一台设备
        spinLabels.clear();
        spinOnline.clear();
        spinnerIds = new ArrayList<>();
        // 「全部设备」在群聊视图下的语义见 refreshChat：只汇总群聊内容
        spinLabels.add("全部设备");
        spinOnline.add(true);
        spinnerIds.add(ALL_ID);

        List<JSONObject> sorted = new ArrayList<>(peerMap.values());
        sorted.sort((a, b) -> {
            if (a.optBoolean("online") != b.optBoolean("online"))
                return a.optBoolean("online") ? -1 : 1;
            return a.optString("name").compareTo(b.optString("name"));
        });
        // 在线设备：先入列，并顺手刷新「已知设备」档案
        java.util.Set<String> seen = new java.util.HashSet<>();
        for (JSONObject p : sorted) {
            String id = p.optString("id");
            // ★ v1.18.24：无 id 的脏数据不入列 —— 否则会多出一条名字为空、
            //   选中后 viewPeerId="" 切不出任何内容的"幽灵行"
            if (id == null || id.isEmpty()) continue;
            // ★ v1.18.31：已删除（屏蔽）的设备不入列，也不再写回 known_peers
            //   （rememberPeer 是删除后设备"复活"的另一条路径）
            if (Prefs.get(this).isBlocked(id)) continue;
            // ★ v1.18.18：显示备注名（不改 peer 数据本身）
            spinLabels.add(displayNameOf(id, p.optString("name")));
            spinOnline.add(p.optBoolean("online"));
            spinnerIds.add(id);
            seen.add(id);
            try {
                Prefs.get(this).rememberPeer(id, p.optString("name"),
                        p.optString("platform"), System.currentTimeMillis());
            } catch (Throwable ignored) {}
        }

        // ★ v1.18.9（用户第 4 条）：**发送过消息的设备跨网络不丢失聊天记录**。
        // 实时发现只覆盖"此刻在同一网段的设备"，设备一离线/换网络就整个从
        // 选择框消失 —— 用户看到的现象就是"聊天记录不见了"。
        // 这里把 known_peers 档案里的离线设备补进列表（受「离线聊天」开关控制），
        // 它们以灰色状态点呈现，点进去仍能看历史，也能继续发离线消息。
        if (Prefs.get(this).offlineChat()) {
            try {
                org.json.JSONArray known = Prefs.get(this).knownPeers();
                for (int i = 0; i < known.length(); i++) {
                    org.json.JSONObject o = known.optJSONObject(i);
                    if (o == null) continue;
                    String id = o.optString("id");
                    if (id.isEmpty() || seen.contains(id)) continue;
                    // ★ v1.18.31：已删除（屏蔽）的设备不以"离线设备"身份补位
                    if (Prefs.get(this).isBlocked(id)) continue;
                    if (!FdUtil.historyFile(this, id).exists()
                            && !o.has("last_seen")) continue;   // 从未有过会话 → 不占位
                    // ★ v1.18.18：离线设备同样显示备注名
                    spinLabels.add(displayNameOf(o.optString("id"),
                            o.optString("name")));
                    spinOnline.add(false);                      // 离线 → 灰点
                    spinnerIds.add(id);
                    seen.add(id);
                }
            } catch (Throwable ignored) {}
        }
        suppressSpinnerCb = true;
        try {
            if (spinnerAdapter == null) {
                spinnerAdapter = new DeviceSpinAdapter();
                targetSpinner.setAdapter(spinnerAdapter);
            } else {
                spinnerAdapter.notifyDataSetChanged();
            }
            int sel = spinnerIds.indexOf(prevId);
            targetSpinner.setSelection(sel >= 0 ? sel : 0);
            if (sel < 0) viewPeerId = ALL_ID;
        } finally {
            suppressSpinnerCb = false;
        }
    }

    private android.widget.BaseAdapter spinnerAdapter;
    /** ★ v1.18.20：设备框内刷新转圈的防重入标志 */
    private boolean scanSpinning = false;
    private final List<String> spinLabels = new ArrayList<>();
    private final List<Boolean> spinOnline = new ArrayList<>();

    /** 下拉项：设备名 + 在线状态点（在线绿色 / 离线灰色） */
    private class DeviceSpinAdapter extends android.widget.BaseAdapter {
        @Override public int getCount() { return spinLabels.size(); }
        @Override public Object getItem(int position) { return spinLabels.get(position); }
        @Override public long getItemId(int position) { return position; }

        @Override
        public View getView(int position, View convertView, ViewGroup parent) {
            LinearLayout row = new LinearLayout(MainActivity.this);
            row.setOrientation(LinearLayout.HORIZONTAL);
            // ★ v1.18.13（用户第 3 条）：顶部设备选择栏三项修正。
            //
            //   用户原话：
            //     ①「未打开的状态下 全部设备后面的状态灯未在最右侧」
            //     ②「点开后 设备名称被压缩了 没有显示完整（限长也可以
            //        但是现在的太短）且状态灯与设备名称过近」
            //     ③「设备状态灯要和打开的 全部设备 状态灯 对齐 删除的X
            //        对应在后面」
            //
            //   根因：名字用 weight=1f 吃掉全部剩余宽度，状态灯被顶到
            //   **名字之后**而非**行尾**；而收起态 Spinner 自身还有内边距，
            //   于是点离右边框总差一截。展开态又额外插了 weight=1f 的
            //   spacer 把 ✕ 推到行尾，双重 weight 挤压下名字只剩很短一截。
            //
            //   修法（统一收起态与展开态的骨架）：
            //     名字（定宽上限，可省略号）+ 状态灯（固定槽位，右对齐）
            //     + ✕ / 占位（固定槽位）
            //   状态灯与 ✕ 都用**固定宽度的槽位**，保证：
            //     · 收起态与展开态的灯在同一 x（③的对齐要求）
            //     · ✕ 永远排在灯**之后**（③的"X 对应在后面"）
            //     · 名字有确定的宽度上限，不再被 weight 挤成极短（②）
            row.setGravity(android.view.Gravity.CENTER_VERTICAL);
            row.setMinimumHeight(dp(40));
            // 左右内边距与收起态 Spinner 保持一致（14dp / 12dp）
            row.setPadding(dp(14), 0, dp(14), 0);

            TextView tv = new TextView(MainActivity.this);
            tv.setText(spinLabels.get(position));
            tv.setTextColor(theme.text);
            tv.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
            tv.setSingleLine(true);
            tv.setEllipsize(TextUtils.TruncateAt.END);
            tv.setGravity(android.view.Gravity.CENTER_VERTICAL);
            // ★ 名字：吃满「除两个固定槽位外」的剩余宽度。
            //   槽位总宽 = DOT_SLOT + X_SLOT，都用固定 dp，不再随内容浮动。
            LinearLayout.LayoutParams tlp = new LinearLayout.LayoutParams(
                    0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
            // 名字右侧与灯的槽位之间留 8dp，避免长名字直接顶到点上
            tlp.rightMargin = dp(8);
            row.addView(tv, tlp);

            // ---- 状态灯：固定槽位（宽度 DOT_SLOT），内部居中 ----
            //   固定槽位 = 无论在线/离线、无论名字多长，灯都落在同一 x。
            FrameLayout dotSlot = new FrameLayout(MainActivity.this);
            LinearLayout.LayoutParams slp = new LinearLayout.LayoutParams(
                    dp(DOT_SLOT_DP), ViewGroup.LayoutParams.MATCH_PARENT);
            dotSlot.setLayoutParams(slp);

            View dot = new View(MainActivity.this);
            GradientDrawable dg = new GradientDrawable();
            dg.setShape(GradientDrawable.OVAL);
            dg.setColor(spinOnline.get(position) ? theme.green : 0xFF6B7280);
            dot.setBackground(dg);
            FrameLayout.LayoutParams dlp = new FrameLayout.LayoutParams(
                    dp(9), dp(9), android.view.Gravity.CENTER_VERTICAL |
                    android.view.Gravity.RIGHT);
            dotSlot.addView(dot, dlp);
            row.addView(dotSlot);

            // ---- ✕ 槽位：固定宽度，保证收起态与展开态行骨架一致 ----
            //   ★ v1.18.20：收起态的空占位换成**刷新转圈**（用户需求：
            //   "设备小绿点后面框内的空白位置增加一个刷新的转圈按键，
            //   风格统一、无外框，代替目前的扫描按钮"）。
            //   · 无外框、颜色用 dim，与状态灯同尺寸量级，视觉融入框内
            //   · 点击 = 深度扫描（原顶栏「扫描」按钮的功能），期间 ↻ 旋转
            //   · child 设为 clickable 会消费点击，不会误触 Spinner 下拉
            FrameLayout xSlot = new FrameLayout(MainActivity.this);
            LinearLayout.LayoutParams xslp = new LinearLayout.LayoutParams(
                    dp(X_SLOT_DP), ViewGroup.LayoutParams.MATCH_PARENT);
            // ★ v1.18.21 视觉修正：v1.18.20 的转圈太小且高度不居中
            //   （16sp 文字在 32dp 槽位里视觉偏下、点击区域也小）。
            //   改为 20sp + 显式固定高度 + FrameLayout gravity 居中。
            // ★ v1.18.22：刷新按钮改用矢量图标（ic_rescan）替代文字 "↻"。
            //   根因：文字字形在字体 em-box 内并非几何居中，导致
            //   ① 视觉偏上/偏下（不居中）；② View 默认旋转轴心取 view 中心，
            //      而字形绘制中心偏离 view 中心 → 旋转看起来绕非中心转。
            //   矢量图标几何中心 = view 中心，setScaleType(CENTER) 后图标真正
            //   居中，rotationBy 也绕图标中心旋转，两个问题同时解决。
            android.widget.ImageView spin = new android.widget.ImageView(MainActivity.this);
            spin.setImageResource(R.drawable.ic_rescan);
            spin.setColorFilter(theme.dim);
            spin.setScaleType(android.widget.ImageView.ScaleType.CENTER);
            spin.setClickable(true);
            spin.setFocusable(true);
            spin.setOnClickListener(v -> {
                if (scanSpinning) return;          // 防重入
                scanSpinning = true;
                FlashApp.get().node().rescan(true);
                toast("正在扫描附近设备…");
                // pivot 默认 = view 中心 = 图标几何中心 → 绕中心匀速旋转
                v.animate().rotationBy(360 * 4).setDuration(2400L)
                        .withEndAction(() -> {
                            scanSpinning = false;
                            v.setRotation(0f);
                        }).start();
            });
            FrameLayout.LayoutParams spinSlp = new FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    android.view.Gravity.CENTER);
            xSlot.addView(spin, spinSlp);
            row.addView(xSlot, xslp);
            return row;
        }

        /**
         * 下拉列表项：在 getView（名称 + 状态灯 + ✕ 槽位）基础上，
         * 把 ✕ 槽位里的空占位换成可点的删除按钮。
         *
         * ★ v1.18.9 新增（用户第 4 条需求）：
         *   「在设备选择框 设备名称后面增加 删除的 X 符号，在状态灯后面，
         *     点击可以删除对话 及 收到发送的一切信息」
         *
         * ★ v1.18.13 重构：✕ 不再用「额外插 spacer weight=1f」的方式推到行尾
         *   （那会把名字挤成极短），而是复用 getView 已经留好的
         *   **固定宽度 ✕ 槽位**。好处：
         *     · 收起态/展开态行骨架完全一致 → 灯与名字位置绝对对齐
         *     · 名字可用宽度在展开前后不变 → 不会"点开后名字突然变短"
         *     · ✕ 天然排在状态灯**之后**
         *
         * 只在下拉项里给 X：Spinner 收起时（getView）保持干净，
         * 展开时才出现可点的删除入口 —— 与微信「长按会话删除」同样的克制思路，
         * 但这里用显式 X 更易发现。
         *
         * ★ v1.18.31（用户反馈「连接过的安卓手机不能在设备列表删除」）：
         *   ✕ 此前**只对有聊天记录的设备显示**（hasHistory 门槛）——
         *   "连接过但从没聊过/传过"的设备行里一个删除入口都没有，
         *   只能靠长按收起态选择器这条隐藏路径，用户根本找不到。
         *   现在**所有设备行统一给 ✕**（"全部设备"仍不给：聚合视图无对应会话）。
         *   v1.18.24 的教训保持不变：✕ 只设 clickable、**不设 focusable**
         *   （可聚焦子控件会让 AbsListView 把整行点击判给它，行就"点不动"）。
         *
         * 「全部设备」是聚合视图、不对应真实会话，故不提供 X。
         */
        @Override
        public View getDropDownView(int position, View convertView, ViewGroup parent) {
            View base = getView(position, convertView, parent);
            if (!(base instanceof LinearLayout)) return base;
            LinearLayout row = (LinearLayout) base;

            boolean isAll = position == 0;
            boolean hasSession = !isAll && spinnerIds.size() > position;
            String pid = spinnerIds.size() > position ? spinnerIds.get(position) : null;

            // ✕ 槽位 = getView 里加在最后的那一个 FrameLayout
            View last = row.getChildAt(row.getChildCount() - 1);
            if (!(last instanceof FrameLayout)) return row;
            FrameLayout xSlot = (FrameLayout) last;
            // ★ v1.18.24：槽位必须**无条件**先清空（里面可能是收起态残留的 ↻，
            //   它是 focusable 的，会把整行点击吃掉）；v1.18.31：清空后除
            //   「全部设备」外一律放 ✕，不再问有没有聊天记录。
            xSlot.removeAllViews();
            if (!hasSession || pid == null) return row;
            // ★ v1.18.24 修复（用户反馈「无记录的设备行点不动 / 在线设备也切不过去」）：
            //
            //   根因：getView() 给 ✕ 槽位塞的是 ↻ 刷新按钮，且它是
            //   setClickable(true) + **setFocusable(true)** 的。而 getView 同时
            //   被收起态和下拉行复用 —— 旧代码只对「有聊天记录」的行
            //   removeAllViews() 换成 ✕，**「无记录」的行在 hasHistory=false 时
            //   直接 return 了**，于是这类行的槽位里残留一个**可聚焦**的 ↻：
            //   AbsListView 把 item 点击判给了这个子控件（点它触发的是重新扫描，
            //   不是切换会话），整行表现为"点不动 / 切不过去"。
            //   刚发现、从未聊过的在线设备正是"无记录"，所以两个现象同源。
            //
            //   修法：**无论有无记录都先清空槽位**，再按需放 ✕。
            //   ★ v1.18.31：清空后除「全部设备」外**一律放 ✕**（见上方注释），
            //   ✕ 只 clickable 不 focusable，行点击不受影响。
            TextView x = new TextView(MainActivity.this);
            x.setText("✕");
            x.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
            x.setTextColor(theme.dim);
            x.setGravity(android.view.Gravity.CENTER);
            x.setTag(TAG_DELETE_X);
            // 只 clickable、**绝不 focusable**（v1.18.24 的教训）：
            // 可聚焦子控件会让 AbsListView 把整行点击判给它
            x.setClickable(true);
            x.setFocusable(false);
            final String delId = pid;
            final String delName = spinLabels.get(position);
            x.setOnClickListener(v -> confirmDeleteConversation(delId, delName));
            xSlot.addView(x, new FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.MATCH_PARENT));
            // ★ v1.18.19：长按监听从下拉行**撤掉** —— v1.18.18 挂在这里后
            //   用户反馈"下拉点击设备没有反应"（item 根视图挂 long-click
            //   会改变 AbsListView 的触摸判定，部分 ROM 上吞掉单击）。
            //   备注入口改挂收起态 Spinner 的长按（见 onCreate），下拉行
            //   恢复 v1.18.17 的纯净触摸链路。
            return row;
        }
    }

    /**
     * 状态灯槽位宽度（dp）。固定槽位宽度是「收起态 / 展开态 灯位置一致」的
     * 前提：灯用固定宽度容器承载，名字长度就再也影响不到灯的 x 坐标。
     */
    private static final int DOT_SLOT_DP = 22;

    /**
     * ✕ 槽位宽度（dp）。收起态放空占位、展开态放可点 ✕，
     * 保证两种状态下行骨架完全一致（名字可用宽度不随展开变化）。
     */
    private static final int X_SLOT_DP = 34;

    /** 下拉项 ✕ 的标识 tag（用于 convertView 复用时精确摘除） */
    private static final String TAG_DELETE_X = "fd_peer_delete_x";

    /**
     * ★ v1.18.19：设备选择对话框 —— 顶栏选择器的点击入口。
     *
     * 为什么用对话框而不是 Spinner 下拉：Spinner 的 onItemSelected 有
     * 大量隐式时序（同位置不回调、adapter 刷新后 stale position、
     * 下拉 item 点击被吞），真机上出现过"点击设备没有反应"。
     * 对话框的每个选项点击走的是我们自己的回调，机制上保证可达。
     */
    private void showDevicePicker() {
        if (spinLabels.isEmpty()) return;
        List<String> rows = new ArrayList<>();
        List<String> ids = new ArrayList<>();
        for (int i = 0; i < spinnerIds.size(); i++) {
            String pid = spinnerIds.get(i);
            boolean online = i < spinOnline.size() && spinOnline.get(i);
            boolean isAll = ALL_ID.equals(pid);
            String mark;
            if (isAll) mark = "👥 ";
            else if (online) mark = "🟢 ";
            else mark = "⚪ ";
            String cur = pid.equals(viewPeerId) ? "　✓" : "";
            rows.add(mark + spinLabels.get(i) + cur);
            ids.add(pid);
        }
        // ★ v1.18.21：搜索入口已迁到顶栏 🔍 按钮 + 会话内联搜索行
        FdDialog.list(this, "选择设备", "点击切换会话",
                rows, idx -> {
                    if (idx < 0 || idx >= ids.size()) return;
                    onViewPeerChanged(ids.get(idx));
                });
    }

    /**
     * ★ v1.18.18：长按设备下拉行弹出的操作菜单（备注 / 清除备注 / 删除会话）。
     * ★ v1.18.19：入口从下拉行改为**长按收起态选择器**（对当前设备生效）。
     */
    private void showPeerActions(String pid, String shownName) {
        if (pid == null || ALL_ID.equals(pid)) return;
        FdDialog.list(this, shownName, null,
                java.util.Arrays.asList("给设备起备注…", "清除备注", "删除会话"),
                which -> {
                    if (which == 0) showAliasEditor(pid, shownName);
                    else if (which == 1) clearAlias(pid);
                    else if (which == 2) confirmDeleteConversation(pid, shownName);
                });
    }

    /** 备注输入框（留空 = 清除备注，恢复显示设备自报名） */
    private void showAliasEditor(String pid, String shownName) {
        // ★ blank final 不能在 try/catch 两分支各赋一次
        //   （try 中赋值后若后续语句抛异常进入 catch，就成了第二次赋值）
        String cur0 = "";
        try { cur0 = Prefs.get(this).getAlias(pid); } catch (Throwable ignored) {}
        final String cur = cur0;
        android.widget.EditText input = new android.widget.EditText(this);
        input.setText(cur);
        input.setSelection(input.getText() == null ? 0 : input.getText().length());
        input.setSingleLine(true);
        input.setHint("仅本机显示，不影响对方");
        int pad = (int) (getResources().getDisplayMetrics().density * 20);
        android.widget.LinearLayout wrap = new android.widget.LinearLayout(this);
        wrap.setOrientation(android.widget.LinearLayout.VERTICAL);
        wrap.setPadding(pad, pad / 2, pad, 0);
        wrap.addView(input, new android.widget.LinearLayout.LayoutParams(
                android.view.ViewGroup.LayoutParams.MATCH_PARENT,
                android.view.ViewGroup.LayoutParams.WRAP_CONTENT));
        FdDialog.custom(this, "设备备注",
                "给「" + shownName + "」起个备注：",
                wrap, "保存", "取消", false, () -> {
                    String v = input.getText() == null ? "" : input.getText().toString().trim();
                    if (v.length() > 40) v = v.substring(0, 40);
                    try {
                        Prefs.get(this).setAlias(pid, v);
                    } catch (Throwable t) {
                        toast("备注保存失败");
                        return;
                    }
                    rebuildSpinner();          // 立即反映到选择框
                    refreshChat();             // 气泡里的设备名同步
                    if (v.isEmpty()) toast("已清除备注");
                    else toast("已备注为「" + v + "」");
                });
    }

    private void clearAlias(String pid) {
        try {
            if (Prefs.get(this).getAlias(pid).isEmpty()) {
                toast("该设备还没有备注");
                return;
            }
            Prefs.get(this).setAlias(pid, "");
        } catch (Throwable t) {
            toast("清除备注失败");
            return;
        }
        rebuildSpinner();
        refreshChat();
        toast("已清除备注，恢复显示设备原名");
    }

    /**
     * 确认删除某设备的一切痕迹（v1.18.9）。
     *
     * 覆盖用户要求的「删除对话 及 收到发送的一切信息」三件套：
     *   ① 聊天记录文件（history/<peer>.jsonl）
     *   ② 内存中该会话的消息（立即从界面消失）
     *   ③ 该设备保存目录下的收发文件（Download/FlashDrop/保存的文件/<name>）
     * 并顺带从 known_peers 档案里摘掉，避免它继续以「离线设备」身份占位。
     *
     * ★ v1.18.31：删除 = 同时进**持久屏蔽名单**（blocked_peers）。
     *   用户反馈「连接过的安卓手机不能在设备列表删除」——根因是设备还在
     *   同一网段，UDP 广播发现 + rebuildSpinner 的 rememberPeer 会把它
     *   **立刻加回列表**，forgetPeer 单靠摘档案拦不住。现在：
     *     · 节点层：广播不回应、连接直接拒、手动添加也拒（FlashNode）
     *     · UI 层：设备列表 / 离线补位 / 全局搜索全按名单过滤
     *     · 事件层：它的 text/transfer 事件直接丢弃（NodeService 分发处）
     *   误删可恢复：设置页「已删除的设备」→ 解除屏蔽。
     */
    private void confirmDeleteConversation(String pid, String name) {
        if (pid == null || pid.isEmpty()) return;
        try { dismissPopup(); } catch (Throwable ignored) {}
        String show = (name == null || name.isEmpty()) ? "该设备" : name;
        FdDialog.danger(this, "删除会话",
                "确定删除与「" + show + "」的会话吗？\n\n"
                        + "将清除该设备的聊天记录、收到的文件、发送过的文件（如有），\n"
                        + "并将其从设备列表移除。\n\n"
                        + "删除后该设备不再出现在设备列表，也不会再收到它的消息\n"
                        + "（误删可在设置页「已删除的设备」中恢复）。",
                "删除", () -> {
                    // ① 磁盘：历史 + 保存目录
                    new Thread(() -> {
                        try { FdUtil.clearHistory(MainActivity.this, pid); }
                        catch (Throwable ignored) {}
                        try {
                            FdUtil.deleteSavedFiles(
                                    MainActivity.this, saveFolderOf(pid),
                                    Boolean.FALSE, null);
                            FdUtil.deleteSavedFiles(
                                    MainActivity.this, saveFolderOf(pid),
                                    Boolean.TRUE, null);
                        } catch (Throwable ignored) {}
                        // ③ 档案：不再作为离线设备出现
                        try { Prefs.get(MainActivity.this).forgetPeer(pid); } catch (Throwable ignored) {}
                        // ★ v1.18.31：持久屏蔽 + 节点层立即断开现存连接
                        try { Prefs.get(MainActivity.this).blockPeer(pid, show); }
                        catch (Throwable ignored) {}
                        try { FlashApp.get().node().enforceBlocklist(); }
                        catch (Throwable ignored) {}
                        // ★ v1.18.18：同时清掉设备备注，避免留下永远不再显示的孤儿条目
                        try { Prefs.get(MainActivity.this).setAlias(pid, ""); }
                        catch (Throwable ignored) {}
                        ui.post(() -> {
                            // ② 内存
                            try { peerMap.remove(pid); } catch (Throwable ignored) {}
                            try { msgs.remove(pid); } catch (Throwable ignored) {}
                            if (pid.equals(viewPeerId)) viewPeerId = ALL_ID;
                            rebuildSpinner();
                            refreshChat();
                            toast("已删除与「" + show + "」的会话，该设备不会再出现");
                        });
                    }, "fd-del-conv").start();
                });
    }

    /** 该设备的保存目录名（与收发落地目录保持一致） */
    private String saveFolderOf(String pid) {
        try {
            Object p = peerMap.get(pid);
            if (p instanceof JSONObject) {
                String n = ((JSONObject) p).optString("name");
                if (n != null && !n.isEmpty()) return n;
            }
        } catch (Throwable ignored) {}
        return pid;
    }

    private List<String> currentTargets() {
        int pos = targetSpinner == null ? 0 : targetSpinner.getSelectedItemPosition();
        String sel = pos >= 0 && pos < spinnerIds.size() ? spinnerIds.get(pos) : ALL_ID;
        List<String> out = new ArrayList<>();
        if (ALL_ID.equals(sel)) {
            for (JSONObject p : peerMap.values())
                if (p.optBoolean("online")) out.add(p.optString("id"));
        } else {
            JSONObject p = peerMap.get(sel);
            if (p != null && p.optBoolean("online")) out.add(sel);
        }
        return out;
    }

    private void sendText() {
        String text = input.getText().toString().trim();
        if (text.isEmpty()) return;
        List<String> targets = currentTargets();
        if (targets.isEmpty()) {
            // 异步待发（v1.9.0）：没有在线设备时先保存，设备上线后自动发出
            input.setText("");
            hidePanel();
            hideIme();
            List<String> sel = currentSelectedIds();
            boolean bc = sel.isEmpty();     // 未选中具体设备 = 全部设备（群发语义）
            FlashApp.get().pendingSends.add(new FlashApp.PendingSend(
                    new ArrayList<>(), sel, text, bc));
            FlashApp.get().savePendingSends();
            // ★ v1.18.17 审计修复：文本入队同样要挂上周期重试（队列空时自动停）
            FlashApp.get().schedulePendingRetry();
            rebuildPendingMsgs();
            refreshPendingBtn();
            toast("当前没有在线设备，消息已保存到待发送，设备上线后自动发出");
            return;
        }
        input.setText("");
        hidePanel();
        hideIme();
        FlashNode node = FlashApp.get().node();
        String mid = node.sendText(targets, text);
        Msg m = new Msg();
        m.kind = "text"; m.dir = "out"; m.mid = mid; m.text = text;
        m.peerName = "我"; m.state = "sending"; m.ts = FdUtil.nowMs();
        m.targets = new ArrayList<>(targets);
        m.peerId = targets.get(0);
        // ★ v1.18.9：打上频道标记 —— 当前选中「全部设备」= 群聊；
        //   选中某台设备 = 私聊（进不了群聊视图）。
        m.channel = ALL_ID.equals(viewPeerId)
                ? "group" : channelFor(targets, false);
        synchronized (msgs) { msgs.add(m); }
        indexMsg(m);
        persist(m);
        refreshChat();
    }

    private void toast(String s) {
        Toast.makeText(this, s, Toast.LENGTH_SHORT).show();
    }

    /** ★ v1.15.0：2 秒提示（用户明确要求"弹出一个 2s 的提示"） */
    private void toast2s(String s) {
        Toast.makeText(this, s, Toast.LENGTH_LONG).show();
    }

    /** 待安装 APK 的 Uri：用户去授权安装权限后回来重试 */
    private Uri installApkRetry;

    // ============================ 列表适配器 ============================

    private class MsgAdapter extends BaseAdapter {
        @Override
        public int getCount() { return viewMsgs.size(); }
        @Override
        public Object getItem(int position) { return viewMsgs.get(position); }
        @Override
        public long getItemId(int position) { return position; }

        @Override
        public int getViewTypeCount() { return 4; }

        /**
         * ★ v1.18.0：显式声明视图类型，交给 ListView 按类型分桶回收。
         *
         * 旧代码只靠 `row.getTag(R.id.tag_view_type)` 在 getView 里手工比对，
         * 发现类型不符就把 convertView 丢回、重新 inflate。这有两个隐患：
         *   ① 被丢弃的那一行只活到本次 getView 结束，**永远进不了 recycle 池**，
         *      于是"收到文件那几行"反复经历 inflate → 首帧无 drawable → 错乱；
         *   ② 类型混杂时回收池命中率下降，inflate 次数变多，正好放大了问题①。
         * 让 ListView 自己按 4 种类型分桶后，文件卡片的 convertView 能稳定复用，
         * 配合 inflate 时预置的占位图标，错乱窗口被彻底关掉。
         */
        @Override
        public int getItemViewType(int position) {
            Msg m = viewMsgs.get(position);
            boolean out = "out".equals(m.dir);
            if ("text".equals(m.kind)) return out ? 1 : 0;
            return out ? 3 : 2;
        }

        private int layoutOf(Msg m) {
            boolean out = "out".equals(m.dir);
            return "text".equals(m.kind)
                    ? (out ? R.layout.item_text_out : R.layout.item_text_in)
                    : (out ? R.layout.item_file_out : R.layout.item_file_in);
        }

        @Override
        public View getView(int position, View convertView, ViewGroup parent) {
            Msg m = viewMsgs.get(position);
            View row = convertView;
            if (row != null) {
                Integer have = (Integer) row.getTag(R.id.tag_view_type);
                if (have == null || have != layoutOf(m)) row = null;
            }
            if (row == null) {
                row = getLayoutInflater().inflate(layoutOf(m), parent, false);
                row.setTag(R.id.tag_view_type, layoutOf(m));
                VH h = new VH();
                h.name = row.findViewById(R.id.msg_name);
                h.meta = row.findViewById(R.id.msg_meta);
                h.status = row.findViewById(R.id.msg_status);
                h.time = row.findViewById(R.id.msg_time);
                h.bar = row.findViewById(R.id.msg_bar);
                h.b1 = row.findViewById(R.id.msg_b1);
                h.b2 = row.findViewById(R.id.msg_b2);
                // ★ v1.18.10（用户第 3 条）：把气泡按钮的系统内缩清零，
                //   否则「取消」这类 2 汉字按钮会被截断（详见 FdUtil.normalizeButton）。
                FdUtil.normalizeButton(h.b1, dp(14), 0);
                FdUtil.normalizeButton(h.b2, dp(14), 0);
                h.thumb = row.findViewById(R.id.msg_thumb);
                h.typeIcon = row.findViewById(R.id.msg_typeicon);
                // ★ v1.18.0：布局膨胀后**立刻**给类型图标塞一张透明占位位图。
                // 原因见 FdFileIcon.placeholder() 的长注释：ImageView 无 drawable 时
                // 参与 ListView 首次测量会塌成 0 宽 → 卡片先按"没有图标"排一帧，
                // 用户看到的就是"短暂错乱"。有占位位图后固有尺寸恒定在 40x52dp。
                if (h.typeIcon != null) {
                    int ph = fileIconSize();
                    ViewGroup.LayoutParams plp0 = h.typeIcon.getLayoutParams();
                    if (plp0 == null || plp0.width != fileIconWidth()
                            || plp0.height != ph) {
                        h.typeIcon.setLayoutParams(
                                new LinearLayout.LayoutParams(fileIconWidth(), ph));
                    }
                    h.typeIcon.setImageBitmap(FdFileIcon.placeholder(ph));
                    h.iconKey = null;   // 占位图不是真图标，必须让 bind 走一次真绘制
                }
                h.ring = row.findViewById(R.id.msg_ring);
                row.setTag(h);
            }
            VH h = (VH) row.getTag();
            // 兜底：单条消息渲染失败不能拖垮整个列表（否则 App 永久进不去）。
            // 历史消息内容不可控（早期版本可能写入异常数据），渲染异常时跳过该行。
            try {
                bind(row, h, m, position);
            } catch (Throwable t) {
                android.util.Log.e("FlashDrop", "bind failed at pos=" + position, t);
                try {
                    if (h.name != null) h.name.setText("");
                    if (h.status != null) { h.status.setVisibility(View.GONE); }
                    if (h.bar != null) h.bar.setVisibility(View.GONE);
                    if (h.b1 != null) h.b1.setVisibility(View.GONE);
                    if (h.b2 != null) h.b2.setVisibility(View.GONE);
                    if (h.thumb != null) h.thumb.setVisibility(View.GONE);
                } catch (Throwable ignored) {}
            }
            // v1.11.0：新消息气泡入场（淡入 + 轻微上移）。
            // 只在 m.appended 为真时播一次：ListView 会复用 convertView，
            // 若每次 bind 都播，滚动时整屏气泡会不停闪。
            // 播完立刻把 appended 置 false，避免该行再次滚入时重播。
            try {
                if (m.appended) {
                    m.appended = false;
                    FdAnim.bubbleEnter(row);
                }
            } catch (Throwable ignored) {}
            return row;
        }
    }

    static class VH {
        TextView name, meta, status, time;
        ImageView thumb;
        ImageView typeIcon;          // ★ v1.14.0：文件类型图标（微信风格）
        String iconKey;              // ★ v1.17.0：当前已绘制的图标 key（扩展名|高|虚线态）
        ProgressBar bar;             // 旧横条（已废弃，保留兼容）
        ProgressBar ring;            // ★ v1.14.0：转圈进度
        Button b1, b2;
        // ★ v1.18.10（用户第 5 条）：当前行的局部选择助手。
        //   挂在 VH 上便于多选模式下主动 clear()，也便于菜单动作取选区文本。
        TextSelectionHelper selHelper;
        // ★ v1.18.2：原 `selectableSet`（文字消息是否已设 TextIsSelectable 的短路标志）
        // 已随「文本长按改走菜单」一并移除 —— 它正是导致部分行 focusable 状态
        // 不再稳定建立、长按无反应的环节。
        // v1.18.10 起进一步弃用系统 TextIsSelectable，改自绘手柄（见 TextSelectionHelper）。
    }

    /**
     * ★ v1.17.0：图标"身份串"。与 FdFileIcon 内部缓存 key 同构，
     * 用于判断 convertView 复用后当前图标是否需要重画 —— 相同则跳过
     * setImageBitmap，避免每次 getView 都触发一次 invalidate。
     */
    private static String iconKeyOf(String fileName, int height, boolean dimmed) {
        String ext = FdFileIcon.extOf(fileName);
        return (ext.isEmpty() ? "?" : ext) + '|' + height + '|' + (dimmed ? 1 : 0);
    }

    private void bind(View row, VH h, Msg m, int position) {
        FdTheme t = theme;
        boolean out = "out".equals(m.dir);
        // 气泡底色：发送侧=本机配色方案；接收侧=对方消息自带的方案（全局气泡）
        View bubble = (View) row.findViewById(R.id.msg_bubble);
        // ★ v1.13.0：先求出气泡的"实际底色"，再据此推导各行的文字色。
        // 旧代码把 name/meta/status 的颜色写死成主题色（t.text / t.dim），
        // 那是按"深色页面背景"设计的；气泡一旦是自定义方案色（浅绿/浅黄等），
        // 灰字压在浅底上对比度骤降 —— 这就是用户报的"颜色对比度不足"。
        int bubbleBg;
        if (out) {
            bubbleBg = t.bubbleOut;
        } else {
            int[] ps = FdTheme.schemeColors(m.peerScheme);
            // 无方案时回落到主题自带的接收气泡底色
            // （深色主题 #2D3038 / 浅色主题 #FFFFFF，与 bubble_in*.xml 一致）
            bubbleBg = ps != null ? ps[0] : (t.dark ? 0xFF2D3038 : 0xFFFFFFFF);
        }
        if (bubble != null) {
            GradientDrawable bg = theme.round(bubbleBg, 12, this);
            // ★ v1.16.0 浅色适配：浅色主题下接收气泡是 #FFFFFF，压在同为浅灰的
            // 页面底（#F2F3F5）上几乎看不见边界（用户报"浅色适配性差"）。
            // 这里给"浅底气泡"补一条极淡描边，界出卡片轮廓；深色气泡不动。
            if (FdTheme.perceivedLuminance(bubbleBg) > 0.82f) {
                bg.setStroke(Math.max(1, dp(1)), theme.dark
                        ? 0x1F000000 : 0x14000000);
            }
            bubble.setBackground(bg);
        }
        // 由气泡底色推导的三档前景色
        final int onText = FdTheme.onColorText(bubbleBg);   // 主文字（文件名 / 正文）
        final int onDim = FdTheme.onColorDim(bubbleBg);     // 次级文字（大小 / 状态 / 时间）
        // ★ v1.18.0：照片模式（微信式无气泡图片）下的文字**不在气泡里**，
        // 而是直接压在**页面底色**上，因此不能沿用 onText / onDim ——
        // 那两个值是按 bubbleBg 推的，而照片模式已经把气泡背景置空了。
        //
        // 实测这导致的对比度（WCAG 相对亮度比）：
        //   浅色主题：文字 #4B5563 压在页面 #F2F3F5 上 → 2.65（远低于 AA 的 4.5）
        //   深色主题：文字 #4B5563 压在页面 #191B1F 上 → 2.43 ← 深灰压近黑，
        //             用户看到的"文件名看不见"就是这个
        // 修法：照片模式一律改用**主题自身的正文/次级色**（t.text / t.dim），
        // 这两个值本来就是为"压在页面底色上"设计的。
        final int onPageText = t.text;   // 页面底色上的正文色
        final int onPageDim = t.dim;     // 页面底色上的次级色
        // 消息头像（小，标识来源）
        ImageView avatar = (ImageView) row.findViewById(R.id.msg_avatar);
        if (avatar != null) {
            String aname = "in".equals(m.dir) ? m.peerName : "我";
            String aseed = "in".equals(m.dir) ? m.peerId : "self";
            avatar.setImageBitmap(makeAvatar(aname == null || aname.isEmpty()
                    ? "?" : aname, aseed == null || aseed.isEmpty() ? "?" : aseed));
        }
        // 多选遮罩提示
        row.setAlpha(selectMode && selectedKeys.contains(keyOf(m)) ? 1f
                : selectMode ? 0.45f : 1f);
        // 时间戳：与上一条间隔 > 5 分钟时显示
        if (h.time != null) {
            // 注意必须用 viewMsgs（当前会话视图），用 msgs 会取到别的设备的消息，
            // 导致时间分隔符错乱
            boolean showTime = position == 0
                    || (m.ts - viewMsgs.get(position - 1).ts > 5 * 60 * 1000);
            if (showTime && m.ts > 0) {
                h.time.setText(TF.format(new Date(m.ts)));
                h.time.setTextColor(t.dim);
                h.time.setVisibility(View.VISIBLE);
            } else {
                h.time.setVisibility(View.GONE);
            }
        }
        boolean isFile = "file".equals(m.kind);
        boolean img = FdUtil.isImageMime(m.mime);
        // 微信式照片模式：图片完成收发后不套气泡，直接显示，下方小字"文件名 · 大小"
        boolean photoMode = isFile && img
                && ("done".equals(m.state) || "ok".equals(m.state));
        if (bubble != null && photoMode) {
            bubble.setBackground(null);
            bubble.setPadding(0, 0, 0, 0);
        }
        if (h.name != null) {
            if (photoMode) {
                h.name.setVisibility(View.GONE);
            } else {
                h.name.setVisibility(View.VISIBLE);
                h.name.setTextColor(onText);
                // ★ v1.15.0：文件名「严格两行」——第一行全部保留，
                // 超出部分在中间用 "..." 代替，结尾的扩展名保留
                // （对齐微信截图：`甘肃国钛拆除、砌筑、安装技术附件20....17.pdf`）。
                // 这里用换行符锁定两行，再由布局的 maxLines=2 兜底。
                h.name.setText(truncateFileName(
                        TextUtils.isEmpty(m.file) ? "文件" : m.file,
                        fileNameCharsPerLine(fileCardTextWidth())));
                h.name.setMaxLines(2);
                h.name.setEllipsize(TextUtils.TruncateAt.END);
                h.name.setMaxWidth(fileCardTextWidth());
                h.name.setWidth(fileCardTextWidth());
            }
        }
        if (h.meta != null) {
            if (photoMode) {
                h.meta.setVisibility(View.GONE);
            } else if (isFile) {
                // ★ v1.15.0：文件大小与状态（已保存 / 失败 / 待接收…）合并到
                // **同一行**显示（用户要求）。状态文字由下面的 status 段算出后
                // 回填到这里，因此本处只放"大小"，status 段再统一拼装。
                h.meta.setText(FdUtil.fmtSize(m.size));
                h.meta.setTextColor(onDim);
                h.meta.setMaxWidth(fileCardTextWidth());
            } else {
                h.meta.setText(m.text == null ? "" : m.text);
                // 文字消息正文：有对方方案时优先用方案自带的文字色（尊重用户配色），
                // 否则用按气泡底色推导的高对比色
                int[] ps = FdTheme.schemeColors(m.peerScheme);
                h.meta.setTextColor((!out && ps != null) ? ps[1] : onText);
                // ★ v1.18.10（用户第 5 条）：改用**自绘局部选择**替代系统选择模式。
                //
                // 用户连续三版反馈"局部选择文字还是不能用"。系统 textIsSelectable
                // 路线已确认在部分 ROM（三星 One UI 等）上静默失效：它要求
                //   mText instanceof Spannable && isEnabled() 在触摸那一刻成立，
                // 但 convertView 复用 / 主题重绘 / setText() 都可能把文字换回
                // 普通 String，框架随即判定"此文本不支持选择"直接放弃 ——
                // 表现就是长按毫无反应或只能全选。
                //
                // 新方案（与主流 IM 的"自由复制"实现同思路）完全自持：
                //   · 长按 → 立刻全选（保证可见反馈）
                //   · 自绘左右两个圆形手柄，拖动可把选区收窄到任意片段
                //   · 松手弹出自建菜单（复制选中 / 全选 / 多选 / 删除）
                // 详见 TextSelectionHelper 的类注释。
                //
                // 多选模式下不挂选择能力，让行点击（勾选）正常工作。
                if (h.meta instanceof BdTextView) {
                    BdTextView bd =
                            (BdTextView) h.meta;
                    if (bd.getTag(R.id.tag_sel_helper) == null) {
                        TextSelectionHelper hlp = TextSelectionHelper.attach(
                                bd, () -> {
                                    Msg mm = (Msg) bd.getTag(R.id.tag_msg);
                                    if (mm != null) showTextMenu(mm, bd);
                                });
                        bd.bindHelper(hlp);
                        bd.setTag(R.id.tag_sel_helper, hlp);
                    } else if (h.selHelper != (TextSelectionHelper)
                            bd.getTag(R.id.tag_sel_helper)) {
                        h.selHelper = (TextSelectionHelper)
                                bd.getTag(R.id.tag_sel_helper);
                    }
                    // 多选模式下退出选择态，避免与勾选争触摸
                    if (selectMode && h.selHelper != null
                            && h.selHelper.isActive()) {
                        h.selHelper.clear();
                    }
                }
                h.meta.setTag(R.id.tag_msg, m);   // 菜单动作时取当前消息
            }
            // 气泡限宽随屏幕（约 62%），避免长文本把头像挤出屏幕边缘
            h.meta.setMaxWidth(photoMode || isFile ? fileCardTextWidth()
                    : bubbleTextMaxWidth());
            h.meta.setVisibility(photoMode ? View.GONE : View.VISIBLE);
        }
        // ★ v1.15.0：把文件气泡**钉死**在固定宽度上。
        // 默认的 wrap_content 会让卡片跟着文字长短伸缩，同屏几张卡片长短不一
        // （用户反馈"卡片长度没有统一"）。这里显式指定宽高，配合布局里固定的
        // 文字区与图标尺寸，所有文件卡片宽度严格一致，完全对齐微信。
        //
        // ★ v1.17.0：加「值相同则不重设」的短路。
        // convertView 复用时 getView 会被高频调用（滚动、回滚、切换会话全都会走），
        // 旧写法每次无条件 setLayoutParams → 每次都 requestLayout 触发一次完整
        // 测量/布局，一屏十几张卡片叠加就是"卡顿 + 首帧错乱"的来源之一。
        // 宽度只在真正变化时才写回，稳态下零重排。
        if (bubble != null && isFile && !photoMode) {
            android.view.ViewGroup.LayoutParams lp = bubble.getLayoutParams();
            int want = fileCardWidth();
            if (lp != null && lp.width != want) {
                lp.width = want;
                lp.height = ViewGroup.LayoutParams.WRAP_CONTENT;
                bubble.setLayoutParams(lp);
            }
            // ★ v1.18.0：文字列容器也钉成固定宽。之前只有内部 TextView 固定，
            // 容器 wrap_content 会先按自然内容宽参与一次测量，再被顶开 ——
            // 这一次多余的测量就是"卡片短暂错乱"里最难消掉的一帧。
            View textCol = row.findViewById(R.id.msg_textcol);
            if (textCol != null) {
                android.view.ViewGroup.LayoutParams tlp = textCol.getLayoutParams();
                int tw = fileCardTextWidth();
                if (tlp != null && tlp.width != tw) {
                    tlp.width = tw;
                    textCol.setLayoutParams(tlp);
                }
            }
        } else if (bubble != null) {
            // 图片模式 / 文字消息：恢复自适应宽度
            android.view.ViewGroup.LayoutParams lp = bubble.getLayoutParams();
            if (lp != null && lp.width == fileCardWidth()) {
                lp.width = ViewGroup.LayoutParams.WRAP_CONTENT;
                bubble.setLayoutParams(lp);
            }
            // ★ v1.18.0：文字列同步回 wrap_content（照片模式下名字/元信息都 GONE，
            // 若残留固定宽会把图片顶出右侧空白）。
            View textCol = row.findViewById(R.id.msg_textcol);
            if (textCol != null) {
                android.view.ViewGroup.LayoutParams tlp = textCol.getLayoutParams();
                if (tlp != null && tlp.width != ViewGroup.LayoutParams.WRAP_CONTENT) {
                    tlp.width = ViewGroup.LayoutParams.WRAP_CONTENT;
                    textCol.setLayoutParams(tlp);
                }
            }
        }
        // 图片消息：微信式预览（收发双方都直接显示，保持宽高比）
        if (isFile && h.thumb != null) {
            android.graphics.Bitmap bm = img ? thumbCache.get(m.tid) : null;
            if (img) {
                h.thumb.setAdjustViewBounds(true);
                h.thumb.setMaxWidth(dp(200));
                h.thumb.setMaxHeight(dp(200));
                h.thumb.setScaleType(ImageView.ScaleType.FIT_CENTER);
            }
            if (img && bm != null) {
                h.thumb.setVisibility(View.VISIBLE);
                h.thumb.setBackground(null);
                h.thumb.setLayoutParams(new LinearLayout.LayoutParams(
                        ViewGroup.LayoutParams.WRAP_CONTENT,
                        ViewGroup.LayoutParams.WRAP_CONTENT));
                h.thumb.setImageBitmap(bm);
                h.thumb.setOnClickListener(v -> openImageViewer(m));
                // v1.12.0：长按图片弹菜单（保存到相册 / 删除 / 多选），
                // 单击仍进查看器（查看器内另有保存/转发/删除）
                h.thumb.setOnLongClickListener(v -> {
                    try {
                        v.performHapticFeedback(android.view.HapticFeedbackConstants.LONG_PRESS);
                    } catch (Throwable ignored) {}
                    showMsgMenu(m, v);
                    return true;
                });
            } else if (img && (photoMode || hasThumbSource(m))) {
                // 照片模式先给灰色占位块，加载完成后自适应
                h.thumb.setImageDrawable(null);
                h.thumb.setBackground(theme.round(t.card, 8, MainActivity.this));
                h.thumb.setLayoutParams(new LinearLayout.LayoutParams(dp(160), dp(120)));
                h.thumb.setVisibility(View.VISIBLE);
                h.thumb.setOnClickListener(v -> openImageViewer(m));
                // v1.12.0：长按弹菜单（保存到相册 / 删除 / 多选）
                h.thumb.setOnLongClickListener(v -> {
                    try {
                        v.performHapticFeedback(android.view.HapticFeedbackConstants.LONG_PRESS);
                    } catch (Throwable ignored) {}
                    showMsgMenu(m, v);
                    return true;
                });
                if (!loadingThumbs.contains(m.tid)) loadThumbAsync(m);
            } else {
                h.thumb.setVisibility(View.GONE);
            }
        }
        if (h.status != null) {
            String s = "";
            int color = t.dim;
            if (isFile) {
                switch (m.state == null ? "" : m.state) {
                    case "offer": s = "等待接收…"; break;
                    // ★ v1.18.10（用户第 3 条）：待发送文案太长，气泡被撑爆。
                    //   原文案 "⏳ 待发送 · 设备上线后自动发出"（15 字）在窄气泡里
                    //   要换行/挤压，观感很差。统一缩短为 6 字，语义不变：
                    //   ⏳ 待发送（上方 status 行已经点明"待发送"，不再重复解释）。
                    case "pending": s = "⏳ 待发送"; color = t.warn; break;
                    case "confirm": s = "对方请求发送文件，是否接收？"; color = t.warn; break;
                    case "started":
                    case "progress": {
                        int pct = (int) Math.min(100, m.transferred * 100 / Math.max(m.size, 1));
                        s = (out ? "发送中 " : "接收中 ") + pct + "%"
                                + (m.speed > 0 ? "  " + FdUtil.fmtSpeed(m.speed) : "");
                        color = t.accent;
                        break;
                    }
                    case "done":
                        // ★ v1.14.0：多目标下首个成功即 done，若还有目标未完成，
                        // 用"已送达"而非"接收中/发送中"，避免用户以为没发出去
                        // ★ v1.18.27：文件被删了就不能再显示"已保存" ——
                        //   用户在文件管理器/设置里删掉文件后，卡片状态必须同步
                        //   （用户实测"已经删除的文件还是显示已保存"）。
                        if (!out && fileGoneOf(m)) {
                            s = "文件已删除";
                            color = t.warn;
                        } else {
                            s = out ? "已送达" : "已保存";
                            color = t.green;
                        }
                        break;
                    case "ok": s = "已送达"; color = t.green; break;
                    case "refused": s = "对方拒绝接收"; color = t.warn; break;
                    case "cancelled": s = "已取消"; color = t.dim; break;
                    case "failed":
                        s = "失败 · " + (TextUtils.isEmpty(m.reason) ? "未知原因" : m.reason);
                        color = t.red;
                        break;
                    // ★ v1.18.18：自动重试 / 断点续传暂停
                    case "retrying":
                        s = "重试中（第 " + m.attempt + " 次）"
                                + (TextUtils.isEmpty(m.reason) ? "" : " · " + m.reason);
                        color = t.warn;
                        break;
                    case "paused":
                        s = m.totalChunks > 0
                                ? "已暂停，可续传（" + m.haveChunks + "/" + m.totalChunks + " 块）"
                                : "已暂停，可断点续传";
                        color = t.warn;
                        break;
                }
            } else if (out) {
                switch (m.state == null ? "" : m.state) {
                    // ★ v1.18.10（用户第 3 条）：文案精简。
                    //   原为 "⏳ 待发送 · 全部设备上线后自动发出" / "· 目标设备…"，
                    //   最长 18 字，在气泡里很占地方。现统一为 6 字。
                    case "pending":
                        s = "⏳ 待发送";
                        color = t.warn; break;
                    case "sending": s = "发送中…"; break;
                    case "ok": s = "已送达"; color = t.green; break;
                    case "timeout": s = "未收到回执"; break;
                    case "failed": s = "发送失败"; color = t.red; break;
                    // ★ v1.18.18：自动重试要在气泡上体现，
                    //   否则用户只看到"卡在发送中"，不知道设备在重连重试。
                    case "retrying":
                        s = "重试中（第 " + m.attempt + " 次）";
                        color = t.warn;
                        break;
                }
            }
            h.status.setText(s);
            // ★ v1.13.0：语义色（成功绿/失败红/等待黄）按气泡底色适配亮度，
            // 否则亮色语义色压在浅色气泡上会发糊（用户实测的对比度问题）
            h.status.setTextColor(FdTheme.onColorAccent(color, bubbleBg));
            h.status.setMaxWidth(photoMode || isFile ? fileCardTextWidth()
                    : bubbleTextMaxWidth());
            h.status.setMaxLines(1);
            h.status.setEllipsize(TextUtils.TruncateAt.END);

            if (isFile && !photoMode) {
                // ★ v1.15.0：文件卡片把「大小」与「状态」合并到**同一行**
                // （用户要求："文件大小显示的文案和 保存 失败 等文案放同一行"）。
                // 拼装后写进 meta，独立的 status 行隐藏，卡片因此只有两行文字。
                String merged = FdUtil.fmtSize(m.size);
                if (!TextUtils.isEmpty(s)) merged = merged + "  " + s;
                h.meta.setText(merged);
                h.meta.setTextColor(onDim);
                h.meta.setMaxWidth(fileCardTextWidth());
                h.meta.setMaxLines(1);
                h.meta.setEllipsize(TextUtils.TruncateAt.END);
                h.meta.setVisibility(View.VISIBLE);
                h.status.setVisibility(View.GONE);
            } else {
                h.status.setVisibility(TextUtils.isEmpty(s) ? View.GONE : View.VISIBLE);
            }
            if (photoMode) {
                // 照片模式：气泡下方小字 = 文件名 · 大小
                // ★ v1.18.0：改用 onPageDim（压在页面上），不再用 onDim（压在气泡上）
                h.status.setText((TextUtils.isEmpty(m.file) ? "图片" : m.file)
                        + " · " + FdUtil.fmtSize(m.size));
                h.status.setTextColor(onPageDim);
                h.status.setVisibility(View.VISIBLE);
            }
            // 链接识别：文字消息含链接时显示点击入口（弹出 复制/打开）
            if (!isFile && !selectMode) {
                final String url = FdUtil.firstUrl(m.text);
                if (url != null) {
                    h.status.setText("🔗 " + FdUtil.shortUrl(url, 36));
                    h.status.setTextColor(t.accent);
                    h.status.setVisibility(View.VISIBLE);
                    h.status.setOnClickListener(v -> showLinkMenu(url));
                } else {
                    h.status.setOnClickListener(null);
                }
            } else {
                h.status.setOnClickListener(null);
            }
        }
        // ★ v1.14.0：进度指示改为微信式「转圈」，废弃横向进度条。
        // 旧横条放在 wrap_content 容器里，宽度按 match_parent 撑满，
        // 长文件名或窄屏时会顶出气泡边框（用户报的"偶发超出卡片框"）。
        // 转圈是固定尺寸（13dp）的小控件，永远不会溢出，也更贴近微信观感。
        boolean transferring = isFile
                && ("started".equals(m.state) || "progress".equals(m.state));
        if (h.ring != null) {
            h.ring.setVisibility(transferring ? View.VISIBLE : View.GONE);
            if (transferring) {
                // 转圈与气泡底色保持对比（浅色气泡上用深色圈）
                try {
                    float lum = FdTheme.perceivedLuminance(bubbleBg);
                    int ring = lum > 0.55f ? 0xFF4B5563 : 0xFFFFFFFF;
                    h.ring.getIndeterminateDrawable()
                            .setTintList(android.content.res.ColorStateList
                                    .valueOf(ring));
                } catch (Throwable ignored) {}
            }
        }
        // 兼容：旧布局残留的横条一律隐藏（新版布局里它已归零）
        if (h.bar != null) h.bar.setVisibility(View.GONE);

        // ★ v1.16.0：文件类型图标（严格复刻微信文件卡片）。
        //  - 形状 → 圆角矩形 + 右上角切角（`FdFileIcon` 内统一，v1.15.0 的
        //    "矩形缺右下角" 已按实测微信截图推翻）
        //  - 尺寸 → 40x52dp 竖长方形，宽高比 0.77（1440px 截图 ÷ 2.2 密度实测）
        //  - 位置 → 贴左、垂直居中（sent 侧镜像贴右）
        //  - 未接收/未下载 → 同色系**虚线描边**（不是虚化半透明）
        //  - 分类色由 FdFileIcon 内部按扩展名决定，APK 与 EXE 必须分开
        if (h.typeIcon != null) {
            boolean showIcon = isFile && !photoMode;
            if (showIcon) {
                // ★ v1.18.7：**接收侧状态自愈**。
                //
                // 历史里可能存在被"后台落库去重缺陷"写坏的中间态 ——
                // state 停在 offer / started，但文件其实已完整落盘
                // （电脑端显示"已送达"、手机 Download 里也能找到文件）。
                //
                // "文件确实在本地"是唯一可信的事实：据此把状态修正为 done，
                // 让**已经写坏的旧记录无需重传**就能显示正常。
                if (!out && hasLocalContent(m)
                        && !"done".equals(m.state) && !"ok".equals(m.state)) {
                    m.state = "done";
                }
                // 判定"是否已拿到本地文件"：已接收/已送达才算实色
                boolean got;
                if (out) {
                    // 发送侧：本地本来就有源文件，按传输是否完成区分
                    got = "done".equals(m.state) || "ok".equals(m.state);
                } else {
                    // ★ v1.18.7：接收侧改以**本地实况**为准。
                    // 状态字段曾因后台落库的去重缺陷停在中间态（offer/started），
                    // 导致"文件明明已完整落盘，界面却显示未接收/失败"。
                    // "文件确实在本地"是不会骗人的事实 —— 据此判定还能**自愈
                    // 已经写坏的历史记录**（不必让用户重传）。
                    got = hasLocalContent(m) || "done".equals(m.state);
                }
                int ih = fileIconSize();            // 高 52dp
                int iw = fileIconWidth();           // 宽 40dp
                h.typeIcon.setVisibility(View.VISIBLE);
                // ★ v1.17.0：尺寸与位图都做「变了才写」判断。
                // 图标 Bitmap 本身已在 FdFileIcon 内按扩展名缓存（同一格式所有
                // 文件共用一张），这里再避免重复 setLayoutParams / setImageBitmap
                // —— 后者即使传入同一张 Bitmap 也会触发一次 invalidate，
                // convertView 高频复用时就是"每次进入都在重建"的观感来源。
                ViewGroup.LayoutParams ilp = h.typeIcon.getLayoutParams();
                if (ilp == null || ilp.width != iw || ilp.height != ih) {
                    h.typeIcon.setLayoutParams(new LinearLayout.LayoutParams(iw, ih));
                }
                android.graphics.Bitmap ibm = FdFileIcon.make(m.file, ih, !got);
                if (h.typeIcon.getDrawable() == null || h.iconKey == null
                        || !h.iconKey.equals(iconKeyOf(m.file, ih, !got))) {
                    h.typeIcon.setImageBitmap(ibm);
                    h.iconKey = iconKeyOf(m.file, ih, !got);
                }
                h.typeIcon.setAlpha(1f);
            } else {
                h.typeIcon.setVisibility(View.GONE);
                h.typeIcon.setImageDrawable(null);
                h.iconKey = null;
            }
        }
        // ★ v1.15.0：文件卡片的交互改为「单击打开 / 长按弹菜单」（用户要求）——
        // 单击直接预览（图片进查看器、常见文档进内置预览器、其它交系统应用）；
        // 打开 / 保存 / 分享 / 更多打开方式 / 删除 / 多选 等动作全部移到长按菜单。
        if (bubble != null && isFile && !photoMode) {
            if (selectMode) {
                bubble.setOnClickListener(null);
                bubble.setOnLongClickListener(null);
                bubble.setClickable(false);
            } else {
                bubble.setClickable(true);
                bubble.setOnClickListener(v -> openOrPreview(m));
                bubble.setOnLongClickListener(v -> {
                    try {
                        v.performHapticFeedback(
                                android.view.HapticFeedbackConstants.LONG_PRESS);
                    } catch (Throwable ignored) {}
                    showMsgMenu(m, v);
                    return true;
                });
            }
        } else if (bubble != null && !isFile) {
            // ★ v1.18.6（关键修复）：文本消息的气泡必须**彻底透明** ——
            // 不可点、不可长按、不挡事件。
            //
            // 背景：v1.18.2 为了让"长按至少有点反应"，给文本气泡挂了
            // OnLongClickListener 并 setClickable(true)。但气泡是正文
            // TextView 的**父容器**：它一旦 clickable / longClickable，
            // 就会在事件分发里成为**拦截者** —— 长按落在气泡上被它消费，
            // 正文的 TextIsSelectable 永远进不去选择模式。
            // 这就是"长按文本没有选择光标"的最后一层原因。
            //
            // 现在文本消息的长按**只**由正文 TextView 自己处理
            // （配合 chatList.setItemsCanFocus(true) 把事件下传）。
            // 若某些 ROM 上仍拉不起选区，popup 兜底已由行级长按承担。
            bubble.setClickable(false);
            bubble.setLongClickable(false);
            bubble.setOnClickListener(null);
            bubble.setOnLongClickListener(null);
        } else if (bubble != null) {
            bubble.setOnClickListener(null);
            bubble.setOnLongClickListener(null);
            bubble.setClickable(false);
        }

        // 操作按钮
        Button b1 = h.b1, b2 = h.b2;
        String a1 = null, a2 = null;
        if (!selectMode) {
            if (isFile) {
                switch (m.state == null ? "" : m.state) {
                    case "confirm": a1 = "接收"; a2 = "拒绝"; break;
                    case "started": case "progress": a1 = "取消"; break;
                    case "pending": a1 = "取消"; break;
                    case "failed": case "refused": case "cancelled":
                        if (out && !TextUtils.isEmpty(m.src)) a1 = "重发";
                        break;
                    // ★ v1.14.0：「打开」按钮从卡片内移除（用户要求卡片更干净），
                    // 打开能力挪到卡片的点击菜单里（见 showMsgMenu）。此处留空。
                }
            } else if (out && "pending".equals(m.state)) {
                a1 = "取消";   // 文本待发送同样可取消（v1.9.0）
            }
        }
        if (b1 != null) {
            if (a1 == null) {
                b1.setVisibility(View.GONE);
            } else {
                final String act1 = a1;
                b1.setVisibility(View.VISIBLE);
                b1.setText(a1);
                b1.setBackground(theme.primary(MainActivity.this));
                b1.setOnClickListener(v -> {
                    switch (act1) {
                        case "接收":
                            FlashApp.get().node().acceptInbound(m.tid); break;
                        case "取消":
                            if (m.tid != null && m.tid.startsWith("pending")) {
                                cancelPendingMsg(m);
                                break;
                            }
                            if ("in".equals(m.dir)) FlashApp.get().node().cancelInbound(m.tid);
                            else FlashApp.get().node().cancelSend(m.tid);
                            break;
                        case "打开":
                            // ★ v1.15.0：与单击卡片一致——优先内置预览器，再退系统应用
                            openOrPreview(m);
                            break;
                        case "重发":
                            resendMsg(m);
                            break;
                    }
                });
            }
        }
        if (b2 != null) {
            if (a2 == null) {
                b2.setVisibility(View.GONE);
            } else {
                final String act2 = a2;
                b2.setVisibility(View.VISIBLE);
                b2.setText(a2);
                GradientDrawable dg = theme.round(0x00000000, 6, MainActivity.this);
                dg.setStroke(dp(1), t.red);
                b2.setBackground(dg);
                b2.setTextColor(t.red);
                b2.setOnClickListener(v -> {
                    if ("拒绝".equals(act2)) FlashApp.get().node().rejectInbound(m.tid);
                });
            }
        }
    }

    // ---------- 头像 / 文字选择 / 缩略图辅助 ----------

    private final Map<String, android.graphics.Bitmap> avatarCache = new HashMap<>();
    private static final int[] AVATAR_COLORS = {
            0xFF3B82F6, 0xFF8B5CF6, 0xFFEC4899, 0xFFF59E0B,
            0xFF10B981, 0xFF06B6D4, 0xFFEF4444, 0xFF84CC16};

    /** 生成圆形首字头像（按 seed 着色，缓存） */
    private android.graphics.Bitmap makeAvatar(String name, String seed) {
        int size = dp(28);
        String key = seed + "|" + size;
        android.graphics.Bitmap cached = avatarCache.get(key);
        if (cached != null) return cached;
        android.graphics.Bitmap bm = android.graphics.Bitmap.createBitmap(
                size, size, android.graphics.Bitmap.Config.ARGB_8888);
        android.graphics.Canvas cv = new android.graphics.Canvas(bm);
        // 注意：Math.abs(Integer.MIN_VALUE) 仍为负数，会导致负下标越界崩溃，
        // 因此用 floorMod 直接得到非负下标
        int h = Math.floorMod((seed + name).hashCode(), AVATAR_COLORS.length);
        android.graphics.Paint p = new android.graphics.Paint(
                android.graphics.Paint.ANTI_ALIAS_FLAG);
        p.setColor(AVATAR_COLORS[h]);
        cv.drawCircle(size / 2f, size / 2f, size / 2f, p);
        p.setColor(0xFFFFFFFF);
        p.setTextSize(size * 0.45f);
        p.setTextAlign(android.graphics.Paint.Align.CENTER);
        p.setTypeface(Typeface.DEFAULT_BOLD);
        android.graphics.Paint.FontMetrics fm = p.getFontMetrics();
        float ty = size / 2f - (fm.ascent + fm.descent) / 2f;
        String ch = (name == null || name.isEmpty()) ? "?" :
                name.substring(0, 1).toUpperCase(Locale.US);
        cv.drawText(ch, size / 2f, ty, p);
        avatarCache.put(key, bm);
        return bm;
    }

    // ---------- 文字选择 / 缩略图辅助 ----------

    /**
     * ★ v1.18.4：文本消息的**悬浮选择菜单**（对齐微信长按文字的交互）。
     *
     * 长按正文 → 系统进入文本选择模式（出现可选择的光标 / 左右把手），
     * 上方浮动菜单由本回调**完全接管**，并随选区动态切换。
     *
     * **菜单项顺序固定（用户指定）**：
     *
     *     ① 刚长按、光标未移动（或已全选）→ 复制 · 删除 · 多选   ← 消息级
     *     ② 拖动光标选中局部文字之后       → 复制 · 全选         ← 选区级
     *
     * 判定用 `moved && !full`：
     *   · 「刚长按」还没动光标 → 给消息级的 删除/多选 最顺手；
     *   · 「拖动把手」说明用户想精确选一段 → 给 全选 以便一键回到整体；
     *   · 点过「全选」后选区=全文，此时又回到消息级菜单，形成闭环。
     *
     * 实现要点：在 onPrepareActionMode 里先 `menu.clear()` 再自己 add ——
     * 系统会在 onCreateActionMode 之后自动填充默认项（复制/全选/分享…，
     * 且各 ROM 不一致），不 clear 会出现重复或多余项。
     */
    private android.view.ActionMode.Callback textSelectionCallback(TextView tv, Msg m) {
        return new android.view.ActionMode.Callback() {
            private static final int ID_COPY = 1;
            private static final int ID_DELETE = 2;
            private static final int ID_MULTI = 3;
            private static final int ID_ALL = 4;

            /** 进入选择模式时的初始选区，用来判断用户是否拖动过光标 */
            private int initS = -1, initE = -1;

            /** VH 复用时取当前绑定的消息 */
            private Msg current() {
                Object tag = tv.getTag(R.id.tag_msg);
                return tag instanceof Msg ? (Msg) tag : m;
            }

            /** 光标是否已被用户拖动过（首次调用时记录初始选区） */
            private boolean selectionMoved() {
                int s = tv.getSelectionStart(), e = tv.getSelectionEnd();
                if (initS < 0) {
                    initS = s;
                    initE = e;
                    return false;
                }
                return s != initS || e != initE;
            }

            @Override
            public boolean onCreateActionMode(android.view.ActionMode mode,
                                              android.view.Menu menu) {
                return true;
            }

            @Override
            public boolean onPrepareActionMode(android.view.ActionMode mode,
                                               android.view.Menu menu) {
                int s = tv.getSelectionStart(), e = tv.getSelectionEnd();
                boolean moved = selectionMoved();
                boolean full = tv.length() > 0 && s == 0 && e == tv.length();

                menu.clear();               // 丢弃系统默认项，完全自绘
                if (moved && !full) {
                    // ② 拖动光标选中局部 → 选区级：复制 · 全选
                    putActionIcon(menu.add(0, ID_COPY, 0, "复制"), FdMenuIcon.COPY);
                    putActionIcon(menu.add(0, ID_ALL, 1, "全选"), FdMenuIcon.SELECT_ALL);
                } else {
                    // ① 刚长按 / 已全选 → 消息级：复制 · 删除 · 多选
                    putActionIcon(menu.add(0, ID_COPY, 0, "复制"), FdMenuIcon.COPY);
                    putActionIcon(menu.add(0, ID_DELETE, 1, "删除"), FdMenuIcon.DELETE);
                    putActionIcon(menu.add(0, ID_MULTI, 2, "多选"), FdMenuIcon.MULTI);
                }
                return true;
            }

            @Override
            public boolean onActionItemClicked(android.view.ActionMode mode,
                                               android.view.MenuItem item) {
                final Msg cm = current();
                switch (item.getItemId()) {
                    case ID_COPY: {
                        // 有选区就复制选区内容，否则退化为整条文本
                        int s = tv.getSelectionStart(), e = tv.getSelectionEnd();
                        CharSequence sel = (s >= 0 && e > s)
                                ? tv.getText().subSequence(s, e)
                                : tv.getText();
                        ClipboardManager cb = getSystemService(ClipboardManager.class);
                        if (cb != null) {
                            cb.setPrimaryClip(ClipData.newPlainText("text", sel));
                        }
                        toast("已复制");
                        mode.finish();
                        return true;
                    }
                    case ID_ALL: {
                        // 一键全选：选区变为全文后菜单会切回「复制 · 删除 · 多选」。
                        //
                        // ★ 注：本项目编译用的 android.jar 里 TextView **未暴露
                        // setSelection(int,int)**（只有 getSelectionStart/End），
                        // 因此改走官方 android.text.Selection —— 选区的本质就是
                        // Spannable 上的 SELECTION_START/END 两个 span。
                        // setTextIsSelectable(true) 已把正文转成 SPANNABLE，
                        // 故此处 instanceof 判断可稳定通过。
                        CharSequence text = tv.getText();
                        if (text instanceof android.text.Spannable) {
                            android.text.Selection.setSelection(
                                    (android.text.Spannable) text, 0, text.length());
                        }
                        mode.invalidate();   // 主动请求刷新菜单
                        return true;
                    }
                    case ID_DELETE:
                        FdDialog.danger(MainActivity.this, "删除消息",
                                "确定删除这条消息吗？\n删除后不可恢复。",
                                "删除", () -> deleteMsgs(Collections.singleton(keyOf(cm))));
                        mode.finish();
                        return true;
                    case ID_MULTI:
                        enterSelectMode(cm);
                        mode.finish();
                        return true;
                    default:
                        return false;
                }
            }

            @Override
            public void onDestroyActionMode(android.view.ActionMode mode) {
                // 复位初始选区记录，下次长按重新开始判定
                initS = -1;
                initE = -1;
            }
        };
    }

    /** 气泡内文字最大宽度：屏宽约 62%（预留头像与边距，防止长文本挤出屏幕） */
    private int bubbleTextMaxWidth() {
        return (int) (getResources().getDisplayMetrics().widthPixels * 0.62f);
    }

    /**
     * ★ v1.17.0：文件卡片「整卡固定宽度」—— 本轮按用户要求**加长**。
     *
     * 用户反馈「文件卡片的长度较短，需要加长，统一和微信聊天对话框的卡片长度一样」。
     *
     * 本轮重新逐像素测量了两端原图（均为 1440px 宽、密度 2.2x ≈ 654.5dp 屏）：
     *
     *   微信（1000402955.jpg）文件卡片：
     *     卡片宽 714px = 324.5dp，占屏 0.496
     *     图标  137x173px = 62.3x78.6dp
     *     卡内**文字区** ≈ 586px = 266dp
     *
     *   FlashDrop 改前（1000402977.jpg）：
     *     卡片宽 709px = 322.3dp，占屏 0.492      ← 卡宽本身已与微信持平
     *     但文字区只有 462px = 210dp             ← 比微信**窄 56dp**（这才是"看起来短"的真因）
     *
     * 结论：卡宽不是问题，**文字区被右留白吃掉**才是问题。旧排版把图标
     * 固定在 40dp + 左右各 12dp 内边距，卡右还空出 44dp 死区。
     *
     * 修法（两步，都对齐微信）：
     *   ① 卡宽按**文字区目标**反推：文字区取微信实测 266dp
     *      → 卡宽 = 266 + 12(左) + 14(图标左边距) + 40(图标) + 12(右) = 344dp
     *      → 占屏 = 344 / 654.5 = 0.526（比改前 0.493 长约 7%，肉眼可辨）
     *   ② 图标右内边距由 12dp 收到与微信一致的贴边观感（见 fileCardTextWidth）
     *
     * 用比例而非绝对 dp：不同密度屏幕自动等比放大，窄屏也不会把文字挤没。
     */
    private float fileCardWidthRatio() {
        return 0.526f;
    }

    private int fileCardWidth() {
        int w = (int) (getResources().getDisplayMetrics().widthPixels
                * fileCardWidthRatio());
        // 极端窄屏兜底：至少能放下图标 + 一点文字
        int min = fileIconWidth() + dp(12 + 14 + 12 + 60);
        return Math.max(w, min);
    }

    /** 文件卡片文字区固定宽度（px）：由整卡宽度倒推，保证卡内留白与微信一致 */
    private int fileCardTextWidth() {
        return Math.max(dp(60), fileCardWidth() - dp(12 + 14 + 12) - fileIconWidth());
    }

    /** 文件类型图标宽度（px）：40:52 竖长方形，与微信实测一致 */
    private int fileIconWidth() {
        return dp(40);
    }

    /** 文件类型图标高度（px） */
    private int fileIconSize() {
        return dp(52);
    }

    /**
     * ★ v1.15.0：文件名截断为「严格两行」，第一行全部保留，
     * 超出部分在中间用「...」代替，**结尾的扩展名予以保留**
     * （对齐用户提供的微信截图：`甘肃国钛拆除、砌筑、安装技术附件20....17.pdf`）。
     *
     * @param name  原始文件名
     * @param lineW 每行可容纳的字符数
     */
    private String truncateFileName(String name, int lineW) {
        if (TextUtils.isEmpty(name)) return "";
        if (lineW < 6) lineW = 6;
        int total = lineW * 2;                 // 两行总容量
        if (name.length() <= total) return name;

        // 拆出扩展名（结尾要保留）
        String ext = "";
        String stem = name;
        int dot = name.lastIndexOf('.');
        if (dot > 0 && dot < name.length() - 1 && name.length() - dot <= 9) {
            ext = name.substring(dot);         // 含"."
            stem = name.substring(0, dot);
        }

        // 结尾保留段：扩展名 + 前面几个字符（微信是 "20....17.pdf" 这种观感）
        String tail = "";
        int keepTail = Math.min(4, Math.max(0, stem.length() - 2));
        if (keepTail > 0) tail = stem.substring(stem.length() - keepTail);
        String tailFull = tail + ext;

        // 第一行：原样保留前 lineW 个字符
        String line1 = name.substring(0, Math.min(lineW, name.length()));

        // 第二行：预算 = total - lineW，扣掉"..."和结尾段后，放剩余的中段
        int line2Budget = total - lineW;
        int dots = 3;
        int middleRoom = line2Budget - dots - tailFull.length();
        if (middleRoom < 1) {
            // 空间不足：优先保证尾部（扩展名最重要），省略号前不再放中段
            middleRoom = 0;
            if (dots + tailFull.length() > line2Budget) {
                // 连尾巴都放不下，退化为尾部右对齐截断
                tailFull = tailFull.substring(
                        Math.max(0, tailFull.length() - (line2Budget - dots)));
            }
        }
        // 中段从第一行结束处继续取（保证"第一行全部保留"的连续观感）
        String middle = "";
        if (middleRoom > 0) {
            int from = lineW;
            int to = Math.min(stem.length(), from + middleRoom);
            if (to > from) middle = stem.substring(from, to);
        }
        String line2 = middle + "..." + tailFull;

        return line1 + "\n" + line2;
    }

    /**
     * 估算文件名每行可容纳的字符数。
     * 中文字符约占一个全角宽，ASCII 约占半个 —— 取一个加权平均的保守值，
     * 宁可截断早一点，也不让文字顶出卡片（用户要求"严格限位"）。
     */
    private int fileNameCharsPerLine(int textWidthPx) {
        float sp = getResources().getDisplayMetrics().scaledDensity;
        float charW = 14f * sp * 0.62f;        // 14sp 字号，混合中英估宽
        if (charW <= 0) return 20;
        return Math.max(8, (int) (textWidthPx / charW));
    }

    private boolean hasThumbSource(Msg m) {
        return !TextUtils.isEmpty(m.path) || !TextUtils.isEmpty(m.open)
                || !TextUtils.isEmpty(m.src);
    }

    /**
     * ★ v1.14.0：判断这条文件消息是否已真正落到本地（用于图标虚化判定）。
     * 只要有可用路径或 content:// 打开句柄就算"已拿到"。
     */
    private boolean hasLocalContent(Msg m) {
        return !TextUtils.isEmpty(m.path) || !TextUtils.isEmpty(m.open);
    }

    /**
     * v1.11.0：打开全屏图片查看器（ImageViewerActivity）。
     *
     * 相对 v1.10.1 的 Dialog 版本，用户提了三点，全都在新查看器里解决了：
     *   1. 打开不能放大 → 双指捏合 1x~5x、双击 2.5x、放大后拖动（以双指中心为锚点）；
     *   2. 底部"保存/转发"按钮用 WRAP_CONTENT 横向拼贴，两边不对称、间距不均
     *      → 改为 weight=1 均分的**竖排卡片**（图标在上、文字在下），严格等宽等高；
     *   3. 不能长按保存/删除 → 长按图片弹出「保存到相册 / 转发 / 删除」，删除带二次确认。
     *
     * 传的是**当前视图内的全部图片**（微信同款左右切换 + "3/12" 计数），
     * 不是只有这一张。
     */
    private void openImageViewer(Msg m) {
        if (isFinishing() || isDestroyed() || m == null) return;
        final java.util.List<Msg> imgs = new ArrayList<>();
        int at = 0;
        // 用 viewMsgs（当前会话投影）而不是 msgs，跨设备切会话时不会把别的设备的图混进来
        java.util.List<Msg> src = (viewMsgs != null && !viewMsgs.isEmpty()) ? viewMsgs : msgs;
        synchronized (msgs) {
            for (Msg x : src) {
                if (!FdUtil.isImageMime(x.mime) && !"image".equals(x.kind)) continue;
                if (TextUtils.isEmpty(ImageViewerActivity.imageSrcOf(x))) continue;
                if (x == m) at = imgs.size();
                imgs.add(x);
            }
        }
        if (imgs.isEmpty()) { toast("图片不可用"); return; }
        ImageViewerActivity.start(this, imgs, at);
    }

    /** 保存位图到相册 Pictures/FlashDrop；返回 MediaStore Uri，失败 null */
    /** v1.12.0：把图片消息的原始文件流复制进相册（Pictures/FlashDrop），不重压缩保真 */
    private boolean saveImageMsgToGallery(Msg m) {
        String src = null;
        if (!TextUtils.isEmpty(m.open)) src = m.open;
        else if (!TextUtils.isEmpty(m.src)) src = m.src;
        else if (!TextUtils.isEmpty(m.path) && new File(m.path).isAbsolute()) src = m.path;
        if (TextUtils.isEmpty(src)) return false;
        String name = TextUtils.isEmpty(m.file)
                ? "flashdrop_" + System.currentTimeMillis() + ".jpg" : m.file;
        String mt = FdUtil.isImageMime(m.mime) ? m.mime : "image/jpeg";
        try {
            android.content.ContentResolver cr = getContentResolver();
            android.net.Uri dst;
            if (Build.VERSION.SDK_INT >= 29) {
                android.content.ContentValues cv = new android.content.ContentValues();
                cv.put(android.provider.MediaStore.Images.Media.DISPLAY_NAME, name);
                cv.put(android.provider.MediaStore.Images.Media.MIME_TYPE, mt);
                cv.put(android.provider.MediaStore.Images.Media.RELATIVE_PATH,
                        android.os.Environment.DIRECTORY_PICTURES + "/FlashDrop");
                dst = cr.insert(
                        android.provider.MediaStore.Images.Media.EXTERNAL_CONTENT_URI, cv);
                if (dst == null) return false;
            } else {
                File dir = new File(android.os.Environment.getExternalStoragePublicDirectory(
                        android.os.Environment.DIRECTORY_PICTURES), "FlashDrop");
                if (!dir.exists()) dir.mkdirs();
                dst = Uri.fromFile(new File(dir, name));
            }
            try (java.io.InputStream in = openStream(src);
                 java.io.OutputStream out = "content".equals(
                         dst.getScheme() == null ? "" : dst.getScheme())
                         ? cr.openOutputStream(dst)
                         : new java.io.FileOutputStream(new File(dst.getPath()))) {
                byte[] buf = new byte[16 * 1024];
                int n;
                while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
                out.flush();
            }
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    private android.net.Uri saveBitmapToGallery(android.graphics.Bitmap bm, String name,
                                                String mime) {        try {
            if (TextUtils.isEmpty(name))
                name = "flashdrop_" + System.currentTimeMillis() + ".jpg";
            String mt = FdUtil.isImageMime(mime) ? mime : "image/jpeg";
            if (Build.VERSION.SDK_INT >= 29) {
                android.content.ContentValues cv = new android.content.ContentValues();
                cv.put(android.provider.MediaStore.Images.Media.DISPLAY_NAME, name);
                cv.put(android.provider.MediaStore.Images.Media.MIME_TYPE, mt);
                cv.put(android.provider.MediaStore.Images.Media.RELATIVE_PATH,
                        android.os.Environment.DIRECTORY_PICTURES + "/FlashDrop");
                android.net.Uri uri = getContentResolver().insert(
                        android.provider.MediaStore.Images.Media.EXTERNAL_CONTENT_URI, cv);
                if (uri == null) return null;
                try (java.io.OutputStream os =
                             getContentResolver().openOutputStream(uri)) {
                    bm.compress(mt.contains("png")
                                    ? android.graphics.Bitmap.CompressFormat.PNG
                                    : android.graphics.Bitmap.CompressFormat.JPEG,
                            92, os);
                }
                return uri;
            }
            File dir = new File(android.os.Environment.getExternalStoragePublicDirectory(
                    android.os.Environment.DIRECTORY_PICTURES), "FlashDrop");
            if (!dir.exists()) dir.mkdirs();
            File dst = new File(dir, name);
            try (java.io.FileOutputStream fos = new java.io.FileOutputStream(dst)) {
                bm.compress(android.graphics.Bitmap.CompressFormat.JPEG, 92, fos);
            }
            return Uri.fromFile(dst);
        } catch (Exception e) {
            return null;
        }
    }

    private java.io.InputStream openStream(String src) throws Exception {
        if (src.startsWith("content:"))
            return getContentResolver().openInputStream(Uri.parse(src));
        return new java.io.FileInputStream(src);
    }

    private void loadThumbAsync(Msg m) {
        if (m.tid == null || loadingThumbs.contains(m.tid)) return;
        loadingThumbs.add(m.tid);
        new Thread(() -> {
            // ★ v1.18.18 性能 P0：三级查找 内存 -> 磁盘 -> 原图解码。
            //   旧实现每次进程启动都从原图重新解码（100~300ms/张），
            //   重启后滚动到图片消息整屏卡顿。
            //   磁盘缓存位于 cacheDir/flashdrop-thumbs/<tid>.jpg，
            //   解码成功后写入；重读只要几 ms。
            android.graphics.Bitmap bm = loadThumbFromDisk(m.tid);
            if (bm == null) {
                // 优先级：open(自带授权的 content uri) > src(发送方选中 uri) > 绝对路径
                String src = null;
                if (!TextUtils.isEmpty(m.open)) src = m.open;
                else if (!TextUtils.isEmpty(m.src)) src = m.src;
                else if (!TextUtils.isEmpty(m.path) && new File(m.path).isAbsolute())
                    src = m.path;
                bm = decodeSampled(src, 1024);
                // 兜底：Uri 失效时按文件名从 Download/FlashDrop 重新读取（接收的图片）
                if (bm == null && FdUtil.isImageMime(m.mime)) {
                    bm = decodeSampled(null, 1024, m.file);
                }
                if (bm != null) {
                    int w = bm.getWidth(), h = bm.getHeight();
                    float scale = Math.min(1f, 900f / Math.max(w, h));
                    if (scale < 1f)
                        bm = android.graphics.Bitmap.createScaledBitmap(bm,
                                (int) (w * scale), (int) (h * scale), true);
                    saveThumbToDisk(m.tid, bm);
                }
            }
            if (bm != null) {
                thumbCache.put(m.tid, bm);
            }
            loadingThumbs.remove(m.tid);
            if (bm != null) ui.post(() -> adapter.notifyDataSetChanged());
        }).start();
    }

    /** 磁盘缩略图目录：cacheDir/flashdrop-thumbs/（懒创建） */
    private File thumbDiskDir() {
        File d = new File(new File(FdUtil.cacheDir(this).getParentFile(),
                "flashdrop-thumbs"), "");
        if (!d.exists()) d.mkdirs();
        return d;
    }

    private android.graphics.Bitmap loadThumbFromDisk(String tid) {
        try {
            File f = new File(thumbDiskDir(), tid + ".jpg");
            if (!f.isFile()) return null;
            android.graphics.BitmapFactory.Options o =
                    new android.graphics.BitmapFactory.Options();
            o.inPreferredConfig = android.graphics.Bitmap.Config.RGB_565;
            android.graphics.Bitmap bm =
                    android.graphics.BitmapFactory.decodeFile(f.getAbsolutePath(), o);
            if (bm == null) {
                // 损坏缓存：删掉走原图解码
                f.delete();
            }
            return bm;
        } catch (Throwable t) {
            return null;
        }
    }

    private void saveThumbToDisk(String tid, android.graphics.Bitmap bm) {
        try {
            File d = thumbDiskDir();
            File f = new File(d, tid + ".jpg");
            File tmp = new File(f.getAbsolutePath() + ".tmp");
            try (java.io.FileOutputStream fos = new java.io.FileOutputStream(tmp)) {
                bm.compress(android.graphics.Bitmap.CompressFormat.JPEG, 82, fos);
                fos.flush();
                fos.getFD().sync();
            }
            if (!tmp.renameTo(f)) {
                if (f.exists() && !f.delete()) return;
                tmp.renameTo(f);
            }
            // 容量治理：超过 500 个就整体清空（缩略图可随时由原图重建，
            // 无需精细 LRU —— 简单粗暴但可靠）
            File[] fs = d.listFiles();
            if (fs != null && fs.length > 500) {
                for (File x : fs) {
                    if (x.getName().endsWith(".jpg")) x.delete();
                }
            }
        } catch (Throwable ignored) {
        }
    }

    /** 解码采样位图：src 为路径/uri 字符串；为 null 时用 name 从 MediaStore 兜底读取 */
    private android.graphics.Bitmap decodeSampled(String src, int maxSize) {
        return decodeSampled(src, maxSize, null);
    }

    private android.graphics.Bitmap decodeSampled(String src, int maxSize, String fallbackName) {
        try {
            java.io.InputStream is;
            if (src != null) {
                is = openStream(src);
            } else if (fallbackName != null) {
                is = FdUtil.openSavedStream(this, fallbackName);
            } else {
                return null;
            }
            if (is == null) return null;
            android.graphics.BitmapFactory.Options o = new android.graphics.BitmapFactory.Options();
            o.inJustDecodeBounds = true;
            android.graphics.BitmapFactory.decodeStream(is, null, o);
            is.close();
            int sample = 1;
            while (o.outWidth / sample > maxSize || o.outHeight / sample > maxSize)
                sample *= 2;
            android.graphics.BitmapFactory.Options o2 = new android.graphics.BitmapFactory.Options();
            o2.inSampleSize = sample;
            if (src != null) {
                is = openStream(src);
            } else if (fallbackName != null) {
                is = FdUtil.openSavedStream(this, fallbackName);
            } else {
                return null;
            }
            if (is == null) return null;
            android.graphics.Bitmap bm = android.graphics.BitmapFactory.decodeStream(is, null, o2);
            is.close();
            return bm;
        } catch (Exception e) {
            return null;
        }
    }

    /** 链接点击菜单：打开 / 复制（微信风格列表） */
    private void showLinkMenu(String url) {
        FdDialog.list(this, FdUtil.shortUrl(url, 48), null,
                java.util.Arrays.asList("打开链接", "复制链接"), w -> {
                    if (w == 0) {
                        try {
                            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
                        } catch (Exception e) {
                            toast("没有可打开链接的应用");
                        }
                    } else {
                        ClipboardManager cm = getSystemService(ClipboardManager.class);
                        cm.setPrimaryClip(ClipData.newPlainText("url", url));
                        toast("链接已复制");
                    }
                });
    }

    /** 取消待发送：从队列移除并刷新显示 */
    private void cancelPendingMsg(Msg m) {
        try {
            int idx = Integer.parseInt(m.tid.substring("pending#".length()));
            List<FlashApp.PendingSend> ps = FlashApp.get().pendingSends;
            if (idx >= 0 && idx < ps.size()) {
                ps.remove(idx);
                FlashApp.get().savePendingSends();
            }
        } catch (Exception ignored) {}
        rebuildPendingMsgs();
        refreshPendingBtn();
        toast("已取消待发送");
    }

    // ================= 异步待发送管理窗口（v1.9.0） =================

    /**
     * v1.13.0：待发送不再有独立的按钮入口 —— 顶栏按钮保持隐藏，
     * 待发送内容以 pending 状态直接显示在消息气泡里，设备上线自动投递。
     * 保留此方法是为了让原有的调用点（多处）无需改动。
     */
    private void refreshPendingBtn() {
        // ★ v1.18.18：按钮已复用为「搜索」入口，保持常显
        if (btnPending == null) return;
        btnPending.setVisibility(View.VISIBLE);
    }

    private String pendingTargetDesc(FlashApp.PendingSend p) {
        if (p.broadcast || p.targets.isEmpty()) return "全部设备";
        StringBuilder sb = new StringBuilder();
        for (String t : p.targets) {
            JSONObject pr = peerMap.get(t);
            String n = pr != null ? pr.optString("name", "") : "";
            if (n.isEmpty()) n = (t == null || t.isEmpty()) ? "" : t.substring(0, Math.min(8, t.length()));
            if (n.isEmpty()) continue;
            if (sb.length() > 0) sb.append("、");
            sb.append(n);
        }
        return sb.length() == 0 ? "全部设备" : sb.toString();
    }

    /** 立即补发某条待发内容；不在线则保留在队列 */
    private void pendingSendNow(int idx) {
        List<FlashApp.PendingSend> ps = FlashApp.get().pendingSends;
        if (idx < 0 || idx >= ps.size()) return;
        FlashApp.PendingSend p = ps.get(idx);
        List<String> online = FlashApp.get().node().onlinePeerIds();
        if (online.isEmpty()) {
            toast("当前没有在线设备，仍保留在待发送");
            return;
        }
        List<String> targets = FlashApp.get().resolveTargets(p, online);
        if (targets.isEmpty()) {
            toast("目标设备仍不在线");
            return;
        }
        if (p.isText()) {
            FlashApp.get().node().sendText(targets, p.text);
            Msg m = new Msg();
            m.kind = "text"; m.dir = "out"; m.text = p.text;
            m.peerName = "我"; m.state = "sending"; m.ts = FdUtil.nowMs();
            m.targets = new ArrayList<>(targets);
            m.peerId = targets.get(0);
            synchronized (msgs) { msgs.add(m); }
            indexMsg(m);
            persist(m);
        } else {
            FlashApp.get().node().sendFiles(targets, p.uris);
        }
        ps.remove(idx);
        FlashApp.get().savePendingSends();
        rebuildPendingMsgs();
        refreshPendingBtn();
        toast("已发送");
    }

    private void pendingDelete(int idx) {
        List<FlashApp.PendingSend> ps = FlashApp.get().pendingSends;
        if (idx < 0 || idx >= ps.size()) return;
        ps.remove(idx);
        FlashApp.get().savePendingSends();
        rebuildPendingMsgs();
        refreshPendingBtn();
        toast("已删除该待发送内容");
    }

    /** 待发送管理窗口：查看 / 立即发送 / 删除 / 清空 */
    /**
     * ★ v1.18.18：聊天记录搜索（跨设备，搜文本正文与文件名）。
     *
     * 结果是**只读列表**，点击跳转到对应设备会话。
     * 不做消息内定位 —— 搜索命中的 msg 是从磁盘反序列化的新对象，
     * 与内存气泡列表的 Msg 实例身份不同，无法直接复用渲染管线。
     */
    /**
     * ★ v1.18.23：🔍搜索 按钮的**统一入口**（三种语义合一，避免歧义）。
     *   · 设备态：点击 → 本行原地切换为搜索态（搜索框 / 搜全局 / 🔍搜索 三组件）。
     *   · 搜索态 + 输入框有关键词：点击 → 搜**当前设备**（runSearch(false)）。
     *   · 搜索态 + 输入框为空：点击 → 收起还原为设备态（"再次点击变回原样"）。
     */
    private void onSearchClick() {
        if (!searchMode) {
            toggleSearchBar();          // 设备态 → 进入搜索态
            return;
        }
        String kw = searchInput.getText() == null ? ""
                : searchInput.getText().toString().trim();
        if (kw.isEmpty()) {
            toggleSearchBar();          // 空关键词 → 收起还原
            return;
        }
        runSearch(false);               // 有关键词 → 搜当前设备
    }

    /**
     * ★ v1.18.25：设备态 ⇄ 搜索态 **原地形变**（替代旧版整块显隐切换）。
     *
     * 旧实现为什么跳：两种模式的模块大小不一样就整行重排 ——
     *   · 搜索框 34dp vs 其它按钮 32dp → 行高差 2dp，切换时整行忽高忽低；
     *   · 「删除」与「搜全局」是两个独立按钮，宽窄/位置都不同，显隐即重排；
     *   · 在线数、Spinner 的显隐同样触发整行重新分配宽度。
     * 用户实测就是"上半部分切换时会由于模块大小不一样跳动"。
     *
     * 现在按四根锚点重做（与 activity_main.xml 的 sel_bar 注释一一对应）：
     *   · 行高固定 41dp、子控件统一 32dp → 不高低跳动；
     *   · Spinner 与搜索框共用 weight=1 的 FrameLayout 槽位 → 显隐不重排行；
     *   · 「删除」按钮本身形变为「搜全局」（宽度向左延长 + 字色渐变 + 过半换字）；
     *   · 🔍搜索 是行末锚定子控件，全程不参与形变 → 位置不跳动。
     *
     * 动画（进入 240ms 减速 / 退出 200ms 加速；尊重系统动画时长与应用内动效开关）：
     *   设备选择框向右推进并淡出，搜索框自左滑入并淡入，
     *   在线数坍缩为 0 宽并淡出，「删除」边向左延长边换字换色变成「搜全局」。
     */
    private void toggleSearchBar() {
        boolean enter = !searchMode;
        searchMode = enter;
        // 先摘旧动画回调再 cancel：否则 cancel 会触发上一段动画的收尾，
        // 把行推到旧目标态（快速连点时会看到行"弹回去"）。
        boolean wasAnimating = searchAnim != null;
        if (searchAnim != null) {
            searchAnim.removeAllListeners();
            searchAnim.cancel();
            searchAnim = null;
        }

        // 参与形变的视图先全部设为可见：Spinner 与搜索框在同槽位内叠放
        // （显隐不影响行布局），在线数保持原宽只做淡出，删除按钮宽度由动画驱动，
        // 所以"先可见再形变"不会引起跳动。
        targetSpinner.setVisibility(View.VISIBLE);
        searchInput.setVisibility(View.VISIBLE);
        onlineLabel.setVisibility(View.VISIBLE);
        ensureMorphWidths();
        if (!wasAnimating) {
            // 静止态：把"起点"宽度换成实测值 —— 形变从哪出发必须精确，
            // 估算值只用于"到哪"（差 1px 也看不出来）。
            // 动画中途再点不覆盖缓存，否则会把中间宽度写成端点，越点越歪。
            if (enter) {
                if (btnDelete.getWidth() > 0) btnDelW = btnDelete.getWidth();
            } else if (btnDelete.getWidth() > 0) {
                btnGlbW = btnDelete.getWidth();
            }
        }

        android.view.inputmethod.InputMethodManager imm =
                (android.view.inputmethod.InputMethodManager)
                        getSystemService(INPUT_METHOD_SERVICE);
        if (enter) {
            // hint 跟随当前视图：本设备搜本设备，全部设备视图搜全部
            searchInput.setHint(ALL_ID.equals(viewPeerId)
                    ? "搜索全部设备" : "搜索：" + safeNameOf(viewPeerId));
            searchInput.setText("");
            // ★ v1.18.26：焦点与软键盘**推迟到形变结束后**再要
            //   （finishSearchToggle 里）。边动画边弹键盘会让整个窗口 resize 重排，
            //   动画每帧都在跟键盘抢布局 —— 这是"卡顿"的主因之一。
        } else {
            hideSearchResults();
            searchInput.setText("");
            if (imm != null)
                imm.hideSoftInputFromWindow(searchInput.getWindowToken(), 0);
        }

        final float from = searchF;
        final float to = enter ? 1f : 0f;
        if (!FdAnim.on(this) || Math.abs(to - from) < 0.01f) {
            // 用户关了动效（或系统动画时长=0）/ 已在对端态 → 瞬时到位
            applySearchF(to);
            finishSearchToggle();
            return;
        }
        searchAnim = android.animation.ValueAnimator.ofFloat(from, to);
        // 与 FdAnim 的动效语言对齐：进入 220ms 减速、退出 180ms 加速
        searchAnim.setDuration(enter ? FdAnim.DURATION_ENTER
                : FdAnim.DURATION_EXIT);
        searchAnim.setInterpolator(
                enter ? FdAnim.CURVE_DECELERATE : FdAnim.CURVE_ACCELERATE);
        searchAnim.addUpdateListener(
                a -> applySearchF((Float) a.getAnimatedValue()));
        searchAnim.addListener(new android.animation.AnimatorListenerAdapter() {
            @Override
            public void onAnimationEnd(android.animation.Animator a) {
                finishSearchToggle();
            }
        });
        searchAnim.start();
    }

    /**
     * ★ v1.18.25：按进度 f（0=设备态，1=搜索态）驱动 sel_bar 的原地形变。
     * ★ v1.18.26：重排时序，消除「换行→两排→一排」与卡顿 —— 见下方三段注释。
     *
     * 时序（全部是 f 的纯函数 → 进/退互为精确逆放）：
     *   · 左槽：设备选择框向右推进+淡出，搜索框自左滑入+淡入（同槽位叠放，不重排）；
     *   · 在线数：**只淡出，不做宽度动画**（宽度由槽位吸收）；
     *   · 「删除」→「搜全局」：宽度在前半段就长到位 → 文字在最淡时交叉换字 →
     *     后半段淡入，字色也在文字最淡时过渡。
     *   · 🔍搜索 是行末锚定子控件，不在这里出现 → 全程不跳动。
     */
    private void applySearchF(float f) {
        searchF = f;
        final float slide = dp(24);

        // 左槽（FrameLayout 内叠放）：设备选择框右推淡出 / 搜索框左滑淡入
        targetSpinner.setAlpha(1f - f);
        targetSpinner.setTranslationX(f * slide);
        searchInput.setAlpha(f);
        searchInput.setTranslationX(-(1f - f) * slide);

        // 在线数：★ v1.18.26 —— 只淡出，不再压宽度。
        // 旧版同时做宽度坍缩，"在线 3" 在宽度不足时被 ellipsize 成 "在线…"、"在…"，
        // 动画中途文字抽搐（用户实测"非常不自然"）。数学上这一步根本不需要：
        // 槽位是 weight=1，删除按钮变宽时槽位自己会让出空间，按钮左缘照样向左延长；
        // 且在线数保持原宽时，它显示/隐藏都不会挪动右侧任何控件（宽度变化被槽位吸收）。
        onlineLabel.setAlpha(1f - Math.min(1f, f / 0.35f));

        // 删除 → 搜全局
        ensureMorphWidths();
        // ① 宽度：在前半段（f=0→SWAP_F）就长到位。
        //    旧版宽度按整个时长线性增长，可文字在 f=0.5 就换成 3 个字的「搜全局」——
        //    那时宽度只长了一半，字放不下就**折成两行**（按钮撑高、整行抖），
        //    正是用户说的"从一排过度到两排再过度到一排"。
        float wf = Math.min(1f, f / SWAP_F);
        setChildWidth(btnDelete,
                Math.round(btnDelW + (btnGlbW - btnDelW) * wf));
        // ② 字色：在文字最淡的时候过渡（f=0.3→0.7），看不出跳变
        float cf = Math.max(0f, Math.min(1f, (f - 0.3f) / 0.4f));
        int cFrom = theme != null ? theme.red : 0xFFEF4444;
        int cTo = theme != null ? theme.text : 0xFFE5E7EB;
        int col = (Integer) new android.animation.ArgbEvaluator()
                .evaluate(cf, cFrom, cTo);
        // ③ 文字：f=0/1 全显、f=SWAP_F 全隐 —— 在"看不见"的那一瞬换字，
        //    变成标准的交叉淡入淡出，而不是「删除」硬跳成「搜全局」
        float ta = Math.min(1f, Math.abs(f - SWAP_F) / SWAP_F);
        btnDelete.setTextColor((col & 0x00FFFFFF) | ((int) (255f * ta) << 24));
        boolean global = f >= SWAP_F;
        if (global != morphIsGlobal) {
            morphIsGlobal = global;
            btnDelete.setText(global ? "搜全局" : "删除");
        }
    }

    /** 形变结束收尾：把退场视图彻底隐藏（不留可聚焦/可点击残区），并还原可复用属性 */
    private void finishSearchToggle() {
        if (searchMode) {
            // 搜索态：设备选择器与在线数退场，中间按钮定格为「搜全局」
            targetSpinner.setVisibility(View.GONE);
            onlineLabel.setVisibility(View.GONE);
            btnDelete.setText("搜全局");
            if (theme != null) btnDelete.setTextColor(theme.text);
            // ★ v1.18.26：形变跑完再要焦点 + 弹键盘。
            //   边动画边弹键盘会让窗口 resize 重排，跟动画抢帧（卡顿主因之一）。
            searchInput.requestFocus();
            android.view.inputmethod.InputMethodManager imm =
                    (android.view.inputmethod.InputMethodManager)
                            getSystemService(INPUT_METHOD_SERVICE);
            if (imm != null)
                imm.showSoftInput(searchInput,
                        android.view.inputmethod.InputMethodManager.SHOW_IMPLICIT);
        } else {
            // 设备态：搜索框退场，一切属性还原
            searchInput.setVisibility(View.GONE);
            searchInput.setTranslationX(0f);
            searchInput.setAlpha(1f);
            targetSpinner.setAlpha(1f);
            targetSpinner.setTranslationX(0f);
            onlineLabel.setAlpha(1f);
            btnDelete.setText("删除");
            if (theme != null) btnDelete.setTextColor(theme.red);
        }
        morphIsGlobal = searchMode;
    }

    /** 惰性计算形变按钮两个身份的宽度（删除 / 搜全局），跑一次即缓存 */
    private void ensureMorphWidths() {
        if (btnDelW == 0 || btnGlbW == 0) {
            btnDelW = textWidthFor(btnDelete, "删除");
            btnGlbW = textWidthFor(btnDelete, "搜全局");
        }
    }

    /** 文本 + 内边距的自然像素宽（宽度形变用，避免靠肉眼猜） */
    private int textWidthFor(TextView tv, String text) {
        android.text.TextPaint tp = new android.text.TextPaint();
        tp.setTextSize(tv.getTextSize());
        tp.setTypeface(tv.getTypeface());
        return tv.getPaddingLeft() + tv.getPaddingRight()
                + (int) Math.ceil(tp.measureText(text == null ? "" : text));
    }

    /** 改子视图宽度（宽度变化才 setLayoutParams，避免每帧无谓重排） */
    private void setChildWidth(View v, int w) {
        ViewGroup.LayoutParams lp = v.getLayoutParams();
        if (lp == null || lp.width == w) return;
        lp.width = w;
        v.setLayoutParams(lp);
    }

    /** 收起搜索结果，回到正常会话列表 */
    private void hideSearchResults() {
        searchResultList.setVisibility(View.GONE);
        searchHits.clear();
    }

    /**
     * ★ v1.18.21：执行搜索（不弹窗，结果直接铺在会话界面内）。
     *
     * @param global true=搜全部设备（「搜全局」）；false=只搜当前设备
     */
    private void runSearch(boolean global) {
        String kw = searchInput.getText() == null ? "" :
                searchInput.getText().toString().trim();
        if (kw.isEmpty()) {
            toast("请输入搜索关键词");
            return;
        }
        final String low = kw.toLowerCase();
        final boolean g = global;
        // 工作线程扫盘（每个设备最多 2000 条，同 v1.18.18）
        new Thread(() -> {
            java.util.LinkedHashSet<String> pids = new java.util.LinkedHashSet<>();
            if (!g && !ALL_ID.equals(viewPeerId)) {
                pids.add(viewPeerId);
            } else {
                try {
                    for (JSONObject p : peerMap.values()) pids.add(p.optString("id"));
                    org.json.JSONArray known = Prefs.get(this).knownPeers();
                    for (int i = 0; i < known.length(); i++) {
                        String id = known.optJSONObject(i) == null ? ""
                                : known.optJSONObject(i).optString("id");
                        // ★ v1.18.31：已删除的设备不参与全局搜索
                        if (!id.isEmpty() && !Prefs.get(this).isBlocked(id)) pids.add(id);
                    }
                } catch (Throwable ignored) {}
            }
            pids.remove(null);
            pids.remove("");
            List<JSONObject> hits = new ArrayList<>();
            int limit = 300;
            try {
                for (String pid : pids) {
                    List<JSONObject> hist = FdUtil.loadHistory(this, pid, 2000);
                    for (int i = hist.size() - 1; i >= 0 && hits.size() < limit; i--) {
                        JSONObject o = hist.get(i);
                        String text = o.optString("text", "");
                        if (TextUtils.isEmpty(text)) text = o.optString("file", "");
                        if (text == null || text.isEmpty()) continue;
                        if (text.toLowerCase().indexOf(low) < 0) continue;
                        // 每条命中都带上设备 id / 时间 / 方向 / 摘要（展示与跳转用）
                        String sn = snippetOf(text, text.toLowerCase().indexOf(low),
                                low.length());
                        String when = TF.format(new java.util.Date(o.optLong("ts")));
                        String who = displayNameOf(pid, peerNameOfId(pid));
                        String dir = "out".equals(o.optString("dir")) ? "我发出" : "对方发来";
                        String kind = "text".equals(o.optString("kind")) ? "💬 " : "📎 ";
                        hits.add(FdProto.obj(
                                "pid", pid, "ts", o.optLong("ts"), "mid",
                                o.optString("mid", ""), "kind", o.optString("kind"),
                                "title", who + " · " + dir + " · " + when,
                                "snippet", kind + sn));
                        if (hits.size() >= limit) break;
                    }
                    if (hits.size() >= limit) break;
                }
            } catch (Throwable ignored) {}
            final int n = hits.size();
            ui.post(() -> {
                if (n == 0) {
                    hideSearchResults();
                    toast("没有找到与「" + kw + "」匹配的记录");
                    return;
                }
                searchHits.clear();
                searchHits.addAll(hits);
                if (searchAdapter == null) {
                    searchAdapter = new android.widget.BaseAdapter() {
                        @Override public int getCount() { return searchHits.size(); }
                        @Override public Object getItem(int p) { return searchHits.get(p); }
                        @Override public long getItemId(int p) { return p; }
                        @Override public View getView(int pos, View cv, ViewGroup p2) {
                            android.widget.LinearLayout row =
                                    new android.widget.LinearLayout(MainActivity.this);
                            row.setOrientation(android.widget.LinearLayout.VERTICAL);
                            row.setPadding(dp(14), dp(10), dp(14), dp(10));
                            row.setGravity(android.view.Gravity.CENTER_VERTICAL);
                            // ★ v1.18.24：搜索结果行**必须有不透明底色**。
                            //   此前 row 完全没设背景（默认透明），而 searchResultList
                            //   是覆盖在聊天区之上的 —— 聊天消息会从行背后透出来，
                            //   文字（尤其浅色主题的近黑 text #1F2328）压在杂乱背景上
                            //   根本看不清，用户实测就是"黑色文字 + 透明背景"。
                            //   行底色用 theme.card（浅色=白 / 深色=#26292F），
                            //   列表底用 theme.bg，形成清晰的卡片层级。
                            row.setBackgroundColor(theme.card);
                            JSONObject h = searchHits.get(pos);
                            android.widget.TextView t1 =
                                    new android.widget.TextView(MainActivity.this);
                            t1.setText(h.optString("title"));
                            t1.setTextColor(theme.text);
                            t1.setTextSize(13);
                            t1.setSingleLine(true);
                            t1.setEllipsize(TextUtils.TruncateAt.END);
                            android.widget.TextView t2 =
                                    new android.widget.TextView(MainActivity.this);
                            t2.setText(h.optString("snippet"));
                            t2.setTextColor(theme.dim);
                            t2.setTextSize(12);
                            t2.setMaxLines(2);
                            t2.setEllipsize(TextUtils.TruncateAt.END);
                            t2.setPadding(0, dp(2), 0, 0);
                            row.addView(t1);
                            row.addView(t2);
                            return row;
                        }
                    };
                    searchResultList.setAdapter(searchAdapter);
                } else {
                    searchAdapter.notifyDataSetChanged();
                }
                searchResultList.setVisibility(View.VISIBLE);
                searchResultList.setSelection(0);
                // ★ v1.18.25：结果淡入（与设备栏形变同一套动效语言）
                FdAnim.fadeIn(searchResultList, FdAnim.DURATION_ENTER);
            });
        }).start();
    }

    /** 命中位置附近的上下文片段（首尾 … 表示截断） */
    private static String snippetOf(String text, int hitIdx, int kwLen) {
        String t = text.replace("\n", " ").replace("\r", " ").trim();
        int a = Math.max(0, hitIdx - 20);
        int b = Math.min(t.length(), hitIdx + kwLen + 20);
        return (a > 0 ? "…" : "") + t.substring(a, b) + (b < t.length() ? "…" : "");
    }

    /** 设备显示名兜底（peerMap 没有时查档案） */
    private String peerNameOfId(String pid) {
        if (pid == null || pid.isEmpty()) return "";
        JSONObject p = peerMap.get(pid);
        if (p != null && !TextUtils.isEmpty(p.optString("name"))) return p.optString("name");
        try {
            org.json.JSONArray known = Prefs.get(this).knownPeers();
            for (int i = 0; i < known.length(); i++) {
                org.json.JSONObject o = known.optJSONObject(i);
                if (o != null && pid.equals(o.optString("id")))
                    return o.optString("name", "");
            }
        } catch (Throwable ignored) {}
        return "";
    }

    /**
     * ★ v1.18.21：在当前视图里定位到指定 mid 的消息（搜索结果点击后）。
     * 找不到（历史被裁剪/删除）就退化为滚到最新一条。
     */
    private void locateMsg(String mid) {
        if (TextUtils.isEmpty(mid)) return;
        ui.postDelayed(() -> {
            if (viewMsgs == null || viewMsgs.isEmpty()) return;
            for (int i = 0; i < viewMsgs.size(); i++) {
                if (mid.equals(viewMsgs.get(i).mid)
                        || mid.equals(viewMsgs.get(i).tid)) {
                    chatList.setSelection(i);
                    return;
                }
            }
            chatList.setSelection(viewMsgs.size() - 1);
        }, 120);
    }

    /** 跳转到某设备的会话（搜索结果点击） */
    private void jumpToPeer(String pid) {
        if (pid == null || pid.isEmpty()) return;
        int sel = spinnerIds.indexOf(pid);
        if (sel < 0) {
            toast("该设备已不在列表中");
            return;
        }
        // 挂起 Spinner 回调后再设置选中（见 suppressSpinnerCb 的抑制约定）
        suppressSpinnerCb = true;
        try {
            targetSpinner.setSelection(sel);
        } finally {
            suppressSpinnerCb = false;
        }
        viewPeerId = pid;
        refreshChat();
    }

    private void showPendingWindow() {
        List<FlashApp.PendingSend> ps =
                new ArrayList<>(FlashApp.get().pendingSends);
        if (ps.isEmpty()) {
            FdDialog.info(this, "待发送",
                    "暂无待发送内容。\n\n在「全部设备」视图发送时若没有在线设备，"
                            + "内容会保存到这里，设备上线后自动发出。",
                    "知道了", null);
            return;
        }
        String[] items = new String[ps.size()];
        for (int i = 0; i < ps.size(); i++) {
            FlashApp.PendingSend p = ps.get(i);
            String kind = p.isText() ? "💬 文本" : "📎 文件";
            String text = p.summary();
            if (text.length() > 40) text = text.substring(0, 40) + "…";
            // ★ v1.18.18：显示"为什么还在队列里"（失败原因 + 重试次数），
            //   否则用户只看到内容一直待发，不知道卡在哪
            StringBuilder extra = new StringBuilder();
            if (p.attempt > 0) extra.append("已重试 ").append(p.attempt).append(" 次");
            if (!TextUtils.isEmpty(p.lastError)) {
                if (extra.length() > 0) extra.append(" · ");
                extra.append("原因：").append(p.lastError);
            }
            items[i] = kind + "　" + text + "\n目标：" + pendingTargetDesc(p)
                    + (extra.length() > 0 ? "\n" + extra : "")
                    + "\n（点击可立即发送或删除）";
        }
        FdDialog.list(this, "待发送（" + ps.size() + "）", null,
                java.util.Arrays.asList(items), this::showPendingItemActions);
    }

    /** 单条待发送的操作菜单：立即发送 / 删除 */
    private void showPendingItemActions(int idx) {
        List<FlashApp.PendingSend> ps = FlashApp.get().pendingSends;
        if (idx < 0 || idx >= ps.size()) return;
        FlashApp.PendingSend p = ps.get(idx);
        String label = p.isText() ? "文本" : "文件";
        FdDialog.list(this, label + " · " + pendingTargetDesc(p), null,
                java.util.Arrays.asList("立即发送", "删除"), which -> {
                    if (which == 0) pendingSendNow(idx);
                    else pendingDelete(idx);
                });
    }

    private void confirmClearPending(int n) {
        FdDialog.danger(this, "清空待发送",
                "确定清空全部 " + n + " 条待发送内容吗？\n清空后不会自动补发。",
                "清空", () -> {
                    FlashApp.get().pendingSends.clear();
                    FlashApp.get().savePendingSends();
                    rebuildPendingMsgs();
                    refreshPendingBtn();
                    toast("已清空待发送队列");
                });
    }

    /** 重发失败/中断的发送消息（原图/原文件仍在时） */
    private void resendMsg(Msg m) {
        List<String> targets = new ArrayList<>();
        if (m.targets != null) {
            for (String t : m.targets) {
                if (FlashApp.get().node().isPeerOnline(t)) targets.add(t);
            }
        }
        if (targets.isEmpty() || TextUtils.isEmpty(m.src)) {
            toast("目标设备不在线");
            return;
        }
        FlashApp.get().node().sendFiles(targets, Collections.singletonList(m.src));
        toast("已重新发送");
    }

    /**
     * ★ v1.14.0：菜单里的「打开」入口（卡片内按钮已移除）。
     * 图片走内置查看器，其它文件交给系统应用。
     */
    /**
     * ★ v1.15.0：单击卡片 / 菜单选「打开」的统一入口。
     *
     * 分流规则（用户要求）：
     *  · 图片 → 内置全屏图片查看器（分享 / 保存）
     *  · 常见文档（txt / word / excel / ppt / pdf）→ 内置文件预览器
     *  · 其它能被系统接管的类型 → 交给系统应用
     *  · 完全不支持的 → 弹 2 秒提示，引导长按用其它应用打开
     */
    private void openFileMsg(Msg m) {
        openOrPreview(m);
    }

    // 说明：uriOf / saveFileToUserDir / copyStream / uniqueDownloadName /
    // downloadNameExists / uniqueNameIn / shareFileMsg / openWithChooser / tryOpen
    // 的具体实现已统一收敛到 FdFileOp（见本文件末尾的薄委托层），此处不再重复实现。

    private void openOrPreview(Msg m) {
        if (m == null) return;
        if (!hasLocalContent(m)) {
            toast("文件尚未接收完成");
            return;
        }
        if (FdUtil.isImageMime(m.mime)) {
            openImageViewer(m);
            return;
        }
        String ext = lowerExt(m.file);
        if (FdPreviewActivity.canPreview(ext)) {
            FdPreviewActivity.start(this, m);
            return;
        }
        if (isApk(m)) {
            installApk(m);
            return;
        }
        // 非内置支持的类型：先试系统应用，失败再给 2 秒提示
        if (!tryOpen(m)) {
            toast2s("暂不支持打开此类文件，可长按卡片选择「其他应用打开」");
        }
    }

    /**
     * ★ v1.15.0：APK 安装。
     *
     * 用户反馈"能打开系统安装程序，但到打开后不执行下一步"。根因是
     * Android 8.0+ 要求安装未知来源应用必须持有 REQUEST_INSTALL_PACKAGES
     * 权限，且**未授权时 PackageInstaller 只会打开一个空白/无动作的界面**，
     * 不会报错也不会继续。所以这里先检查、按需引导去设置页授权，
     * 授权后再重新发起安装。
     */
    private void installApk(Msg m) {
        Uri uri = uriOf(m);
        if (uri == null) { toast("文件不可用"); return; }
        if (Build.VERSION.SDK_INT >= 26) {
            if (!getPackageManager().canRequestPackageInstalls()) {
                FdDialog.show(this, "需要安装权限",
                        "安装应用需要允许「闪传」安装未知应用。\n\n"
                                + "点击「去设置」后打开开关，再回来重试即可。",
                        "去设置", "取消", () -> {
                            try {
                                Intent s = new Intent(
                                        android.provider.Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                                        Uri.parse("package:" + getPackageName()));
                                startActivity(s);
                            } catch (Throwable t) {
                                try {
                                    startActivity(new Intent(
                                            android.provider.Settings.ACTION_SECURITY_SETTINGS));
                                } catch (Throwable ignored) {
                                    toast("请到 设置 → 应用 → 特殊权限 中开启安装权限");
                                }
                            }
                            installApkRetry = uri;
                        }, null, false);
                return;
            }
        }
        doInstallApk(uri);
    }

    /** apk 的精确 MIME。 */
    private static final String MIME_APK = "application/vnd.android.package-archive";

    /**
     * APK 安装：走**逐级放宽**直到系统有候选为止。
     *
     * 演进历史：
     *   v1.16.0 —— 用户反馈"点击安卓安装包会显示无法启动安装程序"。旧版对
     *   `ACTION_VIEW` 硬绑了 `setType("application/vnd.android.package-archive")`，
     *   部分国产 ROM（且文件已在 Download 目录被 MediaStore 接管）没有
     *   与该 MIME 精确匹配的 Activity，于是 resolveActivity 返回 null →
     *   弹"无法启动安装程序"。当时改为「依次试 3 种意图 + 先探测」。
     *
     *   v1.18.1 —— 用户反馈 v1.18.0 又出现"未找到可用的安装程序"（报错来自
     *   本方法末尾的兜底 toast）。核查后 **APK 文件本身无问题**：包名 /
     *   minSdk / targetSdk / 13 项权限 / v2+v3 签名 / 证书 SHA-256 /
     *   zip 结构（41 条目、flag_bits、压缩方法、中央目录偏移）与 v1.17.0
     *   **逐项一致**，且 md5 校验通过、可覆盖安装。本方法自 v1.16.0 起
     *   一字未改 —— 属于**环境漂移**放大了下面两个先天缺陷：
     *
     *     缺陷 ①：第 ①② 级都用 `new Intent(base)` 复制后探测。`base` 若不带
     *     MIME，copy 出来 type 仍为 null，探测语义退化成"有没有应用能打开
     *     这个 content://"，与实际 filter 匹配不一致。
     *
     *     缺陷 ②：`ACTION_INSTALL_PACKAGE` 是 Android 7 之前的老入口，
     *     Android 9+ 起 MIUI / ColorOS / EMUI / OriginOS 多数已**移除对该
     *     action 的声明**，安装器改为只注册 `ACTION_VIEW` + apk MIME。
     *     于是第 ③ 级必然 false。
     *
     * 现在（v1.18.1）的策略 —— 复用 {@link FdFileOp#openWithChooser} 已验证
     * 有效的"逐级放宽"，探测用 `queryIntentActivities` 计数判定：
     *   ① ACTION_VIEW + 精确 apk MIME
     *   ② ACTION_VIEW + 通配 MIME（国产 ROM 的救命稻草 —— 让所有能
     *      "打开文件"的应用进候选，系统安装器必然在内）
     *   ③ ACTION_VIEW 不带 MIME（靠 ContentProvider 的 getType 推断）
     *   ④ ACTION_INSTALL_PACKAGE（老系统兜底，故放最后）
     * 全失败才提示，且提示改为**引导去设置页**而非干巴巴报错。
     */
    private void doInstallApk(Uri uri) {
        final int grant = Intent.FLAG_GRANT_READ_URI_PERMISSION;

        // ① 首选：精确 apk MIME（最贴合系统安装器声明的 filter）
        Intent i1 = new Intent(Intent.ACTION_VIEW)
                .setDataAndType(uri, MIME_APK).addFlags(grant);
        if (tryInstall(i1)) return;

        // ② 次选：通配 MIME。国产 ROM 对第三方 authority 的精确 MIME 匹配
        //    常失败，放开成 */* 后系统安装器一定能进候选列表。
        Intent i2 = new Intent(Intent.ACTION_VIEW)
                .setDataAndType(uri, "*/*").addFlags(grant);
        if (tryInstall(i2)) return;

        // ③ 不带 MIME：交给系统按 scheme 推断（ContentProvider.getType）
        Intent i3 = new Intent(Intent.ACTION_VIEW)
                .setData(uri).addFlags(grant);
        if (tryInstall(i3)) return;

        // ④ 老系统专用入口（Android 9+ 多数 ROM 已移除，故放最后）
        Intent i4 = new Intent(Intent.ACTION_INSTALL_PACKAGE)
                .setData(uri)
                .putExtra(Intent.EXTRA_NOT_UNKNOWN_SOURCE, true)
                .putExtra(Intent.EXTRA_RETURN_RESULT, false)
                .addFlags(grant);
        if (tryInstall(i4)) return;

        // ⑤ 真的一个候选都没有 —— 给可执行的下一步，而不是干巴巴报错
        FdDialog.show(this, "未能启动安装程序",
                "系统里没有找到能安装应用的程序。\n\n"
                        + "请依次检查：\n"
                        + "1. 是否已允许「闪传」安装未知应用\n"
                        + "2. 手机安全中心是否拦截了本次安装\n"
                        + "3. 可长按文件卡片选「用其他应用打开」手动选择安装器",
                "去设置", "取消", () -> {
                    try {
                        startActivity(new Intent(
                                android.provider.Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                                Uri.parse("package:" + getPackageName())));
                    } catch (Throwable t) {
                        try {
                            startActivity(new Intent(
                                    android.provider.Settings.ACTION_SECURITY_SETTINGS));
                        } catch (Throwable ignored) { }
                    }
                }, null, false);
    }

    /**
     * 探测 + 启动。
     *
     * ★ v1.18.1：探测改用 {@code queryIntentActivities} 计数，不再用
     * {@code resolveActivity}。后者在部分 ROM 上对 content:// + 第三方
     * authority 会给出假阴性（明明 chooser 能列出应用却返回 null），
     * 正是"未找到可用的安装程序"误报的主要来源。计数为 0 才算无候选。
     *
     * 另外：候选只有 1 个时直接启动，不套 chooser（少一次无意义的点击）。
     */
    private boolean tryInstall(Intent base) {
        try {
            final PackageManager pm = getPackageManager();
            Intent probe = new Intent(base);
            probe.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            List<ResolveInfo> cands = pm.queryIntentActivities(probe, 0);
            if (cands == null || cands.isEmpty()) return false;

            Intent launch = (cands.size() == 1)
                    ? base
                    : Intent.createChooser(base, "选择安装程序");
            launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                    | Intent.FLAG_GRANT_READ_URI_PERMISSION);
            startActivity(launch);
            return true;
        } catch (Throwable t) {
            return false;
        }
    }

    private boolean isApk(Msg m) {
        String e = lowerExt(m.file);
        if ("apk".equals(e)) return true;
        return m.mime != null && m.mime.contains("android.package-archive");
    }

    private static String lowerExt(String name) {
        if (TextUtils.isEmpty(name)) return "";
        int d = name.lastIndexOf('.');
        if (d < 0 || d == name.length() - 1) return "";
        return name.substring(d + 1).toLowerCase(java.util.Locale.ROOT);
    }

    /**
     * ★ v1.15.0：文件操作的**薄委托层**。
     *
     * 真正的实现在 {@link FdFileOp}，聊天页长按菜单与内置预览器的「⋯」三点菜单
     * 共用同一套逻辑，避免两处分叉（保存路径 / 重名策略 / chooser 文案不一致）。
     * 这里只保留一个 Msg → Uri 的便捷入口。
     */
    private Uri uriOf(Msg m) {
        return FdFileOp.uriOf(this, m);
    }

    /** ★ v1.15.0：「保存」——另存到 Download/FlashDrop/（与预览器共用实现） */
    private void saveFileToUserDir(Msg m) {
        Uri src = uriOf(m);
        if (src == null) { toast("文件不可用"); return; }
        FdFileOp.saveToUserDir(this, src,
                TextUtils.isEmpty(m.file) ? "文件" : m.file, m.mime);
    }

    /** ★ v1.15.0：「分享」——调用系统分享面板发送到其它应用 */
    private void shareFileMsg(Msg m) {
        Uri uri = uriOf(m);
        if (uri == null) { toast("文件不可用"); return; }
        FdFileOp.share(this, uri, m.file, m.mime);
    }

    /** ★ v1.15.0：「更多打开方式 / 其他应用打开」——强制弹应用选择器 */
    private void openWithChooser(Msg m) {
        Uri uri = uriOf(m);
        if (uri == null) { toast("文件不可用"); return; }
        FdFileOp.openWithChooser(this, uri, m.file, m.mime);
    }

    /** 交给系统应用打开。返回是否成功发起。 */
    private boolean tryOpen(Msg m) {
        Uri uri = uriOf(m);
        if (uri == null) { toast("文件不可用"); return false; }
        return FdFileOp.tryOpen(this, uri, m.file, m.mime);
    }
}
