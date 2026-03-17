from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QBrush, QColor, QPainter, QRadialGradient
from PyQt5.QtWidgets import QPushButton


class CircularButton(QPushButton):
    """圆形按钮，支持颜色和闪烁状态。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(40, 40)
        self._color = QColor(100, 100, 100)
        self._is_flashing = False
        self._flash_state = False
        self._flash_timer = QTimer(self)
        self._flash_timer.timeout.connect(self._toggle_flash)

    def set_color(self, color: QColor):
        self._color = color
        self.update()

    def start_flashing(self, interval: int = 500):
        self._is_flashing = True
        self._flash_timer.start(interval)

    def stop_flashing(self):
        self._is_flashing = False
        self._flash_timer.stop()
        self._flash_state = False
        self.update()

    def _toggle_flash(self):
        self._flash_state = not self._flash_state
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        center_x = self.width() // 2
        center_y = self.height() // 2
        radius = min(self.width(), self.height()) // 2 - 5

        if self._is_flashing:
            if self._flash_state:
                color = QColor(
                    min(255, self._color.red() + 50),
                    min(255, self._color.green() + 50),
                    min(255, self._color.blue() + 50),
                )
            else:
                color = self._color
        else:
            color = self._color

        gradient = QRadialGradient(center_x, center_y, radius)
        gradient.setColorAt(0, color)
        gradient.setColorAt(1, color.darker(150))

        painter.setBrush(QBrush(gradient))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(center_x - radius, center_y - radius, radius * 2, radius * 2)
