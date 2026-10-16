import os, sys
os.environ.pop("QT_QPA_PLATFORM", None)
ROOT = r"E:/工作缓存/Workbuddy/FlashDrop/windows"
sys.path.insert(0, ROOT)
from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QToolButton
app = QApplication.instance() or QApplication([])
from app.ui import theme as TH
QSS = TH.build_qss(TH.resolve_theme("light"))
IMG = os.path.join(ROOT, "assets", "fluent_emoji", "alien.png")
def measure(own_qss, with_app):
    app.setStyleSheet(QSS if with_app else "")
    b = QToolButton()
    b.setFixedSize(44, 44)
    b.setIconSize(QSize(26, 26))
    if own_qss:
        b.setStyleSheet(own_qss)
    b.setIcon(QIcon(QPixmap(IMG)))
    b.show(); app.processEvents()
    img = b.grab().toImage()
    W, H = img.width(), img.height()
    def col(x, y):
        c = img.pixelColor(x, y)
        return max(c.red(), c.green(), c.blue()) - min(c.red(), c.green(), c.blue()) > 40
    xs = [x for x in range(W) if any(col(x, y) for y in range(H))]
    b.hide(); app.setStyleSheet("")
    return (max(xs) - min(xs) + 1) if xs else 0
a = measure(None, True)
b = measure("QToolButton { padding: 0px; }", True)
c = measure(None, False)
print("A 旧写法 + 全局QSS      -> %d px" % a)
print("B 自身表padding:0 +全局QSS -> %d px" % b)
print("C 旧写法 无全局QSS       -> %d px" % c)
