# -*- coding: utf-8 -*-
"""v1.18.9 全量回归汇总（Windows 端）

按顺序跑所有**仍然有效**的验证脚本，输出一张通过/失败总表。
历史脚本（目标 API 已被重写）由各自脚本自行声明并跳过，不计入门槛。
"""
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WIN = os.path.dirname(HERE)
PY = sys.executable

# (脚本, 说明, 是否计入验收门槛)
SUITES = [
    ("verify_v1189_lock.py",       "单实例锁 / PING-PONG 探活", True),
    ("verify_v1189_win.py",        "6 条需求落地静态审计", True),
    ("verify_v1189_group.py",      "全部设备纯群聊视图（行为）", True),
    ("verify_v1189_arrow.py",      "截图下箭头无重复（像素）", True),
    ("verify_v1189_exe_lock.py",   "EXE 孤儿锁端到端", True),
    ("repro_exe_open.py",          "EXE 冷/热启动复现", True),
    ("smoke_exe.py",               "EXE 冒烟（真实启动产物）", True),
    ("verify_v1188_btn.py",        "底部按钮一致性（回归）", True),
    ("verify_v1180_snip.py",       "截图功能（回归）", True),
    ("test_ui_smoke.py",           "UI 冒烟 + 单实例三路径", True),
    ("test_core.py",               "协议/传输核心", True),
    ("verify_round7.py",           "第七轮专项", True),
    ("verify_v1110_conn.py",       "连接/发现", True),
    ("verify_legacy_interop.py",   "旧版互操作", True),
    ("verify_fixes.py",            "历史修复汇总", True),
    ("verify_v1150_win.py",        "图片编辑（若已标记历史则跳过）", False),
    ("verify_v1160_win.py",        "图片编辑二（若已标记历史则跳过）", False),
    ("verify_v1170_win.py",        "图片编辑三（若已标记历史则跳过）", False),
    ("verify_v1140_iv.py",         "历史脚本（已声明跳过）", False),
]

print("=" * 72)
print("v1.18.9 全量回归汇总")
print("=" * 72)


def _cleanup():
    """每个套件前后清掉可能残留的 FlashDrop 进程。

    ★ 必要性：test_ui_smoke.py / smoke_exe.py 等会真启动应用。
    若有实例没退干净，锁端口 58898 就被占着，后面跑单实例相关
    断言的套件（test_ui_smoke、verify_fixes）会**串行污染** ——
    单独跑全绿、汇总跑却红，纯属测试互相干扰，不是产品缺陷。
    """
    try:
        subprocess.run(["taskkill", "/F", "/IM", "FlashDrop.exe"],
                       capture_output=True, timeout=20)
    except Exception:
        pass
    time.sleep(2)


rows = []
gate_fail = 0
for name, desc, gate in SUITES:
    p = os.path.join(HERE, name)
    if not os.path.isfile(p):
        rows.append((name, desc, "缺失", gate))
        continue
    _cleanup()
    try:
        r = subprocess.run([PY, p], capture_output=True, text=True,
                           timeout=600, encoding="utf-8", errors="replace",
                           cwd=WIN)
        out = (r.stdout or "") + (r.stderr or "")
        rc = r.returncode
    except subprocess.TimeoutExpired:
        out, rc = "TIMEOUT", -9

    m = re.search(r"通过\s*(\d+)\s*项[，,]\s*失败\s*(\d+)\s*项", out)
    if m:
        p_, f_ = int(m.group(1)), int(m.group(2))
        status = "OK" if f_ == 0 else f"FAIL({f_})"
        if f_ and gate:
            gate_fail += 1
        rows.append((name, desc, f"{status}  {p_}/{p_ + f_}", gate))
        continue
    m2 = re.search(r"(\d+)\s*通过[，,]\s*(\d+)\s*失败", out)
    if m2:
        p_, f_ = int(m2.group(1)), int(m2.group(2))
        status = "OK" if f_ == 0 else f"FAIL({f_})"
        if f_ and gate:
            gate_fail += 1
        rows.append((name, desc, f"{status}  {p_}/{p_ + f_}", gate))
        continue

    if "已跳过" in out:
        rows.append((name, desc, "SKIP(历史)", gate))
    elif rc == 0:
        rows.append((name, desc, "OK", gate))
    else:
        if gate:
            gate_fail += 1
        rows.append((name, desc, f"FAIL(rc={rc})", gate))

_cleanup()
print()
w = max(len(r[0]) for r in rows) + 2
wd = max(len(r[1]) for r in rows) + 2
print(f"{'脚本'.ljust(w)}{'说明'.ljust(wd)}{'结果'.ljust(18)}门槛")
print("-" * 72)
for name, desc, res, gate in rows:
    print(f"{name.ljust(w)}{desc.ljust(wd)}{res.ljust(18)}"
          f"{'是' if gate else '否'}")
print("-" * 72)
ok = sum(1 for r in rows if r[2].startswith("OK"))
sk = sum(1 for r in rows if r[2].startswith("SKIP"))
bad = len(rows) - ok - sk
print(f"合计 {len(rows)} 个套件：OK {ok} · SKIP {sk} · 其他 {bad}")
print(f"验收门槛失败数：{gate_fail}")
print("=" * 72)
sys.exit(1 if gate_fail else 0)
