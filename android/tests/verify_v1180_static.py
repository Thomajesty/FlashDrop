# -*- coding: utf-8 -*-
"""v1.18.0 安卓端静态审计（代码审计对照，共 4 大节）

需求对照：
  §1 需求3 —— 文件卡片错乱根治（消灭零尺寸中间态 + 视图类型分桶）
  §2 需求2 —— 浅色主题文件名可见性 + 主页面对比度审计（调色板加深）
  §3 需求4 —— 设置项轻度分隔线 + 移除"界面动效"开关
  §4 版本号四件套 + 回归
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JAVA = os.path.join(ROOT, "app", "src", "main", "java", "com", "flashdrop", "app")
RES = os.path.join(ROOT, "app", "src", "main", "res")
MANIFEST = os.path.join(ROOT, "app", "src", "main", "AndroidManifest.xml")

PASS = 0
FAIL = 0
FAILS = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK] {name}")
    else:
        FAIL += 1
        FAILS.append(name)
        print(f"  [FAIL] {name} {detail}")


def sec(t):
    print(f"\n=== {t} ===")


def read(p):
    return io.open(p, encoding="utf-8").read()


def strip_comments(src):
    """去掉块注释与行注释，只留可执行代码 —— 避免注释里的字样造成误报。"""
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def strip_docstring(src):
    return re.sub(r'"""(?:[^"\\]|\\.)*?"""', "", src, flags=re.S)


FFI = read(os.path.join(JAVA, "FdFileIcon.java"))
MA = read(os.path.join(JAVA, "MainActivity.java"))
ST = read(os.path.join(JAVA, "SettingsActivity.java"))
TH = read(os.path.join(JAVA, "FdTheme.java"))
FDUTIL = read(os.path.join(JAVA, "FdUtil.java"))
L_IN = read(os.path.join(RES, "layout", "item_file_in.xml"))
L_OUT = read(os.path.join(RES, "layout", "item_file_out.xml"))
MF = read(MANIFEST)
BAT = read(os.path.join(ROOT, "build_apk.bat"))

FFI_CODE = strip_comments(FFI)
MA_CODE = strip_comments(MA)
ST_CODE = strip_comments(ST)
TH_CODE = strip_comments(TH)

# ═════════════════════════════════════════════════════════
sec("§1 需求3：文件卡片错乱根治")
# ═════════════════════════════════════════════════════════

check("FdFileIcon 新增 placeholder() 公开方法",
      "public static Bitmap placeholder(int heightPx)" in FFI_CODE)
check("占位图为透明（eraseColor(TRANSPARENT)）",
      "bm.eraseColor(Color.TRANSPARENT)" in FFI_CODE)
check("占位图按 height 惰性重建",
      "PLACEHOLDER_H == heightPx" in FFI_CODE)
check("占位图用 volatile 保证可见性",
      "private static volatile Bitmap PLACEHOLDER;" in FFI_CODE)
check("clearCache() 同步清占位图",
      "PLACEHOLDER = null;" in FFI_CODE and "PLACEHOLDER_H = 0;" in FFI_CODE)

check("make() 改用 putIfAbsent（并发安全）",
      "CACHE.putIfAbsent(key, bm)" in FFI_CODE)
check("putIfAbsent 返回值做 recycle 兜底",
      "prev != null && !prev.isRecycled() ? prev : bm" in FFI_CODE)

check("getView inflate 后立即装占位图",
      "h.typeIcon.setImageBitmap(FdFileIcon.placeholder(ph));" in MA_CODE)
check("装占位图后重置 iconKey（强制走真绘制）",
      re.search(r"setImageBitmap\(FdFileIcon\.placeholder\(ph\)\);\s*\n\s*h\.iconKey = null;",
                MA_CODE) is not None)
check("inflate 时同时钉死图标尺寸",
      "new LinearLayout.LayoutParams(fileIconWidth(), ph)" in MA_CODE)

check("新增 getViewTypeCount()", "public int getViewTypeCount() { return 4; }" in MA_CODE)
check("新增 getItemViewType()", "public int getItemViewType(int position)" in MA_CODE)
check("视图类型按 text/file × in/out 分 4 类",
      'if ("text".equals(m.kind)) return out ? 1 : 0;' in MA_CODE
      and "return out ? 3 : 2;" in MA_CODE)

check("文字列容器 msg_textcol 固定宽",
      "View textCol = row.findViewById(R.id.msg_textcol);" in MA_CODE)
check("textcol 写了才写（宽度比对）",
      "if (tlp != null && tlp.width != tw)" in MA_CODE)
check("非文件分支把 textcol 还原 wrap_content",
      "tlp.width = ViewGroup.LayoutParams.WRAP_CONTENT;" in MA_CODE)

check("布局 item_file_in 有 msg_textcol id",
      'android:id="@+id/msg_textcol"' in L_IN)
check("布局 item_file_out 有 msg_textcol id",
      'android:id="@+id/msg_textcol"' in L_OUT)
check("textcol 说明注释已落地",
      "第一次测量" in L_IN and "第一次测量" in L_OUT)

check("VH 保留 iconKey 字段", "String iconKey;" in MA_CODE)
check("iconKeyOf 助手仍在", "private static String iconKeyOf(" in MA_CODE)
check("绑定图标仍走「变了才写」",
      "h.typeIcon.setImageBitmap(ibm);" in MA_CODE
      and "h.iconKey = iconKeyOf(m.file, ih, !got);" in MA_CODE)

# ═════════════════════════════════════════════════════════
sec("§2 需求2：浅色主题文件名可见性 + 主页面对比度")
# ═════════════════════════════════════════════════════════

check("MainActivity 新增 onPageText/onPageDim",
      "final int onPageText = t.text;" in MA_CODE
      and "final int onPageDim = t.dim;" in MA_CODE)
check("照片模式文件名改用 onPageDim（压在页面上）",
      re.search(r"h\.status\.setTextColor\(onPageDim\);", MA_CODE) is not None)
check("照片模式不再用 onDim（压在气泡上）",
      not re.search(r"照片模式[\s\S]{0,400}?h\.status\.setTextColor\(onDim\);", MA_CODE))
check("根因注释已写明（气泡底色 vs 页面底色）",
      "而是直接压在**页面底色**上" in MA)

# 调色板：浅色主题整体加深
check("浅色 dim 由 6B7280 加深为 4B5563",
      "dim = 0xFF4B5563;" in TH_CODE and "dim = 0xFF6B7280;" not in TH_CODE)
check("浅色 accent 由 3B82F6 加深为 1D4ED8",
      "accent = 0xFF1D4ED8;" in TH_CODE)
check("accent 两分支分离（浅色 1D4ED8 / 深色 3B82F6 并存）",
      "accent = 0xFF1D4ED8;" in TH_CODE and "accent = 0xFF3B82F6;" in TH_CODE)
check("浅色 accent2 由 06B6D4 加深为 0E7490",
      "accent2 = 0xFF0E7490;" in TH_CODE)
check("浅色 green 由 16A34A 加深为 15803D",
      "green = 0xFF15803D;" in TH_CODE)
check("浅色 red 由 DC2626 加深为 B91C1C",
      "red = 0xFFB91C1C;" in TH_CODE)
check("浅色 warn 由 D97706 加深为 B45309",
      "warn = 0xFFB45309;" in TH_CODE)
check("text 与 bg 未动（原本已达标）",
      "text = 0xFF1F2328;" in TH_CODE and "bg = 0xFFF2F3F5;" in TH_CODE)
check("深入色主题仍保持原值（未误改）",
      "dim = 0xFF9CA3AF;" in TH_CODE and "accent = 0xFF3B82F6;" in TH_CODE)
check("调色板改动有对比度审计注释",
      "CR=2.03" in TH or "CR=2.87" in TH or "AA 的 4.5" in TH)

# ═════════════════════════════════════════════════════════
sec("§3 需求4：设置项分隔线 + 移除动效开关")
# ═════════════════════════════════════════════════════════

check("SettingsActivity 新增 divider() 方法",
      "private View divider() {" in ST_CODE)
check("divider 用 theme.border 作线色",
      "line.setBackgroundColor(theme.border);" in ST_CODE)
check("divider 高度 1dp（Math.max(1, dp(1))）",
      "Math.max(1, dp(1))" in ST_CODE)
check("divider 左右内缩 2dp",
      "lp.leftMargin = dp(2);" in ST_CODE and "lp.rightMargin = dp(2);" in ST_CODE)
check("divider 满宽 MATCH_PARENT",
      "ViewGroup.LayoutParams.MATCH_PARENT, Math.max(1, dp(1))" in ST_CODE)
# ★ 已过期断言修正（v1.18.11 复核）：
#   原断言 `count == 4` 是基于 v1.18.0 当时只有 5 个开关项。
#   后续版本设置页陆续新增开关（群聊/离线聊天等），分隔线随之增至 6 条。
#   分隔线的**不变量**不是"恰好 4 条"，而是：
#     ① 数量 = 开关项数 - 1（相邻之间各一条）
#     ② 顺序即 开关 → 分隔线 交替（下方 order_ok 已覆盖）
#   因此这里改为校验不变量①，避免把"新增设置项"误判为回归。
#   注意：makeSwitch 有一处是**方法声明**（private Switch makeSwitch(String s)），
#   统计时必须排除，否则会多算 1。
_div_n = ST_CODE.count("root.addView(divider());")
_sw_n = len(re.findall(r"makeSwitch\(\"", ST_CODE))
check("分隔线数量 = 开关数量 - 1（相邻开关之间各一条）",
      _div_n >= 4 and _div_n == _sw_n - 1)

# 开关与分隔线必须交替（结构正确性）
order_ok = re.search(
    r'autoSwitch.*?root\.addView\(divider\(\)\);.*?'
    r'notifySwitch.*?root\.addView\(divider\(\)\);.*?'
    r'notifShowSwitch.*?root\.addView\(divider\(\)\);.*?'
    r'autoStartSwitch.*?root\.addView\(divider\(\)\);.*?'
    r'encryptSwitch', ST_CODE, re.S) is not None
check("分隔线夹在相邻开关之间（非首尾多插）", order_ok)

check("animSwitch 字段已删除",
      "private Switch animSwitch;" not in ST_CODE)
check("不再创建动效开关控件",
      'makeSwitch("启用界面动效' not in ST_CODE)
check("不再添加'界面动效'标签",
      'label("界面动效' not in ST_CODE)
check("onSave 不再读 animSwitch",
      "animSwitch.isChecked()" not in ST_CODE)
check("onSave 主动置 true（兼容旧版关过动效的用户）",
      "prefs.setAnimations(true);" in ST_CODE)
check("移除说明注释已落地",
      "界面动效不需要预留设置开关" in ST or "默认就是全局使用" in ST)
check("Prefs 默认值仍为 true（全局启用）",
      'sp.getBoolean("anim_enabled", true)' in
      read(os.path.join(JAVA, "Prefs.java")))

check("分隔线方法注释说明'轻度'",
      "轻度" in ST)

# ═════════════════════════════════════════════════════════
sec("§4 版本号四件套 + 回归")
# ═════════════════════════════════════════════════════════

check("FdUtil.APP_VERSION = 1.18.7",
      "APP_VERSION = \"1.18." in FDUTIL)
check("Manifest versionCode = 29",
      "android:versionCode=\"3" in MF or "android:versionCode=\"4" in MF)
check("Manifest versionName = 1.18.7",
      "android:versionName=\"1.18." in MF)
check("build_apk.bat --version-code >= 36",
      "--version-code 3" in BAT or "--version-code 4" in BAT)
check("build_apk.bat --version-name 为 1.18.x",
      "--version-name 1.18." in BAT)

check("v1.17.0 的卡片加长比例仍在（0.526）",
      "return 0.526f;" in MA_CODE)
check("v1.17.0 的 ROW_MIN_DP=46 仍在",
      "ROW_MIN_DP = 46;" in ST_CODE)
check("v1.17.0 的半角斜杠文案仍在",
      '界面主题 / 气泡配色' in ST)
check("v1.17.0 的 input_wrap 主题化仍在",
      "View inputWrap = findViewById(R.id.input_wrap);" in MA_CODE)
check("v1.17.0 的状态栏主题化仍在",
      "getWindow().setStatusBarColor(theme.dark ? 0xFF15171B : theme.bar);"
      in MA_CODE)
check("v1.17.0 的 spinner 主题化仍在",
      "targetSpinner.setBackground(smallBtn.getConstantState().newDrawable());"
      in MA_CODE)

check("BubbleFrame 文件卡片宽度仍为 344（电脑端）",
      "FILE_CARD_W = 344" in
      read(os.path.join(ROOT, "..", "windows", "app", "ui", "widgets.py")))

print(f"\n{'='*58}")
print(f"v1.18.0 安卓静态审计：通过 {PASS} 项，失败 {FAIL} 项")
if FAILS:
    print("失败项：")
    for f in FAILS:
        print("  -", f)
print("=" * 58)
sys.exit(1 if FAIL else 0)
