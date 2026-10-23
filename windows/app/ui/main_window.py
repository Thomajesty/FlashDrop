# -*- coding: utf-8 -*-
"""FlashDrop 主窗口"""

import os
import shutil
import subprocess
import sys
import ctypes
import tempfile
import threading
import time

from PySide6.QtCore import (Qt, QThread, QTimer, QUrl, QRectF, QPointF, QEvent,
                           QObject, Signal)
from PySide6.QtGui import (QIcon, QAction, QPixmap, QPainter, QColor, QPolygonF,
                           QLinearGradient, QBrush, QDesktopServices, QCloseEvent,
                           QDragEnterEvent, QDropEvent, QKeySequence, QShortcut,
                           QFontMetrics, QGuiApplication, QCursor)
from PySide6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
                               QLabel, QListWidget, QListWidgetItem, QPushButton,
                               QLineEdit, QPlainTextEdit, QScrollArea,
                               QFileDialog, QDialog, QFormLayout, QCheckBox,
                               QComboBox, QSpinBox, QTabWidget, QMessageBox,
                               QSystemTrayIcon, QMenu, QApplication,
                               QDialogButtonBox, QGraphicsOpacityEffect, QFrame,
                               QToolButton, QStackedWidget, QInputDialog,
                               QProgressBar)

from .. import util
from .. import updater
from ..node import FlashNode
from .theme import (build_qss, DARK, LIGHT, ACCENT, ACCENT2, GREEN, RED,
                    resolve_theme, bubble_scheme, BUBBLE_SCHEMES)
from .bridge import NodeBridge
from .history import History
from .widgets import BubbleFrame, make_avatar, make_platform_badge
from .image_viewer import ImageViewer
from .emoji import EmojiButton

ALL_ID = "__all__"

_EXT_MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp",
}


def _mime_of(path: str) -> str:
    """按扩展名粗判 MIME（预览器只需要区分"是不是图片"）"""
    return _EXT_MIME.get(os.path.splitext(path or "")[1].lower(), "")


def _force_foreground(win) -> None:
    """把窗口强制拉到前台（Windows 专用兜底）。

    ★ 为什么需要它（v1.18.9）：
    Windows 有「前台锁定」策略 —— 只有当前拥有输入焦点的进程才能
    随意调用 `SetForegroundWindow`。程序被隐藏到托盘后失去前台资格，
    此时 Qt 的 `activateWindow()` 常被系统**静默忽略**，
    结果是窗口恢复了却仍在其他窗口后面，用户以为「双击没反应」。

    技巧：`AttachThreadInput` 把当前线程挂到前台线程的输入队列上，
    临时借用其前台资格，再调 `SetForegroundWindow`。
    这是托盘类程序恢复窗口的标准做法，失败也不会抛异常。
    """
    if sys.platform != "win32":
        return
    try:
        hwnd = int(win.winId())
    except Exception:
        return
    try:
        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        SW_RESTORE = 9
        # 若是最小化，先还原
        if u32.IsIconic(hwnd):
            u32.ShowWindow(hwnd, SW_RESTORE)

        fg = u32.GetForegroundWindow()
        cur_tid = k32.GetCurrentThreadId()
        fg_tid = u32.GetWindowThreadProcessId(fg, None) if fg else 0
        attached = False
        if fg_tid and fg_tid != cur_tid:
            attached = bool(u32.AttachThreadInput(fg_tid, cur_tid, True))
        try:
            u32.BringWindowToTop(hwnd)
            u32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                u32.AttachThreadInput(fg_tid, cur_tid, False)
    except Exception:
        pass


def confirm(parent, title: str, text: str, ok_text="确定", cancel_text="取消") -> bool:
    """中文按钮的确认对话框（默认 Yes/No 是英文），返回是否确认"""
    box = QMessageBox(QMessageBox.Question, title, text,
                      QMessageBox.Yes | QMessageBox.No, parent)
    box.button(QMessageBox.Yes).setText(ok_text)
    box.button(QMessageBox.No).setText(cancel_text)
    box.setDefaultButton(QMessageBox.No)
    return box.exec() == QMessageBox.Yes


def make_app_icon(size=64) -> QIcon:
    """程序图标：渐变圆角方块 + 闪电"""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    m = int(size * 0.04)
    grad = QLinearGradient(m, m, size - m, size - m)
    grad.setColorAt(0, QColor("#3b82f6"))
    grad.setColorAt(1, QColor("#06b6d4"))
    p.setBrush(QBrush(grad))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(m, m, size - 2 * m, size - 2 * m), size * 0.22, size * 0.22)
    poly = QPolygonF()
    for x, y in [(0.56, 0.16), (0.30, 0.55), (0.47, 0.55), (0.40, 0.86),
                 (0.70, 0.44), (0.52, 0.44), (0.62, 0.16)]:
        poly.append(QPointF(x * size, y * size))
    p.setBrush(QColor("white"))
    p.drawPolygon(poly)
    p.end()
    return QIcon(pm)


class DeviceItemWidget(QWidget):
    """设备列表项：头像 + 名称 + 在线状态灯 + 平台徽标 + 未读

    ★ v1.18.9 改动（对齐用户需求）：
      · 在线状态灯从**行尾**移到**设备名紧后面**，绿=在线 / 灰=离线，
        一眼能看出每台设备的在线情况（用户点名要求"设备名称后面用
        绿色灰色显示在线状态"）。
    ★ v1.18.17 改动：
      · **移除行内 ✕ 删除按钮**（用户反馈"设备那一行有删除按钮 需要取消"）。
        删除入口统一收敛为：右击菜单 + 多选后的底部「删除选中」。
        原因：行内 ✕ 单击即删、误触风险高，且与右击菜单重复。
    """

    deleteRequested = Signal(str)   # 保留兼容位（历史待发送窗口仍在用）

    def __init__(self, snap: dict, unread=0, dim="#9ca3af", parent=None,
                 deletable=False):
        super().__init__(parent)
        self._pid = snap["id"]
        self.setAttribute(Qt.WA_TranslucentBackground)
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 8, 8, 8)
        root.setSpacing(10)
        av = QLabel()
        av.setPixmap(make_avatar(snap["name"], snap["id"], 38))
        root.addWidget(av)
        mid = QVBoxLayout()
        mid.setSpacing(2)
        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        name = QLabel(snap["name"])
        name.setStyleSheet("font-size: 13px; font-weight: 600;")
        name_row.addWidget(name)
        # ★ 状态灯紧跟在设备名后面（在线绿 / 离线灰）
        if snap["id"] != ALL_ID:
            dotw = QLabel()
            on = bool(snap.get("online"))
            dotw.setFixedSize(9, 9)
            dotw.setStyleSheet(
                "background:%s;border-radius:4px;" % (GREEN if on else "#6b7280"))
            dotw.setToolTip("在线" if on else "离线")
            name_row.addWidget(dotw)
            badge = QLabel()
            badge.setPixmap(make_platform_badge(snap["platform"]))
            name_row.addWidget(badge)
        name_row.addStretch(1)
        if unread:
            dot = QLabel(str(unread) if unread < 100 else "99+")
            dot.setStyleSheet(f"background:{RED};color:white;border-radius:8px;"
                              "font-size:10px;padding:1px 6px;font-weight:600;")
            name_row.addWidget(dot)
        # ★ v1.18.17：行内 ✕ 删除按钮已移除（见类注释）
        mid.addLayout(name_row)
        if snap["id"] == ALL_ID:
            sub = QLabel("全体在线设备")
        else:
            ip = snap["ips"][0] if snap.get("ips") else ""
            sub = QLabel((ip + " · " if ip else "") + self._state_text(snap))
        sub.setStyleSheet(f"font-size: 11px; color: {dim};")
        mid.addWidget(sub)
        root.addLayout(mid, 1)

    @staticmethod
    def _state_text(snap):
        if snap.get("connected"):
            return "已连接"
        if snap.get("online"):
            return "可达 · 未连接"
        return "离线"


class AddDeviceDialog(QDialog):
    def __init__(self, parent, default_port):
        super().__init__(parent)
        self.setWindowTitle("添加设备")
        self.setMinimumWidth(380)
        v = QVBoxLayout(self)
        tip = QLabel("输入对方设备的 IP 和端口（默认端口 58899）。\n"
                     "适用于 AP 隔离、非常规网段等自动发现失败的环境。")
        tip.setWordWrap(True)
        v.addWidget(tip)
        form = QFormLayout()
        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("例如 192.168.1.101")
        self.port_edit = QLineEdit(str(default_port))
        form.addRow("IP 地址", self.host_edit)
        form.addRow("端口", self.port_edit)
        v.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("连接")
        bb.button(QDialogButtonBox.Cancel).setText("取消")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def host_port(self):
        host = self.host_edit.text().strip()
        port = int(self.port_edit.text().strip() or 58899)
        return host, port


# ---------- v1.18.30：软件更新（数据源 GitHub Releases，双端对称） ----------

class UpdateChecker(QObject):
    """后台检查最新 Release；结果经信号送回主线程。

    工作线程不能直接碰 UI，也不能在工作线程里调 QTimer.singleShot
    （会被静默丢弃）——统一走 Signal（跨线程 emit 安全）。
    """
    finished = Signal(object)          # dict | None

    def __init__(self, parent=None):
        super().__init__(parent)

    def check(self):
        def work():
            try:
                info = updater.fetch_latest()
            except Exception:
                info = None
            self.finished.emit(info)
        threading.Thread(target=work, daemon=True,
                         name="fd-update-check").start()


class UpdateDownloader(QObject):
    """后台下载安装包；进度经信号回主线程（v1.18.32）。

    工作线程不碰 UI：progress/finished/failed 都是跨线程 emit 安全的信号。
    先写 .part 完成再改名，避免半包被当成成品。
    """

    progress = Signal(int, int)          # done_bytes, total_bytes(0=未知)
    finished = Signal(str)               # 保存路径
    failed = Signal(str)                 # 错误信息

    def __init__(self, url, dest, parent=None):
        super().__init__(parent)
        self.url = url
        self.dest = dest
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        import tempfile
        import urllib.request
        try:
            req = urllib.request.Request(
                self.url, headers={"User-Agent": updater.USER_AGENT})
            os.makedirs(os.path.dirname(self.dest), exist_ok=True)
            tmp = self.dest + ".part"
            with urllib.request.urlopen(req, timeout=30) as resp, \
                    open(tmp, "wb") as f:
                total = int(resp.headers.get("Content-Length") or 0)
                done = 0
                while not self._cancelled:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    self.progress.emit(done, total)
            if self._cancelled:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                return
            os.replace(tmp, self.dest)
            self.finished.emit(self.dest)
        except Exception as e:
            self.failed.emit(str(e))


class UpdateDialog(QDialog):
    """发现新版本：版本对比 + 更新日志 + 应用内下载 / 跳过此版本。"""

    def __init__(self, cfg, current, info, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.info = info
        self.version = info.get("version", "")
        self._thread = None
        self._worker = None
        self._kind = "exe"
        self._downloaded = None       # 下载完成的文件路径
        self.setWindowTitle("发现新版本")
        self.setMinimumWidth(500)
        v = QVBoxLayout(self)
        v.setSpacing(10)

        title = QLabel(f"<b>闪传 FlashDrop</b>　v{current}　→　"
                       f"<span style='color:{ACCENT}'>v{self.version}</span>")
        title.setStyleSheet("font-size:15px;")
        v.addWidget(title)

        notes = QPlainTextEdit()
        notes.setPlainText((info.get("notes") or "（此版本没有更新说明）").strip()[:4000])
        notes.setReadOnly(True)
        notes.setMinimumHeight(180)
        v.addWidget(notes, 1)

        # ---- 下载进度（初始隐藏）----
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.progress.setRange(0, 100)
        self.progress.hide()
        v.addWidget(self.progress)
        self.status = QLabel("")
        self.status.setStyleSheet(f"color:{ACCENT2};font-size:12px;")
        self.status.hide()
        v.addWidget(self.status)

        row = QHBoxLayout()
        row.setSpacing(8)
        exe = updater.asset_for(info, ".exe")
        apk = updater.asset_for(info, ".apk")
        self.buttons = []
        if exe:
            b = QPushButton("下载 Windows 版")
            b.clicked.connect(lambda: self._start_download(exe, "exe"))
            row.addWidget(b)
            self.buttons.append(b)
        if apk:
            b = QPushButton("下载 Android 版")
            b.clicked.connect(lambda: self._start_download(apk, "apk"))
            row.addWidget(b)
            self.buttons.append(b)
        b = QPushButton("打开下载页")
        b.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(
            info.get("html_url") or updater.RELEASES_PAGE)))
        row.addWidget(b)
        self.buttons.append(b)
        row.addStretch(1)
        b = QPushButton("跳过此版本")
        b.clicked.connect(self._skip)
        row.addWidget(b)
        self.buttons.append(b)
        b = QPushButton("稍后再说")
        b.clicked.connect(self.reject)
        b.setDefault(True)
        row.addWidget(b)
        self.buttons.append(b)
        v.addLayout(row)
        self._row = row

    # ---------- 应用内下载（v1.18.32） ----------

    def _start_download(self, asset, kind):
        """把安装包下到临时目录；EXE 完成后可直接升级，APK 完成后开文件夹。"""
        if self._thread is not None:
            return
        name = asset.get("name") or ("FlashDrop_v%s" % self.version)
        dest = os.path.join(tempfile.gettempdir(), "FlashDropUpdate", name)
        self._kind = kind
        self.progress.show()
        self.status.show()
        self.status.setText("正在连接…")
        self._set_buttons_enabled(False)

        self._worker = UpdateDownloader(asset["url"], dest)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._thread.start()

    def _on_progress(self, done, total):
        if total > 0:
            pct = int(done * 100 / total)
            self.progress.setRange(0, 100)
            self.progress.setValue(pct)
            self.status.setText("已下载 %s / %s（%d%%）"
                                % (_fmt_size(done), _fmt_size(total), pct))
        else:
            self.progress.setRange(0, 0)   # 未知大小 → 走马灯
            self.status.setText("已下载 %s" % _fmt_size(done))

    def _on_finished(self, path):
        self._cleanup_thread()
        self._downloaded = path
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        size = _fmt_size(os.path.getsize(path)) if os.path.exists(path) else ""
        self.status.setText("下载完成（%s）：%s" % (size, path))
        self._set_buttons_enabled(True)
        if self._kind == "exe":
            b = QPushButton("立即安装（关闭并启动新版本）")
            b.clicked.connect(self._install)
        else:
            b = QPushButton("打开所在文件夹")
            b.clicked.connect(lambda: _open_folder(path))
        # 插到「打开下载页」之后，保持尾部三个按钮顺序
        idx = self._row.count() - 3
        self._row.insertWidget(idx, b)
        self.buttons.append(b)

    def _on_failed(self, msg):
        self._cleanup_thread()
        self.progress.hide()
        self.status.setText("下载失败：%s（可点「打开下载页」手动下载）" % msg)
        self._set_buttons_enabled(True)

    def _install(self):
        """关闭当前程序并启动新下载的安装包（PyInstaller onefile 直接运行即新版）。"""
        path = self._downloaded
        if not path or not os.path.exists(path):
            return
        try:
            subprocess.Popen([path], close_fds=True)
        except Exception as e:
            self.status.setText("启动失败：%s" % e)
            return
        self.accept()
        QApplication.quit()

    def _set_buttons_enabled(self, on):
        for b in self.buttons:
            b.setEnabled(on)

    def _cleanup_thread(self):
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(3000)
            self._thread = None
            self._worker = None

    def _skip(self):
        updater.mark_version_skipped(self.cfg, self.version)
        self.reject()

    def reject(self):
        if self._worker is not None:
            self._worker.cancel()
        self._cleanup_thread()
        super().reject()

    def closeEvent(self, ev):
        if self._worker is not None:
            self._worker.cancel()
        self._cleanup_thread()
        super().closeEvent(ev)


def _fmt_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return "%.1f %s" % (n, unit) if unit != "B" else "%d B" % n
        n /= 1024.0
    return "%d B" % n


def _open_folder(path):
    """打开文件所在文件夹并选中该文件（资源管理器 /select）。"""
    try:
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    except Exception:
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))


class SettingsDialog(QDialog):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("设置")
        self.setMinimumWidth(520)
        v = QVBoxLayout(self)
        tabs = QTabWidget()
        v.addWidget(tabs, 1)

        w1 = QWidget()
        f1 = QFormLayout(w1)
        f1.setSpacing(12)
        self.name_edit = QLineEdit(cfg["name"])
        f1.addRow("设备名称", self.name_edit)
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("跟随系统", "system")
        self.theme_combo.addItem("深色", "dark")
        self.theme_combo.addItem("浅色", "light")
        idx = 2 if cfg["theme"] == "light" else (1 if cfg["theme"] == "dark" else 0)
        self.theme_combo.setCurrentIndex(idx)
        f1.addRow("界面主题", self.theme_combo)
        self.scheme_combo = QComboBox()
        self._scheme_keys = list(BUBBLE_SCHEMES.keys())
        for k in self._scheme_keys:
            self.scheme_combo.addItem(BUBBLE_SCHEMES[k]["name"], k)
        cur = self._scheme_keys.index(cfg["bubble_scheme"]) \
            if cfg["bubble_scheme"] in self._scheme_keys else 0
        self.scheme_combo.setCurrentIndex(cur)
        f1.addRow("气泡配色", self.scheme_combo)
        self.auto_accept = QCheckBox("自动接收文件（关闭后需手动确认）")
        self.auto_accept.setChecked(bool(cfg["auto_accept"]))
        f1.addRow("", self.auto_accept)
        self.notify = QCheckBox("收到消息时显示系统通知")
        self.notify.setChecked(bool(cfg["notify_on_receive"]))
        f1.addRow("", self.notify)
        self.tray_chk = QCheckBox("点击关闭按钮时最小化到托盘")
        self.tray_chk.setChecked(bool(cfg["minimize_to_tray"]))
        f1.addRow("", self.tray_chk)
        # ★ v1.18.9 新增（用户第 5 条需求）：「离线聊天」开关。
        #
        # 与「保存聊天」（history_limit 决定是否落盘）并存，职责正交：
        #   · 保存聊天 → 数据层：聊天记录是否写盘
        #   · 离线聊天 → 视图/交互层：是否展示并使用离线能力
        # 开启后：不在同一网络的设备仍留在设备列表（灰色状态灯），
        #         点进去能看历史、能发离线消息，设备上线自动送达。
        # 关闭后：设备列表只显示当前在线设备，界面更干净。
        self.offline_chk = QCheckBox(
            "离线聊天（保留对话框：显示离线设备、可发离线消息、可看历史）")
        self.offline_chk.setChecked(bool(cfg["offline_chat"]))
        f1.addRow("", self.offline_chk)
        tabs.addTab(w1, "基本")

        w2 = QWidget()
        f2 = QFormLayout(w2)
        f2.setSpacing(12)
        self.save_edit = QLineEdit(cfg["save_dir"])
        b1 = QPushButton("浏览…")
        b1.clicked.connect(self._pick_save)
        row1 = QHBoxLayout()
        row1.addWidget(self.save_edit, 1)
        row1.addWidget(b1)
        f2.addRow("接收保存位置", row1)
        self.cache_edit = QLineEdit(cfg["cache_dir"])
        b2 = QPushButton("浏览…")
        b2.clicked.connect(self._pick_cache)
        row2 = QHBoxLayout()
        row2.addWidget(self.cache_edit, 1)
        row2.addWidget(b2)
        f2.addRow("传输缓存位置", row2)
        open_save = QPushButton("打开保存文件夹")
        open_save.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(cfg["save_dir"])))
        open_cache = QPushButton("清理缓存")
        open_cache.clicked.connect(self._clear_cache)
        clear_orphan = QPushButton("清理失效文件卡片")
        clear_orphan.clicked.connect(self._clear_orphan_cards)
        clear_hist = QPushButton("清空全部聊天记录")
        clear_hist.setObjectName("Danger")
        clear_hist.clicked.connect(self._clear_all_history)
        row3 = QHBoxLayout()
        row3.addWidget(open_save)
        row3.addWidget(open_cache)
        row3.addWidget(clear_orphan)
        row3.addWidget(clear_hist)
        f2.addRow("", row3)
        orphan_note = QLabel(
            "失效文件卡片：文件已被删除、但聊天记录还在的空卡片（清理后不再显示“已保存”）")
        orphan_note.setWordWrap(True)
        _dim2 = parent.theme["text_dim"] if parent is not None else "#8a919c"
        orphan_note.setStyleSheet(f"color:{_dim2};font-size:11px;")
        f2.addRow("", orphan_note)
        tabs.addTab(w2, "存储")

        w3 = QWidget()
        f3 = QFormLayout(w3)
        f3.setSpacing(12)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(int(cfg["port"]))
        f3.addRow("服务端口", self.port_spin)
        self.encrypt_chk = QCheckBox(
            "传输加密（TLS）：与同样开启加密的设备自动加密通信，\n"
            "未开启加密的设备自动回退明文（无需重启，立即生效）")
        self.encrypt_chk.setChecked(bool(cfg["encrypt"]))
        f3.addRow("", self.encrypt_chk)
        note = QLabel("修改端口后需重启应用生效。同一局域网内的设备需使用相同端口\n"
                      "才能互相自动发现；不同端口可通过“添加设备”手动连接。")
        # 颜色跟随当前主题（写死灰色在浅色主题下对比度过低）
        _dim = parent.theme["text_dim"] if parent is not None else "#8a919c"
        note.setStyleSheet(f"color:{_dim};font-size:11px;")
        f3.addRow("", note)
        fw_btn = QPushButton("允许 Windows 防火墙入站（需要管理员权限）")
        fw_btn.clicked.connect(self._fix_firewall)
        f3.addRow("", fw_btn)
        tabs.addTab(w3, "网络")

        # 关于：版本与作者信息
        w4 = QWidget()
        v4 = QVBoxLayout(w4)
        v4.setSpacing(8)
        from .. import APP_AUTHOR, APP_CONTACT, __version__
        about = QLabel(
            f"<div style='line-height:180%'>"
            f"<b>闪传 FlashDrop</b> v{__version__}<br>"
            f"局域网文件与消息互传工具<br><br>"
            f"作者：{APP_AUTHOR}<br>"
            f"联系：<a href='mailto:{APP_CONTACT}'>{APP_CONTACT}</a>"
            f"</div>")
        about.setOpenExternalLinks(True)
        about.setTextInteractionFlags(Qt.TextBrowserInteraction)
        about.setAlignment(Qt.AlignTop)
        v4.addWidget(about)

        # ★ v1.18.30：检查更新（GitHub Releases，与安卓端同源）
        upd_row = QHBoxLayout()
        upd_row.setSpacing(8)
        self.btn_check_update = QPushButton("检查更新")
        self.btn_check_update.clicked.connect(self._check_update)
        upd_row.addWidget(self.btn_check_update)
        self.upd_status = QLabel("更新与安装包托管在 GitHub Releases")
        self.upd_status.setStyleSheet("color:#6b7280;font-size:12px;")
        upd_row.addWidget(self.upd_status, 1)
        v4.addLayout(upd_row)

        # v1.12.0：赞助支持 —— 微信 / 支付宝 收款码卡片（按各自品牌配色）
        sponsor_lbl = QLabel("<b>赞助支持</b>　·　如果闪传对你有帮助，请作者喝杯咖啡 ☕")
        sponsor_lbl.setStyleSheet(f"color:{_dim};font-size:12px;")
        v4.addWidget(sponsor_lbl)

        from PySide6.QtGui import QPixmap

        def _qr_card(path, brand, color):
            """一张收款码卡片：白底圆角 + 二维码 + 底部品牌色文字"""
            card = QFrame()
            card.setStyleSheet(
                "QFrame{background:#FFFFFF;border:1px solid #E5E7EB;"
                "border-radius:10px;}")
            cv = QVBoxLayout(card)
            cv.setContentsMargins(12, 12, 12, 8)
            cv.setSpacing(6)
            img = QLabel()
            pm = QPixmap(path)
            if not pm.isNull():
                img.setPixmap(pm.scaled(150, 150, Qt.KeepAspectRatio,
                                        Qt.SmoothTransformation))
            img.setAlignment(Qt.AlignCenter)
            cv.addWidget(img)
            cap = QLabel(brand)
            cap.setStyleSheet(
                f"color:{color};font-size:13px;font-weight:bold;"
                "background:transparent;border:none;")
            cap.setAlignment(Qt.AlignCenter)
            cv.addWidget(cap)
            return card

        from .theme import _res_url
        qr_row = QHBoxLayout()
        qr_row.setSpacing(16)
        qr_row.addWidget(_qr_card(_res_url("weixin_qr.png"), "微信", "#07C160"))
        qr_row.addWidget(_qr_card(_res_url("alipay_qr.png"), "支付宝", "#1677FF"))
        qr_row.addStretch(1)
        v4.addLayout(qr_row)

        v4.addStretch(1)
        tabs.addTab(w4, "关于")

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("保存")
        bb.button(QDialogButtonBox.Cancel).setText("取消")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _pick_save(self):
        d = QFileDialog.getExistingDirectory(self, "选择接收保存位置", self.save_edit.text())
        if d:
            self.save_edit.setText(d)

    def _pick_cache(self):
        d = QFileDialog.getExistingDirectory(self, "选择缓存位置", self.cache_edit.text())
        if d:
            self.cache_edit.setText(d)

    def _clear_cache(self):
        n = 0
        try:
            for f in os.listdir(self.cfg["cache_dir"]):
                if f.endswith(".part"):
                    try:
                        os.remove(os.path.join(self.cfg["cache_dir"], f))
                        n += 1
                    except Exception:
                        pass
        except Exception:
            pass
        QMessageBox.information(self, "清理缓存", f"已清理 {n} 个未完成传输的缓存文件")

    def _clear_orphan_cards(self):
        """★ v1.18.27：清理「失效文件卡片」—— 文件已被删掉、记录还留着的空卡片。

        与安卓端设置「数据清理」第 4 类同一口径：清理后这些卡片不再显示
        "已保存"（仍然打不开），界面与磁盘实际状态保持一致。
        """
        mw = self.parent()
        if mw is None or not hasattr(mw, "history"):
            return
        n = mw.history.purge_orphan_files()
        if n <= 0:
            QMessageBox.information(self, "清理失效文件卡片",
                                    "没有发现失效的文件卡片（已接收的文件都还在）")
            return
        # 重新按磁盘加载，界面与磁盘一致（_load_all_history 内部会重绘）
        try:
            mw.msgs.clear()
            mw.unread.clear()
            mw._exit_select_mode()
            mw._load_all_history()
        except Exception:
            pass
        QMessageBox.information(
            self, "清理失效文件卡片",
            f"已清理 {n} 条失效文件卡片\n（对应文件已不存在，记录已移除）")

    def _clear_all_history(self):
        mw = self.parent()
        if mw is None or not hasattr(mw, "history"):
            return
        if not confirm(self, "清空聊天记录",
                       "确定清空本机的全部聊天记录吗？（不影响已接收的文件）"):
            return
        mw.history.clear_all()
        mw.msgs.clear()
        mw.unread.clear()
        mw._exit_select_mode()
        mw._render_chat()
        QMessageBox.information(self, "清空聊天记录", "已清空全部聊天记录")

    def _fix_firewall(self):
        exe = sys.executable
        try:
            if ctypes.windll.shell32.IsUserAnAdmin():
                subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule",
                                "name=FlashDrop"], capture_output=True)
                subprocess.run(["netsh", "advfirewall", "firewall", "add", "rule",
                                "name=FlashDrop", "dir=in", "action=allow",
                                f"program={exe}", "enable=yes"], capture_output=True)
                QMessageBox.information(self, "防火墙", "已添加防火墙入站规则")
            else:
                params = ('/C netsh advfirewall firewall delete rule name=FlashDrop & '
                          'netsh advfirewall firewall add rule name=FlashDrop dir=in '
                          f'action=allow program="{exe}" enable=yes')
                ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", params, None, 1)
        except Exception as e:
            QMessageBox.warning(self, "防火墙", f"操作失败：{e}\n请手动允许 FlashDrop 通过防火墙")

    def apply(self):
        self.cfg["name"] = self.name_edit.text().strip() or self.cfg["name"]
        self.cfg["theme"] = self.theme_combo.currentData()
        self.cfg["bubble_scheme"] = self.scheme_combo.currentData() or "blue"
        self.cfg["auto_accept"] = self.auto_accept.isChecked()
        self.cfg["notify_on_receive"] = self.notify.isChecked()
        self.cfg["minimize_to_tray"] = self.tray_chk.isChecked()
        # ★ v1.18.9：离线聊天（视图层开关），与保存聊天正交
        self.cfg["offline_chat"] = self.offline_chk.isChecked()
        self.cfg["save_dir"] = self.save_edit.text().strip() or self.cfg["save_dir"]
        self.cfg["cache_dir"] = self.cache_edit.text().strip() or self.cfg["cache_dir"]
        self.cfg["port"] = self.port_spin.value()
        self.cfg["encrypt"] = self.encrypt_chk.isChecked()
        try:
            os.makedirs(self.cfg["save_dir"], exist_ok=True)
            os.makedirs(self.cfg["cache_dir"], exist_ok=True)
        except Exception:
            pass

    # ---------- v1.18.30：检查更新 ----------

    def _check_update(self):
        from .. import __version__
        self.btn_check_update.setEnabled(False)
        self.upd_status.setText("正在检查…")
        self._upd_checker = UpdateChecker(self)   # 持有引用防 GC
        self._upd_checker.finished.connect(
            lambda info: self._on_update_info(info, __version__))
        self._upd_checker.check()

    def _on_update_info(self, info, current):
        self.btn_check_update.setEnabled(True)
        if info is None:
            # 国内直连 GitHub 常超时/被限流：明确告知，不静默
            self.upd_status.setText("检查失败：网络不可达或 GitHub 限流，请稍后重试")
            return
        if not updater.is_newer(info.get("version", ""), current):
            self.upd_status.setText(f"当前已是最新版本 v{current}")
            return
        self.upd_status.setText("")
        UpdateDialog(self.cfg, current, info, self).exec()


class PendingWindow(QDialog):
    """异步发送保存窗口（v1.9.0）

    列出待发队列：文本与文件混排，支持「立即发送」「删除」「清空」。
    队列由 MainWindow._pending_files 持有，本窗口只做展示与操作转发。
    """

    def __init__(self, win: "MainWindow"):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("待发送")
        self.setMinimumSize(560, 420)
        v = QVBoxLayout(self)
        v.setSpacing(10)

        tip = QLabel("这里的内容已经保存到本地。任意目标设备上线后会自动发出，"
                     "也可以点「立即发送」马上尝试。")
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color:{win.theme['text_dim']};font-size:12px;")
        v.addWidget(tip)

        self.listw = QListWidget()
        self.listw.setStyleSheet(
            "QListWidget{background:transparent;border:none;}"
            f"QListWidget::item{{padding:8px 6px;border-bottom:1px solid "
            f"{win.theme['border']};}}")
        v.addWidget(self.listw, 1)

        self.empty_lbl = QLabel("暂无待发送内容")
        self.empty_lbl.setAlignment(Qt.AlignCenter)
        self.empty_lbl.setStyleSheet(f"color:{win.theme['text_dim']};font-size:13px;")
        v.addWidget(self.empty_lbl)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._send_btn = QPushButton("立即发送")
        self._send_btn.setToolTip("立刻尝试发给当前在线的目标设备")
        self._send_btn.clicked.connect(self._send_now)
        self._del_btn = QPushButton("删除此项")
        self._del_btn.clicked.connect(self._del_one)
        clear_btn = QPushButton("清空全部")
        clear_btn.clicked.connect(self._clear_all)
        close_btn = QPushButton("关闭")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        row.addWidget(self._send_btn)
        row.addWidget(self._del_btn)
        row.addWidget(clear_btn)
        row.addStretch(1)
        row.addWidget(close_btn)
        v.addLayout(row)

        self._send_btn.setEnabled(False)
        self._del_btn.setEnabled(False)
        self._reload()
        self.listw.currentRowChanged.connect(self._on_row_changed)

    def _send_now(self):
        mid = self._current_mid()
        if not mid:
            return
        self.win._pending_retry_now(mid)
        self._reload()

    def _del_one(self):
        mid = self._current_mid()
        if not mid:
            return
        self.win._drop_pending(mid, "已删除该待发送内容")
        self._reload()

    def _reload(self):
        self.listw.blockSignals(True)
        self.listw.clear()
        entries = list(self.win._pending_files)
        for e in entries:
            kind = "💬 文本" if self.win._queue_kind(e) == "text" else "📎 文件"
            text = self.win._entry_text(e)
            if len(text) > 60:
                text = text[:60] + "…"
            when = time.strftime("%H:%M:%S",
                                 time.localtime((e.get("ts") or 0) / 1000))
            # ★ v1.18.18：把"为什么还留在队列里"显式告诉用户
            # last_error 早期版本可能是 dict（send_files 返回值），
            # 这里统一转成字符串，别让面板因为类型不符直接崩掉
            _raw = e.get("last_error")
            err = (_raw if isinstance(_raw, str)
                   else self.win._describe_send_fail(_raw, [])).strip()
            att = e.get("attempt")
            bits = [f"目标：{self.win._pending_target_names(e)}", when]
            if att:
                bits.append(f"已重试 {att} 次")
            if err:
                bits.append(f"原因：{err}")
            item = QListWidgetItem(f"{kind}　{text}\n" + "　·　".join(bits))
            item.setData(Qt.UserRole, e.get("mid"))
            item.setToolTip(text if not err else f"{text}\n\n{err}")
            self.listw.addItem(item)
        self.listw.blockSignals(False)
        n = len(entries)
        self.empty_lbl.setVisible(n == 0)
        self.listw.setVisible(n > 0)
        self.setWindowTitle(f"待发送（{n}）" if n else "待发送")

    def _on_row_changed(self, row):
        """选中一行时才启用操作按钮（无选中时禁用，避免误操作）"""
        has = row >= 0
        for name in ("_send_btn", "_del_btn"):
            btn = getattr(self, name, None)
            if btn is not None:
                btn.setEnabled(has)

    def _current_mid(self):
        item = self.listw.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _clear_all(self):
        if not self.win._pending_files:
            return
        if not confirm(self, "清空待发送",
                       f"确定清空全部 {len(self.win._pending_files)} 条待发送内容吗？"
                       "\n清空后不会自动补发。", ok_text="清空"):
            return
        self.win._pending_clear_all()
        self._reload()


class SearchWindow(QDialog):
    """聊天记录搜索窗口（v1.18.18）

    ★ 为什么做成**独立窗口**而不是把结果插进聊天页气泡列表：
    1. `widgets_by_msg` 以 `id(msg)` 作为气泡身份索引，多选删除 / 状态刷新
       全靠它。History.search() 从磁盘反序列化出的 dict 是**新对象**，
       直接塞进气泡列表会让这些操作全部失效。
    2. 聊天页有 LRU 缓存（`_chat_pages`，上限 8 页），键是 (视图, 设备集)。
       搜索是跨设备的，若插进聊天页会把不同搜索结果的页面挤进同一套缓存，
       正是 v1.18.17 花力气消除的"整页重建卡顿"。

    因此：结果只做**只读列表**展示 + 双击跳转到对应设备会话。
    """

    # ★ 跨线程回结果用信号（不能在工作线程里调 QTimer.singleShot，
    #   那样会被静默丢弃，表现为"搜索永远停在搜索中"）
    _search_result = Signal(object, str, object)   # win, kw, peer_ids
    _search_done = Signal(object, object)          # hits, err

    def __init__(self, win: "MainWindow", keyword: str = "",
                 scope: str = "all"):
        super().__init__(win)
        self._search_result.connect(self._start_search)
        self._search_done.connect(self._on_search_done)
        self.win = win
        self.setWindowTitle("搜索聊天记录")
        self.setMinimumSize(640, 480)
        self._hits = []
        self._loading = False
        v = QVBoxLayout(self)
        v.setSpacing(10)

        # ---- 搜索条----
        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addWidget(QLabel("关键词："))
        self.edit = QLineEdit(keyword)
        self.edit.setPlaceholderText("搜索聊天内容 / 文件名（不区分大小写）")
        self.edit.returnPressed.connect(self._do_search)
        bar.addWidget(self.edit, 1)
        self.btn_search = QPushButton("搜索")
        self.btn_search.clicked.connect(self._do_search)
        bar.addWidget(self.btn_search)
        v.addLayout(bar)

        # ---- 范围选择----
        self.scope_box = QComboBox()
        self.scope_box.addItem("全部设备", "all")
        cur = getattr(win, "current_peer", lambda: "")() or ""
        if cur and cur != ALL_ID:
            try:
                self.scope_box.addItem(
                    f"仅当前设备（{win._display_name(cur)}）", cur)
            except Exception:
                pass
        # ★ 默认"全部设备"（index 0），不是"仅当前设备"。
        #   默认窄范围是最容易踩的坑：用户搜一个存在但属于别的设备的词，
        #   结果是 0 条，用户会以为功能坏了 / 历史丢了。
        self.scope_box.setCurrentIndex(0)
        self.scope_box.currentIndexChanged.connect(self._do_search)
        lbl = QLabel("范围：")
        lbl.setStyleSheet(f"color:{win.theme['text_dim']};font-size:12px;")
        lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        sb = QHBoxLayout()
        sb.addStretch(1)
        sb.addWidget(lbl)
        sb.addWidget(self.scope_box)
        v.addLayout(sb)

        self.status = QLabel("")
        self.status.setStyleSheet(f"color:{win.theme['text_dim']};font-size:12px;")
        v.addWidget(self.status)

        # ---- 结果列表 ----
        self.listw = QListWidget()
        self.listw.setStyleSheet(
            "QListWidget{background:transparent;border:none;}"
            f"QListWidget::item{{padding:7px 6px;border-bottom:1px solid "
            f"{win.theme['border']};}}")
        v.addWidget(self.listw, 1)
        self.listw.itemDoubleClicked.connect(self._on_jump)

        self.empty_lbl = QLabel("输入关键词开始搜索")
        self.empty_lbl.setAlignment(Qt.AlignCenter)
        self.empty_lbl.setStyleSheet(
            f"color:{win.theme['text_dim']};font-size:13px;")
        v.addWidget(self.empty_lbl)

        # ---- 底部 ----
        row = QHBoxLayout()
        row.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)
        v.addLayout(row)

        if keyword.strip():
            QTimer.singleShot(0, self._do_search)
        else:
            self.edit.setFocus()

    # ---------------- 搜索 ----------------

    def _do_search(self):
        kw = self.edit.text().strip()
        if not kw:
            self._hits = []
            self._fill([])
            self.status.setText("")
            self.empty_lbl.setText("输入关键词开始搜索")
            self.empty_lbl.setVisible(True)
            self.listw.setVisible(False)
            return
        if self._loading:
            return
        self._loading = True
        self.btn_search.setEnabled(False)
        self.status.setText("搜索中…")
        scope = self.scope_box.currentData()
        pids = None if scope == "all" else [scope]
        win = self.win
        # ★ 必须用**信号**回主线程，不能在工作线程里调
        #   QTimer.singleShot：singleShot 要求在 GUI 线程调用，
        #   跨线程调用会被静默丢弃 —— 表现为搜索永远停在"搜索中…"。
        self._search_result.emit(win, kw, pids)

    def _on_search_done(self, hits, err):
        """工作线程算完 -> 回到 GUI 线程刷新界面（信号槽，运行在 GUI 线程）"""
        self._loading = False
        self.btn_search.setEnabled(True)
        if err:
            self.status.setText(f"搜索失败：{err}")
            self._fill([])
            return
        self._hits = hits
        self._fill(hits)

    def _start_search(self, win, kw, pids):
        """在 GUI 线程里起搜索工作线程"""
        import threading
        t = threading.Thread(target=self._search_worker, args=(win, kw, pids),
                             daemon=True)
        t.start()

    def _search_worker(self, win, kw, pids):
        """工作线程：只做磁盘扫描，不碰任何 Qt 对象"""
        try:
            hits = win.history.search(kw, peer_ids=pids)
            err = None
        except Exception as e:          # 异常必须回传，不能静默吞
            hits, err = [], str(e)
        # Qt 信号跨线程是队列化的 -> 槽函数在 GUI 线程执行
        self._search_done.emit(hits, err)

    def _fill(self, hits, kw=""):
        self.listw.blockSignals(True)
        self.listw.clear()
        for i, h in enumerate(hits):
            m = h.get("msg") or {}
            ts = h.get("ts") or m.get("ts") or 0
            when = time.strftime("%Y-%m-%d %H:%M",
                                 time.localtime(ts / 1000)) if ts else ""
            who = self.win._display_name(h.get("peer_id"))
            direction = "我发出" if m.get("dir") == "out" else "对方发来"
            if m.get("file"):
                kind = "📎 文件"
            elif m.get("text"):
                kind = "💬 文本"
            else:
                kind = "·"
            item = QListWidgetItem(
                f"{kind}　{who}　·　{direction}　·　{when}\n"
                f"　　{h.get('snippet') or ''}")
            item.setData(Qt.UserRole, (h.get("peer_id"), m.get("mid")))
            item.setToolTip(h.get("snippet") or "")
            self.listw.addItem(item)
        self.listw.blockSignals(False)
        n = len(hits)
        self.listw.setVisible(n > 0)
        self.empty_lbl.setVisible(n == 0)
        if n == 0:
            self.empty_lbl.setText("没有找到匹配的消息")
            # ★ 0 结果时也必须改写状态栏，否则永远停在"搜索中…"，
            #   用户会以为程序卡住了。
            self.status.setText("没有找到匹配的消息")
        else:
            self.status.setText(f"共 {n} 条结果（最多显示 300 条，"
                                "每个设备只扫描最近 5000 条）")

    # ---------------- 跳转 ----------------

    def _on_jump(self, item):
        """双击结果：切到对应设备会话（不做消息定位，避免改动气泡身份）"""
        pid = (item.data(Qt.UserRole) or ("", None))[0]
        if not pid:
            return
        try:
            self.win._select_peer_by_id(pid)
        except Exception as e:
            self.win._toast(f"跳转失败：{e}")
            return
        self.accept()


class MainWindow(QMainWindow):
    ipcShow = Signal()          # 单实例 IPC：唤起主窗口

    def __init__(self, cfg, node: FlashNode, ipc_sock=None):
        super().__init__()
        self.cfg = cfg
        self.theme_setting = cfg["theme"]
        self.theme = self._effective_theme()
        # ★ v1.18.0：截图时是否隐藏当前窗口（下拉三角可切换，选择被记住）
        # 注意 cfg 在正式运行时是 Config 对象（只实现了 __getitem__，
        # **没有 dict 的 .get()**），仅在测试里才可能被注入成纯 dict。
        # 因此这里不能用 cfg.get(...)，要走 cfg["..."] + KeyError 兜底。
        try:
            self._snip_hide_self = bool(cfg["snip_hide_self"])
        except (KeyError, TypeError):
            self._snip_hide_self = True   # 老配置文件缺该键 → 沿用旧行为（隐藏）
        self._snip_overlay = None   # 取景遮罩引用（防被 GC 提前回收）
        self.setWindowTitle("闪传 FlashDrop · 局域网互传")
        self.resize(1080, 720)
        self.setMinimumSize(860, 560)
        self.setWindowIcon(make_app_icon())

        self.bridge = NodeBridge(node, self)
        self.history = History(max_per_peer=int(cfg["history_limit"]))
        self.peers = {}            # id -> snapshot
        self.unread = {}           # peer_id -> count
        self.msgs = {}             # peer_id -> [msg dict]
        self._partial = set()      # 懒加载前先收到新消息的 peer（列表不完整）
        self.out_by_tid = {}       # tid -> msg dict
        self.in_by_tid = {}        # (peer_id,tid) -> msg
        self.widgets_by_msg = {}   # id(msg) -> [BubbleFrame]
        # ★ v1.18.17：增量渲染用 —— 已渲染的消息 id 顺序 + 当时的视图标识
        self._rendered_ids = None
        self._rendered_key = None
        self._rebuilding = False

        # 多选删除状态
        self.multi_mode = False
        self.selected_ids = set()  # id(msg)
        self._manual_scanning = False

        self._build_ui()
        self._connect_signals()
        self.setStyleSheet(build_qss(self.theme))
        self._apply_native_titlebar()
        # 全局窗口标题栏主题同步（弹窗/消息框/文件对话框）
        QApplication.instance().installEventFilter(self)

        # 单实例 IPC：收到 SHOW 请求时唤起窗口
        self.ipc_sock = ipc_sock
        if ipc_sock is not None:
            self.ipcShow.connect(self._show_and_activate)
            self._start_ipc_listener()

        self.tray = QSystemTrayIcon(make_app_icon(), self)
        self.tray.setToolTip("闪传 FlashDrop")
        tm = QMenu()
        a_show = QAction("显示主窗口", self)
        a_show.triggered.connect(self._show_and_activate)
        a_quit = QAction("退出", self)
        a_quit.triggered.connect(self._real_quit)
        tm.addAction(a_show)
        tm.addAction(a_quit)
        self.tray.setContextMenu(tm)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

        self.bridge.start()
        QTimer.singleShot(1500, self._refresh_devices)
        QTimer.singleShot(1200, self._load_all_history)
        # ★ v1.18.18 性能 P2：空闲预热 —— 等 UI 与历史加载都稳定后：
        #   ① 清理超期磁盘缩略图（30 天）
        #   ② 预画常用文件类型图标（有缓存后这次画的会被所有气泡复用）
        QTimer.singleShot(3500, self._preheat_idle)
        self._update_self_info()
        self._pending_load()
        # 自检：启动 20 秒仍无任何设备 → 提示防火墙/代理
        QTimer.singleShot(20000, self._conn_selfcheck)
        # ★ v1.18.30：启动 5 秒后静默检查更新（每天最多一次；有新版本才弹窗）。
        #   国内直连 GitHub 偏慢，放启动任务之后，且 8s 超时失败即静默跳过。
        QTimer.singleShot(5000, self._auto_check_update)

    def _auto_check_update(self):
        try:
            if not updater.auto_check_allowed(self.cfg):
                return
        except Exception:
            return
        updater.mark_auto_checked(self.cfg)

        def _done(info):
            from .. import __version__
            if not info or not updater.is_newer(info.get("version", ""), __version__):
                return
            try:
                if updater.version_skipped(self.cfg, info.get("version", "")):
                    return
            except Exception:
                pass
            dlg = UpdateDialog(self.cfg, __version__, info, self)
            dlg.exec()

        c = UpdateChecker(self)     # 持有引用防 GC
        c.finished.connect(_done)
        self._upd_checker = c
        c.check()

    def _conn_selfcheck(self):
        if self.peers or not self.isVisible():
            return
        self._toast("未发现设备？请允许防火墙入站（设置→网络），"
                    "并检查代理/VPN 是否接管了局域网")

    # ================= 滚动与懒加载 =================

    def _on_scroll_changed(self, v):
        sb = self.chat_scroll.verticalScrollBar()
        self._stick_bottom = v >= sb.maximum() - max(
            self.chat_scroll.viewport().height(), 1) - 60
        if self._stick_bottom:
            self._hide_newmsg_btn()

    def _on_range_changed(self, a, b):
        sb = self.chat_scroll.verticalScrollBar()
        if self._stick_bottom:
            sb.setValue(b)
        elif self._new_msg_pending:
            self._new_msg_pending = False
            self._show_newmsg_btn()

    def _goto_bottom(self):
        sb = self.chat_scroll.verticalScrollBar()
        self._stick_bottom = True
        self._new_msg_pending = False
        sb.setValue(sb.maximum())
        self._hide_newmsg_btn()

    def _show_newmsg_btn(self):
        ih = self.input_panel.height() or 130
        self.newmsg_btn.adjustSize()
        self.newmsg_btn.move(max(8, self.width() - self.newmsg_btn.width() - 28),
                             max(8, self.height() - ih - 46))
        self.newmsg_btn.show()
        self.newmsg_btn.raise_()

    def _hide_newmsg_btn(self):
        self._new_msg_pending = False
        self.newmsg_btn.hide()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.newmsg_btn.isVisible():
            self._show_newmsg_btn()

    def _preheat_idle(self):
        """★ v1.18.18 性能 P2：空闲预热（一次性，3.5s 后触发）。

        刻意保持轻量：只做「磁盘 GC + 常用图标预画」，全部是毫秒级操作；
        不在空闲期批量解码缩略图 —— 用户可能正在打字/滚屏，抢主线程得不偿失。
        """
        try:
            import threading
            from .widgets import _thumb_gc
            # 磁盘 GC 是纯 IO，可放工作线程
            threading.Thread(target=lambda: _thumb_gc(30),
                             daemon=True).start()
        except Exception:
            pass
        # ★ v1.18.18 审计修复：图标预画必须回到 GUI 主线程 ——
        #   QPixmap 只允许在 GUI 线程创建/绘制（Qt 明确约束），
        #   在工作线程画会打 "QPixmap: It is not safe to use pixmaps
        #   outside the GUI thread" 并可能崩溃。QTimer.singleShot
        #   从主窗口触发，回调天然在主线程执行。
        try:
            QTimer.singleShot(0, self._preheat_icons)
        except Exception:
            pass

    def _preheat_icons(self):
        """主线程图标预画（make_file_icon 有缓存，画一次全局复用）"""
        try:
            from .widgets import make_file_icon
            for ext in ("pdf", "doc", "docx", "xls", "xlsx",
                        "ppt", "zip", "jpg", "png", "mp4", "txt"):
                make_file_icon("x." + ext)
        except Exception:
            # ★ 预热失败不影响功能，但要留痕（原来 except pass 把
            #   QPixmap 线程违规吞掉了，问题在开发期完全不可见）
            try:
                import traceback
                traceback.print_exc()
            except Exception:
                pass

    def _load_all_history(self):
        """懒加载：当前视图内尚未加载历史的设备，后台读盘（全部设备视图只读最近 80 条）"""
        full = self._view_is_single()
        ids = [pid for pid in self._view_peer_ids() if self._need_load(pid)]
        if not ids:
            self._render_chat()
            return

        def work():
            for pid in ids:
                self._ensure_loaded(pid, None if full else 80)
            QTimer.singleShot(0, self._render_chat)

        threading.Thread(target=work, daemon=True).start()

    def _view_is_single(self) -> bool:
        sel = [i.data(Qt.UserRole) for i in self.device_list.selectedItems()]
        return not (ALL_ID in sel or not sel)

    def _need_load(self, pid) -> bool:
        return pid not in self.msgs or pid in self._partial

    def _ensure_loaded(self, pid, limit=None):
        """加载设备历史；返回是否发生了加载（线程安全，由后台线程调用）

        ★ v1.18.35 修复（用户反馈"给新连接的手机发消息/收文件，消息框都是
          空的，但文件实际传过去了"）：旧实现 `self.msgs[pid] = msgs` 直接
          **整体替换**列表 —— 懒加载在后台线程读盘期间，主线程实时收到/发出
          的消息 append 在**旧列表对象**上，加载完成的一瞬被整体换掉。
          首联设备的第一批收发（恰是触发懒加载的那一批）因此全部从消息框
          消失；老设备早已加载完（_need_load=False）不会触发替换，所以
          只有"新连接的设备"必现。
          现改为**按消息身份合并**：磁盘读回的 + 加载期间内存里实时新增的，
          双端去重后按时间排序，实时消息不再被冲掉。
        """
        if not self._need_load(pid):
            return False
        msgs = self.history.load(pid, limit)
        old = self.msgs.get(pid)
        if old:
            seen = set()
            merged = []
            for m in list(msgs) + list(old):
                key = self._msg_identity(m)
                if key in seen:
                    continue
                seen.add(key)
                merged.append(m)
            merged.sort(key=lambda x: x.get("ts", 0))
            self.msgs[pid] = merged
        else:
            self.msgs[pid] = msgs
        self._partial.discard(pid)
        return True

    def _start_ipc_listener(self):
        """后台线程监听 UDP 锁端口。

        - 收到 SHOW → 唤起主窗口
        - 收到 PING → 回 PONG（告诉新实例「我活着，别抢锁」）

        ★ v1.18.35：main.py 的单实例锁在 bind 后**立即**起了
          responder 线程应答 PING（消灭"已 bind 未应答"启动窗口期，
          根治多开）。socket 只允许一个 reader —— 两个线程同时 recv
          会瓜分数据报。因此这里不再自起新线程，只把 SHOW 回调注册进
          responder（sock.fd_ipc_cb）；仅当锁 socket 无 responder 时
          （测试直接构造 MainWindow 等）才走原有自起线程路径。
        """
        import socket as _socket

        sock = self.ipc_sock
        cb = getattr(sock, "fd_ipc_cb", None) if sock is not None else None
        if cb is not None:
            cb["show"] = self.ipcShow.emit
            return

        def _loop():
            sock = self.ipc_sock
            try:
                sock.settimeout(1.0)
                while True:
                    try:
                        data, addr = sock.recvfrom(256)
                    except _socket.timeout:
                        continue
                    except OSError:
                        return          # 套接字被关闭（退出流程）
                    if b"PING" in data:
                        try:
                            sock.sendto(b"FlashDrop_PONG", addr)
                        except Exception:
                            pass
                    elif b"SHOW" in data:
                        self.ipcShow.emit()
            except Exception:
                pass

        threading.Thread(target=_loop, name="flashdrop-ipc", daemon=True).start()

    # ================= 构建界面 =================

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        side = QWidget()
        side.setObjectName("Sidebar")
        side.setFixedWidth(258)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(10, 14, 10, 10)
        sv.setSpacing(10)

        # 标题行：⚡ 闪传 + 本机信息两行（第一行设备名，第二行 IP·端口，小字单行）
        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title = QLabel("⚡ 闪传")
        title.setObjectName("AppTitle")
        title_row.addWidget(title)
        info_col = QVBoxLayout()
        info_col.setSpacing(0)
        self.self_name_lbl = QLabel("…")
        self.self_name_lbl.setObjectName("SelfInfoName")
        self.self_name_lbl.setWordWrap(False)
        self.self_ip_lbl = QLabel("…")
        self.self_ip_lbl.setObjectName("SelfIp")
        self.self_ip_lbl.setWordWrap(False)
        info_col.addWidget(self.self_name_lbl)
        info_col.addWidget(self.self_ip_lbl)
        title_row.addLayout(info_col, 1)
        sv.addLayout(title_row)

        self.device_list = QListWidget()
        self.device_list.setObjectName("DeviceList")
        self.device_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.device_list.itemSelectionChanged.connect(self._on_target_changed)
        # ★ v1.18.16（用户第 1 条）：设备列表右键菜单（删除 / 删除选中）
        self.device_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.device_list.customContextMenuRequested.connect(
            self._on_device_context_menu)
        self.device_list.setToolTip("提示：Ctrl / Shift 可多选，"
                                    "选中多个设备后下方会出现「删除选中」")
        sv.addWidget(self.device_list, 1)

        # 扫描状态（在底部按钮行上方；无内容时隐藏，不占一行空白）
        self.scan_lbl = QLabel("")
        self.scan_lbl.setStyleSheet(f"color:{self.theme['text_dim']};font-size:11px;")
        self.scan_lbl.setAlignment(Qt.AlignCenter)
        self.scan_lbl.setWordWrap(True)
        self.scan_lbl.hide()
        sv.addWidget(self.scan_lbl)

        # ★ v1.18.17（用户第 2 条）：多选操作行 —— 「删除选中 N 个」+「取消」
        #   仅在**多选（≥2 个真实设备）**时出现；单选不显示，避免误触。
        self.del_sel_row = QWidget()
        _dr = QHBoxLayout(self.del_sel_row)
        _dr.setContentsMargins(0, 0, 0, 0)
        _dr.setSpacing(8)
        self.del_sel_btn = QPushButton("删除选中的设备")
        self.del_sel_btn.setObjectName("DelSelBtn")
        self.del_sel_btn.setCursor(Qt.PointingHandCursor)
        self.del_sel_btn.setToolTip("删除选中设备的聊天记录、收到的文件与设备档案")
        self.del_sel_btn.setStyleSheet(
            "QPushButton { border: 1px solid #b91c1c; color: #b91c1c; "
            "background: transparent; border-radius: 6px; padding: 4px 10px; }"
            "QPushButton:hover { background: #b91c1c; color: #ffffff; }")
        self.del_sel_btn.clicked.connect(self._delete_selected_peers)
        self.del_cancel_btn = QPushButton("取消")
        self.del_cancel_btn.setObjectName("DelCancelBtn")
        self.del_cancel_btn.setCursor(Qt.PointingHandCursor)
        self.del_cancel_btn.setToolTip("退出多选（清空选择）")
        self.del_cancel_btn.setStyleSheet(
            "QPushButton { border: 1px solid #4b5563; color: #9ca3af; "
            "background: transparent; border-radius: 6px; padding: 4px 14px; }"
            "QPushButton:hover { background: #374151; color: #e5e7eb; }")
        self.del_cancel_btn.clicked.connect(self._cancel_multi_select)
        _dr.addWidget(self.del_sel_btn, 1)
        _dr.addWidget(self.del_cancel_btn, 0)
        self.del_sel_row.hide()
        sv.addWidget(self.del_sel_row)

        # 底部：添加 / 扫描 与设置齿轮并排（齿轮无外框）
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        add_btn = QPushButton("添加")
        add_btn.setToolTip("手动添加设备（IP:端口）")
        add_btn.clicked.connect(self._add_device)
        scan_btn = QPushButton("扫描")
        scan_btn.setToolTip("扫描常见子网，适用于多路由器环境")
        scan_btn.clicked.connect(self._deep_scan)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(scan_btn)
        btn_row.addStretch(1)
        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setFixedSize(34, 30)
        self.settings_btn.setToolTip("设置")
        self.settings_btn.setStyleSheet(
            "QPushButton { border: none; background: transparent; "
            "font-size: 17px; padding: 0; }"
            "QPushButton:hover { background: transparent; color: #3b82f6; }")
        self.settings_btn.setCursor(Qt.PointingHandCursor)
        self.settings_btn.clicked.connect(self._open_settings)
        btn_row.addWidget(self.settings_btn)
        sv.addLayout(btn_row)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)

        header = QWidget()
        header.setObjectName("ChatHeader")
        header.setFixedHeight(60)
        hv = QHBoxLayout(header)
        hv.setContentsMargins(18, 8, 14, 8)
        hcol = QVBoxLayout()
        hcol.setSpacing(1)
        self.header_title = QLabel("全部设备")
        self.header_title.setObjectName("ChatHeaderLabel")
        self.header_sub = QLabel("发送给所有在线设备")
        self.header_sub.setObjectName("ChatSub")
        hcol.addWidget(self.header_title)
        hcol.addWidget(self.header_sub)
        hv.addLayout(hcol, 1)
        self.header_actions = QHBoxLayout()
        self.header_actions.setSpacing(6)
        # v1.13.0：移除顶栏「⏳ 待发送 N」按钮。
        # 待发送内容现在以 pending 状态直接显示在聊天区的气泡里
        # （_show_pending_msg 已实现），设备一上线就自动投递，
        # 不再需要单独的管理入口/列表窗口。
        self.pending_btn = QPushButton("⏳ 待发送 0")
        self.pending_btn.setVisible(False)
        self.pending_btn.setEnabled(False)
        self.pending_btn.setMaximumWidth(0)
        open_dir_btn = QPushButton("📂 保存文件夹")
        open_dir_btn.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(self.cfg["save_dir"])))
        clear_btn = QPushButton("🧹 清空记录")
        clear_btn.clicked.connect(self._clear_chat)
        # ★ v1.18.18：聊天记录搜索
        search_btn = QPushButton("🔍 搜索")
        search_btn.setToolTip("搜索聊天内容 / 文件名（Ctrl+F）")
        search_btn.clicked.connect(self._open_search_window)
        multi_btn = QPushButton("☑ 多选")
        multi_btn.setToolTip("批量选择并删除消息（也可右键消息）；再次点击取消")
        multi_btn.clicked.connect(self._toggle_multi)
        self.multi_btn = multi_btn
        # ★ v1.18.18：Ctrl+F 打开搜索窗口（QShortcut 而非 keyPressEvent，
        #   这样焦点在输入框/列表里也能触发）
        self._search_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self._search_shortcut.activated.connect(self._open_search_window)
        # 注意：pending_btn 不再加入布局（保持创建是为了兼容 _update_pending_btn 的调用）
        self.header_actions.addWidget(open_dir_btn)
        self.header_actions.addWidget(clear_btn)
        self.header_actions.addWidget(search_btn)
        self.header_actions.addWidget(multi_btn)
        hv.addLayout(self.header_actions)

        self.chat_scroll = QScrollArea()
        self.chat_scroll.setObjectName("ChatScroll")
        self.chat_scroll.setWidgetResizable(True)
        container = QStackedWidget()
        container.setObjectName("ChatScroll")
        # ★ v1.18.17：聊天区改成"每视图一页"的栈。
        #   原来所有视图共用一个 QVBoxLayout，切设备必须销毁重建全部气泡
        #   （实测 200 条 ≈ 3000ms，非常卡）。现在每个视图的气泡页建一次就缓存下来，
        #   切换设备只是 setCurrentIndex —— 不再重建，切换近乎瞬时。
        self._chat_stack = container
        self._chat_pages = {}      # ckey -> (page QWidget, vbox)
        self._chat_page_order = [] # ckey 的 LRU 顺序
        self._chat_current_key = None
        page0 = QWidget()
        page0.setObjectName("ChatScrollPage")
        self.chat_vbox = QVBoxLayout(page0)
        self.chat_vbox.setAlignment(Qt.AlignTop)
        self.chat_vbox.setSpacing(10)
        self.chat_vbox.addStretch(1)
        container.addWidget(page0)
        self._chat_pages[("__init__", ())] = (page0, self.chat_vbox)
        self._chat_page_order = [("__init__", ())]
        self.chat_scroll.setWidget(container)
        sb = self.chat_scroll.verticalScrollBar()
        sb.valueChanged.connect(self._on_scroll_changed)
        sb.rangeChanged.connect(self._on_range_changed)
        self._stick_bottom = True      # 用户是否停在底部（决定是否自动滚动）
        self._new_msg_pending = False  # 不在底部时来了新消息

        # 飞书式"有新消息"下箭头提示（悬浮在聊天区右下角）
        self.newmsg_btn = QPushButton("⬇ 有新消息", self)
        self.newmsg_btn.setObjectName("NewMsgPill")
        self.newmsg_btn.hide()
        self.newmsg_btn.setCursor(Qt.PointingHandCursor)
        self.newmsg_btn.clicked.connect(self._goto_bottom)

        input_panel = QWidget()
        input_panel.setObjectName("InputPanel")
        self.input_panel = input_panel
        ipv = QVBoxLayout(input_panel)
        ipv.setContentsMargins(14, 10, 14, 10)
        ipv.setSpacing(8)
        tools = QHBoxLayout()
        tools.setSpacing(8)
        # ★ v1.18.10（用户第 4 条）：发送文件**之前**增加表情按钮。
        #   面板统一使用微软 Fluent Emoji（离线内置 assets/fluent_emoji/），
        #   点击后把 emoji 字符插入输入框光标处。
        self.emoji_btn = EmojiButton(self.theme)
        self.emoji_btn.setToolTip("插入表情（微软 Fluent Emoji）")
        self.emoji_btn.picked.connect(self._insert_emoji)
        file_btn = QPushButton("📎 发送文件")
        file_btn.clicked.connect(self._pick_files)
        img_btn = QPushButton("🖼 发送图片")
        img_btn.clicked.connect(self._pick_images)
        clip_btn = QPushButton("📋 发送剪贴板")
        clip_btn.clicked.connect(self._send_clipboard)
        # ★ v1.16.0：底部工具行新增「截图」
        # ★ v1.18.0：截图按钮改为**带下拉三角**的组合控件（对齐微信）——
        #   主按钮直接用上次的"是否隐藏窗口"设置执行；
        #   右侧小三角展开可切换该设置。用 QToolButton + InstantPopup 实现，
        #   视觉上是一个按钮、右侧一条细分隔 + ▼。
        # ★ v1.18.8：修复「截图」与左侧三个 QPushButton 视觉不一致——
        #   根因是 QToolButton 在 theme.py 里**没有任何 QSS 规则**，
        #   走 Windows 原生 Fusion 绘制：无卡片底色/无圆角/边框发灰，
        #   且 sizeHint 比 QPushButton 矮，导致同一 HBox 里高度对不齐。
        #   修法：① theme.py 补 QToolButton 通用样式（padding/font 对齐
        #   QPushButton）；② SnipMain/SnipArrow 用 objectName 只保留半边
        #   圆角 + 去掉相邻边框，拼成一个整体，中间不留缝。
        shot_box = QWidget()
        shot_lay = QHBoxLayout(shot_box)
        shot_lay.setContentsMargins(0, 0, 0, 0)
        shot_lay.setSpacing(0)

        shot_btn = QToolButton()
        shot_btn.setObjectName("SnipMain")
        shot_btn.setText("✂ 截图")
        # 显式指定纯文字风格：默认 ToolButtonIconOnly 在部分平台会把
        # 文本压成 "…"，这是"看着不一样"的另一个来源。
        shot_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        shot_btn.setToolTip("抓取屏幕并框选区域（点击右侧 ▼ 可切换是否隐藏当前窗口）")
        shot_btn.setCursor(Qt.PointingHandCursor)
        shot_btn.clicked.connect(self._screenshot)

        shot_arrow = QToolButton()
        shot_arrow.setObjectName("SnipArrow")
        shot_arrow.setText("▾")
        shot_arrow.setToolButtonStyle(Qt.ToolButtonTextOnly)
        shot_arrow.setToolTip("截图选项：是否隐藏当前窗口")
        shot_arrow.setCursor(Qt.PointingHandCursor)
        shot_arrow.setPopupMode(QToolButton.InstantPopup)
        shot_arrow.setArrowType(Qt.NoArrow)   # 自绘字符箭头，视觉更紧凑
        shot_menu = QMenu(shot_arrow)
        shot_arrow.setMenu(shot_menu)

        # 菜单内容在每次弹出前重建，保证勾选状态实时反映 _snip_hide_self
        def _fill_shot_menu():
            shot_menu.clear()
            a_hide = QAction("截图时隐藏当前窗口", self)
            a_hide.setCheckable(True)
            a_hide.setChecked(self._snip_hide_self)
            a_keep = QAction("截图时保留当前窗口", self)
            a_keep.setCheckable(True)
            a_keep.setChecked(not self._snip_hide_self)

            def pick(hide):
                self._snip_hide_self = hide
                self._remember_snip_hide(hide)
                self._toast("截图时将%s当前窗口"
                            % ("隐藏" if hide else "保留"))
                self._start_snip(hide_self=hide)

            a_hide.triggered.connect(lambda: pick(True))
            a_keep.triggered.connect(lambda: pick(False))
            shot_menu.addAction(a_hide)
            shot_menu.addAction(a_keep)

        shot_menu.aboutToShow.connect(_fill_shot_menu)

        shot_lay.addWidget(shot_btn)
        shot_lay.addWidget(shot_arrow)

        tools.addWidget(self.emoji_btn)
        tools.addWidget(file_btn)
        tools.addWidget(img_btn)
        tools.addWidget(clip_btn)
        tools.addWidget(shot_box)
        tools.addStretch(1)
        self.online_lbl = QLabel("")
        self.online_lbl.setStyleSheet(f"color:{self.theme['text_dim']};font-size:11px;")
        tools.addWidget(self.online_lbl)
        ipv.addLayout(tools)

        edit_row = QHBoxLayout()
        edit_row.setSpacing(8)
        self.input_edit = QPlainTextEdit()
        self.input_edit.setPlaceholderText(
            "输入消息，Enter 发送，Shift+Enter 换行；可直接粘贴或拖入文件…")
        self.input_edit.setFixedHeight(64)
        self.input_edit.setAcceptDrops(False)
        self.input_edit.installEventFilter(self)
        self.input_edit.setContextMenuPolicy(Qt.CustomContextMenu)
        self.input_edit.customContextMenuRequested.connect(self._input_menu)
        edit_row.addWidget(self.input_edit, 1)
        send_btn = QPushButton("发送")
        send_btn.setObjectName("Primary")
        send_btn.setFixedSize(84, 64)
        send_btn.clicked.connect(self._send_input)
        edit_row.addWidget(send_btn)
        ipv.addLayout(edit_row)

        # 多选操作栏（默认隐藏；取消由顶部多选按钮切换）
        self.select_bar = QWidget()
        self.select_bar.setObjectName("ChatHeader")
        self.select_bar.setFixedHeight(44)
        sbh = QHBoxLayout(self.select_bar)
        sbh.setContentsMargins(18, 4, 14, 4)
        self.select_count_lbl = QLabel("已选择 0 条")
        self.select_count_lbl.setStyleSheet(f"color:{ACCENT};font-weight:600;")
        sbh.addWidget(self.select_count_lbl)
        sbh.addStretch(1)
        sel_all_btn = QPushButton("全选")
        sel_all_btn.clicked.connect(self._select_all_visible)
        sel_del_btn = QPushButton("删除")
        sel_del_btn.setObjectName("Danger")
        sel_del_btn.clicked.connect(self._delete_selected)
        sbh.addWidget(sel_all_btn)
        sbh.addWidget(sel_del_btn)
        self.select_bar.hide()

        rv.addWidget(header)
        rv.addWidget(self.select_bar)
        rv.addWidget(self.chat_scroll, 1)
        rv.addWidget(input_panel)

        root.addWidget(side)
        root.addWidget(right, 1)
        self.setAcceptDrops(True)

    def eventFilter(self, obj, ev):
        # 应用级过滤：任何窗口（设置弹窗/消息框/文件对话框）显示时同步标题栏主题
        if ev.type() == QEvent.Show and isinstance(obj, QWidget) and obj.isWindow():
            self._apply_titlebar_to(obj)
        if obj is self.input_edit and ev.type() == QEvent.KeyPress:
            if ev.key() in (Qt.Key_Return, Qt.Key_Enter) and not ev.modifiers() & Qt.ShiftModifier:
                self._send_input()
                return True
            # Ctrl+V：剪贴板里是图片时直接发送（微信习惯）
            if ev.matches(QKeySequence.Paste):
                if not QApplication.clipboard().image().isNull():
                    self._send_clipboard_image()
                    return True
        return super().eventFilter(obj, ev)

    def _input_menu(self, pos):
        """输入框中文右键菜单（默认菜单为英文且部分动作不可用）"""
        edit = self.input_edit
        m = QMenu(self)
        clip = QApplication.clipboard()
        has_sel = edit.textCursor().hasSelection()
        a_paste_img = (m.addAction("粘贴并发送图片")
                       if not clip.image().isNull() else None)
        a_paste = m.addAction("粘贴")
        a_copy = m.addAction("复制")
        a_cut = m.addAction("剪切")
        m.addSeparator()
        a_undo = m.addAction("撤销")
        a_undo.setEnabled(edit.canUndo())
        a_redo = m.addAction("重做")
        a_redo.setEnabled(edit.canRedo())
        m.addSeparator()
        a_all = m.addAction("全选")
        a_all.setEnabled(bool(edit.toPlainText()))
        a_clear = m.addAction("清空")
        a_clear.setEnabled(bool(edit.toPlainText()))
        chosen = m.exec(edit.mapToGlobal(pos))
        if chosen is None:
            return
        if a_paste_img is not None and chosen == a_paste_img:
            self._send_clipboard_image()
        elif chosen == a_paste:
            edit.paste()
        elif chosen == a_copy and has_sel:
            edit.copy()
        elif chosen == a_cut and has_sel:
            edit.cut()
        elif chosen == a_undo:
            edit.undo()
        elif chosen == a_redo:
            edit.redo()
        elif chosen == a_all:
            edit.selectAll()
        elif chosen == a_clear:
            edit.clear()

    def _connect_signals(self):
        self.bridge.peersChanged.connect(self._on_peers)
        # ★ v1.18.15：待发补发在工作线程执行，结果用信号回 UI 线程提交
        self.bridge.pendingFlushDone.connect(self._finish_pending_flush)
        self.bridge.textReceived.connect(self._on_text_in)
        self.bridge.textState.connect(self._on_text_state)
        self.bridge.ackReceived.connect(self._on_ack)
        self.bridge.transferEvent.connect(self._on_transfer)
        self.bridge.logMessage.connect(self._on_log)
        self.bridge.scanDone.connect(self._on_scan_done)
        self.bridge.peerMerged.connect(self._on_peer_merged)

    def _on_peer_merged(self, old_id, new_id):
        """同机跨版本设备身份合并：聊天记录与未读数迁移到新 ID"""
        if not old_id or not new_id or old_id == new_id:
            return
        self.history.merge(old_id, new_id)
        old_msgs = self.msgs.pop(old_id, None)
        if old_msgs:
            lst = self.msgs.setdefault(new_id, [])
            seen = {self._msg_identity(m) for m in lst}
            for m in old_msgs:
                if self._msg_identity(m) not in seen:
                    lst.append(m)
            lst.sort(key=lambda x: x.get("ts", 0))
        if self.unread.get(old_id):
            self.unread[new_id] = self.unread.get(new_id, 0) + self.unread.pop(old_id)
        else:
            self.unread.pop(old_id, None)
        self._render_chat()

    # ================= 设备列表 =================

    def _effective_theme(self) -> dict:
        """解析主题 + 注入气泡配色方案"""
        t = dict(resolve_theme(self.cfg["theme"]))
        sch = bubble_scheme(self.cfg["bubble_scheme"])
        t["scheme_out"] = sch["out"]
        t["scheme_out_text"] = sch["out_text"]
        return t

    def _update_self_info(self):
        from .. import netinfo
        ips = [i.ip for i in netinfo.get_local_ifaces()] or ["127.0.0.1"]
        # 两行小字、严格单行：超长用省略号截断
        fm_n = QFontMetrics(self.self_name_lbl.font())
        fm_i = QFontMetrics(self.self_ip_lbl.font())
        self.self_name_lbl.setText(
            fm_n.elidedText(self.cfg["name"], Qt.ElideRight, 150))
        ip_text = f"{', '.join(ips)} · 端口 {self.cfg['port']}"
        self.self_ip_lbl.setText(fm_i.elidedText(ip_text, Qt.ElideRight, 150))
        # 主题跟随系统：定期检查系统深浅色变化
        if self.cfg["theme"] == "system":
            new_t = resolve_theme("system")
            if new_t["name"] != self.theme["name"]:
                self._apply_theme()
        QTimer.singleShot(5000, self._update_self_info)

    def _apply_theme(self):
        """应用当前设置的主题（dark/light/system）并整体刷新"""
        self.theme = self._effective_theme()
        self.theme_setting = self.cfg["theme"]
        self.setStyleSheet(build_qss(self.theme))
        self._render_chat()
        self._apply_native_titlebar()

    def _apply_native_titlebar(self):
        """让 Windows 系统标题栏跟随深浅主题（Win10 1809+ / Win11）"""
        self._apply_titlebar_to(self)

    def _apply_titlebar_to(self, w):
        """对指定窗口应用 DWM 深色/浅色标题栏"""
        if sys.platform != "win32" or not isinstance(w, QWidget):
            return
        try:
            hwnd = int(w.winId())
            dark = 1 if self.theme.get("name") == "dark" else 0
            for attr in (20, 19):  # 20=1809+，19=旧版回退
                res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    ctypes.c_void_p(hwnd), attr,
                    ctypes.byref(ctypes.c_int(dark)), 4)
                if res == 0:
                    break
        except Exception:
            pass

    def _refresh_devices(self):
        self._on_peers(self.bridge.node.peers_snapshot())

    def _on_peers(self, peers: list):
        """刷新左侧设备列表。

        ★ v1.18.9：合并「实时发现的在线设备」与「已知设备档案 known_peers」，
        这样设备**离开同一网络后仍留在列表里**（灰灯），可以：
          · 继续查看该会话的历史消息（聊天记录不再因为换网络而"消失"）
          · 给它发离线消息（进待发队列，对方上线自动补发）
        由设置里的「离线聊天」开关控制是否列出离线设备。
        """
        live = {p["id"]: p for p in peers if p["id"] != ALL_ID}
        # 记录最新档案（含下线设备），供下次启动/离线时使用
        self._remember_known_peers(live)
        show_offline = bool(self.cfg["offline_chat"])
        merged = dict(live)
        if show_offline:
            for pid, kp in (self.cfg["known_peers"] or {}).items():
                if pid in merged:
                    continue
                merged[pid] = {"id": pid, "name": kp.get("name") or "未知设备",
                               "platform": kp.get("platform") or "windows",
                               "ips": kp.get("ips") or [], "online": False,
                               "connected": False}
        self.peers = merged
        for pid in self.peers:  # 加载历史
            if pid not in self.msgs:
                self.msgs[pid] = self.history.load(pid)

        sel_ids = {i.data(Qt.UserRole) for i in self.device_list.selectedItems()}
        self._rebuilding = True
        self.device_list.blockSignals(True)
        self.device_list.clear()
        allw = DeviceItemWidget({"id": ALL_ID, "name": "全部设备", "platform": "windows",
                                 "ips": [], "online": True, "connected": True},
                                dim=self.theme["text_dim"])
        it = QListWidgetItem(self.device_list)
        it.setData(Qt.UserRole, ALL_ID)
        it.setSizeHint(self._size(56))
        self.device_list.addItem(it)
        self.device_list.setItemWidget(it, allw)
        # 在线优先、其次按名字；离线设备排后面
        ordered = sorted(self.peers.values(),
                         key=lambda p: (not p.get("online"),
                                        (p.get("name") or "")))
        for p in ordered:
            # ★ v1.18.17：行内 ✕ 删除入口已移除，删除统一走右击菜单 / 多选底部按钮
            # ★ v1.18.18：列表显示备注名（不改 p 本身 —— p 是节点数据，
            #   写进去会污染排序键与 known_peers 落盘内容）
            snap = dict(p)
            snap["name"] = self._display_name(p["id"])
            w = DeviceItemWidget(snap, unread=self.unread.get(p["id"], 0),
                                 dim=self.theme["text_dim"])
            it = QListWidgetItem(self.device_list)
            it.setData(Qt.UserRole, p["id"])
            it.setSizeHint(self._size(56))
            self.device_list.addItem(it)
            self.device_list.setItemWidget(it, w)
        restored = False
        for i in range(self.device_list.count()):
            if self.device_list.item(i).data(Qt.UserRole) in sel_ids:
                self.device_list.item(i).setSelected(True)
                restored = True
        if not restored:
            self.device_list.item(0).setSelected(True)
        self.device_list.blockSignals(False)
        self._rebuilding = False
        self._on_target_changed()
        # ★ v1.18.16：列表重建后 _rebuilding 拦住了信号，这里补一次按钮刷新
        self._update_del_sel_btn()
        self._flush_pending()

    def _remember_known_peers(self, live: dict):
        """把当前在线设备写入配置的 known_peers（持久化，跨网络不丢）"""
        kp = dict(self.cfg["known_peers"] or {})
        changed = False
        now = int(time.time())
        for pid, p in live.items():
            rec = kp.get(pid) or {}
            new = {"id": pid,
                   "name": p.get("name") or rec.get("name") or "",
                   "platform": p.get("platform") or rec.get("platform") or "",
                   "ips": list(p.get("ips") or []),
                   "last_seen": now}
            if rec != new:
                kp[pid] = new
                changed = True
        if changed:
            self.cfg["known_peers"] = kp
            try:
                saver = getattr(self.cfg, "save", None)
                if callable(saver):
                    saver()
            except Exception:
                pass

    # ---------- 设备删除（v1.18.16：右键删除 + 多选全部删除） ----------

    def _deletable_selected_ids(self):
        """当前选中、且**允许删除**的设备 id 列表。

        ★ v1.18.16：「全部设备」(ALL_ID) 是固定的聚合视图，没有对应档案、
          没有专属文件夹，**不允许删除** —— 一律在这里挡掉。
        """
        out = []
        for i in self.device_list.selectedItems():
            pid = i.data(Qt.UserRole)
            if not pid or pid == ALL_ID or pid == self.PENDING_PEER:
                continue
            out.append(pid)
        return out

    def _update_del_sel_btn(self):
        """★ v1.18.17：**仅多选（≥2 个真实设备）**时显示底部操作行。

        v1.18.16 是 n >= 1 就显示，用户反馈"单选底部就有删除"——
        单击就删、误触风险高。现在单选不显示，必须明确多选（Ctrl/Shift）
        才出现「删除选中 + 取消」。
        """
        row = getattr(self, "del_sel_row", None)
        if row is None:
            return
        n = len(self._deletable_selected_ids())
        if n >= 2:
            self.del_sel_btn.setText(f"删除选中的 {n} 个设备")
            row.show()
        else:
            row.hide()

    def _cancel_multi_select(self):
        """取消多选：清空选择并回到「全部设备」视图"""
        self.device_list.blockSignals(True)
        self.device_list.clearSelection()
        self.device_list.blockSignals(False)
        it = self.device_list.item(0)
        if it is not None:
            it.setSelected(True)
        self._update_del_sel_btn()
        self._on_target_changed()

    def _build_device_menu(self, pos):
        """构造设备列表右键菜单；返回 QMenu（不弹出）。

        ★ 独立出来是为了可测试：菜单内容可以直接断言，不必真的 exec 模态框。
        """
        item = self.device_list.itemAt(pos)
        menu = QMenu(self)
        if item is not None:
            pid = item.data(Qt.UserRole)
            # 惯例：右键在哪一项就选中哪一项（不打断已有多选）
            if pid and not item.isSelected():
                self.device_list.clearSelection()
                item.setSelected(True)
            if pid == ALL_ID:
                act = menu.addAction("「全部设备」是固定视图，不可删除")
                act.setEnabled(False)
            elif pid == self.PENDING_PEER:
                act = menu.addAction("「待发送」不是设备，不可删除")
                act.setEnabled(False)
            elif pid:
                name = self._display_name(pid)
                # ★ v1.18.18：设备备注/别名。备注只改本机显示，
                #   不影响对端自报名（否则两端互相覆盖）。
                cur_alias = self._peer_alias(pid)
                menu.addAction(f"备注此设备（当前：{cur_alias}）…"if cur_alias
                               else "给此设备起备注…",
                               lambda p=pid: self._rename_peer(p))
                menu.addAction("清除备注", lambda p=pid: self._clear_peer_alias(p))
                menu.addSeparator()
                menu.addAction(f"删除「{name}」的会话",
                               lambda p=pid: self._delete_peer_conversation(p))
        sel = self._deletable_selected_ids()
        if len(sel) > 1:
            if menu.actions():
                menu.addSeparator()
            menu.addAction(f"删除选中的 {len(sel)} 个设备",
                           self._delete_selected_peers)
        return menu if menu.actions() else None

    # ---------- v1.18.18 设备备注 ----------

    def _display_name(self, pid):
        """显示名：备注 > 自报名 > id 前 8 位。

        ★ 查**UI 侧** self.peers 而不是 node.peers：
          离线设备只存在于 UI 的合并视图里（v1.18.9 行为把 known_peers
          合并进来），node.peers 只有当前在线/已连设备。
          只查 node.peers 会让离线设备一律退化成 id 前 8 位。
        """
        try:
            alias = self._peer_alias(pid)
            if alias:
                return alias
        except Exception:
            pass
        name = (self.peers.get(pid) or {}).get("name")
        if not name:
            try:
                name = self.bridge.node.display_name(pid)
            except Exception:
                name = ""
        if not name:
            rec = (self.cfg["known_peers"] or {}).get(pid) or {}
            name = rec.get("name") or ""
        return name or (pid or "")[:8]

    def _peer_alias(self, pid):
        try:
            return (self.bridge.node.get_alias(pid) or "").strip()
        except Exception:
            return ""

    def _rename_peer(self, pid):
        """弹出输入框设置设备备注"""
        if not pid or pid == ALL_ID or pid == self.PENDING_PEER:
            return
        cur = self._peer_alias(pid)
        try:
            text, ok = QInputDialog.getText(
                self, "设备备注",
                f"给「{self._display_name(pid)}」起个备注：\n"
                "（仅本机显示，不影响对方；留空可清除）",
                QLineEdit.Normal, cur)
        except Exception:
            return
        if not ok:
            return
        text = (text or "").strip()[:40]
        if not text:
            self._clear_peer_alias(pid)
            return
        try:
            self.bridge.node.set_alias(pid, text)
        except Exception as e:
            self._toast(f"备注保存失败：{e}")
            return
        # 已有气泡的头像/标题也要跟着变
        self._refresh_peer_name_in_chat(pid)
        self._toast(f"已备注为「{text}」")

    def _clear_peer_alias(self, pid):
        if not pid:
            return
        try:
            if not self.bridge.node.get_alias(pid):
                self._toast("该设备还没有备注")
                return
            self.bridge.node.set_alias(pid, "")
        except Exception as e:
            self._toast(f"清除备注失败：{e}")
            return
        self._refresh_peer_name_in_chat(pid)
        self._toast("已清除备注，恢复显示设备原名")

    def _refresh_peer_name_in_chat(self, pid):
        """备注变更后，刷新历史气泡里显示的设备名（头像种子/标题）"""
        new = self._display_name(pid)
        touched = 0
        for m in self.msgs.get(pid, []):
            if m.get("dir") == "out":
                continue
            if m.get("peer_name") != new:
                m["peer_name"] = new
                for w in self.widgets_by_msg.get(id(m), []):
                    try:
                        w.update_msg(m)
                    except Exception:
                        pass
                touched += 1
        if touched:
            self._render_chat()

    def _on_device_context_menu(self, pos):
        """设备列表右键菜单（只弹出，不在此处执行动作）"""
        menu = self._build_device_menu(pos)
        if menu is None:
            return
        menu.exec(self.device_list.viewport().mapToGlobal(pos))

    def _delete_selected_peers(self):
        """★ v1.18.16：删除当前选中的全部设备（一次确认，动作批量执行）"""
        ids = self._deletable_selected_ids()
        if not ids:
            self._toast("请先在左侧列表选中要删除的设备（Ctrl / Shift 可多选）")
            return
        names = []
        for pid in ids:
            names.append(self._display_name(pid))
        if len(ids) == 1:
            body = f"确定删除与「{names[0]}」的整个会话吗？"
        else:
            body = ("确定删除以下 %d 个设备的整个会话吗？\n\n%s\n"
                    % (len(ids), "、".join(names)))
        if not confirm(self, "删除会话",
                       body + "\n\n将同时删除本机保存的聊天记录与收到的文件，"
                              "且不可恢复。",
                       ok_text="全部删除" if len(ids) > 1 else "删除"):
            return
        for pid in ids:
            self._do_delete_peer(pid)
        self._save_cfg()
        self._refresh_devices()
        self._update_del_sel_btn()
        self._toast(f"已删除 {len(ids)} 个设备的会话（记录 / 文件 / 设备档案）")

    def _delete_peer_conversation(self, pid: str):
        """删除某个设备的整个会话：聊天记录 + 收发文件 + 设备档案"""
        if pid == ALL_ID:
            self._toast("「全部设备」是固定视图，不可删除")
            return
        name = self._display_name(pid)
        if not confirm(self, "删除会话",
                       f"确定删除与「{name}」的整个会话吗？\n"
                       "将同时删除本机保存的聊天记录与收到的文件，且不可恢复。",
                       ok_text="删除"):
            return
        self._do_delete_peer(pid)
        self._save_cfg()
        self._refresh_devices()
        self._update_del_sel_btn()
        self._toast(f"已删除与「{name}」的会话")

    def _do_delete_peer(self, pid: str):
        """真正删除单个设备的全部数据（不弹确认、不刷新界面）

        范围：磁盘聊天记录 + 内存消息与索引 + 接收文件夹 + 设备档案(known_peers)。
        「全部设备」(ALL_ID) 不走这里 —— 它没有档案也没有专属文件夹。
        """
        if not pid or pid == ALL_ID:
            return
        # ★ 这里必须用设备**自报名**（不是备注）—— 它要拼接收文件夹路径，
        #   文件夹是按自报名建的；若换成备注名会"删不掉旧文件夹"。
        name = (self.peers.get(pid) or {}).get("name") or pid
        # 1) 删磁盘聊天记录
        try:
            self.history.clear(pid)
        except Exception:
            pass
        # 2) 删内存中的消息与索引
        self.msgs.pop(pid, None)
        # tid → msg 索引也要摘干净：出向按 target 命中该设备、入向按 peer_id
        self.out_by_tid = {k: v for k, v in self.out_by_tid.items()
                           if pid not in (v.get("targets") or [])
                           and v.get("peer_id") != pid}
        self.in_by_tid = {k: v for k, v in self.in_by_tid.items()
                          if v.get("peer_id") != pid}
        # 出向消息也可能散在别人的会话树里（群发），一并从内存里剔除
        for other, lst in list(self.msgs.items()):
            self.msgs[other] = [
                m for m in lst
                if not (pid == m.get("peer_id")
                        or pid in (m.get("targets") or []))
            ]
        self.unread.pop(pid, None)
        # 3) 删该设备发来的已落盘文件（保存目录下的设备子文件夹）
        try:
            self._remove_peer_files(pid, name)
        except Exception:
            pass
        # 4) 从 known_peers 移除；若仍在线则保留实时项
        kp = dict(self.cfg["known_peers"] or {})
        kp.pop(pid, None)
        self.cfg["known_peers"] = kp
        # 5) ★ v1.18.18：清掉设备备注，否则留下永远不会再显示的孤儿条目
        try:
            aliases = dict(self.cfg["peer_aliases"] or {})
            if aliases.pop(pid, None) is not None:
                self.cfg["peer_aliases"] = aliases
        except Exception:
            pass

    def _save_cfg(self):
        """把配置落盘（删除设备档案后必须调用）"""
        try:
            saver = getattr(self.cfg, "save", None)
            if callable(saver):
                saver()
        except Exception:
            pass

    def _remove_peer_files(self, pid, name):
        """删除该设备对应的接收文件夹（按设备名建的那种）"""
        import shutil as _sh
        safe = "".join(c if c not in '\\/:*?"<>|' else "_" for c in (name or ""))
        base = self.cfg["save_dir"]
        if not base or not safe:
            return
        target = os.path.join(base, safe)
        # 只删保存目录下的直接子目录，绝不动 base 本身
        if os.path.isdir(target) and os.path.abspath(target) != os.path.abspath(base):
            _sh.rmtree(target, ignore_errors=True)

    def _update_header_online(self):
        """全部设备视图的在线数（直接取快照 online 字段，避免不同步）"""
        n_online = sum(1 for p in self.peers.values() if p.get("online"))
        self.header_sub.setText(f"群发模式 · 消息发送给所有在线设备（当前 {n_online} 台）")
        self.online_lbl.setText(f"在线设备 {n_online}")

    @staticmethod
    def _size(h):
        from PySide6.QtCore import QSize
        return QSize(238, h)

    def _targets(self) -> list:
        """当前可立即发送的在线目标（v1.9.0 起主流程走 _resolve_targets，
        此方法保留给既有调用方/测试）"""
        return self._resolve_targets()[0]

    def _view_peer_ids(self) -> list:
        sel = [i.data(Qt.UserRole) for i in self.device_list.selectedItems()]
        # 待发送消息始终可见（挂在 PENDING_PEER 下，不属于任何具体设备）
        if ALL_ID in sel or not sel:
            # 全部设备视图：包含历史记录中的设备（即使当前离线/未知）
            return list(set(self.peers.keys()) | set(self.msgs.keys())
                        | set(self.history.all_peer_ids()))
        return [s for s in sel if s != ALL_ID] + [self.PENDING_PEER]

    def current_peer(self) -> str:
        """当前单选的设备 id（群发/待发送视图返回空串）"""
        sel = [i.data(Qt.UserRole) for i in self.device_list.selectedItems()]
        if len(sel) == 1 and sel[0] not in (ALL_ID, self.PENDING_PEER):
            return sel[0]
        return ""

    def _select_peer_by_id(self, pid: str) -> bool:
        """按设备 id 选中左侧列表项并渲染对应会话（搜索结果跳转用）。

        ★必须同时提供历史记录里存在、但当前 peers 里没有的设备 ——
        设备已离线/被删档案时聊天记录仍在，这种"孤儿记录"也要能打开。
        """
        if not pid:
            return False
        self.device_list.blockSignals(True)
        found = False
        for i in range(self.device_list.count()):
            if self.device_list.item(i).data(Qt.UserRole) == pid:
                self.device_list.clearSelection()
                self.device_list.item(i).setSelected(True)
                found = True
                break
        if not found:
            # 设备不在列表里（离线且无档案）：补一个临时项再选中
            rec = (self.cfg["known_peers"] or {}).get(pid) or {}
            snap = {"id": pid, "name": rec.get("name") or pid[:8],
                    "platform": rec.get("platform") or "", "online": False,
                    "ip": rec.get("ip") or ""}
            self.peers.setdefault(pid, snap)
            it = QListWidgetItem(self.device_list)
            it.setData(Qt.UserRole, pid)
            it.setSizeHint(self._size(56))
            self.device_list.addItem(it)
            self.device_list.clearSelection()
            it.setSelected(True)
            self.device_list.setItemWidget(
                it, DeviceItemWidget(snap, unread=self.unread.get(pid, 0),
                                     dim=self.theme["text_dim"]))
        self.device_list.blockSignals(False)
        self._on_target_changed()
        return True

    def _open_search_window(self, keyword: str = ""):
        """打开聊天记录搜索窗口"""
        dlg = SearchWindow(self, keyword or "")
        dlg.exec()

    def _on_target_changed(self):
        if self._rebuilding:
            return
        # ★ v1.18.16：选中变化时同步「删除选中」按钮的显隐与计数
        self._update_del_sel_btn()
        sel = [i.data(Qt.UserRole) for i in self.device_list.selectedItems()]
        if ALL_ID in sel or not sel:
            self.header_title.setText("全部设备")
            n_online = sum(1 for p in self.peers.values() if p.get("online"))
            self.header_sub.setText(f"群发模式 · 消息发送给所有在线设备（当前 {n_online} 台）")
        else:
            names = [self._display_name(s) for s in sel if s in self.peers]
            self.header_title.setText("、".join(names) if names else "未选择设备")
            self.header_sub.setText(f"已选择 {len(sel)} 台设备，发送时将同步送达")
        for pid in self._view_peer_ids():
            self.unread.pop(pid, None)
        self._render_chat()
        self._load_all_history()

    # ================= 聊天渲染 =================

    def _visible_msgs(self) -> list:
        ids = set(self._view_peer_ids())
        seen = set()
        out = []
        # ★ v1.18.9：「全部设备」视图 = **纯群聊视图**。
        #   只显示真正在群聊里发过的消息（channel == "group"）与待发送项；
        #   端到端私聊（channel == "p2p"）的内容不在这里混着展示。
        #   与安卓端 belongsToView() 的判定口径保持一致。
        sel = [i.data(Qt.UserRole) for i in self.device_list.selectedItems()]
        all_view = (ALL_ID in sel) or (not sel)
        for pid in ids:
            for m in self.msgs.get(pid, []):
                if id(m) in seen:
                    continue
                if all_view and pid != self.PENDING_PEER:
                    ch = m.get("channel")
                    if ch == "p2p":
                        # 端到端私聊：明确标记过就不进「全部设备」群聊视图
                        continue
                    # ch == "group"  —— 群聊，可见
                    # ch is None      —— 老数据（v1.18.9 之前未打标），
                    #                    无标记可依据，保守起见仍然可见，
                    #                    避免老用户的聊天记录凭空消失。
                    # 注：挂在外层 peers 下的老数据没有明确 channel，
                    #     一律保留；判断"是否是群聊"交给后续版本迁移。
                seen.add(id(m))
                out.append(m)
        out.sort(key=lambda m: m.get("ts", 0))
        return out[-300:]

    def _chat_view_key(self):
        """当前视图的标识：选中了哪些设备 + 是否处于多选态"""
        sel = [i.data(Qt.UserRole) for i in self.device_list.selectedItems()]
        return (tuple(sel), bool(self.multi_mode))

    _CHAT_PAGE_CAP = 8      # 最多缓存几个视图的气泡页（超出按 LRU 丢弃）

    def _build_chat_page(self, ckey, msgs):
        """新建一个气泡页并把 msgs 全建进去"""
        page = QWidget()
        page.setObjectName("ChatScrollPage")
        vbox = QVBoxLayout(page)
        vbox.setAlignment(Qt.AlignTop)
        vbox.setSpacing(10)
        vbox.addStretch(1)
        saved_vbox, saved_map = self.chat_vbox, self.widgets_by_msg
        self.chat_vbox, self.widgets_by_msg = vbox, {}
        try:
            for m in msgs:
                self._append_bubble(m)
        finally:
            built_map = self.widgets_by_msg
            self.chat_vbox, self.widgets_by_msg = saved_vbox, saved_map
        self._chat_stack.addWidget(page)
        mids = [id(m) for m in msgs]
        self._chat_pages[ckey] = (page, vbox, built_map, mids)
        self._chat_page_order = [k for k in self._chat_page_order if k != ckey]
        self._chat_page_order.append(ckey)
        # LRU 淘汰：别让长时间使用把内存堆满
        while len(self._chat_page_order) > self._CHAT_PAGE_CAP:
            old = self._chat_page_order.pop(0)
            if old == self._chat_current_key or old == ("__init__", ()):
                self._chat_page_order.append(old)
                continue
            rec = self._chat_pages.pop(old, None)
            if rec:
                self._chat_stack.removeWidget(rec[0])
                rec[0].deleteLater()
        return page, vbox, built_map, mids

    def _switch_chat_page(self, ckey):
        """把缓存的气泡页切到前台（切换设备真正的动作：不重建任何气泡）"""
        rec = self._chat_pages.get(ckey)
        if rec is None:
            return
        page, vbox, wmap, _ids = rec
        self.chat_vbox = vbox
        self.widgets_by_msg = wmap
        if self._chat_current_key != ckey:
            idx = self._chat_stack.indexOf(page)
            if idx >= 0:
                self._chat_stack.setCurrentIndex(idx)
            self._chat_current_key = ckey
            self._chat_page_order = [k for k in self._chat_page_order if k != ckey]
            self._chat_page_order.append(ckey)

    def _render_chat(self, force=False):
        """渲染聊天区。

        ★ v1.18.17 性能改造（用户反馈"切换和界面显示不流畅"）：
          实测（`tests/profile_render_chat.py`）气泡**构造**约 1.8ms/条且线性累加，
          而"只重排不重建"只要 8~30ms —— 瓶颈是"每次都重建"，不是布局或绘制。
          原来切一次设备 / 来一条消息都要把整个会话重建一遍，200 条时实测 ≈3000ms。

          现在三级策略：
            ① 该视图的消息列表命中缓存 → **只切页**，零重建（切回看过的设备瞬时）
            ② 只是末尾追加 → 在当前页**只补新增气泡**
            ③ 其余（首次进入该视图 / 内容变了）→ 建新页并缓存
        """
        msgs = self._visible_msgs()
        view_key = self._chat_view_key()
        ids = [id(m) for m in msgs]
        ckey = (view_key, tuple(ids))

        # ① 命中缓存 → 换页即可
        if not force and ckey in self._chat_pages and ckey != self._chat_current_key:
            self._switch_chat_page(ckey)
            self._stick_bottom = True
            self._hide_newmsg_btn()
            return
        if not force and ckey == self._chat_current_key:
            return   # 完全没变

        # ② 末尾追加 → 只补新的
        prev = self._chat_pages.get(self._chat_current_key)
        prev_ids = prev[3] if prev is not None else None
        grew = (not force and prev_ids is not None
                and len(ids) > len(prev_ids) and ids[:len(prev_ids)] == prev_ids)
        if grew:
            self._stick_bottom = True
            self._hide_newmsg_btn()
            for m in msgs[len(prev_ids):]:
                self._append_bubble(m)
            # 页内容变了 → 缓存 key 也要跟着换
            old_key = self._chat_current_key
            self._chat_pages.pop(old_key, None)
            self._chat_page_order = [k for k in self._chat_page_order
                                     if k != old_key]
            new_key = (view_key, tuple(ids))
            self._chat_pages[new_key] = (prev[0], prev[1], prev[2], list(ids))
            self._chat_page_order.append(new_key)
            self._chat_current_key = new_key
            self._rendered_ids = ids
            self._rendered_key = view_key
            return

        # ③ 建新页
        self._stick_bottom = True
        self._hide_newmsg_btn()
        container = self._chat_stack.parentWidget()
        if container is not None:
            container.setUpdatesEnabled(False)
        try:
            page, vbox, wmap, mids = self._build_chat_page(ckey, msgs)
        finally:
            if container is not None:
                container.setUpdatesEnabled(True)
        self._switch_chat_page(ckey)
        self._rendered_ids = ids
        self._rendered_key = view_key

    def _append_bubble(self, m: dict):
        w = BubbleFrame(m, self.theme)
        w.openRequested.connect(self._open_path)
        w.folderRequested.connect(self._open_folder)
        # ★ v1.15.0：文件卡片菜单新增「保存」/「转发」（与安卓端对齐）
        w.saveRequested.connect(self._save_file_as)
        w.forwardRequested.connect(self._forward_file)
        # ★ v1.16.0：图片右键菜单（复制 / 另存为）+ 拖出
        # ★ v1.17.0：按用户要求去掉「编辑图片」入口（与「打开」重复），
        #   并新增「其他应用打开…」。editImageRequested 保留为无操作兼容位。
        w.copyImageRequested.connect(self._copy_image_to_clipboard)
        w.saveImageAsRequested.connect(self._save_image_as)
        w.openWithRequested.connect(self._open_image_with)
        w.imageDragStarted.connect(self._on_image_drag)
        w.cancelRequested.connect(self._on_cancel_requested)
        w.acceptRequested.connect(self._on_accept_requested)
        w.rejectRequested.connect(self._on_reject_requested)
        w.resendRequested.connect(self._on_resend)
        w.selectToggled.connect(self._on_select_toggled)
        w.deleteRequested.connect(self._delete_single)
        w.multiSelectRequested.connect(self._enter_select_mode)
        w.openLinkRequested.connect(self._open_link)
        w.cancelPendingRequested.connect(self._on_cancel_pending)
        w.set_select_mode(self.multi_mode)
        if self.multi_mode and id(m) in self.selected_ids:
            w.set_checked(True)
        self.chat_vbox.insertWidget(self.chat_vbox.count() - 1, w)
        self.widgets_by_msg.setdefault(id(m), []).append(w)

    def _open_link(self, url):
        QDesktopServices.openUrl(QUrl(url))

    # ================= 多选删除 =================

    @staticmethod
    def _msg_identity(m: dict):
        return (m.get("ts"), m.get("mid") or m.get("tid") or "",
                m.get("dir"), m.get("kind"))

    def _toggle_multi(self):
        if self.multi_mode:
            self._exit_select_mode()
        else:
            self._enter_select_mode()

    def _enter_select_mode(self, first_msg=None):
        self.multi_mode = True
        self.selected_ids.clear()
        if first_msg is not None:
            self.selected_ids.add(id(first_msg))
        for ws in self.widgets_by_msg.values():
            for w in ws:
                w.set_select_mode(True)
                if id(w.msg) in self.selected_ids:
                    w.set_checked(True)
        self.multi_btn.setText("✕ 取消")
        self.select_bar.show()
        self._update_select_count()

    def _exit_select_mode(self):
        self.multi_mode = False
        self.selected_ids.clear()
        for ws in self.widgets_by_msg.values():
            for w in ws:
                w.set_select_mode(False)
        self.multi_btn.setText("☑ 多选")
        self.select_bar.hide()

    def _on_select_toggled(self, m, on):
        if on:
            self.selected_ids.add(id(m))
        else:
            self.selected_ids.discard(id(m))
        self._update_select_count()

    def _update_select_count(self):
        self.select_count_lbl.setText(f"已选择 {len(self.selected_ids)} 条")

    def _select_all_visible(self):
        for m in self._visible_msgs():
            self.selected_ids.add(id(m))
        for ws in self.widgets_by_msg.values():
            for w in ws:
                w.set_checked(True)
        self._update_select_count()

    def _delete_selected(self):
        if not self.selected_ids:
            return
        if not confirm(self, "删除",
                       f"确定删除选中的 {len(self.selected_ids)} 条消息吗？"):
            return
        identities = set()
        for ws in self.widgets_by_msg.values():
            for w in ws:
                if id(w.msg) in self.selected_ids:
                    identities.add(self._msg_identity(w.msg))
        self._remove_msgs(identities)
        self._exit_select_mode()

    def _delete_single(self, m):
        if m.get("state") == "pending":
            self._on_cancel_pending(m)
            return
        if not confirm(self, "删除", "确定删除这条消息吗？"):
            return
        self._remove_msgs({self._msg_identity(m)})

    def _remove_msgs(self, identities: set):
        """从内存与历史记录文件中删除指定标识的消息"""
        if not identities:
            return
        # 先记录被删的待发送消息 mid（下面会从 msgs 中移除，需提前取）
        gone_pending_mids = {m.get("mid") for m in self.msgs.get(self.PENDING_PEER, [])
                             if self._msg_identity(m) in identities}
        for pid in list(self.msgs.keys()):
            self.msgs[pid] = [m for m in self.msgs[pid]
                              if self._msg_identity(m) not in identities]
            if not self.msgs[pid]:
                self.msgs.pop(pid)
        try:
            self.history.delete_by_identities(identities)
        except Exception:
            pass
        # 清理 tid 索引
        for key in list(self.in_by_tid.keys()):
            if self._msg_identity(self.in_by_tid[key]) in identities:
                self.in_by_tid.pop(key, None)
        for tid in list(self.out_by_tid.keys()):
            if self._msg_identity(self.out_by_tid[tid]) in identities:
                self.out_by_tid.pop(tid, None)
        # 同步清理待发队列，避免删除后重启又"复活"
        if gone_pending_mids:
            self._pending_files = [e for e in self._pending_files
                                   if e.get("mid") not in gone_pending_mids]
            self.cfg["pending_files"] = self._pending_files
        self._render_chat()

    def _refresh_msg(self, m: dict):
        for w in self.widgets_by_msg.get(id(m), []):
            w.update_msg(m)
        # ★ v1.14.0：状态变更落盘。
        # 接收/发送的进度与终态原先只在内存里改，重启后 load 回来又变回
        # "发送中"，用户以为消息没发出去。这里在所有刷新路径统一 upsert，
        # 比在十几处事件分支各写一遍可靠。
        self._persist_msg_state(m)

    def _persist_msg_state(self, m: dict):
        """把一条消息的当前状态覆盖式写回磁盘（按 mid / tid 定位）"""
        try:
            if m.get("kind") == "text" and not m.get("mid"):
                return
            if m.get("kind") == "file" and not m.get("tid"):
                return
            if m.get("dir") == "in":
                pid = m.get("peer_id")
                if pid:
                    self.history.upsert(pid, m)
            else:
                # 发送侧：同一条消息挂在每个目标的会话里，逐个更新
                targets = m.get("targets") or ([m.get("peer_id")]
                                               if m.get("peer_id") else [])
                for t in targets:
                    if t:
                        self.history.upsert(t, m)
        except Exception:
            pass

    def _is_in_view(self, m) -> bool:
        view = set(self._view_peer_ids())
        if m.get("dir") == "in":
            return m.get("peer_id") in view
        targets = m.get("targets") or [m.get("peer_id")]
        return bool(set(targets) & view)

    def _append_msg(self, pid: str, m: dict, notify=False):
        if pid not in self.msgs:
            # 懒加载：该设备历史尚未读入，先只放新消息，视图切换时补全
            self.msgs[pid] = []
            self._partial.add(pid)
        lst = self.msgs[pid]
        lst.append(m)
        lst.sort(key=lambda x: x.get("ts", 0))
        self.history.append(pid, m)
        if self._is_in_view(m):
            if not self._stick_bottom and m.get("dir") == "in":
                self._new_msg_pending = True
            self._append_bubble(m)
        if notify and (not self.isVisible() or not self._is_in_view(m)):
            self.unread[pid] = self.unread.get(pid, 0) + 1
            if self.cfg["notify_on_receive"]:
                title = m.get("peer_name") or "新消息"
                body = m.get("text") or f"文件：{m.get('file', '')}"
                self.tray.showMessage(title, body, QSystemTrayIcon.Information, 3000)
            self._refresh_devices()

    # ================= 事件处理 =================

    def _on_log(self, level, msg):
        if level == "error":
            self.statusBar().showMessage(msg, 8000)

    def _toast(self, text, ms=2000):
        """屏幕中间的自动消失通知（无需确认）"""
        lbl = QLabel(text, self)
        lbl.setObjectName("Toast")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(
            "QLabel#Toast { background: rgba(20,22,26,220); color: white;"
            "border-radius: 10px; padding: 14px 30px; font-size: 14px; }")
        lbl.adjustSize()
        lbl.move(max(0, (self.width() - lbl.width()) // 2),
                 max(0, (self.height() - lbl.height()) // 2))
        lbl.show()
        lbl.raise_()
        eff = QGraphicsOpacityEffect(lbl)
        eff.setOpacity(0.96)
        lbl.setGraphicsEffect(eff)
        QTimer.singleShot(ms, lbl.deleteLater)

    def _on_scan_done(self, info):
        # 后台定时扫描静默完成，不打扰；仅手动"深度扫描"显示结果
        if not info.get("full"):
            if not self._manual_scanning:
                self._set_scan_text("")
            return
        self._manual_scanning = False
        self._set_scan_text("扫描完成" + (f"（新连接 {info.get('found', 0)}）"
                                        if info.get("found") else ""))
        QTimer.singleShot(6000, lambda: self._set_scan_text(""))

    def _on_text_in(self, e: dict):
        pid = e["peer_id"]
        m = {"kind": "text", "dir": "in", "peer_id": pid, "peer_name": e.get("name"),
             "mid": e.get("mid"), "text": e.get("text", ""),
             "peer_scheme": e.get("scheme", ""),
             # ★ v1.18.9：入向文本自带 channel（发送端已打标）；老版本对端
             #   不带该字段时按 targets 数量保守判定：多人=群聊，单人=私聊。
             "channel": e.get("channel") or self._channel_for(
                 e.get("targets") or [pid], e.get("broadcast", False)),
             "ts": e.get("ts") or int(time.time() * 1000)}
        self._append_msg(pid, m, notify=True)

    @staticmethod
    def _channel_for(targets, broadcast: bool) -> str:
        """★ v1.18.9：给消息打「频道」标记，用于「全部设备」纯群聊视图。

        "group" —— 在「全部设备」里群发（与安卓端 channelFor 同口径）
        "p2p"   —— 端到端私聊（选中 1 台或多台具体设备定向发送）
        """
        return "group" if broadcast else "p2p"

    def _out_text_msg(self, targets, mid, text, channel=None):
        if channel is None:
            # 未显式指定时按目标数推断：>1 台视为群发
            channel = "group" if len(list(targets)) > 1 else "p2p"
        for pid in targets:
            m = {"kind": "text", "dir": "out", "peer_id": pid, "peer_name": "我",
                 "mid": mid, "text": text, "state": "sending",
                 "channel": channel,
                 "targets": list(targets), "ts": int(time.time() * 1000)}
            self._append_msg(pid, m)

    def _on_text_state(self, e: dict):
        pid = e["peer_id"]
        for m in self.msgs.get(pid, []):
            if m.get("mid") == e.get("mid"):
                m["state"] = e.get("state")
                self._refresh_msg(m)

    def _on_ack(self, pid, mid):
        for m in self.msgs.get(pid, []):
            if m.get("mid") == mid and m.get("dir") == "out":
                m["state"] = "ok"
                self._refresh_msg(m)

    def _on_transfer(self, e: dict):
        kind = e.get("kind")
        tid = e.get("tid")
        pid = e.get("peer_id")
        state = e.get("state")
        if kind == "recv":
            key = (pid, tid)
            m = self.in_by_tid.get(key)
            if not m:
                m = {"kind": "file", "dir": "in", "peer_id": pid,
                     "peer_name": e.get("name"), "tid": tid,
                     "file": e.get("file"), "size": e.get("size"),
                     "mime": e.get("mime"), "state": state,
                     "peer_scheme": e.get("scheme", ""),
                     "transferred": e.get("transferred", 0),
                     "speed": e.get("speed", 0), "path": e.get("path"),
                     "ts": int(time.time() * 1000)}
                self.in_by_tid[key] = m
            else:
                for f in ("state", "transferred", "speed", "path", "reason",
                          "file", "size",
                          # ★ v1.18.18：断点续传字段。
                          #   不带的话 _status_text() 拿不到块数，
                          #   "已暂停，可续传" 只能显示成无进度的一句话。
                          "total_chunks", "have_chunks", "attempt"):
                    if e.get(f) is not None:
                        m[f] = e[f]
            # offer 仅是预告，不立刻上屏；进入实际流程后首次事件时上屏
            if not m.get("_appended") and state != "offer":
                m["_appended"] = True
                self._append_msg(pid, m, notify=state in ("confirm", "done"))
            self._refresh_msg(m)
        else:  # send
            m = self.out_by_tid.get(tid)
            if not m:
                _tg = e.get("targets") or [pid]
                m = {"kind": "file", "dir": "out", "peer_id": pid,
                     "peer_name": "我", "tid": tid, "file": e.get("file"),
                     "size": e.get("size"), "mime": e.get("mime"),
                     "state": state, "targets": _tg,
                     "channel": e.get("channel") or self._channel_for(
                         _tg, bool(e.get("broadcast"))),
                     "target_states": {}, "_bytes": {},
                     "src_path": e.get("src_path"),
                     "ts": int(time.time() * 1000)}
                # ★ v1.18.19：append 前按 tid 查重 —— out_by_tid 与 msgs
                #   的索引若因任何路径（删除消息摘索引、异常时序）失同步，
                #   同一 tid 会建出第二个气泡（用户反馈的"偶发显示两遍"）。
                #   以 msgs 里的实际内容为准重建索引，保证只有一个气泡。
                dup = None
                # ★ 只扫每个目标列表的**尾部 30 条**：新气泡 ts 最大、
                #   总是插在尾部附近；全量扫描 200 条会拖慢追加路径
                #   （v11817_perf 的 15ms 上限实测被推到 17ms）。
                for t in m["targets"]:
                    lst_t = self.msgs.get(t) or []
                    for x in lst_t[-30:]:
                        if x.get("tid") == tid and x.get("dir") == "out":
                            dup = x
                            break
                    if dup is not None:
                        break
                if dup is not None:
                    self.out_by_tid[tid] = dup
                    self._refresh_msg(dup)
                else:
                    self.out_by_tid[tid] = m
                    for t in m["targets"]:
                        self.msgs.setdefault(t, []).append(m)
                        self.msgs[t].sort(key=lambda x: x.get("ts", 0))
                        self.history.append(t, m)
                    if self._is_in_view(m):
                        self._append_bubble(m)
            else:
                if state == "progress":
                    m["_bytes"][pid] = e.get("transferred", 0)
                    m["transferred"] = sum(m["_bytes"].values())
                    m["speed"] = e.get("speed", 0)
                elif state in ("ok", "fail", "refuse", "cancel"):
                    m["target_states"][pid] = state
                elif state == "failed":
                    # ★ v1.18.19：node 的 emitSendState 发的是 "failed"，
                    #   这里以前只认 "fail" —— 失败永远进不了 target_states，
                    #   all_terminal 判断失效、状态卡在发送中。
                    m["target_states"][pid] = "fail"
                # ★ v1.14.0：多目标发送改为「首个目标成功即视为完成」。
                # 旧逻辑直接把每个目标的事件 state 覆盖成整体 state，
                # 结果"发出的文件被第一台设备收下后，又被第二台的进度事件
                # 覆盖回 sending/progress"，界面显示一直在发送中。
                ts = m.get("target_states") or {}
                any_ok = any(v == "ok" for v in ts.values())
                all_terminal = bool(ts) and all(
                    v in ("ok", "refuse", "cancel", "fail") for v in ts.values())
                if any_ok:
                    m["state"] = "done"
                    m["transferred"] = m.get("size", 0)
                elif all_terminal:
                    m["state"] = "failed"
                    m["reason"] = "所有目标均未接收"
                else:
                    m["state"] = state
                if state in ("failed", "refused", "cancelled"):
                    m["reason"] = e.get("reason")
            self._refresh_msg(m)

    # ---- 气泡按钮回调 ----
    def _open_path(self, path):
        """打开文件。

        ★ v1.17.0 行为变更（用户要求）：
          「把双击打开的图片编辑框，包括裁剪到应用马赛克的功能都删除」
        → 图片不再进内置编辑器，改为**交给系统默认看图程序**打开，
          与"打开任何文件"语义完全一致，也让右键菜单里的
          「打开」和「其他应用打开」形成清晰的层级：
            打开          = 系统默认程序（图片即默认看图软件）
            其他应用打开… = 弹出系统"打开方式"让用户挑别的程序

        历史：v1.14.0–v1.16.0 图片走内置 ImageViewer（可裁剪/标记/马赛克），
        v1.17.0 按用户反馈移除该编辑能力。
        """
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _open_image_with(self, path):
        """「其他应用打开…」：弹出系统"打开方式"对话框让用户选择程序。

        Windows 上没有直接唤起「打开方式」列表的公开 API，
        通用做法是起一个 cmd 执行 `rundll32 shell32.dll,OpenAs_RunDLL <file>`，
        这正是资源管理器右键「打开方式」调用的同一个入口，兼容性最好。
        非 Windows 平台退化为普通打开（macOS/Linux 无此概念）。
        """
        if not path or not os.path.isfile(path):
            self._toast("文件不可用")
            return
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(
                    ["rundll32.exe", "shell32.dll,OpenAs_RunDLL",
                     os.path.normpath(path)],
                    close_fds=True)
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception as e:
            self._toast(f"打开失败：{e}")

    # ★ v1.15.0：文件卡片的「保存」/「转发」（与安卓端 Download/FlashDrop 位置对齐）

    @staticmethod
    def _user_save_dir() -> str:
        """★ v1.16.0：用户手动「保存」的落盘位置。

        与安卓端严格对齐 —— 落在保存根目录下、与按设备分的接收文件夹**同级**
        的「保存的文件」子目录：

            Downloads/FlashDrop/
                ├── <设备名>/        ← 自动接收的文件
                └── 保存的文件/       ← 手动保存的文件（不受"清空"影响）

        为什么单独放一层：用户要求手动留存的文件在与设备文件夹同级的位置，
        并且清空聊天/清理接收文件时**不能**把它们一起删掉。
        """
        return os.path.join(MainWindow._save_root_dir(), "保存的文件")

    @staticmethod
    def _save_root_dir() -> str:
        """保存根目录（各设备文件夹与「保存的文件」的共同父目录）"""
        home = os.path.expanduser("~")
        cand = os.path.join(home, "Downloads")
        if os.path.isdir(cand):
            return os.path.join(cand, "FlashDrop")
        return os.path.join(home, "FlashDrop")

    def _unique_dest(self, dst_dir: str, name: str) -> str:
        """目标目录内不重名（重名追加 -1 / -2 …），与安卓端策略一致"""
        stem, ext = os.path.splitext(name)
        cand = name
        i = 1
        while os.path.exists(os.path.join(dst_dir, cand)) and i < 200:
            cand = f"{stem}-{i}{ext}"
            i += 1
        return os.path.join(dst_dir, cand)

    def _save_file_as(self, path):
        """另存到 ~/Downloads/FlashDrop/（不覆盖同名文件）"""
        if not path or not os.path.isfile(path):
            self._toast("文件不可用")
            return
        try:
            dst_dir = self._user_save_dir()
            os.makedirs(dst_dir, exist_ok=True)
            dst = self._unique_dest(dst_dir, os.path.basename(path))
            if os.path.abspath(dst) == os.path.abspath(path):
                self._toast("该文件已在此位置")
                return
            shutil.copy2(path, dst)
            self._toast(f"已保存到 {os.path.basename(dst_dir)}/{os.path.basename(dst)}")
        except Exception as e:
            self._toast(f"保存失败：{e}")

    def _forward_file(self, path):
        """转发：调起系统「发送到」/ 分享面板，让用户选择其它应用。

        Windows 上没有统一的系统分享面板，用「发送到」菜单
        （shell:SendTo）等价实现；其它平台退回到打开文件所在目录。
        """
        if not path or not os.path.isfile(path):
            self._toast("文件不可用")
            return
        try:
            if os.name == "nt":
                # 调起资源管理器的「发送到」子菜单（等价于微信的"转发到其它应用"）
                subprocess.Popen(["rundll32.exe", "shell32.dll,OpenAs_RunDLL", path])
                return
        except Exception:
            pass
        try:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception as e:
            self._toast(f"转发失败：{e}")

    # ================= ★ v1.16.0：图片相关（复制 / 另存为 / 其他应用打开 / 拖出） =================
    # ★ v1.17.0：删除 open_image_editor（内置编辑器连同裁剪/马赛克一并移除），
    #   图片打开统一走系统默认程序（见 _open_path）。

    def _copy_image_to_clipboard(self, path):
        """复制图片到系统剪贴板（可直接粘贴进其它聊天软件）"""
        if not path or not os.path.isfile(path):
            self._toast("图片不可用")
            return
        try:
            from PySide6.QtGui import QImage
            img = QImage(path)
            if img.isNull():
                self._toast("无法读取图片")
                return
            QGuiApplication.clipboard().setImage(img)
            self._toast("已复制图片到剪贴板")
        except Exception as e:
            self._toast(f"复制失败：{e}")

    def _save_image_as(self, path):
        """图片另存为（弹系统保存对话框，默认目录为「保存的文件」）"""
        if not path or not os.path.isfile(path):
            self._toast("图片不可用")
            return
        try:
            default_dir = self._user_save_dir()
            os.makedirs(default_dir, exist_ok=True)
            name = os.path.basename(path)
            target, _ = QFileDialog.getSaveFileName(
                self, "图片另存为", os.path.join(default_dir, name),
                "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp *.gif);;所有文件 (*.*)")
            if not target:
                return
            if os.path.abspath(target) != os.path.abspath(path):
                shutil.copy2(path, target)
            self._toast(f"已保存到 {os.path.basename(target)}")
        except Exception as e:
            self._toast(f"保存失败：{e}")

    def _on_image_drag(self, path):
        """图片开始被拖出 —— 仅记录一次提示，实际落盘由目标程序完成。"""
        if not path:
            return
        self._toast("拖动到文件夹或聊天窗口即可发送")

    # ================= ★ v1.16.0：截图 =================

    def _screenshot(self):
        """★ v1.18.0：截图主入口 —— 支持**框选** + 是否隐藏窗口由下拉决定。

        与 v1.16.0 的差别：
          · 原来只能整屏直抓，且"先隐藏主窗口"是写死的；
          · 现在统一走 `_start_snip(hide_self)`，由截图按钮的下拉菜单
            （`_screenshot_menu`）决定 hide_self。

        流程：
          hide_self=True  → 先 hide() → 延迟 260ms（等窗口管理器动画收尾）
                            → 抓屏 → 弹取景器框选 → 复原窗口
          hide_self=False → 不隐藏，直接把当前画面连同本窗口一起抓下来
        """
        self._start_snip(hide_self=self._snip_hide_self)

    # ---- 截图按钮：带下拉三角（对齐微信）------------------------------

    def _screenshot_menu(self):
        """截图按钮右侧下拉三角：选择"是否隐藏当前窗口"。

        对齐微信截图的交互：主按钮直接按上次的选择执行，
        点右侧小三角才展开选项，避免每次都要二次确认。
        """
        m = QMenu(self)
        a_hide = QAction("截图时隐藏当前窗口", self)
        a_hide.setCheckable(True)
        a_hide.setChecked(self._snip_hide_self)
        a_keep = QAction("截图时保留当前窗口", self)
        a_keep.setCheckable(True)
        a_keep.setChecked(not self._snip_hide_self)

        def pick(hide):
            self._snip_hide_self = hide
            # 记住选择，下次直接按同一模式执行（与微信一致）
            self._remember_snip_hide(hide)
            self._toast("截图时将%s当前窗口"
                        % ("隐藏" if hide else "保留"))
            # 选完立即执行一次，少一次点击
            self._start_snip(hide_self=hide)

        a_hide.triggered.connect(lambda: pick(True))
        a_keep.triggered.connect(lambda: pick(False))
        m.addAction(a_hide)
        m.addAction(a_keep)
        # 三角按钮挂在截图按钮右下角
        btn = self.sender()
        if isinstance(btn, QWidget):
            m.exec(btn.mapToGlobal(btn.rect().bottomLeft()))
        else:
            m.exec(QCursor.pos())

    def _remember_snip_hide(self, hide: bool):
        """记住"截图时是否隐藏当前窗口"，并落盘到 config.json。

        写 self.cfg 数据字典 + 立即 save()，下次启动沿用；
        cfg 可能是 Config 对象或纯 dict（测试注入），两种都兼容。
        """
        self._snip_hide_self = bool(hide)
        try:
            self.cfg["snip_hide_self"] = bool(hide)
            saver = getattr(self.cfg, "save", None)
            if callable(saver):
                saver()
        except Exception:
            # 配置不可写不该阻断截图功能
            pass

    def _start_snip(self, hide_self: bool):
        """抓屏并进入框选取景器。"""
        try:
            from .snip import grab_virtual_desktop, SnipOverlay, region_from_canvas
        except Exception as e:
            self._toast(f"截图组件不可用：{e}")
            return

        was_visible = self.isVisible()

        def do_capture():
            canvas, origin = grab_virtual_desktop()
            if canvas.isNull() or canvas.width() < 2:
                if hide_self and was_visible:
                    self.showMaximized()
                self._toast("截图失败：无法获取屏幕画面")
                return
            if hide_self and was_visible:
                # 抓完立刻恢复本窗口，让用户能对着熟悉的界面框选
                self.showMaximized()
                self.raise_()
                self.activateWindow()

            ov = SnipOverlay(canvas, hint="拖动鼠标框选截图区域 · Esc 取消")
            # 用列表持住引用，防止 Python 侧被回收导致 overlay 提前销毁
            self._snip_overlay = ov

            def on_picked(region):
                sub, _grect = region_from_canvas(canvas, region, origin)
                if sub.isNull() or sub.width() < 2:
                    self._toast("截图失败：选区为空")
                    return
                self._save_shot(sub)

            def on_cancel():
                self._toast("已取消截图")

            ov.picked.connect(on_picked)
            ov.cancelled.connect(on_cancel)
            ov.show()
            ov.raise_()
            ov.activateWindow()
            # 确保遮罩拿到键盘焦点，Esc 才生效
            ov.setFocus(Qt.OtherFocusReason)

        if hide_self and was_visible:
            self.hide()
            # 给窗口管理器留出动画时间，否则会拍到本窗口的残影
            QTimer.singleShot(260, do_capture)
        else:
            # 保留窗口：直接抓（本窗口会被拍进去，属预期行为）
            QTimer.singleShot(60, do_capture)

    def _save_shot(self, pixmap):
        """把框选结果落盘，并串进本会话图片序列，方便"截完就发"。"""
        try:
            shot_dir = os.path.join(self._user_save_dir(), "截图")
            os.makedirs(shot_dir, exist_ok=True)
            name = time.strftime("截图_%Y%m%d_%H%M%S.png")
            path = self._unique_dest(shot_dir, name)
            if not pixmap.save(path, "PNG"):
                self._toast("截图保存失败")
                return
        except Exception as e:
            self._toast(f"截图保存失败：{e}")
            return
        self._screenshots = getattr(self, "_screenshots", [])
        self._screenshots.append(path)
        self._toast(f"已截图 {pixmap.width()}×{pixmap.height()}："
                    f"{os.path.basename(path)}——可在相册中发送")
        self.open_image_viewer(path)


    def open_image_viewer(self, path):
        """在内置预览器中打开图片；自动把当前会话里的所有图片串成可翻页的序列。"""
        paths = []
        try:
            view = set(self._view_peer_ids())
            seen = set()
            for pid, lst in self.msgs.items():
                if pid not in view:
                    continue
                for m in lst:
                    if m.get("kind") != "file":
                        continue
                    p = m.get("path") if m.get("dir") == "in" else m.get("src_path")
                    if not p or p in seen or not os.path.isfile(p):
                        continue
                    if not util.is_image_mime(m.get("mime", "") or _mime_of(p)):
                        continue
                    seen.add(p)
                    paths.append(p)
        except Exception:
            paths = []
        if path not in paths:
            paths.append(path)
        idx = paths.index(path)
        # 记住引用，避免被 GC 掉导致窗口一闪而过
        if not hasattr(self, "_viewers"):
            self._viewers = []
        v = ImageViewer(paths, idx, self)
        self._viewers.append(v)
        v.finished.connect(lambda _r, vv=v: self._viewers.remove(vv)
                           if vv in self._viewers else None)
        v.show()
        v.raise_()
        v.activateWindow()
        return v

    def _open_folder(self, path):
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))

    def _on_accept_requested(self, tid):
        self.bridge.accept_inbound(tid)

    def _on_reject_requested(self, tid):
        self.bridge.reject_inbound(tid)

    def _on_cancel_requested(self, tid):
        if any(k[1] == tid for k in self.in_by_tid):
            self.bridge.cancel_inbound(tid)
        else:
            self.bridge.cancel_send(tid)

    def _on_resend(self, m):
        targets = [t for t in (m.get("targets") or [m.get("peer_id")])
                   if t in self.peers and self.peers[t]["online"]]
        src = m.get("src_path")
        if not src or not os.path.isfile(src):
            QMessageBox.information(self, "重新发送", "原文件已不存在")
            return
        if targets:
            self._do_send_files(targets, [src])
        else:
            self._queue_files([src], list(m.get("targets") or [m.get("peer_id")]))

    # ================= 发送 =================
    #
    # 异步待发（v1.9.0）：
    #   选「全部设备」发送且当前没有任何在线设备时，消息不丢弃，
    #   而是进入持久化待发队列并以「待发送」气泡显示在聊天区；
    #   之后任意设备上线即自动补发。文本与文件走同一套队列。

    PENDING_PEER = "::pending::"   # 待发送消息的显示归属（不入历史）

    @staticmethod
    def _queue_kind(entry: dict) -> str:
        """待发条目类型；旧版本条目无 type 字段，按文件处理"""
        t = entry.get("type")
        if t in ("text", "file"):
            return t
        return "file"

    @staticmethod
    def _describe_send_fail(res, bad_targets) -> str:
        """把发送结果字典翻译成一句人能看懂的原因（供待发面板展示）

        res 形如 {peer_id: "ok"|"failed"|"timeout"|...}；
        只取失败目标的原因，多目标时合并去重。
        """
        reasons = []
        try:
            items = res.items() if isinstance(res, dict) else []
        except Exception:
            items = []
        for pid, v in items:
            if v == "ok":
                continue
            if isinstance(v, (tuple, list)) and len(v) > 1:
                v = v[1]
            reasons.append(str(v))
        if not reasons and bad_targets:
            reasons = ["设备无响应"]
        out = "；".join(dict.fromkeys(reasons)) or "发送失败"
        return out[:80]

    @staticmethod
    def _entry_text(entry: dict) -> str:
        """待发条目的可读摘要（用于气泡与管理窗口）"""
        if MainWindow._queue_kind(entry) == "text":
            return entry.get("text") or ""
        paths = entry.get("paths") or []
        names = "、".join(os.path.basename(p) for p in paths[:3])
        if len(paths) > 3:
            names += f" 等 {len(paths)} 个文件"
        return names or "待发文件"

    def _pending_target_names(self, entry: dict) -> str:
        """待发目标的显示文案：群发 / 指定设备名 / 未指定

        ★ v1.18.18：不再用 `if t in self.peers` 过滤掉未知设备。
        旧写法下，若目标设备已离线且不在 peers 里，names 会变空 ->
        返回"全部设备" —— 用户以为要群发给所有人，实际只发给那一个离线设备，
        属于**误导性显示**。现在未知设备显示为"未知设备(离线)"。
        """
        if entry.get("broadcast"):
            return "全部设备"
        targets = entry.get("targets") or []
        if not targets:
            return "全部设备"
        names = []
        for t in targets:
            if t == self.PENDING_PEER:
                continue
            names.append(self._display_name(t))
        if not names:
            return "全部设备"
        return "、".join(names)

    def _queue_entry(self, entry: dict, toast_msg: str = ""):
        """统一入队：补 mid、持久化、显示待发送气泡"""
        entry.setdefault("mid", util.gen_uid())
        entry.setdefault("ts", int(time.time() * 1000))
        self._pending_files.append(entry)
        self.cfg["pending_files"] = self._pending_files
        self._show_pending_msg(entry)
        self._pending_btn_refresh()
        if toast_msg:
            self._toast(toast_msg)

    def _send_input(self):
        text = self.input_edit.toPlainText().strip()
        if not text:
            return
        targets, intent, broadcast = self._resolve_targets()
        if targets:
            mid = self.bridge.send_text(targets, text)
            self.input_edit.clear()
            self._out_text_msg(targets, mid, text,
                               channel=self._channel_for(targets, broadcast))
            return
        # 无在线目标：文本也入队（与文件一致的异步语义）
        self.input_edit.clear()
        entry = {"type": "text", "text": text, "paths": [],
                 "targets": list(intent), "broadcast": broadcast}
        self._queue_entry(entry, self._pending_toast_text("消息"))

    def _insert_emoji(self, ch: str):
        """把选中的 Fluent Emoji 字符插入输入框光标处（保留当前选区语义）。"""
        if not ch:
            return
        self.input_edit.setFocus()
        cur = self.input_edit.textCursor()
        cur.insertText(ch)
        self.input_edit.setTextCursor(cur)

    def _pending_toast_text(self, what: str) -> str:
        return (f"当前没有在线设备，{what}已保存到待发送，"
                f"设备上线后自动发出")

    def _resolve_targets(self):
        """返回 (立即发送的在线目标, 用户勾选的全部目标, 是否群发语义)

        群发语义 = 用户在「全部设备」视图发送。这类目标集合随上线设备变化，
        待发队列里以 broadcast=True 记录，补发时发给当时所有在线设备。
        """
        sel = [i.data(Qt.UserRole) for i in self.device_list.selectedItems()]
        is_all = ALL_ID in sel or not sel
        online = [pid for pid, p in self.peers.items() if p.get("online")]
        if is_all:
            return online, [], True
        now = [s for s in sel if s != ALL_ID
               and self.peers.get(s, {}).get("online")]
        intent = [s for s in sel if s != ALL_ID]
        return now, intent, False

    def _selected_ids_all(self) -> list:
        """当前勾选的全部设备 id（含离线，排除"全部设备"），作为待发意图目标"""
        return [i.data(Qt.UserRole) for i in self.device_list.selectedItems()
                if i.data(Qt.UserRole) != ALL_ID]

    # ---------- 待发队列（持久化） ----------

    def _pending_load(self):
        self._pending_files = list(self.cfg["pending_files"] or [])
        # ★ v1.18.15：补发进行中标记 + 周期重试定时器（懒创建）
        self._flush_running = False
        self._pending_retry = None
        for entry in self._pending_files:
            self._show_pending_msg(entry)
        self._pending_btn_refresh()
        if self._pending_files:
            self._render_chat()
            # ★ v1.18.15：启动即挂上周期重试 —— 覆盖"启动时对方已在线、
            #   之后 peers 事件不再变化"的场景（旧实现会一直卡在待发送）。
            self._start_pending_retry()
            QTimer.singleShot(2500, lambda: self._toast(
                f"有 {len(self._pending_files)} 条待发送内容等待设备上线"))

    def _show_pending_msg(self, entry):
        """在聊天区显示一条"待发送"消息（不入历史；成功后移除）"""
        mid = entry.setdefault("mid", util.gen_uid())
        kind = self._queue_kind(entry)
        paths = entry.get("paths") or []
        if kind == "text":
            m = {"kind": "text", "dir": "out", "state": "pending", "mid": mid,
                 "text": entry.get("text") or "", "targets": list(entry["targets"]),
                 "peer_id": entry["targets"][0] if entry["targets"] else "",
                 "ts": entry.get("ts") or int(time.time() * 1000)}
        else:
            try:
                size = sum(os.path.getsize(p) for p in paths if os.path.isfile(p))
            except Exception:
                size = 0
            m = {"kind": "file", "dir": "out", "state": "pending", "mid": mid,
                 "file": self._entry_text(entry), "size": size,
                 "targets": list(entry["targets"]),
                 "peer_id": entry["targets"][0] if entry["targets"] else "",
                 "src_path": paths[0] if len(paths) == 1 else "",
                 "ts": entry.get("ts") or int(time.time() * 1000)}
        m["pending_broadcast"] = bool(entry.get("broadcast"))
        m["pending_targets_desc"] = self._pending_target_names(entry)
        lst = self.msgs.setdefault(self.PENDING_PEER, [])
        lst[:] = [x for x in lst if x.get("mid") != mid]
        lst.append(m)
        lst.sort(key=lambda x: x.get("ts", 0))
        if not self._rebuilding:
            self._render_chat()

    def _remove_pending_msg(self, mid):
        lst = self.msgs.get(self.PENDING_PEER, [])
        self.msgs[self.PENDING_PEER] = [x for x in lst if x.get("mid") != mid]
        if not self.msgs[self.PENDING_PEER]:
            self.msgs.pop(self.PENDING_PEER, None)
        self._render_chat()

    def _drop_pending(self, mid, toast_msg=""):
        """从队列与显示中移除一条待发"""
        self._pending_files = [e for e in self._pending_files
                               if e.get("mid") != mid]
        self.cfg["pending_files"] = self._pending_files
        self._remove_pending_msg(mid)
        self._pending_btn_refresh()
        if toast_msg:
            self._toast(toast_msg)

    def _on_cancel_pending(self, m):
        self._drop_pending(m.get("mid"), "已取消待发送")

    def _queue_files(self, paths, entry_targets, broadcast=False):
        """目标不在线：文件加入待发队列（持久化），设备上线后自动发送"""
        entry = {"type": "file", "paths": list(paths),
                 "targets": list(entry_targets or []), "broadcast": broadcast,
                 "ts": int(time.time() * 1000)}
        self._queue_entry(entry, self._pending_toast_text("文件"))

    def _flush_pending(self):
        """有设备上线时补发待发队列（文本与文件 alike）

        ★ v1.18.15（用户反馈「安卓给电脑离线发送，对方上线后收不到」）：
        旧实现在**刚调用 send 就把条目从队列里删掉**并落盘，可 send_text 是异步的
        （内部还要 _wait_conn 等 TCP 最多 15s、再等 ack 12s）。设备刚上线时 UDP 层
        已判在线 → 触发 flush，但 TCP 往往还没建好 → wait_conn 失败 →
        text_state=failed → **条目已经没了，消息永久丢失**：接收端收不到、
        发送端只看到"发送失败"。而队列没有任何重试机制，等于必丢。

        改为三条：
          1. **确认送达（收到 ack）才移除条目**，失败/超时一律保留
          2. 整个补发放到工作线程（send_text_sync 会阻塞，不能压 UI 线程）
          3. 队列非空且有在线设备时每 10s 自动重试，队列空了自动停
        """
        if not self._pending_files:
            self._stop_pending_retry()
            return
        if self._flush_running:
            return
        online = [pid for pid, p in self.peers.items() if p.get("online")]
        if not online:
            self._start_pending_retry()
            return
        self._flush_running = True
        snapshot = list(self._pending_files)
        # ★这三个容器必须在 work() 外面创建，且 work() 内**只允许
        #   append/clear/extend，绝不能重新绑定名字**。
        #   Python 的作用域规则：函数体内只要出现 name = ...，
        #   该 name 就是局部变量，外层同名变量被完全遮蔽 ->
        #   UnboundLocalError。而这里的历史故障被外层 except 静默吞掉，
        #   表现为"队列条目删不掉、也没任何报错"，极难定位。
        remain = []
        ok = []              # [(entry, real_mid|None, targets)]
        sent_box = [0]      # 发送计数（用单元素列表装，避免 += 变成重新绑定）

        def _keep(entry, reason=None):
            """v1.18.18：补发失败时把原因与重试次数记进条目，
            让 PendingWindow 能显示"为什么还在队列里、重试了几次"。
            （之前失败条目只是 remain.append(entry)，面板无从展示，
              用户只看到"一直发不出去"却不知道卡在哪。）"""
            if reason:
                entry["last_error"] = reason
            try:
                entry["attempt"] = int(entry.get("attempt") or 0) + 1
            except Exception:
                entry["attempt"] = 1
            remain.append(entry)

        def work():
            try:
                for entry in snapshot:
                    if self._queue_kind(entry) == "text":
                        if entry.get("broadcast") or not entry.get("targets"):
                            targets = list(online)
                        else:
                            targets = [t for t in entry["targets"] if t in online]
                        if not targets:
                            _keep(entry, "目标设备不在线")
                            continue
                        # 阻塞等结论（ok/failed/timeout）
                        try:
                            real_mid, res = self.bridge.send_text_sync(
                                targets, entry.get("text") or "")
                        except Exception as e:
                            _keep(entry, f"发送异常: {e}")
                            continue
                        if not isinstance(res, dict) or not any(
                                res.get(t) == "ok" for t in targets):
                            # ★ 失败保留，等重试；记下真实原因
                            bad = [t for t in targets
                                   if not isinstance(res, dict)
                                   or res.get(t) != "ok"]
                            _keep(entry, self._describe_send_fail(res, bad))
                            continue
                        sent_box[0] += 1
                        ok.append((entry, real_mid, targets))
                    else:
                        paths = [p for p in (entry.get("paths") or []) if os.path.isfile(p)]
                        if not paths:
                            ok.append((entry, None, []))   # 文件已不存在 → 清掉
                            continue
                        if entry.get("broadcast") or not entry.get("targets"):
                            targets = list(online)
                        else:
                            targets = [t for t in entry["targets"] if t in online]
                        if not targets:
                            _keep(entry, "目标设备不在线")
                            continue
                        # ★ v1.18.20：改同步发送 + 确认送达才移除条目。
                        #   旧实现 send_files（fire-and-forget）后**立即当作
                        #   成功**移除条目 —— 本次尝试一旦失败（设备刚上线
                        #   TCP 未就绪等），内容丢失；且与用户手动重发并存时
                        #   出现两个气泡（用户反馈的"多选发送偶发显示两遍"）。
                        #   send_files_sync 内部已含每目标自动重试（断点续传）。
                        try:
                            fres = self.bridge.send_files_sync(targets, paths)
                        except Exception as e:
                            _keep(entry, f"发送异常: {e}")
                            continue
                        if not isinstance(fres, dict) or not any(
                                fres.get(t) == "ok" for t in targets):
                            bad = [t for t in targets
                                   if not isinstance(fres, dict)
                                   or fres.get(t) != "ok"]
                            _keep(entry, self._describe_send_fail(fres, bad))
                            continue
                        sent_box[0] += len(paths)
                        ok.append((entry, None, []))
            except Exception:
                # ★ 这里**绝不能写 remain = list(snapshot) / ok = []**。
                #   Python 编译器只要在函数体内看到对该名字赋值，就把它判为
                #   work() 的局部变量，外层同名变量被完全遮蔽 ->
                #   后面 emit 时读到"从未赋值的局部名" -> UnboundLocalError，
                #   结果永远送不到 UI 线程（队列条目删不掉且**无任何报错**）。
                #   正确做法：只清空容器内容，不重新绑定名字。
                ok.clear()
                remain.clear()
                remain.extend(snapshot)
                sent_box[0] = 0
            try:
                self.bridge.emit_pending_flush_done({
                    "snapshot": snapshot, "remain": remain,
                    "ok": ok, "sent": sent_box[0],
                })
            except Exception:
                # ★ 不能静默吞：这里抛异常会导致结果永远送不到 UI 线程，
                #   表现是"队列条目删不掉、也不报错"，极难定位。
                import traceback
                traceback.print_exc()

        threading.Thread(target=work, name="fd-flush-pending",
                         daemon=True).start()

    def _finish_pending_flush(self, payload: dict):
        """补发结果回到 UI 线程：提交队列 + 更新气泡 + 安排重试"""
        self._flush_running = False
        try:
            remain = payload.get("remain") or []
            ok = payload.get("ok") or []
            sent_n = payload.get("sent") or 0
            ok_ids = set(id(e) for e, _mid, _tg in ok)

            # ★ 只移除「本轮确认送达」的条目；
            #   失败 / 目标未上线 / flush 期间用户新加的条目一律保留。
            self._pending_files = [e for e in self._pending_files
                                   if id(e) not in ok_ids]
            self.cfg["pending_files"] = self._pending_files

            # 文本补发成功：用真实 mid 建气泡，才能收到 ack 把状态推进到已送达
            for entry, real_mid, targets in ok:
                mid = entry.get("mid")
                if real_mid and targets and self._queue_kind(entry) == "text":
                    self._out_text_msg(
                        list(targets), real_mid, entry.get("text") or "",
                        channel=self._channel_for(
                            list(targets), bool(entry.get("broadcast"))))
                if mid:
                    self._remove_pending_msg(mid)

            self._pending_btn_refresh()
            self._render_chat()
            if sent_n:
                self._toast(f"设备已上线，已自动发送 {sent_n} 条待发送内容")
            # 队列还剩东西 → 继续周期重试
            if self._pending_files:
                self._start_pending_retry()
            else:
                self._stop_pending_retry()
        except Exception as e:
            # ★ 必须打日志：这里曾经静默 except 导致"队列提交完全失效"
            #   而所有静态断言全绿，排查成本极高。
            try:
                import traceback
                traceback.print_exc()
            except Exception:
                pass
            self._flush_running = False

    def _start_pending_retry(self):
        """★ v1.18.15：待发队列周期重试（默认 10s），队列空了自动停"""
        t = getattr(self, "_pending_retry", None)
        if t is None:
            t = QTimer(self)
            t.setInterval(10000)
            t.timeout.connect(self._flush_pending)
            self._pending_retry = t
        if not t.isActive():
            t.start()

    def _stop_pending_retry(self):
        t = getattr(self, "_pending_retry", None)
        if t is not None and t.isActive():
            t.stop()

    def _do_send_files(self, targets, paths, intent=None, broadcast=False):
        """在线目标立即发送；离线目标进入待发队列（显示"待发送"消息，上线自动补发）"""
        paths = [p for p in paths if os.path.isfile(p)]
        if not paths:
            return
        online = set(pid for pid, p in self.peers.items() if p.get("online"))
        # targets 已由 _resolve_targets() 过滤为在线；intent 为用户勾选的全部设备（含离线）
        now = [t for t in (targets or []) if t in online]
        later = [t for t in (intent or []) if t not in online]
        if now:
            self.bridge.send_files(now, paths)
        if later:
            self._queue_files(paths, later)
        elif not now:
            # 无任何在线目标：记录用户意图（broadcast=群发；否则定向或空）
            self._queue_files(paths, list(intent or []), broadcast=broadcast)

    # ---------- 待发送管理窗口 ----------

    # ---------- 待发送管理（v1.13.0：改为气泡内标记，不再有独立入口） ----------

    def _pending_btn_refresh(self):
        """
        v1.13.0：待发送不再有独立的按钮入口。

        队列状态改为直接体现在聊天区气泡上（_show_pending_msg 把条目以
        state="pending" 渲染成气泡，设备上线后 _flush_pending 自动投递）。
        保留此方法是为了让原有的多处调用点无需改动。
        """
        btn = getattr(self, "pending_btn", None)
        if btn is None:
            return
        btn.setVisible(False)

    def _open_pending_window(self):
        """异步发送保存窗口：查看 / 取消 / 清空 待发队列"""
        dlg = PendingWindow(self)
        dlg.exec()

    def _pending_retry_now(self, mid):
        """手动立即补发一条待发内容（不依赖设备上线事件）

        ★ v1.18.15：不再「先删条目、再发送」—— 那会导致发送失败时消息直接丢失。
        统一交给确认送达才移除的补发流程；失败会留在队列里由周期重试继续发。
        """
        entry = next((e for e in self._pending_files if e.get("mid") == mid), None)
        if not entry:
            return
        online = [pid for pid, p in self.peers.items() if p.get("online")]
        if not online:
            self._toast("当前没有在线设备，仍保留在待发送队列")
            return
        targets = list(online) if (entry.get("broadcast")
                                   or not entry.get("targets")) \
            else [t for t in entry["targets"] if t in online]
        if not targets:
            self._toast("目标设备仍不在线")
            return
        self._flush_pending()

    def _pending_clear_all(self):
        self._pending_files = []
        self.cfg["pending_files"] = self._pending_files
        self._remove_pending_msg_all()
        self._pending_btn_refresh()
        self._toast("已清空待发送队列")

    def _remove_pending_msg_all(self):
        self.msgs.pop(self.PENDING_PEER, None)
        self._render_chat()

    def _pick_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择要发送的文件")
        if files:
            now, intent, bc = self._resolve_targets()
            self._do_send_files(now, files, intent=intent, broadcast=bc)

    def _pick_images(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择图片", "", "图片 (*.png *.jpg *.jpeg *.gif *.bmp *.webp)")
        if files:
            now, intent, bc = self._resolve_targets()
            self._do_send_files(now, files, intent=intent, broadcast=bc)

    def _send_clipboard_image(self) -> bool:
        """剪贴板有图片时保存为临时文件并直接发送；返回是否发送了图片"""
        img = QApplication.clipboard().image()
        if img.isNull():
            return False
        os.makedirs(self.cfg["cache_dir"], exist_ok=True)
        path = os.path.join(self.cfg["cache_dir"],
                            f"剪贴板_{util.gen_uid()[:6]}.png")
        img.save(path)
        now, intent, bc = self._resolve_targets()
        self._do_send_files(now, [path], intent=intent, broadcast=bc)
        return True

    def _send_clipboard(self):
        if self._send_clipboard_image():
            return
        text = QApplication.clipboard().text().strip()
        if text:
            self._send_input()
            return
        QMessageBox.information(self, "剪贴板", "剪贴板中没有文本或图片内容")

    # ================= 拖拽 =================

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent):
        files = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if files:
            now, intent, bc = self._resolve_targets()
            self._do_send_files(now, files, intent=intent, broadcast=bc)

    # ================= 历史 =================

    def _clear_chat(self):
        ids = self._view_peer_ids()
        if not ids:
            return
        if not confirm(self, "清空记录",
                       "确定清空当前视图的聊天记录吗？（不影响已接收的文件）"):
            return
        for pid in ids:
            self.msgs.pop(pid, None)
            self.history.clear(pid)
        self._render_chat()

    # ================= 设置/工具 =================

    def _open_settings(self):
        dlg = SettingsDialog(self.cfg, self)
        if dlg.exec():
            old_name = self.cfg["name"]
            dlg.apply()
            # 主题/配色可能同时变化，统一走 _apply_theme（含方案色注入）
            self._apply_theme()
            scheme_name = BUBBLE_SCHEMES.get(
                self.cfg["bubble_scheme"], {}).get("name", "闪传蓝")
            self._toast(f"设置已保存 · 气泡配色：{scheme_name}")
            if self.cfg["name"] != old_name:
                self.bridge.set_name(self.cfg["name"])
            self._update_self_info()
            # ★ v1.18.9：「离线聊天」开关直接影响设备列表是否合并离线设备，
            #   保存后必须立刻重绘一次，否则要等下次 UDP 广播（最长数秒）才变。
            try:
                self._on_peers(list(self.peers.values()))
            except Exception:
                pass

    def _set_scan_text(self, text):
        """扫描状态文案：空文本时隐藏整行（避免按钮下方常驻空白行）"""
        self.scan_lbl.setText(text)
        self.scan_lbl.setVisible(bool(text))

    def _add_device(self):
        dlg = AddDeviceDialog(self, self.cfg["port"])
        if dlg.exec():
            host, port = dlg.host_port()
            if not host:
                return
            self._set_scan_text(f"正在连接 {host}…")
            fut = self.bridge.connect_manual(host, port)

            def _worker():
                try:
                    ok, info = fut.result(20)
                except Exception as ex:
                    ok, info = False, str(ex)
                QTimer.singleShot(0, lambda: self._connect_result(ok, info, host))

            threading.Thread(target=_worker, daemon=True).start()

    def _connect_result(self, ok, info, host):
        if ok:
            self._set_scan_text(f"已连接：{info}")
            QTimer.singleShot(4000, lambda: self._set_scan_text(""))
            self._toast(f"已连接：{info}")
        else:
            self._set_scan_text("")
            QMessageBox.warning(self, "添加设备", f"连接 {host} 失败：{info}")

    def _deep_scan(self):
        self._manual_scanning = True
        self._set_scan_text("深度扫描中（约 10-60 秒）…")
        self.bridge.rescan(full=True)

    # ================= 窗口行为 =================

    def _show_and_activate(self):
        """把主窗口拉到前台。

        ★ v1.18.9 修复「EXE 双击打不开」：
        原实现只调 `showNormal() + show() + activateWindow()`。
        当窗口已被 `minimize_to_tray` 隐藏到托盘后，Windows 的前台锁定
        (SetForegroundWindow 规则) 会**静默拒绝** `activateWindow()`，
        窗口确实恢复了，但被压在其他窗口/任务栏后面 ——
        用户观感就是「双击了没反应 = 打不开」。

        修复三件套：
          1. 最小化 → 恢复；隐藏 → 显示（两条路径都要覆盖）
          2. `raise_()` 抬起 Z 序，避免被同级窗口遮挡
          3. Win32 `SetForegroundWindow` 兜底强制前台（对托盘唤醒最有效）
        """
        # 1) 恢复/显示
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        # 2) Z 序抬升
        self.raise_()
        # 3) 强制前台
        self.activateWindow()
        _force_foreground(self)

    def _on_tray_activated(self, reason):
        """托盘图标点击：左键单/双击都唤起（旧版只响应 DoubleClick，
        用户单击没反应也会觉得「打不开」）。"""
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._show_and_activate()

    def closeEvent(self, e: QCloseEvent):
        if self.cfg["minimize_to_tray"] and self.tray.isVisible():
            e.ignore()
            self.hide()
            self.tray.showMessage("闪传仍在运行",
                                  "已最小化到系统托盘，继续接收局域网消息。",
                                  QSystemTrayIcon.Information, 2000)
        else:
            self._real_quit()
            e.accept()

    def _real_quit(self):
        self.tray.hide()
        self.bridge.stop()
        QApplication.instance().quit()
