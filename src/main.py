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
                             QGroupBox, QFormLayout, QMessageBox, QFileDialog, QCheckBox, QColorDialog, QMenu, QAction, QShortcut, QComboBox, QTextEdit, QSplitter, QInputDialog)
from PyQt5.QtCore import Qt, QTimer, QDateTime, QSize
from PyQt5.QtCore import Qt, QTimer, QDateTime
from PyQt5.QtGui import QFont, QPainter, QColor, QPen, QBrush, QRadialGradient, QKeySequence

from data_sources.manager import DataSourceManager, create_udp_source
from visualization.waveform_widget import WaveformWidget
from enum import Enum


class ConnectionState(Enum):
    """连接状态枚举"""
    DISCONNECTED = "未连接"
    CONNECTED_WAITING = "已连接-等待数据"
    CONNECTED_RECEIVING = "已连接-接收数据"
    DATA_FORMAT_MISMATCH = "数据格式不匹配"
    DATA_STOPPED = "数据停止"
    PAUSED = "暂停"


class State:
    """状态基类"""
    
    def __init__(self, state_machine: 'StateMachine'):
        self.state_machine = state_machine
    
    def enter(self) -> None:
        """进入状态时调用"""
        pass
    
    def exit(self) -> None:
        """退出状态时调用"""
        pass
    
    def handle_event(self, event: str, **kwargs) -> None:
        """处理事件
        
        Args:
            event: 事件名称
            **kwargs: 事件参数
        """
        pass


class DisconnectedState(State):
    """未连接状态"""
    
    def enter(self) -> None:
        """进入状态"""
        context = self.state_machine.context
        # 更新UI
        context.connect_btn.set_color(QColor(100, 100, 100))  # 灰色
        context.connect_btn.stop_flashing()
        context.data_status_label.setText("数据状态: 无数据")
        context.data_status_label.setStyleSheet("color: #666;")
        print(f"[状态] 进入未连接状态")
    
    def handle_event(self, event: str, **kwargs) -> None:
        """处理事件"""
        if event == 'connect':
            self.state_machine.transition_to(ConnectedWaitingState(self.state_machine))


class ConnectedWaitingState(State):
    """已连接-等待数据状态"""
    
    def enter(self) -> None:
        """进入状态"""
        context = self.state_machine.context
        # 更新UI
        context.connect_btn.set_color(QColor(100, 149, 237))  # 蓝色
        context.connect_btn.stop_flashing()
        context.data_status_label.setText("数据状态: 等待数据")
        context.data_status_label.setStyleSheet("color: #666;")
        print(f"[状态] 进入等待数据状态")
    
    def handle_event(self, event: str, **kwargs) -> None:
        """处理事件"""
        if event == 'data_received':
            self.state_machine.transition_to(ConnectedReceivingState(self.state_machine))
        elif event == 'format_error':
            self.state_machine.transition_to(DataFormatMismatchState(self.state_machine))
        elif event == 'disconnect':
            self.state_machine.transition_to(DisconnectedState(self.state_machine))


class ConnectedReceivingState(State):
    """已连接-接收数据状态"""
    
    def enter(self) -> None:
        """进入状态"""
        context = self.state_machine.context
        # 更新UI
        context.connect_btn.set_color(QColor(100, 149, 237))  # 蓝色
        context.connect_btn.start_flashing(100)  # 100ms闪烁
        context.data_status_label.setText("数据状态: 正常接收")
        context.data_status_label.setStyleSheet("color: green;")
        print(f"[状态] 进入接收数据状态")
    
    def handle_event(self, event: str, **kwargs) -> None:
        """处理事件"""
        if event == 'timeout':
            self.state_machine.transition_to(DataStoppedState(self.state_machine))
        elif event == 'format_error':
            self.state_machine.transition_to(DataFormatMismatchState(self.state_machine))
        elif event == 'pause':
            self.state_machine.transition_to(PausedState(self.state_machine))
        elif event == 'disconnect':
            self.state_machine.transition_to(DisconnectedState(self.state_machine))


class DataFormatMismatchState(State):
    """数据格式不匹配状态"""
    
    def __init__(self, state_machine: 'StateMachine'):
        super().__init__(state_machine)
        self.mismatch_count = 0
    
    def enter(self) -> None:
        """进入状态"""
        context = self.state_machine.context
        # 更新UI
        context.connect_btn.set_color(QColor(220, 20, 60))  # 红色
        context.connect_btn.start_flashing(500)  # 500ms闪烁
        context.data_status_label.setText(f"数据状态: 数据格式不匹配 ({self.mismatch_count}次)")
        context.data_status_label.setStyleSheet("color: red;")
        print(f"[状态] 进入数据格式不匹配状态，次数: {self.mismatch_count}")
    
    def handle_event(self, event: str, **kwargs) -> None:
        """处理事件"""
        if event == 'data_received':
            self.state_machine.transition_to(ConnectedReceivingState(self.state_machine))
        elif event == 'timeout':
            self.state_machine.transition_to(DataStoppedState(self.state_machine))
        elif event == 'format_error':
            # 更新不匹配次数
            self.mismatch_count = kwargs.get('mismatch_count', self.mismatch_count + 1)
            # 更新UI
            context = self.state_machine.context
            context.data_status_label.setText(f"数据状态: 数据格式不匹配 ({self.mismatch_count}次)")
            print(f"[状态] 更新数据格式不匹配次数: {self.mismatch_count}")
        elif event == 'disconnect':
            self.state_machine.transition_to(DisconnectedState(self.state_machine))


class DataStoppedState(State):
    """数据停止状态"""
    
    def enter(self) -> None:
        """进入状态"""
        context = self.state_machine.context
        # 更新UI
        context.connect_btn.set_color(QColor(100, 149, 237))  # 蓝色
        context.connect_btn.stop_flashing()
        context.data_status_label.setText("数据状态: 数据停止")
        context.data_status_label.setStyleSheet("color: #666;")
        print(f"[状态] 进入数据停止状态")
    
    def handle_event(self, event: str, **kwargs) -> None:
        """处理事件"""
        if event == 'data_received':
            self.state_machine.transition_to(ConnectedReceivingState(self.state_machine))
        elif event == 'format_error':
            self.state_machine.transition_to(DataFormatMismatchState(self.state_machine))
        elif event == 'disconnect':
            self.state_machine.transition_to(DisconnectedState(self.state_machine))


class PausedState(State):
    """暂停状态"""
    
    def enter(self) -> None:
        """进入状态"""
        context = self.state_machine.context
        # 更新UI
        context.connect_btn.set_color(QColor(100, 149, 237))  # 蓝色
        context.connect_btn.stop_flashing()
        context.data_status_label.setText("数据状态: 已暂停")
        context.data_status_label.setStyleSheet("color: #666;")
        print(f"[状态] 进入暂停状态")
    
    def handle_event(self, event: str, **kwargs) -> None:
        """处理事件"""
        if event == 'resume':
            self.state_machine.transition_to(ConnectedReceivingState(self.state_machine))
        elif event == 'disconnect':
            self.state_machine.transition_to(DisconnectedState(self.state_machine))


class StateMachine:
    """有限状态机"""
    
    def __init__(self, context: 'MainWindow'):
        self.context = context
        self.current_state = None
        # 初始状态为未连接
        self.transition_to(DisconnectedState(self))
    
    def transition_to(self, new_state: State) -> None:
        """转换到新状态
        
        Args:
            new_state: 新状态
        """
        if self.current_state:
            print(f"[状态机] 退出状态: {self.current_state.__class__.__name__}")
            self.current_state.exit()
        
        print(f"[状态机] 进入状态: {new_state.__class__.__name__}")
        self.current_state = new_state
        self.current_state.enter()
    
    def handle_event(self, event: str, **kwargs) -> None:
        """处理事件
        
        Args:
            event: 事件名称
            **kwargs: 事件参数
        """
        print(f"[状态机] 处理事件: {event}, 参数: {kwargs}")
        if self.current_state:
            self.current_state.handle_event(event, **kwargs)
    
    def get_current_state_name(self) -> str:
        """获取当前状态名称
        
        Returns:
            当前状态名称
        """
        if self.current_state:
            return self.current_state.__class__.__name__
        return "None"
    
    def is_connected(self) -> bool:
        """是否已连接
        
        Returns:
            True表示已连接，False表示未连接
        """
        return not isinstance(self.current_state, DisconnectedState)
    
    def is_receiving(self) -> bool:
        """是否正在接收数据
        
        Returns:
            True表示正在接收数据，False表示未接收
        """
        return isinstance(self.current_state, ConnectedReceivingState)
    
    def is_paused(self) -> bool:
        """是否暂停
        
        Returns:
            True表示暂停，False表示未暂停
        """
        return isinstance(self.current_state, PausedState)


class ConnectionStateManager:
    """连接状态管理器 - 管理所有状态转换和UI更新"""
    
    def __init__(self, connect_btn: 'CircularButton', data_status_label: QLabel):
        """初始化状态管理器
        
        Args:
            connect_btn: 连接按钮
            data_status_label: 数据状态标签
        """
        self.connect_btn = connect_btn
        self.data_status_label = data_status_label
        self.current_state = ConnectionState.DISCONNECTED
        
        # 状态配置
        self.state_config = {
            ConnectionState.DISCONNECTED: {
                'button_color': QColor(100, 100, 100),  # 灰色
                'flashing': False,
                'flash_interval': 0,
                'data_status_text': '数据状态: 无数据',
                'data_status_color': '#666'
            },
            ConnectionState.CONNECTED_WAITING: {
                'button_color': QColor(100, 149, 237),  # 蓝色
                'flashing': False,
                'flash_interval': 0,
                'data_status_text': '数据状态: 等待数据',
                'data_status_color': '#666'
            },
            ConnectionState.CONNECTED_RECEIVING: {
                'button_color': QColor(100, 149, 237),  # 蓝色
                'flashing': True,
                'flash_interval': 100,
                'data_status_text': '数据状态: 正常接收',
                'data_status_color': 'green'
            },
            ConnectionState.DATA_FORMAT_MISMATCH: {
                'button_color': QColor(220, 20, 60),  # 红色
                'flashing': True,
                'flash_interval': 500,
                'data_status_text': '数据状态: 数据格式不匹配',
                'data_status_color': 'red'
            },
            ConnectionState.DATA_STOPPED: {
                'button_color': QColor(100, 149, 237),  # 蓝色
                'flashing': False,
                'flash_interval': 0,
                'data_status_text': '数据状态: 数据停止',
                'data_status_color': '#666'
            },
            ConnectionState.PAUSED: {
                'button_color': QColor(100, 149, 237),  # 蓝色
                'flashing': False,
                'flash_interval': 0,
                'data_status_text': '数据状态: 已暂停',
                'data_status_color': '#666'
            }
        }
    
    def transition_to(self, new_state: ConnectionState, **kwargs):
        """转换到新状态
        
        Args:
            new_state: 新状态
            **kwargs: 额外参数（如数据格式不匹配次数）
        """
        print(f"[状态转换] 当前状态: {self.current_state}, 新状态: {new_state}")
        if new_state == self.current_state:
            # 状态相同，只更新动态内容
            self._update_dynamic_content(new_state, **kwargs)
            return
        
        # 状态不同，执行完整的状态转换
        self.current_state = new_state
        config = self.state_config[new_state]
        
        print(f"[状态转换] 执行状态转换: {new_state}")
        
        # 更新按钮
        self.connect_btn.set_color(config['button_color'])
        if config['flashing']:
            self.connect_btn.start_flashing(config['flash_interval'])
        else:
            self.connect_btn.stop_flashing()
        
        # 更新数据状态标签
        self.data_status_label.setText(config['data_status_text'])
        self.data_status_label.setStyleSheet(f"color: {config['data_status_color']};")
        
        # 更新动态内容
        self._update_dynamic_content(new_state, **kwargs)
    
    def _update_dynamic_content(self, state: ConnectionState, **kwargs):
        """更新动态内容
        
        Args:
            state: 当前状态
            **kwargs: 额外参数
        """
        if state == ConnectionState.DATA_FORMAT_MISMATCH:
            # 更新数据格式不匹配次数
            mismatch_count = kwargs.get('mismatch_count', 0)
            if mismatch_count > 0:
                self.data_status_label.setText(f"数据状态: 数据格式不匹配 ({mismatch_count}次)")
    
    def get_current_state(self) -> ConnectionState:
        """获取当前状态
        
        Returns:
            当前状态
        """
        return self.current_state
    
    def is_connected(self) -> bool:
        """是否已连接
        
        Returns:
            True表示已连接，False表示未连接
        """
        return self.current_state != ConnectionState.DISCONNECTED
    
    def is_receiving(self) -> bool:
        """是否正在接收数据
        
        Returns:
            True表示正在接收数据，False表示未接收
        """
        return self.current_state == ConnectionState.CONNECTED_RECEIVING
    
    def is_paused(self) -> bool:
        """是否暂停
        
        Returns:
            True表示暂停，False表示未暂停
        """
        return self.current_state == ConnectionState.PAUSED



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
        self.setWindowTitle("Python上位机 - 数据采集")
        self.setGeometry(100, 100, 1400, 800)
        
        # 创建中央控件
        central_widget = QWidget()
        main_layout = QHBoxLayout()
        
        # 左侧控制面板
        control_panel = self.create_control_panel()
        
        # 右侧面板（使用QSplitter支持调整大小）
        right_splitter = QSplitter(Qt.Vertical)
        
        # 右侧上部：波形显示
        self.waveform_widget = WaveformWidget()
        
        # 右侧下部：原始数据接收区
        raw_data_panel = self.create_raw_data_panel()
        
        # 添加到分割器
        right_splitter.addWidget(self.waveform_widget)
        right_splitter.addWidget(raw_data_panel)
        
        # 设置初始比例（波形显示占70%，原始数据接收区占30%）
        right_splitter.setStretchFactor(0, 7)
        right_splitter.setStretchFactor(1, 3)
        
        # 设置最小尺寸，防止一个被压缩消失
        right_splitter.setChildrenCollapsible(False)  # 禁止折叠
        right_splitter.setHandleWidth(5)  # 设置分割线宽度
        
        # 设置子控件的最小尺寸
        self.waveform_widget.setMinimumSize(QSize(200, 200))  # 波形显示最小尺寸
        raw_data_panel.setMinimumSize(QSize(200, 100))  # 原始数据接收区最小尺寸
        
        # 添加到主布局
        main_layout.addWidget(control_panel, 1)
        main_layout.addWidget(right_splitter, 3)
        
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
        
        # 数据源类型选择
        source_group = QGroupBox("数据源")
        source_layout = QFormLayout()
        
        self.source_type_combo = QComboBox()
        self.source_type_combo.addItems(["UDP", "串口"])
        self.source_type_combo.currentTextChanged.connect(self.on_source_type_changed)
        source_layout.addRow("数据源类型:", self.source_type_combo)
        
        source_group.setLayout(source_layout)
        layout.addWidget(source_group)
        
        # UDP配置组
        self.udp_group = QGroupBox("UDP配置")
        udp_layout = QFormLayout()
        
        self.host_edit = QLineEdit("0.0.0.0")
        self.port_edit = QLineEdit("8888")
        
        udp_layout.addRow("主机地址:", self.host_edit)
        udp_layout.addRow("端口:", self.port_edit)
        
        self.udp_group.setLayout(udp_layout)
        layout.addWidget(self.udp_group)
        
        # 串口配置组
        self.serial_group = QGroupBox("串口配置")
        serial_layout = QFormLayout()
        
        self.serial_port_combo = QComboBox()
        self.refresh_serial_ports()
        self.serial_port_combo.showPopup = self.refresh_serial_ports_and_show_popup
        self.baudrate_combo = QComboBox()
        self.baudrate_combo.addItems(["9600", "19200", "38400", "57600", "115200"])
        self.baudrate_combo.setCurrentText("115200")
        self.protocol_combo = QComboBox()
        self.protocol_combo.addItems(["文本协议", "Justfloat", "Rawdata"])
        self.protocol_combo.setCurrentText("文本协议")
        self.protocol_combo.currentTextChanged.connect(self.on_protocol_changed)
        
        serial_layout.addRow("串口号:", self.serial_port_combo)
        serial_layout.addRow("波特率:", self.baudrate_combo)
        serial_layout.addRow("通信协议:", self.protocol_combo)
        
        # 隐藏串口配置组
        self.serial_group.setVisible(False)
        
        self.serial_group.setLayout(serial_layout)
        layout.addWidget(self.serial_group)
        
        # 数据校验头配置（公用的）
        self.header_group = QGroupBox("数据校验头配置")
        header_layout = QFormLayout()
        
        self.header_edit = QLineEdit("DATA")
        self.header_edit.setPlaceholderText("数据校验头")
        
        header_layout.addRow("数据校验头:", self.header_edit)
        
        self.header_group.setLayout(header_layout)
        layout.addWidget(self.header_group)
        
        # 连接控制组（公用的）
        control_group = QGroupBox("连接控制")
        control_layout = QVBoxLayout()
        
        # 圆形连接按钮
        button_layout = QHBoxLayout()
        self.connect_btn = CircularButton()
        self.connect_btn.clicked.connect(self.toggle_connection)
        button_layout.addWidget(self.connect_btn)
        button_layout.addStretch()
        control_layout.addLayout(button_layout)
        
        # 数据状态标签
        self.data_status_label = QLabel("数据状态: 无数据")
        self.data_status_label.setStyleSheet("color: #666;")
        control_layout.addWidget(self.data_status_label)
        
        # 暂停按钮
        self.pause_btn = QPushButton("暂停")
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.pause_btn.setEnabled(False)
        control_layout.addWidget(self.pause_btn)
        
        control_group.setLayout(control_layout)
        layout.addWidget(control_group)
        
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
    
    def create_raw_data_panel(self):
        """创建原始数据接收区面板"""
        panel = QWidget()
        layout = QVBoxLayout()
        
        # 原始数据接收区
        raw_data_group = QGroupBox("原始数据接收区")
        raw_data_layout = QVBoxLayout()
        
        # 编码格式和显示格式选择
        format_layout = QHBoxLayout()
        
        encoding_label = QLabel("编码格式:")
        self.encoding_combo = QComboBox()
        self.encoding_combo.addItems(["UTF-8", "GBK"])
        self.encoding_combo.setCurrentText("UTF-8")
        
        display_label = QLabel("显示格式:")
        self.display_format_combo = QComboBox()
        self.display_format_combo.addItems(["文本", "十六进制"])
        self.display_format_combo.setCurrentText("文本")
        
        format_layout.addWidget(encoding_label)
        format_layout.addWidget(self.encoding_combo)
        format_layout.addWidget(display_label)
        format_layout.addWidget(self.display_format_combo)
        raw_data_layout.addLayout(format_layout)
        
        # 原始数据显示区域
        self.raw_data_text = QTextEdit()
        self.raw_data_text.setReadOnly(True)
        self.raw_data_text.setStyleSheet("font-family: Consolas, monospace; font-size: 10pt;")
        raw_data_layout.addWidget(self.raw_data_text)
        
        # 清空按钮
        clear_raw_data_btn = QPushButton("清空原始数据")
        clear_raw_data_btn.clicked.connect(self.clear_raw_data)
        raw_data_layout.addWidget(clear_raw_data_btn)
        
        raw_data_group.setLayout(raw_data_layout)
        layout.addWidget(raw_data_group)
        
        panel.setLayout(layout)
        return panel
    
    def init_components(self):
        """初始化组件"""
        self.data_source_manager = DataSourceManager()
        self.data_count = 0
        self.auto_save_enabled = False
        self.last_data_time = None  # 记录最后接收数据的时间
        self.data_timeout = 1000  # 数据超时时间（毫秒）
        
        # 初始化状态机
        self.state_machine = StateMachine(self)
        
        # 定义断开回调函数
        def on_disconnect():
            """数据源断开回调"""
            print("[断开回调] 数据源已断开")
            # 更新UI状态
            self.status_label.setText("未连接")
            self.status_label.setStyleSheet("color: red;")
            self.pause_btn.setEnabled(False)
            # 启用数据源类型选择
            self.source_type_combo.setEnabled(True)
            self.data_count = 0
            self.data_count_label.setText("接收数据: 0")
            self.save_file_label.setText("保存文件: 无")
            self.channels_label.setText("自动检测通道...")
            self.save_btn.setText("开始保存")
            self.auto_save_enabled = False
            self.clear_raw_data()  # 清空原始数据接收区
            # 重置last_data_time
            self.last_data_time = None
            # 转换到未连接状态
            self.state_machine.handle_event('disconnect')
        
        # 保存断开回调函数
        self.disconnect_callback = on_disconnect
        
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
        
        # 设置空格键快捷键为暂停/继续
        self.space_shortcut = QShortcut(QKeySequence(Qt.Key_Space), self)
        self.space_shortcut.activated.connect(self.toggle_pause)
    
    def toggle_connection(self):
        """切换连接/断开状态"""
        if self.data_source_manager.is_connected():
            # 断开连接
            self.data_source_manager.disconnect()
            self.status_label.setText("未连接")
            self.status_label.setStyleSheet("color: red;")
            self.pause_btn.setEnabled(False)
            # 启用数据源类型选择
            self.source_type_combo.setEnabled(True)
            self.data_count = 0
            self.data_count_label.setText("接收数据: 0")
            self.save_file_label.setText("保存文件: 无")
            self.channels_label.setText("自动检测通道...")
            self.save_btn.setText("开始保存")
            self.auto_save_enabled = False
            self.clear_raw_data()  # 清空原始数据接收区
            
            # 转换到未连接状态
            self.state_machine.handle_event('disconnect')
            # 重置last_data_time，避免check_data_timeout继续检测超时
            self.last_data_time = None
            print("数据源已断开")
        else:
            # 连接
            try:
                source_type = self.source_type_combo.currentText()
                header = self.header_edit.text().strip() or 'DATA'
                
                # 设置数据校验头
                self.data_source_manager.set_data_header(header)
                
                if source_type == "UDP":
                    # UDP数据源
                    host = self.host_edit.text()
                    port = int(self.port_edit.text())
                    data_source = create_udp_source(host, port)
                    # 设置原始数据回调函数
                    data_source.set_raw_data_callback(self.on_raw_data_received)
                    # 设置断开回调函数
                    data_source.set_disconnect_callback(self.disconnect_callback)
                    success = self.data_source_manager.set_source(data_source)
                    
                    if success:
                        print(f"已连接到UDP {host}:{port}，数据校验头: {header}")
                else:
                    # 串口数据源
                    from data_sources.manager import create_serial_source
                    serial_port = self.serial_port_combo.currentData()  # 获取实际的串口号（如COM1）
                    if not serial_port:
                        QMessageBox.warning(self, "错误", "请选择有效的串口")
                        return
                    baudrate = int(self.baudrate_combo.currentText())
                    protocol_text = self.protocol_combo.currentText()
                    # 根据协议类型使用不同的数据校验头
                    if protocol_text == '文本协议':
                        protocol = 'text'
                        serial_header = header  # 文本协议使用公用的数据校验头
                    elif protocol_text == 'Justfloat':
                        protocol = 'justfloat'
                        serial_header = ''  # Justfloat不使用数据校验头
                    else:  # Rawdata
                        protocol = 'rawdata'
                        serial_header = ''  # Rawdata不使用数据校验头
                    data_source = create_serial_source(serial_port, baudrate, protocol, serial_header)
                    # 设置原始数据回调函数
                    data_source.set_raw_data_callback(self.on_raw_data_received)
                    # 设置断开回调函数
                    data_source.set_disconnect_callback(self.disconnect_callback)
                    success = self.data_source_manager.set_source(data_source)
                    
                    if success:
                        if protocol == 'text':
                            print(f"已连接到串口 {serial_port} @ {baudrate}bps，协议: {protocol_text}，数据校验头: {serial_header}")
                        else:
                            print(f"已连接到串口 {serial_port} @ {baudrate}bps，协议: {protocol_text}")
                
                if success:
                    self.status_label.setText("已连接")
                    self.status_label.setStyleSheet("color: green;")
                    self.pause_btn.setEnabled(True)
                    # 禁用数据源类型选择
                    self.source_type_combo.setEnabled(False)
                    
                    # 清空旧通道
                    self.waveform_widget.clear_all()
                    self.channels_label.setText("自动检测通道...")
                    
                    # 重置校验头不匹配计数器
                    self.data_source_manager.reset_header_mismatch_count()
                    
                    # 转换到已连接-等待数据状态
                    self.state_machine.handle_event('connect')
                    
                    # 自动开始保存
                    save_path = self.save_path_edit.text()
                    if save_path:
                        self.data_source_manager.set_save_path(save_path)
                        if self.data_source_manager.start_saving():
                            self.save_btn.setText("停止保存")
                            save_file = self.data_source_manager.get_save_file()
                            self.save_file_label.setText(f"保存文件: {save_file}")
                            self.auto_save_enabled = True
                else:
                    QMessageBox.warning(self, "失败", "连接失败，请检查配置")
            except ValueError:
                QMessageBox.warning(self, "错误", "请输入有效的端口号或波特率")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"连接失败: {str(e)}")
    
    def on_source_type_changed(self, source_type: str):
        """数据源类型改变事件处理
        
        Args:
            source_type: 数据源类型（UDP或串口）
        """
        if source_type == "UDP":
            self.udp_group.setVisible(True)
            self.serial_group.setVisible(False)
            # UDP模式：启用数据校验头配置
            self.header_group.setEnabled(True)
        else:
            self.udp_group.setVisible(False)
            self.serial_group.setVisible(True)
            # 根据协议类型控制数据校验头配置的启用/禁用
            self.on_protocol_changed(self.protocol_combo.currentText())
    
    def refresh_serial_ports(self):
        """刷新串口列表，扫描所有可用的COM端口"""
        try:
            import serial.tools.list_ports
            
            # 获取所有可用的串口
            ports = serial.tools.list_ports.comports()
            
            # 清空当前列表
            self.serial_port_combo.clear()
            
            if ports:
                # 添加所有可用的串口
                for port in ports:
                    port_info = f"{port.device} - {port.description}"
                    self.serial_port_combo.addItem(port_info, port.device)
                print(f"扫描到 {len(ports)} 个串口")
            else:
                # 没有找到串口
                self.serial_port_combo.addItem("无可用串口", "")
                print("未扫描到可用串口")
        except ImportError:
            # pyserial未安装
            self.serial_port_combo.clear()
            self.serial_port_combo.addItem("请安装pyserial库", "")
            print("错误: 未安装pyserial库，请运行: pip install pyserial")
        except Exception as e:
            # 扫描失败
            self.serial_port_combo.clear()
            self.serial_port_combo.addItem("扫描失败", "")
            print(f"扫描串口失败: {e}")
    
    def refresh_serial_ports_and_show_popup(self):
        """刷新串口列表并显示下拉框"""
        self.refresh_serial_ports()
        QComboBox.showPopup(self.serial_port_combo)
    
    def on_protocol_changed(self, protocol_text: str):
        """串口协议改变事件处理
        
        Args:
            protocol_text: 协议文本（文本协议、Justfloat、Rawdata）
        """
        if protocol_text == "文本协议":
            # 文本协议：启用数据校验头配置
            self.header_group.setEnabled(True)
        else:
            # Justfloat和Rawdata：禁用数据校验头配置
            self.header_group.setEnabled(False)
    
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
    
    def on_raw_data_received(self, data: bytes):
        """原始数据接收回调
        
        Args:
            data: 原始字节数据
        """
        # 暂停时不刷新原始数据栏
        if self.waveform_widget.is_paused:
            return
        
        try:
            encoding = self.encoding_combo.currentText().replace('-', '').lower()
            display_format = self.display_format_combo.currentText()
            
            if display_format == "文本":
                # 文本格式显示
                try:
                    text = data.decode(encoding)
                    self.raw_data_text.append(text)
                except UnicodeDecodeError:
                    # 解码失败，检查是否是二进制数据
                    if self._is_binary_data(data):
                        # 二进制数据，显示提示信息
                        self.raw_data_text.append("[二进制数据 - 请切换到十六进制格式查看]\n")
                    else:
                        # 非二进制数据，显示错误信息
                        self.raw_data_text.append(f"[解码失败: {data.hex()}]\n")
            else:
                # 十六进制格式显示
                hex_str = data.hex(' ').upper()
                self.raw_data_text.append(f"{hex_str}\n")
            
            # 限制显示行数，避免内存占用过大
            max_lines = 1000
            document = self.raw_data_text.document()
            if document.blockCount() > max_lines:
                cursor = self.raw_data_text.textCursor()
                cursor.movePosition(cursor.Start)
                cursor.movePosition(cursor.Down, cursor.KeepAnchor, document.blockCount() - max_lines)
                cursor.removeSelectedText()
            
            # 自动滚动到底部
            scrollbar = self.raw_data_text.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
        except Exception as e:
            print(f"显示原始数据失败: {e}")
    
    def _is_binary_data(self, data: bytes) -> bool:
        """判断数据是否是二进制数据
        
        Args:
            data: 原始字节数据
        
        Returns:
            True表示是二进制数据，False表示是文本数据
        """
        if not data:
            return False
        
        # 检查前100个字节（或全部字节，如果少于100个）
        sample_size = min(100, len(data))
        sample = data[:sample_size]
        
        # 统计不可打印字符的数量
        non_printable_count = 0
        for byte in sample:
            # ASCII码小于32（除了\t, \n, \r）或大于126的字符被认为是不可打印的
            if byte < 32 and byte not in (9, 10, 13):
                non_printable_count += 1
            elif byte > 126:
                non_printable_count += 1
        
        # 如果不可打印字符超过20%，认为是二进制数据
        return non_printable_count / sample_size > 0.2
    
    def clear_raw_data(self):
        """清空原始数据"""
        self.raw_data_text.clear()
    
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
            # 触发resume事件
            print("波形显示已恢复")
            self.state_machine.handle_event('resume')
        else:
            # 暂停
            self.waveform_widget.is_paused = True
            self.pause_btn.setText("继续")
            # 触发pause事件
            print("波形显示已暂停（数据继续接收和保存）")
            self.state_machine.handle_event('pause')
    
    def update_data(self):
        """更新数据"""
        if not self.state_machine.is_connected():
            return
        
        # 循环读取所有积压的数据
        while True:
            # 读取数据（返回字典格式）
            data_dict = self.data_source_manager.read_data()
            
            if data_dict is None:
                # 没有更多数据，退出循环
                break
            
            print(f"[update_data] 收到数据: {data_dict}")
            
            # 检查是否是格式错误标识
            if data_dict.get('format_error'):
                # 格式错误，触发format_error事件
                header_mismatch_count = self.data_source_manager.get_header_mismatch_count()
                print(f"[update_data] 格式错误，触发format_error事件，header_mismatch_count: {header_mismatch_count}")
                self.state_machine.handle_event('format_error', mismatch_count=header_mismatch_count)
                continue
            
            # 检查数据格式不匹配情况（在读取数据后检查）
            header_mismatch_count = self.data_source_manager.get_header_mismatch_count()
            print(f"[update_data] header_mismatch_count: {header_mismatch_count}")
            
            if header_mismatch_count > 0:
                # 数据格式不匹配，触发format_error事件
                print(f"[update_data] 数据格式不匹配，触发format_error事件")
                self.state_machine.handle_event('format_error', mismatch_count=header_mismatch_count)
                continue
            
            # 数据格式正确，触发data_received事件
            print(f"[update_data] 数据格式正确，触发data_received事件")
            self.state_machine.handle_event('data_received')
            
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
        # 只在连接状态下才检查超时
        if not self.state_machine.is_connected():
            return
        
        if self.last_data_time is not None:
            current_time = QDateTime.currentMSecsSinceEpoch()
            elapsed = current_time - self.last_data_time
            if elapsed > self.data_timeout:
                # 数据超时，触发timeout事件
                print(f"[check_data_timeout] 数据超时，触发timeout事件")
                self.state_machine.handle_event('timeout')
                # 重置last_data_time，避免重复检测超时
                self.last_data_time = None
    
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
        
        # 检查是否是Justfloat协议
        is_justfloat = False
        current_source = self.data_source_manager.get_current_source()
        if hasattr(current_source, 'get_protocol'):
            protocol = current_source.get_protocol()
            is_justfloat = (protocol == 'justfloat')
        
        # 只有Justfloat协议才显示重命名通道菜单
        if is_justfloat:
            rename_menu = menu.addMenu("重命名通道")
            for channel_name in channels:
                action = QAction(channel_name, self)
                action.triggered.connect(lambda checked, name=channel_name: self.rename_channel(name))
                rename_menu.addAction(action)
        
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
    
    def rename_channel(self, old_name: str):
        """重命名通道
        
        Args:
            old_name: 原通道名称
        """
        if old_name not in self.waveform_widget.channels:
            QMessageBox.warning(self, "错误", f"通道 '{old_name}' 不存在")
            return
        
        # 弹出输入对话框
        new_name, ok = QInputDialog.getText(self, "重命名通道", f"请输入通道 '{old_name}' 的新名称:")
        
        if ok and new_name:
            # 检查新名称是否已存在
            if new_name in self.waveform_widget.channels:
                QMessageBox.warning(self, "错误", f"通道 '{new_name}' 已存在")
                return
            
            # 检查新名称是否为空
            if not new_name.strip():
                QMessageBox.warning(self, "错误", "通道名称不能为空")
                return
            
            # 更新waveform_widget中的通道名
            self.waveform_widget.rename_channel(old_name, new_name)
            
            # 更新data_source_manager中的通道列表
            if old_name in self.data_source_manager.channels:
                index = self.data_source_manager.channels.index(old_name)
                self.data_source_manager.channels[index] = new_name
            
            # 更新通道显示
            channels_text = ", ".join(self.data_source_manager.get_channels())
            self.channels_label.setText(f"检测到通道: {channels_text}")
            
            print(f"通道 '{old_name}' 已重命名为 '{new_name}'")
        else:
            print(f"通道 '{old_name}' 重命名已取消")
    

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