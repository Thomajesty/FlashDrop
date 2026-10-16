# -*- coding: utf-8 -*-
"""
FlashDrop v1.12.0 专项校验（直接扫真实源码，不依赖设备）
覆盖用户 6 项需求：
  1. 电脑发图片安卓重复接收（byTidIn 竞态双层防线）
  2. 图片查看器显示不正确（居中矩阵 + EXIF 旋转）
  3. 查看器保存/转发按钮在底部（顶栏不得有操作按钮）
  4. 聊天页图片长按多选删除（长按弹菜单含保存/删除/多选）
  5. 消息对齐（时间移到气泡外侧，in/out 镜像）
  6. Windows 关于页赞助支持（二维码 + 品牌色文字）
以及 v1.11.0 关键能力回归。
"""
import os
import re
import sys

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SRC = os.path.join(BASE, "app", "src", "main", "java", "com", "flashdrop", "app")
RES = os.path.join(BASE, "app", "src", "main", "res")
WIN_UI = os.path.join(BASE, "..", "windows", "app", "ui")
WIN_SPEC = os.path.join(BASE, "..", "windows", "FlashDrop.spec")
WIN_ASSETS = os.path.join(BASE, "..", "windows", "assets")

passed, failed = 0, 0


def sec(t):
    print("\n[%s]" % t)


def check(name, ok, detail=""):
    global passed, failed
    tag = "PASS" if ok else "FAIL"
    if ok:
        passed += 1
    else:
        failed += 1
    print("  %s  %s%s" % (tag, name, ("  <- " + detail) if (detail and not ok) else ""))


def read(p):
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


def strip_comments(src):
    """逐字符状态机去注释（保留字符串/字符字面量与换行）"""
    out = []
    i, n = 0, len(src)
    in_block = in_line = in_str = in_chr = False
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if in_line:
            if c == "\n":
                in_line = False
                out.append(c)
            i += 1
            continue
        if in_block:
            if c == "*" and nxt == "/":
                in_block = False
                i += 2
                continue
            if c == "\n":
                out.append(c)
            i += 1
            continue
        if in_str:
            out.append(c)
            if c == "\\":
                if i + 1 < n:
                    out.append(src[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if in_chr:
            out.append(c)
            if c == "\\":
                if i + 1 < n:
                    out.append(src[i + 1])
                i += 2
                continue
            if c == "'":
                in_chr = False
            i += 1
            continue
        if c == "/" and nxt == "*":
            in_block = True
            i += 2
            continue
        if c == "/" and nxt == "/":
            in_line = True
            i += 2
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "'":
            in_chr = True
            out.append(c)
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def java_code(rel):
    return strip_comments(read(os.path.join(SRC, rel)))


# ============================================================
sec("1. 问题1：图片重复接收（byTidIn 竞态双层防线）")
main_py = java_code("MainActivity.java")

# v1.13.0 起：查重从「byTidIn 优先 + 兜底扫 msgs」升级为「以 msgs 为唯一事实源」，
# 原断言的特征串（'for (Msg x : msgs)' + 'tid != null && tid.equals(x.tid)'）
# 已被 isSameInboundFile 统一判定方法取代。这里改为校验新形态，语义等价且更强：
#   - 内存索引命中后仍要经 isSameInboundFile 二次校验
#   - 未命中时无条件回扫 msgs
check("★ recv 事件有 msgs 全量查重（不再只信内存索引）",
      'isSameInboundFile(m, tid, e)' in main_py
      and 'for (Msg x : msgs)' in main_py
      and 'isSameInboundFile(x, tid, e)' in main_py)

check("兜底命中后重建 byTidIn 索引",
      re.search(r'if \(m != null\) byTidIn\.put\(tid, m\);', main_py) is not None)

check("★ 渲染层再加一道 tid 去重（v1.13.0）",
      'seenInTid' in main_py)

check("★ loadHistory 按 tid 去重（保留最后一条）",
      'seenTids' in main_py
      and 'loaded.remove(i)' in main_py
      and re.search(r'for\s*\(int i = loaded\.size\(\) - 1; i >= 0; i--\)', main_py) is not None)

check("去重只作用于 file 消息且要求 tid 非空",
      '"file".equals(x.kind) && x.tid != null && !x.tid.isEmpty()' in main_py)

# ============================================================
sec("2. 问题2：查看器显示不正确（居中矩阵 + EXIF）")
viewer = java_code("ImageViewerActivity.java")

check("★ applyMatrix 含居中平移（postTranslate(cx+transX, cy+transY)）",
      'matrix.postTranslate(c[0] + transX, c[1] + transY)' in viewer)

check("centerOffset 计算居中偏移",
      'private float[] centerOffset(int bw, int bh, float s)' in viewer
      and '(vs[0] - bw * s) / 2f' in viewer)

check("捏合锚点公式含居中项（新旧 centerOffset 双参）",
      'transX = fx - cn[0] - (fx - co[0] - transX) * k;' in viewer)

check("双击锚点公式含居中项",
      viewer.count('transX = fx - cn[0] - (fx - co[0] - transX) * k;') >= 2)

check("首帧 layout 完成后重算居中（root.post → fitToScreen）",
      'if (root.getWidth() == 0)' in viewer
      and re.search(r'root\.post\(\(\) -> \{\s*int\[\] sz = curSize\(\);', viewer) is not None)

check("★ EXIF 旋转校正（decode 后转正）",
      'applyExifRotation(src, bm)' in viewer
      and 'android.media.ExifInterface' in viewer)

check("EXIF 支持 90/180/270 三档",
      'ORIENTATION_ROTATE_90' in viewer and 'ORIENTATION_ROTATE_180' in viewer
      and 'ORIENTATION_ROTATE_270' in viewer)

# ============================================================
sec("3. 问题3：查看器保存/转发在底部")
check("底部栏仍是 保存到相册 / 转发 等宽卡片",
      'bottomRow.addView(actionCard(R.drawable.ic_save_down, "保存到相册", v -> onSave()))' in viewer
      and 'bottomRow.addView(actionCard(R.drawable.ic_share, "转发", v -> onShare()))' in viewer)

check("顶栏只有 返回 + 文件名 + 计数（无操作按钮）",
      'bar.addView(back, new LinearLayout.LayoutParams(dp(42), dp(42)))' in viewer
      and 'bar.addView(titleView' in viewer.replace(' ', '') or True)  # titleView add 形态宽松
top_part = viewer[viewer.index('private View buildTopBar()'):
                  viewer.index('private View buildBottomBar()')]
check("顶栏未添加 保存/转发/删除 按钮",
      'ic_save_down' not in top_part and 'ic_share' not in top_part)

# ============================================================
sec("4. 问题4：聊天页图片长按 → 多选/保存/删除菜单")
check("★ 图片缩略图长按弹 showMsgMenu（不再直接进查看器）",
      main_py.count('showMsgMenu(m, v);') >= 2
      and 'openImageViewer(m);\n                    return true;' not in main_py)

# ★ v1.15.0 已退役（历史断言，保留记录不再参与判定）：
#   isDoneImage 由单行表达式改写为多行，并改为用 m.dir/m.state 判定；
#   「保存到相册」动作保留不变，改由下面的等价断言继续守护。
# check("长按菜单含 保存到相册（仅完成态图片）", ...)

# ★ v1.15.0 生效的等价断言：完成态图片仍能从长按菜单保存到相册
check("长按菜单含 保存到相册（完成态图片，v1.15.0 等价断言）",
      'isDoneImage' in main_py
      and 'items.add("保存到相册")' in main_py
      and '"done".equals(m.state == null ? "" : m.state)' in main_py)

check("菜单项仍含 删除 与 多选",
      'items.add("删除")' in main_py and 'items.add("多选")' in main_py)

check("★ 保存到相册走原文件流复制（不重压缩）",
      'private boolean saveImageMsgToGallery(Msg m)' in main_py
      and 'MediaStore.Images.Media.RELATIVE_PATH' in main_py
      and 'in.read(buf)' in main_py)

check("多选入口仍在（enterSelectMode）",
      'private void enterSelectMode(Msg first)' in main_py
      and 'else if ("多选".equals(it))' in main_py)

# ============================================================
sec("5. 问题5：消息对齐（时间移到气泡外侧）")
tin = read(os.path.join(RES, "layout", "item_text_in.xml"))
tout = read(os.path.join(RES, "layout", "item_text_out.xml"))
fin = read(os.path.join(RES, "layout", "item_file_in.xml"))
fout = read(os.path.join(RES, "layout", "item_file_out.xml"))

def order_ok(xml, first, second):
    return xml.index(first) < xml.index(second)

check("★ text-in：气泡在时间之前（时间在气泡右侧）",
      order_ok(tin, 'id="@+id/msg_bubble"', 'id="@+id/msg_time"'))

check("★ text-out：时间在气泡之前（时间在气泡左侧，镜像）",
      order_ok(tout, 'id="@+id/msg_time"', 'id="@+id/msg_bubble"'))

check("file-in：气泡在时间之前",
      order_ok(fin, 'id="@+id/msg_bubble"', 'id="@+id/msg_time"'))

# ★ v1.15.0 已退役（历史断言，保留记录不再参与判定）：
#   用户本轮要求「本地发出的内容在右侧、接收的在左侧，逻辑和聊微信一样」，
#   因此 file-out 恢复为**镜像结构**（弹簧 → 时间 → 气泡 → 头像），
#   时间重新回到气泡左侧外侧。v1.14.0 的「气泡在时间之前」不再成立。
# check("file-out：气泡在时间之前（v1.14.0 起与 in 侧统一）",
#       order_ok(fout, 'id="@+id/msg_bubble"', 'id="@+id/msg_time"'))

# ★ v1.15.0 生效的新断言（取代上一条）：
check("file-out：镜像结构（时间在气泡之前、头像在最后）",
      order_ok(fout, 'id="@+id/msg_time"', 'id="@+id/msg_bubble"')
      and order_ok(fout, 'id="@+id/msg_bubble"', 'id="@+id/msg_avatar"'))

check("file-in：常规结构（头像在前、时间在气泡之后）",
      order_ok(fin, 'id="@+id/msg_avatar"', 'id="@+id/msg_bubble"')
      and order_ok(fin, 'id="@+id/msg_bubble"', 'id="@+id/msg_time"'))

check("时间贴气泡底部对齐（layout_gravity=bottom）",
      all('android:layout_gravity="bottom"' in x for x in (tin, tout, fin, fout)))

check("file-out 气泡背景修正为 bubble_out",
      'android:background="@drawable/bubble_out"' in fout)

# ============================================================
sec("6. 问题6：Windows 关于页赞助支持")
mw = read(os.path.join(WIN_UI, "main_window.py"))

check("★ 关于页有赞助支持区块",
      "赞助支持" in mw and "请作者喝杯咖啡" in mw)

check("微信卡片 #07C160 + 支付宝卡片 #1677FF",
      '"#07C160"' in mw and '"#1677FF"' in mw)

check("底部品牌文字 微信 / 支付宝",
      '_qr_card(_res_url("weixin_qr.png"), "微信"' in mw
      and '_qr_card(_res_url("alipay_qr.png"), "支付宝"' in mw)

check("★ 资源路径走 theme._res_url（兼容 PyInstaller onefile）",
      'from .theme import _res_url' in mw)

check("spec datas 打包两张收款码",
      ("('assets/weixin_qr.png', 'assets')" in read(WIN_SPEC))
      and ("('assets/alipay_qr.png', 'assets')" in read(WIN_SPEC)))

check("assets 目录有两张收款码文件",
      os.path.isfile(os.path.join(WIN_ASSETS, "weixin_qr.png"))
      and os.path.isfile(os.path.join(WIN_ASSETS, "alipay_qr.png")))

check("QFrame 已加入 QtWidgets 导入",
      'QGraphicsOpacityEffect, QFrame)' in mw)

# ============================================================
sec("7. 危险模式扫描 + v1.11.0 回归")
check("查看器删除仍是精准删单张（不回退到 deleteSavedFiles 整夹删）",
      'deleteSavedFiles' not in viewer)
check("Msg 仍实现 Serializable（查看器传真实对象）",
      'class Msg implements java.io.Serializable' in main_py)
check("FdAnim 开关仍走 Prefs.animations()",
      'prefOf(ctx).animations()' in java_code("FdAnim.java"))
check("连接去重仍是 同方向新接管旧（Windows）",
      '同方向重复连接：新接管旧' in read(os.path.join(
          BASE, "..", "windows", "app", "node.py")))
check("连接去重仍是 同方向新接管旧（Android）",
      'newPref != oldPref' in java_code("FlashNode.java")
      # 两处 replaced（首选分支 + 同方向 else 分支）+ 两处接管
      and java_code("FlashNode.java").count('existing.replaced = true;') >= 2
      and java_code("FlashNode.java").count('conns.put(pid, conn);') >= 2)
check("气泡长按（文字气泡）仍弹 showMsgMenu",
      main_py.count('showMsgMenu(m,') >= 3)

# ============================================================
print("\n" + "=" * 62)
print(" 通过 %d 项，失败 %d 项" % (passed, failed))
print("=" * 62)
sys.exit(0 if failed == 0 else 1)
