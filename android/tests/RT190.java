import java.lang.reflect.*;
import java.util.*;

/**
 * FlashDrop v1.9.0 异步待发专项测试（纯逻辑，不依赖 Android 运行时）
 *
 * 复刻 FlashApp.resolveTargets / MainActivity 的判定逻辑，验证：
 *   1. 群发语义（broadcast / 无指定目标）→ 发给所有在线设备
 *   2. 定向语义 → 只发给已上线的目标
 *   3. 文本与文件载荷分类
 *   4. 摘要文案生成
 *   5. 与 Windows 端口径一致
 */
public class RT190 {

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

    // ===== 复刻 FlashApp.PendingSend =====
    static class PendingSend {
        final List<String> uris;
        final String text;
        final String type;
        final List<String> targets;
        final boolean broadcast;
        final long ts;
        PendingSend(List<String> u, List<String> t, String text, boolean bc) {
            uris = u == null ? new ArrayList<>() : u;
            targets = t == null ? new ArrayList<>() : t;
            this.text = text;
            this.type = (text != null && !text.isEmpty()) ? "text" : "file";
            this.broadcast = bc;
            this.ts = 1700000000000L;
        }
        boolean isText() { return "text".equals(type); }
        String summary() {
            if (isText()) return text == null ? "" : text;
            StringBuilder sb = new StringBuilder();
            int n = Math.min(3, uris.size());
            for (int i = 0; i < n; i++) {
                String u = uris.get(i);
                if (u == null || u.isEmpty()) continue;
                int k = u.lastIndexOf('/');
                String name = (k >= 0 ? u.substring(k + 1) : u);
                if (name.isEmpty()) continue;
                if (sb.length() > 0) sb.append("、");
                sb.append(name);
            }
            if (sb.length() == 0) return "待发送文件";
            if (uris.size() > 3) sb.append(" 等 ").append(uris.size()).append(" 个文件");
            return sb.toString();
        }
    }

    /** 复刻 FlashApp.resolveTargets */
    static List<String> resolveTargets(PendingSend ps, List<String> online) {
        List<String> out = new ArrayList<>();
        if (ps.broadcast || ps.targets.isEmpty()) {
            out.addAll(online);
        } else {
            for (String t : ps.targets) if (online.contains(t)) out.add(t);
        }
        return out;
    }

    /** 复刻 MainActivity.sendText 的 broadcast 判定 */
    static boolean broadcastOf(List<String> selectedIds) {
        return selectedIds.isEmpty();
    }

    /** 复刻 MainActivity 状态文案分支 */
    static String statusText(boolean isFile, String state, boolean noTargets) {
        if (isFile) {
            if ("pending".equals(state)) return "⏳ 待发送 · 设备上线后自动发出";
            return "";
        }
        if ("pending".equals(state)) {
            return noTargets ? "⏳ 待发送 · 全部设备上线后自动发出"
                             : "⏳ 待发送 · 目标设备上线后自动发出";
        }
        return "";
    }

    public static void main(String[] args) {
        System.out.println("== RT190: v1.9.0 异步待发专项测试 ==");

        // ---------- 1. 群发语义：发给所有在线设备 ----------
        System.out.println("\n[1] 群发语义（broadcast=true）");
        List<String> online3 = Arrays.asList("A", "B", "C");
        PendingSend bcText = new PendingSend(new ArrayList<>(), new ArrayList<>(),
                "大家好", true);
        eq("群发文本 → 3 台全发", resolveTargets(bcText, online3).size(), 3);
        check("群发文本含全部在线设备",
                resolveTargets(bcText, online3).containsAll(online3));

        PendingSend bcFile = new PendingSend(
                Arrays.asList("content://x/a.pdf"), new ArrayList<>(), null, true);
        eq("群发文件 → 3 台全发", resolveTargets(bcFile, online3).size(), 3);
        check("群发文件 isText=false", !bcFile.isText());

        // 关键回归：v1.8.0 只发第一台（online[:1]），v1.9.0 必须全发
        check("群发不是只发第一台（v1.8.0 缺陷已修）",
                resolveTargets(bcFile, online3).size() != 1);

        // ---------- 2. 无 broadcast 但 targets 为空 → 同样按群发 ----------
        System.out.println("\n[2] targets 为空（兼容旧数据）视为群发");
        PendingSend legacy = new PendingSend(
                Arrays.asList("content://x/old.pdf"), new ArrayList<>(), null, false);
        eq("旧格式空 targets → 群发全发", resolveTargets(legacy, online3).size(), 3);
        PendingSend legacyText = new PendingSend(
                new ArrayList<>(), new ArrayList<>(), "旧文本", false);
        eq("旧格式空 targets 文本 → 群发全发",
                resolveTargets(legacyText, online3).size(), 3);

        // ---------- 3. 定向语义 ----------
        System.out.println("\n[3] 定向语义");
        PendingSend dir1 = new PendingSend(new ArrayList<>(),
                Arrays.asList("A"), "只给A", false);
        eq("定向 A 在线 → 发 A", resolveTargets(dir1, online3).toString(), "[A]");

        PendingSend dir2 = new PendingSend(new ArrayList<>(),
                Arrays.asList("D"), "只给D", false);
        eq("定向 D 离线 → 不发", resolveTargets(dir2, online3).size(), 0);

        PendingSend dir3 = new PendingSend(new ArrayList<>(),
                Arrays.asList("A", "D"), "给A和D", false);
        eq("定向 A+D 仅 A 在线 → 只发 A",
                resolveTargets(dir3, online3).toString(), "[A]");

        PendingSend dir4 = new PendingSend(new ArrayList<>(),
                Arrays.asList("D", "E"), "给D和E", false);
        eq("定向全部离线 → 不发（继续保留队列）",
                resolveTargets(dir4, online3).size(), 0);

        // ---------- 4. 无在线设备 ----------
        System.out.println("\n[4] 零在线设备");
        List<String> none = new ArrayList<>();
        eq("群发零在线 → 不发", resolveTargets(bcText, none).size(), 0);
        eq("定向零在线 → 不发", resolveTargets(dir1, none).size(), 0);

        // ---------- 5. 载荷分类 ----------
        System.out.println("\n[5] 载荷分类");
        check("有 text → type=text", bcText.isText());
        check("无 text → type=file", bcFile.isText() == false);
        PendingSend emptyFile = new PendingSend(
                new ArrayList<>(), new ArrayList<>(), null, true);
        check("空 uri + 无 text → 归为 file（向后兼容）", !emptyFile.isText());

        // ---------- 6. 摘要文案 ----------
        System.out.println("\n[6] 摘要文案（与 Windows 端 _entry_text 同口径）");
        eq("单文件摘要", bcFile.summary(), "a.pdf");
        PendingSend multi = new PendingSend(
                Arrays.asList("content://x/1.pdf", "content://x/2.zip"),
                new ArrayList<>(), null, true);
        eq("两个文件全部列出", multi.summary(), "1.pdf、2.zip");
        PendingSend over3 = new PendingSend(
                Arrays.asList("content://x/1.pdf", "content://x/2.zip",
                        "content://x/3.pdf", "content://x/4.txt", "content://x/5.pdf"),
                new ArrayList<>(), null, true);
        eq("超过 3 个折算数量", over3.summary(), "1.pdf、2.zip、3.pdf 等 5 个文件");
        PendingSend noName = new PendingSend(
                new ArrayList<>(), new ArrayList<>(), null, true);
        eq("空路径兜底文案", noName.summary(), "待发送文件");
        eq("文本摘要", bcText.summary(), "大家好");

        // ---------- 7. sendText 的 broadcast 判定 ----------
        System.out.println("\n[7] sendText 群发判定");
        check("选中全部设备（空列表）→ 群发", broadcastOf(new ArrayList<>()));
        check("选中具体设备 → 非群发",
                !broadcastOf(Arrays.asList("A")));
        check("单设备视图 → 定向", !broadcastOf(Arrays.asList("B")));

        // ---------- 8. 状态文案 ----------
        System.out.println("\n[8] 气泡状态文案");
        check("文件 pending 文案",
                statusText(true, "pending", false).contains("待发送"));
        check("文本 pending 群发文案",
                statusText(false, "pending", true).contains("全部设备"));
        check("文本 pending 定向文案",
                statusText(false, "pending", false).contains("目标设备"));
        eq("非 pending 无文案", statusText(false, "ok", false), "");

        // ---------- 9. 与 Windows 端一致性 ----------
        System.out.println("\n[9] 双端口径一致（同一组场景应得出同一结论）");
        String[][] cases = {
                {"bc", "A,B,C", "true", ""},
                {"empty", "A,B,C", "false", ""},
                {"dir_online", "A,B,C", "false", "A"},
                {"dir_offline", "A,B,C", "false", "D"},
                {"dir_mixed", "A,B,C", "false", "A,D"},
                {"dir_none", "A,B,C", "false", "D,E"},
                {"bc_zero", "", "true", ""},
                {"dir_zero", "", "false", "A"},
        };
        for (String[] c : cases) {
            List<String> on = c[1].isEmpty() ? new ArrayList<>()
                    : Arrays.asList(c[1].split(","));
            List<String> tg = c[3].isEmpty() ? new ArrayList<>()
                    : Arrays.asList(c[3].split(","));
            PendingSend p = new PendingSend(
                    Arrays.asList("content://x/f.pdf"), tg, null,
                    Boolean.parseBoolean(c[2]));
            int jy = resolveTargets(p, on).size();          // Java 端
            int win = winResolve(c[2], c[3], c[1]);          // Python 端同样规则
            eq("一致性[" + c[0] + "]", jy, win);
        }

        // ---------- 10. 队列稳定性 ----------
        System.out.println("\n[10] 队列稳定性");
        List<PendingSend> q = new ArrayList<>();
        q.add(bcText);
        q.add(dir2);      // 定向离线，应保留
        q.add(bcFile);
        List<PendingSend> remain = new ArrayList<>();
        int sent = 0;
        for (PendingSend p : q) {
            List<String> t = resolveTargets(p, online3);
            if (t.isEmpty()) remain.add(p);
            else sent++;
        }
        eq("3 条中发出 2 条", sent, 2);
        eq("保留 1 条（定向离线）", remain.size(), 1);
        check("保留的是定向离线那条", remain.get(0) == dir2);
        // 第二轮：新设备上线后应发出
        List<String> online4 = Arrays.asList("A", "B", "C", "D");
        eq("D 上线后剩余条目发出",
                resolveTargets(remain.get(0), online4).size(), 1);

        System.out.println("\n===== RT190 结果：" + pass + "/" + (pass + fail)
                + " 通过，失败 " + fail + " =====");
        if (fail > 0) System.exit(1);
    }

    /** 复刻 Python 端 _flush_pending 的目标解析，保持双端一致 */
    static int winResolve(String broadcast, String targets, String online) {
        List<String> on = online.isEmpty() ? new ArrayList<>()
                : Arrays.asList(online.split(","));
        List<String> tg = targets.isEmpty() ? new ArrayList<>()
                : Arrays.asList(targets.split(","));
        if (Boolean.parseBoolean(broadcast) || tg.isEmpty()) return on.size();
        int n = 0;
        for (String t : tg) if (on.contains(t)) n++;
        return n;
    }
}
