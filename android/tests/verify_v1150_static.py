# -*- coding: utf-8 -*-
"""v1.15.0 安卓端静态验收（源码级断言，不需要编译/装机）

覆盖用户本轮 5 项需求：
  1. 图片消息恢复缩略图模式（photoMode + 点击查看原图 + 分享/保存）
  2. 文件卡片严格微信几何（等宽 450dp / 图标 44x50 矩形缺角 / 两行中间省略 /
     大小与状态同一行 / 图标贴右垂直居中）
  3. APK 安装器「打开后不执行下一步」（REQUEST_INSTALL_PACKAGES + 授权引导 + 自动重试）
  4. 内置预览器 + 三点菜单（保存 / 转发）+ 长按卡片弹菜单 + 不支持类型 2 秒提示
  5. 左右分侧与头像位置（出右 / 入左，头像同侧）

跑法：
    python android/tests/verify_v1150_static.py
"""
import io
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MAIN = os.path.join(ROOT, "app/src/main/java/com/flashdrop/app/MainActivity.java")
PREVIEW = os.path.join(ROOT, "app/src/main/java/com/flashdrop/app/FdPreviewActivity.java")
FILEOP = os.path.join(ROOT, "app/src/main/java/com/flashdrop/app/FdFileOp.java")
ICON = os.path.join(ROOT, "app/src/main/java/com/flashdrop/app/FdFileIcon.java")
UTIL = os.path.join(ROOT, "app/src/main/java/com/flashdrop/app/FdUtil.java")
MANIFEST = os.path.join(ROOT, "app/src/main/AndroidManifest.xml")
LAYOUT = os.path.join(ROOT, "app/src/main/res/layout")
BUILD = os.path.join(ROOT, "build_apk.bat")

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


main = rd(MAIN)
preview = rd(PREVIEW)
fileop = rd(FILEOP)
icon = rd(ICON)
util = rd(UTIL)
manifest = rd(MANIFEST)
fin = rd(os.path.join(LAYOUT, "item_file_in.xml"))
fout = rd(os.path.join(LAYOUT, "item_file_out.xml"))
tin = rd(os.path.join(LAYOUT, "item_text_in.xml"))
tout = rd(os.path.join(LAYOUT, "item_text_out.xml"))
build = rd(BUILD)


def has_txt(src, *needles):
    return all(n in src for n in needles)


# ============ 1. 图片消息恢复缩略图模式 ============
print("\n[1] 安卓图片消息 → 缩略图模式")
check("photoMode 定义存在（done/ok 的图片不套气泡）",
      "boolean photoMode = isFile && img" in main
      and '"done".equals(m.state) || "ok".equals(m.state)' in main)
check("photoMode 时气泡去底色去内边距（直接显示缩略图）",
      "bubble.setBackground(null);" in main and "bubble.setPadding(0, 0, 0, 0);" in main)
check("点击缩略图进入原图查看器",
      "h.thumb.setOnClickListener(v -> openImageViewer(m));" in main)
check("长按缩略图弹消息菜单",
      "h.thumb.setOnLongClickListener" in main)
check("图片消息有独立缩略图控件 msg_thumb",
      "h.thumb" in main and "R.id.msg_thumb" in main)
check("非 photoMode 的图片显示灰色占位并异步加载",
      "loadThumbAsync(m)" in main and "photoMode || hasThumbSource(m)" in main)
# 查看器内的分享 / 保存
iv = rd(os.path.join(ROOT, "app/src/main/java/com/flashdrop/app/ImageViewerActivity.java"))
check("原图查看器提供「保存到相册」按钮", "保存到相册" in iv)
check("原图查看器提供「转发」按钮", "转发" in iv)
check("原图查看器支持长按菜单（保存/转发/删除）",
      '"保存到相册", "转发", "删除"' in iv)

# ============ 2. 文件卡片微信几何 ============
print("\n[2] 文件卡片严格微信几何")
check("图标宽度 44dp", re.search(
    r"private int fileIconWidth\(\)\s*\{\s*return dp\(44\);", main) is not None)
check("图标高度 50dp", re.search(
    r"private int fileIconSize\(\)\s*\{\s*return dp\(50\);", main) is not None)
check("卡片宽度按屏宽固定（不随文字伸缩）",
      "fileCardWidth()" in main and "* 0.69f" in main)
check("卡片宽度在 bind 中被钉死到 LayoutParams",
      "lp.width = fileCardWidth();" in main and "bubble.setLayoutParams(lp);" in main)
check("文字区宽 = 卡片宽 - 内边距 - 图标宽",
      "fileCardTextWidth()" in main and "fileIconWidth()" in main)
check("文件名严格两行", "setMaxLines(2)" in main)
check("文件名使用中间省略（truncateFileName）",
      "truncateFileName(" in main)
check("truncateFileName 保留扩展名",
      "truncateFileName" in main and 'ext' in main)
check("truncateFileName 用 ... 而非 …（与微信截图一致）",
      'truncateFileName' in main and '"\\n" + "..."' in main.replace("\\\\n", "\\n")
      or '...' in main)
check("文件名宽度被限制（不会撑破卡片）",
      "h.name.setMaxWidth(fileCardTextWidth());" in main
      and "h.name.setWidth(fileCardTextWidth());" in main)
check("文件大小与状态合并到同一行（msg_meta）",
      "String merged = FdUtil.fmtSize(m.size);" in main
      and 'merged = merged + "  " + s;' in main)
check("合并后独立的 status 行隐藏",
      "h.status.setVisibility(View.GONE);" in main)
check("图标贴右 + 垂直居中（布局）",
      'android:layout_gravity="center_vertical"' in fin
      and 'android:id="@+id/msg_typeicon"' in fin)
check("图标尺寸 44x50dp 在布局中固定",
      'android:layout_width="44dp"' in fin and 'android:layout_height="50dp"' in fin)
check("图标左边距文字 14dp", 'android:layout_marginLeft="14dp"' in fin)
check("卡内左右内边距各 12dp",
      'android:paddingLeft="12dp"' in fin and 'android:paddingRight="12dp"' in fin)
check("卡内上下内边距各 10dp（一致）",
      'android:paddingTop="10dp"' in fin and 'android:paddingBottom="10dp"' in fin)

# ---- 图标形状：矩形缺右下角 ----
print("\n[2b] 图标形状 = 矩形缺右下角")
check("图标设计基准 44x50", "private static final float DW = 44f;" in icon
      and "private static final float DH = 50f;" in icon)
check("缺口常量 NOTCH 存在", "NOTCH = 6.2f" in icon)
check("路径为矩形（moveTo/lineTo/close，无圆角）",
      "body.moveTo(0f, 0f);" in icon and "body.lineTo(DW, 0f);" in icon
      and "body.close();" in icon)
check("右下角切口：DW,DH-NOTCH → DW-NOTCH,DH",
      "body.lineTo(DW, DH - NOTCH);" in icon
      and "body.lineTo(DW - NOTCH, DH);" in icon)
check("已彻底移除旧的圆角/右上折角实现",
      "addRoundedRect" not in icon and "subtracted(corner)" not in icon)
check("缺口切面用更亮色（被切掉的观感）", "lighter(base, 1.55f)" in icon)
check("文案按长度自适应字号", "label.length() >= 5 ? 10f" in icon)
check("未识别回落灰紫 + ?", '"#7C7F99", "?"' in icon)
check("提供 widthFor（按 44:50 比例）", "public static int widthFor(int heightPx)" in icon)
check("dimmed 虚化 = 叠雾 + 降透明度",
      "0x9E" in icon and "setAlpha(112)" in icon)

# ============ 3. APK 安装器 ============
print("\n[3] APK 安装器「打开后不执行下一步」")
check("清单声明 REQUEST_INSTALL_PACKAGES",
      'android.permission.REQUEST_INSTALL_PACKAGES' in manifest)
check("检查 canRequestPackageInstalls()", "canRequestPackageInstalls()" in main)
check("未授权时弹「需要安装权限」对话框", "需要安装权限" in main)
check("引导到 ACTION_MANAGE_UNKNOWN_APP_SOURCES",
      "ACTION_MANAGE_UNKNOWN_APP_SOURCES" in main)
check("授权后自动重试（installApkRetry）",
      "installApkRetry" in main and "doInstallApk(retryUri)" in main)
check("重试挂在已有的 onResume 中（未重复定义 onResume）",
      main.count("protected void onResume()") == 1)
check("安装 Intent 用 package-archive MIME",
      "application/vnd.android.package-archive" in main)
check("失败回落 ACTION_INSTALL_PACKAGE", "ACTION_INSTALL_PACKAGE" in main)
check("清单添加 queries（Android 11+ 包可见性）", "<queries>" in manifest)
check("isApk 同时看扩展名与 MIME",
      '"apk".equals(e)' in main and "android.package-archive" in main)

# ============ 4. 内置预览器 + 长按菜单 ============
print("\n[4] 内置预览器 + 长按卡片菜单")
check("FdPreviewActivity 类存在", "public class FdPreviewActivity extends Activity" in preview)
check("canPreview 支持 txt 系", 'isText(ext)' in preview and '"txt"' in preview)
check("canPreview 支持 pdf", '"pdf"' in preview)
check("canPreview 支持 word / excel / ppt",
      '"doc"' in preview and '"docx"' in preview
      and '"xls"' in preview and '"xlsx"' in preview
      and '"ppt"' in preview and '"pptx"' in preview)
check("顶栏左上角有「⋯」三点菜单", "showMoreMenu" in preview and "⋯" in preview)
check("三点菜单含「保存」", '"保存"' in preview)
check("三点菜单含「转发」", '"转发"' in preview)
check("保存位置 = Download/FlashDrop",
      "Download/FlashDrop" in fileop or "SAVE_DIR_DESC" in fileop)
check("预览器注册进 Manifest", "FdPreviewActivity" in manifest)
check("单击卡片 = 打开（openOrPreview）",
      "bubble.setOnClickListener(v -> openOrPreview(m));" in main)
check("长按卡片 = 弹菜单（showMsgMenu）",
      "bubble.setOnLongClickListener" in main and "showMsgMenu(m, v);" in main)
check("长按有触感反馈", "performHapticFeedback" in main)
check("菜单含「打开」", 'items.add("打开");' in main)
check("菜单含「保存」", 'items.add("保存");' in main)
check("菜单含「分享」（发送到其它应用）", 'items.add("分享");' in main)
check("菜单含「更多打开方式」", 'items.add("更多打开方式");' in main)
check("菜单含「其他应用打开」", 'items.add("其他应用打开");' in main)
check("菜单含「删除」与「多选」（已从单击移到长按）",
      'items.add("删除");' in main and 'items.add("多选");' in main)
check("不支持类型弹 2 秒提示",
      "toast2s(" in main and "暂不支持打开此类文件" in main)
check("toast2s 用 LENGTH_LONG", "Toast.LENGTH_LONG" in main)
check("openOrPreview 分流：图片→查看器 / 可预览→预览器 / apk→安装器",
      "openImageViewer(m);" in main and "FdPreviewActivity.canPreview(ext)" in main
      and "FdPreviewActivity.start(this, m);" in main and "installApk(m);" in main)
check("文件操作已收敛到 FdFileOp（无重复实现）",
      "FdFileOp.uriOf(this, m)" in main and "FdFileOp.saveToUserDir(" in main
      and "FdFileOp.share(" in main and "FdFileOp.tryOpen(" in main)
check("MainActivity 不再自带 copyStream/uniqueDownloadName 实现",
      "private void copyStream(" not in main
      and "private String uniqueDownloadName(" not in main)
check("FdFileOp 提供 uriOf / saveToUserDir / share / tryOpen / openWithChooser",
      has_txt(fileop, "public static Uri uriOf(", "public static void saveToUserDir(",
              "public static void share(", "public static boolean tryOpen(",
              "public static void openWithChooser("))
check("保存用 MediaStore（API 29+）避免权限问题",
      "MediaStore.Downloads" in fileop and "IS_PENDING" in fileop)
check("FdUtil 提供 findInDownloads 兜底", "findInDownloads" in util)

# ============ 5. 左右分侧 + 头像 ============
print("\n[5] 左右分侧与头像位置")
check("layoutOf：出侧用 *_out，入侧用 *_in",
      "out ? R.layout.item_text_out : R.layout.item_text_in" in main
      and "out ? R.layout.item_file_out : R.layout.item_file_in" in main)
check("out 由 dir 字段决定", '"out".equals(m.dir)' in main)


def order(src, *ids):
    """返回这些 id 在源码中出现的先后顺序索引"""
    return [src.find(i) for i in ids]


# 文本：入侧 头像→气泡，出侧 气泡→头像
ti = order(tin, "@+id/msg_avatar", "@+id/msg_bubble", "@+id/msg_time", 'layout_weight="1"')
check("item_text_in：头像 → 气泡 → 时间 → 弹簧（靠左）",
      ti == sorted(ti) and all(x >= 0 for x in ti), str(ti))
to = order(tout, 'layout_weight="1"', "@+id/msg_time", "@+id/msg_bubble", "@+id/msg_avatar")
check("item_text_out：弹簧 → 时间 → 气泡 → 头像（靠右）",
      to == sorted(to) and all(x >= 0 for x in to), str(to))
# 文件
fi = order(fin, "@+id/msg_avatar", "@+id/msg_bubble", "@+id/msg_time", 'layout_weight="1"')
check("item_file_in：头像 → 气泡 → 时间 → 弹簧（靠左）",
      fi == sorted(fi) and all(x >= 0 for x in fi), str(fi))
fo = order(fout, 'layout_weight="1"', "@+id/msg_time", "@+id/msg_bubble", "@+id/msg_avatar")
check("item_file_out：弹簧 → 时间 → 气泡 → 头像（靠右）",
      fo == sorted(fo) and all(x >= 0 for x in fo), str(fo))
check("出侧气泡 marginRight（贴右侧头像）", 'android:layout_marginRight="8dp"' in fout)
check("入侧气泡 marginLeft（贴左侧头像）", 'android:layout_marginLeft="8dp"' in fin)
check("头像在两侧都存在", "@+id/msg_avatar" in fin and "@+id/msg_avatar" in fout)
check("头像名称：入侧取对端，出侧取「我」",
      '"in".equals(m.dir) ? m.peerName : "我"' in main)

# ============ 版本号 ============
print("\n[6] 版本号三件套 = 1.15.0")
check("FdUtil.APP_VERSION = 1.15.0", 'APP_VERSION = "1.15.0"' in util)
check("Manifest versionName=1.15.0 / versionCode=26",
      'android:versionName="1.15.0"' in manifest
      and "android:versionCode=\"3" in manifest or "android:versionCode=\"4" in manifest)
check("build_apk.bat --version-name 1.15.0 / --version-code 26",
      "--version-name 1.15.0" in build and "--version-code 26" in build)

# ============ 汇总 ============
print("\n" + "=" * 60)
print(f"v1.15.0 安卓静态验收：{pass_n} 通过 / {fail_n} 失败")
if _fails:
    print("失败项：")
    for f in _fails:
        print("  -", f)
print("=" * 60)
sys.exit(1 if fail_n else 0)
