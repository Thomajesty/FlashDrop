# -*- coding: utf-8 -*-
"""v1.8.0 Windows 端验证：设备文件夹名净化 + 与 Android 端结果一致性 + 接收分目录落盘。

Android 侧同名逻辑见 android/app/src/main/java/com/flashdrop/app/FdUtil.folderNameOf，
期望两端口径完全一致（同一台设备在手机/电脑上落到同名文件夹）。
"""
import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import util  # noqa: E402

PASS = 0
FAIL = 0


def eq(name, got, want):
    global PASS, FAIL
    if str(got) == str(want):
        PASS += 1
    else:
        FAIL += 1
        print("FAIL %s\n   got  = %r\n   want = %r" % (name, got, want))


def ok(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print("FAIL " + name)


# ---------------- 1. 设备文件夹名净化 ----------------
eq("普通名", util.safe_folder("小米 14"), "小米 14")
eq("斜杠", util.safe_folder("a/b"), "a_b")
eq("反斜杠", util.safe_folder("a\\b"), "a_b")
eq("Windows非法字符", util.safe_folder("a:b*c?d"), "a_b_c_d")
eq("双引号", util.safe_folder('李"雷'), "李_雷")
eq("空串", util.safe_folder(""), "未知设备")
eq("None", util.safe_folder(None), "未知设备")
eq("纯空格", util.safe_folder("   "), "未知设备")
eq("前导点", util.safe_folder("..abc"), "abc")
eq("全非法", util.safe_folder("///"), "___")
ok("超长截断", len(util.safe_folder("设备名称" * 30)) <= 40)

# 目录穿越必须阻断
for evil in ["..", "../..", "a/../../b", "..\\..\\x", "./.", "..."]:
    f = util.safe_folder(evil)
    ok("无穿越 %r -> %r" % (evil, f),
       "/" not in f and "\\" not in f and f not in (".", ".."))

# 控制字符
f = util.safe_folder("a\x00b\x1fc")
ok("控制字符被替换: %r" % f, "\x00" not in f and "\x1f" not in f)

# ---------------- 2. 与 Android 端口径一致性 ----------------
# 这些样本在 RT180.java 里有对应断言，两端必须给出相同结果
ANDROID_SAMPLES = [
    ("小米 14", "小米 14"),
    ("a/b", "a_b"),
    ("a\\b", "a_b"),
    ("a:b*c?d", "a_b_c_d"),
    ('李"雷', "李_雷"),
    ("", "未知设备"),
    ("   ", "未知设备"),
    ("..abc", "abc"),
    ("///", "___"),
    ("小米 14: Pro/测试", "小米 14_ Pro_测试"),
]
for src, want in ANDROID_SAMPLES:
    eq("跨端一致 %r" % src, util.safe_folder(src), want)

# ---------------- 3. 接收文件按设备分目录落盘 ----------------
tmp = tempfile.mkdtemp(prefix="fd180_")
try:
    save_dir = os.path.join(tmp, "收到的文件")
    # 模拟 node.py 的落盘逻辑
    for pname, fname in [("小米 14", "a.txt"), ("小米 14", "a.txt"),
                         ("华为: P60", "b.png"), ("未知设备", "c.bin")]:
        folder = util.safe_folder(pname)
        dest_dir = os.path.join(save_dir, folder)
        os.makedirs(dest_dir, exist_ok=True)
        dest = util.unique_path(dest_dir, fname)
        with open(dest, "w", encoding="utf-8") as f:
            f.write("x")

    ok("设备目录已建", os.path.isdir(os.path.join(save_dir, "小米 14")))
    ok("含非法字符的设备名目录已建", os.path.isdir(os.path.join(save_dir, "华为_ P60")))

    a1 = os.path.join(save_dir, "小米 14", "a.txt")
    a2 = os.path.join(save_dir, "小米 14", "a (1).txt")
    ok("同名文件不冲突(1)", os.path.exists(a1))
    ok("同名文件不冲突(2)", os.path.exists(a2))

    # 设备间文件互不干扰
    ok("B设备文件在B目录",
       os.path.exists(os.path.join(save_dir, "华为_ P60", "b.png")))
    ok("A目录不含B的文件",
       not os.path.exists(os.path.join(save_dir, "小米 14", "b.png")))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# ---------------- 4. 原有 API 未破坏 ----------------
ok("safe_filename 仍可用", util.safe_filename("a/b.txt") == "a_b.txt")
ok("unique_path 仍可用", util.unique_path(tempfile.gettempdir(), "x.txt").endswith("x.txt"))

print()
print("PASS=%d  FAIL=%d" % (PASS, FAIL))
print("ALL_OK" if FAIL == 0 else "HAS_FAILURE")
sys.exit(0 if FAIL == 0 else 1)
