# -*- coding: utf-8 -*-
"""软件更新检查 —— 数据源 GitHub Releases（v1.18.30 新增，双端对称）。

设计要点：
- 双端共用同一仓库（Thomajesty/FlashDrop）：Windows exe 与 Android apk
  都挂在 Release 附件上，本模块负责"查最新版本 / 比较语义版本 / 挑安装包"，
  不碰 UI（线程与信号封装见 ui/main_window.py 的 UpdateChecker）。
- 频率控制：启动静默检查每天最多 1 次（last_update_check 记日期）；
  手动检查不限频（GitHub 未认证限额 60 次/小时/IP，用户主动点击量极小）。
- 国内网络直连 api.github.com 常超时：统一 8s 超时，失败返回 None 由调用方
  决定提示方式；**绝不静默吞掉**——手动检查失败会明确告知用户。
"""

import json
import urllib.request

# ---------- 仓库配置（与 Android 端 FdUtil.UPDATE_REPO 保持一致） ----------
GITHUB_OWNER = "Thomajesty"
GITHUB_REPO = "FlashDrop"
API_LATEST = "https://api.github.com/repos/%s/%s/releases/latest" % (GITHUB_OWNER, GITHUB_REPO)
RELEASES_PAGE = "https://github.com/%s/%s/releases" % (GITHUB_OWNER, GITHUB_REPO)

HTTP_TIMEOUT = 8.0
USER_AGENT = "FlashDrop-Updater"


def parse_version(text):
    """把版本号解析为可比较的元组；无法解析返回 None（调用方按"不提示"处理）。

    接受形式：v1.18.29 / 1.18.29 / V1.18 / 1.18.30-beta / 1.18.30+build5。
    只比较数字段（缺段补 0，最多取 4 段），预发布/构建后缀忽略。
    """
    if text is None:
        return None
    s = str(text).strip()
    if s[:1] in ("v", "V"):
        s = s[1:]
    core = s.split("-")[0].split("+")[0]
    if not core:
        return None
    nums = []
    for p in core.split("."):
        if not p.isdigit():
            return None
        nums.append(int(p))
        if len(nums) == 4:
            break
    if not nums:
        return None
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


def is_newer(latest, current):
    """latest 是否严格新于 current；任一侧无法解析时返回 False（保守：不提示）。"""
    a = parse_version(latest)
    b = parse_version(current)
    if a is None or b is None:
        return False
    return a > b


def fetch_latest(timeout=HTTP_TIMEOUT):
    """查询仓库最新 Release。

    返回 dict：
        {"version": "1.18.30",          # 去 v 前缀的版本号
         "tag": "v1.18.30",             # 原始 tag
         "notes": "...",                # 更新日志（markdown 原文）
         "html_url": "...",             # Release 页面
         "assets": [{"name","url","size"}...]}
    任何失败（网络超时/限流/JSON 异常/字段缺失）返回 None。
    """
    req = urllib.request.Request(
        API_LATEST,
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    tag = data.get("tag_name") or ""
    ver = parse_version(tag)
    if ver is None:
        return None
    assets = []
    for a in data.get("assets") or []:
        if not isinstance(a, dict):
            continue
        name = a.get("name") or ""
        url = a.get("browser_download_url") or ""
        if name and url:
            assets.append({"name": name, "url": url,
                           "size": int(a.get("size") or 0)})
    return {
        "version": ".".join(str(x) for x in ver),
        "tag": tag,
        "notes": data.get("body") or "",
        "html_url": data.get("html_url") or RELEASES_PAGE,
        "assets": assets,
    }


def asset_for(info, suffix):
    """从最新 Release 附件里挑某个平台的安装包；找不到返回 None。"""
    if not info:
        return None
    suf = suffix.lower()
    for a in info.get("assets") or []:
        if a.get("name", "").lower().endswith(suf):
            return a
    return None


def auto_check_allowed(cfg):
    """启动静默检查的限频：今天还没查过才允许。cfg 为 Config 实例或 dict。"""
    try:
        last = cfg["last_update_check"]
    except Exception:
        return True
    from datetime import date
    return last != date.today().isoformat()


def mark_auto_checked(cfg):
    """记录今天已做过静默检查。"""
    from datetime import date
    try:
        cfg["last_update_check"] = date.today().isoformat()
    except Exception:
        pass


def version_skipped(cfg, version):
    """用户是否选择跳过该版本。"""
    try:
        return bool(cfg["skipped_version"]) and cfg["skipped_version"] == version
    except Exception:
        return False


def mark_version_skipped(cfg, version):
    try:
        cfg["skipped_version"] = version
    except Exception:
        pass
