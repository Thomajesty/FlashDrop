# -*- coding: utf-8 -*-
"""v1.18.18 Android UI 静态断言 —— 设备备注 / 消息搜索 / retrying-paused 文案

与 verify_v11815 的双端审计套路一致：读 Java 源码做结构断言。
运行：python windows/tests/verify_v11818_android_ui.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT2 = os.path.dirname(os.path.dirname(HERE))
AND = os.path.join(HERE, "..", "..", "android", "app", "src", "main",
                   "java", "com", "flashdrop", "app")

FAILS = []
N = 0


def ck(name, cond, extra=""):
    global N
    N += 1
    if not cond:
        FAILS.append(f"{name} | {extra}")
    print(("  ok  " if cond else " FAIL ") + name +
          ((" | " + str(extra)) if extra and not cond else ""))


def rd(name):
    with open(os.path.join(AND, name), encoding="utf-8") as f:
        return f.read()


def main():
    print("=" * 68)
    print("v1.18.18 Android UI 静态断言")
    print("=" * 68)

    ma = rd("MainActivity.java")
    prefs = rd("Prefs.java")
    node = rd("FlashNode.java")
    with open(os.path.join(ROOT2, "android", "app", "src", "main", "res",
                            "layout", "activity_main.xml"),
              encoding="utf-8") as f:
        xml = f.read()

    # ★ v1.18.25：sel_bar 片段（从 id 到多选操作栏注释之前，含整行闭合标签）
    sb = xml[xml.index('android:id="@+id/sel_bar"'):
             xml.index("多选操作栏")]

    # ---- 设备备注 ----
    print("\n[设备备注]")
    ck("displayNameOf 存在且备注优先",
       "displayNameOf" in ma and "getAlias(pid)" in ma)
    ck("在线设备标签走备注",
       'spinLabels.add(displayNameOf(id, p.optString("name")))' in ma)
    ck("离线设备标签走备注",
       'spinLabels.add(displayNameOf(o.optString("id"),' in ma)
    # ★ v1.18.20 演进：恢复原生 Spinner 下拉（用户明确要求回到原交互）。
    #   v1.18.18 "下拉点击没反应"的根因（下拉行根视图挂长按）已在 v1.18.19
    #   撤掉，下拉行触摸链路已纯净；v1.18.19 的对话框方案保留代码不挂接。
    ck("下拉行不再挂长按（v1.18.19 修复保持）",
       "showPeerActions(delId, delName)" not in ma)
    ck("不再拦截 Spinner 触摸（原生下拉恢复）",
       "targetSpinner.setOnTouchListener" not in ma)
    ck("设备选择对话框代码保留（备用，不挂接）",
       "private void showDevicePicker()" in ma)
    ck("备注入口在收起态选择器长按",
       "showPeerActions(pid, safeNameOf(pid))" in ma)
    # ---- v1.18.21：微信式内联搜索（不再弹窗）----
    ck("搜索入口走 🔍搜索 统一入口（onSearchClick）",
       "private void toggleSearchBar()" in ma
       and "btnRescan.setOnClickListener(v -> onSearchClick());" in ma
       and "private void onSearchClick()" in ma)
    ck("搜索语义：搜当前设备 / 搜全局 都在（runSearch false/true）",
       "runSearch(false)" in ma and "runSearch(true)" in ma)
    # ★ v1.18.25：「搜全局」不再是独立按钮，由「删除」按钮原地形变而来
    ck("删除按钮按模式分流：设备态删会话 / 搜索态搜全局",
       "if (searchMode) runSearch(true);" in ma
       and "else showDeletePicker();" in ma)
    ck("结果内联显示在会话界面（search_result_list）",
       "searchResultList" in ma
       and "searchResultList.setVisibility(View.VISIBLE)" in ma)
    ck("结果点击跳转到该设备并定位记录（locateMsg）",
       "private void locateMsg(String mid)" in ma
       and "onViewPeerChanged(pid);" in ma)
    ck("搜索结果行含设备名+方向+时间",
       'who + " · " + dir + " · " + when' in ma)
    ck("不再有搜索弹窗（showSearchDialog 已移除）",
       "showSearchDialog" not in ma)
    ck("设备选择对话框的搜索行已移除",
       '"__search__"' not in ma)
    ck("顶栏搜索按钮用 ic_search 图标（XML）",
       "@drawable/ic_search" in xml)
    # ★ v1.18.22：搜索控件移入 sel_bar 原地切换，不再有独立 search_bar
    # ★ v1.18.23：独立「搜索」按钮移除，🔍 变为图标+文字；删除与 🔍 对调
    ck("搜索控件在 sel_bar 内（search_input/删除形变/🔍搜索）",
       "@+id/sel_bar" in xml
       and "@+id/search_input" in xml
       and "@+id/btn_delete" in xml
       and "@+id/btn_rescan" in xml
       and "@+id/search_result_list" in xml)
    ck("独立 search_bar / btn_search_global 已移除（搜全局由删除形变而来）",
       "@+id/search_bar" not in xml and "@+id/btn_search_global" not in xml
       and "btn_search_global" not in ma)
    ck("独立 btn_search_here 已移除（并入 🔍搜索）",
       "btn_search_here" not in ma and "btn_search_here" not in xml)
    ck("🔍 按钮是图标+文字（ic_search_btn + tv_search_label）",
       "@+id/ic_search_btn" in xml and "@+id/tv_search_label" in xml
       and 'android:text="搜索"' in xml)
    ck("删除排在 🔍搜索 之前（对调，降低误触）",
       xml.index("@+id/btn_delete") < xml.index("@+id/btn_rescan"))
    # ---- v1.18.24：搜索结果底色（用户反馈"黑色文字 + 透明背景"）----
    ck("搜索结果行有不透明底色（theme.card）",
       "row.setBackgroundColor(theme.card)" in ma)
    ck("搜索结果列表有不透明底色（theme.bg）",
       "searchResultList.setBackgroundColor(theme.bg)" in ma)
    ck("搜索结果分隔线跟随主题（不再写死 #2E3138）",
       "searchResultList.setDivider(" in ma and "theme.border" in ma)
    # ---- v1.18.24：下拉行残留 ↻ 吃掉 item 点击（点不动/切不过去）----
    ck("下拉行无论有无记录都先清空 ✕ 槽位（修复点不动）",
       "xSlot.removeAllViews();" in ma
       and "if (!hasHistory) return row;" in ma
       and ma.index("xSlot.removeAllViews();")
       < ma.index("if (!hasHistory) return row;"))
    ck("无 id 的脏 peer 不入设备列表（避免幽灵行）",
       "if (id == null || id.isEmpty()) continue;" in ma)
    ck("toggleSearchBar 改为原地形变（applySearchF 逐帧驱动）",
       "private void applySearchF(float f)" in ma
       and "private void finishSearchToggle()" in ma
       and "searchAnim.addUpdateListener(" in ma)
    # ---- v1.18.25：设备态/搜索态原地形变，消除切换跳动 ----
    ck("sel_bar 行高固定 41dp（两种模式行高一致 → 不上下跳动）",
       'android:layout_height="41dp"' in sb)
    ck("旧跳动源 34dp 搜索框已消除（高度统一 32dp）",
       'android:layout_height="34dp"' not in xml)
    ck("Spinner 与搜索框共用 FrameLayout 槽位（显隐不重排行）",
       "@+id/device_search_slot" in sb
       and "@+id/target_spinner" in sb
       and "@+id/search_input" in sb
       and sb.index("@+id/target_spinner") > sb.index("@+id/device_search_slot")
       and sb.index("@+id/search_input") > sb.index("@+id/target_spinner")
       and sb.index("@+id/search_input") < sb.index("</FrameLayout>"))
    ck("Spinner 不再自带 weight（weight 上移到槽位，宽度恒定）",
       re.search(r'@\+id/target_spinner[\s\S]{0,200}?android:layout_weight', sb)
       is None)
    ck("🔍搜索 无 weight 且在行末（右边缘被 padding 锚定 → 不跳动）",
       "android:layout_weight" not in sb[sb.index("@+id/btn_rescan"):])
    ck("形变：设备选择框向右推进 + 淡出",
       "targetSpinner.setTranslationX(f * slide)" in ma
       and "targetSpinner.setAlpha(1f - f)" in ma)
    ck("形变：搜索框自左滑入 + 淡入",
       "searchInput.setTranslationX(-(1f - f) * slide)" in ma
       and "searchInput.setAlpha(f)" in ma)
    ck("形变：删除按钮宽度向左延长 + 字色渐变 + 过半换字",
       "setChildWidth(btnDelete," in ma
       and "ArgbEvaluator" in ma
       and 'btnDelete.setText(global ? "搜全局" : "删除")' in ma)
    # ★ v1.18.26：在线数**只淡出、不再压宽度** —— 旧版压宽度会把它 ellipsize 成
    #   "在线…"、"在…"，动画中途文字抽搐（用户实测"非常不自然"）。
    #   数学上不需要压：槽位是 weight=1，按钮变宽时槽位自己让出空间，
    #   按钮左缘照样向左延长；在线数保持原宽时显隐都不挪动右侧任何控件。
    ck("在线数只做淡出（不再压宽度 → 避免 ellipsize 抽搐）",
       "onlineLabel.setAlpha(1f - Math.min(1f, f / 0.35f))" in ma
       and "setChildWidth(onlineLabel," not in ma
       and "onlineNatW" not in ma)
    ck("形变尊重动效开关（关闭时瞬时到位）",
       "FdAnim.on(this)" in ma)
    ck("快速连点安全：旧动画先摘回调再 cancel",
       "searchAnim.removeAllListeners()" in ma)
    ck("搜索结果淡入（与形变动效同语言）",
       "FdAnim.fadeIn(searchResultList" in ma)
    # ★ v1.18.26：形变流畅度（用户反馈"不自然 + 卡顿 + 折成两排"）----
    m_del = re.search(r'<Button[^>]*@\+id/btn_delete[\s\S]*?>', sb)
    del_attr = m_del.group(0) if m_del else ""
    ck("★ 删除按钮锁死单行（形变中途 3 字不会折成两排）",
       'android:singleLine="true"' in del_attr
       and 'android:maxLines="1"' in del_attr)
    ck("★ 宽度在换字前就长到位（SWAP_F 之前完成，字放得下不折行）",
       "SWAP_F" in ma and "float wf = Math.min(1f, f / SWAP_F)" in ma)
    ck("★ 文字交叉淡入淡出（换字发生在最淡的一瞬，不是硬跳）",
       "float ta = Math.min(1f, Math.abs(f - SWAP_F) / SWAP_F)" in ma
       and "btnDelete.setTextColor((col & 0x00FFFFFF)" in ma)
    ck("★ 字色在文字最淡时过渡（f=0.3→0.7，看不出跳变）",
       "float cf = Math.max(0f, Math.min(1f, (f - 0.3f) / 0.4f))" in ma)
    ck("★ 焦点与软键盘推迟到形变结束（不与动画抢帧 → 不卡）",
       "searchInput.requestFocus()" in ma
       and ma.index("searchInput.requestFocus()")
       > ma.index("private void finishSearchToggle()")
       and "imm.showSoftInput(searchInput," in ma)
    ck("★ 时长走 FdAnim 标准（进入 220ms / 退出 180ms）",
       "FdAnim.DURATION_ENTER" in ma and "FdAnim.DURATION_EXIT" in ma)
    # ---- v1.18.26：状态栏可见（用户反馈"页面顶部手机导航栏不显示"）----
    ck("状态栏底色跟随主题（浅色=bar 白 / 深色=#15171B）",
       "getWindow().setStatusBarColor(theme.dark ? 0xFF15171B : theme.bar)"
       in ma)
    ck("★ 状态栏图标明暗按主题动态切（浅底→深色图标，白底白字时看不见）",
       "SYSTEM_UI_FLAG_LIGHT_STATUS_BAR" in ma
       and "sf |= View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR" in ma
       and "sf &= ~View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR" in ma
       and "Build.VERSION.SDK_INT >= Build.VERSION_CODES.M" in ma)
    # ---- v1.18.20 / v1.18.22：框内转圈 + 顶栏搜索 ----
    ck("设备框内刷新转圈（收起态 ✕ 槽位，矢量图标）",
       "R.drawable.ic_rescan" in ma and "scanSpinning" in ma)
    ck("刷新图标绕几何中心旋转（ScaleType.CENTER）",
       "ScaleType.CENTER" in ma and "rotationBy" in ma)
    ck("转圈点击触发深度扫描",
       "FlashApp.get().node().rescan(true)" in ma
       and "正在扫描附近设备" in ma)
    # 已由 v1.18.21 的 toggleSearchBar 断言覆盖
    ck("备注编辑对话框存在", "showAliasEditor" in ma
       and 'FdDialog.custom(this, "设备备注"' in ma)
    ck("备注写入 Prefs.setAlias", "Prefs.get(this).setAlias(pid, v)" in ma)
    ck("备注后刷新 spinner 与聊天",
       "rebuildSpinner();          // 立即反映到选择框" in ma)
    ck("删除会话同时清备注（不留孤儿）",
       'try { Prefs.get(MainActivity.this).setAlias(pid, ""); }' in ma)
    ck("Prefs.peerAliases 配置存在",
       '"peer_aliases"' in prefs and "setAlias" in prefs and "getAlias" in prefs)
    ck("Prefs 清除走重建写法（测试桩无 JSONObject.remove）",
       "out.put(k, old.optString(k" in prefs)
    ck("FlashNode.displayName 供事件层使用",
       "public String displayName(String peerId)" in node)

    # ---- 消息搜索 ----
    print("\n[消息搜索]")
    # ★ v1.18.21 演进：btnPending 复用方案废弃（布局 0dp 隐藏），
    #   搜索入口 = 顶栏 ImageButton(ic_search) + 会话内联搜索行
    ck("btnPending 不再承担搜索（隐藏占位）",
       'btnPending.setText("🔍 搜索")' not in ma)
    ck("refreshPendingBtn 保持常显",
       "btnPending.setVisibility(View.VISIBLE)" in ma)
    ck("搜索扫描全部历史（loadHistory 2000 条）",
       'FdUtil.loadHistory(this, pid, 2000)' in ma)
    ck("文本与文件名都参与匹配",
       'o.optString("text", "")' in ma and 'o.optString("file", "")' in ma)
    ck("结果可跳转会话并定位（locateMsg）",
       "jumpToPeer(" in ma or "locateMsg(" in ma)
    ck("无命中给空态提示", "没有找到与「" in ma)
    ck("搜索结果区分方向", '"我发出"' in ma and '"对方发来"' in ma)
    ck("snippet 截取命中附近", "snippetOf" in ma)

    # ---- retrying / paused 文案 ----
    print("\n[状态文案]")
    ck("Msg 有 attempt/haveChunks/totalChunks",
       "int attempt, haveChunks, totalChunks;" in ma)
    ck("recv 事件消费断点字段",
       'm.attempt = e.optInt("attempt");' in ma
       and 'm.haveChunks = e.optInt("have_chunks");' in ma
       and 'm.totalChunks = e.optInt("total_chunks");' in ma)
    ck("文件气泡 retrying 文案", 'case "retrying":' in ma
       and "重试中（第 \" + m.attempt + \" 次）" in ma)
    ck("文件气泡 paused 文案（含块进度）",
       '"已暂停，可续传（" + m.haveChunks + "/" + m.totalChunks + " 块）"' in ma)
    ck("文本气泡 retrying 文案", "重试中（第 \" + m.attempt + \" 次）" in ma)

    # ---- 待发面板增强 ----
    print("\n[待发面板]")
    app = rd("FlashApp.java")
    ck("PendingSend 有 last_error/attempt",
       "last_error" in app or "lastError" in app,
       "（FlashApp 文件条目确认式补发为下一轮工作，此处仅检查不强制）")

    print("\n" + "=" * 68)
    print(f"结果：{N - len(FAILS)}/{N} 通过")
    if FAILS:
        print("失败项：")
        for f in FAILS:
            print("  - " + f)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
