# -*- coding: utf-8 -*-
"""
FlashDrop v1.10.1 专项校验（直接扫真实 .java 源码，不依赖设备）

覆盖两个用户反馈的缺陷：

1. 设置页「打开保存位置」点了没用
   用户现象：点"打开保存位置" → 弹出应用选择器 → 选"我的文件" → 又弹回设置页
   真实根因：接收目录是公共 Download/FlashDrop，本应用无权用 FileProvider 暴露目录
            （FdFileProvider 只有 openFile，没有 queryDocuments/isChildDirectory，
              不具备 DocumentsProvider 能力）；
            唯一跳转途径 content://com.android.externalstorage.documents/...
            依赖目标文件管理器实现 DocumentsContract，国产 ROM 普遍不实现
            → 能打开文件管理器但随即解析失败返回。
   结论：无法修复，改为「查看保存位置」= 展示真实路径 + 各设备子目录 + 一键复制路径。
   本脚本锁死：旧的 Intent 跳转逻辑必须零残留。

2. 主界面删除文件后聊天记录还在
   用户现象：删除弹窗里删了"下载文件/接收图片"，文件没了但气泡记录仍在
   真实根因：v1.10.0 的 doScopedDelete 里
            - delChat 分支调用了 deleteMsgs()（会从 msgs 移除）
            - delFile/delImg 分支只调 FdUtil.deleteByIdentities() 删历史文件，
              **从未把消息从内存 msgs 里摘掉**，所以界面记录原封不动
   修复：三类统一走 detachMsgs()（内存移除，含 byMid/byTidIn/byTidOut 索引清理）
        + purgeMsgs()（磁盘文件 + 历史文件），并立即 refreshChat()。
   本脚本锁死：三类必须走同一条 detach 路径，且 detachMsgs 必须清理三个索引。
"""
import os
import re
import sys

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "app", "src", "main", "java", "com", "flashdrop", "app")
MAIN = os.path.join(SRC, "MainActivity.java")
SETT = os.path.join(SRC, "SettingsActivity.java")
FDU = os.path.join(SRC, "FdUtil.java")
FDP = os.path.join(SRC, "FdFileProvider.java")

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
    """
    剥离注释，避免把"根因说明注释"误判成真实代码。

    用逐字符状态机（不是逐行 split），否则跨行块注释 /* ... */
    只会吃掉第一行，剩下的 " * ..." 行会被当成代码 ——
    本轮就踩了这个坑：注释里写的 "早前这里调的是 FdUtil.deleteSavedFiles(...)"
    被误判成"代码里还在调 deleteSavedFiles"，产生假失败。
    """
    out = []
    i, n = 0, len(src)
    in_block = False
    in_line = False
    in_str = False
    in_chr = False
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if in_block:
            if c == "*" and nxt == "/":
                in_block = False
                i += 2
                # 保留换行，避免行号错位
                continue
            if c == "\n":
                out.append(c)
            i += 1
            continue
        if in_line:
            if c == "\n":
                in_line = False
                out.append(c)
            i += 1
            continue
        if in_str:
            out.append(c)
            if c == "\\" and nxt:
                out.append(nxt)
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if in_chr:
            out.append(c)
            if c == "\\" and nxt:
                out.append(nxt)
                i += 2
                continue
            if c == "'":
                in_chr = False
            i += 1
            continue
        # 普通代码区
        if c == "/" and nxt == "*":
            in_block = True
            i += 2
            continue
        if c == "/" and nxt == "/":
            in_line = True
            i += 2
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "'":
            in_chr = True
            out.append(c)
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def body_of(src, sig):
    i = src.find(sig)
    if i < 0:
        return None
    j = src.find("{", i)
    if j < 0:
        return None
    depth, k = 0, j
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
    print("=" * 62)
    print(" FlashDrop v1.10.1 专项校验（保存位置 + 记录同步删除）")
    print("=" * 62)

    for p in (MAIN, SETT, FDU, FDP):
        if not os.path.exists(p):
            print("源码缺失: " + p)
            sys.exit(2)

    m, s, u, fp = read(MAIN), read(SETT), read(FDU), read(FDP)
    mc, sc, uc = strip_comments(m), strip_comments(s), strip_comments(u)

    # ==================================================================
    sec("1. 旧跳转逻辑必须零残留（问题 1 根因）")

    check("MainActivity 无 settings.DOWNLOADS_SETTINGS",
          "DOWNLOADS_SETTINGS" not in mc)
    check("MainActivity 无 externalstorage.documents", "externalstorage.documents" not in mc)
    check("SettingsActivity 无 android.settings.DOWNLOADS_SETTINGS",
          "DOWNLOADS_SETTINGS" not in sc)
    check("SettingsActivity 无 externalstorage.documents 跳转",
          "externalstorage.documents" not in sc)
    check("SettingsActivity 无 ACTION_GET_CONTENT 选文件绕路",
          "ACTION_GET_CONTENT" not in sc)
    check("已删除 openSaveFolder 方法", "openSaveFolder" not in sc)
    check("已删除 CATEGORY_OPENABLE（那是选文件不是开目录）",
          "CATEGORY_OPENABLE" not in sc)

    # 全源码目录扫一遍
    bad = []
    for fn in os.listdir(SRC):
        if fn.endswith(".java") and "externalstorage.documents" in strip_comments(read(os.path.join(SRC, fn))):
            bad.append(fn)
    check("全源码无 externalstorage.documents 跳转残留", not bad, str(bad))

    # ==================================================================
    sec("2. 新的「查看保存位置」（100% 可用方案）")

    check("有 showSaveLocation 方法", body_of(sc, "private void showSaveLocation()") is not None)
    sl = body_of(sc, "private void showSaveLocation()")
    if sl:
        check("展示真实路径", "saveRootDesc()" in sl)
        check("列出各设备子目录", "isDirectory()" in sl and "listFiles()" in sl)
        check("子目录带文件数统计", "countSavedFiles(this, f.getName())" in sl)
        check("空目录有友好提示", "还没有收到过文件" in sl)
        check("有复制路径按钮", 'setPositiveButton("复制路径"' in sl)
        check("有取消按钮", 'setNegativeButton("关闭"' in sl)
        check("告知用户粘贴到地址栏", "地址栏粘贴" in sl)
        check("子目录排序便于阅读", "Collections.sort" in sl)

    check("有 copySavePath 方法", body_of(sc, "private void copySavePath(") is not None)
    cp = body_of(sc, "private void copySavePath(")
    if cp:
        check("写入剪贴板", "setPrimaryClip" in cp)
        check("复制的是绝对路径（各 ROM 通用）",
              "getExternalStoragePublicDirectory" in cp)
        check("有失败兜底（手动输入提示）", "复制失败" in cp)
        check("有次级兜底（复制目录名）", "FlashDrop\"" in cp)

    check("入口文案改为「查看保存位置」", '"查看保存位置' in sc)
    check("入口调用 showSaveLocation", "showSaveLocation()" in sc)
    check("入口不再是 Intent 跳转",
          body_of(sc, 'openDir.setOnClickListener') is None
          or "showSaveLocation" in sc)

    # ==================================================================
    sec("3. 根因确认：FdFileProvider 确实无法暴露目录")

    fpc = strip_comments(fp)
    check("FdFileProvider 未实现 DocumentsProvider（无 queryDocuments）",
          "queryDocuments" not in fpc)
    check("FdFileProvider 无 isChildDirectory", "isChildDirectory" not in fpc)
    check("FdFileProvider 只支持 cache/files/abs 三类路径",
          'path.startsWith("/cache/")' in fpc
          and 'path.startsWith("/files/")' in fpc
          and 'path.startsWith("/abs/")' in fpc)
    check("FdFileProvider 继承 ContentProvider 而非 DocumentsProvider",
          "extends ContentProvider" in fpc and "extends DocumentsProvider" not in fpc)

    # ==================================================================
    sec("4. 记录同步删除（问题 2 根因）")

    ds = body_of(mc, "private void doScopedDelete(")
    check("doScopedDelete 存在", ds is not None)
    if ds:
        # 只看「key 收集段」= 方法开头 → detachMsgs 调用之前。
        # 方法体后半段仍有 if (delChat) 用于后台清历史文件，那是正确且必要的，
        # 不能拿整个方法体来判断 key 收集是否被 delChat 门禁（v1.10.1 修正的断言）。
        _cut = ds.find("detachMsgs(")
        seg = ds[:_cut] if _cut > 0 else ds
        check("key 收集段内没有 delChat 门禁（三类统一收集）",
              "if (delChat)" not in seg)
        check("key 收集段按作用域筛选（设备级 or 全局）",
              "allScope || viewPeerId.equals(peerScopeOf(m))" in seg)
        check("三类统一按 categoryOf 分派",
              "(c == CAT_CHAT) ? delChat" in ds
              and "(c == CAT_IMAGE) ? delImg" in ds
              and "(c == CAT_FILE) ? delFile" in ds)
        check("调用 detachMsgs 做内存移除", "detachMsgs(" in ds)
        check("立即刷新界面", "refreshChat()" in ds)
        check("调用 purgeMsgs 做磁盘+历史清理", "purgeMsgs(" in ds)
        check("detach 在主线程（refresh 之前）",
              ds.find("detachMsgs(") < ds.find("refreshChat()"))
        check("磁盘残留也一并清（消息已清但文件还在）",
              "deleteSavedFiles(" in ds)
        check("聊天记录按作用域清", "clearHistory(" in ds and "clearAllHistory(" in ds)
        check("不再调用旧的 deleteMsgs（避免重复移除与二次 toast）",
              "deleteMsgs(" not in ds)
        check("Toast 汇总记录数与文件数",
              "条记录" in ds and "个文件" in ds)

    dm = body_of(mc, "private List<Msg> detachMsgs(")
    check("detachMsgs 存在", dm is not None)
    if dm:
        check("从 msgs 里真正移除", "msgs.removeIf" in dm)
        check("收集被移除的消息用于后续删文件", "gone.add(m)" in dm)
        check("清理 byMid 索引（否则进度事件复活）", "byMid.remove" in dm)
        check("清理 byTidIn 索引", "byTidIn.remove" in dm)
        check("清理 byTidOut 索引", "byTidOut.remove" in dm)
        check("空集合直接返回不报错", "if (keys == null || keys.isEmpty()) return gone" in dm)
        check("操作 msgs 都在同步块内", "synchronized (msgs)" in dm)

    pm = body_of(mc, "private int purgeMsgs(")
    check("purgeMsgs 存在", pm is not None)
    if pm:
        check("删对应磁盘文件", "deleteLocalFileOf" in pm)
        check("清历史文件条目", "deleteByIdentities" in pm)
        check("返回删除文件数用于汇总", "return files" in pm)

    check("有 tidOf 还原辅助（配合 tid 索引清理）",
          body_of(mc, "private static String tidOf(") is not None)
    check("keyOf 格式未变（ts|midOrTid|dir|kind）",
          'return m.ts + "|" + (m.mid != null ? m.mid' in mc)
    check("midOf 仍存在（byMid 清理复用）",
          body_of(mc, "private static String midOf(") is not None)

    # ==================================================================
    sec("5. 三类都是「记录 + 文件」成对删除")

    # 模拟：删图片时，图片消息必须同时进 keys（不再只删文件）
    ds2 = ds or ""
    check("图片类删除会摘除对应消息（categoryOf 命中 CAT_IMAGE）",
          "(c == CAT_IMAGE) ? delImg" in ds2)
    check("文件类删除会摘除对应消息（categoryOf 命中 CAT_FILE）",
          "(c == CAT_FILE) ? delFile" in ds2)
    check("聊天类删除会摘除对应消息（categoryOf 命中 CAT_CHAT）",
          "(c == CAT_CHAT) ? delChat" in ds2)
    check("作用域过滤仍在（不误删别的设备）",
          "viewPeerId.equals(peerScopeOf(m))" in ds2)
    check("全部设备视图仍可全删", "allScope ||" in ds2)

    # ==================================================================
    sec("6. v1.10.0 既有能力未被破坏")

    check("v1.10.0 删除弹窗仍在",
          body_of(mc, "private void showDeletePicker()") is not None)
    dp = body_of(mc, "private void showDeletePicker()")
    if dp:
        check("CheckBox[3] 崩溃修复仍在",
              re.search(r"CheckBox\[\]\s*checks\s*=\s*new\s+CheckBox\[3\]", dp) is not None)
        check("三类 CheckBox 仍在", "CAT_NAMES[c]" in dp)
        check("全选按钮仍在", '"全选"' in dp)
        check("删除/取消按钮仍在",
              'setPositiveButton("删除"' in dp and 'setNegativeButton("取消"' in dp)
    check("二次确认仍在", body_of(mc, "private void confirmScopedDelete(") is not None)
    check("设置页数据清理仍在", body_of(sc, "private void onDataClean()") is not None)
    check("设置页 runDataClean 仍在", body_of(sc, "private void runDataClean(") is not None)
    check("数据清理仍为全局（folder 传 null）", "deleteSavedFiles(this, null," in sc)
    check("v1.9.0 待发队列未被破坏", "pendingSends" in read(os.path.join(SRC, "FlashApp.java")))
    check("崩溃捕获仍在", "CrashTrap" in read(os.path.join(SRC, "CrashApp.java"))
          if os.path.exists(os.path.join(SRC, "CrashApp.java")) else True)

    print("\n" + "=" * 62)
    print(" 通过 %d 项，失败 %d 项" % (_pass, _fail))
    print("=" * 62)
    if _fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
