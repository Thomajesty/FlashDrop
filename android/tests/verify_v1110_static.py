# -*- coding: utf-8 -*-
"""
FlashDrop v1.11.0 专项校验（直接扫真实 .java 源码，不依赖设备）

覆盖用户提的 4 个问题：

1. 连接好的情况下 电脑发送的文字 安卓端收不到
   根因：FlashNode.registerConn / node.py:_register_conn 的连接去重逻辑写成
        `if (newPref && !oldPref) {替换} else {closeConn(conn); return false;}`
        —— 同方向的两条连接 newPref == oldPref，走进 else 把**新来的**这条丢掉。
        对端重连 / 双向同时互连时，真实活着的恰恰是新连接，丢掉它 =
        这条链路上后续所有 TEXT 都被对端读不到（对端 _wait_conn 拿到的正是被丢弃那条），
        表现为"已连接（心跳正常）但收不到文字"，而文件走重试/另一条链路还能收到。
   修复：方向不同 → 仍按偏好规则；方向相同 → 新连接接管旧连接。
   本脚本锁死：两端都必须有"同方向新接管旧"分支，且不能再出现"同方向直接丢弃"。

2. 图片打开不能放大预览（要和微信一样）
   → ImageViewerActivity：ScaleGestureDetector 捏合 1x~5x、以双指中心为锚点、
     双击 2.5x、放大后拖动且 clampTrans 限制边缘、垂直下拉关闭。

3. 图片不能长按保存删除 + 底部保存/转发按钮布局不好看
   → 长按 420ms 计时器弹「保存到相册 / 转发 / 删除」，删除带二次确认且**只删这一张**；
   → 底部改为 weight=1 均分的竖排卡片（图标在上、文字在下），严格等宽等高。
   ★ 特别锁死：查看器里不得再出现 deleteSavedFiles(...)（那是"按设备删整个文件夹"，
     在查看器里点一次会把该设备所有图片删光，属严重误删）。

4. 安卓端动画特效基本上没有
   → FdAnim 基础设施 + 主界面/设置页/查看器实际调用点；
   ★ 锁死：动效开关必须读写同一份 Prefs（早前 FdAnim 另开 "motion" 文件，
     设置页写 flashdrop_prefs、这里读 motion，开关永远读不到 = 永远开）。
"""
import os
import re
import sys

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SRC = os.path.join(BASE, "app", "src", "main", "java", "com", "flashdrop", "app")
MAIN = os.path.join(SRC, "MainActivity.java")
SETT = os.path.join(SRC, "SettingsActivity.java")
NODE = os.path.join(SRC, "FlashNode.java")
ANIM = os.path.join(SRC, "FdAnim.java")
VIEW = os.path.join(SRC, "ImageViewerActivity.java")
PREFS = os.path.join(SRC, "Prefs.java")
FDU = os.path.join(SRC, "FdUtil.java")
MANIFEST = os.path.join(BASE, "app", "src", "main", "AndroidManifest.xml")
NODE_PY = os.path.join(BASE, "..", "windows", "app", "node.py")

_pass = 0
_fail = 0


def check(name, ok, detail=""):
    global _pass, _fail
    if ok:
        _pass += 1
        print("  PASS  " + name)
    else:
        _fail += 1
        print("  FAIL  " + name + ("   " + detail if detail else ""))


def sec(t):
    print("\n[" + t + "]")


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def strip_comments(src):
    """
    剥离注释，避免把"根因说明注释"误判成真实代码。

    用逐字符状态机（不是逐行 split），否则跨行块注释 /* ... */
    只会吃掉第一行，剩下的 " * ..." 行会被当成代码 ——
    本轮就踩了这个坑：注释里写的 "早前这里调的是 FdUtil.deleteSavedFiles(...)"
    被误判成"代码里还在调 deleteSavedFiles"，产生假失败。
    """
    out = []
    i, n = 0, len(src)
    in_block = False
    in_line = False
    in_str = False
    in_chr = False
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if in_block:
            if c == "*" and nxt == "/":
                in_block = False
                i += 2
                # 保留换行，避免行号错位
                continue
            if c == "\n":
                out.append(c)
            i += 1
            continue
        if in_line:
            if c == "\n":
                in_line = False
                out.append(c)
            i += 1
            continue
        if in_str:
            out.append(c)
            if c == "\\" and nxt:
                out.append(nxt)
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if in_chr:
            out.append(c)
            if c == "\\" and nxt:
                out.append(nxt)
                i += 2
                continue
            if c == "'":
                in_chr = False
            i += 1
            continue
        # 普通代码区
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


def body_of(src, sig):
    """取方法体：从 sig 起，到大括号配平为止"""
    i = src.find(sig)
    if i < 0:
        return None
    j = src.find("{", i)
    if j < 0:
        return None
    d = 0
    for k in range(j, len(src)):
        if src[k] == "{":
            d += 1
        elif src[k] == "}":
            d -= 1
            if d == 0:
                return src[i:k + 1]
    return None


def py_body_of(src, sig):
    """
    按**缩进**提取 Python 方法体（不能用大括号配平）。

    原因：Python 里 dict 字面量 {"a": 1} 的大括号会干扰配平计数，
    而 lambda / 字典嵌套让配平在中途就"归零"，只截到方法前半段
    （本轮就踩了：_register_conn 只取到 2173 字符，恰好丢掉"同方向新接管旧"分支）。
    """
    lines = src.split("\n")
    start = None
    for i, ln in enumerate(lines):
        if sig in ln:
            start = i
            break
    if start is None:
        return None
    # 方法体的基准缩进 = 冒号后的内容缩进；本方法体第一行是下一行
    body = []
    base = None
    for ln in lines[start + 1:]:
        if not ln.strip():
            body.append("")
            continue
        ind = len(ln) - len(ln.lstrip())
        if base is None:
            base = ind
        if ind < base:
            break
        body.append(ln)
    return "\n".join(body)


def main():
    mc_raw = read(MAIN)
    sc_raw = read(SETT)
    nc_raw = read(NODE)
    an_raw = read(ANIM)
    vw_raw = read(VIEW)
    pr_raw = read(PREFS)
    mf_raw = read(MANIFEST)
    np_raw = read(NODE_PY)

    mc = strip_comments(mc_raw)
    sc = strip_comments(sc_raw)
    nc = strip_comments(nc_raw)
    an = strip_comments(an_raw)
    vw = strip_comments(vw_raw)
    pr = strip_comments(pr_raw)
    npc = strip_comments(np_raw)

    # ==================================================================
    sec("1. 问题1 根因修复：同方向重复连接不再被丢弃（Android）")

    rc = body_of(nc, "boolean registerConn(Conn conn, JSONObject hello)")
    check("registerConn 存在", rc is not None)
    if rc:
        # 必须有 newPref != oldPref 的分支（方向不同）
        check("按 newPref != oldPref 区分方向", "newPref != oldPref" in rc)
        # 同方向分支必须"新接管旧"
        check("同方向有新接管旧分支",
              "已更新为最新链路" in rc or "更新为最新" in rc)
        # 关键：不能再出现"条件不满足就 closeConn + return false"的一刀切
        # 允许只在 oldPref 更优时丢弃（即 newPref != oldPref 且 !newPref）
        bad = re.search(r"if\s*\(\s*newPref\s*&&\s*!oldPref\s*\)\s*\{[^}]*\}\s*else\s*\{",
                        rc)
        check("不再是一刀切 if(newPref && !oldPref) else closeConn",
              bad is None,
              "仍存在旧的一刀切去重结构")

    rl = body_of(nc, "private void readerLoop(")
    check("readerLoop 存在", rl is not None)
    if rl:
        check("readerLoop 不再静默吞异常",
              "catch (Exception ignored)" not in rl)
        check("readerLoop 异常有日志留痕",
              "的消息处理异常" in rl)

    # ==================================================================
    sec("1b. 问题1 根因修复：Windows 端同步（两端规则必须一致）")

    prc = py_body_of(npc, "async def _register_conn(")
    check("_register_conn 存在", prc is not None)
    if prc:
        check("Windows 端也按 new_pref != old_pref 区分方向",
              "new_pref != old_pref" in prc)
        check("Windows 端同方向有新接管旧分支",
              "已更新为最新链路" in prc or "更新为最新" in prc)
        badpy = re.search(r"if\s+new_pref\s+and\s+not\s+old_pref\s*:\s*\n(?:.*\n){0,6}?\s*else\s*:",
                          prc)
        check("Windows 端不再是一刀切去重", badpy is None,
              "仍存在旧的一刀切去重结构")

    # ==================================================================
    sec("2. 问题2 图片全屏预览：捏合缩放 / 双击 / 下拉关闭（微信式）")

    check("ImageViewerActivity 文件存在", os.path.exists(VIEW))
    check("已在 Manifest 注册",
          "ImageViewerActivity" in mf_raw)
    check("注册为全屏主题",
          re.search(r'\.ImageViewerActivity[\s\S]{0,200}Fullscreen', mf_raw)
          is not None)
    check("scaleType 改为 MATRIX（才能真正缩放）",
          "setScaleType(ImageView.ScaleType.MATRIX)" in vw)
    check("使用 ScaleGestureDetector（捏合）",
          "ScaleGestureDetector" in vw)
    check("缩放下限 MIN_SCALE=1.0", re.search(r"MIN_SCALE\s*=\s*1\.0f", vw) is not None)
    check("缩放上限 MAX_SCALE=5.0", re.search(r"MAX_SCALE\s*=\s*5\.0f", vw) is not None)
    check("缩放被 clampScale 限制在区间内",
          "clampScale" in vw and "Math.max(MIN_SCALE" in vw)
    check("以双指中心为锚点缩放（getFocusX/Y）",
          "getFocusX()" in vw and "getFocusY()" in vw)
    check("双击放大/还原 toggleZoomAt", "toggleZoomAt" in vw)
    check("双击目标为 2.5x", re.search(r"target\s*=\s*2\.5f", vw) is not None)
    check("放大后单指拖动", "transX += dx" in vw and "transY += dy" in vw)
    check("拖动范围被 clampTrans 限制（边缘不飞出屏）",
          "clampTrans" in vw and "maxX" in vw)
    check("垂直下拉关闭", "applyDismissOffset" in vw and "DISMISS_DISTANCE" in vw)
    check("下拉关闭有速度阈值", "DISMISS_VELOCITY" in vw and "VelocityTracker" in vw)
    check("未放大才允许下拉关闭（放大时优先拖图）",
          re.search(r"scale\s*<=\s*1\.01f", vw) is not None)
    check("单击切换顶栏/底栏显隐", "onSingleTap" in vw)
    check("缩放有补间动画（不是瞬变）", "animateTo" in vw and "ValueAnimator" in vw)
    check("多图计数显示（3/12）",
          re.search(r'pageView\.setText', vw) is not None)

    # ==================================================================
    sec("3a. 问题3 长按图片：保存 / 转发 / 删除")

    check("长按菜单方法存在", "onLongPressImage" in vw)
    check("长按用计时器实现（onTouch 吃掉了事件，不能靠 LongClickListener）",
          "postDelayed(longPressRunnable" in vw)
    check("长按阈值 420ms", re.search(r"postDelayed\(longPressRunnable,\s*420\)", vw)
          is not None)
    check("移动超过阈值取消长按",
          re.search(r"cancelLongPress\(\)", vw) is not None)
    check("长按有触觉反馈", "LONG_PRESS" in vw)
    check("菜单三项：保存到相册/转发/删除",
          '"保存到相册"' in vw and '"转发"' in vw and '"删除"' in vw)
    check("删除走二次确认", "confirmDelete" in vw and "setPositiveButton(\"删除\"" in vw)
    check("onDestroy 清理长按回调（防泄漏）",
          re.search(r"onDestroy\(\)[\s\S]{0,200}cancelLongPress", vw) is not None)

    # ---- ★ 关键：查看器里绝不能出现"按设备删整个文件夹" ----
    check("★ 查看器不再调 deleteSavedFiles（会误删该设备全部图片）",
          "deleteSavedFiles" not in vw,
          "仍存在按文件夹批量删除的调用 —— 属于严重误删")
    check("只删当前这一张（deleteFileOf）", "deleteFileOf" in vw)
    check("删除走 m.open / m.path 精确定位",
          "m.open" in vw and "m.path" in vw)
    check("删除结果回传主界面（del_key）", '"del_key"' in vw)
    check("用 setResult 回传", "setResult(RESULT_OK" in vw)
    check("keyOfMsg 与主界面 keyOf 口径一致（ts|midOrTid|dir|kind）",
          re.search(r"keyOfMsg[\s\S]{0,400}ts\s*\+.*mid[\s\S]{0,120}dir[\s\S]{0,80}kind",
                    vw) is not None)
    check("主界面 keyOf 仍是同一口径",
          re.search(r"keyOf\(Msg\s+\w+\)\s*\{[\s\S]{0,200}ts\s*\+", mc) is not None)
    check("主界面有 REQ_VIEWER 回传码", "REQ_VIEWER" in mc)
    check("主界面 onActivityResult 处理 del_key",
          re.search(r"REQ_VIEWER[\s\S]{0,300}del_key", mc) is not None)
    check("主界面 removeMsgByKey 走 detachMsgs+purgeMsgs（与批量删除同路径）",
          body_of(mc, "private void removeMsgByKey(") is not None)
    rmk = body_of(mc, "private void removeMsgByKey(")
    if rmk:
        check("removeMsgByKey 调 detachMsgs", "detachMsgs" in rmk)
        check("removeMsgByKey 调 purgeMsgs", "purgeMsgs" in rmk)
        check("removeMsgByKey 立即 refreshChat（界面同步）", "refreshChat" in rmk)
    check("查看器用 startActivityForResult 启动（需要回传 key）",
          "startActivityForResult" in vw)

    # ==================================================================
    sec("3b. 问题3 底部保存/转发按钮布局：等宽竖排卡片")

    check("有 actionCard 卡片构建方法", "actionCard" in vw)
    ac = body_of(vw, "private View actionCard(")
    check("actionCard 存在", ac is not None)
    if ac:
        check("卡片竖排（图标在上、文字在下）",
              "VERTICAL" in ac and "dp(24), dp(24)" in ac)
        check("卡片圆角 12dp", re.search(r"round\([^,]+,\s*12,", ac) is not None)
        check("卡片等宽（weight=1 均分）",
              re.search(r"new\s+LinearLayout\.LayoutParams\(0,[^,]+,\s*1f\)", ac)
              is not None)
        check("卡片有按压反馈", "pressDown" in ac and "pressUp" in ac)
    check("底部栏两个动作：保存到相册 / 转发",
          re.search(r'actionCard\(R\.drawable\.ic_save_down,\s*"保存到相册"', vw)
          is not None
          and re.search(r'actionCard\(R\.drawable\.ic_share,\s*"转发"', vw) is not None)
    check("底部栏避让手势条（safeBottom）", "safeBottom" in vw)
    check("底部栏固定高度（不是 WRAP_CONTENT 拼贴）",
          re.search(r"bottomRow[\s\S]{0,200}dp\(60\)", vw) is not None)
    check("旧做法 WRAP_CONTENT 横向拼贴已移除",
          not re.search(r'bar\.addView\(btnSave\)', mc),
          "MainActivity 仍残留旧的 WRAP_CONTENT 拼贴底栏")

    # 气泡长按
    check("气泡接上长按（进查看器后可长按保存/删除）",
          "setOnLongClickListener" in mc)
    # v1.12.0 更新：图片缩略图长按改为弹 showMsgMenu（用户要求聊天页图片
    # 长按可多选/保存/删除），单击仍进查看器；openImageViewer 调用仍存在于
    # 缩略图 click 与文字气泡长按中，断言随之更新
    check("缩略图单击仍调 openImageViewer",
          re.search(r'setOnClickListener\(v -> openImageViewer\(m\)\)', mc)
          is not None)
    check("缩略图长按改弹 showMsgMenu（v1.12.0）",
          re.search(r'setOnLongClickListener\([\s\S]{0,320}showMsgMenu\(m, v\)', mc)
          is not None)
    ov = body_of(mc, "private void openImageViewer(")
    check("openImageViewer 存在", ov is not None)
    if ov:
        check("openImageViewer 改走 ImageViewerActivity.start",
              "ImageViewerActivity.start" in ov)
        check("传的是当前视图的全部图片（可左右切换）",
              "viewMsgs" in ov and "imgs.add(x)" in ov)
    check("旧 Dialog 版查看器已移除（不再 new Dialog + 固定 FIT_CENTER）",
          "全屏图片查看器：原图显示" not in mc)
    check("旧 circleIconBtn 已清理（无引用）",
          "circleIconBtn" not in mc)

    # ==================================================================
    sec("4. 问题4 过渡动画：基础设施 + 实际调用点")

    check("FdAnim 文件存在", os.path.exists(ANIM))
    check("定义了 Material 时长常量",
          "DURATION_FAST" in an and "DURATION_ENTER" in an
          and "DURATION_EXIT" in an and "DURATION_MOVE" in an)
    check("使用 PathInterpolator 曲线（非线性匀速）",
          "PathInterpolator" in an and "CURVE_DECELERATE" in an
          and "CURVE_ACCELERATE" in an)
    check("尊重系统动画关闭（ANIMATOR_DURATION_SCALE）",
          "ANIMATOR_DURATION_SCALE" in an)
    check("提供 activityEnter", "activityEnter" in an)
    check("提供 activityExit", "activityExit" in an)
    check("提供 bubbleEnter", "bubbleEnter" in an)
    check("提供 pressDown/pressUp", "pressDown" in an and "pressUp" in an)
    check("提供 slideInFromTop/FromBottom",
          "slideInFromTop" in an and "slideInFromBottom" in an)
    check("提供 fadeIn/fadeOut", "fadeIn" in an and "fadeOut" in an)

    # ---- ★ 锁死：动效开关必须读同一份 Prefs ----
    check("★ FdAnim 不再另开 \"motion\" 独立文件",
          '"motion"' not in an,
          "仍读独立 motion 文件 → 与设置页写入的 flashdrop_prefs 不是一份，开关永远无效")
    check("★ FdAnim 通过 Prefs.animations() 读开关",
          "prefOf(ctx).animations()" in an)
    check("Prefs 有 animations() / setAnimations()",
          "animations()" in pr and "setAnimations" in pr)
    check("setAnimations 会清 FdAnim 缓存（即时生效）",
          re.search(r"setAnimations\([\s\S]{0,300}invalidatePrefCache", pr)
          is not None)
    check("FdAnim 提供缓存失效方法", "invalidatePrefCache" in an)
    check("统一入口 on(ctx)：系统允许 && 用户未关",
          re.search(r"on\(Context\s+\w+\)[\s\S]{0,200}!enabled", an) is not None)
    # 所有动效方法都要判开关
    for m in ["pressDown", "pressUp", "fadeIn", "fadeOut",
              "slideInFromTop", "slideInFromBottom", "bubbleEnter"]:
        b = body_of(an, "public static void " + m + "(")
        check("FdAnim.%s 判了开关" % m, b is not None and "on(" in b)

    # ---- 实际调用点 ----
    check("主界面接入进出场动效", "FdAnim.activityEnter" in mc)
    check("主界面气泡入场动效", "FdAnim.bubbleEnter" in mc)
    be = body_of(mc, "private void bind(")
    check("气泡入场只播一次（appended 标记，滚动不闪）",
          "m.appended" in mc and "m.appended = false" in mc)
    check("主界面按钮按压反馈", "pressable" in mc and "FdAnim.pressDown" in mc)
    check("底部面板滑入", "FdAnim.slideInFromBottom" in mc)
    hp = body_of(mc, "private void hidePanel()")
    check("底部面板滑出（动画走完再隐藏）",
          hp is not None and "FdAnim.CURVE_ACCELERATE" in hp
          and "withEndAction" in hp)
    check("设置页接入进入动效", "FdAnim.activityEnter" in sc)
    check("设置页接入退出动效", "FdAnim.activityExit" in sc)
    check("设置页有动效开关控件", "animSwitch" in sc)
    check("设置页动效开关文案说明用途",
          "启用界面动效" in sc)
    check("设置页 onSave 持久化动效开关",
          re.search(r"setAnimations\(", sc) is not None)
    check("查看器接入进入动效（淡入 + 顶栏下滑 + 底栏上滑）",
          "FdAnim.slideInFromTop" in vw and "FdAnim.slideInFromBottom" in vw)
    check("查看器接入退出动效（淡出下移再 finish）",
          "closeWithAnim" in vw and "CURVE_ACCELERATE" in vw)
    check("查看器 finish() 复位（防复用残留）",
          re.search(r"public void finish\(\)[\s\S]{0,300}setTranslationY", vw)
          is not None)
    check("查看器保存成功有微反馈", "withEndAction" in vw)

    # ==================================================================
    sec("5. v1.10.1 / v1.10.0 既有能力未被破坏")

    check("v1.10.1 设置页数据清理仍在",
          body_of(sc, "private void onDataClean()") is not None)
    check("v1.10.1 doScopedDelete 仍在",
          body_of(mc, "private void doScopedDelete(") is not None)
    check("v1.10.1 detachMsgs 仍在", body_of(mc, "private List<Msg> detachMsgs(") is not None)
    dp = body_of(mc, "private List<Msg> detachMsgs(")
    if dp:
        check("detachMsgs 仍清三个索引",
              "byMid" in dp and "byTidIn" in dp and "byTidOut" in dp)
    check("v1.10.0 删除弹窗仍在",
          body_of(mc, "private void showDeletePicker()") is not None)
    check("v1.10.0 CheckBox[3] 崩溃修复仍在",
          re.search(r"CheckBox\[\]\s*checks\s*=\s*new\s+CheckBox\[3\]", mc) is not None)
    check("待发队列仍在", "pendingSends" in pr)
    check("崩溃捕获仍在（CrashTrap）",
          os.path.exists(os.path.join(SRC, "CrashTrap.java")))
    check("FdUtil.dp 仍存在（动效基础设施依赖）",
          re.search(r"public static int dp\(Context", read(FDU)) is not None)

    # ==================================================================
    sec("6. 危险模式扫描（回归防护）")

    # 6.1 查看器里不得再有"忽略返回值的线程/异步删除"
    check("查看器删除在子线程执行（不卡 UI）", "new Thread(" in vw)
    # 6.2 startActivityForResult 后必须 return，避免继续走选文件的逻辑
    oar = body_of(mc, "protected void onActivityResult(")
    check("onActivityResult 对 REQ_VIEWER 提前 return",
          oar is not None and re.search(
              r"requestCode == REQ_VIEWER[\s\S]{0,400}return;", oar) is not None)
    # 6.3 查看器 onCreate 空列表必须兜底 finish，不能停在黑屏
    oc = body_of(vw, "protected void onCreate(")
    check("查看器无可读图片时直接 finish（不留黑屏）",
          oc is not None and "images.isEmpty()" in oc and "finish()" in oc)
    # 6.4 Intent 反序列化要判空（系统回收重建场景）
    check("查看器判空 getSerializableExtra",
          "getSerializableExtra" in vw and "!= null" in vw)
    # 6.5 长按计时器必须在 onDestroy 移除（防 Handler 泄漏）
    check("长按 Handler 泄漏防护", "onDestroy" in vw and "removeCallbacks" in vw)
    # 6.6 Msg 可序列化是删除回传的前提
    check("MainActivity.Msg 实现了 Serializable（传真实对象的前提）",
          re.search(r"class Msg implements java\.io\.Serializable", mc) is not None)
    check("Msg 有 serialVersionUID",
          re.search(r"serialVersionUID", mc) is not None)

    print("\n" + "=" * 62)
    print(" 通过 %d 项，失败 %d 项" % (_pass, _fail))
    print("=" * 62)
    if _fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
