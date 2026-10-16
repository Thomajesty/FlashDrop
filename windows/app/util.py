# -*- coding: utf-8 -*-
"""FlashDrop Windows 端公共工具"""

import hashlib
import os
import re
import socket
import uuid

_URL_RE = re.compile(
    r"(https?://[^\s，。；！？、（）【】《》\"'<>]+|www\.[^\s，。；！？、（）【】《》\"'<>]+)",
    re.IGNORECASE)


def first_url(text: str):
    """提取文本中的第一个链接（www.* 自动补 http://），无链接返回 None"""
    m = _URL_RE.search(text or "")
    if not m:
        return None
    u = m.group(1).rstrip(".,;:!?)]}")
    return u if u.lower().startswith("http") else "http://" + u


def short_url(url: str, maxlen=42) -> str:
    return url if len(url) <= maxlen else url[:maxlen - 1] + "…"


def gen_device_id() -> str:
    return uuid.uuid4().hex[:16]


def stable_device_id() -> str:
    """由主机名 + 主 MAC 派生的稳定设备 ID：同机跨版本/重装配置身份不变

    ★ 环境变量 `FLASHDROP_DEVICE_ID` 可强制指定（仅供自动化测试隔离用）：
    同一台机器上跑多个测试实例时，派生 ID 会全部相同，
    导致测试节点与真实运行实例互相发现，断言结果不可信。
    """
    forced = os.environ.get("FLASHDROP_DEVICE_ID", "").strip()
    if forced:
        return forced[:16]
    try:
        node = uuid.getnode()
        mac = "-".join(f"{(node >> i) & 0xFF:02x}" for i in range(0, 48, 8))
    except Exception:
        mac = "unknown"
    base = f"FlashDrop|{socket.gethostname()}|{mac}"
    return hashlib.md5(base.encode("utf-8")).hexdigest()[:16]


def gen_uid() -> str:
    return uuid.uuid4().hex


def default_device_name() -> str:
    """默认设备名使用主机名（全网唯一），避免不同电脑上同名用户导致重名"""
    try:
        host = (socket.gethostname() or "").strip().split(".")[0]
    except Exception:
        host = ""
    return host or "我的电脑"


def fmt_size(n: float) -> str:
    """字节数格式化为人类可读"""
    try:
        n = float(n)
    except Exception:
        return str(n)
    if n < 1024:
        return f"{int(n)} B"
    for unit in ("KB", "MB", "GB", "TB"):
        n /= 1024.0
        if n < 1024:
            return f"{n:.1f} {unit}"
    return f"{n:.1f} PB"


def fmt_speed(bps: float) -> str:
    if bps <= 0:
        return "0 B/s"
    return fmt_size(bps) + "/s"


def md5_of_chunk(h, data: bytes):
    if h is None:
        h = hashlib.md5()
    h.update(data)
    return h


_INVALID_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def safe_filename(name: str, default: str = "file") -> str:
    """去掉文件名中的非法字符与路径分隔，防止目录穿越"""
    name = (name or "").strip().replace("\\", "_").replace("/", "_")
    name = _INVALID_NAME.sub("", name)
    name = name.strip(" .")
    if not name or name in (".", ".."):
        return default
    return name[:200]


def safe_folder(name: str, default: str = "未知设备") -> str:
    """设备名 → 安全的子文件夹名（用于按设备归档接收文件）。

    与 Android 端 FdUtil.folderNameOf 保持同一套规则，
    同一台设备在手机和电脑上落到同名文件夹，跨端查找直观。

    注意顺序：非法字符必须先"替换成 _"再剥前后空白。
    若先用 _INVALID_NAME.sub("", ...) 删除，后续替换分支永远不会执行，
    两端口径会不一致（Windows 端曾因此把 "a:b" 变成 "ab"）。
    """
    s = (name or "").strip()
    if not s:
        return default
    # 先把路径分隔符与 Windows 非法字符统一替换成 _（Android 端同规则）
    s = s.replace("\\", "_").replace("/", "_")
    s = "".join("_" if (ord(c) < 0x20 or c in '\\/:*?"<>|') else c for c in s)
    s = s.strip()
    s = s.strip(" .")
    while s.startswith("."):
        s = s[1:]
    if not s:
        return default
    return s[:40]


def unique_path(dirpath: str, filename: str) -> str:
    """在目录中获取不冲突的完整路径：a.txt -> a (1).txt -> a (2).txt"""
    base, ext = os.path.splitext(filename)
    cand = os.path.join(dirpath, filename)
    i = 1
    while os.path.exists(cand):
        cand = os.path.join(dirpath, f"{base} ({i}){ext}")
        i += 1
    return cand


def guess_mime(name: str) -> str:
    ext = os.path.splitext(name)[1].lower()
    mimes = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".bmp": "image/bmp", ".webp": "image/webp",
        ".svg": "image/svg+xml", ".ico": "image/x-icon",
        ".mp4": "video/mp4", ".mkv": "video/x-matroska", ".avi": "video/x-msvideo",
        ".mov": "video/quicktime", ".mp3": "audio/mpeg", ".flac": "audio/flac",
        ".wav": "audio/wav", ".aac": "audio/aac",
        ".pdf": "application/pdf", ".txt": "text/plain", ".md": "text/markdown",
        ".doc": "application/msword", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xls": "application/vnd.ms-excel", ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".ppt": "application/vnd.ms-powerpoint", ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".zip": "application/zip", ".rar": "application/vnd.rar", ".7z": "application/x-7z-compressed",
        ".exe": "application/vnd.microsoft.portable-executable", ".apk": "application/vnd.android.package-archive",
        ".json": "application/json", ".csv": "text/csv", ".html": "text/html", ".htm": "text/html",
    }
    return mimes.get(ext, "application/octet-stream")


def is_image_mime(mime: str) -> bool:
    return mime.startswith("image/") and mime not in ("image/svg+xml",)
