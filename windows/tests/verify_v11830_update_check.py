# -*- coding: utf-8 -*-
"""v1.18.30 更新功能 + 角标修复验收

用户需求：
  1. 双端增加软件更新功能（数据源：GitHub Releases，仓库 Thomajesty/FlashDrop）；
  2. 把软件推送到 git（本地仓库初始化/提交由单独步骤验收，本脚本管功能）；
  3. 安卓版未收到消息时图标也显示红色 1 —— NotificationChannel 默认
     setShowBadge(true)，后台服务常驻通知被国产 ROM 计入未读 → 桌面角标常亮。
     修法：服务通知渠道 setShowBadge(false)，消息渠道保留 badge；
     回前台主动 cancel 后台消息通知，避免已读后角标残留。

本脚本五层验收：
  A. 两端代码静态断言：更新入口、常量一致（owner/repo 双端对齐）、
     静默检查限频、失败可见（不静默吞）；
  B. 版本比较仿真：12 个边界用例，两端同算法；
  C. GitHub API 解析仿真：mock 响应 → version/notes/assets 挑选，
     非语义 tag / 网络失败 / assets 缺失的降级路径；
  D. 限频与跳过版本逻辑；
  E. 角标修复断言：服务渠道关 badge、消息通知 id 登记与回前台清理。

运行：python windows/tests/verify_v11830_update_check.py
"""
import io
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
WIN = os.path.join(ROOT, "windows", "app")
AND = os.path.join(ROOT, "android", "app", "src", "main", "java",
                   "com", "flashdrop", "app")

FAILS = []
N = 0


def ck(name, ok, detail=""):
    global N
    N += 1
    mark = "✓" if ok else "✗"
    print(f"  [{mark}] {name}" + (f"  —— {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name + (f" —— {detail}" if detail else ""))


def rd(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


print("=" * 72)
print("v1.18.30 验收：双端更新功能（GitHub Releases）+ 安卓角标修复")
print("=" * 72)

# ============================================================
print("\n■ A. 两端代码静态断言")
# ============================================================
updater_py = os.path.join(WIN, "updater.py")
main_py = os.path.join(WIN, "ui", "main_window.py")
cfg_py = os.path.join(WIN, "config.py")
ck("windows/app/updater.py 存在", os.path.isfile(updater_py))

upd = rd(updater_py)
ck("updater 的 API 模板指向 GitHub Releases latest",
   'https://api.github.com/repos/%s/%s/releases/latest' in upd
   and "GITHUB_OWNER" in upd and "GITHUB_REPO" in upd)
ck("updater 仓库常量 = Thomajesty/FlashDrop",
   'GITHUB_OWNER = "Thomajesty"' in upd and 'GITHUB_REPO = "FlashDrop"' in upd)
ck("updater 有语义版本比较 is_newer", "def is_newer" in upd)
ck("updater 有资产挑选 asset_for", "def asset_for" in upd)
ck("updater 有每日限频 auto_check_allowed/mark_auto_checked",
   "def auto_check_allowed" in upd and "def mark_auto_checked" in upd)
ck("updater 有跳过版本 version_skipped/mark_version_skipped",
   "def version_skipped" in upd and "def mark_version_skipped" in upd)
ck("updater 超时 8s（国内直连 GitHub 防卡）", "8.0" in upd)

mw = rd(main_py)
ck("MainWindow 有 UpdateChecker（后台线程+信号回主线程）",
   "class UpdateChecker" in mw and "Signal(object)" in mw)
ck("MainWindow 有 UpdateDialog（版本对比+更新日志+下载）",
   "class UpdateDialog" in mw and "setReadOnly(True)" in mw)
ck("UpdateDialog 有下载/跳过/稍后三个动作",
   all(k in mw for k in ("下载 Windows 版", "下载 Android 版", "跳过此版本")))
ck("设置页有「检查更新」入口", "检查更新" in mw and "_check_update" in mw)
ck("启动静默检查 _auto_check_update（每天一次）",
   "_auto_check_update" in mw and "auto_check_allowed" in mw)
ck("检查失败明确提示（不静默）",
   "检查失败：网络不可达或 GitHub 限流" in mw)
ck("跨线程用 Signal（不用 QTimer.singleShot 从工作线程调）",
   "self.finished.emit(info)" in mw)

cfg = rd(cfg_py)
ck("Config 有 last_update_check / skipped_version 字段",
   '"last_update_check"' in cfg and '"skipped_version"' in cfg)

# ---- Android 侧 ----
uc_java = os.path.join(AND, "UpdateChecker.java")
ck("android UpdateChecker.java 存在", os.path.isfile(uc_java))
uc = rd(uc_java)
ck("UpdateChecker API 模板指向 GitHub Releases latest（双端仓库对齐）",
   "https://api.github.com/repos/" in uc and "releases/latest" in uc
   and 'REPO_OWNER = "Thomajesty"' in uc and 'REPO_NAME = "FlashDrop"' in uc)
ck("UpdateChecker 有 isNewer/assetFor/check/showUpdateDialog",
   all(k in uc for k in ("isNewer", "assetFor", "public static void check",
                          "showUpdateDialog")))
ck("UpdateChecker 超时 8s", "8000" in uc)
ck("check() 回调切主线程（Handler(Looper.getMainLooper())）",
   "Looper.getMainLooper()" in uc)

sa = rd(os.path.join(AND, "SettingsActivity.java"))
ck("设置页有「检查更新」按钮与 onCheckUpdate",
   "检查更新" in sa and "onCheckUpdate" in sa)
ck("手动检查失败有 Toast 提示（不静默）",
   "检查失败：网络不可达或 GitHub 限流" in sa)

ma = rd(os.path.join(AND, "MainActivity.java"))
ck("MainActivity 启动静默检查 maybeCheckUpdate（每天一次）",
   "maybeCheckUpdate" in ma and "lastUpdateCheck" in ma)

pf = rd(os.path.join(AND, "Prefs.java"))
ck("Prefs 有 lastUpdateCheck/skippedVersion 四个方法",
   all(k in pf for k in ("lastUpdateCheck", "setLastUpdateCheck",
                          "skippedVersion", "setSkippedVersion")))

# ============================================================
print("\n■ B. 版本比较仿真（12 边界用例，直接调 Windows 端实现）")
# ============================================================
sys.path.insert(0, WIN)     # updater.py 只依赖标准库，可直接 import
try:
    import updater as U
except Exception as e:      # pragma: no cover
    U = None
    ck("导入 windows updater 模块", False, str(e))

CASES = [
    ("1.18.30", "1.18.29", True),   # 补位号 +1
    ("v1.18.30", "1.18.29", True),  # v 前缀
    ("1.19.0", "1.18.29", True),    # 次位进位（不能按字符串比！）
    ("1.18.9", "1.18.10", False),   # 9 < 10（不能按字符串比！）
    ("1.18.29", "1.18.29", False),  # 同版本不提示
    ("1.18.30-beta", "1.18.29", True),   # 预发布仍算新（数字段比较）
    ("V1.18", "1.17.999", True),    # 大 V + 缺段补 0
    ("abc", "1.18.29", False),      # 无法解析 → 保守不提示
    ("1.18.29", "xyz", False),      # 当前版本无法解析 → 不提示
    ("", "1.0", False),             # 空串
    ("1.18.30.1", "1.18.30", True),  # 第四段
    ("2.0", "1.99.99", True),       # 主位
]
if U:
    bad = [(a, b, e) for a, b, e in CASES if U.is_newer(a, b) != e]
    ck("12/12 边界用例通过", not bad, str(bad))

    # 反向防护：字符串比较会误判的经典场景必须成立
    ck("反向防护：'1.18.9' 不比 '1.18.10' 新（字符串比较会误判）",
       not U.is_newer("1.18.9", "1.18.10"))

# ============================================================
print("\n■ C. GitHub API 解析仿真（mock 响应）")
# ============================================================
if U:
    def mock_urlopen(payload, code=200):
        class R:
            status = code
            def read(self):
                return json.dumps(payload).encode()
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
        return R()

    GOOD = {
        "tag_name": "v1.18.30",
        "body": "## 更新内容\n- 新增检查更新\n- 修复角标",
        "html_url": "https://github.com/Thomajesty/FlashDrop/releases/tag/v1.18.30",
        "assets": [
            {"name": "FlashDrop_v1.18.30_win.exe",
             "browser_download_url": "https://gh/exe", "size": 53614539},
            {"name": "FlashDrop_v1.18.30.apk",
             "browser_download_url": "https://gh/apk", "size": 2926193},
        ],
    }

    real = urllib.request.urlopen
    try:
        urllib.request.urlopen = lambda req, timeout=None: mock_urlopen(GOOD)
        info = U.fetch_latest()
        ck("正常响应：version 去掉 v 前缀", info and info["version"] == "1.18.30")
        ck("正常响应：notes/ html_url 带出", info and "修复角标" in info["notes"]
           and info["html_url"].endswith("v1.18.30"))
        ck("正常响应：两个附件都解析出来", info and len(info["assets"]) == 2)
        ck("asset_for('.exe') 挑到 Windows 包",
           U.asset_for(info, ".exe")["url"] == "https://gh/exe")
        ck("asset_for('.apk') 挑到安卓包",
           U.asset_for(info, ".apk")["url"] == "https://gh/apk")
        ck("asset_for('.dmg') 找不到返回 None", U.asset_for(info, ".dmg") is None)

        # 非语义 tag → 不提示（防止把 nightly 之类推给用户）
        urllib.request.urlopen = lambda req, timeout=None: mock_urlopen(
            {"tag_name": "nightly-build", "assets": []})
        ck("非语义 tag（nightly-build）→ 返回 None 不提示",
           U.fetch_latest() is None)

        # 无 assets 字段
        urllib.request.urlopen = lambda req, timeout=None: mock_urlopen(
            {"tag_name": "v1.18.31"})
        info2 = U.fetch_latest()
        ck("无 assets 字段不炸，assets 为空列表",
           info2 is not None and info2["assets"] == [])

        # 网络失败（抛异常）→ None
        def boom(req, timeout=None):
            raise OSError("timeout")
        urllib.request.urlopen = boom
        ck("网络超时 → None（调用方按失败提示，不崩溃）",
           U.fetch_latest() is None)
    finally:
        urllib.request.urlopen = real

    # ============================================================
    print("\n■ D. 限频与跳过版本")
    # ============================================================
    class FakeCfg(dict):
        pass

    import datetime
    cfg1 = FakeCfg(last_update_check="", skipped_version="")
    ck("首次启动允许静默检查", U.auto_check_allowed(cfg1))
    U.mark_auto_checked(cfg1)
    ck("标记后当天不再重复检查", not U.auto_check_allowed(cfg1))
    cfg2 = FakeCfg(last_update_check="1999-01-01", skipped_version="")
    ck("昨天查过 → 今天允许", U.auto_check_allowed(cfg2))

    ck("默认不跳过任何版本", not U.version_skipped(cfg2, "1.18.30"))
    U.mark_version_skipped(cfg2, "1.18.30")
    ck("标记后该版本被跳过", U.version_skipped(cfg2, "1.18.30"))
    ck("其他版本不受跳过影响", not U.version_skipped(cfg2, "1.18.31"))

# ============================================================
print("\n■ E. 角标修复断言（安卓）")
# ============================================================
ns = rd(os.path.join(AND, "NodeService.java"))
ck("服务通知渠道 CH_ID 关 badge（setShowBadge(false)）",
   ns.count("setShowBadge(false)") >= 2)
ck("消息通知渠道 CH_MSG 保留 badge（只有真实消息亮角标）",
   "chM.setShowBadge(true)" in ns)
ck("notifyMessage 登记通知 id（addActiveNotifId）",
   "addActiveNotifId" in ns)

fa = rd(os.path.join(AND, "FlashApp.java"))
ck("FlashApp 有 activeNotifIds 登记与 clearMessageNotifications",
   "activeNotifIds" in fa and "clearMessageNotifications" in fa)
ck("clearMessageNotifications 不动常驻通知（只 cancel 登记的 id）",
   "for (Integer id : activeNotifIds)" in fa)

ck("MainActivity.onResume 调用 clearMessageNotifications（已读消角标）",
   "FlashApp.get().clearMessageNotifications()" in ma)

# ============================================================
print("\n" + "=" * 72)
if FAILS:
    print(f"结果：{N - len(FAILS)}/{N} 通过，{len(FAILS)} 个失败：")
    for f in FAILS:
        print("  ✗", f)
    sys.exit(1)
print(f"结果：{N}/{N} 全部通过 ✅")
print("=" * 72)
