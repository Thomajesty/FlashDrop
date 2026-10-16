import java.io.*;
import java.util.*;
import java.util.regex.*;

/**
 * v1.18.9 Android 静态审计测试（无设备，纯源码断言）
 *
 * 针对用户反馈的三项：
 *   A. 文字长按选择仍失效 → 改为程序化全选 + 自建菜单
 *   B. 离线消息发送端卡「发送中」 → 补发必须回填真实 mid
 *   C. 设备列表 / 离线聊天 / 全部设备群聊视图
 *
 * 运行：javac RT1189.java && java RT1189 <MainActivity.java 路径>
 */
public class RT1189 {
    static int PASS = 0, FAIL = 0;
    static List<String> FAILS = new ArrayList<>();

    static void check(String name, boolean cond) {
        check(name, cond, "");
    }

    static void check(String name, boolean cond, String detail) {
        if (cond) { PASS++; System.out.println("  [OK] " + name); }
        else { FAIL++; FAILS.add(name + " " + detail);
               System.out.println("  [FAIL] " + name + " " + detail); }
    }

    static String read(String p) throws IOException {
        StringBuilder sb = new StringBuilder();
        try (BufferedReader r = new BufferedReader(
                new InputStreamReader(new FileInputStream(p), "UTF-8"))) {
            String l;
            while ((l = r.readLine()) != null) sb.append(l).append('\n');
        }
        return sb.toString();
    }

    public static void main(String[] args) throws Exception {
        String base = args.length > 0 ? args[0]
                : "../app/src/main/java/com/flashdrop/app";
        String ma = read(base + "/MainActivity.java");
        System.out.println("==================================================");
        System.out.println("v1.18.9 Android 静态审计");
        System.out.println("文件：" + new File(base + "/MainActivity.java").getAbsolutePath());
        System.out.println("行数：" + ma.split("\n").length);
        System.out.println("==================================================");

        // ───── A. 文字长按选择 ─────
        System.out.println("\n=== A 文字长按选择（v1.18.9 根治） ===");
        check("A1 存在 selectAllText 辅助方法",
                ma.contains("private void selectAllText(TextView tv)"));
        check("A2 用 android.text.Selection 设置选区（避开未暴露的 setSelection(int,int)）",
                ma.contains("android.text.Selection.setSelection("));
        // 只看**真实代码**里有没有调用；注释里提到该 API 名不算（那正是解释为何不用它）
        StringBuilder codeOnly = new StringBuilder();
        for (String l : ma.split("\n")) {
            String t = l.trim();
            if (t.startsWith("*") || t.startsWith("//") || t.startsWith("/*")) continue;
            codeOnly.append(l).append('\n');
        }
        check("A3 真实代码里没有 tv.setSelection(0,（仅在注释里被引用）",
                !codeOnly.toString().contains("tv.setSelection(0,"),
                "该方法在本项目 android.jar 中不存在，会编译失败");
        check("A4 正文挂了 OnLongClickListener",
                Pattern.compile("h\\.meta\\.setOnLongClickListener").matcher(ma).find());
        check("A5 长按处理器里调用了 selectAllText",
                Pattern.compile("setOnLongClickListener\\(v -> \\{[\\s\\S]{0,600}?selectAllText\\(\\(TextView\\) v\\)")
                        .matcher(ma).find());
        check("A6 长按处理器里弹出自建菜单 showTextMenu",
                Pattern.compile("setOnLongClickListener\\(v -> \\{[\\s\\S]{0,900}?showTextMenu\\(m, v\\)")
                        .matcher(ma).find());
        check("A7 存在 showTextMenu 方法",
                ma.contains("private void showTextMenu(Msg m, View anchor)"));
        check("A8 文本菜单含 复制/全选/多选/删除",
                ma.contains("new FdMenuIcon.Item(\"复制\"")
                        && ma.contains("new FdMenuIcon.Item(\"全选\"")
                        && ma.contains("new FdMenuIcon.Item(\"多选\"")
                        && ma.contains("new FdMenuIcon.Item(\"删除\""));
        check("A9 onMenuAction 有「全选」分支且调用 selectAllText",
                Pattern.compile("case \"全选\":[\\s\\S]{0,400}?selectAllText\\(tv\\)")
                        .matcher(ma).find());
        check("A10 「复制」优先复制选区、无选区回落全文",
                ma.contains("tv.getSelectionStart()") && ma.contains("tv.getSelectionEnd()"));
        check("A11 抽出统一菜单定位 showMenuAt（避免两份实现漂移）",
                ma.contains("private void showMenuAt(View anchor, View box)"));
        int nShowMenuAt = ma.split("showMenuAt\\(anchor, box\\);", -1).length - 1;
        check("A12 showMsgMenu 与 showTextMenu 都走 showMenuAt（应有 2 处调用）",
                nShowMenuAt >= 2, "实际调用次数=" + nShowMenuAt);
        check("A13 有 _textMenuTv 字段承载选区控件",
                ma.contains("private TextView _textMenuTv;"));
        check("A14 长按有触觉反馈（可感知「有反应」）",
                ma.contains("HapticFeedbackConstants.LONG_PRESS"));

        // ───── B. 补发 mid ─────
        System.out.println("\n=== B 离线消息卡「发送中」（mid 回填） ===");
        check("B1 补发回调不再把 mid 置 null",
                !Pattern.compile("flushPendingSends\\([\\s\\S]{0,700}?m\\.mid\\s*=\\s*null")
                        .matcher(ma).find(),
                "m.mid = null 会让 ack 匹配不到 → 永久 sending");
        check("B2 补发回填了真实 mid",
                Pattern.compile("m\\.mid\\s*=\\s*mid").matcher(ma).find());
        String fa = read(base + "/FlashApp.java");
        check("B3 FlashApp 提供 BiConsumer 双参重载（透出真实 mid）",
                fa.contains("BiConsumer<PendingSend, String>"));

        // ───── C. 设备列表 / 离线聊天 / 全部设备 ─────
        System.out.println("\n=== C 设备列表增强 / 离线聊天 / 全部设备群聊 ===");
        String prefs = read(base + "/Prefs.java");
        String sa = read(base + "/SettingsActivity.java");

        check("C1 设备状态灯：在线绿 / 离线灰",
                ma.contains("theme.green") && ma.contains("0xFF6B7280"),
                "Spinner 设备项的状态点");

        check("C2 known_peers 档案读写已接入",
                prefs.contains("public JSONArray knownPeers()")
                        && ma.contains("Prefs.get(this).rememberPeer("));

        check("C3 rebuildSpinner 会合并离线设备（受 offlineChat 控制）",
                Pattern.compile("rebuildSpinner\\(\\)[\\s\\S]{0,3000}?offlineChat\\(\\)")
                        .matcher(ma).find());

        check("C4 下拉项末尾有删除 ✕ 按钮",
                ma.contains("TAG_DELETE_X") && ma.contains("getDropDownView"));

        check("C5 ✕ 只在「有历史记录」的设备上出现（全部设备不显示）",
                ma.contains("historyFile(MainActivity.this, pid).exists()"));

        check("C6 convertView 复用时会摘掉旧 ✕（不会越点越多）",
                ma.contains("stripDeleteButton"));

        check("C7 删除会话确认弹窗覆盖记录+文件",
                Pattern.compile("confirmDeleteConversation[\\s\\S]{0,900}?clearHistory")
                        .matcher(ma).find()
                        && ma.contains("deleteSavedFiles"));

        check("C8 删除后从 knownPeers 档案摘除",
                ma.contains("forgetPeer(pid)"));

        check("C9 Prefs 有 offlineChat 开关（默认开）",
                prefs.contains("public boolean offlineChat()")
                        && prefs.contains("getBoolean(\"offline_chat\", true)"));

        check("C10 Prefs 有 keepHistory 开关（默认开）",
                prefs.contains("public boolean keepHistory()"));

        check("C11 设置页有「离线聊天」开关行",
                sa.contains("offlineChatSwitch") && sa.contains("离线聊天"));

        check("C12 设置页有「保存聊天」开关行",
                sa.contains("keepHistorySwitch") && sa.contains("保存聊天"));

        check("C13 onSave 持久化两个新开关",
                sa.contains("prefs.setOfflineChat(") && sa.contains("prefs.setKeepHistory("));

        check("C14 persist 尊重 keepHistory（关闭则不写盘）",
                Pattern.compile("private void persist\\(Msg m\\)[\\s\\S]{0,900}?keepHistory\\(\\)")
                        .matcher(ma).find());

        check("C15 Msg 新增 channel 字段（group/p2p）",
                ma.contains("String channel;"));

        check("C16 belongsToView 全部设备走群聊语义",
                Pattern.compile("if \\(isAll\\) \\{[\\s\\S]{0,400}?\"group\"\\.equals\\(m\\.channel\\)")
                        .matcher(ma).find());

        check("C17 群聊消息不进入单设备私聊视图",
                Pattern.compile("if \\(\"group\"\\.equals\\(m\\.channel\\)\\) return false;")
                        .matcher(ma).find());

        check("C18 sendText 按当前视图打频道标记",
                Pattern.compile("sendText\\(\\)[\\s\\S]{0,1800}?m\\.channel = ALL_ID\\.equals\\(viewPeerId\\)")
                        .matcher(ma).find());

        check("C19 待发补发沿用原频道（broadcast → group）",
                ma.contains("ps.broadcast ? \"group\""));

        check("C20 无频道老数据按 targets 数量保守判定",
                Pattern.compile("return n != 1;").matcher(ma).find());

        System.out.println("\n==================================================");
        System.out.printf("v1.18.9 Android 审计：通过 %d 项，失败 %d 项%n", PASS, FAIL);
        if (!FAILS.isEmpty()) {
            System.out.println("失败项：");
            for (String f : FAILS) System.out.println("  - " + f);
        }
        System.out.println("==================================================");
        System.exit(FAIL == 0 ? 0 : 1);
    }
}
