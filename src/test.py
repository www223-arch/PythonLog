# 以 PyQt5 为例（PyQt6 仅需替换 Qt.WindowType）
import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QPushButton
from PyQt5.QtCore import Qt

class ToggleTopWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("可切换置顶的窗口")
        self.resize(400, 300)
        self.is_top = False  # 标记当前是否置顶
        
        # 界面布局
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # 切换置顶按钮
        self.toggle_btn = QPushButton("开启置顶")
        self.toggle_btn.clicked.connect(self.toggle_top)
        layout.addWidget(self.toggle_btn)

    def toggle_top(self):
        self.is_top = not self.is_top
        if self.is_top:
            # 开启置顶
            self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
            self.toggle_btn.setText("关闭置顶")
        else:
            # 取消置顶（恢复默认窗口标志）
            self.setWindowFlags(Qt.Window)
            self.toggle_btn.setText("开启置顶")
        # 关键：重新显示窗口（设置flags后需调用show()生效）
        self.show()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ToggleTopWindow()
    window.show()
    sys.exit(app.exec_())