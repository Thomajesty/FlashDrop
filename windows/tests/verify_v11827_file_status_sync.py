# -*- coding: utf-8 -*-
"""v1.18.27 文件状态同步 / 失效文件卡片「验收」（静态断言 + 逻辑仿真）

用户反馈两个问题：
  1. 手机端文件状态未同步 —— 已经删除的文件还是显示「已保存」；
  2. 设置里的「数据清理」没有把已删文件的空文件卡片（记录）删掉。

本脚本做两件事：
  A. 静态断言：两端源码里"已完成文件"的状态判定必须检查磁盘实际存在性；
     数据清理必须覆盖"失效文件卡片"，且清理后能触发界面重载。
  B. 逻辑仿真：把安卓 FdUtil.purgeOrphanFileMsgs 的判定口径（kind=file /
     dir=in / state in (done, ok) / 本地文件不存在）用 Python 复刻一遍，
     造"文件在/文件没了/发出去的/content Uri/无路径"五类记录，
     断言只有该删的被删、其它一律保留（防止误删）。

运行：python windows/tests/verify_v11827_file_status_sync.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
AND = os.path.join(ROOT, "android", "app", "src", "main", "java",
                   "com", "flashdrop", "app")
WIN = os.path.join(ROOT, "windows", "app")

FAILS = []
N = 0


def ck(name, cond, extra=""):
    global N
    N += 1
    if not cond:
        FAILS.append(f"{name} | {extra}")
    print(("  ok  " if cond else " FAIL ") + name +
          ((" | " + str(extra)) if extra else ""))


def rd(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


# ---------------- B. 判定口径仿真 ----------------

def normalize(desc):
    """复刻 FdUtil.splitSavedDesc：归一化为 "flashdrop/设备名/文件名" 小写"""
    if not desc:
        return None
    s = desc.strip().replace("\\", "/")
    i = s.find("/Download/")
    if i >= 0:
        s = s[i + 1:]
    if s.startswith("Download/"):
        s = s[len("Download/"):]
    if s.startswith("/"):
        s = s[1:]
    p = s.rfind("/")
    if p < 0:
        return None
    return (s[:p + 1] + s[p + 1:]).lower()


def is_orphan(rec, index):
    """复刻 FdUtil.isOrphanFileMsg（v1.18.28：以索引为准，查不到即保守）

    index: set 或 None。None = 查询失败（游标 null）→ 一律当作"还在"
    """
    if rec.get("kind") != "file":
        return False
    if rec.get("dir") != "in":
        return False
    if rec.get("state") not in ("done", "ok"):
        return False
    p = rec.get("path") or ""
    if not p or p.startswith("content:"):
        return False                     # 保守保留
    if index is None:
        return False                     # 查不到 → 保守，绝不误标已删除
    key = normalize(p)
    if key is None:
        return False                     # 解析不出 → 保守
    return key not in index


def main():
    print("=" * 70)
    print("v1.18.27 文件状态同步 / 失效文件卡片 · 验收")
    print("=" * 70)

    ma = rd(os.path.join(AND, "MainActivity.java"))
    util = rd(os.path.join(AND, "FdUtil.java"))
    st = rd(os.path.join(AND, "SettingsActivity.java"))
    node = rd(os.path.join(AND, "FlashNode.java"))
    wdg = rd(os.path.join(WIN, "ui", "widgets.py"))
    hist = rd(os.path.join(WIN, "ui", "history.py"))
    mw = rd(os.path.join(WIN, "ui", "main_window.py"))

    print("\n[A1 安卓：气泡状态必须看磁盘]")
    ck("已完成文件不再无条件显示“已保存”（先判文件是否还在）",
       "fileGoneOf(m)" in ma and 's = "文件已删除"' in ma)
    ck("判定只看收到的文件（dir=in），发出去的“已送达”不受影响",
       'if (m == null || !"in".equals(m.dir)) return false;' in ma)
    # ★ v1.18.28：判定必须以 MediaStore 索引为准，不能再拿 File.exists() 拼路径
    ck("★ 判定走 FdUtil.savedFileExists（不再自己拼 File 路径）",
       "return !FdUtil.savedFileExists(this, m.path);" in ma
       and "new java.io.File(FdUtil.legacySaveDir(), p)" not in ma)
    ck("★ 以 MediaStore 索引为准（查询 RELATIVE_PATH LIKE Download/FlashDrop%）",
       "RELATIVE_PATH\n" in util.replace(" ", "") or
       "MediaColumns.RELATIVE_PATH" in util,
       "FdUtil 必须查 MediaStore")
    ck("★ 索引查不到（游标 null）→ 保守当作“还在”，不误标已删除",
       "if (cur == null) {" in util and "// 查不到" in util)
    ck("★ 无路径 / content Uri / 解析不出 → 保守当作“还在”",
       'if (desc == null || desc.isEmpty()) return true;' in util
       and 'if (desc.startsWith("content:")) return true;' in util
       and "if (dn == null) return true;" in util)
    ck("★ 路径归一化兼容三种写法（相对描述/绝对路径/缺 Download 前缀）",
       'int i = s.indexOf("/Download/");' in util
       and 'if (s.startsWith("Download/"))' in util)
    ck("★ 索引有失效时机（回到前台 / 刚收完文件 / 清理后）",
       "FdUtil.invalidateSavedIndex();" in ma
       and "FdUtil.invalidateSavedIndex();" in node
       and "FdUtil.invalidateSavedIndex();" in st)
    ck("★ 索引在后台线程建立（buildSavedIndex），UI 线程不查库",
       "public static void buildSavedIndex(Context ctx)" in util
       and "private void refreshSavedIndexAsync()" in ma
       and "FdUtil.buildSavedIndex(MainActivity.this)" in ma)
    ck("★ savedFileExists 只读缓存（没建好时一律保守返回“还在”）",
       "java.util.Set<String> idx = savedIndex;" in util
       and "if (idx == null) return true;" in util)
    ck("★ 查询失败有退避（5 秒内不重试，避免每帧查库）",
       "savedIndexFailedAt" in util and "5000L" in util)
    ck("★ 启动与回前台都会重建索引",
       re.search(r"loadHistory\(\);[\s\S]{0,300}?refreshSavedIndexAsync\(\)", ma)
       is not None)
    ck("回到前台无条件重绘（外部删文件后状态能同步）",
       re.search(r"onResume[\s\S]{0,2500}?adapter\.notifyDataSetChanged\(\)",
                 ma) is not None)

    print("\n[A2 安卓：数据清理必须清失效卡片]")
    ck("新增失效卡片统计 countOrphanFileMsgs",
       "public static int countOrphanFileMsgs(Context ctx)" in util)
    ck("新增失效卡片清理 purgeOrphanFileMsgs",
       "public static int purgeOrphanFileMsgs(Context ctx)" in util)
    ck("清理先写 .tmp 再 rename（写一半崩掉不丢记录）",
       'f.getName() + ".tmp"' in util and "tmp.renameTo(f)" in util)
    ck("设置页新增第 4 类「失效文件卡片」",
       "CAT_ORPHAN = 3" in st and "失效文件卡片（文件已被删除）" in st)
    ck("删文件/图片后自动连带清失效卡片（不留空卡片）",
       "if (delOrphan || delFile || delImg)" in st
       and "FdUtil.purgeOrphanFileMsgs(this)" in st)
    ck("清掉记录后能触发主界面重载（historyCleared）",
       "if (orphan > 0) FlashApp.get().historyCleared = true;" in st)

    print("\n[A3 Windows：同类问题同步修复]")
    ck("Windows 已完成文件不再无条件“已保存”（检查 isfile）",
       "文件已删除" in wdg and "os.path.isfile(p)" in wdg)
    ck("Windows 历史新增 purge_orphan_files",
       "def purge_orphan_files(self)" in hist)
    ck("Windows 设置页新增「清理失效文件卡片」入口",
       "清理失效文件卡片" in mw and "_clear_orphan_cards" in mw)
    ck("Windows 清理后可重新加载界面",
       "_load_all_history()" in mw)

    # ---------------- B. 判定口径仿真 ----------------
    print("\n[B 判定口径仿真：只删该删的]")
    # 索引：MediaStore 里实际存在的两个文件（键已归一化）
    IDX = {
        "flashdrop/电脑/a.txt",
        "flashdrop/电脑/b.jpg",
    }
    cases = [
        ("收到的文件在索引里 → 保留",
         {"kind": "file", "dir": "in", "state": "done",
          "path": "Download/FlashDrop/电脑/a.txt"}, IDX, False),
        ("收到的文件不在索引里 → 判定失效",
         {"kind": "file", "dir": "in", "state": "done",
          "path": "Download/FlashDrop/电脑/gone.txt"}, IDX, True),
        ("★ 绝对路径写法（API<29）在索引里 → 保留",
         {"kind": "file", "dir": "in", "state": "done",
          "path": "/sdcard/Download/FlashDrop/电脑/b.jpg"}, IDX, False),
        ("★ 缺 Download 前缀的写法在索引里 → 保留",
         {"kind": "file", "dir": "in", "state": "done",
          "path": "FlashDrop/电脑/a.txt"}, IDX, False),
        ("★ 索引查询失败（游标 null）→ 一律保留（防误判）",
         {"kind": "file", "dir": "in", "state": "done",
          "path": "Download/FlashDrop/电脑/a.txt"}, None, False),
        ("收到的文件 state=ok 且已删 → 判定失效",
         {"kind": "file", "dir": "in", "state": "ok",
          "path": "Download/FlashDrop/电脑/gone.jpg"}, IDX, True),
        ("发出去的文件（dir=out）→ 保留（已送达是对方状态）",
         {"kind": "file", "dir": "out", "state": "done",
          "path": "Download/FlashDrop/电脑/c.txt"}, IDX, False),
        ("文本消息 → 保留",
         {"kind": "text", "dir": "in", "state": "done", "path": ""}, IDX, False),
        ("还在传输中（progress）→ 保留",
         {"kind": "file", "dir": "in", "state": "progress",
          "path": "Download/FlashDrop/电脑/d.txt"}, IDX, False),
        ("失败状态 → 保留",
         {"kind": "file", "dir": "in", "state": "failed",
          "path": "Download/FlashDrop/电脑/e.txt"}, IDX, False),
        ("content Uri（无法判定）→ 保留",
         {"kind": "file", "dir": "in", "state": "done",
          "path": "content://media/123"}, IDX, False),
        ("没有路径信息 → 保留",
         {"kind": "file", "dir": "in", "state": "done", "path": ""}, IDX, False),
    ]
    for name, rec, index, want in cases:
        got = is_orphan(rec, index)
        ck(name, got == want, f"判定={got} 期望={want}")

    # 批量：一轮清理后剩余条数
    recs = [
        ({"kind": "file", "dir": "in", "state": "done",
          "path": "Download/FlashDrop/电脑/a.txt"}),      # 在
        ({"kind": "file", "dir": "in", "state": "done",
          "path": "Download/FlashDrop/电脑/gone.txt"}),   # 删
        ({"kind": "file", "dir": "in", "state": "done",
          "path": "Download/FlashDrop/电脑/gone2.txt"}),  # 删
        ({"kind": "file", "dir": "out", "state": "done",
          "path": "Download/FlashDrop/电脑/x.txt"}),      # 发出的，保留
        ({"kind": "text", "dir": "in", "state": "done", "path": ""}),  # 保留
    ]
    keep = [r for r in recs if not is_orphan(r, IDX)]
    ck("批量清理：5 条里只删 2 条失效卡片，其余 3 条保留",
       len(keep) == 3, f"剩余={len(keep)}")

    print("\n" + "=" * 70)
    print(f"结果：{N - len(FAILS)}/{N} 通过")
    if FAILS:
        print("失败项：")
        for f in FAILS:
            print("  - " + f)
        return 1
    print("全部通过 —— 已删除文件不再显示“已保存”，数据清理能清掉空文件卡片")
    return 0


if __name__ == "__main__":
    sys.exit(main())
