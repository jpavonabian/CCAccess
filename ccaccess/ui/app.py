import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from ccaccess.ui.main_window import MainWindow


def run() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("CCAccess")
    win = MainWindow()
    win.show()
    QTimer.singleShot(0, win.start)
    return app.exec()
