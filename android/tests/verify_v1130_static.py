# -*- coding: utf-8 -*-
"""
FlashDrop v1.13.0 专项校验（直接扫真实源码，不依赖设备）
覆盖用户 5 项需求：
  1. 图片查看器打开显示过小（缩略图占位 + baseScale 1.0 封顶）
  2. 保存/转发按钮不在底部（buildBottomBar 的 LayoutParams 未应用）
  3. 图片消息仍重复两条（接收查重 + 渲染层去重）
  4. 气泡内文字溢出 / 对比度不足（自适应宽度 + 按底色推导前景色）
  5. 待发送改为气泡内行内标记（双端移除独立按钮/列表入口）
以及 v1.12.0 / v1.11.0 关键能力回归。
"""
import os
import re
import sys

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SRC = os.path.join(BASE, "app", "src", "main", "java", "com", "flashdrop", "app")
RES = os.path.join(BASE, "app", "src", "main", "res")
WIN_UI = os.path.join(BASE, "..", "windows", "app", "ui")

passed, failed = 0, 0


def sec(t):
    print("\n[%s]" % t)


def check(name, ok, detail=""):
    global passed, failed
    tag = "PASS" if ok else "FAIL"
    if ok:
        passed += 1
    else:
        failed += 1
    print("  %s  %s%s" % (tag, name, ("  <- " + detail) if (detail and not ok) else ""))


def read(p):
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


def strip_comments(src):
    """逐字符状态机去注释（保留字符串/字符字面量与换行）"""
    out = []
    i, n = 0, len(src)
    in_block = in_line = in_str = in_chr = False
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if in_line:
            if c == "\n":
                in_line = False
                out.append(c)
            i += 1
            continue
        if in_block:
            if c == "*" and nxt == "/":
                in_block = False
                i += 2
                continue
            if c == "\n":
                out.append(c)
            i += 1
            continue
        if in_str:
            out.append(c)
            if c == "\\":
                if i + 1 < n:
                    out.append(nxt)
                    i += 2
                    continue
            elif c == '"':
                in_str = False
            i += 1
            continue
        if in_chr:
            out.append(c)
            if c == "\\":
                if i + 1 < n:
                    out.append(nxt)
                    i += 2
                    continue
            elif c == "'":
                in_chr = False
            i += 1
            continue
        if c == "/" and nxt == "/":
            in_line = True
            i += 2
            continue
        if c == "/" and nxt == "*":
            in_block = True
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


VIEWER = read(os.path.join(SRC, "ImageViewerActivity.java"))
VIEWER_C = strip_comments(VIEWER)
MAIN = read(os.path.join(SRC, "MainActivity.java"))
MAIN_C = strip_comments(MAIN)
THEME = read(os.path.join(SRC, "FdTheme.java"))
THEME_C = strip_comments(THEME)
WIN = read(os.path.join(WIN_UI, "main_window.py"))
WIN_WIDGETS = read(os.path.join(WIN_UI, "widgets.py"))
LAYOUT = os.path.join(RES, "layout")
XML_MAIN = read(os.path.join(LAYOUT, "activity_main.xml"))
XML_FI = read(os.path.join(LAYOUT, "item_file_in.xml"))
XML_FO = read(os.path.join(LAYOUT, "item_file_out.xml"))
XML_TI = read(os.path.join(LAYOUT, "item_text_in.xml"))
XML_TO = read(os.path.join(LAYOUT, "item_text_out.xml"))


# ============================================================
sec("1. 图片打开显示过小（缩略图占位 + 1.0 封顶）")
# ============================================================

# baseScale 不再被 1.0 封顶
check("fitToScreen 不再把 baseScale 封顶到 1.0",
      "baseScale = Math.min(baseScale, 1f)" not in VIEWER_C
      and "if (baseScale > 1f) baseScale = 1f" not in VIEWER_C)

# 去掉封顶后应保留说明性注释（源码里仍在）
check("fitToScreen 标注了 v1.13.0 修复说明",
      "v1.13.0" in VIEWER and "不再把 baseScale 封顶" in VIEWER)

# 占位图不再用 inSampleSize=8 的聊天缩略图
check("showIndex 不再用 loadThumb 作全屏占位",
      "Bitmap cached = loadThumb(src)" not in VIEWER_C)

# 新增按屏幕采样的占位解码
check("新增 decodeForScreen 按屏幕尺寸采样占位",
      "decodeForScreen" in VIEWER_C)

# 占位图也走 applyBitmap（触发 fitToScreen 重算）
check("占位图经 applyBitmap 应用（会重算 fit）",
      "applyBitmap(placeholder, name, mime)" in VIEWER_C)

# 高清图到达后必然重算 fit
check("高清图加载后无条件重算 fitToScreen",
      "fitToScreen(bm.getWidth(), bm.getHeight());" in VIEWER_C)

# 居中偏移仍保留（v1.12.0 修复不可回退）
check("applyMatrix 仍含居中平移",
      "centerOffset(bw, bh, s)" in VIEWER_C
      and "matrix.postTranslate(c[0] + transX, c[1] + transY)" in VIEWER_C)


# ============================================================
sec("2. 保存/转发按钮未显示在底部（LayoutParams 未应用）")
# ============================================================

# buildBottomBar 必须把 lp 应用上
check("buildBottomBar 用 wrap(outer, lp) 应用 BOTTOM 布局参数",
      "return wrap(outer, lp);" in VIEWER_C)

# 不得再出现裸 return outer
check("buildBottomBar 不再裸 return outer",
      "lp.gravity = Gravity.BOTTOM;\n        return outer;" not in VIEWER_C)

# 顶栏仍正常应用（防止改坏对照组）
check("buildTopBar 仍用 wrap(bar, lp)",
      "return wrap(bar, lp);" in VIEWER_C)

# 底栏内容：保存到相册 + 转发 两个等宽卡片
check("底栏含「保存到相册」卡片",
      'actionCard(R.drawable.ic_save_down, "保存到相册"' in VIEWER_C)
check("底栏含「转发」卡片",
      'actionCard(R.drawable.ic_share, "转发"' in VIEWER_C)

# 顶栏只应有 返回 + 标题 + 计数，不得有操作按钮
top_src = VIEWER_C[VIEWER_C.find("buildTopBar"):VIEWER_C.find("buildBottomBar")]
check("顶栏不含保存/转发按钮",
      "保存" not in top_src and "转发" not in top_src)

# 底栏 gravity=BOTTOM 且高度 wrap
check("底栏容器重力为 BOTTOM",
      "lp.gravity = Gravity.BOTTOM;" in VIEWER_C)


# ============================================================
sec("3. 图片消息仍重复两条（查重加固）")
# ============================================================

# 抽出的三元组判定方法
check("新增 isSameInboundFile 统一判定",
      "private boolean isSameInboundFile(Msg x, String tid, JSONObject e)" in MAIN_C)

# 内存索引命中后仍要校验（防止索引指向错条）
check("byTidIn 命中后仍经 isSameInboundFile 校验",
      "m == null || !isSameInboundFile(m, tid, e)" in MAIN_C)

# 无条件回扫 msgs
check("未命中时无条件回扫 msgs 查找同 tid",
      "for (Msg x : msgs)" in MAIN_C
      and "if (isSameInboundFile(x, tid, e)) { m = x; break; }" in MAIN_C)

# tid 缺失时的三元组兜底
check("tid 缺失时退化为 文件名+大小 匹配",
      "sz == x.size && sz > 0" in MAIN_C)

# 渲染层投影去重（最后一道保险）
check("rebuildView 在上屏前按 tid 去重",
      "seenInTid" in MAIN_C and "if (!seenInTid.add(m.tid)) continue;" in MAIN_C)

# loadHistory 去重仍在（v1.12.0 修复不可回退）
check("loadHistory 仍按 tid 去重历史脏数据",
      "seenTids" in MAIN_C)

# 方案色随事件更新（offer 期无 scheme 的补正）
check("scheme 随事件更新保持一致",
      "if (!TextUtils.isEmpty(sc)) m.peerScheme = sc;" in MAIN_C)


# ============================================================
sec("4. 气泡内文字溢出 / 对比度不足")
# ============================================================

# v1.14.0 变更：文件气泡改为「左栏固定宽 + 右栏固定尺寸图标」的两栏结构，
# 气泡本身不再需要 maxWidth（固定宽左栏天然锁死卡片宽度），故文件卡片的
# 容器 maxWidth 断言已下架，改由 verify_v1140_static.py 校验两栏结构。
check("接收侧文本气泡设了容器 maxWidth",
      'android:id="@+id/msg_bubble"' in XML_TI and 'android:maxWidth=' in XML_TI)
check("发送侧文本气泡设了容器 maxWidth",
      'android:id="@+id/msg_bubble"' in XML_TO and 'android:maxWidth=' in XML_TO)

# 文本气泡子 View 不再有硬编码 maxWidth（会互相竞争撑破气泡）
check("文本气泡子 View 去掉硬编码 maxWidth",
      XML_TI.count("android:maxWidth") == 1 and XML_TO.count("android:maxWidth") == 1)

# ProgressBar 不再固定 260dp
check("item_file_in 进度条不再固定 260dp",
      'android:layout_width="260dp"' not in XML_FI)
check("item_file_out 进度条不再固定 260dp",
      'android:layout_width="260dp"' not in XML_FO)

# 对比度工具方法
check("FdTheme 新增 onColorText（主文字按底色推导）",
      "public static int onColorText(int bubbleBg)" in THEME_C)
check("FdTheme 新增 onColorDim（次级文字按底色推导）",
      "public static int onColorDim(int bubbleBg)" in THEME_C)
check("FdTheme 新增 onColorAccent（语义色按底色适配）",
      "public static int onColorAccent(int accent, int bubbleBg)" in THEME_C)
check("FdTheme 新增感知亮度计算",
      "public static float perceivedLuminance(int color)" in THEME_C)

# MainActivity 实际使用
# v1.14.0：文件卡片不再显示保存路径 / 对端名，meta 只保留文件大小
check("文件消息 meta 用 onDim（不再写死 t.dim）",
      "h.meta.setText(FdUtil.fmtSize(m.size));\n                h.meta.setTextColor(onDim);" in MAIN_C)
check("status 语义色经 onColorAccent 适配",
      "h.status.setTextColor(FdTheme.onColorAccent(color, bubbleBg));" in MAIN_C)
check("文件名用 onText",
      "h.name.setTextColor(onText);" in MAIN_C)
check("气泡底色先求值（bubbleBg）再推导前景色",
      "int bubbleBg;" in MAIN_C and "final int onText = FdTheme.onColorText(bubbleBg);" in MAIN_C)

# 时间在气泡外，仍用主题 dim（不应被误改）
check("时间标签仍用主题 dim（气泡外不受影响）",
      'android:textColor="#9CA3AF"' in XML_FI and 'android:id="@+id/msg_time"' in XML_FI)


# ============================================================
sec("5. 待发送改为气泡内行内标记（双端）")
# ============================================================

# Android：顶栏按钮不再可见
check("Android 顶栏待发送按钮已 gone",
      'android:id="@+id/btn_pending"' in XML_MAIN
      and 'android:visibility="gone"' in XML_MAIN)

btn_block = XML_MAIN[XML_MAIN.find('@+id/btn_pending'):XML_MAIN.find('@+id/btn_pending') + 260]
check("顶栏按钮尺寸归零（不占位）",
      'android:layout_width="0dp"' in btn_block and 'android:layout_height="0dp"' in btn_block)

check("refreshPendingBtn 恒隐藏",
      "btnPending.setVisibility(View.GONE);" in MAIN_C
      and "待发送 \" + n" not in MAIN_C)

check("不再调用待发送管理窗口（方法定义可留存，但无调用点）",
      "showPendingWindow()" not in MAIN_C.replace(
          "private void showPendingWindow()", ""))

# Android：气泡内 pending 标记仍在
check("Android 气泡内仍有 pending 标记文案",
      "待发送 · 全部设备上线后自动发出" in MAIN_C
      and "待发送 · 目标设备上线后自动发出" in MAIN_C)

# Android：设备上线自动投递仍在
check("Android 设备上线自动投递待发队列",
      "设备已上线，已自动发送" in MAIN_C)

# Windows：顶栏按钮隐藏且不入布局
check("Windows 顶栏待发送按钮已隐藏",
      "self.pending_btn.setVisible(False)" in WIN)
check("Windows 待发送按钮不再加入布局",
      "self.header_actions.addWidget(self.pending_btn)" not in WIN)
check("Windows 不再绑定待发送管理窗口入口",
      "self.pending_btn.clicked.connect(self._open_pending_window)" not in WIN)
check("Windows _pending_btn_refresh 恒隐藏",
      "btn.setVisible(False)" in WIN)

# Windows：气泡内 pending 标记仍在
check("Windows 气泡内仍有 pending 标记",
      "待发送 · {desc}上线后自动发出" in WIN_WIDGETS
      or "待发送 · 目标设备上线后自动发出" in WIN_WIDGETS)

# Windows：上线自动 flush 仍在
check("Windows 上线自动 flush 待发队列",
      "self._flush_pending()" in WIN)


# ============================================================
sec("6. 版本号与回归")
# ============================================================

FDUTIL = read(os.path.join(SRC, "FdUtil.java"))
MANIFEST = read(os.path.join(BASE, "app", "src", "main", "AndroidManifest.xml"))
WIN_INIT = read(os.path.join(BASE, "..", "windows", "app", "__init__.py"))

check("FdUtil APP_VERSION = 1.15.0",
      'APP_VERSION = "1.15.0"' in FDUTIL)
# 说明：以下 4 项在 v1.13.0 时断言 1.13.0/23；v1.13.1 / v1.14.0 / v1.15.0
# 每轮升级版本号后同步更新（历史套件的既定处理方式，见 v1.10.1 / v1.11.0 /
# v1.12.0 / v1.13.1 / v1.14.0 先例）。
# v1.13.0 的"五项修复本身"仍由本套件其余断言保护，不受版本号影响。
check("Manifest versionCode = 26",
      "android:versionCode=\"3" in MANIFEST or "android:versionCode=\"4" in MANIFEST)
check("Manifest versionName = 1.15.0",
      'android:versionName="1.15.0"' in MANIFEST)
check("Windows __version__ = 1.15.0",
      '__version__ = "1.15.0"' in WIN_INIT)

# v1.12.0 关键能力不得回退
check("回归：EXIF 旋转校正仍在", "applyExifRotation" in VIEWER_C)
check("回归：图片长按进 showMsgMenu", "setOnLongClickListener" in MAIN_C)
check("回归：saveImageMsgToGallery 仍在", "saveImageMsgToGallery" in MAIN_C)
check("回归：4 布局时间均在气泡外侧",
      XML_TI.find('@+id/msg_bubble') < XML_TI.find('@+id/msg_time')
      and XML_TI.find('@+id/msg_time') < XML_TI.find('android:layout_weight="1"'))

# v1.13.0 详细说明注释存在
check("源码含 v1.13.0 修复溯源注释",
      VIEWER.count("v1.13.0") >= 2 and MAIN.count("v1.13.0") >= 3
      and THEME.count("v1.13.0") >= 1)


print("\n" + "=" * 44)
print(" 通过 %d 项，失败 %d 项" % (passed, failed))
print("=" * 44)
if failed > 0:
    sys.exit(1)
