# v1.18.43 代码评审结论（ocr delegate 模式）

**评审对象**：v1.18.41 + v1.18.42 两笔提交（共 17 文件 / 1050 行新增）
**工具**：`ocr delegate preview --commit <hash>` 挑文件 + `ocr delegate rule` 出规则（84 行 Python 规则），由 agent 逐项核对
**模式**：A 委派模式（未配 LLM endpoint，零配置零成本）

## 一、确认并已修复的缺陷（4 项）

### 1【阻断级 / 功能回归】tid 索引与 msgs 裁剪失配 → 重复卡片复活
- **位置**：`windows/app/ui/main_window.py` `_trim_msg_containers()`（v1.18.42 引入）
- **规则命中**：Boundary / Shared State
- **问题**：v1.18.42 给 `in_by_tid` 设了独立上限 256，而 msgs 上限是 1000。
  实测：收 600 个文件后 msgs=600、索引=256，第 300 条的 tid 已从索引消失但
  消息仍在 msgs；此时对端重发该传输的 progress 事件 → 索引未命中 →
  `_on_transfer` 新建第二张卡（用户最痛恨的重复卡片在西1.18.42 里被我重新引入）。
- **复现**：`/tmp/probe_index_mismatch.py` → "t300 卡片数: 2"
- **修复**：删除独立 256 上限；改为 msgs 裁剪后用 `live_ids` 集合清理
  "指向已不在任何 msgs 列表中的消息"的索引项。索引容量天然受 msgs 上限约束，
  既无界增长也不会误删存活消息。群发消息（挂多个 target）只有在**所有**
  msgs 中都不存在时才清索引。
- **新增断言**：`verify_v11842_memory_leaks.py` B4「旧 tid 的 progress 不建重复卡」

### 2【高 / 资源泄漏】`_persist_memo` 卡死条目无界增长
- **位置**：`main_window.py` `_persist_msg_state()`（v1.18.41 引入节流）
- **规则命中**：Module-level mutable globals / Resource Management
- **问题**：memo 只在终态 pop。传输中断、对端消失导致状态永远停在 progress 时，
  key 永久驻留。
- **修复**：memo >512 时先按 10 分钟老化清理，仍超限则按时间戳砍最旧的。

### 3【中 / 异步泄漏】`ack_waiters` 在 CancelledError 路径不清理
- **位置**：`node.py` `_send_text_task()`（v1.18.42 只修了 TimeoutError 分支）
- **规则命中**：Concurrency and Async
- **问题**：任务被外部取消时抛 `CancelledError`，不进 TimeoutError 分支，
  Future 永久驻留 dict。
- **修复**：把 pop 移到 `finally`，覆盖 timeout/ok/cancel/任意异常全路径。
- **竞态确认**：ACK 到达时 941 行已有 `not fut.done()` 保护，finally 二次 pop 无害。

### 4【低 / 死代码】`_trim_bubbles` 未使用的 `QLayoutItem` 导入
- **规则命中**：Dead Code — 删除。

## 二、审计通过的点（确认无问题）

- **`_dispose_item_widgets` / `dispose_widget` 的 shiboken6 即时析构**：
  调用点均不在被删控件的信号栈内；Viewer 用 QTimer(0) 延迟一拍防 UAF，正确。
- **`_send_files_task` 的 finally 清理**：tid 由 gen_uid 生成不会与同步路径重复，
  无竞态；同步版 gather 有 `return_exceptions=True`，正常路径一致。
- **widgets.py 模块级缓存**（`_THUMB_CACHE` 160 / `_AVATAR_CACHE` 256 /
  `_QSS_CACHE` 64）：均有上限，属规则允许的"documented cache"。
- **闭包捕获**：lambda 捕获的都是局部常量或已用默认参数绑定的循环变量。
- **可变默认参数 / `is` 比较字面量**：无命中。
- **测试文件 `except Exception: pass`**：gc 遍历时跳过无效对象的防御，合理。
- **v11833 A2/A3 失败**：经 `git stash` 对照确认是 HEAD 既有遗留失败，与本次改动无关。

## 三、评审边界说明

ocr 官方 benchmark 明确"precision over recall"，安全漏洞会有漏报；
本结论仅覆盖上述工具挑出的 diff 范围与规则项，不作合规/安全审计结论。
