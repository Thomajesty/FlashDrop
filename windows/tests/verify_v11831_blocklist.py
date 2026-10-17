# -*- coding: utf-8 -*-
"""v1.18.31 验收：连接过的设备可以在设备列表删除（删得掉 + 不复活）

用户需求：「安卓版内 连接过的安卓手机不能在设备列表删除 需要优化」

定位到两条根因（本脚本覆盖第二条 + 全链路接线；第一条的行为测试见
android/tests/RT11831.java，35/35）：

  根因 1（删了又复活）：设备还在同一网段，UDP 广播发现 +
          rebuildSpinner 里的 rememberPeer 会把它**立刻加回列表**，
          forgetPeer 单靠摘 known_peers 档案拦不住。
          → 修法：持久屏蔽名单 blocked_peers + 节点层拒连（FlashNode）
            + UI 层过滤（MainActivity）+ 事件层丢弃（NodeService）。

  根因 2（没有删除入口）：下拉行的 ✕ 只在「有聊天记录」时出现，
          "连接过但从没聊过/传过"的设备行一个删除入口都没有。
          → 修法：所有设备行统一给 ✕（"全部设备"除外），
            ✕ 只 clickable 不 focusable（v1.18.24 的教训：可聚焦子控件
            会让 AbsListView 把整行点击判给它，行就"点不动"）。

本脚本六层验收：
  A. Prefs：屏蔽名单 API 齐备且持久化（key/方法名）；
  B. FlashNode：广播/连接/重连三层拦截 + enforceBlocklist；
  C. MainActivity：删除流程落屏蔽名单 + 列表/补位/搜索/合并四路过滤；
  D. NodeService：后台路径也丢弃已删设备的事件；
  E. SettingsActivity：恢复入口存在（删除可逆，不是黑洞）；
  F. 删除入口覆盖：下拉行 ✕ 不再要求有聊天记录；
     版本号 5 处同步 1.18.31；无回归（-A assets 铁律仍在）。

运行：python windows/tests/verify_v11831_blocklist.py
"""
import io
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
AND = os.path.join(ROOT, "android", "app", "src", "main", "java",
                   "com", "flashdrop", "app")

FAILS = []
N = 0


def ck(name, ok, detail=""):
    global N
    N += 1
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f"  —— {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name + (f" —— {detail}" if detail else ""))


def rd(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def src(name):
    return rd(os.path.join(AND, name))


print("=" * 72)
print("v1.18.31 验收：连接过的设备可以在设备列表删除（删得掉 + 不复活）")
print("=" * 72)

prefs = src("Prefs.java")
node = src("FlashNode.java")
main = src("MainActivity.java")
svc = src("NodeService.java")
settings = src("SettingsActivity.java")
fdutil = src("FdUtil.java")

# ============================================================
print("\n■ A. Prefs：持久屏蔽名单（blocked_peers）")
# ============================================================
ck("A1 blocked_peers 存储 key 存在", '"blocked_peers"' in prefs)
ck("A2 blockedPeers() 读接口", "public JSONArray blockedPeers()" in prefs)
ck("A3 blockedPeers(JSONArray) 写接口",
   "public void blockedPeers(JSONArray arr)" in prefs)
ck("A4 isBlocked(id) 判定接口", "public boolean isBlocked(String id)" in prefs)
ck("A5 blockPeer(id,name) 入名单", "public void blockPeer(String id, String name)" in prefs)
ck("A6 unblockPeer(id) 解除屏蔽", "public void unblockPeer(String id)" in prefs)
ck("A7 名单条目带 id/name/ts 三字段",
   all(k in prefs for k in ['o.put("id", id)', 'o.put("name"', 'o.put("ts"']))
ck("A8 重复 blockPeer 去重（不堆重复条目）",
   'id.equals(o.optString("id"))) continue' in prefs)
ck("A9 空 id 不入名单（blockPeer 开头守卫）",
   re.search(r"public void blockPeer\(String id, String name\)\s*\{[^}]*?"
             r"if \(id == null \|\| id\.isEmpty\(\)\) return;", prefs, re.S) is not None)
ck("A10 名单读取有异常容错（坏 JSON 不崩）",
   re.search(r"public JSONArray blockedPeers\(\)\s*\{\s*try\s*\{"
             r"[^}]*\}\s*catch \(Exception e\)", prefs, re.S) is not None)

# ============================================================
print("\n■ B. FlashNode：广播/连接/重连三层拦截 + 即时生效")
# ============================================================
ck("B1 session() 对已删设备直接拒连",
   re.search(r"if \(peerBlocked\(hello\)\)\s*\{[^}]*?closeConn\(conn\); return;",
             node, re.S) is not None)
ck("B2 peerBlocked() 辅助方法存在",
   "private boolean peerBlocked(JSONObject hello)" in node)
ck("B3 peerBlocked 覆盖跨版本身份合并（旧 ID 被删 → 新 ID 也拒）",
   re.search(r"peerBlocked\(JSONObject hello\)\s*\{.*?mergeCandidate\(pid, hello\).*?"
             r"prefs\.isBlocked\(mergedFrom\)", node, re.S) is not None)
ck("B4 udpLoop 跳过已删设备（不回应广播、不建连）",
   re.search(r'if \(pid\.equals\(deviceId\)\) continue;\s*\n\s*'
             r'// ★ v1\.18\.31：已删除（屏蔽）的设备.*?\n\s*'
             r'if \(prefs\.isBlocked\(pid\)\)', node, re.S) is not None)
ck("B5 touchPeer 命中名单返回 null 且清出 peers",
   re.search(r"touchPeer\(JSONObject msg, String ip\)\s*\{.*?"
             r"prefs\.isBlocked\(pid\).*?peers\.remove\(pid\);\s*\n\s*return null;",
             node, re.S) is not None)
ck("B6 enforceBlocklist() 公开方法存在",
   "public void enforceBlocklist()" in node)
ck("B7 enforceBlocklist 先摘 peers 再关连接（防连接风暴）",
   re.search(r"enforceBlocklist\(\)\s*\{.*?"
             r"for \(String id : new ArrayList<>\(peers\.keySet\(\)\)\).*?"
             r"for \(Conn c : new ArrayList<>\(conns\.values\(\)\)\)", node, re.S) is not None)
ck("B8 closeConn 对已删设备不重连（ensureConnected 前判屏蔽）",
   re.search(r"if \(!prefs\.isBlocked\(pid\)\) ensureConnected\(p, true\);",
             node) is not None)
ck("B9 手动添加（connectManual）也拒已删设备",
   re.search(r"connectManual.*?peerBlocked\(hello\)", node, re.S) is not None)

# ============================================================
print("\n■ C. MainActivity：删除流程 + 四路 UI 过滤")
# ============================================================
ck("C1 删除会话落屏蔽名单（blockPeer）",
   re.search(r"confirmDeleteConversation.*?blockPeer\(pid, show\)", main, re.S)
   is not None)
ck("C2 删除后立即生效（enforceBlocklist）",
   re.search(r"confirmDeleteConversation.*?enforceBlocklist\(\)", main, re.S)
   is not None)
ck("C3 peers 事件不过滤已删设备（handleEvent）",
   re.search(r'case "peers": \{.*?if \(Prefs\.get\(this\)\.isBlocked\(pid\)\) continue;',
             main, re.S) is not None)
ck("C4 rebuildSpinner 在线列过滤 + 不再 rememberPeer",
   re.search(r"rebuildSpinner\(\)\s*\{.*?"
             r"if \(Prefs\.get\(this\)\.isBlocked\(id\)\) continue;.*?"
             r"rememberPeer\(", main, re.S) is not None)
ck("C5 rebuildSpinner 离线补位也过滤（known_peers 分支）",
   re.search(r"knownPeers\(\).*?if \(Prefs\.get\(this\)\.isBlocked\(id\)\) continue;",
             main, re.S) is not None)
ck("C6 全局搜索跳过已删设备",
   re.search(r"known\.optJSONObject\(i\).*?isBlocked\(id\)", main, re.S) is not None)
ck("C7 peer_merged：旧 ID 被删 → 新 ID 一并屏蔽",
   re.search(r'case "peer_merged": \{.*?isBlocked\(oldId\).*?blockPeer\(newId',
             main, re.S) is not None)
ck("C8 handleEvent 丢弃已删设备的 text/transfer 事件",
   re.search(r'private void handleEvent\(JSONObject e\)\s*\{.*?'
             r'\("text"\.equals\(ev\) \|\| "transfer"\.equals\(ev\)\).*?'
             r"isBlocked\(e\.optString\(\"peer_id\"\)\)", main, re.S) is not None)
ck("C9 删除确认弹窗说明「不会再出现 + 可恢复」",
   "不再出现在设备列表" in main and "已删除的设备」中恢复" in main)
ck("C10 删除成功提示同步更新", "该设备不会再出现" in main)

# ============================================================
print("\n■ D. NodeService：后台路径同样拦截")
# ============================================================
ck("D1 事件分发最前段丢弃已删设备的 text/transfer",
   re.search(r"installEventDispatcher\(\)\s*\{.*?"
             r'\("text"\.equals\(ev\) \|\| "transfer"\.equals\(ev\)\).*?'
             r"isBlocked\(e\.optString\(\"peer_id\"\)\)", svc, re.S) is not None)
ck("D2 拦截点在 ui/后台分流之前（后台落库+通知也挡住）",
   re.search(r"installEventDispatcher\(\)\s*\{.*?isBlocked.*?"
             r"FlashNode\.Listener ui = FlashApp\.get\(\)\.uiListener;",
             svc, re.S) is not None)

# ============================================================
print("\n■ E. SettingsActivity：恢复入口（删除可逆）")
# ============================================================
ck("E1 设置页有「已删除的设备」入口", "已删除的设备" in settings)
ck("E2 refreshBlockedBtn 数量展示", "refreshBlockedBtn" in settings)
ck("E3 showBlockedDevices 列表 + 解除屏蔽",
   "showBlockedDevices" in settings and "unblockPeer" in settings)
ck("E4 空名单有引导文案（告诉用户误删可恢复）",
   "误删" in settings or "恢复" in settings)

# ============================================================
print("\n■ F. 删除入口覆盖 + 版本号 + 构建铁律")
# ============================================================
ck("F1 下拉行 ✕ 不再要求有聊天记录（boolean hasHistory 门槛已移除）",
   "boolean hasHistory" not in main)
ck("F2 ✕ 只 clickable 不 focusable（v1.18.24 教训保持）",
   re.search(r"x\.setClickable\(true\);\s*\n\s*x\.setFocusable\(false\);", main)
   is not None)
ck("F3 「全部设备」行仍不给 ✕（聚合视图无对应会话）",
   re.search(r"if \(!hasSession \|\| pid == null\) return row;", main) is not None)
ck("F4 xSlot 无条件先清空（防收起态 ↻ 残留吃点击）",
   re.search(r"xSlot\.removeAllViews\(\);\s*\n\s*if \(!hasSession", main) is not None)

manifest = rd(os.path.join(ROOT, "android", "app", "src", "main",
                           "AndroidManifest.xml"))
# ★ v1.18.32 起改为演进式断言：版本号只增不减、5 处彼此一致（勿写死具体值，
#   否则每版都要改本套件——具体值的一致性由当版专项套件负责）
_m = re.search(r'android:versionCode="(\d+)"', manifest)
_vn = re.search(r'android:versionName="(\d+\.\d+\.\d+)"', manifest)
_vcode = int(_m.group(1)) if _m else -1
_vname = _vn.group(1) if _vn else ""
ck("F5 AndroidManifest versionCode>=60 且版本语义 >=1.18.31",
   _vcode >= 60 and _vname >= "1.18.31")
ck("F6 FdUtil.APP_VERSION 与 manifest 一致",
   ('public static final String APP_VERSION = "%s";' % _vname) in fdutil)
win_init = rd(os.path.join(ROOT, "windows", "app", "__init__.py"))
ck("F7 windows __version__ 与 Android 一致",
   ('__version__ = "%s"' % _vname) in win_init)
bat = rd(os.path.join(ROOT, "android", "build_apk.bat"))
sh = rd(os.path.join(ROOT, "android", "_build_v11817.sh"))
ck("F8 build_apk.bat version 同步",
   ("--version-code %d --version-name %s" % (_vcode, _vname)) in bat)
ck("F9 _build_v11817.sh version 同步",
   ("--version-code %d --version-name %s" % (_vcode, _vname)) in sh)
ck("F10 aapt2 link 两个入口都带 -A assets（表情资产铁律）",
   '-A "%SRC%\\assets"' in bat and '-A "$BPW\\\\assets"' in sh)
ck("F11 屏蔽名单持久化 key 不与既有 key 冲突",
   prefs.count('"blocked_peers"') >= 1
   and '"known_peers"' in prefs and '"peer_aliases"' in prefs)

# ============================================================
print("\n" + "=" * 72)
print(f"合计 {N} 项：PASS {N - len(FAILS)} / FAIL {len(FAILS)}")
if FAILS:
    print("\n失败项：")
    for f in FAILS:
        print("  · " + f)
    raise SystemExit(1)
print("全部通过 ✓")
