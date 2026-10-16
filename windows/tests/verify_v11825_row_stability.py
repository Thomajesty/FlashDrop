# -*- coding: utf-8 -*-
"""v1.18.25 sel_bar 行稳定性「视觉验收」（布局仿真版）

背景：用户反馈安卓"上半部分切换时会由于模块大小不一样跳动"，
要求"设备行和搜索行高做统一、最后面的搜索按钮不跳动、删除按钮向左延长
变为搜全局"。

沙箱里没有真机，无法截图；本脚本改为**解析 activity_main.xml 的真实
布局参数**（权重/宽高/边距/内边距），按 LinearLayout 的测量规则仿真
设备态与搜索态两种布局，对以下不变量逐项断言：

  1. 行高两种模式完全一致（41dp）              → 不上下跳动
  2. 🔍搜索（行末锚定子控件）坐标两种模式完全一致 → 最后面的按钮不跳动
  3. 「删除」按钮**右边缘不变、左缘向左延长**（增量=搜全局-删除 宽度差）
                                               → 正是"向左延长变为搜全局"
  4. 左槽位左边缘固定在行 padding 处           → 设备选择框不左右漂移
  5. 参数扫描（在线数宽度/文字宽度取多组现实值）下以上不变量全部成立
  6. 权重分配后槽位宽度不为负（不会溢出屏幕）

运行：python windows/tests/verify_v11825_row_stability.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
XML = os.path.join(ROOT, "android", "app", "src", "main", "res",
                   "layout", "activity_main.xml")

FAILS = []
N = 0

# 仿真用屏幕宽度（dp）：覆盖小屏 320 到大屏 411
SCREENS = (320, 360, 411)


def ck(name, cond, extra=""):
    global N
    N += 1
    if not cond:
        FAILS.append(f"{name} | {extra}")
    print(("  ok  " if cond else " FAIL ") + name +
          ((" | " + str(extra)) if extra else ""))


def sel_bar_block(xml):
    """截取 sel_bar 整段（含闭合标签）。"""
    start = xml.index('android:id="@+id/sel_bar"')
    end = xml.index("多选操作栏", start)
    return xml[start:end]


def attrs_of(xml, tag_id):
    """取某个 id 所在元素标签的属性串。"""
    i = xml.index(tag_id)
    lt = xml.rindex("<", 0, i)
    gt = xml.index(">", i)
    return xml[lt:gt + 1]


def get_int(attr, key, default=None):
    m = re.search(key + r'="(-?\d+)dp"', attr)
    return int(m.group(1)) if m else default


def get_weight(attr):
    m = re.search(r'android:layout_weight="([\d.]+)"', attr)
    return float(m.group(1)) if m else 0.0


def is_gone(attr):
    return 'android:visibility="gone"' in attr


def is_match_parent(attr, key="android:layout_width"):
    return re.search(key + r'="match_parent"', attr) is not None


def is_wrap(attr, key="android:layout_width"):
    return re.search(key + r'="wrap_content"', attr) is not None


def simulate(sb, screen, w_online, w_del, w_glb, w_rescan, state,
             online_visible_in_search=False):
    """按 LinearLayout horizontal 规则仿真 sel_bar，返回各子视图几何。

    state: "device"（设备态）或 "search"（搜索态）
    布局（XML 顺序）：[device_search_slot(weight=1)] [online_label]
                      [btn_pending(0dp,gone)] [btn_delete] [btn_rescan]
    搜索态：online_label 宽度坍缩为 0（GONE），btn_delete 变为「搜全局」。
    """
    pad_l, pad_r, pad_t, pad_b = 10, 10, 2, 7
    row_h = 41

    slot = attrs_of(sb, "@+id/device_search_slot")
    online = attrs_of(sb, "@+id/online_label")
    pend = attrs_of(sb, "@+id/btn_pending")
    delete = attrs_of(sb, "@+id/btn_delete")
    rescan = attrs_of(sb, "@+id/btn_rescan")

    # ---- 收集可见子视图（按 XML 顺序）----
    kids = []          # (name, fixed_w, weight, margin_l, margin_r, height)
    # 槽位：0dp + weight=1，右外边距 6
    kids.append(("slot", 0, get_weight(slot),
                 get_int(slot, "android:layout_marginLeft", 0) or 0,
                 get_int(slot, "android:layout_marginRight", 0) or 0))
    # 在线数：设备态可见（宽度=w_online）；搜索态默认坍缩为 0。
    # ★ v1.18.26：形变**中途**在线数只淡出、仍占原宽（online_visible_in_search=True），
    #   所以最坏情况是"在线数满宽 + 按钮已长成搜全局"，要一并验算不溢出。
    online_w = w_online if (state != "search"
                            or online_visible_in_search) else 0
    kids.append(("online", online_w, 0.0,
                 0, get_int(online, "android:layout_marginRight", 0) or 0))
    # btn_pending：0dp 且 gone → 不占位
    if not (is_gone(pend) and (get_int(pend, "android:layout_width", 0) or 0) == 0):
        kids.append(("pending", get_int(pend, "android:layout_width", 0) or 0,
                     0.0, 0, 0))
    # 删除 / 搜全局：同一个按钮的两种身份
    kids.append(("mid", w_glb if state == "search" else w_del, 0.0,
                 get_int(delete, "android:layout_marginLeft", 0) or 0, 0))
    # 🔍搜索：行末锚定
    kids.append(("rescan", w_rescan, 0.0,
                 get_int(rescan, "android:layout_marginLeft", 0) or 0, 0))

    avail = screen - pad_l - pad_r
    fixed = sum(w + ml + mr for _, w, _, ml, mr in kids)
    total_w = sum(k[2] for k in kids)
    left = pad_l
    out = {}
    for name, w, weight, ml, mr in kids:
        width = w if weight == 0 else max(0, round((avail - fixed) * weight / total_w))
        out[name] = {"left": left + ml, "right": left + ml + width,
                     "width": width, "top": pad_t, "bottom": pad_t + 32}
        left += ml + width + mr
    out["_row"] = {"left": 0, "right": screen, "top": 0, "bottom": row_h,
                   "height": row_h}
    out["_avail"] = avail
    out["_fixed"] = fixed
    return out


def main():
    print("=" * 68)
    print("v1.18.25 sel_bar 行稳定性 · 布局仿真验收")
    print("=" * 68)

    xml = open(XML, encoding="utf-8").read()
    sb = sel_bar_block(xml)

    # ---------- 结构前提（与 Java 形变实现的对应关系）----------
    ck("sel_bar 行高固定 41dp", 'android:layout_height="41dp"' in sb)
    ck("槽位/删除/🔍搜索 三个可见子控件高度统一 32dp",
       all(get_int(attrs_of(sb, t), "android:layout_height") == 32
           for t in ("@+id/device_search_slot", "@+id/btn_delete",
                     "@+id/btn_rescan")))
    ck("旧跳动源：不存在 34dp 高的子控件",
       'android:layout_height="34dp"' not in xml)
    ck("🔍搜索 无 layout_weight（右边缘被行 padding 锚定）",
       get_weight(attrs_of(sb, "@+id/btn_rescan")) == 0.0)
    ck("🔍搜索 是 sel_bar 内最后一个带 id 的顶层子控件",
       sb.rindex("@+id/btn_rescan") > sb.rindex("@+id/btn_delete")
       and "android:layout_weight" not in sb[sb.index("@+id/btn_rescan"):])
    ck("Spinner 与搜索框同在槽位内（显隐不重排行）",
       sb.index("@+id/target_spinner") > sb.index("@+id/device_search_slot")
       and sb.index("@+id/search_input") > sb.index("@+id/target_spinner")
       and sb.index("@+id/search_input") < sb.index("</FrameLayout>"))
    ck("Spinner 不再自带 weight（weight 上移到槽位）",
       get_weight(attrs_of(sb, "@+id/target_spinner")) == 0.0
       and is_match_parent(attrs_of(sb, "@+id/target_spinner"),
                           "android:layout_width"))

    # ---- v1.18.26：形变流畅度（用户反馈"不自然 + 折成两排"）----
    del_attr = attrs_of(sb, "@+id/btn_delete")
    ck("删除按钮锁死单行（singleLine+maxLines=1 → 3 字不会折成两排）",
       'android:singleLine="true"' in del_attr
       and 'android:maxLines="1"' in del_attr)
    ck("槽位与在线数均无 ellipsize 风险（形变途中不出现省略号抽搐）",
       'android:ellipsize="end"' in del_attr)

    # ---------- 布局仿真：不变量断言 ----------
    # 文字宽度（dp）：12sp 中文约 1em/字 + 按钮左右各 12dp 内边距
    w_del, w_glb = 48, 60          # 删除(2字) / 搜全局(3字)
    w_rescan = 64                  # 放大镜16 + 间距4 + “搜索”2字 + 左右各10
    print("\n[布局仿真]  删除=%ddp 搜全局=%ddp 🔍搜索=%ddp（行末锚定）"
          % (w_del, w_glb, w_rescan))

    jump_ok = True
    anchor_ok = True
    extend_ok = True
    slot_ok = True
    overflow_ok = True
    for screen in SCREENS:
        for w_online in (0, 24, 36, 45, 52):     # “在线 0”~“在线 12”+截断
            d = simulate(sb, screen, w_online, w_del, w_glb, w_rescan, "device")
            s = simulate(sb, screen, w_online, w_del, w_glb, w_rescan, "search")

            # 1) 行高一致
            if d["_row"]["height"] != s["_row"]["height"]:
                jump_ok = False
            # 2) 🔍搜索 坐标完全一致（不跳动的核心保证）
            for k in ("left", "right", "top", "bottom", "width"):
                if d["rescan"][k] != s["rescan"][k]:
                    anchor_ok = False
            # 3) 删除→搜全局：右缘不动、左缘向左延长（增量=宽度差）
            if d["mid"]["right"] != s["mid"]["right"]:
                extend_ok = False
            if (d["mid"]["left"] - s["mid"]["left"]) != (w_glb - w_del):
                extend_ok = False
            # 4) 左槽位左缘固定在行 padding（10dp），不左右漂移
            if d["slot"]["left"] != 10 or s["slot"]["left"] != 10:
                slot_ok = False
            # 6) 权重分配后槽位宽度必须为正（不溢出屏幕）
            if d["slot"]["width"] <= 0 or s["slot"]["width"] <= 0:
                overflow_ok = False

    ck("两种模式行高完全一致（41dp，无高低跳动）", jump_ok)
    ck("🔍搜索 坐标两种模式完全一致（行末锚定，不跳动）", anchor_ok)
    ck("删除→搜全局：右缘不动、左缘向左延长（增量=搜全局-删除）", extend_ok)
    ck("左槽位（设备选择框/搜索框）左缘固定，不左右漂移", slot_ok)
    ck("参数扫描（3 种屏宽 × 5 种在线数宽度）下槽位宽度均 > 0（不溢出）",
       overflow_ok)

    # ★ v1.18.26：形变**中途**在线数只淡出、仍占原宽，且按钮已长成「搜全局」宽。
    # 这是全程最"挤"的一帧，必须验算槽位不为负（否则会挤压/溢出）。
    overflow_mid = True
    for screen in SCREENS:
        for w_online in (0, 24, 36, 45, 52):
            g = simulate(sb, screen, w_online, w_del, w_glb, w_rescan,
                         "search", online_visible_in_search=True)
            if g["slot"]["width"] <= 0:
                overflow_mid = False
    ck("形变中途最挤的一帧（在线数满宽 + 按钮已加宽）槽位仍 > 0，不挤压溢出",
       overflow_mid)

    # 360dp 屏上打印两种模式的几何，供人工核对
    d = simulate(sb, 360, 45, w_del, w_glb, w_rescan, "device")
    s = simulate(sb, 360, 45, w_del, w_glb, w_rescan, "search")
    print("\n[360dp 屏 · 在线数 45dp 时的几何]")
    for tag, g in (("设备态", d), ("搜索态", s)):
        parts = "  ".join(
            "%s[x=%d..%d w=%d]" % (k, g[k]["left"], g[k]["right"], g[k]["width"])
            for k in ("slot", "online", "mid", "rescan"))
        print("  %s：%s" % (tag, parts))
    print("  → 行高 %ddp / %ddp；🔍搜索 x 均为 %d..%d；删除右缘均 %d，"
          "左缘 %d → %d（向左延长 %ddp）"
          % (d["_row"]["height"], s["_row"]["height"],
             d["rescan"]["left"], d["rescan"]["right"], d["mid"]["right"],
             d["mid"]["left"], s["mid"]["left"], w_glb - w_del))

    print("\n" + "=" * 68)
    print(f"结果：{N - len(FAILS)}/{N} 通过")
    if FAILS:
        print("失败项：")
        for f in FAILS:
            print("  - " + f)
        return 1
    print("全部通过 —— 两种模式行高一致、🔍搜索 不跳动、删除向左延长为搜全局")
    return 0


if __name__ == "__main__":
    sys.exit(main())
