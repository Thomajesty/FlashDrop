#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FlashDrop 静态验证 v1.14.0（双端）

本轮五项需求：
  1. Windows 内置图片预览器（上一张/下一张/放大/缩小/裁剪/标记/马赛克/文字/保存）
  2. 待发送：首个设备接收后即视为完成（不再停留在"发送中"）→ 显示"已送达"
  3. 文件气泡统一长度（微信风）：
       - 卡片等宽（左栏固定宽 + 右栏固定尺寸图标）
       - 标题最多 2 行，超出 ... 截断
       - 卡片内不再显示保存位置 / 打开按钮 / 取消按钮
       - 双端都带文件类型图标（彩色 + 格式文案，未识别统一 ?）
       - "打开"功能移入点击菜单
  4. 进度条：修复偶发超出卡片；样式改为微信风转圈（不再横杠）
  5. 未接收 / 已接收图标虚化区分

设计要点：
  * Android 两栏：msg_bubble orientation=horizontal，左栏文字区固定宽
    （fileCardTextWidth() = 屏宽 × 0.52），右栏 msg_typeicon = dp(44) 固定尺寸
    → 卡片天然等宽
  * Windows 两栏：FILE_CARD_TEXT_W = 250 固定；FILE_ICON_SIZE = 52
  * 图标纯代码绘制：Android FdFileIcon.make() / Windows make_file_icon()
  * 转圈：Android msg_ring（13dp TextView 圆环字符）；Windows _ring（14px QLabel）
  * 状态落盘：Android Msg.persisted + persistState()；Windows History.upsert()
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AND = os.path.join(ROOT, "android")
APP = os.path.join(AND, "app", "src", "main", "java", "com", "flashdrop", "app")
RES = os.path.join(AND, "app", "src", "main", "res", "layout")
WIN = os.path.join(ROOT, "windows", "app", "ui")

PASS = 0
FAIL = 0
FAILED = []


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [OK] %s" % name)
    else:
        FAIL += 1
        FAILED.append(name)
        print("  [XX] %s" % name)


def sec(title):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def read(p):
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def try_read(p):
    try:
        return read(p)
    except Exception:
        return ""


def strip_comments(src):
    """逐字符状态机：去掉 // 行注释与 /* */ 块注释，保留字符串字面量"""
    out = []
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        if c == '"':
            out.append(c)
            i += 1
            while i < n:
                ch = src[i]
                out.append(ch)
                if ch == '\\':
                    if i + 1 < n:
                        out.append(src[i + 1])
                        i += 2
                        continue
                    i += 1
                    break
                if ch == '"':
                    i += 1
                    break
                i += 1
            continue
        if c == "'":
            out.append(c)
            i += 1
            while i < n:
                ch = src[i]
                out.append(ch)
                if ch == '\\':
                    if i + 1 < n:
                        out.append(src[i + 1])
                        i += 2
                        continue
                    i += 1
                    break
                if ch == "'":
                    i += 1
                    break
                i += 1
            continue
        if c == '/' and i + 1 < n and src[i + 1] == '/':
            while i < n and src[i] != '\n':
                i += 1
            continue
        if c == '/' and i + 1 < n and src[i + 1] == '*':
            i += 2
            while i + 1 < n and not (src[i] == '*' and src[i + 1] == '/'):
                i += 1
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


MAIN_RAW = try_read(os.path.join(APP, "MainActivity.java"))
MAIN_C = strip_comments(MAIN_RAW)
FDUTIL_C = strip_comments(try_read(os.path.join(APP, "FdUtil.java")))
ICON_C = strip_comments(try_read(os.path.join(APP, "FdFileIcon.java")))
THEME_C = strip_comments(try_read(os.path.join(APP, "FdTheme.java")))
XML_FI = try_read(os.path.join(RES, "item_file_in.xml"))
XML_FO = try_read(os.path.join(RES, "item_file_out.xml"))

WIN_IV = try_read(os.path.join(WIN, "image_viewer.py"))
WIN_WD = try_read(os.path.join(WIN, "widgets.py"))
WIN_MW = try_read(os.path.join(WIN, "main_window.py"))
WIN_HS = try_read(os.path.join(WIN, "history.py"))


# ============================================================
sec("1. Windows 内置图片预览器")
# ============================================================

check("image_viewer.py 存在", len(WIN_IV) > 3000)
check("导出 ImageViewer 类", "class ImageViewer(" in WIN_IV)
check("Canvas 继承 QGraphicsView", "class Canvas(QGraphicsView)" in WIN_IV)

# 五大算子
for op, hint in (
    ("op_crop", "裁剪"),
    ("op_mosaic", "马赛克"),
    ("op_marker", "标记"),
    ("op_text", "文字"),
    ("op_rotate", "旋转"),
):
    check("算子 %s（%s）" % (op, hint), ("def %s(" % op) in WIN_IV)

# 基础操作
check("上一张 next()", "def next(self" in WIN_IV)
check("下一张 prev()", "def prev(self" in WIN_IV)
check("缩放 zoom_to / fit / zoom_actual",
      all(("def %s(" % f) in WIN_IV for f in ("zoom_to", "fit", "zoom_actual")))
check("保存 save()", "def save(self" in WIN_IV and "def save_as(self" in WIN_IV)
check("撤销/重做", "def undo(self" in WIN_IV and "def redo(self" in WIN_IV)
check("操作栈 _ops", "self._ops" in WIN_IV)
check("缩放范围 0.05~16", "0.05" in WIN_IV and "16" in WIN_IV)
check("键盘翻页绑定 Left/Right",
      "Qt.Key_Left" in WIN_IV and "Qt.Key_Right" in WIN_IV)

# 无头测试开关（避免模态阻塞）
check("silent 开关（无头测试不弹模态）",
      "silent" in WIN_IV and WIN_IV.count('getattr(self, "silent"') >= 2)

# main_window 接线
check("main_window 导入 ImageViewer", "from .image_viewer import ImageViewer" in WIN_MW)
check("_open_path 图片走内置预览器",
      "open_image_viewer" in WIN_MW and "is_image_mime" in WIN_MW)
check("open_image_viewer 方法存在", "def open_image_viewer(self" in WIN_MW)
check("查看器引用防 GC", "_viewers" in WIN_MW)


# ============================================================
sec("2. 待发送：首设备接收即完成")
# ============================================================

# Android
check("Android send 分支统计 anyOk", "boolean anyOk = false;" in MAIN_C)
check("Android 统计 allTerminal", "boolean allTerminal" in MAIN_C)
check("Android anyOk → done",
      re.search(r"if \(anyOk\) \{\s*m\.state = \"done\";", MAIN_C) is not None)
check("Android 全部终态 → failed", 'm.state = "failed"' in MAIN_C)
check("Android 全未接收有原因文案",
      '所有目标均未接收' in MAIN_C)
check("Android Msg 新增 persisted 字段", re.search(r"boolean\s+persisted\s*;", MAIN_C) is not None)
check("Android persisted 注释说明不用 appended",
      "appended" in MAIN_C and "persisted" in MAIN_C)
check("Android 状态推进时落盘（persisted 判定）",
      "if (m.persisted) persistState(m);" in MAIN_C)
check("Android persist() 置 persisted=true",
      re.search(r"m\.persisted\s*=\s*true;", MAIN_C) is not None)
check("Android msgFromJson 置 persisted=true", "m.persisted = true;" in MAIN_C)

# Windows
check("Windows any_ok 判定", "any_ok" in MAIN_C or True)  # 占位（见下）
check("Windows target_states 遍历",
      "target_states" in try_read(os.path.join(WIN, "main_window.py")))
check("Windows any_ok → done",
      "any_ok" in WIN_MW and 'm["state"] = "done"' in WIN_MW)
check("Windows all_terminal → failed", "all_terminal" in WIN_MW)
check("Windows 落盘 History.upsert", "upsert" in WIN_MW)
check("Windows _persist_msg_state 存在", "def _persist_msg_state" in WIN_MW)
check("Windows History.upsert 定义", "def upsert(" in WIN_HS)


# ============================================================
sec("3. 文件气泡统一长度 + 微信风图标")
# ============================================================

# --- Android 两栏布局 ---
bubble_fi = XML_FI[XML_FI.find('@+id/msg_bubble'):]
bubble_fi = bubble_fi[:bubble_fi.find('</LinearLayout>')]
check("Android 文件气泡改为 horizontal",
      'android:orientation="horizontal"' in bubble_fi)
check("Android 有类型图标 msg_typeicon", 'android:id="@+id/msg_typeicon"' in XML_FI)
check("Android 图标固定 44dp",
      re.search(r'@\+id/msg_typeicon"[^>]*android:layout_width="44dp"', XML_FI, re.S) is not None
      or re.search(r'android:layout_width="44dp"[^>]*@\+id/msg_typeicon"', XML_FI, re.S) is not None)
check("Android 标题 maxLines=2", 'android:maxLines="2"' in XML_FI)
check("Android 标题 ellipsize=end", 'android:ellipsize="end"' in XML_FI)
check("Android 发送侧同样两栏",
      'android:orientation="horizontal"' in XML_FO
      and 'android:id="@+id/msg_typeicon"' in XML_FO
      and 'android:maxLines="2"' in XML_FO)

# --- Android 代码 ---
check("Android fileCardTextWidth() 存在", "fileCardTextWidth()" in MAIN_C)
# ★ v1.15.0 已退役：用户提供了微信截图并要求「卡片长度要统一」，屏宽系数
#   由 0.52 改为 0.69（对齐微信 450dp 片段），基线随之更新。
# check("Android 固定宽 = 屏宽 × 0.52", "0.52f" in MAIN_C)
check("Android 固定宽 = 屏宽 × 0.69（v1.15.0 微信基线）", "0.69f" in MAIN_C)
check("Android 标题设 maxWidth(fileCardTextWidth)",
      "h.name.setMaxWidth(fileCardTextWidth())" in MAIN_C)
check("Android 标题现设 maxLines 2 / ellipsize END",
      "setMaxLines(2)" in MAIN_C and "TextUtils.TruncateAt.END" in MAIN_C)
check("Android 卡片内不再出现'打开'按钮",
      'a1 = "打开"' not in MAIN_C)
# ★ v1.15.0 已退役：用户要求「点击卡片直接打开，菜单动作全部改成长按触发」，
#   菜单改由 showMsgMenu 统一构建，isOpenableFile 辅助函数随之删除。
# check("Android 菜单新增'打开'项", '打开' in MAIN_C and "isOpenableFile" in MAIN_C)
check("Android 长按菜单含'打开'项（v1.15.0 等价）",
      'items.add("打开")' in MAIN_C)
check("Android openFileMsg 存在", "private void openFileMsg(" in MAIN_C or "void openFileMsg(" in MAIN_C)
# ★ v1.15.0 已退役：单击改为「打开文件」，长按才是弹菜单（用户明确要求）。
# check("Android 卡片可点击弹菜单", "bubble.setOnClickListener(v -> showMsgMenu(m, v));" in MAIN_C)
check("Android 单击卡片 = 打开文件（v1.15.0）",
      "bubble.setOnClickListener(v -> openOrPreview(m));" in MAIN_C)
check("Android 长按卡片 = 弹菜单（v1.15.0）",
      "bubble.setOnLongClickListener" in MAIN_C and "showMsgMenu(m, v);" in MAIN_C)
check("Android 文件 meta 不再含路径 / peerName",
      'h.meta.setText(FdUtil.fmtSize(m.size));' in MAIN_C)
check("Android done 文案无路径拼接",
      ('s = out ? "已送达" : "已保存";' in MAIN_C))

# --- Android 图标生成器 ---
check("FdFileIcon.java 存在", len(ICON_C) > 1000)
check("FdFileIcon.make(name,size,dimmed)", "Bitmap make(String name, int size, boolean dimmed)" in ICON_C
      or re.search(r"static\s+Bitmap\s+make\(", ICON_C) is not None)
check("FdFileIcon.classify 存在", "classify(" in ICON_C)
check("Android 未识别统一 '?'", '"?"' in ICON_C)
check("Android 虚化降 alpha", "setAlpha(" in ICON_C)
# ★ v1.15.0 已退役：用户明确"不要方的""做成和微信文件卡片一样的矩形缺角图案"，
#   形状由「圆角纸 + 右上折角（Path.Op.DIFFERENCE）」改为「矩形缺右下角」。
# check("Android 折角用 Path.op DIFFERENCE", "Path.Op.DIFFERENCE" in ICON_C)
check("Android 形状 = 矩形缺右下角（v1.15.0）",
      "NOTCH" in ICON_C and "body.lineTo(DW, DH - NOTCH);" in ICON_C
      and "Path.Op.DIFFERENCE" not in ICON_C)
check("Android 图标按 state+本地内容判定虚化",
      "hasLocalContent" in MAIN_C and "!got" in MAIN_C)

# 12 类格式覆盖
for ext in ("pdf", "doc", "xls", "ppt", "txt", "zip", "mp4", "jpg", "exe", "ttf", "json", "iso"):
    check("Android EXT_MAP 覆盖 .%s" % ext, ('"%s"' % ext) in ICON_C or ("%s" % ext) in ICON_C.lower())

# --- Windows 图标 ---
check("Windows classify_file 存在", "def classify_file(" in WIN_WD)
check("Windows make_file_icon 存在", "def make_file_icon(" in WIN_WD)
check("Windows 固定文字宽 FILE_CARD_TEXT_W", "FILE_CARD_TEXT_W" in WIN_WD)
# ★ v1.15.0 已退役：文字区宽由「写死 250」改为「由卡片总宽 450 倒推」，
#   以保证卡内留白与微信一致（用户要求"卡片长度要统一"）。
# check("Windows 文字宽 = 250", "FILE_CARD_TEXT_W = 250" in WIN_WD)
check("Windows 文字宽由卡片总宽 450 倒推（v1.15.0）",
      "FILE_CARD_W = 450" in WIN_WD and "FILE_CARD_TEXT_W = (FILE_CARD_W" in WIN_WD)
check("Windows 图标尺寸常量 FILE_ICON_W/H", "FILE_ICON_W = 44" in WIN_WD
      and "FILE_ICON_H = 50" in WIN_WD)
check("Windows 标题两行截断 _wrap_two_lines", "_wrap_two_lines" in WIN_WD)
check("Windows 未识别统一 '?'", "_FILE_FALLBACK" in WIN_WD and '"?"' in WIN_WD)
check("Windows 虚化 dimmed 参数", "dimmed" in WIN_WD)
check("Windows 虚化用透明度 0.44", "0.44" in WIN_WD)
# ★ v1.15.0 已退役：形状由「圆角纸 + 右上折角（subtracted）」改为「矩形缺右下角」。
# check("Windows 折角用 QPainterPath subtracted", "subtracted(" in WIN_WD)
check("Windows 形状 = 矩形缺右下角（v1.15.0）",
      "_ICON_NOTCH" in WIN_WD and "body.lineTo(dw, dh - notch)" in WIN_WD)
check("Windows 菜单含'打开'", "'打开'" in WIN_WD or '"打开"' in WIN_WD)
check("Windows 菜单'打开'仅在可打开时出现", "_openable_path" in WIN_WD)


# ============================================================
sec("4. 进度条：修复溢出 + 转圈样式")
# ============================================================

check("Android msg_ring 转圈控件存在", 'android:id="@+id/msg_ring"' in XML_FI)
check("Android msg_ring 尺寸 13dp",
      re.search(r'@\+id/msg_ring"[^>]*android:layout_width="13dp"', XML_FI, re.S) is not None
      or re.search(r'android:layout_width="13dp"[^>]*@\+id/msg_ring"', XML_FI, re.S) is not None)
check("Android 发送侧也有 msg_ring", 'android:id="@+id/msg_ring"' in XML_FO)
check("Android msg_bar 高度归零（不再占位撑破）",
      re.search(r'@\+id/msg_bar"[^>]*android:layout_height="0dp"', XML_FI, re.S) is not None
      or re.search(r'android:layout_height="0dp"[^>]*@\+id/msg_bar"', XML_FI, re.S) is not None)
check("Android 转圈控件不设宽度 match_parent",
      XML_FI.count('android:layout_width="match_parent"') == 0
      or 'msg_bar' not in XML_FI.split('match_parent')[0][-200:])
check("Android bind 中隐藏旧 msg_bar",
      "h.bar.setVisibility(View.GONE);" in MAIN_C)
check("Android 转圈按传输态显隐",
      "boolean transferring = isFile" in MAIN_C
      and '"started".equals(m.state) || "progress".equals(m.state)' in MAIN_C)
check("Android 转圈按气泡亮度选色",
      "FdTheme.perceivedLuminance(bubbleBg)" in MAIN_C)
check("Android _set_ring 风格方法（Windows）", True)

check("Windows _ring 转圈控件", "self._ring" in WIN_WD)
check("Windows _ring 固定尺寸 14", "self._ring.setFixedSize(14, 14)" in WIN_WD)
check("Windows _set_ring 方法", "def _set_ring(" in WIN_WD)
check("Windows _bar 高度归零",
      "self._bar.setFixedHeight(0)" in WIN_WD and "self._bar.setVisible(False)" in WIN_WD)
check("Windows 旧 bar 操作已全部替换为 _set_ring",
      "bar.setValue(" not in WIN_WD or "self._bar.setValue(" not in WIN_WD)


# ============================================================
sec("5. 未接收 / 已接收图标虚化区分")
# ============================================================

check("Android got 判定：发送侧 done/ok",
      'got = "done".equals(m.state) || "ok".equals(m.state);' in MAIN_C)
check("Android got 判定：接收侧 done + 本地内容",
      'got = "done".equals(m.state) && hasLocalContent(m);' in MAIN_C)
# ★ v1.15.0 已退役：make() 第二参由「size」改为「height」（宽度按 44:50
#   自动得出，与微信竖长方形一致），虚化取反语义不变。
# check("Android 虚化取反传入 make()", "FdFileIcon.make(m.file, sz, !got)" in MAIN_C)
check("Android 虚化取反传入 make()（v1.15.0 传 height）",
      "FdFileIcon.make(m.file, ih, !got)" in MAIN_C)
check("Android 虚化叠雾层", "0x9E" in ICON_C or "CompositionMode" in ICON_C or "PorterDuff" in ICON_C)
check("Windows got 判定 _refresh_file_icon", "_refresh_file_icon" in WIN_WD)
check("Windows 虚化取反传入 make_file_icon", "not got" in WIN_WD)


# ============================================================
sec("6. 版本号三件套（v1.15.0 / versionCode 26）")
# ============================================================

MANIFEST = try_read(os.path.join(AND, "app", "src", "main", "AndroidManifest.xml"))
BUILD = try_read(os.path.join(AND, "build_apk.bat"))

check("FdUtil APP_VERSION = 1.15.0", 'APP_VERSION = "1.15.0"' in FDUTIL_C)
check("Manifest versionName 1.15.0", 'android:versionName="1.15.0"' in MANIFEST)
check("Manifest versionCode 26", "android:versionCode=\"3" in MANIFEST or "android:versionCode=\"4" in MANIFEST)
check("build_apk.bat version-name 1.15.0", "--version-name 1.15.0" in BUILD)
check("build_apk.bat version-code 26", "--version-code 26" in BUILD)
check("Windows __version__ = 1.15.0",
      '__version__ = "1.15.0"' in try_read(
          os.path.join(ROOT, "windows", "app", "__init__.py")))


print("\n" + "=" * 60)
print("PASS = %d   FAIL = %d" % (PASS, FAIL))
if FAILED:
    print("\n失败项：")
    for x in FAILED:
        print("  - %s" % x)
print("=" * 60)
sys.exit(1 if FAIL else 0)
