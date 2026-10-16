# -*- coding: utf-8 -*-
"""
FlashDrop v1.10.0 Android 端源码静态校验（不依赖 Android 运行时 / 不需要设备）

为什么需要这一层：
  RT1100 复刻的是逻辑，而 v1.9.0 曾出现过"复刻测试全绿、真机仍崩"的经典问题
  （staticmethod 调用实例方法，纯文本测不到，只有真发文件才触发）。
  所以这里用 ast 式扫描直接检查真实 .java 源码，锁死结构层面的约束。

检查项：
  1. 崩溃回归：MainActivity 不得再有 new java.util.List[]{} 长度 0 数组
  2. 分类常量与命名（下载文件 / 接收图片（未保存到图库）/ 聊天记录）
  3. 主界面删除弹窗结构：CheckBox 固定长度 3、默认不选、全选按钮、取消+删除、二次确认
  4. 设置页：只有一个数据清理按钮，旧四按钮已移除
  5. FdUtil 新接口签名（folder 参数 / imagesOnly 三态 / 统计方法）
  6. 设备作用域 vs 全局作用域调用正确
"""
import os
import re
import sys

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "app", "src", "main", "java", "com", "flashdrop", "app")
MAIN = os.path.join(SRC, "MainActivity.java")
SETT = os.path.join(SRC, "SettingsActivity.java")
FDU = os.path.join(SRC, "FdUtil.java")

_pass = 0
_fail = 0


def check(name, ok, detail=""):
    global _pass, _fail
    if ok:
        _pass += 1
        print("  PASS  " + name)
    else:
        _fail += 1
        print("  FAIL  " + name + ("   " + detail if detail else ""))


def sec(t):
    print("\n[" + t + "]")


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def strip_comments(src):
    """去掉行注释与块注释，避免把"注释里提到坏写法"误判成真实代码。
    这里刻意保留换行以维持行结构（字符串里的 // 不做处理，
    因为本项目源码不含含 // 的字面量）。"""
    out = []
    in_block = False
    for line in src.split("\n"):
        s = line
        if in_block:
            if "*/" in s:
                s = s.split("*/", 1)[1]
                in_block = False
            else:
                continue
        if "/*" in s:
            pre, _, rest = s.partition("/*")
            if "*/" in rest:
                s = pre + rest.split("*/", 1)[1]
            else:
                s = pre
                in_block = True
        # 去掉行注释（// 之后到行尾）
        i = s.find("//")
        if i >= 0:
            s = s[:i]
        out.append(s)
    return "\n".join(out)


def body_of(src, sig):
    """取方法体：从签名行到下一个同缩进方法/类结束（按大括号配平）"""
    i = src.find(sig)
    if i < 0:
        return None
    j = src.find("{", i)
    if j < 0:
        return None
    depth = 0
    k = j
    while k < len(src):
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                return src[j:k + 1]
        k += 1
    return None


def main():
    print("=" * 60)
    print(" FlashDrop v1.10.0 Android 源码静态校验")
    print("=" * 60)

    for p in (MAIN, SETT, FDU):
        if not os.path.exists(p):
            print("源码缺失: " + p)
            sys.exit(2)

    m = read(MAIN)
    s = read(SETT)
    u = read(FDU)
    # 去掉注释后的纯代码（"崩溃根因说明"写在注释里，不算真实代码）
    mc, sc, uc = strip_comments(m), strip_comments(s), strip_comments(u)

    # ---------------- 1. 崩溃回归 ----------------
    sec("1. 崩溃回归：new java.util.List[]{} 长度 0 数组已消除")

    check("MainActivity 不再出现 new java.util.List[]{}", "new java.util.List[]{}" not in mc)
    check("SettingsActivity 不再出现 new java.util.List[]{}", "new java.util.List[]{}" not in sc)
    # 整个 Android 源码目录都不能有（同样忽略注释）
    bad = []
    for fn in os.listdir(SRC):
        if not fn.endswith(".java"):
            continue
        if "new java.util.List[]{}" in strip_comments(read(os.path.join(SRC, fn))):
            bad.append(fn)
    check("全源码目录无长度 0 泛型数组", not bad, str(bad))

    dp = body_of(mc, "private void showDeletePicker()")
    check("showDeletePicker 存在", dp is not None)
    if dp:
        check("showDeletePicker 内用 CheckBox[3] 固定长度数组",
              re.search(r"CheckBox\[\]\s*checks\s*=\s*new\s+CheckBox\[3\]", dp) is not None)
        check("不再按桶声明 List<CheckBox>[]", "List<CheckBox>" not in dp)
        check("三个分类各建一个 CheckBox",
              dp.count("new CheckBox(this)") == 1)   # 在 for 循环里建一次
        check("默认不勾选", "setChecked(false)" in dp)
        check("无内容的分类置灰不可选", "setEnabled(counts[c] > 0)" in dp)
        check("有全选按钮", '"全选"' in dp)
        check("全选可切换为取消全选", '"取消全选"' in dp)
        check("有删除按钮", 'setPositiveButton("删除"' in dp)
        check("有取消按钮", 'setNegativeButton("取消"' in dp)
        check("未勾选时提示而非静默", "请先勾选" in dp)

    # 二次确认在 confirmScopedDelete（弹窗回调调它）
    cs = body_of(mc, "private void confirmScopedDelete(")
    check("confirmScopedDelete 存在", cs is not None)
    if cs:
        check("删除前有二次确认弹窗", "再次确认" in cs)
        check("二次确认含删除与取消", 'setPositiveButton("删除"' in cs
              and 'setNegativeButton("取消"' in cs)
        check("二次确认逐项列出所选类型",
              '"· 下载文件' in cs and '"· 接收图片' in cs and '"· 聊天记录' in cs)
        check("二次确认调用真正执行", "doScopedDelete(" in cs)

    # ---------------- 2. 分类常量 ----------------
    sec("2. 分类常量与命名（用户口径）")

    check("MainActivity CAT_FILE = 0", re.search(r"CAT_FILE\s*=\s*0", m) is not None)
    check("MainActivity CAT_IMAGE = 1", re.search(r"CAT_IMAGE\s*=\s*1", m) is not None)
    check("MainActivity CAT_CHAT = 2", re.search(r"CAT_CHAT\s*=\s*2", m) is not None)
    check("MainActivity 含『下载文件』", '"下载文件"' in mc)
    check("MainActivity 含『接收图片（未保存到图库）』",
          '"接收图片（未保存到图库）"' in mc)
    check("MainActivity 含『聊天记录』", '"聊天记录"' in mc)
    # 旧的分类名不能残留
    check("旧分类名『聊天』单字已废弃", '"聊天"' not in mc)
    check("旧分类名数组 {聊天,文件,图片} 已移除",
          '{"聊天", "文件", "图片"}' not in mc)

    check("SettingsActivity 分类常量与主界面一致",
          re.search(r"CAT_FILE\s*=\s*0", sc) is not None
          and re.search(r"CAT_IMAGE\s*=\s*1", sc) is not None
          and re.search(r"CAT_CHAT\s*=\s*2", sc) is not None)
    check("SettingsActivity 含三类名称",
          '"下载文件"' in sc and '"接收图片（未保存到图库）"' in sc and '"聊天记录"' in sc)
    check("两端分类名称完全一致",
          re.findall(r'"(下载文件|接收图片（未保存到图库）|聊天记录)"', mc)[:3]
          == re.findall(r'"(下载文件|接收图片（未保存到图库）|聊天记录)"', sc)[:3])

    # ---------------- 3. 设置页合并 ----------------
    sec("3. 设置页：四按钮合并为一个数据清理")

    check("已移除 onClearHistory 回调", "onClearHistory" not in sc)
    check("已移除 onDeleteDownloads 回调", "onDeleteDownloads" not in sc)
    check("已移除旧本地删除实现 deleteDownloadFiles", "deleteDownloadFiles" not in sc)
    check("不存在『清空聊天记录』按钮", 'setText("清空聊天记录")' not in sc)
    check("不存在『删除下载文件』按钮", 'setText("删除下载文件")' not in sc)
    check("不存在『删除下载图片』按钮", 'setText("删除下载图片")' not in sc)

    check("有『数据清理』按钮", 'setText("数据清理' in sc)
    cd = body_of(sc, "private void onDataClean()")
    check("onDataClean 存在", cd is not None)
    if cd:
        check("数据清理用 CheckBox[3]",
              re.search(r"CheckBox\[\]\s*checks\s*=\s*new\s+android\.widget\.CheckBox\[3\]", cd)
              is not None)
        check("数据清理默认不勾选", "setChecked(false)" in cd)
        check("数据清理有全选按钮", '"全选"' in cd)
        check("数据清理有删除按钮", 'setPositiveButton("删除"' in cd)
        check("数据清理有取消按钮", 'setNegativeButton("取消"' in cd)
        check("数据清理有二次确认", "再次确认" in cd)
        check("数据清理空数据时给提示", "暂无聊天记录" in cd)
        check("数据清理实时统计三类数量", "countSavedFiles" in cd and "countHistory" in cd)
        check("数据清理作用域为全局（folder 传 null）",
              "deleteSavedFiles(this, null," in sc)

    rc = body_of(sc, "private void runDataClean(")
    check("runDataClean 存在", rc is not None)
    if rc:
        check("runDataClean 聊天记录走全局清空", "clearAllHistory" in rc)
        check("runDataClean 分别删非图片与图片",
              "Boolean.FALSE" in rc and "Boolean.TRUE" in rc)
        check("runDataClean 走后台线程不卡界面", "new Thread" in rc)
        check("runDataClean 结果回到 UI 线程提示", "runOnUiThread" in rc)
        check("runDataClean 处理 Android 11+ 系统确认",
              "createDeleteRequest" in rc)
        check("runDataClean 通知主界面刷新聊天", "historyCleared = true" in rc)

    # v1.10.1：原「打开保存目录」因 FdFileProvider 无目录浏览能力 + 国产 ROM
    # 不实现 DocumentsContract，点了必然弹回，已按用户授权改为「查看保存位置」。
    # 这里改为断言"仍是可点击的文字入口"，并顺带守住不再出现 Intent 跳转。
    check("保存位置入口仍为可点击文字入口",
          "openDir.setClickable(true)" in sc and "openDir.setText" in sc)
    check("v1.10.1：已移除 openSaveFolder 的 Intent 跳转",
          "openSaveFolder" not in sc)

    # ---------------- 4. 设备作用域 ----------------
    sec("4. 主界面删除作用域 = 当前设备")

    ds = body_of(mc, "private void doScopedDelete(")
    check("doScopedDelete 存在", ds is not None)
    if ds:
        check("用 viewPeerId 判定设备作用域", "viewPeerId.equals(peerScopeOf(m))" in ds)
        check("全部设备视图走 allScope 分支", "allScope ||" in ds)
        check("聊天记录按设备清（clearHistory 单设备）",
              "FdUtil.clearHistory(MainActivity.this, viewPeerId)" in ds)
        check("聊天记录全局清（clearAllHistory）", "clearAllHistory(MainActivity.this)" in ds)
        check("文件删除传设备 folder", "deleteSavedFiles(\n                    MainActivity.this, folder," in ds
              or "MainActivity.this, folder," in ds)
        check("非图片与图片分开删",
              "Boolean.FALSE" in ds and "Boolean.TRUE" in ds)
        # v1.10.1：历史条目清理已收拢进 purgeMsgs()，doScopedDelete 只负责调度，
        # 因此这里改为断言「调度到了 purgeMsgs」而不是直接出现 deleteByIdentities。
        check("删除后同步清历史条目", "purgeMsgs(" in ds)
        check("删除在后台线程", "new Thread" in ds)

    ps = body_of(mc, "private String peerScopeOf(Msg m)")
    check("peerScopeOf 存在", ps is not None)
    if ps:
        check("in 消息按 peerId 归属", '"in".equals(m.dir)' in ps)
        check("out 消息按 targets 归属", "m.targets" in ps)

    check("showDeletePicker 按设备名算 folder",
          "FdUtil.folderNameOf(scopeName)" in mc)
    check("全部设备视图 folder 为 null（全局）", "final String folder = allScope ? null" in mc)

    # ---------------- 5. FdUtil 接口 ----------------
    sec("5. FdUtil 新接口与统计")

    check("deleteSavedFiles 新签名含 folder 参数",
          re.search(r"int\[\]\s*deleteSavedFiles\(Context ctx, String folder, Boolean imagesOnly", uc)
          is not None)
    check("旧签名（无 folder）已移除",
          "deleteSavedFiles(Context ctx, Boolean imagesOnly" not in uc)
    check("有 countSavedFiles 统计", "public static int[] countSavedFiles(Context ctx, String folder)" in uc)
    check("有 countHistory 全局统计", "public static int countHistory(Context ctx, boolean chatsOnly)" in uc)
    check("有 countHistoryOf 单设备统计",
          "public static int countHistoryOf(Context ctx, String peerId, boolean chatsOnly)" in uc)
    check("relPathPattern 支持全部设备（null/空）", "if (folder == null || folder.isEmpty())" in uc)
    check("LIKE 通配符已转义（设备名含 _ % 不会误匹配）",
          "likeEscaped" in uc and 'replace("_", "\\\\_")' in uc)
    check("图片判定与 isImageMime 同口径（svg 不算图片）",
          re.search(r"isImageMime\(mime\)\s*!=\s*imagesOnly", uc) is not None)
    # isImageMime 的定义本身当然含 startsWith("image/")，这里要确保
    # 删除逻辑里没有再各自内联一个"只判 image/ 不排除 svg"的口径
    del_body = body_of(uc, "public static int[] deleteSavedFiles(Context ctx, String folder")
    check("删除逻辑未内联 startsWith(\"image/\")",
          del_body is not None and 'startsWith("image/")' not in del_body)
    check("空设备目录会被清掉", "removeIfEmpty" in uc)
    check("API24-28 分支用 folderRoot 定位", "folderRoot(folder)" in uc)

    # ---------------- 6. 调用点一致性 ----------------
    sec("6. 调用点全部走新接口")

    callers = 0
    for fn in ("MainActivity.java", "SettingsActivity.java"):
        txt = read(os.path.join(SRC, fn))
        for mm in re.finditer(r"FdUtil\.deleteSavedFiles\((.*?)\)\[0\]", txt, re.S):
            callers += 1
            args = mm.group(1)
            check(fn + " 调用含 folder 参数",
                  re.search(r"this,\s*(null|folder)", args) is not None,
                  " ".join(args.split())[:70])
        for mm in re.finditer(r"FdUtil\.deleteSavedFiles\((.*?)\);", txt, re.S):
            if "[0]" in mm.group(1):
                continue
            callers += 1
            args = mm.group(1)
            check(fn + " 调用含 folder 参数（带 needConfirm）",
                  re.search(r"this,\s*(null|folder)", args) is not None,
                  " ".join(args.split())[:70])
    check("共 4 处删除调用（主界面 2 + 设置 2）", callers == 4, "实际 " + str(callers))

    # ---------------- 7. 保留能力 ----------------
    sec("7. 既有能力未被破坏")

    check("v1.9.0 待发队列仍在", "pendingSends" in read(os.path.join(SRC, "FlashApp.java")))
    check("待发管理窗口仍在", "showPendingWindow" in mc)
    check("崩溃捕获仍在", "CrashTrap" in read(os.path.join(SRC, "CrashApp.java"))
          if os.path.exists(os.path.join(SRC, "CrashApp.java")) else True)
    check("历史隐藏入口仍在", "HIDE_TAPS" in sc)
    check("按设备分文件夹仍在", "folderNameOf" in uc)
    check("主界面历史重载机制仍在", "historyCleared" in mc)

    print("\n" + "=" * 60)
    print(" 通过 %d 项，失败 %d 项" % (_pass, _fail))
    print("=" * 60)
    if _fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
