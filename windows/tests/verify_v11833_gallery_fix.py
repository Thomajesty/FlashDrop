#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
v1.18.33 —— 「离线待发图片不显示 / 补发成功后图片不可用」静态断言套件。

用户反馈：
  ① 相册发图片、对方离线 → 待发送气泡不含图片信息（普通文件卡片），
     用户看不出待发的是什么图 → 反复重发 → 同一张图电脑端"显示两遍"；
  ② 上线补发成功后，手机端气泡不能显示图片、点开提示"图片不可用"。

根因：
  A. FlashNode.sendFileSync（离线队列补发路径）不发 started 事件，
     第一个事件来自 emitSendState，而 emitSendState 事件没有 src 字段
     → 气泡没有图片源。
  B. MainActivity.rebuildPendingMsgs 给待发文件气泡不挂 mime/src
     → 图片待发渲染成普通文件卡片。

行为级验证见 android/tests/RT11833.java（10 项）。
"""
import io
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

PASS = 0
FAIL = 0


def ck(name, ok, extra=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("  PASS  " + name)
    else:
        FAIL += 1
        print("  FAIL  " + name + ("   " + str(extra) if extra else ""))


def rd(path):
    with io.open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return f.read()


def main():
    node = rd("android/app/src/main/java/com/flashdrop/app/FlashNode.java")
    main_act = rd("android/app/src/main/java/com/flashdrop/app/MainActivity.java")

    print("\n=== A. sendFileSync 补发路径 ===")
    m = re.search(
        r"public java\.util\.Map<String, String> sendFileSync\(.*?\n    \}",
        node, re.S)
    ck("A1 存在 sendFileSync", m is not None)
    sfs = m.group(0) if m else ""
    ck("A2 sendFileSync 每个文件先发 started 事件（与 sendFiles 同口径）",
       '"state", "started"' in sfs and '"src", path' in sfs)
    # started 事件必须在 sendFileTo 之前发出（UI 先建气泡）
    ck("A3 started 事件先于 sendFileTo",
       sfs.find('"state", "started"') < sfs.find("sendFileTo(pid, tid, path"))

    print("\n=== B. emitSendState 事件字段 ===")
    m = re.search(
        r"private void emitSendState\(String tid, String pid, String state, "
        r"String reason,\s*\n\s*String path, int attempt\) \{.*?\n    \}", node, re.S)
    ck("B1 存在 6 参 emitSendState", m is not None)
    ess = m.group(0) if m else ""
    ck("B2 事件统一带 src（取自 sendInfo）", '"src", info.optString("src")' in ess)
    ck("B3 事件带 mime（UI 照片模式判定依赖）", '"mime", info.optString("mime")' in ess)
    ck("B4 事件带 targets（UI 多目标/频道判定依赖）", '"targets"' in ess)

    print("\n=== C. rebuildPendingMsgs 照片模式 ===")
    m = re.search(r"private void rebuildPendingMsgs\(\) \{.*?\n    \}", main_act, re.S)
    ck("C1 存在 rebuildPendingMsgs", m is not None)
    rpm = m.group(0) if m else ""
    ck("C2 图片待发挂 mime（isImageMime 判定）",
       "isImageMime" in rpm and "guessMime" in rpm)
    ck("C3 图片待发挂 src（首个 URI 作图片源）",
       "m.src = u0" in rpm and "p.uris.get(0)" in rpm)
    ck("C4 非图片待发不受影响（mime 仅在图片分支赋值）",
       rpm.index("isImageMime(mime0)") < rpm.index("m.mime = mime0"))

    print("\n=== D. photoMode 状态行 ===")
    ck("D1 照片模式下 pending 保留「⏳ 待发送」标记",
       '"⏳ 待发送 · " + phLabel' in main_act)
    ck("D2 待发 0 B 不显示大小", '"0 B".equals(phSize)' in main_act)

    print("\n=== E. 版本号 ===")
    manifest = rd("android/app/src/main/AndroidManifest.xml")
    ck("E1 AndroidManifest versionCode=62 / versionName=1.18.33",
       'android:versionCode="62"' in manifest
       and 'android:versionName="1.18.33"' in manifest)
    fdutil = rd("android/app/src/main/java/com/flashdrop/app/FdUtil.java")
    ck("E2 FdUtil.APP_VERSION=1.18.33",
       'public static final String APP_VERSION = "1.18.33";' in fdutil)
    win_init = rd("windows/app/__init__.py")
    ck("E3 windows __version__=1.18.33（双端版本号一致）",
       '__version__ = "1.18.33"' in win_init)
    bat = rd("android/build_apk.bat")
    sh = rd("android/_build_v11817.sh")
    ck("E4 build_apk.bat version 同步", "--version-code 62 --version-name 1.18.33" in bat)
    ck("E5 _build_v11817.sh version 同步", "--version-code 62 --version-name 1.18.33" in sh)

    print("\n=== F. 回归保护（历史教训不复发） ===")
    ck("F1 aapt2 link 两个入口都带 -A assets（表情资产铁律）",
       '-A "%SRC%\\assets"' in bat and '-A "$BPW\\\\assets"' in sh)
    ck("F2 loadThumbAsync 三级查找仍存在（thumb 磁盘缓存）",
       "loadThumbFromDisk" in main_act and "saveThumbToDisk" in main_act)
    ck("F3 发出侧图片气泡仍走 openImageViewer",
       main_act.count("openImageViewer(m)") >= 3)
    ck("F4 Windows 端 tid 去重仍在（_on_transfer send 分支扫尾部 30 条）",
       "lst_t[-30:]" in rd("windows/app/ui/main_window.py"))
    ck("F5 RT11833 行为测试存在", os.path.isfile(
        os.path.join(ROOT, "android", "tests", "RT11833.java")))
    ck("F6 RT11833 运行脚本存在", os.path.isfile(
        os.path.join(ROOT, "android", "tools", "run_rt11833.sh")))

    print("\n结果: %d 通过, %d 失败" % (PASS, FAIL))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
