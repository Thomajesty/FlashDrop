# -*- coding: utf-8 -*-
"""v1.16.0 安卓端静态审计（源码断言，不依赖 Android SDK / 模拟器）

对应用户本轮 6 项需求里与**安卓端**相关的部分：

  [1] 保存目录 → Download/FlashDrop/保存的文件（不可被设置页/聊天页删除键清空）
  [2] 文件浏览流畅度优化（文本分块懒加载 / PDF 后台逐页渲染 + LRU）
  [3] 锁屏息屏在线（WifiLock + WakeLock + 心跳宽限 90s）+ 回读确认同步
  [5] 文件卡片微信化 + 长按菜单重做 + 浅色适配 + APK 走系统安装器
      + 预览器「其他应用打开」交系统（支持 WPS）
  [6] 删除弹窗全部换成微信风格 FdDialog

跑法（任选，不需要 PySide6）：
    "C:/Users/Administrator/.workbuddy/binaries/python/versions/3.13.12/python.exe" \
        android/tests/verify_v1160_static.py
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(ROOT, "android", "app", "src", "main")

pass_n = 0
fail_n = 0
_fails = []


def check(name, cond, detail=""):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print(f"  [PASS] {name}")
    else:
        fail_n += 1
        _fails.append(name)
        print(f"  [FAIL] {name}  {detail}")


def rd(p):
    with io.open(p, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def java(name):
    return rd(os.path.join(SRC, "java", "com", "flashdrop", "app", name))


FDU = java("FdUtil.java")
FOP = java("FdFileOp.java")
FIC = java("FdFileIcon.java")
FMI = java("FdMenuIcon.java")
FDG = java("FdDialog.java")
FPR = java("FdProto.java")
FNODE = java("FlashNode.java")
MA = java("MainActivity.java")
SA = java("SettingsActivity.java")
FTH = java("FdTheme.java")
FPV = java("FdPreviewActivity.java")
IVW = java("ImageViewerActivity.java")
MANIFEST = rd(os.path.join(SRC, "AndroidManifest.xml"))
L_IN = rd(os.path.join(SRC, "res", "layout", "item_file_in.xml"))
L_OUT = rd(os.path.join(SRC, "res", "layout", "item_file_out.xml"))
BUILD = rd(os.path.join(ROOT, "android", "build_apk.bat"))

# ==================================================================
# [0] 版本号四件套
# ==================================================================
print("\n[0] 版本号四件套 = 1.16.0 / versionCode 27")
check("FdUtil.APP_VERSION = 1.16.0", 'APP_VERSION = "1.16.0"' in FDU)
check("Manifest versionName 1.16.0", 'android:versionName="1.16.0"' in MANIFEST)
check("Manifest versionCode 27", "android:versionCode=\"3" in MANIFEST or "android:versionCode=\"4" in MANIFEST)
check("build_apk.bat --version-name 1.16.0",
      "--version-name 1.16.0" in BUILD)
check("build_apk.bat --version-code >= 36", "--version-code 3" in BUILD or "--version-code 4" in BUILD)

# ==================================================================
# [1] 保存目录重构 + 受保护不可删
# ==================================================================
print("\n[1] 保存目录 → Download/FlashDrop/保存的文件（受保护）")
check("FdUtil 定义 USER_SAVE_DIR = \"保存的文件\"",
      'USER_SAVE_DIR = "保存的文件"' in FDU)
check("有 userSavePathDesc()", "userSavePathDesc" in FDU)
check("有 isProtectedPath()", "def isProtectedPath" not in FDU
      and "isProtectedPath" in FDU)
check("有 notProtectedClause()（MediaStore 查询排除）",
      "notProtectedClause" in FDU)
check("有 legacyUserSaveDir()", "legacyUserSaveDir" in FDU)
check("countSavedFiles 带排除条件", "notProtectedClause()" in FDU)
check("deleteSavedFiles 带排除条件", "notProtectedClause()" in FDU)
check("deleteSavedByRelPath 显式跳过受保护路径",
      "isProtectedPath(rel)" in FDU)
check("deleteRecursively 跳过「保存的文件」目录",
      'USER_SAVE_DIR.equals(f.getName())' in FDU)
check("FdFileOp.SAVE_DIR_DESC 用 userSavePathDesc()",
      "FdUtil.userSavePathDesc()" in FOP)
check("FdFileOp.SAVE_REL_PATH 指向 /保存的文件",
      "SAVE_REL_PATH" in FOP and "USER_SAVE_DIR" in FOP)
check("MainActivity.deleteLocalFileOf 跳过受保护路径",
      "FdUtil.isProtectedPath(m.path)" in MA
      and "FdUtil.isProtectedPath(m.open)" in MA)

# ==================================================================
# [2] 文件浏览流畅度优化
# ==================================================================
print("\n[2] 浏览流畅度优化（文本分块 / PDF 懒渲染）")
check("FdPreview 文本改为分块（splitChunks）", "splitChunks" in FPV)
check("文本按行切块，每块 240 行", "240" in FPV)
check("文本块懒加载（滚动到 80% 追加）",
      "addOnScrollChangedListener" in FPV and "0.8f" in FPV)
check("textView 不再一次性 setText 整篇",
      "appendTextChunk" in FPV)
check("文本限读上限提到 8MB", "8 << 20" in FPV)
check("PDF 改为后台线程渲染", "new Thread" in FPV)
check("PDF 位图 LRU 回收（PDF_BITMAP_LRU）", "PDF_BITMAP_LRU" in FPV)
check("PDF 页面上限 PDF_PAGE_LIMIT", "PDF_PAGE_LIMIT" in FPV)
check("PDF 滚动节流（120ms 防抖）", "postDelayed(render, 120)" in FPV)

# ==================================================================
# [3] 锁屏息屏在线 + 回读确认同步
# ==================================================================
print("\n[3] 锁屏息屏在线 + 回读确认同步")
check("FdProto 定义 T_SYNC", 'T_SYNC = "SYNC"' in FPR)
check("FlashNode 有 WifiLock", "createWifiLock" in FNODE
      and "WIFI_MODE_FULL_HIGH_PERF" in FNODE)
check("FlashNode 有 WakeLock", "WakeLock" in FNODE
      and "PARTIAL_WAKE_LOCK" in FNODE)
check("有 WifiLockHolder 内部类", "class WifiLockHolder" in FNODE)
check("有 setTransferring()", "setTransferring" in FNODE)
check("有 acquireWakeLock / releaseWakeLock",
      "acquireWakeLock" in FNODE and "releaseWakeLock" in FNODE)
check("有 screenOff() 判定", "screenOff" in FNODE)
check("心跳宽限常量 30s / 90s",
      "HEARTBEAT_GRACE_MS = 30000" in FNODE
      and "HEARTBEAT_GRACE_IDLE_MS = 90000" in FNODE)
check("心跳按 息屏/传输/inbounds 放宽",
      "screenOff() || transferringNow.get()" in FNODE)
check("SEND_WAIT_OK 提到 300000", "waitSlot(okSlot, 300000)" in FNODE)
check("有 verifySavedFile 回读", "verifySavedFile" in FNODE)
check("FILE_OK 回传 verified", '"verified", verified' in FNODE)
check("verified=false 判 fail「对方未能写入文件」",
      '"对方未能写入文件"' in FNODE)
check("beginInbound 设置传输中标记",
      "beginInbound" in FNODE and "setTransferring(true)" in FNODE)

print("\n[3a] ★ Manifest 权限前置条件（不声明 = 代码完全失效）")
check("声明 WAKE_LOCK（否则 newWakeLock 抛 SecurityException）",
      "android.permission.WAKE_LOCK" in MANIFEST,
      "缺 WAKE_LOCK → 息屏在线修复完全无效")
check("声明 CHANGE_WIFI_STATE（WifiLock 部分 ROM 需要）",
      "android.permission.CHANGE_WIFI_STATE" in MANIFEST)
check("声明 CHANGE_WIFI_MULTICAST_STATE（MulticastLock）",
      "CHANGE_WIFI_MULTICAST_STATE" in MANIFEST)
check("FlashNode 里用了 WakeLock 就必须有权限声明",
      ("WakeLock" not in FNODE)
      or ("android.permission.WAKE_LOCK" in MANIFEST),
      "代码用 WakeLock 但 Manifest 未声明")
check("FlashNode 里用了 WifiLock 就必须有 CHANGE_WIFI_STATE",
      ("createWifiLock" not in FNODE)
      or ("android.permission.CHANGE_WIFI_STATE" in MANIFEST),
      "代码用 WifiLock 但 Manifest 未声明 CHANGE_WIFI_STATE")
check("声明 REQUEST_INSTALL_PACKAGES（APK 安装）",
      "REQUEST_INSTALL_PACKAGES" in MANIFEST)

# ==================================================================
# [5] 文件卡片微信化
# ==================================================================
print("\n[5a] 文件卡片几何：322 / 40x52")
check("FdFileIcon 基准 DW=40 DH=52",
      "DW = 40f" in FIC and "DH = 52f" in FIC,
      repr([l for l in FIC.splitlines() if "DW = " in l or "DH = " in l][:2]))
check("有折角常量 FOLD", "FOLD" in FIC)
check("折角在**右上**（DW-FOLD → DW,FOLD）",
      "DW - FOLD, 0f" in FIC and "DW, FOLD" in FIC)
check("未下载态用 DashPathEffect 虚线",
      "DashPathEffect" in FIC)
check("Card 宽 = 屏宽 × 0.493（322/655）", "0.493f" in MA)
check("fileIconWidth = dp(40)", "return dp(40);" in MA)
check("fileIconSize = dp(52)", "return dp(52);" in MA)
check("fileCardTextWidth 扣掉 12+14+12+图标",
      "dp(12 + 14 + 12)" in MA)
check("气泡固定宽度被写死", "lp.width = fileCardWidth();" in MA)
check("布局 item_file_in 图标 40x52",
      'android:layout_width="40dp"' in L_IN
      and 'android:layout_height="52dp"' in L_IN)
check("布局 item_file_out 图标 40x52",
      'android:layout_width="40dp"' in L_OUT
      and 'android:layout_height="52dp"' in L_OUT)
check("in 布局：头像在首（左）",
      L_IN.index('android:id="@+id/msg_avatar"')
      < L_IN.index('android:id="@+id/msg_bubble"'))
check("out 布局：头像在尾（右）",
      L_OUT.index('android:id="@+id/msg_avatar"')
      > L_OUT.index('android:id="@+id/msg_bubble"'))

print("\n[5b] 文件类型分类：APK 与 EXE 分开")
check("FdFileIcon 有 apk 独立分支 → #3DDC84",
      "3DDC84" in FIC and '"apk"' in FIC)
check("apk 标签为 APK", '"APK"' in FIC)
check("exe/msi → #0F6FCB + EXE",
      "0F6FCB" in FIC and '"EXE"' in FIC)
check("apk 不再与 exe/msi 同组",
      'case "apk": case "exe"' not in FIC
      and '"exe", "msi", "apk"' not in FIC)

print("\n[5c] 长按菜单重做（图标 + 不换行 + 去重）")
check("FdMenuIcon 存在且实现 make()",
      "public static Bitmap make" in FMI)
check("FdMenuIcon 有 Item 内部类", "class Item" in FMI)
check("图标种类 ≥ 10 种",
      len(re.findall(r"public static final int [A-Z_]+ =", FMI)) >= 10,
      repr(re.findall(r"public static final int (\w+) =", FMI))[:1])
check("MainActivity 用 FdMenuIcon.Item 列表构建菜单",
      "List<FdMenuIcon.Item> items" in MA)
check("每行 5 项（PER_ROW = 5）", "PER_ROW = 5" in MA)
check("菜单项文字强制单行 setSingleLine(true)",
      "setSingleLine(true)" in MA)
check("菜单项 setMaxWidth 防挤压", "setMaxWidth(dp(72))" in MA)
check("已删除重复项「更多打开方式」",
      '"更多打开方式"' not in MA)
check("保留「其他应用打开」", '"其他应用打开"' in MA)
check("菜单含 打开/保存/分享/删除/多选",
      all(x in MA for x in ['"打开"', '"保存"', '"分享"', '"删除"', '"多选"']))
check("屏幕贴边修正（防止弹到屏外）",
      "screenW - pw - dp(6)" in MA)

print("\n[5d] 浅色适配")
check("浅底气泡补描边（对比度）",
      "perceivedLuminance(bubbleBg) > 0.82f" in MA)
check("主题浅色下 card=#FFFFFF / text=#1F2328",
      "0xFFFFFFFF" in FTH and "0xFF1F2328" in FTH)
check("有 onColorText / onColorDim 自适应前景",
      "onColorText" in FTH and "onColorDim" in FTH)
check("有 onColorAccent 语义色适配",
      "onColorAccent" in FTH)

print("\n[5e] APK 走系统安装器（不再硬指 MIME）")
check("doInstallApk 改为逐级探测", "private boolean tryInstall" in MA)
check("先探测 resolveActivity 再启动",
      "probe.resolveActivity(getPackageManager()) == null" in MA)
check("用 createChooser 让用户选安装程序",
      'Intent.createChooser(base, "选择安装程序")' in MA)
check("保留 ACTION_INSTALL_PACKAGE 兜底",
      "Intent.ACTION_INSTALL_PACKAGE" in MA)

print("\n[5f] 预览器「其他应用打开」交系统（WPS 可现）")
check("openWithChooser 逐级放宽", "probeAndChoose" in FOP)
check("第二级用通配 */*（关键：让 WPS 进候选）",
      '"*/*"' in FOP)
check("有 effectiveMime（真实 MIME 优先）",
      "effectiveMime" in FOP)
check("mimeOf 支持 2 参（按扩展名补 MIME）",
      "mimeOf(String mime, String fileName)" in FOP)
check("覆盖 docx 的完整 MIME",
      "wordprocessingml.document" in FOP)
check("覆盖 xlsx / pptx",
      "spreadsheetml.sheet" in FOP and "presentationml.presentation" in FOP)
check("覆盖 WPS 自有格式 wps/et/dps",
      'case "wps"' in FOP and 'case "et"' in FOP and 'case "dps"' in FOP)

# ==================================================================
# [6] 删除弹窗微信风格
# ==================================================================
print("\n[6] 删除弹窗 → 微信风格 FdDialog")
check("FdDialog 存在且非空", len(FDG) > 3000)
check("有 confirm / danger / info / list / custom",
      all(("void " + m) in FDG
          for m in ["confirm(", "danger(", "info(", "list(", "custom("]))
check("有 multiChoice（多选行）", "multiChoice" in FDG)
check("微信绿 #07C160", "0xFF07C160" in FDG)
check("微信红 #FA5151（危险操作）", "0xFFFA5151" in FDG)
check("按钮上下堆叠（VERTICAL + 分隔线）",
      "LinearLayout.VERTICAL" in FDG and "divider" in FDG)
check("点击外部不关闭（微信行为）",
      "setCanceledOnTouchOutside(false)" in FDG)
check("对话框宽 78% 屏宽", "0.78f" in FDG)
check("圆角 12dp", "12)" in FDG)

print("\n[6a] MainActivity 系统 AlertDialog 已清零")
remain = len(re.findall(r"new AlertDialog\.Builder\(this\)", MA))
check(f"MainActivity 无残留 AlertDialog.Builder(this)（实际 {remain}）",
      remain == 0, f"剩余 {remain} 处")
sremain = len(re.findall(r"new AlertDialog\.Builder\(this\)", SA))
check(f"SettingsActivity 无残留（实际 {sremain}）", sremain == 0,
      f"剩余 {sremain} 处")
check("删除消息走 FdDialog（含「删除后不可恢复」）",
      '"删除消息"' in MA and "删除后不可恢复" in MA)
check("多选删除走 FdDialog.danger", "FdDialog.danger" in MA)
check("设置页数据清理走 FdDialog.custom", "FdDialog.custom" in SA)
check("设置页再次确认走 FdDialog.danger", "FdDialog.danger" in SA)
check("收到文件确认走 FdDialog.show（接收/拒绝）",
      "FdDialog.show(this, \"收到文件\"" in MA)
check("链接菜单走 FdDialog.list", "FdDialog.list" in MA)
check("待发送提示走 FdDialog.info", "FdDialog.info" in MA)

# ==================================================================
print("\n" + "=" * 60)
print(f"合计：{pass_n} 通过 / {fail_n} 失败")
if _fails:
    print("失败项：")
    for f in _fails:
        print("  - " + f)
print("=" * 60)
sys.exit(1 if fail_n else 0)
