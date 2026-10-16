# -*- coding: utf-8 -*-
"""v1.18.15 专项验收 —— 离线待发队列「确认送达才移除」（双端静态审计）。

用户反馈：安卓给电脑发离线消息，等电脑上线上「对方收不到、发送端也失败」。

根因（v1.18.13 / v1.18.14 两端一致）：
    flush 调用 send_text（**异步**，内部还要 wait_conn 等 TCP 最多 15s、
    再等 ack 12s）之后，**立刻**把条目从队列删掉并落盘。
    设备刚上线时 UDP 已判在线 → 触发 flush，但 TCP 往往还没建好 →
    发送失败 → 条目已丢 → 消息永久丢失。且队列**无任何重试**，等于必丢。

修法（三条，两端对称）：
    1. 确认送达（收到 ack）才移除条目；失败/超时一律保留
    2. 补发移到工作线程（不能压 UI 线程）
    3. 队列非空且有在线设备时周期重试（10s），队列空了自动停

行为级验证见：
    android/tools/run_rt11815.sh   （驱动真实 FlashApp，14 项）
    windows/tests/verify_v11815_pending.py （驱动真实 MainWindow，15 项）

运行：python tests/verify_v11815.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
AND = os.path.join(ROOT, "app", "src", "main", "java", "com", "flashdrop", "app")
WIN = os.path.join(os.path.dirname(ROOT), "windows")

MA = open(os.path.join(AND, "MainActivity.java"), encoding="utf-8").read()
FA = open(os.path.join(AND, "FlashApp.java"), encoding="utf-8").read()
FN = open(os.path.join(AND, "FlashNode.java"), encoding="utf-8").read()
NS = open(os.path.join(AND, "NodeService.java"), encoding="utf-8").read()
NODE = open(os.path.join(WIN, "app", "node.py"), encoding="utf-8").read()
MW = open(os.path.join(WIN, "app", "ui", "main_window.py"), encoding="utf-8").read()
BR = open(os.path.join(WIN, "app", "ui", "bridge.py"), encoding="utf-8").read()

P, F = [], []


def check(name, cond, detail=""):
    (P if cond else F).append(name)
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", name,
                          ("   " + detail) if (detail and not cond) else ""))


def sec(t):
    print("\n" + "=" * 68)
    print(t)
    print("=" * 68)


# ==================================================================
sec("① 安卓：发送侧支持阻塞等结果")
check("★ FlashNode 新增 sendTextSync（阻塞，返回每目标结果）",
      "public Object[] sendTextSync(" in FN)
check("sendTextSync 用 waitConn 等连接（带超时参数）",
      re.search(r"public Object\[\] sendTextSync\([^)]*\)\s*\{.*?waitConn\(pid, connTimeoutMs\)",
                FN, re.S) is not None)
check("sendTextSync 用 waitSlot 等 ack（带超时参数）",
      re.search(r"sendTextSync\([^)]*\)\s*\{.*?waitSlot\(slot, ackTimeoutMs\)", FN,
                re.S) is not None)
check("★ 每目标结论写入 results（ok/failed/timeout）",
      re.search(r'sendTextSync\([^)]*\)\s*\{.*?res\.put\(pid, "failed"\)', FN, re.S)
      is not None
      and '"timeout"' in FN)

# ==================================================================
sec("② 安卓：补发确认送达才移除 + 周期重试 + 不误删新增条目")
check("★ 新增 flushPendingSendsAsync（后台线程执行）",
      "public void flushPendingSendsAsync(" in FA)
check("★ 补发走 flushPool.execute（离开 UI 线程）",
      re.search(r"flushPendingSendsAsync\([^)]*\)\s*\{.*?flushPool\.execute\(",
                FA, re.S) is not None)
check("★ 用 sendTextSync 等结果，全部失败则保留条目",
      re.search(r"flushPendingSendsAsync\([^)]*\)\s*\{.*?"
                r"sendTextSync\([^)]*\).*?if \(!anyOk\)\s*\{.*?failed\.add\(ps\)",
                FA, re.S) is not None)
check("★ 只移除确认送达的条目（按快照身份比对）",
      re.search(r"if \(snapshot\.contains\(p\)\)", FA) is not None)
check("★ 快照之外新增的条目被保留（不误删）",
      re.search(r"next\.add\(p\);", FA) is not None)
check("★ 防重入：flushing 原子标志",
      re.search(r"flushing\.compareAndSet\(false, true\)", FA) is not None)
check("★ 周期重试：RETRY_INTERVAL_MS = 10s",
      re.search(r"RETRY_INTERVAL_MS\s*=\s*10_000L", FA) is not None)
check("★ schedulePendingRetry 幂等挂载",
      "public void schedulePendingRetry()" in FA
      and "mainHandler.removeCallbacks(retryTask)" in FA)
check("重试任务：队列非空且有在线设备才补发",
      re.search(r"if \(!pendingSends\.isEmpty\(\) && !node\(\)\.onlinePeerIds\(\)\.isEmpty\(\)\)",
                FA) is not None)
check("★ 队列非空时自动续上重试",
      re.search(r"if \(!pendingSends\.isEmpty\(\)\) schedulePendingRetry\(\);", FA)
      is not None)
check("旧同步版 flushPendingSends 已改为转调异步（不再自行删条目）",
      re.search(r"public int flushPendingSends\(java\.util\.function\.Consumer<PendingSend> onSent,\s*\n"
                r"\s*java\.util\.function\.BiConsumer<PendingSend, String> onTextSent\) \{"
                r"\s*\n\s*//.*\n\s*flushPendingSendsAsync\(", MA, re.S) is not None
      or "flushPendingSendsAsync(null, onSent, onTextSent);" in FA)

# ==================================================================
sec("③ 安卓：三个触发点都接到新的补发流程")
check("MainActivity peers 事件改用 flushPendingSendsAsync",
      "flushPendingSendsAsync(" in MA)
check("MainActivity 补发成功后才重建待发送气泡",
      re.search(r"rebuildPendingMsgs\(\);\s*\n\s*refreshPendingBtn\(\);", MA) is not None)
check("MainActivity onResume 挂上周期重试",
      re.search(r"protected void onResume\(\).*?schedulePendingRetry\(\)", MA, re.S)
      is not None)
check("NodeService 后台 peers 事件也走异步补发",
      re.search(r'"peers"\.equals\(ev\).*?flushPendingSendsAsync\(', NS, re.S) is not None)
check("NodeService onCreate 挂上周期重试",
      re.search(r"public void onCreate\(\).*?schedulePendingRetry\(\)", NS, re.S) is not None)

# ==================================================================
sec("④ Windows：发送侧支持阻塞等结果")
check("★ _send_text_task 返回 {peer: ok/failed/timeout}",
      re.search(r"async def _send_text_task.*?results\[pid\] = \"ok\"", NODE, re.S)
      is not None)
check("★ node 提供 send_text_sync（工作线程阻塞）",
      re.search(r"def send_text_sync\(self.*?run_coroutine_threadsafe\(", NODE, re.S)
      is not None)
check("bridge 转发 send_text_sync",
      "def send_text_sync(self, targets, text" in BR)
check("★ bridge 提供 pendingFlushDone 信号（工作线程 → UI 线程）",
      "pendingFlushDone = Signal(dict)" in BR
      and "def emit_pending_flush_done" in BR)

# ==================================================================
sec("⑤ Windows：补发确认送达才移除 + 周期重试 + 不误删新增条目")
check("★ _flush_pending 放到工作线程执行",
      re.search(r"def _flush_pending\(self\).*?threading\.Thread\(target=work",
                MW, re.S) is not None)
check("★ 用 send_text_sync 等结果，全部失败则保留条目",
      re.search(r"res\.get\(t\) == \"ok\" for t in targets\):.*?remain\.append\(entry\)",
                MW, re.S) is not None)
check("★ _finish_pending_flush 只移除确认送达的条目",
      re.search(r"self\._pending_files = \[e for e in self\._pending_files\s*\n"
                r"\s*if id\(e\) not in ok_ids\]", MW) is not None)
check("★ 期间新增的条目自然被保留（不在 ok_ids 里）",
      re.search(r"if id\(e\) not in ok_ids\]", MW) is not None)
check("★ 防重入：_flush_running",
      re.search(r"def _flush_pending\(self\):.*?if self\._flush_running:\s*\n\s*return",
                MW, re.S) is not None)
check("★ 周期重试定时器 10s",
      re.search(r"t\.setInterval\(10000\)", MW) is not None)
check("★ 队列非空时启动重试、空时停止",
      "self._start_pending_retry()" in MW and "self._stop_pending_retry()" in MW)
# 取 _pending_retry_now 方法体（到下一个 def 为止），断言它不再调用 _drop_pending
_seg = MW.split("def _pending_retry_now(self, mid):")[1].split("\n    def ")[0]
check("★ 手动「立即重发」不再先删条目",
      "self._flush_pending()" in _seg and "_drop_pending" not in _seg,
      "方法体里不该再出现 _drop_pending")
check("★ _finish_pending_flush 用的是真实存在的 _render_chat（不是 refresh_msgs）",
      "self._render_chat()" in MW and "self.refresh_msgs()" not in MW)
check("pendingFlushDone 已接到 _finish_pending_flush",
      re.search(r"pendingFlushDone\.connect\(self\._finish_pending_flush\)", MW)
      is not None)

# ==================================================================
print()
print("=" * 68)
if F:
    print("失败项：")
    for f in F:
        print("  - %s" % f)
print("v1.18.15 专项验收：通过 %d 项，失败 %d 项" % (len(P), len(F)))
print("=" * 68)
sys.exit(1 if F else 0)