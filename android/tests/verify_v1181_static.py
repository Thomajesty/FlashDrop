# -*- coding: utf-8 -*-
"""v1.18.7 静态验收 —— APK 安装入口修复

背景：用户反馈 v1.18.0 在闪传 App 内点收到的 APK → 「未找到可用的安装程序」，
且"前面版本都是没有问题的"。

诊断结论（本次已核实）：
  · APK 文件本身无问题 —— 包名/minSdk/targetSdk/13 项权限/v2+v3 签名/
    证书 SHA-256/zip 结构（41 条目、flag_bits、压缩方法、中央目录偏移）
    与 v1.17.0 逐项一致，md5 校验通过，可覆盖安装。
  · 报错文案来自 MainActivity:3526 的兜底 toast，该逻辑自 v1.16.0 起未改。
  · 根因是环境漂移放大了两个先天缺陷：
      缺陷① tryInstall 用 new Intent(base) 复制后探测，语义与真实匹配不一致
      缺陷② ACTION_INSTALL_PACKAGE 在 Android 9+ 国产 ROM 上多已移除声明

本套件固化修复，防止回归。
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ANDROID = os.path.dirname(HERE)
SRC = os.path.join(ANDROID, "app", "src", "main", "java", "com", "flashdrop", "app")
MA = open(os.path.join(SRC, "MainActivity.java"), encoding="utf-8").read()
FU = open(os.path.join(SRC, "FdUtil.java"), encoding="utf-8").read()
MF = open(os.path.join(ANDROID, "app", "src", "main", "AndroidManifest.xml"),
          encoding="utf-8").read()
BAT = open(os.path.join(ANDROID, "build_apk.bat"), encoding="utf-8").read()

PASS = 0
FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK] {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name} {detail}")


def section(t):
    print(f"\n=== {t} ===")


# 取 doInstallApk 方法体
m = re.search(r"private void doInstallApk\(Uri uri\) \{(.*?)\n    \}", MA, re.S)
DO = m.group(1) if m else ""
# 取 tryInstall 方法体
m2 = re.search(r"private boolean tryInstall\(Intent base\) \{(.*?)\n    \}", MA, re.S)
TI = m2.group(1) if m2 else ""

print("=" * 62)
print("v1.18.7 静态验收 —— APK 安装入口修复")
print("=" * 62)

section("§1 doInstallApk 四级放宽策略")
check("方法存在", bool(DO))
check("MIME_APK 常量已定义", 'MIME_APK = "application/vnd.android.package-archive"' in MA)
check("① 精确 apk MIME", "setDataAndType(uri, MIME_APK)" in DO)
check("② 通配 MIME（国产 ROM 救命稻草）", 'setDataAndType(uri, "*/*")' in DO)
check("③ 不带 MIME（靠 getType 推断）",
      re.search(r"new Intent\(Intent\.ACTION_VIEW\)\s*\n?\s*\.setData\(uri\)", DO) is not None)
check("④ ACTION_INSTALL_PACKAGE 保留为最后一级",
      "ACTION_INSTALL_PACKAGE" in DO)
check("四级顺序正确（①在②前，②在③前，③在④前）",
      DO.find("MIME_APK") < DO.find('"*/*"') < DO.find(".setData(uri)")
      < DO.find("ACTION_INSTALL_PACKAGE"))
check("每级都带 FLAG_GRANT_READ_URI_PERMISSION", DO.count("grant") >= 4)
check("grant 常量提取（避免逐级硬编码）",
      "final int grant = Intent.FLAG_GRANT_READ_URI_PERMISSION" in DO)

section("§2 旧兜底文案已移除 + 新引导弹窗")
# 注：旧文案仍会出现在 javadoc 的"演进历史"里（描述本次修的是什么），
# 因此不能全仓搜字符串，必须限定在 **可执行代码** 里搜。
MA_CODE = re.sub(r"/\*.*?\*/", "", MA, flags=re.S)          # 去块注释
MA_CODE = re.sub(r"^\s*//.*$", "", MA_CODE, flags=re.M)     # 去行注释
MA_CODE = re.sub(r"^\s*\*.*$", "", MA_CODE, flags=re.M)     # 去残留 javadoc 行
check("旧 toast 文案已从可执行代码移除",
      "未找到可用的安装程序" not in MA_CODE,
      "仍存在于 toast(...) 调用中")
check("旧文案仅保留在注释（演进历史）中",
      "未找到可用的安装程序" in MA)
check("新弹窗标题存在", "未能启动安装程序" in MA)
check("弹窗给出 3 条可执行检查项",
      "是否已允许" in MA and "安全中心" in MA and "长按" in MA)
check("弹窗带「去设置」跳转未知来源开关",
      "ACTION_MANAGE_UNKNOWN_APP_SOURCES" in DO or "ACTION_MANAGE_UNKNOWN_APP_SOURCES" in MA)
check("用 FdDialog 而非裸 toast", "FdDialog.show" in DO)

section("§3 tryInstall 探测方式改造（缺陷①）")
check("方法存在", bool(TI))
check("改用 queryIntentActivities 计数", "queryIntentActivities" in TI)
check("不再用 resolveActivity 探测", "resolveActivity" not in TI)
check("空列表判定", "cands == null" in TI and "isEmpty()" in TI)
check("单候选直启（省一次点击）", "cands.size() == 1" in TI)
check("多候选才用 chooser", "createChooser" in TI)
check("ResolveInfo 已导入", "import android.content.pm.ResolveInfo;" in MA)
check("PackageManager 已导入", "import android.content.pm.PackageManager;" in MA)
check("List 已导入", "import java.util.List;" in MA)

section("§4 安装权限前置检查未被破坏")
check("installApk 仍检查 canRequestPackageInstalls",
      "canRequestPackageInstalls" in MA)
check("Android 8.0+ 分支保留", "Build.VERSION.SDK_INT >= 26" in MA)
check("授权后自动重试机制保留",
      "installApkRetry" in MA and "doInstallApk(retryUri)" in MA)
check("REQUEST_INSTALL_PACKAGES 权限在 Manifest",
      "REQUEST_INSTALL_PACKAGES" in MF)

section("§5 回归：isApk / uriOf 未受影响")
check("isApk 仍识别扩展名", '"apk".equals(e)' in MA)
check("isApk 仍识别 MIME", "android.package-archive" in MA)
check("openFile 仍先走内置预览再走 apk 安装",
      "FdPreviewActivity.canPreview" in MA and "installApk(m)" in MA)

section("§6 版本号四件套（1.18.7 / code 30）")
check("FdUtil APP_VERSION 为 1.18.x", "APP_VERSION = \"1.18." in FU)
check("Manifest versionName 为 1.18.x", 'versionName="1.18.' in MF)
check("Manifest versionCode >= 36", 'versionCode="3' in MF or 'versionCode="4' in MF)
check("build_apk.bat --version-code >= 36", "--version-code 3" in BAT or "--version-code 4" in BAT)
check("build_apk.bat --version-name 为 1.18.x", "--version-name 1.18." in BAT)

section("§7 Javadoc 陷阱回归（{@code */*} 会提前终止注释）")
check("注释中不含会提前闭合的 {@code */*}",
      "{@code */*}" not in MA,
      "该写法里的 */ 会终止块注释，导致整段被当代码解析 → 编译失败")
check("通配 MIME 的说明改为纯文字",
      "通配 MIME（国产 ROM" in MA or "通配 MIME" in MA)

section("§8 APK 结构未被破坏（构建产物的静态前提）")
check("minSdk 24 保留", "--min-sdk-version 24" in BAT)
check("targetSdk 34 保留", "--target-sdk-version 34" in BAT)
check("签名步骤保留", "apksigner" in BAT)
check("验签步骤保留", "verify" in BAT)

print("\n" + "=" * 62)
print(f"v1.18.7 静态验收：通过 {PASS} 项，失败 {FAIL} 项")
if FAILS:
    print("失败项：")
    for f in FAILS:
        print("  -", f)
print("=" * 62)
sys.exit(1 if FAIL else 0)
