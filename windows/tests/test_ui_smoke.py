# -*- coding: utf-8 -*-
"""UI 冒烟测试：offscreen 启动主窗口 + 双实例联动（收发文本/文件），无异常即通过。"""

import os
import sys
import time
import tempfile
import hashlib

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_TMP = tempfile.mkdtemp(prefix="flashdrop_ui_data_")
os.environ["FLASHDROP_DATA_DIR"] = _TMP  # 隔离全局数据（历史记录等）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QEventLoop

from app.config import Config
from app.node import FlashNode
from app.ui.main_window import MainWindow


def wait_ms(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def md5file(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def main():
    tmp = tempfile.mkdtemp(prefix="flashdrop_ui_")
    # 两个配置（模拟两台设备）
    cfgA = Config(os.path.join(tmp, "a.json"))
    cfgA.data.update({"device_id": "aaaaaaaaaaaaaaaa", "name": "UI-A", "port": 58910,
                      "save_dir": os.path.join(tmp, "a_save"),
                      "cache_dir": os.path.join(tmp, "a_cache"),
                      "minimize_to_tray": False, "notify_on_receive": False})
    cfgA.save()
    cfgB = Config(os.path.join(tmp, "b.json"))
    cfgB.data.update({"device_id": "bbbbbbbbbbbbbbbb", "name": "UI-B", "port": 58911,
                      "save_dir": os.path.join(tmp, "b_save"),
                      "cache_dir": os.path.join(tmp, "b_cache"),
                      "minimize_to_tray": False, "notify_on_receive": False})
    cfgB.save()

    app = QApplication(sys.argv)
    nodeA = FlashNode(cfgA)
    winA = MainWindow(cfgA, nodeA)
    winA.show()

    nodeB = FlashNode(cfgB)
    winB = MainWindow(cfgB, nodeB)
    winB.show()

    wait_ms(1500)  # 等待服务启动

    errors = []

    # 探针：统计 nodeB.emit 原始事件 与 winB UI 信号接收次数
    probe_node = {"text": 0, "transfer": 0, "events": []}
    inner_emit = nodeB.emit
    def probing_emit(evt):
        if evt.get("event") == "text":
            probe_node["text"] += 1
            probe_node["events"].append(("NODE-text", evt.get("mid")))
        if evt.get("event") == "transfer":
            probe_node["transfer"] += 1
            probe_node["events"].append(("NODE-xfer", evt.get("kind"), evt.get("tid")[:6],
                                         evt.get("state")))
        inner_emit(evt)
    nodeB.emit = probing_emit

    probe_ui = {"text": 0, "xfer": 0, "events": []}
    winB.bridge.textReceived.connect(lambda e: (probe_ui.__setitem__("text", probe_ui["text"] + 1),
                                                probe_ui["events"].append(("UI-text", e.get("mid")))))
    winB.bridge.transferEvent.connect(lambda e: (probe_ui.__setitem__("xfer", probe_ui["xfer"] + 1),
                                                 probe_ui["events"].append(("UI-xfer", e.get("kind"), e.get("tid","")[:6], e.get("state")))))

    # 预连接（等价于自动发现完成后的状态），避免 UI 层弹模态框
    fut = nodeA.connect_manual("127.0.0.1", 58911)
    okA = fut.result(15) if fut else (False, "no fut")
    print("预连接结果:", okA)
    wait_ms(2000)  # 等待 UI 收到 peers 事件

    # B 应该在设备列表里看到 A
    def peer_ids(w):
        return list(w.peers.keys())
    print("A peers:", peer_ids(winA))
    print("B peers:", peer_ids(winB))
    if "bbbbbbbbbbbbbbbb" not in peer_ids(winA):
        errors.append("A 未发现 B")
    if "aaaaaaaaaaaaaaaa" not in peer_ids(winB):
        errors.append("B 未发现 A")

    # UI 发送文本：A -> B
    targets = winA._targets()
    print("A targets:", targets)
    if "bbbbbbbbbbbbbbbb" not in targets:
        errors.append(f"A 的发送目标未包含 B: {targets}")
    winA.input_edit.setPlainText("UI 冒烟消息 hello")
    winA._send_input()
    wait_ms(1500)
    msgs_b = winB.msgs.get("aaaaaaaaaaaaaaaa", [])
    if not any(m.get("text") == "UI 冒烟消息 hello" for m in msgs_b):
        errors.append("B 未收到 UI 发送的文本")

    # UI 发送文件：A -> B
    src = os.path.join(tmp, "ui_test.bin")
    with open(src, "wb") as f:
        f.write(b"UI-TEST-DATA" * 100000)  # ~1.2MB
    winA._do_send_files(["bbbbbbbbbbbbbbbb"], [src])
    ok = False
    recv_path = None
    for _ in range(60):
        wait_ms(200)
        lst = [m for m in winB.msgs.get("aaaaaaaaaaaaaaaa", [])
               if m.get("kind") == "file" and m.get("state") == "done"]
        if lst:
            ok = True
            recv_path = lst[0]["path"]
            break
    if not ok:
        errors.append("B 未完成文件接收")
        # 诊断输出
        print("== 诊断 ==")
        print("B 收到的所有消息:", [(m.get("kind"), m.get("dir"), m.get("state"),
                                     m.get("file"), m.get("reason"), id(m))
                                    for m in winB.msgs.get("aaaaaaaaaaaaaaaa", [])])
        print("NODE 探针:", probe_node["events"])
        print("UI 探针:", probe_ui["events"][-25:])
        print("A out_states:", dict(nodeA.out_states))
        print("A conns:", {k: (v.alive, v.replaced) for k, v in nodeA.conns.items()})
        print("B conns:", {k: (v.alive, v.replaced) for k, v in nodeB.conns.items()})
        print("B inbounds:", list(nodeB.inbounds.keys()))
    else:
        if md5file(recv_path) != md5file(src):
            errors.append("接收文件内容不一致")

    # 截图验证（offscreen 也能渲染）
    from PySide6.QtGui import QPixmap
    pm = winA.grab()
    shot = os.path.join(os.path.dirname(__file__), "..", "..", "dist", "ui_smoke_A.png")
    os.makedirs(os.path.dirname(shot), exist_ok=True)
    pm.save(shot)
    print("截图:", shot, pm.width(), "x", pm.height())

    # 多选删除逻辑验证（直接驱动主窗口，绕过确认对话框）
    now_ms = int(time.time() * 1000)
    m1 = {"kind": "text", "dir": "in", "peer_id": "bbbbbbbbbbbbbbbb",
          "peer_name": "UI-B", "mid": "deltest0000000000001",
          "text": "待删除消息甲", "ts": now_ms}
    m2 = {"kind": "text", "dir": "in", "peer_id": "bbbbbbbbbbbbbbbb",
          "peer_name": "UI-B", "mid": "deltest0000000000002",
          "text": "待删除消息乙", "ts": now_ms + 1}
    m3 = {"kind": "text", "dir": "in", "peer_id": "bbbbbbbbbbbbbbbb",
          "peer_name": "UI-B", "mid": "keep000000000000000003",
          "text": "保留消息丙", "ts": now_ms + 2}
    winA._append_msg("bbbbbbbbbbbbbbbb", m1)
    winA._append_msg("bbbbbbbbbbbbbbbb", m2)
    winA._append_msg("bbbbbbbbbbbbbbbb", m3)
    winA._enter_select_mode(m1)
    if not (winA.multi_mode and id(m1) in winA.selected_ids):
        errors.append("进入多选模式失败（应预选中第一条）")
    winA._select_all_visible()
    if id(m2) not in winA.selected_ids:
        errors.append("全选失败")
    winA._remove_msgs({winA._msg_identity(m1), winA._msg_identity(m2)})
    remain = [m for m in winA.msgs.get("bbbbbbbbbbbbbbbb", [])
              if m.get("mid") in ("deltest0000000000001", "deltest0000000000002")]
    if remain:
        errors.append("多选删除后内存仍有残留")
    if not any(m.get("mid") == "keep000000000000000003"
               for m in winA.msgs.get("bbbbbbbbbbbbbbbb", [])):
        errors.append("误删了不该删的消息")
    # 历史文件层面校验
    hist_texts = []
    hdir = os.path.join(_TMP, "history")
    for f in os.listdir(hdir):
        with open(os.path.join(hdir, f), "r", encoding="utf-8") as hf:
            hist_texts.append(hf.read())
    blob = "\n".join(hist_texts)
    if "待删除消息甲" in blob or "待删除消息乙" in blob:
        errors.append("历史文件中仍存在已删除消息")
    if "保留消息丙" not in blob:
        errors.append("历史文件误删保留消息")
    print("多选删除验证: msgs 剩余", len(winA.msgs.get("bbbbbbbbbbbbbbbb", [])))

    # 单实例锁函数验证。
    #
    # ★ v1.18.9 契约变更说明（原断言已过时，此处同步更新）：
    #
    # 旧契约：第二次调用一律返回 None（只要端口被占就认定"已有实例"）。
    # 新契约：返回 None 的前提是 **端口被占 且 对方回应 PONG**。
    #   若端口被占但无人应答（孤儿锁 / 残留进程 / 被别的程序占用），
    #   则抢占该锁并返回可用 socket —— 这正是修「EXE 双击打不开」的关键：
    #   旧逻辑下这种情况会让新进程直接 exit(0)，用户观感就是没反应。
    #
    # 因此本用例改为验证**新契约的四条路径**，而不是继续断言旧行为。
    import main as fd_main
    import socket as _sk
    import threading as _th

    # 路径 A：端口空闲 → 拿到锁
    s1 = fd_main.single_instance_lock()
    if s1 is None:
        errors.append("单实例锁：端口空闲时应拿到锁，实际返回 None")
    else:
        print("单实例锁验证 A（空闲可取锁）: OK")

    # 路径 B：活实例（会回 PONG）→ 返回 None
    live = _sk.socket(_sk.AF_INET, _sk.SOCK_DGRAM)
    try:
        live.setsockopt(_sk.SOL_SOCKET, _sk.SO_REUSEADDR, 1)
    except Exception:
        pass
    if s1 is not None:
        try:
            s1.close()          # 让出端口，便于下面精确构造场景
        except Exception:
            pass
    live.bind(("127.0.0.1", 58898))

    def _pong():
        try:
            live.settimeout(3.0)
            data, addr = live.recvfrom(64)
            if b"PING" in data:
                live.sendto(b"FlashDrop_PONG", addr)
        except Exception:
            pass

    _th.Thread(target=_pong, daemon=True).start()
    s2 = fd_main.single_instance_lock()
    if s2 is not None:
        errors.append("单实例锁：活实例在场时应返回 None，实际拿到锁")
    else:
        print("单实例锁验证 B（活实例让位）: OK")
    try:
        live.close()
    except Exception:
        pass
    wait_ms(300)

    # 路径 C：孤儿锁（占端口但不回 PONG）→ 应抢占成功
    orphan = _sk.socket(_sk.AF_INET, _sk.SOCK_DGRAM)
    try:
        orphan.setsockopt(_sk.SOL_SOCKET, _sk.SO_REUSEADDR, 1)
    except Exception:
        pass
    orphan.bind(("127.0.0.1", 58898))
    s3 = fd_main.single_instance_lock()
    if s3 is None:
        errors.append("单实例锁：孤儿锁应被抢占，实际返回 None（会导致打不开）")
    else:
        print("单实例锁验证 C（孤儿锁抢占）: OK")
        try:
            s3.close()
        except Exception:
            pass
    try:
        orphan.close()
    except Exception:
        pass

    # 清理退出
    winA._real_quit()
    winB._real_quit()
    wait_ms(800)

    if errors:
        print("UI_SMOKE_FAIL:", errors)
        sys.exit(1)
    print("UI_SMOKE_OK")


if __name__ == "__main__":
    main()
