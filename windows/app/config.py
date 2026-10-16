# -*- coding: utf-8 -*-
"""FlashDrop Windows 配置管理（%APPDATA%\\FlashDrop\\config.json）"""

import json
import os
import sys
import threading

from . import util

APP_DIRNAME = "FlashDrop"


def app_data_dir() -> str:
    # 允许通过环境变量重定向数据目录（测试/便携模式）
    override = os.environ.get("FLASHDROP_DATA_DIR")
    if override:
        base = override
    else:
        base = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_DIRNAME)
    os.makedirs(base, exist_ok=True)
    return base


def default_save_dir() -> str:
    return os.path.join(os.path.expanduser("~"), APP_DIRNAME, "收到的文件")


def default_cache_dir() -> str:
    return os.path.join(os.path.expanduser("~"), APP_DIRNAME, "cache")


DEFAULTS = {
    "device_id": "",            # 首次生成
    "legacy_ids": [],           # 历史版本使用过的设备 ID（广播 alt 字段，供对端合并身份）
    "name": "",                 # 默认 用户名+的电脑
    "port": 58899,
    "save_dir": "",
    "cache_dir": "",
    "auto_accept": True,        # 自动接收文件
    "theme": "system",          # dark / light / system（跟随系统）
    "bubble_scheme": "blue",    # 气泡配色方案（见 theme.BUBBLE_SCHEMES）
    "minimize_to_tray": True,   # 关闭按钮最小化到托盘
    "notify_on_receive": True,  # 托盘通知
    "encrypt": False,           # 传输加密（TLS）：与开启加密的设备自动加密通信
    # 待发队列：目标离线时保存，设备上线后自动补发。
    # 条目结构（v1.9.0 统一文本与文件）：
    #   {"type": "file"|"text", "paths": [...], "text": str,
    #    "targets": [peer_id...], "broadcast": bool, "ts": int, "mid": str,
    #    "attempt": int,            # v1.18.18：已自动重试次数（缺省视为 0）
    #    "last_error": str}         # v1.18.18：最近一次补发失败原因
    # last_error/attempt 只在补发失败时写入，成功送出后随条目一起消失，
    # 供 PendingWindow 展示"为什么还在队列里、重试了几次"。
    # targets 为空 + broadcast=True 表示"全部设备"语义：上线即发给当时所有在线设备。
    # 旧版本条目无 type 字段，按文件处理（向后兼容）。
    "pending_files": [],
    "known_subnets": [],        # 历史发现过设备的子网，扫描优先
    "manual_peers": [],         # 手动添加的设备 [{host, port}]
    # ★ v1.18.0：截图时是否隐藏当前窗口（对齐微信的下拉三角选项）。
    # 默认 True = 隐藏，与旧版行为一致，用户升级后不会有意外变化。
    # 记住用户选择，下次点"截图"主按钮直接按该模式执行。
    "snip_hide_self": True,
    # ★ v1.18.9：离线聊天开关。
    # 开启（默认）后，设备离开同一网络仍然保留在左侧列表里，
    # 可以继续查看历史消息、发送离线消息（进待发队列，对方上线自动补发）。
    # 关闭后，离线设备只在「全部设备」视图里出现，左侧不单独列出。
    "offline_chat": True,
    # ★ v1.18.9：已知设备档案（离线也能显示在列表里的数据来源）。
    # 结构：{peer_id: {"id","name","platform","last_seen","ips"}}
    # 独立于 UDP 实时发现，设备下线后仍保留，解决"不同网络就丢聊天记录"。
    "known_peers": {},
    # ★ v1.18.18：设备备注/别名。{peer_id: "备注名"}
    # 只影响本机显示，不改写对端自报名（否则两端互相覆盖备注）。
    # 设备身份合并（跨版本）时由 node 迁移，删除设备时一并清除。
    "peer_aliases": {},
    "history_limit": 500,
}


class Config:
    def __init__(self, path=None):
        self.path = path or os.path.join(app_data_dir(), "config.json")
        self.data = dict(DEFAULTS)
        self._lock = threading.Lock()
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                self.data.update({k: v for k, v in saved.items() if k in DEFAULTS})
        except Exception:
            pass
        # 补默认值
        # 设备 ID：以主机名+MAC 派生的稳定 ID 为准（覆盖历史随机 ID，
        # 统一跨版本身份，避免同机多版本被识别为多台设备）
        stable = util.stable_device_id()
        prev = self.data.get("device_id")
        if prev and prev != stable:
            legacy = self.data.get("legacy_ids") or []
            if prev not in legacy:
                legacy.append(prev)
            self.data["legacy_ids"] = legacy[-8:]
        self.data["device_id"] = stable
        # 旧版默认名“<用户名>的电脑”自动迁移为主机名（避免多机重名）
        legacy = f"{os.environ.get('USERNAME') or os.environ.get('USER') or ''}的电脑"
        if not self.data.get("name") or self.data.get("name") == legacy:
            self.data["name"] = util.default_device_name()
        if not self.data.get("save_dir"):
            self.data["save_dir"] = default_save_dir()
        if not self.data.get("cache_dir"):
            self.data["cache_dir"] = default_cache_dir()
        self.save()

    def save(self):
        with self._lock:
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self.path)
            except Exception:
                pass

    # ---- 便捷访问 ----
    def __getitem__(self, k):
        return self.data.get(k)

    def __setitem__(self, k, v):
        self.data[k] = v
        self.save()

    @property
    def device_id(self) -> str:
        return self.data["device_id"]

    @property
    def name(self) -> str:
        return self.data["name"]

    @property
    def port(self) -> int:
        return int(self.data["port"])

    @property
    def save_dir(self) -> str:
        return self.data["save_dir"]

    @property
    def cache_dir(self) -> str:
        return self.data["cache_dir"]

    def ensure_dirs(self):
        for d in (self.save_dir, self.cache_dir):
            try:
                os.makedirs(d, exist_ok=True)
            except Exception:
                pass

    def remember_subnet(self, subnet: str):
        if not subnet:
            return
        subs = self.data.get("known_subnets") or []
        if subnet not in subs:
            subs.append(subnet)
            if len(subs) > 32:
                subs = subs[-32:]
            self.data["known_subnets"] = subs
            self.save()
