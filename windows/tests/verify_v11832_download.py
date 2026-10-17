# -*- coding: utf-8 -*-
"""v1.18.32 专项：双端「检查更新 → 应用内下载」静态断言。

背景（用户反馈）：v1.18.30/31 的更新对话框只展示说明文字，
点「下载」实际只是跳浏览器——没有应用内下载能力。

本套件源码级断言：
  A. Windows（app/ui/main_window.py）：UpdateDownloader 后台下载线程
     + .part 临时文件 + 进度信号 + 立即安装/打开文件夹 + 取消清理；
  B. Android（UpdateChecker.java）：进度对话框 + 重定向跟随 + .part 落盘
     + FdFileProvider content:// 调起安装器 + API26 安装授权引导
     + 失败回退浏览器（绝不静默）；
  C. 常规：版本号 5 处一致 1.18.32 / versionCode 61；构建脚本 -A assets 铁律。
"""
import io
import os
import re
import sys

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT)

_ok = 0
_bad = []


def ck(name, cond):
    global _ok
    if cond:
        _ok += 1
        print("  PASS %s" % name)
    else:
        _bad.append(name)
        print("  FAIL %s" % name)


win = io.open("windows/app/ui/main_window.py", encoding="utf-8").read()
uc = io.open("android/app/src/main/java/com/flashdrop/app/UpdateChecker.java",
             encoding="utf-8").read()
initpy = io.open("windows/app/__init__.py", encoding="utf-8").read()
manifest = io.open("android/app/src/main/AndroidManifest.xml", encoding="utf-8").read()
fdutil = io.open("android/app/src/main/java/com/flashdrop/app/FdUtil.java",
                 encoding="utf-8").read()
bat = io.open("android/build_apk.bat", encoding="utf-8").read()
sh = io.open("android/_build_v11817.sh", encoding="utf-8").read()

print("== A. Windows 应用内下载 ==")
ck("A1 UpdateDownloader 类存在且基于 QObject（跨线程 Signal 模式）",
   "class UpdateDownloader(QObject)" in win)
ck("A2 进度/完成/失败三类信号",
   "progress = Signal(int, int)" in win
   and "finished = Signal(str)" in win
   and "failed = Signal(str)" in win)
ck("A3 .part 临时文件 + os.replace 原子改名",
   'open(tmp, "wb")' in win and "os.replace(tmp, self.dest)" in win)
ck("A4 进度回调含 Content-Length 解析",
   'resp.headers.get("Content-Length")' in win)
ck("A5 取消：cancel 标志 + 关闭/拒绝对话框时清理线程",
   "def cancel(self)" in win and "self._worker.cancel()" in win
   and "def _cleanup_thread" in win)
ck("A6 QThread + moveToThread（不在工作线程碰 UI）",
   "moveToThread(self._thread)" in win and "QThread()" in win)
ck("A7 未知大小走马灯进度条（range(0,0)）",
   "setRange(0, 0)" in win)
ck("A8 EXE 完成后「立即安装（关闭并启动新版本）」",
   "立即安装（关闭并启动新版本）" in win and "def _install" in win)
ck("A9 立即安装 = 启动新 EXE 并退出当前程序",
   "subprocess.Popen([path]" in win and "QApplication.quit()" in win)
ck("A10 APK 完成后「打开所在文件夹」（explorer /select）",
   '"explorer", "/select,"' in win and "_open_folder" in win)
ck("A11 下载中禁用全部按钮、失败恢复并提示打开下载页",
   "_set_buttons_enabled(False)" in win and "_set_buttons_enabled(True)" in win
   and "下载失败" in win)
ck("A12 下载落点隔离在 %TEMP%\\FlashDropUpdate",
   "FlashDropUpdate" in win)

print("== B. Android 应用内下载与安装 ==")
ck("B1 startDownload 应用内下载入口存在",
   "public static void startDownload(final Activity a, final JSONObject apk)" in uc)
ck("B2 进度对话框可取消（取消置 volatile 标志）",
   "private static volatile boolean sCancelled" in uc
   and "sCancelled = true" in uc)
ck("B3 手动跟随重定向（301/302/303/307/308）",
   all(x in uc for x in ("301", "302", "303", "307", "308"))
   and 'getHeaderField("Location")' in uc)
ck("B4 .part 落盘 + renameTo 改名（防半包当成品）",
   '".part"' in uc and "renameTo(out)" in uc)
ck("B5 下载落点：cacheDir/flashdrop/update",
   'new File(FdUtil.cacheDir(a), "update")' in uc)
ck("B6 经 FdFileProvider 转 content:// 调起安装（API24+ 禁 file://）",
   "FdFileProvider.uriForAbsolute" in uc
   and "application/vnd.android.package-archive" in uc)
ck("B7 FLAG_GRANT_READ_URI_PERMISSION 授读",
   "FLAG_GRANT_READ_URI_PERMISSION" in uc)
ck("B8 API26+ 先查 canRequestPackageInstalls，未授权引导去系统设置",
   "canRequestPackageInstalls" in uc
   and "ACTION_MANAGE_UNKNOWN_APP_SOURCES" in uc
   and "Build.VERSION.SDK_INT >= Build.VERSION_CODES.O" in uc)
ck("B9 失败绝不静默：Toast + 回退打开下载页",
   "下载失败，已为你打开下载页" in uc and "openBrowser" in uc)
ck("B10 下载线程命名（可辨识）+ 15s 超时",
   '"fd-update-download"' in uc and "setConnectTimeout(15000)" in uc)
ck("B11 对话框文案含下载按钮（无 apk 附件时回退打开下载页）",
   "下载并安装" in uc and '"打开下载页"' in uc)
ck("B12 半包/取消后清理 .part",
   "tmp.delete()" in uc and "out.delete()" in uc)

print("== C. 版本号与构建铁律 ==")
ck("C1 Windows __version__ = 1.18.32", '__version__ = "1.18.32"' in initpy)
ck("C2 Android APP_VERSION = 1.18.32", 'APP_VERSION = "1.18.32";' in fdutil)
ck("C3 manifest 61 / 1.18.32",
   'android:versionCode="61"' in manifest
   and 'android:versionName="1.18.32"' in manifest)
ck("C4 build_apk.bat / _build_v11817.sh 同步 61/1.18.32",
   "--version-code 61 --version-name 1.18.32" in bat
   and "--version-code 61 --version-name 1.18.32" in sh)
ck("C5 aapt2 link 两个入口都带 -A assets（表情资产铁律）",
   '-A "%SRC%\\assets"' in bat and '-A "$BPW\\\\assets"' in sh)
ck("C6 UpdateChecker 编译期符号完整（imports 无缺）",
   all(x in uc for x in ("import android.os.Build;", "import java.io.File;",
                         "import android.provider.Settings;",
                         "import android.content.pm.PackageManager;")))

print()
print("PASS %d / FAIL %d" % (_ok, len(_bad)))
if _bad:
    print("FAILURES:")
    for b in _bad:
        print("  -", b)
    sys.exit(1)
print("ALL-GREEN")
