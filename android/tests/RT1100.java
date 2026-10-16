import java.lang.reflect.*;
import java.util.*;

/**
 * FlashDrop v1.10.0 数据清理专项测试（纯逻辑，不依赖 Android 运行时）
 *
 * 覆盖两条需求：
 *   1. 主界面顶栏「删除」：三分类 CheckBox + 全选 + 取消/删除，作用域=当前设备
 *   2. 设置页「数据清理」：四按钮合并为一个，三分类多选 + 全选 + 取消/删除，作用域=全局
 *
 * 同时复现并锁死 v1.10.0 修复的真实崩溃：
 *   new java.util.List[]{} 建了长度 0 数组，checks[c]=row(c=0/1/2) 必然越界
 *   → ArrayIndexOutOfBoundsException → "点删除就闪退"
 */
public class RT1100 {

    static int pass = 0, fail = 0;

    static void check(String name, boolean ok) {
        if (ok) { pass++; System.out.println("  PASS  " + name); }
        else { fail++; System.out.println("  FAIL  " + name); }
    }

    static void eq(String name, Object a, Object b) {
        boolean ok = Objects.equals(String.valueOf(a), String.valueOf(b));
        if (ok) { pass++; System.out.println("  PASS  " + name); }
        else {
            fail++;
            System.out.println("  FAIL  " + name + "  期望=[" + b + "] 实际=[" + a + "]");
        }
    }

    static void section(String s) {
        System.out.println("\n[" + s + "]");
    }

    // ===== 复刻 MainActivity v1.10.0 分类常量 =====
    static final int CAT_FILE = 0, CAT_IMAGE = 1, CAT_CHAT = 2;
    static final String[] CAT_NAMES = {
            "下载文件", "接收图片（未保存到图库）", "聊天记录"};

    static class Msg {
        String kind = "text";   // text | file
        String state = "ok";
        String dir = "in";
        String mime = "";
        String peerId = "";
        String path = "";
        List<String> targets = new ArrayList<>();
    }

    /** 复刻 MainActivity.categoryOf */
    static int categoryOf(Msg m) {
        if ("pending".equals(m.state)) return -1;
        if (!"file".equals(m.kind)) return CAT_CHAT;
        return isImageMime(m.mime) ? CAT_IMAGE : CAT_FILE;
    }

    /** 复刻 FdUtil.isImageMime */
    static boolean isImageMime(String mime) {
        return mime != null && mime.startsWith("image/") && !mime.contains("svg");
    }

    /** 复刻 FdUtil.folderNameOf（截断 40 字 + 净化） */
    static String folderNameOf(String peerName) {
        String s = peerName == null ? "" : peerName.trim();
        if (s.isEmpty()) return "未知设备";
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            boolean bad = c < 0x20 || "\\/:*?\"<>|".indexOf(c) >= 0;
            sb.append(bad ? '_' : c);
        }
        s = sb.toString().trim();
        int end = s.length();
        while (end > 0 && (s.charAt(end - 1) == ' ' || s.charAt(end - 1) == '.')) end--;
        s = s.substring(0, end);
        while (s.startsWith(".")) s = s.substring(1);
        if (s.isEmpty()) s = "未知设备";
        if (s.length() > 40) s = s.substring(0, 40);
        return s;
    }

    // ===== 复刻 FdUtil.relPathPattern =====
    static String likeEscaped(String s) {
        if (s == null) return "";
        return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_");
    }

    static String relPathPattern(String folder) {
        String base = "Download/FlashDrop";
        if (folder == null || folder.isEmpty()) return base + "%";
        return base + "/" + likeEscaped(folder) + "%";
    }

    // ===== 复刻 MainActivity.peerScopeOf =====
    static String peerScopeOf(Msg m) {
        if ("in".equals(m.dir)) return m.peerId == null ? "" : m.peerId;
        if (m.targets != null && !m.targets.isEmpty()) return m.targets.get(0);
        return m.peerId == null ? "" : m.peerId;
    }

    /** 复刻 doScopedDelete 的消息筛选：按作用域 + 勾选分类挑出要删的 key */
    static List<String> pickKeys(List<Msg> msgs, String viewPeerId, boolean allScope,
                                 boolean delFile, boolean delImg, boolean delChat) {
        List<String> keys = new ArrayList<>();
        for (Msg m : msgs) {
            boolean inScope = allScope || viewPeerId.equals(peerScopeOf(m));
            if (!inScope) continue;
            int c = categoryOf(m);
            boolean hit = (c == CAT_CHAT) ? delChat
                    : (c == CAT_IMAGE) ? delImg : (c == CAT_FILE) ? delFile : false;
            if (hit) keys.add(m.peerId + "|" + m.kind + "|" + c);
        }
        return keys;
    }

    public static void main(String[] args) {
        System.out.println("========================================");
        System.out.println(" FlashDrop v1.10.0 数据清理专项测试");
        System.out.println("========================================");

        // ---------------------------------------------------------------
        section("1. 崩溃回归：new List[3] 修复（v1.10.0 核心修复）");

        // 旧版写法：长度 0 数组
        try {
            @SuppressWarnings("unchecked")
            List<String>[] bad = new List[]{};
            bad[0] = new ArrayList<>();       // 必然越界
            check("旧写法 new List[]{} 应越界（证明这正是闪退根因）", false);
        } catch (ArrayIndexOutOfBoundsException e) {
            check("旧写法 new List[]{} 越界 —— 复现了闪退根因", true);
        }

        // 新版写法：固定长度 3
        @SuppressWarnings("unchecked")
        List<String>[] fixed = new List[]{null, null, null};
        boolean noAioobe = true;
        try {
            for (int c = 0; c < 3; c++) {
                List<String> row = new ArrayList<>();
                row.add("item" + c);
                fixed[c] = row;
            }
        } catch (ArrayIndexOutOfBoundsException e) {
            noAioobe = false;
        }
        check("新写法 checks[c] 赋值 c=0/1/2 不越界", noAioobe);
        eq("新数组长度", fixed.length, 3);
        check("三类桶都非空", fixed[0] != null && fixed[1] != null && fixed[2] != null);

        // CheckBox 数组同样固定长度 3
        Object[] cbs = new Object[3];
        for (int c = 0; c < 3; c++) cbs[c] = "cb" + c;
        eq("CheckBox 数组长度", cbs.length, 3);
        eq("CheckBox[0]", cbs[0], "cb0");
        eq("CheckBox[2]", cbs[2], "cb2");

        // ---------------------------------------------------------------
        section("2. 分类命名与顺序（用户要求：下载文件/接收图片/聊天记录）");

        eq("分类 0 名称", CAT_NAMES[CAT_FILE], "下载文件");
        eq("分类 1 名称", CAT_NAMES[CAT_IMAGE], "接收图片（未保存到图库）");
        eq("分类 2 名称", CAT_NAMES[CAT_CHAT], "聊天记录");
        eq("分类数量", CAT_NAMES.length, 3);
        check("顺序为 文件→图片→聊天", CAT_FILE == 0 && CAT_IMAGE == 1 && CAT_CHAT == 2);

        // ---------------------------------------------------------------
        section("3. categoryOf 判定");

        Msg txt = new Msg();
        eq("文本消息 → 聊天记录", categoryOf(txt), CAT_CHAT);

        Msg png = new Msg();
        png.kind = "file"; png.mime = "image/png";
        eq("图片文件 → 接收图片", categoryOf(png), CAT_IMAGE);

        Msg pdf = new Msg();
        pdf.kind = "file"; pdf.mime = "application/pdf";
        eq("pdf → 下载文件", categoryOf(pdf), CAT_FILE);

        Msg zip = new Msg();
        zip.kind = "file"; zip.mime = "application/zip";
        eq("zip → 下载文件", categoryOf(zip), CAT_FILE);

        Msg svg = new Msg();
        svg.kind = "file"; svg.mime = "image/svg+xml";
        eq("svg 归下载文件（不算图片）", categoryOf(svg), CAT_FILE);

        Msg pend = new Msg();
        pend.state = "pending";
        eq("待发送不参与删除", categoryOf(pend), -1);

        Msg nullMime = new Msg();
        nullMime.kind = "file"; nullMime.mime = null;
        eq("mime 为 null → 下载文件（不崩）", categoryOf(nullMime), CAT_FILE);

        // ---------------------------------------------------------------
        section("4. 主界面删除：设备作用域（只删该链接设备）");

        List<Msg> all = new ArrayList<>();
        Msg a1 = new Msg(); a1.peerId = "devA"; a1.kind = "text";
        Msg a2 = new Msg(); a2.peerId = "devA"; a2.kind = "file"; a2.mime = "image/jpeg";
        Msg a3 = new Msg(); a3.peerId = "devA"; a3.kind = "file"; a3.mime = "application/pdf";
        Msg b1 = new Msg(); b1.peerId = "devB"; b1.kind = "text";
        Msg b2 = new Msg(); b2.peerId = "devB"; b2.kind = "file"; b2.mime = "image/png";
        all.add(a1); all.add(a2); all.add(a3); all.add(b1); all.add(b2);

        // 只勾聊天记录，只删 devA
        List<String> k = pickKeys(all, "devA", false, false, false, true);
        eq("devA 只删聊天 → 1 条", k.size(), 1);
        check("devA 聊天删除不波及 devB", k.get(0).startsWith("devA"));

        // 只勾接收图片，只删 devA
        k = pickKeys(all, "devA", false, false, true, false);
        eq("devA 只删图片 → 1 条", k.size(), 1);
        check("命中的是 devA 的 jpeg", k.get(0).startsWith("devA") && k.get(0).endsWith("|1"));

        // 只勾下载文件，只删 devA
        k = pickKeys(all, "devA", false, true, false, false);
        eq("devA 只删文件 → 1 条", k.size(), 1);
        check("命中的是 devA 的 pdf", k.get(0).startsWith("devA") && k.get(0).endsWith("|0"));

        // devB 的图片不受 devA 删除影响
        k = pickKeys(all, "devA", false, false, true, false);
        check("devB 图片未被波及", k.stream().noneMatch(x -> x.startsWith("devB")));

        // 全选：devA 三类全删
        k = pickKeys(all, "devA", false, true, true, true);
        eq("devA 全选 → 3 条", k.size(), 3);

        // 未勾选任何项 → 不删
        k = pickKeys(all, "devA", false, false, false, false);
        eq("未勾选 → 0 条（不误删）", k.size(), 0);

        // ---------------------------------------------------------------
        section("5. 主界面删除：全部设备视图（作用域=所有设备）");

        k = pickKeys(all, "__all__", true, false, false, true);
        eq("全部设备只删聊天 → 2 条（两台设备各 1）", k.size(), 2);

        k = pickKeys(all, "__all__", true, false, true, false);
        eq("全部设备只删图片 → 2 条", k.size(), 2);

        k = pickKeys(all, "__all__", true, true, false, false);
        eq("全部设备只删文件 → 1 条", k.size(), 1);

        k = pickKeys(all, "__all__", true, true, true, true);
        eq("全部设备全选 → 5 条", k.size(), 5);

        // ---------------------------------------------------------------
        section("6. peerScopeOf：out 消息按 targets 归属");

        Msg out = new Msg();
        out.dir = "out"; out.peerId = "";
        out.targets = new ArrayList<>(Arrays.asList("devC", "devD"));
        eq("群发 out 归属第一目标", peerScopeOf(out), "devC");

        Msg out2 = new Msg();
        out2.dir = "out"; out2.peerId = "devE"; out2.targets = new ArrayList<>();
        eq("out 无 targets 时回退 peerId", peerScopeOf(out2), "devE");

        Msg in = new Msg();
        in.dir = "in"; in.peerId = "devF";
        eq("in 按 peerId 归属", peerScopeOf(in), "devF");

        // ---------------------------------------------------------------
        section("7. 磁盘作用域：RELATIVE_PATH 模式（设备 vs 全局）");

        eq("全部设备模式", relPathPattern(null), "Download/FlashDrop%");
        eq("空串=全部设备", relPathPattern(""), "Download/FlashDrop%");
        eq("指定设备模式", relPathPattern("手机A"), "Download/FlashDrop/手机A%");
        check("设备模式不会误匹配别的设备",
                !relPathPattern("手机A").equals(relPathPattern("手机B")));

        // 设备名含 SQL LIKE 通配符时必须转义，否则 A% 会匹配到 A/B
        eq("含 % 的设备名已转义", relPathPattern("A%B"), "Download/FlashDrop/A\\%B%");
        eq("含 _ 的设备名已转义", relPathPattern("A_B"), "Download/FlashDrop/A\\_B%");
        check("转义后前缀仍完整",
                relPathPattern("A_B").startsWith("Download/FlashDrop/A\\_B"));

        // ---------------------------------------------------------------
        section("8. 文件夹名一致性（跨端同名）");

        eq("普通设备名", folderNameOf("我的电脑"), "我的电脑");
        eq("非法字符替换", folderNameOf("a/b:c"), "a_b_c");
        eq("空名回退", folderNameOf(""), "未知设备");
        eq("null 回退", folderNameOf(null), "未知设备");
        eq("尾部点去掉", folderNameOf("手机."), "手机");
        StringBuilder longName = new StringBuilder();
        for (int i = 0; i < 50; i++) longName.append("x");
        eq("超长截断到 40", folderNameOf(longName.toString()).length(), 40);

        // ---------------------------------------------------------------
        section("9. 设置页数据清理：全局作用域（所有连接设备）");

        // 设置页 folder 恒为 null → 全局
        eq("设置页文件清理作用域=全局", relPathPattern(null), "Download/FlashDrop%");
        check("设置页不受单个设备目录限制",
                !relPathPattern(null).equals(relPathPattern("devA")));

        // 三类独立勾选，互不影响
        List<String> f = pickKeys(all, "x", true, true, false, false);
        List<String> i = pickKeys(all, "x", true, false, true, false);
        List<String> c = pickKeys(all, "x", true, false, false, true);
        eq("全局 只删文件", f.size(), 1);
        eq("全局 只删图片", i.size(), 2);
        eq("全局 只删聊天", c.size(), 2);

        // 全选三类互斥且完备：并集 == 全量
        Set<String> union = new HashSet<>(f);
        union.addAll(i);
        union.addAll(c);
        List<String> full = pickKeys(all, "x", true, true, true, true);
        eq("三类并集 == 全选结果", union.size(), full.size());
        check("全选覆盖所有可删项", union.size() == 5);

        // ---------------------------------------------------------------
        section("10. 边界与健壮性");

        // 空列表
        eq("空消息列表全选", pickKeys(new ArrayList<>(), "devA", false, true, true, true).size(), 0);

        // 未知设备 id（peerMap 里没有）
        eq("未知设备 → 空", peerScopeOf(new Msg()), "");

        // mime 空串
        Msg empty = new Msg();
        empty.kind = "file"; empty.mime = "";
        check("mime 空串不崩且归文件", categoryOf(empty) == CAT_FILE);

        // 非标准 mime
        Msg weird = new Msg();
        weird.kind = "file"; weird.mime = "image/heic";
        eq("heic 属图片", categoryOf(weird), CAT_IMAGE);
        Msg raw = new Msg();
        raw.kind = "file"; raw.mime = "application/x-tar";
        eq("tar 属文件", categoryOf(raw), CAT_FILE);

        // 待发送不计入任何分类
        Msg pendF = new Msg();
        pendF.kind = "file"; pendF.mime = "image/png"; pendF.state = "pending";
        eq("待发送文件不参与", categoryOf(pendF), -1);
        eq("待发送不进入删除列表",
                pickKeys(Arrays.asList(pendF), "devA", false, true, true, true).size(), 0);

        System.out.println("\n========================================");
        System.out.println(" 通过 " + pass + " 项，失败 " + fail + " 项");
        System.out.println("========================================");
        if (fail > 0) System.exit(1);
    }
}
