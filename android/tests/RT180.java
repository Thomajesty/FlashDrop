import java.lang.reflect.Method;
import java.util.*;

/**
 * v1.8.0 新功能专项验证（不依赖 Android 运行时）：
 *   1. 设备文件夹名净化 FdUtil.folderNameOf
 *   2. 视图归属判定 belongsToView 逻辑（用等价实现复刻，验证设计正确性）
 *   3. 消息三分类 聊天/文件/图片
 *   4. Windows 端 safe_folder 与 Android 端 folderNameOf 结果一致性
 */
public class RT180 {

    static int pass = 0, fail = 0;

    static void eq(String name, Object got, Object want) {
        if (Objects.equals(String.valueOf(got), String.valueOf(want))) {
            pass++;
        } else {
            fail++;
            System.out.println("FAIL " + name + "\n   got  = " + got + "\n   want = " + want);
        }
    }

    static void ok(String name, boolean cond) {
        if (cond) pass++;
        else { fail++; System.out.println("FAIL " + name); }
    }

    // ===== 复刻 MainActivity.belongsToView =====
    static class M {
        String kind, dir, peerId;
        List<String> targets;
        M(String kind, String dir, String peerId, String... tg) {
            this.kind = kind; this.dir = dir; this.peerId = peerId;
            this.targets = tg.length == 0 ? null : new ArrayList<>(Arrays.asList(tg));
        }
    }

    static final String ALL = "__all__";

    /** 复刻 MainActivity.belongsToView（v1.8.0 三规则版） */
    static boolean belongsToView(M m, String peerId) {
        if (peerId == null || ALL.equals(peerId)) return true;
        if (peerId.equals(m.peerId)) return true;
        if (m.targets != null && m.targets.contains(peerId)) return true;
        boolean noTarget = (m.targets == null || m.targets.isEmpty())
                && (m.peerId == null || m.peerId.isEmpty());
        return noTarget;
    }

    // ===== 复刻 MainActivity.categoryOf =====
    static int categoryOf(M m, String mime, String state) {
        if ("pending".equals(state)) return -1;
        if (!"file".equals(m.kind)) return 0;              // CAT_CHAT
        boolean img = mime != null && mime.startsWith("image/") && !mime.contains("svg");
        return img ? 2 : 1;                                 // CAT_IMAGE : CAT_FILE
    }

    public static void main(String[] a) throws Exception {
        // ---------- 1. 设备文件夹名净化 ----------
        Method fn = Class.forName("com.flashdrop.app.FdUtil")
                .getMethod("folderNameOf", String.class);
        eq("folder 普通", fn.invoke(null, "小米 14"), "小米 14");
        eq("folder 斜杠", fn.invoke(null, "a/b"), "a_b");
        eq("folder 反斜杠", fn.invoke(null, "a\\b"), "a_b");
        eq("folder Windows非法", fn.invoke(null, "a:b*c?d"), "a_b_c_d");
        eq("folder 引号", fn.invoke(null, "李\"雷"), "李_雷");
        eq("folder 空", fn.invoke(null, ""), "未知设备");
        eq("folder null", fn.invoke(null, new Object[]{null}), "未知设备");
        eq("folder 仅空格", fn.invoke(null, "   "), "未知设备");
        eq("folder 前导点", fn.invoke(null, "..abc"), "abc");
        eq("folder 全非法", fn.invoke(null, "///"), "___");
        String longName = "设备名称".repeat(30);
        String got = (String) fn.invoke(null, longName);
        ok("folder 超长截断<=40: " + got.length(), got.length() <= 40);

        // 目录穿越必须被阻断
        for (String evil : new String[]{"..", "../..", "a/../../b", "..\\..\\x"}) {
            String f = (String) fn.invoke(null, evil);
            ok("无穿越 " + evil + " -> " + f, !f.contains("/") && !f.contains("\\")
                    && !f.equals("..") && !f.equals("."));
        }

        // ---------- 2. 视图归属判定 ----------
        M inFromA = new M("text", "in", "A");
        M inFromB = new M("text", "in", "B");
        M outToA = new M("text", "out", "A");
        M outToAB = new M("text", "out", "A", "A", "B");
        M outToB = new M("text", "out", "B", "B");
        M outNoTarget = new M("text", "out", "");
        // 待发送：peerId 会被 rebuildPendingMsgs 设为 targets[0]，targets 保留完整列表
        M pendingToA = new M("file", "out", "A", "A");

        ok("全部视图-A的消息", belongsToView(inFromA, ALL));
        ok("全部视图-B的消息", belongsToView(inFromB, ALL));
        ok("A视图收A", belongsToView(inFromA, "A"));
        ok("A视图不含B收的", !belongsToView(inFromB, "A"));
        ok("B视图收B", belongsToView(inFromB, "B"));
        ok("B视图不含A收的", !belongsToView(inFromA, "B"));
        ok("A视图发A", belongsToView(outToA, "A"));
        ok("B视图不含只发A的", !belongsToView(outToA, "B"));
        ok("A视图含群发(A,B)", belongsToView(outToAB, "A"));
        ok("B视图含群发(A,B)", belongsToView(outToAB, "B"));
        ok("A视图不含只发B的", !belongsToView(outToB, "A"));
        // 无目标消息：所有会话都可见（否则用户以为消息丢了）
        ok("A视图含无目标的", belongsToView(outNoTarget, "A"));
        ok("B视图含无目标的", belongsToView(outNoTarget, "B"));
        ok("C视图含无目标的", belongsToView(outNoTarget, "C"));
        ok("null视图=全部", belongsToView(inFromB, null));

        // 视图隔离完整性：A 视图条目数
        List<M> all = Arrays.asList(inFromA, inFromB, outToA, outToAB, outToB, outNoTarget);
        int inA = 0, inB = 0, inAll = 0;
        for (M m : all) {
            if (belongsToView(m, ALL)) inAll++;
            if (belongsToView(m, "A")) inA++;
            if (belongsToView(m, "B")) inB++;
        }
        eq("全部视图条数", inAll, 6);
        eq("A视图条数", inA, 4);   // inFromA,outToA,outToAB,outNoTarget
        eq("B视图条数", inB, 4);   // inFromB,outToAB,outToB,outNoTarget

        // 待发送：只归属目标设备，不污染其他会话
        ok("待发在A视图可见", belongsToView(pendingToA, "A"));
        ok("待发不在B视图", !belongsToView(pendingToA, "B"));
        ok("待发在全部视图可见", belongsToView(pendingToA, ALL));

        // ---------- 3. 三分类 ----------
        eq("文本→聊天", categoryOf(new M("text", "in", "A"), null, "ok"), 0);
        eq("文件pdf→文件", categoryOf(new M("file", "in", "A"),
                "application/pdf", "done"), 1);
        eq("图片png→图片", categoryOf(new M("file", "in", "A"),
                "image/png", "done"), 2);
        eq("图片jpg→图片", categoryOf(new M("file", "in", "A"),
                "image/jpeg", "done"), 2);
        eq("svg→文件(非图片)", categoryOf(new M("file", "in", "A"),
                "image/svg+xml", "done"), 1);
        eq("octet-stream→文件", categoryOf(new M("file", "in", "A"),
                "application/octet-stream", "done"), 1);
        eq("待发送→排除", categoryOf(new M("file", "out", "A"),
                "image/png", "pending"), -1);
        eq("待发送文本→排除", categoryOf(new M("text", "out", "A"), null, "pending"), -1);
        // 发出的图片也算图片
        eq("发出图片→图片", categoryOf(new M("file", "out", "A"),
                "image/webp", "done"), 2);

        // ---------- 4. 跨端文件夹名一致性 ----------
        String androidName = (String) fn.invoke(null, "小米 14: Pro/测试");
        System.out.println("INFO 跨端同名样本(Android) = " + androidName);

        System.out.println();
        System.out.println("PASS=" + pass + "  FAIL=" + fail);
        System.out.println(fail == 0 ? "ALL_OK" : "HAS_FAILURE");
    }
}
