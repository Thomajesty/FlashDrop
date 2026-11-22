# -*- coding: utf-8 -*-
"""v1.18.38 内存占用归因（不猜，量出来）。

用户反馈：Task Manager 里 FlashDrop 常驻内存 ~1.6GB。

逐场景量化私有内存（PagefileUsage，比 WorkingSet 更能反映泄漏）：
  S0 启动基线
  S1 500 条文本消息渲染（单设备，_visible_msgs 窗口 300）
  S2 60 张真实照片消息渲染（300px 缩略图气泡）
  S3 多设备视图切换把 8 页 LRU 填满
  S4 反复进出多选/全选（widgets_by_msg 引用）
  S5 ImageViewer 开/关 x5（v1.18.36 修复回归验证）
  S6 表情面板遍历全部分组（懒加载是否失效）
  S7 模拟连续收 200 条消息（append 路径）
  S8 大量 pending 卡片（离线队列 50 条）

运行：python windows/tests/profile_memory_v11838.py
"""
import ctypes
import ctypes.wintypes as wt
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TMP = tempfile.mkdtemp(prefix="fd_mem_")
os.environ["FLASHDROP_DATA_DIR"] = _TMP
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _PMC(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.K32GetProcessMemoryInfo.restype = wt.BOOL
_k32.K32GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(_PMC), wt.DWORD]


def mem_mb():
    """(workingset, private) MB"""
    pm = _PMC()
    pm.cb = ctypes.sizeof(_PMC)
    h = ctypes.windll.kernel32.GetCurrentProcess()
    if not _k32.K32GetProcessMemoryInfo(h, ctypes.byref(pm), pm.cb):
        return (0.0, 0.0)
    return (pm.WorkingSetSize / 1048576.0, pm.PagefileUsage / 1048576.0)


BASE_WS, BASE_PB = mem_mb()
_rows = []


def step(name):
    ws, pb = mem_mb()
    _rows.append((name, ws - BASE_WS, pb - BASE_PB, pb))
    print("  %-46s  WS %+8.1f MB   私有 %+8.1f MB  (私有总量 %7.1f)"
          % (name, ws - BASE_WS, pb - BASE_PB, pb))
    return pb


def settle(times=6):
    from PySide6.QtWidgets import QApplication
    for _ in range(times):
        QApplication.processEvents()
    import gc
    gc.collect()


def main():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt, QTimer, QEventLoop
    from PySide6.QtGui import QImage, QColor

    app = QApplication(sys.argv)

    from app.config import Config
    from app.node import FlashNode
    from app.ui.main_window import MainWindow, ALL_ID

    tmp = tempfile.mkdtemp(prefix="fd_mem_cfg_")
    cfg = Config(os.path.join(tmp, "a.json"))
    cfg.data.update({"device_id": "aaaaaaaaaaaaaaaa", "name": "MEM-A",
                     "port": 58931,
                     "save_dir": os.path.join(tmp, "save"),
                     "minimize_to_tray": False, "notify_on_receive": False})
    cfg.save()
    node = FlashNode(cfg)
    win = MainWindow(cfg, node)
    win.show()
    settle()
    step("S0 启动基线（MainWindow 显示后）")

    def select_peer(pid):
        for i in range(win.device_list.count()):
            it = win.device_list.item(i)
            if it.data(Qt.UserRole) == pid:
                win.device_list.itemClicked.emit(it)
                it.setSelected(True)
                break
        settle()

    # ---------- S1: 500 条文本 ----------
    pid1 = "b1" * 8
    win._on_peers([{"id": pid1, "name": "文本设备", "platform": "android",
                    "ips": [], "online": False, "connected": False}])
    settle()
    for i in range(500):
        m = {"kind": "text", "dir": "in" if i % 2 else "out",
             "text": "消息 %d —— 一段用来量内存的中文文本，长度接近真实聊天。" % i,
             "ts": 1700000000000 + i * 1000, "mid": "t%d" % i,
             "peer_id": pid1}
        win.msgs.setdefault(pid1, []).append(m)
    select_peer(pid1)
    settle()
    step("S1 500 条文本消息（窗口 300 条渲染）")

    # ---------- S2: 60 张照片消息 ----------
    img_dir = os.path.join(tmp, "imgs")
    os.makedirs(img_dir, exist_ok=True)
    paths = []
    for i in range(60):
        img = QImage(2000, 1500, QImage.Format_ARGB32)
        img.fill(QColor(30 * i % 255, 100, 180))
        p = os.path.join(img_dir, "photo_%02d.jpg" % i)
        img.save(p, "JPG", 85)
        paths.append(p)
    pid2 = "c2" * 8
    win._on_peers([{"id": pid2, "name": "图片设备", "platform": "android",
                    "ips": [], "online": False, "connected": False}])
    settle()
    for i, p in enumerate(paths):
        m = {"kind": "file", "dir": "in", "state": "done",
             "file": "photo_%02d.jpg" % i, "mime": "image/jpeg",
             "path": p, "size": os.path.getsize(p),
             "ts": 1700000000000 + i * 1000, "tid": "f%d" % i,
             "peer_id": pid2}
        win.msgs.setdefault(pid2, []).append(m)
    select_peer(pid2)
    settle()
    step("S2 60 张照片气泡（2000x1500 JPG，300px 缩略图）")

    # ---------- S3: 多设备切换填满 8 页 LRU ----------
    pids = []
    for k in range(6):
        pk = ("d%d" % k) * 4
        pids.append(pk)
        win._on_peers([{"id": pk, "name": "切换设备%d" % k,
                        "platform": "android", "ips": [],
                        "online": False, "connected": False}])
        for i in range(120):
            m = {"kind": "text", "dir": "in" if i % 2 else "out",
                 "text": "切换页 %d-%d —— 填满页缓存" % (k, i),
                 "ts": 1700000000000 + (k * 1000 + i) * 1000,
                 "mid": "s%d_%d" % (k, i), "peer_id": pk}
            win.msgs.setdefault(pk, []).append(m)
    # 停留在图片设备页，然后来回切
    for rnd in range(3):
        for pk in pids:
            select_peer(pk)
        select_peer(pid2)
    settle()
    pages = len(win._chat_pages)
    step("S3 6 设备 x120 条来回切 3 轮（页缓存 %d 页）" % pages)

    # ---------- S4: 多选模式反复进出 ----------
    select_peer(pid1)
    for _ in range(20):
        win._enter_select_mode()
        win._exit_select_mode()
    settle()
    step("S4 多选模式进出 20 次")

    # ---------- S5: ImageViewer 开/关 5 次（真实入口：截图→查看器）----------
    for _ in range(5):
        v = win.open_image_viewer(paths[0])
        settle(3)
        v.close()
        settle(6)
    step("S5 ImageViewer 真实入口开/关 5 次（2000x1500）")
    viewers_alive = len(getattr(win, "_viewers", []) or [])
    print("    _viewers 残留: %s" % viewers_alive)

    # ---------- S6: 表情面板遍历全部分组 ----------
    from app.ui.emoji import EmojiPanel
    panel = EmojiPanel(win, win.theme)
    settle()
    step("S6 表情面板构建（默认组已解码）")
    for key, _b, _lbl in panel._tab_btns:
        panel._show_group(key)
        settle(2)
    step("S6b 表情面板遍历全部分组后")

    # ---------- S7: 连续收 200 条 ----------
    select_peer(pid1)
    for i in range(200):
        m = {"kind": "text", "dir": "in",
             "text": "连续追加 %d —— 模拟持续 incoming" % i,
             "ts": 1750000000000 + i * 1000, "mid": "n%d" % i,
             "peer_id": pid1}
        win._append_msg(pid1, m)
    settle()
    step("S7 连续 append 200 条（走 ② 增量路径）")

    # ---------- S8: pending 队列 50 条 ----------
    srcs = []
    fdir = os.path.join(tmp, "pend")
    os.makedirs(fdir, exist_ok=True)
    for i in range(50):
        p = os.path.join(fdir, "p_%d.bin" % i)
        with open(p, "wb") as f:
            f.write(os.urandom(2048))
        srcs.append(p)
    from app.ui.main_window import ALL_ID as _ALL
    ptarget = pids[0]
    win._queue_files(srcs, [ptarget])
    settle()
    step("S8 离线 pending 队列 50 条")

    # ---------- S9: _trim_pages 回收 ----------
    before_pages = len(win._chat_pages)
    win._trim_pages()
    settle()
    after_pages = len(win._chat_pages)
    step("S9 _trim_pages 后（页数 %d → %d）" % (before_pages, after_pages))
    ck_ok = after_pages <= 2  # 当前页 + init 页
    print("    trim 后页数断言: %s" % ("ok" if ck_ok else "FAIL"))
    # 切到其它设备验证重建路径仍正常
    select_peer(pid2)
    n_bubbles = win.chat_vbox.count()
    print("    trim 后切回图片设备气泡数: %d (>1 应正常重建)" % n_bubbles)
    assert n_bubbles > 1

    # ---------- S10: trim 后再切 3 轮（验证回收后不再堆高） ----------
    for rnd in range(3):
        for pk in pids:
            select_peer(pk)
        select_peer(pid2)
    settle()
    step("S10 trim 后再来回切 3 轮（对比 S3 的增量，应远小于首次）")

    # ---------- 汇总 ----------
    print()
    print("=" * 78)
    print("归因判读（看『私有』增量，基线私有 %.0f MB / WS %.0f MB）"
          % (BASE_PB, BASE_WS))
    for name, dw, dpb, tot in _rows:
        flag = "  ←←← 大头" if dpb > 150 else ""
        print("  %-44s 私有增量 %7.1f MB%s" % (name, dpb, flag))
    print("=" * 78)

    win.close()
    os._exit(0)


if __name__ == "__main__":
    main()
