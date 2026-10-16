# -*- coding: utf-8 -*-
"""v1.17.0 安卓端静态审计（源码断言，不依赖 Android SDK / 模拟器）

对应用户本轮 5 项需求里与**安卓端**相关的部分：

  [1] 文件卡片渲染优化 —— 首次适配慢 / 显示不稳定 / 每次进入像重建
      · FdFileIcon 增加按 (扩展名|高|虚线态) 的 Bitmap 缓存
      · MainActivity 布局参数 & 位图「变了才写」，稳态零重排
  [2] 文件卡片加长 —— 卡宽 0.493 → 0.526（文字区 244→266dp，对齐微信实测）
  [3] 设置页「界面主题 / 气泡配色」斜杠文案 + 选择框与输入框等高（46dp）
  [5] 浅色主题下设备选择框不再黑 + 底部消息栏局部黑色修正

跑法（任选，不需要 PySide6）：
    "C:/Users/Administrator/.workbuddy/binaries/python/versions/3.13.12/python.exe" \
        android/tests/verify_v1170_static.py
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(ROOT, "android", "app", "src", "main")

pass_n = 0
fail_n = 0
_fails = []


def check(name, cond, detail=""):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print(f"  [PASS] {name}")
    else:
        fail_n += 1
        _fails.append(name)
        print(f"  [FAIL] {name}  {detail}")


def rd(p):
    with io.open(p, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def java(name):
    return rd(os.path.join(SRC, "java", "com", "flashdrop", "app", name))


def res(name):
    return rd(os.path.join(SRC, "res", name))


FDU = java("FdUtil.java")
FIC = java("FdFileIcon.java")
MA = java("MainActivity.java")
SA = java("SettingsActivity.java")
FTH = java("FdTheme.java")
MANIFEST = rd(os.path.join(SRC, "AndroidManifest.xml"))
LAY_IN = res("layout/item_file_in.xml")
LAY_OUT = res("layout/item_file_out.xml")
LAY_MAIN = res("layout/activity_main.xml")
BUILD = rd(os.path.join(ROOT, "android", "build_apk.bat"))
WIN_INIT = rd(os.path.join(ROOT, "windows", "app", "__init__.py"))

print("=" * 72)
print("v1.17.0 安卓端静态审计")
print("=" * 72)

# ---------------------------------------------------------------- 版本四件套
print("\n【版本四件套】")
check("FdUtil.APP_VERSION 为 1.18.x",
      'APP_VERSION = "1.18.' in FDU)
check("AndroidManifest versionCode>=36", "android:versionCode=\"3" in MANIFEST or "android:versionCode=\"4" in MANIFEST)
check("AndroidManifest versionName 为 1.18.x",
      "android:versionName=\"1.18." in MANIFEST)
check("build_apk.bat --version-code >= 36", "--version-code 3" in BUILD or "--version-code 4" in BUILD)
check("build_apk.bat --version-name 为 1.18.x", "--version-name 1.18." in BUILD)
check("windows/app/__init__.py __version__ 为 1.18.x",
      '__version__ = "1.18.' in WIN_INIT)

# ------------------------------------------------- [1] 文件卡片渲染优化
print("\n【需求1：文件卡片渲染优化（首帧 / 稳定性 / 复用）】")

# 1.1 Bitmap 缓存
check("FdFileIcon 引入 ConcurrentHashMap 图标缓存",
      "ConcurrentHashMap<String, Bitmap> CACHE" in FIC)
check("FdFileIcon.make 先查缓存再绘制",
      "Bitmap hit = CACHE.get(key)" in FIC
      and "if (hit != null && !hit.isRecycled()) return hit;" in FIC)
check("FdFileIcon.make 绘制后写回缓存",
      # v1.18.0：由 CACHE.put 改为 CACHE.putIfAbsent（并发安全），
      # 断言随之更新 —— 语义仍是"未命中时把新画的位图登记进缓存"。
      "CACHE.putIfAbsent(key, bm)" in FIC)
check("缓存 key 为「扩展名|高度|虚线态」三元组",
      "String key = (ext.isEmpty() ? \"?\" : ext)" in FIC
      and "+ '|' + height + '|' + (dimmed ? 1 : 0);" in FIC)
check("拆分出私有 draw() 供缓存路径调用",
      "private static Bitmap draw(String ext, int height, boolean dimmed)" in FIC)
check("提供 clearCache() 出口", "public static void clearCache()" in FIC)
check("classifyExt() 直接按扩展名分类（省去重复解析文件名）",
      "private static String[] classifyExt(String ext)" in FIC)
check("draw() 内改调 classifyExt(ext) 而非 classify(name)",
      "String[] cls = classifyExt(ext);" in FIC)
check("FdFileIcon.widthFor() 仍公开（调用方兜底用）",
      "public static int widthFor(int heightPx)" in FIC)

# 1.2 MainActivity 稳态零重排
check("MainActivity 卡片宽度「变了才写」",
      "int want = fileCardWidth();" in MA
      and "if (lp != null && lp.width != want) {" in MA)
check("MainActivity 图标尺寸「变了才写」",
      "if (ilp == null || ilp.width != iw || ilp.height != ih) {" in MA)
check("MainActivity 位图按 iconKey 去重",
      "h.iconKey = iconKeyOf(m.file, ih, !got);" in MA
      and "!h.iconKey.equals(iconKeyOf(m.file, ih, !got))" in MA)
check("VH 新增 iconKey 字段",
      "String iconKey;" in MA)
check("新增 iconKeyOf() 静态助手",
      "private static String iconKeyOf(String fileName, int height, boolean dimmed)"
      in MA)
check("隐藏分支复位 iconKey = null", "h.iconKey = null;" in MA)
check("setImageDrawable(null) 前不回收共享缓存位图",
      "setImageDrawable(null);" in MA and "recycle()" not in MA.split(
          "if (h.typeIcon != null)")[1].split("// ★ v1.15.0")[0])

# ------------------------------------------------- [2] 卡片加长
print("\n【需求2：文件卡片加长（对齐微信实测）】")
check("fileCardWidthRatio() 抽出比例常量",
      "private float fileCardWidthRatio()" in MA)
check("比例由 0.493 提到 0.526", "return 0.526f;" in MA)
check("旧比例 0.493 已不再出现", "0.493f" not in MA)
check("fileCardWidth() 使用比例函数",
      "* fileCardWidthRatio());" in MA)
check("窄屏兜底 min 保留",
      "int min = fileIconWidth() + dp(12 + 14 + 12 + 60);" in MA)
check("fileCardTextWidth() 仍按内边距+图标宽倒推",
      "fileCardWidth() - dp(12 + 14 + 12) - fileIconWidth()" in MA)
check("item_file_in.xml 注释更新为 344dp / 266dp",
      "344dp" in LAY_IN and "266dp" in LAY_IN and "0.526" in LAY_IN)
check("item_file_out.xml 注释更新为 344dp / 266dp",
      "344dp" in LAY_OUT and "266dp" in LAY_OUT and "0.526" in LAY_OUT)
check("旧 322dp 规格已从 in 注释移除", "322 - 12 - 14 - 40 - 12" not in LAY_IN)
check("旧 322dp 规格已从 out 注释移除", "322 - 12 - 14 - 40 - 12" not in LAY_OUT)

# ------------------------------------------------- [3] 设置页
print("\n【需求3：设置页斜杠文案 + 选择框等高】")
check("界面主题 / 气泡配色 文案已改半角斜杠",
      '"界面主题 / 气泡配色（发送的消息将带上你的配色）"' in SA)
check("旧全角「界面主题　／　气泡配色」已从**可执行代码**移除",
      not re.search(r'label\("[^"]*界面主题\u3000\uff0f\u3000气泡配色', SA)
      and '"界面主题 / 气泡配色（发送的消息将带上你的配色）"' in SA)
check("界面动效标签全角空格已清理",
      "界面动效\u3000·\u3000" not in SA)
check("服务端口标签全角空格已清理",
      "服务端口（修改后需重启应用）\u3000·\u3000" not in SA)
check("数据清理标签全角空格已清理",
      "数据清理\u3000·\u3000" not in SA)
check("新增 ROW_MIN_DP = 46 行高基准",
      "private static final int ROW_MIN_DP = 46;" in SA)
check("makeInput() 应用最小高度",
      "e.setMinimumHeight(dp(ROW_MIN_DP));" in SA)
check("makeSpinner() 应用最小高度",
      "sp.setMinimumHeight(dp(ROW_MIN_DP));" in SA)
check("Spinner 内 item View 上下内边距归零",
      "tv.setPadding(dp(4), 0, dp(4), 0);" in SA)
check("spinRow 行容器等高",
      "spinRow.setMinimumHeight(dp(ROW_MIN_DP));" in SA)
check("下拉弹层仍保留宽松行高（可点选）",
      "tv.setPadding(dp(12), dp(12), dp(12), dp(12));" in SA)

# ------------------------------------------------- [5] 浅色主题局部黑
print("\n【需求5：浅色主题设备框 / 底部栏】")
check("activity_main.xml 底部输入栏补 id=input_wrap",
      'android:id="@+id/input_wrap"' in LAY_MAIN)
check("target_spinner 移除写死深色 background（btn_small 不再挂在 Spinner 上）",
      not re.search(r'<Spinner[^>]*android:background="@drawable/btn_small"',
                    LAY_MAIN, re.S)
      and re.search(r'<Spinner[^>]*android:id="@\+id/target_spinner"', LAY_MAIN, re.S)
      and not re.search(r'<Spinner[^>]*android:background=', LAY_MAIN, re.S))
check("其余按钮仍保留 btn_small（扫描 / 删除 / 多选，未被误伤）",
      LAY_MAIN.count('android:background="@drawable/btn_small"') >= 4)
check("target_spinner 移除写死深色 popupBackground",
      'android:popupBackground="#26292F"' not in LAY_MAIN)
check("applyTheme 给 input_wrap 上主题色",
      "View inputWrap = findViewById(R.id.input_wrap);" in MA
      and "inputWrap.setBackgroundColor(theme.bar);" in MA)
check("applyTheme 给 targetSpinner 上主题背景",
      "targetSpinner.setBackground(smallBtn.getConstantState().newDrawable());" in MA)
check("applyTheme 状态栏随主题（浅色用 bar）",
      "getWindow().setStatusBarColor(theme.dark ? 0xFF15171B : theme.bar);" in MA)
check("旧写死状态栏色 0xFF15171B 已不再无条件设置",
      "setStatusBarColor(0xFF15171B);" not in MA)
check("FdTheme 浅色 bar = 白", "bar = LIGHT_BAR;" in FTH
      and "LIGHT_BAR = 0xFFFFFFFF" in FTH)
check("FdTheme 浅色 card = 白", "card = 0xFFFFFFFF;" in FTH)

# ------------------------------------------------- 回归：不得误伤
print("\n【回归检查（防止误伤既有能力）】")
check("微信绿方案未被改动",
      "{0xFF95EC69, 0xFF17301B}" in FTH)
check("apk 仍单独分类为安卓绿/APK",
      'put("#3DDC84", "APK", "apk");' in FIC)
check("exe/msi 仍为 EXE 蓝",
      'put("#0F6FCB", "EXE", "exe", "msi", "bat", "cmd");' in FIC)
check("图标几何基准未变（DW=40 DH=52）",
      "private static final float DW = 40f;" in FIC
      and "private static final float DH = 52f;" in FIC)
check("未接收态仍是虚线描边（非半透明）",
      "setPathEffect(new DashPathEffect(" in FIC)
check("卡片宽度钉死逻辑仍在（isFile && !photoMode）",
      "if (bubble != null && isFile && !photoMode) {" in MA)
check("文件名两行截断仍在", "h.name.setMaxLines(2);" in MA)
check("受保护目录 USER_SAVE_DIR 仍在",
      "USER_SAVE_DIR" in FDU and "保存的文件" in FDU)
check("FdDialog 仍被设置页使用", "FdDialog.show(this" in SA)
check("WAKE_LOCK 权限仍在", "WAKE_LOCK" in MANIFEST)

# ---------------------------------------------------------------- 汇总
print("\n" + "=" * 72)
print(f"结果：{pass_n} 通过 / {fail_n} 失败")
if _fails:
    print("失败项：")
    for f in _fails:
        print("  · " + f)
print("=" * 72)
sys.exit(1 if fail_n else 0)
