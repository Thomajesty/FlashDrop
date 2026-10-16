#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FlashDrop Android 静态验证 v1.13.1

本轮修复目标（用户实测报障）：
  A. 后台在线收到文件 → 有通知、可点进来，但聊天对话框空白（文件已落到手机文件夹）
  B. 消息实际已发出，UI 一直停留在"发送中"

根因：
  A. NodeService.handleBackgroundEvent 只弹系统通知，既没写内存 msgs、
     也没写 history/*.jsonl —— "记录入库"这条腿是断的。点通知回到界面后
     loadHistory() 读磁盘读不到东西 → 空白。
  B. ack / text_state 只查内存 byMid（切会话/重载会 clear），miss 就永远停在
     sending；且状态改动不落盘，重启后又退回 sending。

修复点：
  1. FlashApp.persistInboundEvent()：后台事件统一落库（写 jsonl + 计数）
  2. NodeService.handleBackgroundEvent()：调用落库（且不受"通知开关"影响）
  3. MainActivity.onResume：检测后台落库计数变化 → 重载历史
  4. MainActivity.persist()：peerId 为空不再丢弃，回落 __local__ 归档桶
  5. MainActivity.persistState()：状态变更覆盖式写回磁盘
  6. FdUtil.upsertHistory()：按 mid/tid 就地更新历史记录
  7. ack / text_state：内存索引 miss 时回扫 msgs + 落盘
  8. handleTransfer：peerId 为空回落 __local__；已上屏条目状态推进时落盘
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app", "src", "main", "java", "com", "flashdrop", "app")


def read(p):
    with open(os.path.join(APP, p), "r", encoding="utf-8", errors="replace") as f:
        return f.read()


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


PASS = []
FAIL = []


def ck(name, cond, detail=""):
    if cond:
        PASS.append(name)
    else:
        FAIL.append(name + ((" -> " + detail) if detail else ""))


# ============================================================
# 原始源码 / 去注释源码
# ============================================================
flash_app_raw = read("FlashApp.java")
flash_app = strip_comments(flash_app_raw)
node_svc_raw = read("NodeService.java")
node_svc = strip_comments(node_svc_raw)
main_raw = read("MainActivity.java")
main = strip_comments(main_raw)
fdutil_raw = read("FdUtil.java")
fdutil = strip_comments(fdutil_raw)

# ============================================================
# 第 1 节：FlashApp.persistInboundEvent —— 后台落库通道
# ============================================================
print("=== 1. FlashApp.persistInboundEvent ===")
ck("1.1 方法已定义", "public void persistInboundEvent(JSONObject e)" in flash_app,
   "缺少 persistInboundEvent 定义")
ck("1.2 识别 text 事件", '"text".equals(ev)' in flash_app)
ck("1.3 识别 transfer+recv 事件",
   '"transfer".equals(ev)' in flash_app and '"recv".equals(e.optString("kind"))' in flash_app)
ck("1.4 非目标事件直接返回", "if (!isText && !isRecv) return;" in flash_app)
ck("1.5 peer_id 为空时返回（无法归档）",
   'if (peerId == null || peerId.isEmpty()) return;' in flash_app)
ck("1.6 写盘调用 FdUtil.appendHistory", "FdUtil.appendHistory(this, peerId, rec)" in flash_app)
ck("1.7 落库计数自增", "bgPendingReloadCount++" in flash_app)
ck("1.8 计数器字段已声明", "public volatile int bgPendingReloadCount" in flash_app)
ck("1.9 去重键集合已声明", "bgSeenKeys" in flash_app)
ck("1.10 去重键含设备与 tid/mid",
   'peerId + "|"' in flash_app and '("m" + e.optString("mid"))' in flash_app
   and '("t" + e.optString("tid"))' in flash_app)
ck("1.11 重复键直接跳过", "if (bgSeenKeys.contains(key)) return;" in flash_app)
ck("1.12 去重集合有上限保护", "bgSeenKeys.size() > 2000" in flash_app)
ck("1.13 记录不含未完成的 offer 状态字段缺失",
   'rec.put("kind", isText ? "text" : "file")' in flash_app)
ck("1.14 记录方向为接收",
   'rec.put("dir", "in")' in flash_app)
ck("1.15 文本记录带 mid",
   'if (isText) {' in flash_app and 'rec.put("mid", e.optString("mid"))' in flash_app)
ck("1.16 文件记录带 tid/file/size",
   'rec.put("tid", e.optString("tid"))' in flash_app
   and 'rec.put("file", e.optString("file"))' in flash_app
   and 'rec.put("size", e.optLong("size"))' in flash_app)
ck("1.17 时间戳带兜底", 'ts > 0 ? ts : System.currentTimeMillis()' in flash_app)

# ============================================================
# 第 2 节：NodeService 调用落库（核心修复 A）
# ============================================================
print("=== 2. NodeService 后台落库调用 ===")
ck("2.1 调用了 persistInboundEvent",
   "FlashApp.get().persistInboundEvent(e)" in node_svc,
   "NodeService 未调用落库 —— 这是对话框空白的直接原因")
# 落库必须在"通知开关"判断之前
pos_persist = node_svc.find("persistInboundEvent(e)")
pos_prefs = node_svc.find("Prefs prefs = FlashApp.get().prefs();")
ck("2.2 落库早于通知开关判断",
   pos_persist >= 0 and pos_prefs >= 0 and pos_persist < pos_prefs,
   "落库被放到了 notifyOnReceive 判断之后，关掉通知就不落库了")
ck("2.3 peers 分支仍提前返回（不上屏设备事件）",
   'if ("peers".equals(ev)) {' in node_svc and "flushPendingSends()" in node_svc)
ck("2.4 通知逻辑保持原样（text）",
   'if ("text".equals(ev)) {' in node_svc and "notifyMessage(" in node_svc)
ck("2.5 通知逻辑保持原样（recv done）",
   '"done".equals(e.optString("state"))' in node_svc)

# ============================================================
# 第 3 节：MainActivity.onResume 重载历史（修复 A 的另一半）
# ============================================================
print("=== 3. onResume 后台落库后重载 ===")
ck("3.1 记录字段 lastBgReloadCount 已声明",
   "private int lastBgReloadCount" in main)
ck("3.2 读取后台落库计数",
   "int bgCount = FlashApp.get().bgPendingReloadCount;" in main)
ck("3.3 计数变化时重载历史",
   "if (bgCount != lastBgReloadCount)" in main and "loadHistory();" in main)
# onResume 内的重载必须在 loadHistory 定义之外的 onResume 作用域
m_resume = re.search(r"protected void onResume\(\)\s*\{(.*?)\n    \}", main, re.S)
ck("3.4 重载逻辑位于 onResume 内",
   bool(m_resume) and "bgPendingReloadCount" in (m_resume.group(1) if m_resume else ""))

# ============================================================
# 第 4 节：persist 不再丢弃空 peerId（修复 A 的数据层）
# ============================================================
print("=== 4. persist 空 peerId 兜底 ===")
m_persist = re.search(r"private void persist\(Msg m\)\s*\{(.*?)\n    \}", main, re.S)
persist_body = m_persist.group(1) if m_persist else ""
ck("4.1 persist 方法存在", bool(m_persist))
ck("4.2 已移除 'peerId 为空直接 return' 的旧逻辑",
   "if (m.peerId == null || m.peerId.isEmpty()) return;" not in persist_body,
   "旧逻辑仍在：空 peerId 的消息会被悄悄丢弃")
ck("4.3 回落到 __local__ 归档桶",
   "LOCAL_ARCHIVE_ID" in persist_body)
ck("4.4 常量 __local__ 已定义",
   'LOCAL_ARCHIVE_ID = "__local__"' in main)
ck("4.5 落盘写入 msgToJson", "FdUtil.appendHistory(this, pid, msgToJson(m))" in persist_body)

# ============================================================
# 第 5 节：persistState 状态落盘（修复 B）
# ============================================================
print("=== 5. persistState 状态持久化 ===")
m_pstate = re.search(r"private void persistState\(Msg m\)\s*\{(.*?)\n    \}", main, re.S)
pstate_body = m_pstate.group(1) if m_pstate else ""
ck("5.1 persistState 方法已定义", bool(m_pstate))
ck("5.2 使用 upsertHistory 覆盖式更新",
   "FdUtil.upsertHistory(" in pstate_body)
ck("5.3 未命中时退化为追加",
   "FdUtil.appendHistory(" in pstate_body)
ck("5.4 传入 mid 与 tid 双键",
   "m.mid, m.tid, msgToJson(m)" in pstate_body)
ck("5.5 空 peerId 也走 __local__",
   "LOCAL_ARCHIVE_ID" in pstate_body)

# ============================================================
# 第 6 节：FdUtil.upsertHistory 实现
# ============================================================
print("=== 6. FdUtil.upsertHistory ===")
m_up = re.search(r"public static boolean upsertHistory\((.*?)\n    \}", fdutil, re.S)
up_body = m_up.group(1) if m_up else ""
ck("6.1 upsertHistory 已定义", bool(m_up))
ck("6.2 签名含 keyMid / keyTid",
   "String keyMid" in (m_up.group(1) if m_up else "")
   and "String keyTid" in (m_up.group(1) if m_up else ""))
ck("6.3 空 peerId 直接返回 false",
   "if (peerId == null || peerId.isEmpty()) return false;" in up_body)
ck("6.4 文件不存在返回 false",
   "if (!f.exists()) return false;" in up_body)
ck("6.5 优先按 mid 匹配",
   "matched = keyMid.equals(o.optString(\"mid\", \"\"))" in up_body)
ck("6.6 mid 缺失时按 tid+dir+kind 匹配",
   'keyTid.equals(o.optString("tid", ""))' in up_body
   and 'rec.optString("dir", "").equals(o.optString("dir", ""))' in up_body
   and 'rec.optString("kind", "").equals(o.optString("kind", ""))' in up_body)
ck("6.7 命中后覆盖写回（只替换一次）",
   "if (matched && !hit)" in up_body and "hit = true;" in up_body)
ck("6.8 未命中返回 false（交由调用方 append）",
   "if (!hit) return false;" in up_body)
ck("6.9 重写整个文件（非追加）",
   "new FileOutputStream(f, false)" in up_body)

# ============================================================
# 第 7 节：ack / text_state 回扫 + 落盘（修复 B 的事件侧）
# ============================================================
print("=== 7. ack / text_state 兜底 ===")
# 注意：case 体内含 for 循环的 break，不能用 `.*?break;` 截断（会提前匹配到循环里的
# break）。改为匹配到"下一个 case 标签"或 switch 结束，保证取到完整分支体。
m_ack = re.search(r'case "ack": \{(.*?)\n            \}', main, re.S)
ack_body = m_ack.group(1) if m_ack else ""
ck("7.1 ack 分支存在", bool(m_ack))
ck("7.2 ack 优先查内存索引", "byMid.get(ackMid)" in ack_body)
ck("7.3 ack 内存 miss 时回扫 msgs",
   "for (Msg x : msgs)" in ack_body and "ackMid.equals(x.mid)" in ack_body,
   "没有回扫 —— 切会话后 ack 找不到消息，永远卡在发送中")
ck("7.4 ack 回扫命中后回填索引", "byMid.put(ackMid, m)" in ack_body)
ck("7.5 ack 命中后落盘状态", "persistState(m)" in ack_body)
ck("7.6 ack 回填 mid 字段", "m.mid = ackMid;" in ack_body)

m_ts = re.search(r'case "text_state": \{(.*?)\n            \}', main, re.S)
ts_body = m_ts.group(1) if m_ts else ""
ck("7.7 text_state 分支存在", bool(m_ts))
ck("7.8 text_state 内存 miss 时回扫 msgs",
   "for (Msg x : msgs)" in ts_body and "tsMid.equals(x.mid)" in ts_body)
ck("7.9 text_state 命中后落盘状态", "persistState(m)" in ts_body)
ck("7.10 text_state 回填索引", "byMid.put(tsMid, m)" in ts_body)

# ============================================================
# 第 8 节：handleTransfer 接收侧修正
# ============================================================
print("=== 8. handleTransfer 接收侧 ===")
m_ht = re.search(r"private void handleTransfer\(JSONObject e\)\s*\{(.*?)\n    \}", main, re.S)
ht_body = m_ht.group(1) if m_ht else ""
ck("8.1 handleTransfer 存在", bool(m_ht))
ck("8.2 新建接收消息时 peerId 空值回落 __local__",
   'String pid = e.optString("peer_id");' in ht_body
   and "(pid == null || pid.isEmpty()) ? LOCAL_ARCHIVE_ID : pid" in ht_body,
   "接收消息 peer_id 为空会被 belongsToView 规则 1 失配 + persist 丢弃")
ck("8.3 已上屏条目状态推进时落盘",
   "} else if (m.appended) {" in ht_body and "persistState(m)" in ht_body,
   "接收进度/结果没有持久化，重启后丢失")
ck("8.4 原有三层查重逻辑保留",
   "isSameInboundFile(m, tid, e)" in ht_body
   and "isSameInboundFile(x, tid, e)" in ht_body)
ck("8.5 方案色随事件更新保留",
   'String sc = e.optString("scheme");' in ht_body)

# ============================================================
# 第 9 节：回归 —— v1.13.0 五项修复不得被破坏
# ============================================================
print("=== 9. v1.13.0 回归检查 ===")
viewer = strip_comments(read("ImageViewerActivity.java"))
ck("9.1 问题1 仍无 baseScale 封顶",
   "if (baseScale > 1f) baseScale = 1f;" not in viewer)
ck("9.2 问题1 decodeForScreen 保留",
   "decodeForScreen" in viewer)
ck("9.3 问题2 底栏 LayoutParams 仍被应用",
   "return wrap(outer, lp);" in viewer)
ck("9.4 问题3 渲染层去重保留",
   "seenInTid" in main)
ck("9.5 问题4 高对比推导色保留",
   "FdTheme.onColorText(bubbleBg)" in main and "FdTheme.onColorDim(bubbleBg)" in main)
ck("9.6 问题5 顶栏待发送入口仍隐藏",
   "btnPending.setVisibility(View.GONE);" in main)
ck("9.7 belongsToView 三规则完整",
   "peerId.equals(m.peerId)" in main
   and "m.targets.contains(peerId)" in main
   and "boolean noTarget" in main)

# ============================================================
# 汇总
# ============================================================
print()
print("=" * 58)
print("PASS: %d   FAIL: %d   TOTAL: %d" % (len(PASS), len(FAIL), len(PASS) + len(FAIL)))
if FAIL:
    print("-" * 58)
    for f in FAIL:
        print("  FAIL  " + f)
print("=" * 58)
sys.exit(1 if FAIL else 0)
