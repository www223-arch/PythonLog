"""
Python上位机主程序

支持UDP数据源和实时波形显示的上位机软件。

使用方法:
    python src/main.py
"""

import sys
import os
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                             QGroupBox, QFormLayout, QMessageBox, QFileDialog, QCheckBox, QColorDialog, QMenu, QAction)
from PyQt5.QtCore import Qt, QTimer, QDateTime
from PyQt5.QtGui import QFont, QPainter, QColor, QPen, QBrush, QRadialGradient

from data_sources.manager import DataSourceManager, create_udp_source
from visualization.waveform_widget import WaveformWidget


class CircularButton(QPushButton):
    """圆形按钮，支持颜色和闪烁状态"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(40, 40)  # 进一步减小尺寸
        self._color = QColor(100, 100, 100)  # 默认灰色
        self._is_flashing = False
        self._flash_state = False
        self._flash_timer = QTimer(self)
        self._flash_timer.timeout.connect(self._toggle_flash)
    
    def set_color(self, color: QColor):
        """设置按钮颜色
        
        Args:
            color: QColor对象
        """
        self._color = color
        self.update()
    
    def start_flashing(self, interval: int = 500):
        """开始闪烁
        
        Args:
            interval: 闪烁间隔（毫秒）
        """
        self._is_flashing = True
        self._flash_timer.start(interval)
    
    def stop_flashing(self):
        """停止闪烁"""
        self._is_flashing = False
        self._flash_timer.stop()
        self._flash_state = False
        self.update()
    
    def _toggle_flash(self):
        """切换闪烁状态"""
        self._flash_state = not self._flash_state
        self.update()
    
    def paintEvent(self, event):
        """重绘按钮"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 绘制圆形
        center_x = self.width() // 2
        center_y = self.height() // 2
        radius = min(self.width(), self.height()) // 2 - 5
        
        # 如果正在闪烁，根据闪烁状态调整颜色
        if self._is_flashing:
            if self._flash_state:
                # 闪烁时使用更亮的颜色
                color = QColor(
                    min(255, self._color.red() + 50),
                    min(255, self._color.green() + 50),
                    min(255, self._color.blue() + 50)
                )
            else:
                color = self._color
        else:
            color = self._color
        
        # 创建渐变效果
        gradient = QRadialGradient(center_x, center_y, radius)
        gradient.setColorAt(0, color)
        gradient.setColorAt(1, color.darker(150))
        
        # 绘制圆形
        painter.setBrush(QBrush(gradient))
        painter.setPen(Qt.NoPen)  # 去掉边框
        painter.drawEllipse(center_x - radius, center_y - radius, radius * 2, radius * 2)


class MainWindow(QMainWindow):
    """主窗口"""
    
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.init_components()
        self.init_connections()
    
    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle("Python上位机 - UDP数据采集")
        self.setGeometry(100, 100, 1400, 800)
        
        # 创建中央控件
        central_widget = QWidget()
        main_layout = QHBoxLayout()
        
        # 左侧控制面板
        control_panel = self.create_control_panel()
        
        # 右侧波形显示
        self.waveform_widget = WaveformWidget()
        
        # 添加到主布局
        main_layout.addWidget(control_panel, 1)
        main_layout.addWidget(self.waveform_widget, 3)
        
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)
    
    def create_control_panel(self):
        """创建控制面板"""
        panel = QWidget()
        layout = QVBoxLayout()
        
        # 标题
        title_label = QLabel("控制面板")
        title_label.setFont(QFont("Arial", 14, QFont.Bold))
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        # UDP配置组
        udp_group = QGroupBox("UDP配置")
        udp_layout = QFormLayout()
        
        self.host_edit = QLineEdit("0.0.0.0")
        self.port_edit = QLineEdit("8888")
        self.header_edit = QLineEdit("DATA")
        self.header_edit.setPlaceholderText("数据校验头")
        
        udp_layout.addRow("主机地址:", self.host_edit)
        udp_layout.addRow("端口:", self.port_edit)
        udp_layout.addRow("数据校验头:", self.header_edit)
        
        # 圆形连接按钮
        button_layout = QHBoxLayout()
        self.connect_btn = CircularButton()
        self.connect_btn.clicked.connect(self.toggle_connection)
        button_layout.addWidget(self.connect_btn)
        button_layout.addStretch()
        udp_layout.addRow(button_layout)
        
        # 数据状态标签
        self.data_status_label = QLabel("数据状态: 无数据")
        self.data_status_label.setStyleSheet("color: #666;")
        udp_layout.addRow(self.data_status_label)
        
        # 暂停按钮
        self.pause_btn = QPushButton("暂停")
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.pause_btn.setEnabled(False)
        udp_layout.addRow(self.pause_btn)
        
        udp_group.setLayout(udp_layout)
        layout.addWidget(udp_group)
        
        # 通道配置组
        channel_group = QGroupBox("通道配置")
        channel_layout = QVBoxLayout()
        
        self.channels_label = QLabel("自动检测通道...")
        self.channels_label.setStyleSheet("color: #666;")
        self.channels_label.setContextMenuPolicy(Qt.CustomContextMenu)
        self.channels_label.customContextMenuRequested.connect(self.show_channel_context_menu)
        self.channels_label.setFixedHeight(30)  # 固定高度，防止比例变化
        self.channels_label.setWordWrap(True)  # 允许换行
        
        channel_layout.addWidget(self.channels_label)
        
        # 缓存区大小设置
        buffer_layout = QHBoxLayout()
        buffer_label = QLabel("缓存区大小:")
        self.buffer_size_edit = QLineEdit("1000")
        self.buffer_size_edit.setPlaceholderText("数据点数")
        buffer_apply_btn = QPushButton("应用")
        buffer_apply_btn.clicked.connect(self.apply_buffer_size)
        buffer_layout.addWidget(buffer_label)
        buffer_layout.addWidget(self.buffer_size_edit)
        buffer_layout.addWidget(buffer_apply_btn)
        channel_layout.addLayout(buffer_layout)
        
        # 数据限制开关
        self.limit_data_checkbox = QCheckBox("限制数据点数")
        self.limit_data_checkbox.setChecked(True)
        self.limit_data_checkbox.toggled.connect(self.toggle_limit_data)
        channel_layout.addWidget(self.limit_data_checkbox)
        
        clear_channels_btn = QPushButton("清空所有通道")
        clear_channels_btn.clicked.connect(self.clear_all_channels)
        channel_layout.addWidget(clear_channels_btn)
        
        channel_group.setLayout(channel_layout)
        layout.addWidget(channel_group)
        
        # 状态显示
        status_group = QGroupBox("状态")
        status_layout = QVBoxLayout()
        
        self.status_label = QLabel("未连接")
        self.status_label.setStyleSheet("color: red;")
        self.data_count_label = QLabel("接收数据: 0")
        self.save_file_label = QLabel("保存文件: 无")
        self.save_file_label.setStyleSheet("color: #666;")
        
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.data_count_label)
        status_layout.addWidget(self.save_file_label)
        
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
        

        
        # 数据保存控制
        save_group = QGroupBox("数据保存")
        save_layout = QVBoxLayout()
        
        self.save_path_edit = QLineEdit("data")
        self.save_path_edit.setPlaceholderText("保存目录")
        
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self.browse_save_path)
        
        path_layout = QHBoxLayout()
        path_layout.addWidget(self.save_path_edit)
        path_layout.addWidget(browse_btn)
        save_layout.addLayout(path_layout)
        
        self.save_btn = QPushButton("开始保存")
        self.save_btn.clicked.connect(self.toggle_saving)
        save_layout.addWidget(self.save_btn)
        
        save_group.setLayout(save_layout)
        layout.addWidget(save_group)
        
        # 弹簧，推到底部
        layout.addStretch()
        
        # 退出按钮
        exit_btn = QPushButton("退出")
        exit_btn.clicked.connect(self.close)
        layout.addWidget(exit_btn)
        
        panel.setLayout(layout)
        return panel
    
    def init_components(self):
        """初始化组件"""
        self.data_source_manager = DataSourceManager()
        self.data_count = 0
        self.auto_save_enabled = False
        self.last_data_time = None  # 记录最后接收数据的时间
        self.data_timeout = 1000  # 数据超时时间（毫秒）
        
        # 数据更新定时器
        self.data_timer = QTimer()
        self.data_timer.timeout.connect(self.update_data)
        self.data_timer.start(20)  # 20ms更新一次（50Hz）
        
        # 超时检测定时器
        self.timeout_timer = QTimer()
        self.timeout_timer.timeout.connect(self.check_data_timeout)
        self.timeout_timer.start(100)  # 100ms检测一次超时
    
    def init_connections(self):
        """初始化连接"""
        # 启动波形显示更新
        self.waveform_widget.start_update()
    
    def toggle_connection(self):
        """切换连接/断开状态"""
        if self.data_source_manager.is_connected():
            # 断开连接
            self.data_source_manager.disconnect()
            self.status_label.setText("未连接")
            self.status_label.setStyleSheet("color: red;")
            self.connect_btn.set_color(QColor(100, 100, 100))  # 灰色
            self.connect_btn.stop_flashing()
            self.pause_btn.setEnabled(False)
            self.data_count = 0
            self.data_count_label.setText("接收数据: 0")
            self.save_file_label.setText("保存文件: 无")
            self.channels_label.setText("自动检测通道...")
            self.data_status_label.setText("数据状态: 无数据")
            self.data_status_label.setStyleSheet("color: #666;")
            self.save_btn.setText("开始保存")
            self.auto_save_enabled = False
            print("UDP连接已断开")
        else:
            # 连接
            try:
                host = self.host_edit.text()
                port = int(self.port_edit.text())
                header = self.header_edit.text().strip() or 'DATA'
                
                # 设置数据校验头
                self.data_source_manager.set_data_header(header)
                
                udp_source = create_udp_source(host, port)
                success = self.data_source_manager.set_source(udp_source)
                
                if success:
                    self.status_label.setText("已连接")
                    self.status_label.setStyleSheet("color: green;")
                    self.connect_btn.set_color(QColor(100, 149, 237))  # 蓝色
                    # 不开始闪烁，等收到数据后再闪烁
                    self.pause_btn.setEnabled(True)
                    
                    # 清空旧通道
                    self.waveform_widget.clear_all()
                    self.channels_label.setText("自动检测通道...")
                    self.data_status_label.setText("数据状态: 等待数据...")
                    self.data_status_label.setStyleSheet("color: #666;")
                    
                    # 自动开始保存
                    save_path = self.save_path_edit.text()
                    if save_path:
                        self.data_source_manager.set_save_path(save_path)
                        if self.data_source_manager.start_saving():
                            self.save_btn.setText("停止保存")
                            save_file = self.data_source_manager.get_save_file()
                            self.save_file_label.setText(f"保存文件: {save_file}")
                            self.auto_save_enabled = True
                    
                    print(f"已连接到 {host}:{port}，数据校验头: {header}")
                else:
                    QMessageBox.warning(self, "失败", "连接失败，请检查配置")
            except ValueError:
                QMessageBox.warning(self, "错误", "请输入有效的端口号")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"连接失败: {str(e)}")
    
    def browse_save_path(self):
        """浏览保存路径"""
        dir_path = QFileDialog.getExistingDirectory(self, "选择保存目录", self.save_path_edit.text())
        if dir_path:
            self.save_path_edit.setText(dir_path)
    
    def toggle_saving(self):
        """切换数据保存状态"""
        if self.data_source_manager.is_saving():
            self.data_source_manager.stop_saving()
            self.save_btn.setText("开始保存")
            self.save_file_label.setText("保存文件: 无")
            self.auto_save_enabled = False
        else:
            save_path = self.save_path_edit.text()
            if save_path:
                self.data_source_manager.set_save_path(save_path)
            success = self.data_source_manager.start_saving()
            if success:
                self.save_btn.setText("停止保存")
                save_file = self.data_source_manager.get_save_file()
                self.save_file_label.setText(f"保存文件: {save_file}")
                self.auto_save_enabled = True
            else:
                QMessageBox.warning(self, "失败", "启动数据保存失败")
    
    def clear_all_channels(self):
        """清空所有通道"""
        self.waveform_widget.clear_all()
        self.data_count = 0
        self.data_count_label.setText("接收数据: 0")
    
    def apply_buffer_size(self):
        """应用缓存区大小设置"""
        try:
            size = int(self.buffer_size_edit.text())
            if size < 100:
                QMessageBox.warning(self, "警告", "缓存区大小不能小于100")
                return
            if size > 100000:
                QMessageBox.warning(self, "警告", "缓存区大小不能超过100000")
                return
            
            self.waveform_widget.set_max_points(size)
            QMessageBox.information(self, "成功", f"缓存区大小已设置为 {size} 个数据点")
        except ValueError:
            QMessageBox.warning(self, "错误", "请输入有效的数字")
    
    def toggle_limit_data(self, checked: bool):
        """切换数据限制开关
        
        Args:
            checked: 是否选中
        """
        self.waveform_widget.set_limit_data(checked)
    
    def toggle_pause(self):
        """切换暂停状态
        
        暂停时：保持连接，图像不打印，保存继续
        取消暂停：曲线从最新接收的数据开始打印
        """
        if self.waveform_widget.is_paused:
            # 取消暂停
            self.waveform_widget.is_paused = False
            self.pause_btn.setText("暂停")
            print("波形显示已恢复")
        else:
            # 暂停
            self.waveform_widget.is_paused = True
            self.pause_btn.setText("继续")
            print("波形显示已暂停（数据继续接收和保存）")
    
    def update_data(self):
        """更新数据"""
        if not self.data_source_manager.is_connected():
            return
        
        # 检查校验头不匹配情况
        header_mismatch_count = self.data_source_manager.get_header_mismatch_count()
        if header_mismatch_count > 0:
            # 校验头不匹配，红色闪烁
            self.connect_btn.set_color(QColor(220, 20, 60))  # 红色
            self.connect_btn.start_flashing(500)  # 500ms闪烁间隔，更明显
            self.data_status_label.setText(f"数据状态: 校验头不匹配 ({header_mismatch_count}次)")
            self.data_status_label.setStyleSheet("color: red;")
        
        # 循环读取所有积压的数据
        while True:
            # 读取数据（返回字典格式）
            data_dict = self.data_source_manager.read_data()
            
            if data_dict is None:
                # 没有更多数据，退出循环
                break
            
            # 如果之前有校验头不匹配，现在收到有效数据，恢复蓝色闪烁
            if header_mismatch_count > 0:
                self.connect_btn.set_color(QColor(100, 149, 237))  # 蓝色
                self.connect_btn.start_flashing(100)  # 蓝色快速闪烁
                self.data_status_label.setText("数据状态: 正常接收")
                self.data_status_label.setStyleSheet("color: green;")
            
            # 收到数据，开始蓝色快速闪烁
            if self.data_count == 0:
                # 第一次收到数据，开始闪烁
                self.connect_btn.set_color(QColor(100, 149, 237))  # 蓝色
                self.connect_btn.start_flashing(100)  # 快速闪烁（200ms）
                self.data_status_label.setText("数据状态: 正常接收")
                self.data_status_label.setStyleSheet("color: green;")
            
            self.data_count += 1
            self.data_count_label.setText(f"接收数据: {self.data_count}")
            
            # 更新最后接收数据的时间
            self.last_data_time = QDateTime.currentMSecsSinceEpoch()
            
            # 获取当前所有通道
            channels = self.data_source_manager.get_channels()
            
            # 更新通道显示
            if channels:
                channels_text = ", ".join(channels)
                self.channels_label.setText(f"检测到通道: {channels_text}")
            
            # 自动创建通道
            # 使用PyQtGraph支持的颜色格式（RGB值或完整颜色名）
            colors = [
                (255, 0, 0),      # 红色
                (0, 255, 0),      # 绿色
                (0, 0, 255),      # 蓝色
                (0, 255, 255),    # 青色
                (255, 0, 255),    # 品红色
                (255, 255, 0),    # 黄色
                (0, 0, 0),        # 黑色
                (255, 165, 0),    # 橙色
                (128, 0, 128),    # 紫色
                (165, 42, 42),    # 棕色
                (255, 192, 203),  # 粉色
                (128, 128, 128),  # 灰色
                (85, 107, 47),    # 橄榄色
                (128, 0, 128),    # 紫色
                (0, 128, 128),    # 蓝绿色
                (0, 128, 128),    # 海军蓝
                (128, 0, 0),      # 栗色
                (0, 255, 255),    # 浅蓝色
                (0, 255, 0),      # 莱檬绿
                (255, 0, 255),    # 紫红色
                (192, 192, 192),  # 银色
                (255, 215, 0),    # 金色
                (75, 0, 130),     # 靛蓝色
                (238, 130, 238),  # 紫罗兰色
                (255, 105, 180),  # 珊瑚色
                (255, 99, 71),    # 焦糖色
                (147, 112, 219),  # 淡紫色
                (64, 224, 208),   # 绿松石色
                (0, 206, 209),    # 深天蓝色
                (255, 228, 225),  # 旧蕾丝色
                (255, 160, 122),  # 浅鲑鱼肉色
                (255, 127, 80),   # 珊瑚色
                (46, 139, 87),    # 海洋绿
                (255, 239, 213),  # 薰荷色
                (255, 182, 193),  # 浅粉色
                (255, 188, 217),  # 淡紫色
                (255, 255, 240),  # 象牙色
                (240, 248, 255),  # 爱丽丝蓝
                (245, 245, 220),  # 米色
                (255, 250, 205),  # 拉斯金
            ]
            for i, channel_name in enumerate(channels):
                if channel_name not in self.waveform_widget.channels:
                    color = colors[i % len(colors)]
                    self.waveform_widget.add_channel(channel_name, color, 2)
            
            # 更新波形显示（使用发送方的时间戳）
            timestamp = data_dict.get('timestamp', 0.0)
            waveform_data = {k: v for k, v in data_dict.items() if k != 'timestamp'}
            self.waveform_widget.update_channels(waveform_data, timestamp)
    
    def check_data_timeout(self):
        """检查数据是否超时"""
        if not self.data_source_manager.is_connected():
            return
        
        if self.last_data_time is not None:
            current_time = QDateTime.currentMSecsSinceEpoch()
            elapsed = current_time - self.last_data_time
            if elapsed > self.data_timeout:
                # 数据超时，停止闪烁，恢复蓝色但不闪烁
                self.connect_btn.set_color(QColor(100, 149, 237))  # 蓝色
                self.connect_btn.stop_flashing()
                self.data_status_label.setText("数据状态: 数据停止")
                self.data_status_label.setStyleSheet("color: #666;")
    
    def show_channel_context_menu(self, position):
        """显示通道右键菜单
        
        Args:
            position: 鼠标位置
        """
        channels = self.waveform_widget.get_all_channels()
        
        if not channels:
            return
        
        # 创建右键菜单
        menu = QMenu(self)
        
        # 添加通道颜色设置菜单项
        color_menu = menu.addMenu("设置通道颜色")
        
        # 为每个通道添加子菜单项
        for channel_name in channels:
            action = QAction(channel_name, self)
            action.triggered.connect(lambda checked, name=channel_name: self.set_channel_color(name))
            color_menu.addAction(action)
        
        # 显示菜单
        menu.exec_(self.channels_label.mapToGlobal(position))
    
    def set_channel_color(self, channel_name: str):
        """设置指定通道的颜色
        
        Args:
            channel_name: 通道名称
        """
        if channel_name not in self.waveform_widget.channels:
            QMessageBox.warning(self, "错误", f"通道 '{channel_name}' 不存在")
            return
        
        # 获取当前颜色
        current_color = self.waveform_widget.channels[channel_name]['color']
        
        # 如果是RGB元组，转换为QColor
        if isinstance(current_color, tuple):
            from PyQt5.QtGui import QColor
            qcolor = QColor(*current_color)
            initial_color = qcolor
        else:
            from PyQt5.QtGui import QColor
            initial_color = QColor(current_color)
        
        # 显示颜色选择对话框
        color = QColorDialog.getColor(initial_color, self, f"选择通道 '{channel_name}' 的颜色")
        
        if color.isValid():
            # 转换为RGB元组
            rgb = (color.red(), color.green(), color.blue())
            
            # 更新通道颜色
            self.waveform_widget.update_channel_color(channel_name, rgb)
            print(f"通道 '{channel_name}' 颜色已更新为: {color.name()} ({rgb})")
        else:
            print(f"通道 '{channel_name}' 颜色设置已取消")
    

    def closeEvent(self, event):
        """关闭事件"""
        self.data_source_manager.disconnect()
        self.waveform_widget.stop_update()
        event.accept()


def main():
    """主函数"""
    app = QApplication(sys.argv)
    
    # 设置应用属性
    app.setApplicationName("Python上位机")
    app.setOrganizationName("MyCompany")
    
    # 创建并显示主窗口
    window = MainWindow()
    window.show()
    
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())