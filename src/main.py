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
                             QGroupBox, QFormLayout, QMessageBox, QFileDialog)
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
        self.header_edit = QLineEdit("DATA")
        self.header_edit.setPlaceholderText("数据校验头")
        
        udp_layout.addRow("主机地址:", self.host_edit)
        udp_layout.addRow("端口:", self.port_edit)
        udp_layout.addRow("数据校验头:", self.header_edit)
        
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
        channel_layout = QVBoxLayout()
        
        self.channels_label = QLabel("自动检测通道...")
        self.channels_label.setStyleSheet("color: #666;")
        
        channel_layout.addWidget(self.channels_label)
        
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
        
        # 数据更新定时器
        self.data_timer = QTimer()
        self.data_timer.timeout.connect(self.update_data)
        self.data_timer.start(50)  # 50ms更新一次
    
    def init_connections(self):
        """初始化连接"""
        # 启动波形显示更新
        self.waveform_widget.start_update()
    
    def connect_udp(self):
        """连接UDP数据源"""
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
                self.connect_btn.setEnabled(False)
                self.disconnect_btn.setEnabled(True)
                
                # 清空旧通道
                self.waveform_widget.clear_all()
                self.channels_label.setText("自动检测通道...")
                
                # 自动开始保存
                save_path = self.save_path_edit.text()
                if save_path:
                    self.data_source_manager.set_save_path(save_path)
                    if self.data_source_manager.start_saving():
                        self.save_btn.setText("停止保存")
                        save_file = self.data_source_manager.get_save_file()
                        self.save_file_label.setText(f"保存文件: {save_file}")
                        self.auto_save_enabled = True
                
                QMessageBox.information(self, "成功", f"已连接到 {host}:{port}\n数据校验头: {header}")
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
        self.save_file_label.setText("保存文件: 无")
        self.channels_label.setText("自动检测通道...")
        self.save_btn.setText("开始保存")
    
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
    
    def update_data(self):
        """更新数据"""
        if not self.data_source_manager.is_connected():
            return
        
        # 读取数据（返回字典格式）
        data_dict = self.data_source_manager.read_data()
        
        if data_dict is not None:
            self.data_count += 1
            self.data_count_label.setText(f"接收数据: {self.data_count}")
            
            # 获取当前所有通道
            channels = self.data_source_manager.get_channels()
            
            # 更新通道显示
            if channels:
                channels_text = ", ".join(channels)
                self.channels_label.setText(f"检测到通道: {channels_text}")
            
            # 自动创建通道
            colors = ['r', 'g', 'b', 'c', 'm', 'y', 'k', 'w']
            for i, channel_name in enumerate(channels):
                if channel_name not in self.waveform_widget.channels:
                    color = colors[i % len(colors)]
                    self.waveform_widget.add_channel(channel_name, color, 2)
            
            # 更新波形显示（使用发送方的时间戳）
            timestamp = data_dict.get('timestamp', 0.0)
            waveform_data = {k: v for k, v in data_dict.items() if k != 'timestamp'}
            self.waveform_widget.update_channels(waveform_data, timestamp)
    
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