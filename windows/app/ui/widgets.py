# -*- coding: utf-8 -*-
"""聊天气泡与通用小组件"""

import os

from PySide6.QtCore import Qt, Signal, QSize, QRectF, QUrl, QMimeData, QPointF
from PySide6.QtGui import (QPixmap, QPainter, QColor, QFont, QLinearGradient,
                           QBrush, QPen, QFontMetrics, QGuiApplication, QDesktopServices,
                           QImageReader, QPainterPath, QDrag)
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel,
                               QPushButton, QProgressBar, QMenu, QSizePolicy,
                               QCheckBox, QGraphicsDropShadowEffect, QApplication)

from .. import util
from .theme import ACCENT, ACCENT2, RED, GREEN, BUBBLE_SCHEMES

AVATAR_COLORS = [QColor("#3b82f6"), QColor("#8b5cf6"), QColor("#ec4899"),
                 QColor("#f59e0b"), QColor("#10b981"), QColor("#06b6d4"),
                 QColor("#ef4444"), QColor("#84cc16")]

# ★ v1.18.17 性能：头像 / 平台徽标 / 缩略图缓存
#   这三个都是"同样的入参 → 同样的位图"，却每次都重新用 QPainter 画一遍
#   （或把整张大图解码一遍）。切设备 / 收到消息都会重建气泡，于是反复重做。
#   实测 make_avatar 单次约 0.11ms，10 个设备每次列表重建要多花 1.3ms；
#   缩略图更贵 —— 一张 12MP 照片解码要 100~300ms。
_AVATAR_CACHE = {}
_BADGE_CACHE = {}
_THUMB_CACHE = {}
_THUMB_CACHE_MAX = 160
# ★ v1.18.18 性能 P0：文件图标缓存（同一扩展名+尺寸+灰化态每次都重画一遍
#   QPainterPath，切设备重建 200 条气泡时浪费明显）
_ICON_CACHE = {}
# ★ v1.18.18 性能 P0：QSS 字符串按主题缓存 —— setStyleSheet 每次都要
#   重新 parse，200 条气泡建页时同样格式化 + parse 200 次
_QSS_CACHE = {}
# 缩略图磁盘缓存目录（懒创建）；命中可跳过整个解码过程
_THUMB_DISK_DIR = None


def _bubble_qss(bg: str, fg: str) -> str:
    """★ v1.18.18 性能 P0：文本气泡 QSS 按配色缓存。

    setStyleSheet 每次都要重新 parse；同一配色 200 条气泡建页时
    格式化 + parse 各做 200 次，缓存后命中即零成本。
    key 取 (bg, fg) —— 主题切换后配色不同自动 miss。
    """
    k = (bg, fg)
    hit = _QSS_CACHE.get(k)
    if hit is not None:
        return hit
    qss = (f"background: {bg}; color: {fg};"
           " border-radius: 12px; padding: 8px 12px; font-size: 14px;")
    if len(_QSS_CACHE) >= 64:
        _QSS_CACHE.clear()
    _QSS_CACHE[k] = qss
    return qss


def _thumb_disk_dir():
    global _THUMB_DISK_DIR
    if _THUMB_DISK_DIR is None:
        try:
            from ..config import app_data_dir
            d = os.path.join(app_data_dir(), "thumbs")
            os.makedirs(d, exist_ok=True)
            _THUMB_DISK_DIR = d
        except Exception:
            _THUMB_DISK_DIR = ""
    return _THUMB_DISK_DIR


def _thumb_disk_key(src, mtime, size, box):
    """缩略图磁盘文件名：源路径+时间+大小+盒尺寸的 md5。

    mtime/size 参与 key —— 源文件被覆盖后旧缩略图自动失效（不删旧文件，
    由 GC 周期清理），不会展示过期内容。
    """
    import hashlib
    h = hashlib.md5(f"{src}|{mtime}|{size}|{box}".encode("utf-8", "ignore"))
    return h.hexdigest()


def _thumb_gc(days=30):
    """清理超过 days 天未访问的磁盘缩略图（启动后空闲调用一次）"""
    d = _thumb_disk_dir()
    if not d:
        return
    import time as _t
    cutoff = _t.time() - days * 86400
    try:
        for fn in os.listdir(d):
            if not fn.endswith(".png"):
                continue
            p = os.path.join(d, fn)
            try:
                if os.path.getmtime(p) < cutoff:
                    os.remove(p)
            except OSError:
                pass
    except OSError:
        pass


def _cache_put(cache: dict, key, val, cap=256):
    """简单容量上限的缓存（超出就整体清空，避免 LRU 维护开销）"""
    if len(cache) >= cap:
        cache.clear()
    cache[key] = val
    return val


def make_thumb(src, box=300):
    """按需缩放解码 + 缓存的图片缩略图。

    ★ v1.18.17：原来是「完整解码整张图 → 再缩放到 300px」，
    一张手机照片（4000x3000）要解码 1200 万像素，100~300ms 一张，
    会话里几张照片就能把界面拖到卡顿。

    现在两处优化：
      ① 用 QImageReader.setScaledSize() 让 Qt **按目标尺寸解码**，
         不再把整张大图解进内存（解码量降 1~2 个数量级）
      ② 按 (路径, mtime, 大小) 缓存，切设备/重绘直接命中
    """
    if not src:
        return QPixmap()
    try:
        st = os.stat(src)
        key = (str(src), int(st.st_mtime), int(st.st_size), int(box))
    except Exception:
        key = (str(src), 0, 0, int(box))
    hit = _THUMB_CACHE.get(key)
    if hit is not None:
        return hit
    # ★ v1.18.18 性能 P0：二级磁盘缓存 —— 重启后滚动到图片消息
    #   不再重新解码（冷路径 100~300ms/张 → 读一个小 png ~1ms）
    import hashlib
    dkey = _thumb_disk_key(*key)
    d = _thumb_disk_dir()
    if d:
        try:
            dp = os.path.join(d, dkey + ".png")
            if os.path.isfile(dp):
                pm = QPixmap(dp)
                if not pm.isNull():
                    return _cache_put(_THUMB_CACHE, key, pm, _THUMB_CACHE_MAX)
        except Exception:
            pass
    try:
        reader = QImageReader(str(src))
        reader.setAutoTransform(True)
        sz = reader.size()
        if sz.isValid() and sz.width() > 0 and sz.height() > 0:
            sc = min(float(box) / sz.width(), float(box) / sz.height(), 1.0)
            if sc < 1.0:
                reader.setScaledSize(QSize(max(1, int(sz.width() * sc)),
                                           max(1, int(sz.height() * sc))))
        pm = reader.read()
        pm = QPixmap.fromImage(pm)
    except Exception:
        pm = QPixmap()
    if pm.isNull():
        try:
            pm = QPixmap(str(src))
            if not pm.isNull():
                pm = pm.scaled(box, box, Qt.KeepAspectRatio,
                               Qt.SmoothTransformation)
        except Exception:
            pm = QPixmap()
    # ★ 解码成功才写磁盘缓存（原子写：tmp + replace）
    if not pm.isNull() and d:
        try:
            dp = os.path.join(d, dkey + ".png")
            tmp = dp + ".tmp"
            if pm.save(tmp, "PNG"):
                try:
                    os.replace(tmp, dp)
                except OSError:
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
        except Exception:
            pass
    return _cache_put(_THUMB_CACHE, key, pm, _THUMB_CACHE_MAX)


def make_avatar(name: str, seed: str, size=40) -> QPixmap:
    # ★ v1.18.17：加缓存（同样的 name/seed/size → 同样的位图，不必重画）
    key = (name or "?", seed or name or "?", int(size))
    hit = _AVATAR_CACHE.get(key)
    if hit is not None:
        return hit
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    h = sum(ord(c) for c in (seed or name or "?"))
    c1 = AVATAR_COLORS[h % len(AVATAR_COLORS)]
    c2 = AVATAR_COLORS[(h + 3) % len(AVATAR_COLORS)]
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0, c1)
    grad.setColorAt(1, c2)
    p.setBrush(QBrush(grad))
    p.setPen(Qt.NoPen)
    p.drawEllipse(0, 0, size, size)
    ch = (name or "?")[0].upper()
    p.setPen(QColor("white"))
    f = QFont("Microsoft YaHei UI")
    f.setPixelSize(int(size * 0.45))
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, ch)
    p.end()
    return _cache_put(_AVATAR_CACHE, key, pm)


def make_platform_badge(platform: str, size=14) -> QPixmap:
    # ★ v1.18.17：加缓存
    key = (platform or "?", int(size))
    hit = _BADGE_CACHE.get(key)
    if hit is not None:
        return hit
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    if platform == "android":
        p.setPen(QPen(QColor("#3ddc84"), 2))
    else:
        p.setPen(QPen(QColor("#60a5fa"), 2))
    # 简笔：手机/电脑
    if platform == "android":
        p.drawRoundedRect(4, 1, size - 8, size - 2, 2, 2)
    else:
        p.drawRoundedRect(1, 2, size - 2, size - 7, 2, 2)
        p.drawLine(3, size - 2, size - 3, size - 2)
    p.end()
    return _cache_put(_BADGE_CACHE, key, pm)


# ============================================================
# 文件类型图标（v1.14.0）—— 微信风格，与 Android 端 FdFileIcon 同一套规则
# ============================================================

# 扩展名 → (底色, 文案)；与安卓端保持一致，改一处要同步另一处
_FILE_EXT_MAP = {
    # 文档
    "pdf": ("#E8453C", "PDF"),
    "doc": ("#2B579A", "DOC"), "docx": ("#2B579A", "DOC"),
    "rtf": ("#2B579A", "DOC"), "odt": ("#2B579A", "DOC"),
    "wps": ("#2B579A", "DOC"),
    "xls": ("#217346", "XLS"), "xlsx": ("#217346", "XLS"),
    "csv": ("#217346", "XLS"), "ods": ("#217346", "XLS"),
    "et": ("#217346", "XLS"),
    "ppt": ("#D24726", "PPT"), "pptx": ("#D24726", "PPT"),
    "odp": ("#D24726", "PPT"), "dps": ("#D24726", "PPT"),
    # 文本 / 代码
    "txt": ("#5B6B8C", "TXT"), "log": ("#5B6B8C", "TXT"),
    "md": ("#5B6B8C", "TXT"), "ini": ("#5B6B8C", "TXT"),
    "conf": ("#5B6B8C", "TXT"), "json": ("#5B6B8C", "TXT"),
    "xml": ("#5B6B8C", "TXT"), "yml": ("#5B6B8C", "TXT"),
    "yaml": ("#5B6B8C", "TXT"), "bat": ("#5B6B8C", "TXT"),
    "sh": ("#5B6B8C", "TXT"), "java": ("#5B6B8C", "TXT"),
    "py": ("#5B6B8C", "TXT"), "js": ("#5B6B8C", "TXT"),
    "html": ("#5B6B8C", "TXT"), "css": ("#5B6B8C", "TXT"),
    # 图片
    "jpg": ("#0E9F6E", "IMG"), "jpeg": ("#0E9F6E", "IMG"),
    "png": ("#0E9F6E", "IMG"), "gif": ("#0E9F6E", "IMG"),
    "bmp": ("#0E9F6E", "IMG"), "webp": ("#0E9F6E", "IMG"),
    "heic": ("#0E9F6E", "IMG"), "heif": ("#0E9F6E", "IMG"),
    "tif": ("#0E9F6E", "IMG"), "tiff": ("#0E9F6E", "IMG"),
    "svg": ("#0E9F6E", "IMG"), "ico": ("#0E9F6E", "IMG"),
    # 音视频
    "mp4": ("#7C3AED", "MEDIA"), "mkv": ("#7C3AED", "MEDIA"),
    "avi": ("#7C3AED", "MEDIA"), "mov": ("#7C3AED", "MEDIA"),
    "wmv": ("#7C3AED", "MEDIA"), "flv": ("#7C3AED", "MEDIA"),
    "webm": ("#7C3AED", "MEDIA"), "mp3": ("#7C3AED", "MEDIA"),
    "wav": ("#7C3AED", "MEDIA"), "flac": ("#7C3AED", "MEDIA"),
    "aac": ("#7C3AED", "MEDIA"), "m4a": ("#7C3AED", "MEDIA"),
    # 压缩包
    "zip": ("#B45309", "ZIP"), "rar": ("#B45309", "ZIP"),
    "7z": ("#B45309", "ZIP"), "tar": ("#B45309", "ZIP"),
    "gz": ("#B45309", "ZIP"), "xz": ("#B45309", "ZIP"),
    # 程序 / 安装包
    # ★ v1.16.0：apk 单独一类（安卓绿 + APK），不再和 exe 混在一起。
    # 旧版把 apk 也标成 EXE，用户实测反馈"apk 也标注的 exe 文件图标"。
    "apk": ("#3DDC84", "APK"),
    "exe": ("#0F6FCB", "EXE"), "msi": ("#0F6FCB", "EXE"),
    "ipa": ("#0F6FCB", "EXE"), "dmg": ("#0F6FCB", "EXE"),
    "deb": ("#0F6FCB", "EXE"),
    # 字体 / 数据库 / 镜像
    "ttf": ("#6D28D9", "FONT"), "otf": ("#6D28D9", "FONT"),
    "woff": ("#6D28D9", "FONT"), "woff2": ("#6D28D9", "FONT"),
    "db": ("#0F766E", "DB"), "sqlite": ("#0F766E", "DB"),
    "sql": ("#0F766E", "DB"), "mdb": ("#0F766E", "DB"),
    "iso": ("#475569", "ISO"), "vhd": ("#475569", "ISO"),
    "vmdk": ("#475569", "ISO"),
}
_FILE_FALLBACK = ("#6D7588", "?")

#: 文件图标设计基准（与安卓端 FdFileIcon 保持同规格）
#: 宽 40 / 高 52 → 宽高比 ≈ 0.77（实测微信截图）
_ICON_DW = 40.0
_ICON_DH = 52.0
#: 圆角半径（占宽度 12%）
_ICON_RADIUS = 4.8
#: 右上折角边长（占宽度 38%）
_ICON_FOLD = 15.2
#: 虚线描边线宽
_ICON_STROKE = 2.6


def _lighter(color: QColor, f: float) -> QColor:
    """按比例调亮，保持 alpha（与安卓端 FdFileIcon.scale 一致）"""
    return QColor(min(255, int(color.red() * f)),
                  min(255, int(color.green() * f)),
                  min(255, int(color.blue() * f)),
                  color.alpha())


def classify_file(name: str):
    """返回 (底色, 文案)；未识别返回统一问号样式"""
    ext = os.path.splitext(name or "")[1].lstrip(".").lower()
    if not ext or len(ext) > 8 or not ext.isalnum():
        return _FILE_FALLBACK
    return _FILE_EXT_MAP.get(ext, _FILE_FALLBACK)


def _file_icon_key(name: str, height: int, dimmed: bool):
    """图标缓存 key：只取扩展名（不同文件名的 PDF 图标画出来完全一样）"""
    try:
        dot = name.rfind(".")
        ext = (name[dot + 1:] if dot >= 0 else "").upper()[:5]
    except Exception:
        ext = ""
    return (ext, int(height), bool(dimmed))


def make_file_icon(name: str, height: int = 52, dimmed: bool = False) -> QPixmap:
    """★ v1.18.18 性能 P0：带缓存的文件图标。

    同一 (扩展名, 高度, 灰化态) 的图标画出来完全一样 —— 200 条气泡建页
    会把同一个 PDF 图标重画几十遍。绘制逻辑在 _paint_file_icon（原实现）。
    """
    key = _file_icon_key(name, height, dimmed)
    hit = _ICON_CACHE.get(key)
    if hit is not None:
        return hit
    pm = _paint_file_icon(name, height, dimmed)
    if not pm.isNull():
        _cache_put(_ICON_CACHE, key, pm, 128)
    return pm


def _paint_file_icon(name: str, height: int = 52, dimmed: bool = False) -> QPixmap:
    """文件类型图标（v1.16.0）—— 与安卓端 FdFileIcon 严格同规格。

    ── 形状（本版核心修正）─────────────────────────────────────
    前两版都画错了：
      v1.14.0「圆角纸张 + 右上折角」→ 反馈"不要方的"
      v1.15.0「矩形 + 右下切角」    → 仍不对，微信根本不是缺角造型

    本轮拿到清晰的微信「文件传输助手」截图（1440x3088，密度 2.2x）后
    逐像素比对，确认真实造型是：

        ┌──────────┐
        │          ╲      ← **右上角**切掉直角三角（折角）
        │   PDF     │
        │           │
        └───────────┘      ← 整体小圆角

      ① 主体 = 圆角矩形（圆角 ≈ 宽度 12%）
      ② **右上角**切掉直角三角，切口边长 ≈ 宽度 38%
      ③ 折角区域用略亮同色系填充，形成"纸张折起"层次
      ④ 中央白色粗体格式文案（PDF / DOC / XLS …）

    ── 未下载态的区分（也是本版修正）───────────────────────────
    微信的做法**不是把图标变半透明**，而是画成**同色系虚线描边**：
      · 已下载 → 实色填充 + 白色文字
      · 未下载 → 虚线空心轮廓 + 实色文字

    ── 尺寸 ───────────────────────────────────────────────────
    设计基准 40x52（宽高比 ≈ 0.77）。传入 height 为像素高，
    宽度自动按比例得出 —— 与安卓端 widthFor() 完全一致。
    """
    height = max(8, int(height))
    width = max(8, int(round(height * _ICON_DW / _ICON_DH)))

    pm = QPixmap(width, height)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)

    base_hex, label = classify_file(name)
    base = QColor(base_hex)
    k = height / _ICON_DH
    p.scale(k, k)

    dw, dh = _ICON_DW, _ICON_DH
    r, fold = _ICON_RADIUS, _ICON_FOLD

    # ---- 主体路径：圆角矩形，右上角切掉直角三角 ----
    body = QPainterPath()
    body.moveTo(r, 0.0)
    body.lineTo(dw - fold, 0.0)          # 上边到折角处
    body.lineTo(dw, fold)                # 折角斜边
    body.lineTo(dw, dh - r)              # 右边
    body.quadTo(dw, dh, dw - r, dh)      # 右下圆角
    body.lineTo(r, dh)                   # 下边
    body.quadTo(0.0, dh, 0.0, dh - r)    # 左下圆角
    body.lineTo(0.0, r)                  # 左边
    body.quadTo(0.0, 0.0, r, 0.0)        # 左上圆角
    body.closeSubpath()

    # ---- 折角小三角（比主体略亮，形成"纸张折起"层次）----
    fold_tri = QPainterPath()
    fold_tri.moveTo(dw - fold, 0.0)
    fold_tri.lineTo(dw, fold)
    fold_tri.lineTo(dw - fold, fold)
    fold_tri.closeSubpath()

    if dimmed:
        # ★ 未下载态：微信画的是**虚线描边**，不是半透明实心。
        pen = QPen(base)
        pen.setWidthF(_ICON_STROKE)
        pen.setCapStyle(Qt.RoundCap)
        # 虚线段 ≈ 4.5，间隔 ≈ 2.6
        pen.setDashPattern([4.5 / _ICON_STROKE, 2.6 / _ICON_STROKE])
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(body)
        p.drawLine(QPointF(dw - fold, 0.0), QPointF(dw, fold))
    else:
        p.setPen(Qt.NoPen)
        p.setBrush(base)
        p.drawPath(body)
        p.setBrush(_lighter(base, 1.45))
        p.drawPath(fold_tri)

    # ---- 格式文案：居中略偏下（避开右上折角）----
    p.setPen(base if dimmed else QColor("#FFFFFF"))
    f = QFont("Microsoft YaHei UI")
    # 字号与安卓端 FdFileIcon.make() 一一对应（同基准 → 等比缩放）
    if label == "?":
        f.setPixelSize(int(round(22 * k)))
    elif len(label) >= 5:
        f.setPixelSize(int(round(9 * k)))
    elif len(label) == 4:
        f.setPixelSize(int(round(10.5 * k)))
    elif len(label) == 3:
        f.setPixelSize(int(round(12.5 * k)))
    else:
        f.setPixelSize(int(round(15 * k)))
    f.setBold(True)
    p.setFont(f)
    # 与安卓端 cyc = DH/2 + 3 一致：矩形整体下移 3（相对中心）
    p.drawText(QRectF(0, 6, dw, dh - 6), Qt.AlignCenter, label)
    p.end()
    return pm


class ElidedLabel(QLabel):
    """超长文本省略号显示，悬停 tooltip 全文"""
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._full = text

    def setText(self, text):
        self._full = text
        super().setText(text)
        self._elide()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._elide()

    def _elide(self):
        fm = QFontMetrics(self.font())
        elided = fm.elidedText(self._full, Qt.ElideMiddle, self.width())
        super().setText(elided)
        self.setToolTip(self._full if self._full != elided else "")


class BubbleFrame(QWidget):
    """一条消息的行：头像 + 气泡（支持多选、右键菜单、方案配色）"""
    openRequested = Signal(str)
    folderRequested = Signal(str)
    cancelRequested = Signal(str)
    acceptRequested = Signal(str)
    rejectRequested = Signal(str)
    resendRequested = Signal(dict)
    selectToggled = Signal(object, bool)   # (msg, checked)
    deleteRequested = Signal(object)       # msg
    multiSelectRequested = Signal(object)  # msg（进入多选并预选中）
    openLinkRequested = Signal(str)        # 打开消息中的链接
    cancelPendingRequested = Signal(object)  # 取消待发送（msg）
    # ★ v1.15.0：文件卡片菜单新增动作（与安卓端对齐）
    saveRequested = Signal(str)            # 另存到 Download/FlashDrop
    forwardRequested = Signal(str)         # 转发到其它应用
    # ★ v1.16.0：图片相关动作
    # ★ v1.17.0：editImageRequested 已废弃（用户要求删除"编辑"入口，
    #   它与"打开"完全重复）。保留信号名以免历史连接处 ImportError，
    #   但不再有任何菜单项会触发它。
    editImageRequested = Signal(str)       # [v1.17.0 起不再使用]
    copyImageRequested = Signal(str)       # 复制图片到剪贴板
    saveImageAsRequested = Signal(str)     # 图片另存为
    # ★ v1.17.0：用系统「打开方式」对话框选择其它应用打开
    openWithRequested = Signal(str)
    # ★ v1.16.0：把图片拖出到外部（文件夹 / 其它聊天软件）
    imageDragStarted = Signal(str)

    def __init__(self, msg: dict, theme: dict, parent=None):
        super().__init__(parent)
        self.msg = msg
        self.t = theme
        self.out = msg.get("dir") == "out"
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        root = QHBoxLayout(self)
        root.setContentsMargins(12, 3, 12, 3)
        root.setSpacing(8)

        # 多选框（多选模式显示）
        self.select_box = QCheckBox()
        self.select_box.setVisible(False)
        self.select_box.toggled.connect(
            lambda on: self.selectToggled.emit(self.msg, on))
        root.addWidget(self.select_box)

        self.avatar = QLabel()
        self.avatar.setFixedSize(40, 40)
        name = msg.get("peer_name") or msg.get("name") or "?"
        seed = msg.get("peer_id", name)
        self.avatar.setPixmap(make_avatar(name, seed))

        # 气泡内容：按内容自适应宽度（不拉伸），靠近发送方头像
        self.content = QWidget()
        self.content.setLayout(QVBoxLayout())
        self.content.layout().setContentsMargins(1, 1, 1, 1)
        self.content.layout().setSpacing(2)
        if self.out:
            root.addStretch(1)
            root.addWidget(self.content, 0, Qt.AlignBottom)
            root.addWidget(self.avatar)
        else:
            root.addWidget(self.avatar)
            root.addWidget(self.content, 0, Qt.AlignBottom)
            root.addStretch(1)
        self._select_mode = False
        self._wired = set()
        self._rebuild_content()

    def _rebuild_content(self):
        lay = self.content.layout()
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        lay.addWidget(self._make_bubble())
        self._install_menu_policy()

    def _install_menu_policy(self):
        """给所有子控件挂接右键菜单（子控件事件不总是传播到父级）"""
        for w in self.findChildren(QWidget):
            if id(w) in self._wired:
                continue
            self._wired.add(id(w))
            w.setContextMenuPolicy(Qt.CustomContextMenu)
            w.customContextMenuRequested.connect(
                lambda pos, c=w: self._show_menu(c, pos))

    def _show_menu(self, widget, pos):
        if self._select_mode:
            return
        m = QMenu(self)
        url = util.first_url(self.msg.get("text", "")) \
            if self.msg.get("kind") == "text" else None
        act_open_link = m.addAction("打开链接") if url else None
        act_copy_link = m.addAction("复制链接") if url else None
        if url:
            m.addSeparator()
        act_copy = None
        if self.msg.get("kind") == "text":
            # 有局部选中时优先复制所选内容
            sel = ""
            try:
                sel = self._text_lbl.selectedText() if self._text_lbl else ""
            except Exception:
                sel = ""
            if sel:
                act_copy = m.addAction("复制所选")
            else:
                act_copy = m.addAction("复制")
        # ★ v1.15.0：文件卡片菜单与安卓端对齐 ——
        #   打开 / 保存（另存到 Download/FlashDrop）/ 转发（发到其它应用）/
        #   在文件夹中显示 / 删除 / 多选
        act_open_file = None
        act_save_file = None
        act_forward_file = None
        act_reveal_file = None
        # ★ v1.17.0：图片消息专属动作。
        # 用户反馈「电脑版的图片 右击功能 打开 和 编辑是重复的，把编辑删除掉」——
        # 原菜单里「打开」走内置查看器、「编辑图片」也走同一个内置查看器，
        # 两条入口完全等价，确实重复。本轮删除「编辑图片」入口。
        # 同时用户要求「在另存为前增加 其他应用打开功能」→ 新增 act_open_with。
        act_open_with = None
        act_copy_image = None
        act_saveas_image = None
        is_image_msg = (self.msg.get("kind") == "file"
                        and util.is_image_mime(self.msg.get("mime", "") or ""))
        if self.msg.get("kind") == "file":
            p = self._openable_path()
            if p:
                act_open_file = m.addAction("打开")
                act_save_file = m.addAction("保存")
                act_forward_file = m.addAction("转发")
                act_reveal_file = m.addAction("在文件夹中显示")
            if is_image_msg:
                m.addSeparator()
                if p:
                    act_copy_image = m.addAction("复制图片")
                    # ★ v1.17.0：放在「另存为」之前（用户指定的顺序）
                    act_open_with = m.addAction("其他应用打开…")
                    act_saveas_image = m.addAction("图片另存为…")
            m.addSeparator()
        act_multi = m.addAction("多选")
        act_del = m.addAction("删除")
        chosen = m.exec(widget.mapToGlobal(pos))
        if chosen is None:
            return
        if act_open_file is not None and chosen == act_open_file:
            self.openRequested.emit(self._openable_path())
            return
        if act_save_file is not None and chosen == act_save_file:
            self.saveRequested.emit(self._openable_path())
            return
        if act_forward_file is not None and chosen == act_forward_file:
            self.forwardRequested.emit(self._openable_path())
            return
        if act_reveal_file is not None and chosen == act_reveal_file:
            self.folderRequested.emit(self._openable_path())
            return
        # ★ v1.17.0：图片动作分发（「编辑图片」已按用户要求移除）
        if act_copy_image is not None and chosen == act_copy_image:
            self.copyImageRequested.emit(self._openable_path())
            return
        if act_open_with is not None and chosen == act_open_with:
            self.openWithRequested.emit(self._openable_path())
            return
        if act_saveas_image is not None and chosen == act_saveas_image:
            self.saveImageAsRequested.emit(self._openable_path())
            return
        if act_open_link is not None and chosen == act_open_link:
            self.openLinkRequested.emit(url)
            return
        if act_copy_link is not None and chosen == act_copy_link:
            QGuiApplication.clipboard().setText(url)
            return
        if act_copy is not None and chosen == act_copy:
            text = self.msg.get("text", "")
            try:
                if self._text_lbl and self._text_lbl.selectedText():
                    text = self._text_lbl.selectedText()
            except Exception:
                pass
            QGuiApplication.clipboard().setText(text)
        elif chosen == act_multi:
            self.multiSelectRequested.emit(self.msg)
        elif chosen == act_del:
            self.deleteRequested.emit(self.msg)

    # 事件级兜底：直接落在 BubbleFrame 上的右键
    def contextMenuEvent(self, e):
        self._show_menu(self, e.globalPos())
        e.accept()

    def set_select_mode(self, on: bool):
        self._select_mode = on
        self.select_box.setVisible(on)
        if not on:
            self.select_box.blockSignals(True)
            self.select_box.setChecked(False)
            self.select_box.blockSignals(False)

    def set_checked(self, on: bool):
        self.select_box.blockSignals(True)
        self.select_box.setChecked(on)
        self.select_box.blockSignals(False)

    def _make_bubble(self) -> QWidget:
        kind = self.msg.get("kind", "text")
        if kind == "text":
            return self._make_text_bubble()
        return self._make_file_bubble()

    def _make_text_bubble(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(1, 1, 1, 1)
        v.setSpacing(2)
        lbl = QLabel(self.msg.get("text", ""))
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lbl.setMaximumWidth(480)
        lbl.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Minimum)
        self._text_lbl = lbl
        # 全局气泡：接收侧若带发送方方案则按其方案渲染；历史旧消息无此字段走默认
        peer_sch = BUBBLE_SCHEMES.get(self.msg.get("peer_scheme") or "")
        if self.out:
            lbl.setStyleSheet(_bubble_qss(
                self.t.get('scheme_out', '#3B82F6'),
                self.t.get('scheme_out_text', '#FFFFFF')))
        elif peer_sch:
            lbl.setStyleSheet(_bubble_qss(peer_sch['out'], peer_sch['out_text']))
        else:
            lbl.setStyleSheet(_bubble_qss(self.t['bubble_in'], self.t['text']))
        v.addWidget(lbl)
        # 链接识别：气泡下方显示可点击的链接按钮
        url = util.first_url(self.msg.get("text", ""))
        if url:
            link = QLabel(f"🔗 {util.short_url(url)}")
            link.setCursor(Qt.PointingHandCursor)
            link.setToolTip("点击打开链接")
            link.setStyleSheet(f"color: {ACCENT}; font-size: 12px; "
                               "background: transparent;")
            link.mouseReleaseEvent = lambda ev, u=url: self.openLinkRequested.emit(u)
            v.addWidget(link)
        if self.out:
            st = QLabel("")
            self._status_label = st
            st.setStyleSheet(f"color: {self.t['text_dim']}; font-size: 11px; "
                             "background: transparent; padding-right: 6px;")
            st.setAlignment(Qt.AlignRight)
            v.addWidget(st)
            # 待发送时的「取消」按钮行（仅 pending 状态填充内容）
            brow = QHBoxLayout()
            brow.setContentsMargins(0, 2, 0, 0)
            brow.setSpacing(6)
            brow.addStretch(1)
            self._text_btn_row = brow
            v.addLayout(brow)
        self._apply_text_state()
        return w

    def _apply_text_state(self):
        if not self.out:
            return
        st = self.msg.get("state", "")
        if st == "pending":
            # 异步待发（v1.9.0）：目标上线后自动发出
            # ★ v1.18.10（用户第 3 条）：文案精简。
            #   原为 "⏳ 待发送 · {desc}上线后自动发出"（最长 18 字），
            #   在气泡里很占地方。统一缩短为 6 字，与安卓端保持一致。
            if hasattr(self, "_status_label"):
                self._status_label.setText("⏳ 待发送")
            if hasattr(self, "_text_btn_row"):
                self._text_btn_row.addWidget(self._btn(
                    "取消待发送", lambda: self.cancelPendingRequested.emit(self.msg),
                    danger=True))
            return
        txt = {"sending": "发送中…", "ok": "已送达", "timeout": "未收到回执",
               "failed": "发送失败"}.get(st, "")
        # ★ v1.18.18：自动重试状态要在气泡上体现，
        #   否则用户只看到"卡在发送中"，不知道设备在重连重试。
        if not txt and st == "retrying":
            txt = f"重试中（第 {int(self.msg.get('attempt') or 0)} 次）"
        if hasattr(self, "_status_label"):
            self._status_label.setText(txt)

    def _status_text(self) -> str:
        """文本气泡状态文案（供测试与调用方读取）"""
        st = self.msg.get("state", "")
        if st == "retrying":
            return f"重试中（第 {int(self.msg.get('attempt') or 0)} 次）"
        if st == "paused":
            return "已暂停，可断点续传"
        return {"sending": "发送中…", "ok": "已送达",
                "timeout": "未收到回执", "failed": "发送失败"}.get(st, "")

    # ---------- 文件气泡（v1.16.0：严格复刻微信文件卡片几何） ----------
    #
    # 本轮拿到清晰的微信「文件传输助手」截图（1440x3088，密度 2.2x，
    # 即 655dp 宽屏）逐像素实测后反推的规格：
    #
    #     卡片宽        710px / 2.2 ≈ 322dp   ← 占屏宽 49%
    #     卡内左右内边距 12dp                 ← 用户要求"左右距离一致"
    #     图标          40 x 52（宽高比 0.77）← 圆角矩形 + **右上折角**
    #     图标 ← 文字   14dp
    #     文件名严格两行，超出则中间 "..." 代替并保留扩展名
    #     大小 + 状态（已保存/失败/待接收…）合并到**同一行**
    #     未下载态 = 虚线描边（不是半透明虚化）
    #
    #: 文件卡片总宽（px）—— 固定而非自适应，保证同屏所有卡片等宽
    #
    # ★ v1.17.0：322 → 344（用户要求「文件卡片的长度较短，需要加长，
    #   统一和微信聊天对话框的卡片长度一样」）。
    #   本轮重新逐像素测量微信原图（1440px 宽、密度 2.2x ≈ 654.5dp 屏）：
    #     微信文件卡：卡宽 714px = 324.5dp，卡内文字区 586px = 266dp
    #     改前本端：卡宽 322dp，文字区 244dp —— 比微信窄 22dp
    #   按微信实测文字区 266dp 反推：
    #     266 + 12(左) + 14(图标间距) + 40(图标) + 12(右) = 344dp
    #   与安卓端 fileCardWidthRatio() = 0.526 口径一致（344/654.5 ≈ 0.526）。
    FILE_CARD_W = 344
    #: 卡内左右内边距
    FILE_CARD_PAD = 12
    #: 图标左边距文字
    FILE_ICON_GAP = 14
    #: 图标设计尺寸（宽 x 高）
    FILE_ICON_W = 40
    FILE_ICON_H = 52
    #: 图标边长（向后兼容旧引用；现语义为"高度"）
    FILE_ICON_SIZE = FILE_ICON_H
    #: 文字区固定宽度 —— 与图标宽度、内边距一起决定卡片总宽
    FILE_CARD_TEXT_W = (FILE_CARD_W - FILE_CARD_PAD * 2
                        - FILE_ICON_GAP - FILE_ICON_W)

    def _make_image_draggable(self, widget: QWidget):
        """★ v1.16.0：让聊天框里的图片可以「拖出去」。

        用户场景：把图片直接拖到资源管理器文件夹里保存，或拖到微信 /
        其它聊天软件的输入框里发出去 —— 与微信电脑版的行为一致。

        实现：Qt 的原生拖拽（QDrag + mimeData.setUrls）。
        目标程序若支持接收文件 URL（资源管理器、绝大多数聊天软件都支持），
        就会自行完成"保存 / 发送"。这比我们自己实现"另存为"更通用。
        """
        state = {"press": None}

        def _press(ev, w=widget):
            if ev.button() == Qt.LeftButton:
                state["press"] = ev.position().toPoint()

        def _move(ev, w=widget):
            if state["press"] is None:
                return
            if not (ev.buttons() & Qt.LeftButton):
                state["press"] = None
                return
            # 超过系统拖拽起始距离才认定为拖动，避免误触发
            if (ev.position().toPoint() - state["press"]).manhattanLength() \
                    < QApplication.startDragDistance():
                return
            state["press"] = None
            path = self._image_source()
            if not path or not os.path.isfile(path):
                return
            drag = QDrag(w)
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(path)])
            mime.setText(path)
            drag.setMimeData(mime)
            pm = w.pixmap() if hasattr(w, "pixmap") else None
            if pm is not None and not pm.isNull():
                drag.setPixmap(pm.scaled(120, 120, Qt.KeepAspectRatio,
                                         Qt.SmoothTransformation))
            self.imageDragStarted.emit(path)
            drag.exec(Qt.CopyAction | Qt.MoveAction)

        widget.mousePressEvent = _press
        widget.mouseMoveEvent = _move
        widget.setAcceptDrops(False)

    def _openable_path(self):
        """返回可用于打开本文件的本地路径（没有则 None）"""
        m = self.msg
        if m.get("kind") != "file":
            return None
        p = m.get("path") if m.get("dir") == "in" else m.get("src_path")
        if not p:
            p = m.get("path") or m.get("src_path")
        return p if p and os.path.isfile(p) else None

    def _image_source(self):
        msg = self.msg
        if not util.is_image_mime(msg.get("mime", "")):
            return None
        if msg.get("dir") == "in" and msg.get("path") and os.path.isfile(msg["path"]):
            return msg["path"]
        if msg.get("dir") == "out" and msg.get("src_path") and os.path.isfile(msg["src_path"]):
            return msg["src_path"]
        return None

    def _file_card_style(self) -> str:
        """文件卡片的底色样式（出/入两侧同色，与微信一致：卡片是中性灰底）"""
        return (f"background: {self.t['bubble_in']}; "
                f"border-radius: 8px;")

    def _make_file_bubble(self) -> QWidget:
        msg = self.msg
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(1, 1, 1, 1)
        v.setSpacing(3)

        src = self._image_source()
        if src and not msg.get("failed"):
            # 图片：直接显示缩略图（无底色），双击打开预览器
            thumb = QLabel()
            # ★ v1.18.17：走 make_thumb —— 按目标尺寸解码（不把整张大图解进内存）
            #   并带缓存，避免切设备/重绘时反复解码同一张照片。
            pm = make_thumb(src, 300)
            if not pm.isNull():
                thumb.setPixmap(pm)

            def _open_image(_ev, w=thumb):
                p = self._image_source()
                if p:
                    self.openRequested.emit(p)

            thumb.setCursor(Qt.PointingHandCursor)
            # ★ v1.17.0：内置图片编辑已移除，提示语相应更新
            thumb.setToolTip("双击用系统默认程序打开；右键可复制 / 另存为 / 其他应用打开；\n"
                             "直接把图片拖到文件夹或其它聊天窗口即可发送")
            thumb.mouseDoubleClickEvent = _open_image
            # ★ v1.16.0：聊天框图片支持拖动保存 / 拖到其它应用。
            # 实现方式：按住图片拖动时，构造一个带文件 URL 的 QDrag，
            # 目标（资源管理器窗口 / 微信等聊天软件输入框）自行接收并落盘。
            self._make_image_draggable(thumb)
            v.addWidget(thumb)
            info = QLabel(f"{msg.get('file', '')} · {util.fmt_size(msg.get('size', 0))}")
            info.setStyleSheet(f"color: {self.t['text_dim']}; font-size: 11px; "
                               "background: transparent;")
            info.setMaximumWidth(320)
            info.setCursor(Qt.PointingHandCursor)
            info.mouseDoubleClickEvent = _open_image
            v.addWidget(info)
        else:
            # ★ v1.15.0 严格微信几何（见本段顶部规格说明）：
            #   卡内左右各 12px 内边距，上下各 10px；
            #   左=文件名(严格2行) + 大小/状态(同一行)；右=44x50 缺角图标。
            card = QWidget()
            card.setFixedWidth(self.FILE_CARD_W)
            card.setStyleSheet(self._file_card_style())
            crow = QHBoxLayout(card)
            crow.setContentsMargins(self.FILE_CARD_PAD, 10,
                                    self.FILE_CARD_PAD, 10)
            crow.setSpacing(self.FILE_ICON_GAP)

            # ---- 左栏：文字区（固定宽，保证卡片等宽）----
            meta = QVBoxLayout()
            meta.setSpacing(4)
            # 文件名严格两行：第一行全保留，超出部分中间 "..." 代替，
            # 结尾扩展名保留（微信：`...20....17.pdf`）
            name_lbl = QLabel()
            name_lbl.setStyleSheet(f"font-size: 14px; font-weight: 600; "
                                   f"color: {self.t['text']}; background: transparent;")
            name_lbl.setFixedWidth(self.FILE_CARD_TEXT_W)
            name_lbl.setText(self._wrap_two_lines(msg.get("file", "") or "文件"))
            name_lbl.setToolTip(msg.get("file", ""))
            self._name_lbl = name_lbl
            meta.addWidget(name_lbl)

            # 大小 + 状态 + 转圈 —— 全部挤在**同一行**（用户要求）
            sub_row = QHBoxLayout()
            sub_row.setSpacing(6)
            self._ring = QLabel()
            self._ring.setFixedSize(14, 14)
            self._ring.setVisible(False)
            sub_row.addWidget(self._ring)
            sub = QLabel(self._meta_text())
            sub.setStyleSheet(f"color: {self.t['text_dim']}; font-size: 11px; "
                              "background: transparent;")
            self._sub_lbl = sub
            sub_row.addWidget(sub, 1)
            meta.addLayout(sub_row)
            meta.addStretch(1)

            # 左栏文字：固定宽 + 0 伸缩因子，把宽度让给右侧
            crow.addLayout(meta, 0)

            # ---- 右栏：40x52 折角类型图标，垂直居中 -------------
            # ★ v1.16.0：卡宽由 450 改为 322（1440px 微信截图 ÷ 2.2 密度实测），
            #   图标 40x52（宽高比 0.77），文字区 = 322 - 12*2 - 14 - 40 = 244。
            #   addStretch(1) 吸收剩余宽度，保证「图标右边距 = 12」与「左边距 12」相等。
            crow.addStretch(1)
            self._icon = QLabel()
            self._icon.setFixedSize(self.FILE_ICON_W, self.FILE_ICON_H)
            self._icon.setStyleSheet("background: transparent;")
            crow.addWidget(self._icon, 0, Qt.AlignVCenter)
            # ★ v1.16.0：卡片在**收发两侧都紧贴自己的头像**（微信行为）——
            #   发送侧靠右（AlignRight），接收侧靠左（AlignLeft）。
            #   旧版恒为 AlignLeft，导致电脑端发出的文件卡片错误地贴在左边，
            #   与"微信绿气泡"的右侧语义不符，用户目视就是"靠边不对/颜色不对"。
            v.addWidget(card, 0, Qt.AlignRight if self.out else Qt.AlignLeft)

        # 兼容旧引用：进度容器不再使用，保留一个恒隐藏的占位
        self._bar = QProgressBar()
        self._bar.setFixedHeight(0)
        self._bar.setVisible(False)
        v.addWidget(self._bar)

        # 兼容旧引用：状态文案已并入 meta 行，这里保留隐藏占位
        self._state_lbl = QLabel("")
        self._state_lbl.setVisible(False)
        v.addWidget(self._state_lbl)

        self._btn_row = QHBoxLayout()
        self._btn_row.setSpacing(8)
        v.addLayout(self._btn_row)

        self._update_transfer_ui()
        return w

    @staticmethod
    def _wrap_two_lines(text: str, per_line: int = 26) -> str:
        """把文件名严格限制在两行内 —— 复刻微信的"首行全保留 + 中间省略"。

        v1.14.0 的做法是"前两行截断 + 行尾省略号"，与微信截图不符。
        实测微信（参考图 `甘肃国钛拆除、砌筑、安装技术附件20....17.pdf`）：
          · 第一行**完整保留**
          · 超出两行的部分在**中间**用 "..." 代替
          · **结尾的扩展名保留**（用户明确要求"结尾的文件格式等保留"）

        因此这里做三段拼装：首行 + "..." + 末行（末行含扩展名）。

        per_line 的取值依据：文字区宽 368px ÷ 14px 字号下的全角字宽 ≈ 26 个汉字。
        （CJK 字符在 14px 下约占 14px 宽，标点/数字更窄，26 是保守值，
        宁可提前省略也不让 QLabel 把文字裁掉。）
        """
        if not text:
            return ""
        if len(text) <= per_line * 2:
            return text

        # 保留尾部（优先保住扩展名，微信里扩展名总是可见的）
        tail_len = min(len(text) - per_line, per_line)
        ext = ""
        dot = text.rfind(".")
        if dot > 0 and len(text) - dot <= 8:
            ext = text[dot:]
        if ext and len(ext) < tail_len:
            # 末行 = 主干尾部 + 扩展名
            stem_tail_len = tail_len - len(ext)
            tail = text[len(text) - len(ext) - stem_tail_len:
                        len(text) - len(ext)] + ext
        else:
            tail = text[-tail_len:]

        return text[:per_line] + "\n" + "..." + tail

    def _meta_text(self) -> str:
        """meta 行文案：文件大小 + 状态（同一行，用户要求）"""
        msg = self.msg
        size = util.fmt_size(msg.get("size", 0))
        st = self._status_text()
        return f"{size}  {st}" if st else size

    def _status_text(self) -> str:
        """按消息状态推导状态文案（v1.15.0 起与大小同行显示）"""
        msg = self.msg
        state = msg.get("state", "")
        if state in ("started", "progress"):
            # 优先用实时进度文案（含百分比 / 速度 / 多目标计数）
            return getattr(self, "_progress_text", "") or (
                "发送中…" if msg.get("dir") == "out" else "接收中…")
        if state == "pending":
            # ★ v1.18.10（用户第 3 条）：与安卓端统一精简为 6 字
            return "⏳ 待发送"
        if state == "offer":
            return "等待接收…"
        if state == "confirm":
            return "对方请求发送文件，是否接收？"
        if state == "done":
            # ★ v1.18.27：文件被删掉后不能再显示"已保存"（与安卓端同步修复）。
            #   用户在资源管理器里删了接收目录的文件，卡片仍显示已保存、
            #   点开却打不开 —— 状态必须与磁盘实际一致。
            if msg.get("dir") != "out":
                p = msg.get("path") or ""
                if p and not os.path.isfile(p):
                    return "文件已删除"
            return "已送达" if msg.get("dir") == "out" else "已保存"
        if state == "ok":
            return "已送达"
        if state == "refused":
            return "对方拒绝接收"
        if state == "cancelled":
            return "已取消"
        if state == "failed":
            return f"失败 · {msg.get('reason', '未知原因')}"
        # ★ v1.18.18：自动重试 / 断点续传状态
        if state == "retrying":
            n = int(msg.get("attempt") or 0)
            why = msg.get("reason")
            return f"重试中（第 {n} 次）" + (f" · {why}" if why else "")
        if state == "paused":
            total = msg.get("total_chunks")
            have = msg.get("have_chunks")
            if total:
                return f"已暂停，可续传（{have}/{total} 块）"
            return "已暂停，可断点续传"
        return ""

    def _status_text_generic(self) -> str:
        """文本气泡用的状态文案（与文件气泡 _status_text 分开维护）"""
        msg = self.msg
        state = msg.get("state", "")
        if state == "retrying":
            return f"重试中（第 {int(msg.get('attempt') or 0)} 次）"
        if state == "paused":
            return "已暂停，可断点续传"
        return ""

    def _refresh_file_icon(self):
        """按当前状态刷新类型图标（含未接收虚化）"""
        if not hasattr(self, "_icon"):
            return
        msg = self.msg
        out = msg.get("dir") == "out"
        if out:
            got = msg.get("state") in ("done", "ok")
        else:
            got = (msg.get("state") == "done"
                   and bool(msg.get("path") or msg.get("open")))
        # ★ v1.16.0：第二参仍为"高度"（宽度按 40:52 = 0.77 自动得出）
        self._icon.setPixmap(make_file_icon(msg.get("file", ""),
                                            self.FILE_ICON_H, not got))

    def _refresh_meta(self):
        """刷新 meta 行（大小 + 状态同一行）"""
        if hasattr(self, "_sub_lbl") and self._sub_lbl is not None:
            self._sub_lbl.setText(self._meta_text())

    def _btn(self, text, slot, primary=False, danger=False):
        b = QPushButton(text)
        b.setFixedHeight(26)
        b.setCursor(Qt.PointingHandCursor)
        if primary:
            b.setObjectName("Primary")
            b.setStyleSheet(f"""
                QPushButton#Primary {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {ACCENT}, stop:1 {ACCENT2}); color: white; border: none;
                    border-radius: 6px; padding: 2px 12px; font-weight: 600; }}
            """)
        elif danger:
            b.setStyleSheet(f"""
                QPushButton {{ background: transparent; border: 1px solid {RED};
                    color: {RED}; border-radius: 6px; padding: 2px 12px; }}
                QPushButton:hover {{ background: rgba(239,68,68,0.15); }}
            """)
        else:
            b.setStyleSheet(f"""
                QPushButton {{ background: transparent; border: 1px solid {self.t['border']};
                    color: {self.t['text']}; border-radius: 6px; padding: 2px 12px; }}
                QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
            """)
        b.clicked.connect(slot)
        return b

    def _clear_btns(self):
        while self._btn_row.count():
            it = self._btn_row.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

    def _update_transfer_ui(self):
        msg = self.msg
        state = msg.get("state", "")
        size = msg.get("size", 0)
        tid = msg.get("tid", "")
        self._progress_text = ""
        self._clear_btns()
        if state == "pending":
            # 待发送（离线队列）：目标上线后自动发出
            self._set_ring(False)
            self._btn_row.addWidget(self._btn(
                "取消", lambda: self.cancelPendingRequested.emit(self.msg)))
            self._refresh_meta()
            self._refresh_file_icon()
            return
        if state in ("offer", "confirm"):
            self._set_ring(False)
            if state == "confirm":
                self._btn_row.addWidget(self._btn("接收", lambda: self.acceptRequested.emit(tid), primary=True))
                self._btn_row.addWidget(self._btn("拒绝", lambda: self.rejectRequested.emit(tid), danger=True))
        elif state in ("started", "progress"):
            transferred = msg.get("transferred", 0)
            targets = msg.get("targets")
            if msg.get("dir") == "out" and targets:
                total = size * len(targets)
                done_n = sum(1 for t in msg.get("target_states", {}).values() if t == "ok")
                pct = int(min(100, transferred * 100 / max(total, 1)))
                self._progress_text = (
                    f"发送中 {pct}%{f'（{done_n}/{len(targets)} 设备完成）' if len(targets) > 1 else ''}"
                    f"  {util.fmt_speed(msg.get('speed', 0))}")
            else:
                pct = int(min(100, transferred * 100 / max(size, 1)))
                self._progress_text = f"接收中 {pct}%  {util.fmt_speed(msg.get('speed', 0))}"
            self._set_ring(True)
            self._btn_row.addWidget(self._btn("取消", lambda: self.cancelRequested.emit(tid)))
        elif state in ("refused", "cancelled", "failed"):
            self._set_ring(False)
            self._add_resend()
        else:  # done / ok / 空
            self._set_ring(False)
        # ★ v1.15.0：状态文案不再单独占一行，统一并入「大小 + 状态」meta 行
        # （用户要求："文件大小显示的文案和 保存 失败 等文案放同一行"）
        self._refresh_meta()
        self._refresh_file_icon()

    def _set_ring(self, on: bool):
        """v1.14.0：微信式转圈进度（替代横向进度条，避免超出卡片边框）"""
        if not hasattr(self, "_ring") or self._ring is None:
            return
        self._ring.setVisible(bool(on))
        if on:
            self._ring.setText("◌")
            self._ring.setStyleSheet(
                f"color: {ACCENT}; font-size: 13px; background: transparent;")

    def _add_resend(self):
        m = self.msg
        if m.get("dir") == "out" and m.get("src_path") and os.path.isfile(m.get("src_path", "")):
            self._btn_row.addWidget(self._btn("重新发送", lambda: self.resendRequested.emit(m), primary=True))

    def update_msg(self, msg: dict):
        """更新消息数据并刷新 UI；图片就绪时整体重建气泡"""
        self.msg = msg
        if self.msg.get("kind") == "file":
            if self._image_source():
                self._rebuild_content()
                return
            self._update_transfer_ui()
            self._install_menu_policy()
        else:
            self._apply_text_state()
