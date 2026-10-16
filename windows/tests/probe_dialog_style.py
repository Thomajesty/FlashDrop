import os, sys, tempfile
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
tmp = tempfile.mkdtemp(); os.environ['FLASHDROP_DATA_DIR'] = tmp
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtWidgets import QApplication, QTabWidget, QDialog
from PySide6.QtCore import QEvent
from app.config import Config
from app.node import FlashNode
from app.ui.main_window import MainWindow, SettingsDialog
from app.ui.theme import build_qss

app = QApplication(sys.argv)
cfg = Config(os.path.join(tmp, 'c.json'))
cfg.data.update({'device_id': 'tttttttttttttttt', 'name': 'T', 'port': 58940,
                 'save_dir': os.path.join(tmp, 's'), 'cache_dir': os.path.join(tmp, 'c')})
cfg.save()
win = MainWindow(cfg, FlashNode(cfg))
win.show()
app.processEvents()

print('has filter:', win in [f for f in [win]], 'app filters on win:',
      sys.platform)

# 模拟 v1.2.2：安装应用级事件过滤器
class F:
    pass
app.installEventFilter(win)

sd = SettingsDialog(cfg, win)
sd.show()
app.processEvents()
app.processEvents()
# 检查是否继承了样式：objectName 选择器是否命中（QSS 已应用时 wa_StyledBackground 等）
from PySide6.QtWidgets import QComboBox
combo = sd.findChild(QComboBox)
fm = sd.fontMetrics()
print('dialog font family:', sd.font().family())
print('dialog styleSheet empty:', sd.styleSheet() == '')
bg = sd.palette().color(sd.backgroundRole()).name()
print('dialog bg color:', bg)
pm = sd.grab()
pm.save(r'dist/settings_v12_shown.png')
print('grab size:', pm.width(), pm.height())

# 点击取消是否关闭（程序化模拟 rejected）
sd.close()

# 再测消息框样式继承
from PySide6.QtWidgets import QMessageBox
mb = QMessageBox(QMessageBox.Question, '删除', '确定删除这条消息吗？',
                 QMessageBox.Yes | QMessageBox.No, win)
mb.show()
app.processEvents()
print('msgbox font family:', mb.font().family())
pm2 = mb.grab()
pm2.save(r'dist/msgbox_v12.png')
mb.close()
win._real_quit()
print('DONE')
