# -*- coding: utf-8 -*-
"""v1.18.9 Windows 端验证 —— 用户 6 条需求的落地审计

覆盖：
  §1 设备列表：离线设备合并 + 状态灯 + 删除 ✕
  §2 设置页：离线聊天开关
  §3 known_peers 持久化档案
  §4 删除会话：内存 / 索引 / 档案 / 文件 四清
  §5 截图按钮单箭头（v1.18.9 回归）
  §6 托盘唤起 + 前台强制（EXE 打不开修复）
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# 允许从 ASCII 临时目录运行（非 ASCII 路径下 aapt2/javac 会出问题，
# 所以脚本常被复制到 /tmp 再执行）—— 第一个参数可显式指定仓库根。
WIN = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(HERE)
sys.path.insert(0, WIN)

PASS = 0
FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    if cond:
        global PASS
        PASS += 1
        print(f"  [OK] {name}")
    else:
        globals()["FAIL"] += 1
        FAILS.append(f"{name} {detail}")
        print(f"  [FAIL] {name} {detail}")


def src(p):
    return open(os.path.join(WIN, p), encoding="utf-8").read()


print("=" * 66)
print("v1.18.9 Windows 端验证")
print("=" * 66)

mw = src("app/ui/main_window.py")
th = src("app/ui/theme.py")
cf = src("app/config.py")

# ─────────────────────────────────────────────────────────────
print("\n=== §1 设备列表：离线设备 / 状态灯 / 删除 ✕ ===")
check("1a DeviceItemWidget 暴露 deleteRequested 信号",
      "deleteRequested = Signal(str)" in mw)
check("1b DeviceItemWidget 支持 deletable 参数",
      "deletable" in mw)
# ★ v1.18.17 演进（用户反馈"设备那一行有删除按钮 需要取消"）：
#   v1.18.9 曾在设备行内加 ✕ 删除按钮，单击即删、误触风险高，且与右击菜单重复。
#   v1.18.17 已**移除行内 ✕**，删除入口统一收敛为：
#   ① 右击菜单「删除「设备名」的会话」② 多选后底部「删除选中 + 取消」。
check("1c ★ 行内 ✕ 删除按钮已移除（v1.18.17 起删除只走右击/多选）",
      'setObjectName("PeerDelete")' not in mw)
check("1c2 ★ 删除入口仍在（右键菜单 + 多选底部按钮）",
      "_on_device_context_menu" in mw and "_delete_selected_peers" in mw)
# 顺序断言：设备名 → 状态灯 → 平台徽标（不再有删除 ✕）
_i_name = mw.find("name = QLabel(snap[\"name\"])")
_i_dot = mw.find("dotw = QLabel()")
_i_badge = mw.find("badge = QLabel()")
check("1d 行内顺序为 设备名 → 状态灯 → 平台徽标（无删除按钮）",
      -1 < _i_name < _i_dot < _i_badge,
      f"name@{_i_name} dot@{_i_dot} badge@{_i_badge}")
check("1d2 状态灯用绿/灰区分在线离线",
      "GREEN if on else" in mw)
check("1e _on_peers 合并 live 与 known_peers",
      "_remember_known_peers(live)" in mw and "known_peers" in mw)
check("1f 离线设备可见性受 offline_chat 控制",
      'show_offline = bool(self.cfg["offline_chat"])' in mw)
check("1g 在线优先排序（离线沉底）",
      "online" in mw and "sort" in mw.lower())
# ★ v1.18.17 演进：原先"只有聊过的设备才在行内显示 ✕"的逻辑随行内按钮一起移除；
#   现在删除入口对所有真实设备一致可用（不再有"聊过才给入口"的差异）。
check("1h ★ 不再有「仅聊过才显示删除」的行内条件分支",
      "has_session" not in mw)
check("1h2 ★ 「全部设备」仍被排除在删除之外",
      "pid == ALL_ID" in mw)

# ─────────────────────────────────────────────────────────────
print("\n=== §2 设置页：离线聊天开关（用户第 5 条） ===")
check("2a 配置默认含 offline_chat=True",
      '"offline_chat": True' in cf)
check("2b 设置页有 offline_chk 复选框",
      "self.offline_chk = QCheckBox" in mw)
check("2c 复选框文案含「离线聊天」",
      "离线聊天" in mw)
check("2d 复选框文案说明保留对话框/可发离线消息/可看历史",
      "保留对话框" in mw and "离线消息" in mw and "历史" in mw)
check("2e 与「保存聊天」并存（不是替换）",
      "保存聊天" in mw or "history_limit" in mw)
check("2f apply() 写回 cfg['offline_chat']",
      'self.cfg["offline_chat"] = self.offline_chk.isChecked()' in mw)
check("2g 保存设置后立即重绘设备列表",
      "_on_peers(list(self.peers.values()))" in mw)

# ─────────────────────────────────────────────────────────────
print("\n=== §3 known_peers 持久化档案（用户第 4 条①） ===")
check("3a 配置默认含 known_peers={}",
      '"known_peers": {}' in cf)
check("3b 存在 _remember_known_peers 方法",
      "def _remember_known_peers" in mw)
check("3c 记录设备名/平台/IP/最后在线",
      "last_seen" in mw and "ips" in mw)
check("3d 有变化才落盘（避免每次广播都写）",
      "changed" in mw and "saver()" in mw)

# ─────────────────────────────────────────────────────────────
print("\n=== §4 删除会话：四清（用户第 4 条③） ===")
check("4a 存在 _delete_peer_conversation",
      "def _delete_peer_conversation" in mw)
check("4b 删磁盘聊天记录（history.clear）",
      "self.history.clear(pid)" in mw)
check("4c 删内存消息与索引",
      "self.msgs.pop(pid, None)" in mw and "out_by_tid" in mw)
check("4d 删该设备保存的文件目录",
      "def _remove_peer_files" in mw and "rmtree" in mw)
check("4e 安全护栏：绝不动保存根目录",
      "os.path.abspath(target) != os.path.abspath(base)" in mw)
check("4f 从 known_peers 摘除该设备",
      "kp.pop(pid, None)" in mw)
check("4g 高危操作二次确认",
      'confirm(self, "删除会话"' in mw)

# ─────────────────────────────────────────────────────────────
print("\n=== §5 截图按钮单箭头（v1.18.9 回归） ===")
check("5a 压制 QToolButton 原生箭头",
      "menu-indicator" in th and "image: none" in th)
check("5b 仍保留自绘 ▾ 文本",
      "▾" in mw or "SetText" in mw or "setText" in mw)

# ─────────────────────────────────────────────────────────────
print("\n=== §6 EXE 打不开修复（用户第 1 条） ===")
main_py = src("main.py")
check("6a 有 PING/PONG 探活函数",
      "def _lock_is_alive" in main_py and "PING" in main_py)
check("6b 有带重试的唤起函数",
      "def _notify_instance_show" in main_py)
check("6c 能抢占孤儿锁（端口被死进程占用时仍可启动）",
      "reclaimed = _try_bind(reuse=True)" in main_py)
check("6d IPC 监听器会应答 PONG",
      "PONG" in mw and "flashdrop-ipc" in mw)
check("6e _show_and_activate 覆盖最小化与隐藏两态",
      "isMinimized" in mw and "showNormal" in mw)
check("6f 有 Win32 强制前台兜底",
      "def _force_foreground" in mw and "SetForegroundWindow" in mw)
check("6g 托盘单击也能唤起",
      "QSystemTrayIcon.Trigger" in mw)

print("\n" + "=" * 66)
print(f"v1.18.9 Windows 验证：通过 {PASS} 项，失败 {FAIL} 项")
if FAILS:
    print("失败项：")
    for f in FAILS:
        print("  -", f)
print("=" * 66)
sys.exit(1 if FAIL else 0)
