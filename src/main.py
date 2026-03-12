"""
Python上位机主程序

支持UDP数据源和实时波形显示的上位机软件。

使用方法:
    python src/main.py
"""

import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                             QGroupBox, QFormLayout, QMessageBox)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont

from data_sources.manager import DataSourceManager, create_udp_source
from visualization.waveform_widget import WaveformWidget


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
        
        udp_layout.addRow("主机地址:", self.host_edit)
        udp_layout.addRow("端口:", self.port_edit)
        
        self.connect_btn = QPushButton("连接")
        self.connect_btn.clicked.connect(self.connect_udp)
        self.disconnect_btn = QPushButton("断开")
        self.disconnect_btn.clicked.connect(self.disconnect_udp)
        self.disconnect_btn.setEnabled(False)
        
        udp_layout.addRow(self.connect_btn)
        udp_layout.addRow(self.disconnect_btn)
        
        udp_group.setLayout(udp_layout)
        layout.addWidget(udp_group)
        
        # 通道配置组
        channel_group = QGroupBox("通道配置")
        channel_layout = QFormLayout()
        
        self.channel_name_edit = QLineEdit("ch1")
        self.channel_color_edit = QLineEdit("r")
        
        channel_layout.addRow("通道名称:", self.channel_name_edit)
        channel_layout.addRow("颜色 (r/g/b/c/m/y):", self.channel_color_edit)
        
        add_channel_btn = QPushButton("添加通道")
        add_channel_btn.clicked.connect(self.add_channel)
        channel_layout.addRow(add_channel_btn)
        
        clear_channels_btn = QPushButton("清空所有通道")
        clear_channels_btn.clicked.connect(self.clear_all_channels)
        channel_layout.addRow(clear_channels_btn)
        
        channel_group.setLayout(channel_layout)
        layout.addWidget(channel_group)
        
        # 状态显示
        status_group = QGroupBox("状态")
        status_layout = QVBoxLayout()
        
        self.status_label = QLabel("未连接")
        self.status_label.setStyleSheet("color: red;")
        self.data_count_label = QLabel("接收数据: 0")
        
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.data_count_label)
        
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
        
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
        
        # 数据更新定时器
        self.data_timer = QTimer()
        self.data_timer.timeout.connect(self.update_data)
        self.data_timer.start(50)  # 50ms更新一次
    
    def init_connections(self):
        """初始化连接"""
        # 默认添加一些通道
        self.waveform_widget.add_channel("ch1", "r", 2)
        self.waveform_widget.add_channel("ch2", "g", 2)
        self.waveform_widget.add_channel("ch3", "b", 2)
        
        # 启动波形显示更新
        self.waveform_widget.start_update()
    
    def connect_udp(self):
        """连接UDP数据源"""
        try:
            host = self.host_edit.text()
            port = int(self.port_edit.text())
            
            udp_source = create_udp_source(host, port)
            success = self.data_source_manager.set_source(udp_source)
            
            if success:
                self.status_label.setText("已连接")
                self.status_label.setStyleSheet("color: green;")
                self.connect_btn.setEnabled(False)
                self.disconnect_btn.setEnabled(True)
                QMessageBox.information(self, "成功", f"已连接到 {host}:{port}")
            else:
                QMessageBox.warning(self, "失败", "连接失败，请检查配置")
        except ValueError:
            QMessageBox.warning(self, "错误", "请输入有效的端口号")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"连接失败: {str(e)}")
    
    def disconnect_udp(self):
        """断开UDP连接"""
        self.data_source_manager.disconnect()
        self.status_label.setText("未连接")
        self.status_label.setStyleSheet("color: red;")
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
        self.data_count = 0
        self.data_count_label.setText("接收数据: 0")
    
    def add_channel(self):
        """添加通道"""
        name = self.channel_name_edit.text()
        color = self.channel_color_edit.text()
        
        if not name:
            QMessageBox.warning(self, "警告", "请输入通道名称")
            return
        
        self.waveform_widget.add_channel(name, color, 2)
        QMessageBox.information(self, "成功", f"通道 {name} 已添加")
    
    def clear_all_channels(self):
        """清空所有通道"""
        self.waveform_widget.clear_all()
        self.data_count = 0
        self.data_count_label.setText("接收数据: 0")
    
    def update_data(self):
        """更新数据"""
        if not self.data_source_manager.is_connected():
            return
        
        data = self.data_source_manager.read_data()
        
        if data is not None and len(data) > 0:
            self.data_count += 1
            self.data_count_label.setText(f"接收数据: {self.data_count}")
            
            # 将数据分发到各个通道
            data_dict = {}
            for i, value in enumerate(data):
                channel_name = f"ch{i+1}"
                if channel_name in self.waveform_widget.channels:
                    data_dict[channel_name] = value
            
            # 更新波形显示
            self.waveform_widget.update_channels(data_dict)
    
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