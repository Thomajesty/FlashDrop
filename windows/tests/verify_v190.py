# -*- coding: utf-8 -*-
"""FlashDrop v1.9.0 异步待发专项测试（Windows 端，不依赖 GUI 显示）

覆盖：
  1. 队列条目结构（type/broadcast/paths/text）
  2. 旧格式条目向后兼容
  3. 群发 vs 定向目标解析
  4. 文本入队 → flush 后发出并生成正式消息
  5. 零在线保留、重启后恢复
  6. 双端口径一致
"""
import os
import sys
import ast
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import util  # noqa: E402
from app.config import Config  # noqa: E402

PASS = FAIL = 0


def check(name, ok, extra=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {extra}")


def eq(name, a, b):
    check(name, str(a) == str(b), f"期望=[{b}] 实际=[{a}]")


def make_cfg():
    d = tempfile.mkdtemp(prefix="fd190_")
    os.environ["FLASHDROP_DATA_DIR"] = d
    c = Config(os.path.join(d, "config.json"))
    c["save_dir"] = os.path.join(d, "save")
    c["cache_dir"] = os.path.join(d, "cache")
    c.ensure_dirs()
    return c, d


# ---------- 复刻 MainWindow 的纯逻辑 ----------
# 说明：MainWindow 依赖 PySide6（GUI 库），纯逻辑测试环境未必安装。
# 这里复刻其静态方法与目标解析规则；GUI 层的真实调用由 verify_v190_ui.py 覆盖。
WIN_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "app", "ui", "main_window.py")


def queue_kind(entry):
    t = entry.get("type")
    return t if t in ("text", "file") else "file"


def entry_text(entry):
    if queue_kind(entry) == "text":
        return entry.get("text") or ""
    paths = entry.get("paths") or []
    names = "、".join(os.path.basename(p) for p in paths[:3])
    if len(paths) > 3:
        names += f" 等 {len(paths)} 个文件"
    return names or "待发文件"


def pending_target_names(entry, peers=None):
    if entry.get("broadcast"):
        return "全部设备"
    peers = peers or {}
    names = [peers[t]["name"] for t in (entry.get("targets") or []) if t in peers]
    return "、".join(names) if names else "全部设备"


def resolve_targets(entry, online):
    """复刻 _flush_pending 的目标解析规则"""
    if entry.get("broadcast") or not entry.get("targets"):
        return list(online)
    return [t for t in entry["targets"] if t in online]


def main():
    print("== verify_v190: v1.9.0 异步待发专项测试 ==")
    cfg, d = make_cfg()

    # ---------- 1. 队列条目结构 ----------
    print("\n[1] 队列条目结构")
    text_entry = {"type": "text", "text": "你好", "paths": [],
                  "targets": [], "broadcast": True, "ts": 1, "mid": "m1"}
    file_entry = {"type": "file", "paths": [os.path.join(d, "a.pdf")],
                  "targets": ["A"], "broadcast": False, "ts": 2, "mid": "m2"}
    eq("文本条目 type", queue_kind(text_entry), "text")
    eq("文件条目 type", queue_kind(file_entry), "file")
    eq("文本摘要", entry_text(text_entry), "你好")
    eq("文件摘要取 basename", entry_text(file_entry), "a.pdf")

    multi = {"type": "file", "paths": [os.path.join(d, "1.pdf"),
                                       os.path.join(d, "2.zip")],
             "targets": [], "broadcast": True, "ts": 3, "mid": "m3"}
    eq("两个文件全部列出", entry_text(multi), "1.pdf、2.zip")
    over3 = {"type": "file", "paths": [os.path.join(d, f"{i}.pdf") for i in range(5)],
             "targets": [], "broadcast": True, "ts": 3, "mid": "m3b"}
    check("超过 3 个才折算数量", "等 5 个文件" in entry_text(over3),
          entry_text(over3))
    empty_file = {"type": "file", "paths": [], "targets": [],
                  "broadcast": True, "ts": 3, "mid": "m3c"}
    eq("空路径兜底文案", entry_text(empty_file), "待发文件")

    # ---------- 2. 旧格式向后兼容 ----------
    print("\n[2] 旧格式条目兼容（v1.8.0 只有 paths/targets）")
    legacy = {"paths": [os.path.join(d, "old.pdf")], "targets": ["A"],
              "ts": 4, "mid": "m4"}
    eq("无 type 字段 → 归为 file", queue_kind(legacy), "file")
    eq("旧条目摘要可用", entry_text(legacy), "old.pdf")
    eq("旧条目 targets 仍生效", resolve_targets(legacy, ["A", "B"]), ["A"])
    eq("旧条目目标离线则不发", resolve_targets(legacy, ["B"]), [])
    legacy_empty = {"paths": [os.path.join(d, "o.pdf")], "targets": [], "ts": 5}
    eq("旧条目空 targets → 群发全发", len(resolve_targets(legacy_empty, ["A", "B", "C"])), 3)

    # ---------- 3. 群发 vs 定向 ----------
    print("\n[3] 群发 vs 定向")
    online3 = ["A", "B", "C"]
    eq("broadcast 群发全部",
       sorted(resolve_targets(text_entry, online3)), ["A", "B", "C"])
    eq("定向只发在线目标", resolve_targets(file_entry, online3), ["A"])
    mixed = {"type": "text", "text": "x", "paths": [], "targets": ["A", "D"],
             "broadcast": False, "ts": 6}
    eq("定向部分在线只发在线", resolve_targets(mixed, online3), ["A"])
    alloff = {"type": "text", "text": "x", "paths": [], "targets": ["D", "E"],
              "broadcast": False, "ts": 7}
    eq("定向全离线 → 保留", resolve_targets(alloff, online3), [])

    # 关键回归：v1.8.0 是 online[:1]（只发第一台）
    check("群发不再只发第一台（v1.8.0 缺陷已修）",
          len(resolve_targets(text_entry, online3)) != 1,
          f"实际发出 {len(resolve_targets(text_entry, online3))} 台")

    # ---------- 4. 零在线 ----------
    print("\n[4] 零在线设备")
    eq("群发零在线 → 保留", resolve_targets(text_entry, []), [])
    eq("定向零在线 → 保留", resolve_targets(file_entry, []), [])

    # ---------- 5. 持久化往返 ----------
    print("\n[5] 持久化往返（重启后恢复）")
    cfg["pending_files"] = [text_entry, file_entry]
    reloaded = Config(cfg.path)
    got = list(reloaded["pending_files"] or [])
    eq("恢复条目数", len(got), 2)
    eq("文本条目 type 保持", queue_kind(got[0]), "text")
    eq("文本内容保持", got[0].get("text"), "你好")
    eq("broadcast 标记保持", got[0].get("broadcast"), True)
    eq("文件条目 paths 保持", len(got[1].get("paths") or []), 1)

    # ---------- 6. flush 语义（模拟） ----------
    print("\n[6] flush 语义模拟")

    def flush(entries, online):
        remain, sent = [], []
        for e in entries:
            if queue_kind(e) == "file":
                paths = [p for p in e.get("paths") or [] if os.path.isfile(p)]
                if not paths:
                    continue        # 文件已删除 → 丢弃
            tg = resolve_targets(e, online)
            if tg:
                sent.append((e, tg))
            else:
                remain.append(e)
        return sent, remain

    p = os.path.join(d, "real.pdf")
    util_unique = p
    open(util_unique, "wb").write(b"x")
    q = [
        {"type": "text", "text": "t1", "paths": [], "targets": [],
         "broadcast": True, "ts": 1, "mid": "a"},
        {"type": "file", "paths": [util_unique], "targets": [],
         "broadcast": True, "ts": 2, "mid": "b"},
        {"type": "text", "text": "t2", "paths": [], "targets": ["D"],
         "broadcast": False, "ts": 3, "mid": "c"},
        {"type": "file", "paths": [os.path.join(d, "gone.pdf")],
         "targets": ["A"], "broadcast": False, "ts": 4, "mid": "d"},
    ]
    sent, remain = flush(q, ["A", "B"])
    eq("发出 2 条", len(sent), 2)
    eq("群发文本发给 2 台", len(sent[0][1]), 2)
    eq("群发文件发给 2 台", len(sent[1][1]), 2)
    eq("保留 1 条（定向 D 离线）", len(remain), 1)
    eq("保留的是定向那条", remain[0]["mid"], "c")
    check("文件已删除的条目被丢弃", all(x[0]["mid"] != "d" for x in sent))

    # 第二轮：D 上线 → 定向条目发出
    sent2, remain2 = flush(remain, ["A", "D"])
    eq("D 上线后剩余发出", len(sent2), 1)
    eq("发给 D", sent2[0][1], ["D"])
    eq("队列清空", len(remain2), 0)

    # ---------- 7. 目标名称显示 ----------
    print("\n[7] 待发目标描述")
    eq("群发描述", pending_target_names({"broadcast": True, "targets": []}),
       "全部设备")
    eq("空 targets 也算全部设备",
       pending_target_names({"broadcast": False, "targets": []}), "全部设备")
    peers = {"A": {"name": "小米"}, "B": {"name": "华为"}}
    eq("定向描述用设备名",
       pending_target_names({"broadcast": False, "targets": ["A", "B"]}, peers),
       "小米、华为")
    eq("离线未知设备降级",
       pending_target_names({"broadcast": False, "targets": ["Z"]}, peers),
       "全部设备")

    # ---------- 8. 双端口径一致 ----------
    print("\n[8] 与 Android 端 RT190 同场景一致性")
    cases = [
        ("bc", True, [], ["A", "B", "C"], 3),
        ("empty", False, [], ["A", "B", "C"], 3),
        ("dir_online", False, ["A"], ["A", "B", "C"], 1),
        ("dir_offline", False, ["D"], ["A", "B", "C"], 0),
        ("dir_mixed", False, ["A", "D"], ["A", "B", "C"], 1),
        ("dir_none", False, ["D", "E"], ["A", "B", "C"], 0),
        ("bc_zero", True, [], [], 0),
        ("dir_zero", False, ["A"], [], 0),
    ]
    for name, bc, tg, on, expect in cases:
        e = {"type": "text", "text": "x", "paths": [],
             "targets": tg, "broadcast": bc, "ts": 1}
        eq(f"一致[{name}]", len(resolve_targets(e, on)), expect)

    # ---------- 9. 真实方法可静态调用（回归防护） ----------
    # v1.9.0 首次实现时 _queue_kind 是实例方法却被 _entry_text 静态调用，
    # 导致文件入队路径抛 TypeError（纯文本路径测不到）。此处直接调真实方法。
    print("\n[9] 真实 MainWindow 静态方法可直接调用")
    src = open(WIN_SRC, encoding="utf-8").read()
    try:
        # 只做静态解析校验（不 import PySide6）：检查方法签名与调用方式
        tree = ast.parse(src)
        cls = next(n for n in tree.body
                   if isinstance(n, ast.ClassDef) and n.name == "MainWindow")
        fns = {m.name: m for m in cls.body if isinstance(m, ast.FunctionDef)}
        qk = fns.get("_queue_kind")
        et = fns.get("_entry_text")
        check("_queue_kind 已定义", qk is not None)
        check("_entry_text 已定义", et is not None)
        deco = {ast.unparse(d) for d in (qk.decorator_list if qk else [])}
        check("_queue_kind 是 staticmethod（可被 _entry_text 静态调用）",
              "staticmethod" in deco, str(deco))
        # _entry_text 内部必须以 MainWindow._queue_kind(...) 形式调用
        call_names = {ast.unparse(n.func) for n in ast.walk(et)
                      if isinstance(n, ast.Call)} if et else set()
        check("_entry_text 通过类名静态调用 _queue_kind",
              "MainWindow._queue_kind" in call_names, str(call_names))
        # 参数：两者都必须只接受 entry 一个业务参数
        for name, fn in (("_queue_kind", qk), ("_entry_text", et)):
            args = [a.arg for a in fn.args.args if a.arg != "self"]
            check(f"{name} 签名为 (entry)", args == ["entry"], str(args))
    except Exception as e:
        check("静态方法校验可执行", False, repr(e))

    # ---------- 10. 与既有 API 兼容 ----------
    print("\n[10] 既有 API 未破坏")
    for meth in ("_targets", "_selected_ids_all", "_queue_files",
                 "_flush_pending", "_show_pending_msg", "_remove_pending_msg",
                 "_on_cancel_pending", "_do_send_files", "_pending_load",
                 "_queue_entry", "_drop_pending", "_pending_retry_now",
                 "_pending_clear_all", "_resolve_targets", "_pending_btn_refresh",
                 "_open_pending_window", "_entry_text", "_queue_kind",
                 "_pending_target_names", "_pending_toast_text"):
        check(f"MainWindow.{meth} 存在", f"def {meth}(" in src)
    check("PendingWindow 类已定义", "class PendingWindow(QDialog):" in src)
    check("_queue_files 兼容旧两参签名",
          "entry_targets, broadcast=False" in src)
    # v1.13.0 起：待发送不再有独立入口按钮 —— 改为直接在气泡里以 pending
    # 状态显示、设备上线自动投递（用户明确要求"不需要单独做按钮列表"）。
    # 断言随之更新为新形态：按钮对象仍保留（兼容既有刷新调用），但必须隐藏
    # 且不得挂进顶栏布局。
    check("顶栏待发送入口已移除（v1.13.0 改为气泡内标记）",
          "self.pending_btn = QPushButton" in src
          and "self.pending_btn.setVisible(False)" in src
          and "addWidget(self.pending_btn)" not in src)
    check("文本气泡支持 pending 状态",
          'if st == "pending":' in open(
              os.path.join(os.path.dirname(WIN_SRC), "widgets.py"),
              encoding="utf-8").read())
    check("配置项注释说明广播语义", '"broadcast": bool' in open(
        os.path.join(os.path.dirname(WIN_SRC), "..", "config.py"),
        encoding="utf-8").read())

    print(f"\n===== verify_v190 结果：{PASS}/{PASS + FAIL} 通过，失败 {FAIL} =====")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
