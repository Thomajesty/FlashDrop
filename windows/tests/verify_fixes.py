# -*- coding: utf-8 -*-
"""针对本轮修复的验证：设备名迁移 / 右键菜单样式 / 历史与多选回归"""
import os
import socket
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["FLASHDROP_DATA_DIR"] = tempfile.mkdtemp(prefix="fd_verify_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} {detail if not cond else ''}")


print("== 1. 设备名迁移（旧默认'<用户名>的电脑'→主机名）==")
from app.config import Config
from app import util

legacy_name = f"{os.environ.get('USERNAME') or ''}的电脑"
cfg_path = os.path.join(os.environ["FLASHDROP_DATA_DIR"], "config.json")
with open(cfg_path, "w", encoding="utf-8") as f:
    import json
    json.dump({"device_id": "verifier000000001", "name": legacy_name,
               "port": 58899}, f)
cfg = Config(cfg_path)
check("旧用户名默认已迁移为主机名", cfg.name == util.default_device_name(),
      f"got {cfg.name}")
check("迁移值为主机名", cfg.name == socket.gethostname().split(".")[0],
      f"got {cfg.name} expect {socket.gethostname()}")
# 自定义名不被覆盖
cfg.data["name"] = "我的自定义设备"
cfg.save()
cfg2 = Config(cfg_path)
check("自定义设备名不受影响", cfg2.name == "我的自定义设备", cfg2.name)

print("== 2. 右键菜单样式（QSS 加大）==")
os.environ["FLASHDROP_DATA_DIR"] = tempfile.mkdtemp(prefix="fd_verify2_")
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
from app.config import Config as C2
cfg3 = C2()
from app.node import FlashNode
from app.ui.main_window import MainWindow
node = FlashNode(cfg3)
win = MainWindow(cfg3, node)
ss = win.styleSheet()
check("QMenu 字号规则存在", "QMenu" in ss and "font-size: 14px" in ss)
check("QMenu 选中态规则存在", "QMenu::item:selected" in ss)
check("QMenu 内边距加大", "QMenu::item" in ss and "padding: 7px 30px" in ss)

print("== 3. 冒烟链路（历史/多选/单实例锁）==")
import subprocess
r = subprocess.run([sys.executable, os.path.join("tests", "test_ui_smoke.py")],
                   capture_output=True, text=True, cwd=os.path.dirname(
                       os.path.dirname(os.path.abspath(__file__))))
check("UI 冒烟测试通过", "UI_SMOKE_OK" in r.stdout, r.stdout[-500:])

print()
print(f"===== 验证结果: {len(PASS)} 通过, {len(FAIL)} 失败 =====")
if FAIL:
    print("失败项:", FAIL)
    sys.exit(1)
print("VERIFY_OK")
