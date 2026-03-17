"""
Python上位机主程序

支持UDP数据源和实时波形显示的上位机软件。

使用方法:
    python src/main.py
"""

import sys
import os
import queue
import threading
import time
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                             QGroupBox, QFormLayout, QMessageBox, QFileDialog, QCheckBox, QShortcut, QComboBox, QDockWidget)
from PyQt5.QtCore import Qt, QTimer, QDateTime
from PyQt5.QtGui import QFont, QColor, QKeySequence

from data_sources.manager import (
    DataSourceManager,
)
from analytics import ArterialHealthPipeline
from analytics.ml.model_runner import ModelRunner
from visualization.waveform_widget import WaveformWidget
from core.connection_fsm import ConnectedReceivingState, StateMachine, StateViewModel
from core.channel_menu_mixin import ChannelMenuMixin
from core.connection_flow_mixin import ConnectionFlowMixin
from core.dock_layout_mixin import DockLayoutMixin
from core.dock_topmost_mixin import DockTopmostMixin
from core.raw_data_mixin import RawDataMixin
from core.receive_thread import DataReceiveThread
from core.widgets import CircularButton


class MainWindow(ChannelMenuMixin, RawDataMixin, ConnectionFlowMixin, DockLayoutMixin, QMainWindow, DockTopmostMixin):
    """主窗口"""
    
    def __init__(self):
        super().__init__()
        # 提前初始化日志开关，确保init_ui阶段可安全调用log_print
        self.log_enabled = False  # 默认关闭日志
        self.fsm_debug_enabled = True  # FSM/UI调试日志默认开启，便于定位状态切换问题
        self.window_debug_enabled = (os.environ.get("PYTHONLOG_WIN_DEBUG", "0") == "1")  # 窗口层级调试默认关闭
        self.init_ui()
        self.init_components()
        self.init_connections()

    def log_print(self, *args, **kwargs) -> None:
        """统一日志输出接口"""
        if self.log_enabled:
            print(*args, **kwargs)

    def fsm_debug_print(self, *args, **kwargs) -> None:
        """FSM/UI调试日志输出接口（不受普通日志开关影响）。"""
        if self.fsm_debug_enabled:
            print(*args, **kwargs)

    def window_debug_print(self, *args, **kwargs) -> None:
        """窗口层级与置顶相关诊断日志。"""
        if self.window_debug_enabled:
            print(*args, **kwargs)

    def _dock_tag(self, dock: QDockWidget) -> str:
        """生成稳定的Dock调试标签。"""
        if dock is None:
            return "dock=None"
        return f"{dock.objectName() or 'dock'}@{hex(id(dock))}"

    def _debug_ui_state_snapshot(self, tag: str, event: str = "", **kwargs) -> None:
        """打印UI状态快照，便于排查状态与显示不一致问题。"""
        try:
            state_name = self.state_machine.get_current_state_name() if hasattr(self, 'state_machine') else 'None'
            data_status = self.data_status_label.text() if hasattr(self, 'data_status_label') else ''
            conn_status = self.status_label.text() if hasattr(self, 'status_label') else ''
            button_flashing = getattr(self.connect_btn, '_is_flashing', None) if hasattr(self, 'connect_btn') else None
            button_color = None
            if hasattr(self, 'connect_btn') and hasattr(self.connect_btn, '_color') and self.connect_btn._color is not None:
                color = self.connect_btn._color
                button_color = (color.red(), color.green(), color.blue())

            self.fsm_debug_print(
                f"[UI_DEBUG][{tag}] event={event} state={state_name} data_status={data_status} "
                f"conn_status={conn_status} button_flashing={button_flashing} button_color={button_color} extra={kwargs}"
            )
        except Exception as e:
            self.fsm_debug_print(f"[UI_DEBUG][{tag}] snapshot_failed={e}")
    
    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle("Python上位机 - 数据采集")
        self.setGeometry(100, 100, 1400, 800)

        # 启用Dock布局：支持拖拽、分离、复位
        self.setDockNestingEnabled(True)
        self.setDockOptions(
            QMainWindow.AllowNestedDocks |
            QMainWindow.AllowTabbedDocks |
            QMainWindow.AnimatedDocks
        )

        # 主面板
        control_panel = self.create_control_panel()
        self.waveform_widget = WaveformWidget()
        raw_data_panel = self.create_raw_data_panel()

        self.control_dock = self._create_panel_dock("", "dock_control", control_panel, Qt.LeftDockWidgetArea)
        self.waveform_dock = self._create_panel_dock("", "dock_waveform", self.waveform_widget, Qt.LeftDockWidgetArea)
        self.raw_data_dock = self._create_panel_dock("", "dock_raw_data", raw_data_panel, Qt.LeftDockWidgetArea)

        # 默认布局：左控制，右上波形，右下原始数据/发送（覆盖整个工作区，避免中央空白区）
        self.splitDockWidget(self.control_dock, self.waveform_dock, Qt.Horizontal)
        self.splitDockWidget(self.waveform_dock, self.raw_data_dock, Qt.Vertical)
        self.resizeDocks([self.control_dock, self.waveform_dock], [380, 980], Qt.Horizontal)
        self.resizeDocks([self.waveform_dock, self.raw_data_dock], [560, 240], Qt.Vertical)

        # 工具栏：锁定尺寸 + 一键复原
        self._init_layout_toolbar()
        self._install_layer_switching()
        self._bind_dock_signals()
        self._layout_locked = False

        # 自定义样式：避免呆板文本按钮风格
        self.setStyleSheet(self.styleSheet() + """
QDockWidget::title {
    text-align: left;
    padding: 6px 10px;
    color: #1F2A44;
    font-weight: 600;
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #DDE8FF, stop:1 #C7DAFF);
    border-bottom: 1px solid #B5C8ED;
}
QToolBar#layoutToolbar {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #F5FAFF, stop:1 #EAF4FF);
    border: 1px solid #C8D9F2;
    spacing: 8px;
    padding: 4px;
}
QToolBar#layoutToolbar QToolButton {
    border: 1px solid #9CB8E6;
    border-radius: 8px;
    background: #FFFFFF;
    color: #24406F;
    min-width: 22px;
    min-height: 22px;
    padding: 2px;
    font-weight: 600;
}
QToolBar#layoutToolbar QToolButton:checked {
    background: #2E6CE6;
    color: #FFFFFF;
    border-color: #2E6CE6;
}
QToolBar#layoutToolbar QToolButton:hover {
    background: #EAF2FF;
}
QDockWidget::close-button,
QDockWidget::float-button {
    width: 0px;
    height: 0px;
    border: none;
    margin: 0px;
    padding: 0px;
}
""")

        # 保存默认布局，供一键复原
        self._default_geometry = self.saveGeometry()
        self._default_dock_state = self.saveState()
        self._global_above_taskbar = True
        self._pinned_dock = None
        self._handling_visibility_change = False
        self._reasserting_pinned_dock = False
        self._topmost_guard_timer = QTimer(self)
        self._topmost_guard_timer.timeout.connect(self._on_topmost_guard_tick)
        self._topmost_guard_timer.start(300)
        QTimer.singleShot(0, self._enforce_global_topmost)

    def create_control_panel(self):
        """创建控制面板"""
        panel = QWidget()
        layout = QVBoxLayout()
        
        # 标题
        title_label = QLabel("控制面板")
        title_label.setFont(QFont("Arial", 14, QFont.Bold))
        title_label.setAlignment(Qt.AlignCenter)
       # layout.addWidget(title_label)
        
        # 数据源类型选择
        source_group = QGroupBox("数据源")
        source_layout = QFormLayout()
        
        self.source_type_combo = QComboBox()
        self.source_type_combo.addItems(["UDP", "TCP", "串口", "文件"])
        self.source_type_combo.currentTextChanged.connect(self.on_source_type_changed)
        source_layout.addRow("数据源类型:", self.source_type_combo)
        
        source_group.setLayout(source_layout)
        layout.addWidget(source_group)
        
        # UDP配置组
        self.udp_group = QGroupBox("UDP配置")
        udp_layout = QFormLayout()
        
        self.host_edit = QLineEdit("0.0.0.0")
        self.port_edit = QLineEdit("8888")
        self.udp_send_host_edit = QLineEdit("127.0.0.1")
        self.udp_send_port_edit = QLineEdit("8888")
        
        udp_layout.addRow("主机地址:", self.host_edit)
        udp_layout.addRow("端口:", self.port_edit)
        udp_layout.addRow("发送目标IP:", self.udp_send_host_edit)
        udp_layout.addRow("发送目标端口:", self.udp_send_port_edit)
        
        self.udp_group.setLayout(udp_layout)
        layout.addWidget(self.udp_group)

        # TCP配置组
        self.tcp_group = QGroupBox("TCP配置")
        tcp_layout = QFormLayout()

        self.tcp_mode_combo = QComboBox()
        self.tcp_mode_combo.addItems(["监听", "主动连接"])
        self.tcp_mode_combo.setCurrentText("监听")
        self.tcp_mode_combo.currentTextChanged.connect(self.on_tcp_mode_changed)
        self.tcp_host_edit = QLineEdit("0.0.0.0")
        self.tcp_port_edit = QLineEdit("9999")
        self.tcp_target_host_edit = QLineEdit("127.0.0.1")
        self.tcp_target_port_edit = QLineEdit("9999")
        tcp_layout.addRow("TCP模式:", self.tcp_mode_combo)
        tcp_layout.addRow("本地地址:", self.tcp_host_edit)
        tcp_layout.addRow("本地端口:", self.tcp_port_edit)
        tcp_layout.addRow("目标地址:", self.tcp_target_host_edit)
        tcp_layout.addRow("目标端口:", self.tcp_target_port_edit)

        self.tcp_group.setLayout(tcp_layout)
        self.tcp_group.setVisible(False)
        layout.addWidget(self.tcp_group)
        
        # 串口配置组
        self.serial_group = QGroupBox("串口/USB 配置")
        serial_layout = QFormLayout()
        
        self.serial_port_combo = QComboBox()
        self.refresh_serial_ports()
        self.serial_port_combo.showPopup = self.refresh_serial_ports_and_show_popup
        self.baudrate_combo = QComboBox()
        self.baudrate_combo.addItems([
            "9600", "19200", "38400", "57600", "115200",
            "230400", "460800", "921600", "1500000", "2000000"
        ])
        self.baudrate_combo.setCurrentText("115200")
        self.protocol_combo = QComboBox()
        self.protocol_combo.addItems(["文本协议", "Justfloat", "Rawdata"])
        self.protocol_combo.setCurrentText("文本协议")
        self.protocol_combo.currentTextChanged.connect(self.on_protocol_changed)
        
        serial_layout.addRow("串口号:", self.serial_port_combo)
        serial_layout.addRow("波特率:", self.baudrate_combo)
        serial_layout.addRow("通信协议:", self.protocol_combo)
        
        self.serial_group.setLayout(serial_layout)
        layout.addWidget(self.serial_group)

        # 文件配置组
        self.file_group = QGroupBox("文件配置")
        file_layout = QFormLayout()

        self.file_path_edit = QLineEdit()
        self.file_path_edit.setPlaceholderText("选择 .log/.bin/.csv 文件")
        self.file_browse_btn = QPushButton("浏览...")
        self.file_browse_btn.clicked.connect(self.browse_input_file)

        file_path_layout = QHBoxLayout()
        file_path_layout.addWidget(self.file_path_edit)
        file_path_layout.addWidget(self.file_browse_btn)

        self.file_protocol_combo = QComboBox()
        self.file_protocol_combo.addItems(["文本协议", "CSV", "Justfloat", "Rawdata"])
        self.file_protocol_combo.setCurrentText("文本协议")
        self.file_protocol_combo.currentTextChanged.connect(self.on_file_protocol_changed)

        file_layout.addRow("文件路径:", file_path_layout)
        file_layout.addRow("通信协议:", self.file_protocol_combo)

        self.file_group.setLayout(file_layout)
        self.file_group.setVisible(False)
        layout.addWidget(self.file_group)
        
        # 数据校验头配置（公用的）
        
        # Justfloat配置组（默认隐藏）
        self.justfloat_group = QGroupBox("")
        justfloat_layout = QFormLayout()
        
        self.justfloat_mode_combo = QComboBox()
        self.justfloat_mode_combo.addItems(["无时间戳", "带时间戳"])
        self.justfloat_mode_combo.setCurrentText("无时间戳")
        self.justfloat_mode_combo.currentTextChanged.connect(self.on_justfloat_mode_changed)
        justfloat_layout.addRow("Justfloat模式:", self.justfloat_mode_combo)
        
        self.delta_t_edit = QLineEdit("1")
        self.delta_t_edit.setPlaceholderText("数据点间隔(ms)")
        self.delta_t_edit.textChanged.connect(self.on_delta_t_changed)
        justfloat_layout.addRow("Δt(ms):", self.delta_t_edit)
        
        self.justfloat_group.setLayout(justfloat_layout)
        self.justfloat_group.setVisible(False)
        layout.addWidget(self.justfloat_group)
        
        # 隐藏串口配置组
        self.serial_group.setVisible(False)
        
        # 数据校验头配置（公用的）
        self.header_group = QGroupBox("")
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
        self.limit_data_checkbox.setChecked(False)
        self.limit_data_checkbox.toggled.connect(self.toggle_limit_data)
        channel_layout.addWidget(self.limit_data_checkbox)
        
        clear_channels_btn = QPushButton("清空所有通道")
        clear_channels_btn.clicked.connect(self.clear_all_channels)
        channel_layout.addWidget(clear_channels_btn)
        
        channel_group.setLayout(channel_layout)
        layout.addWidget(channel_group)

        # 动脉压力分析配置
        analysis_group = QGroupBox("动脉压力分析")
        analysis_layout = QFormLayout()

        self.analysis_enable_checkbox = QCheckBox("启用分析")
        self.analysis_enable_checkbox.setChecked(False)
        self.analysis_enable_checkbox.toggled.connect(self.on_analysis_enabled_changed)

        self.grid_width_edit = QLineEdit("16")
        self.grid_height_edit = QLineEdit("16")
        self.analysis_stride_edit = QLineEdit("1")
        self.model_path_edit = QLineEdit("")
        self.model_path_edit.setPlaceholderText("可选: joblib模型路径")
        self.model_browse_btn = QPushButton("浏览...")
        self.model_browse_btn.clicked.connect(self.browse_model_path)

        model_path_layout = QHBoxLayout()
        model_path_layout.addWidget(self.model_path_edit)
        model_path_layout.addWidget(self.model_browse_btn)

        apply_analysis_btn = QPushButton("应用分析配置")
        apply_analysis_btn.clicked.connect(self.apply_analysis_config)

        analysis_layout.addRow("分析开关:", self.analysis_enable_checkbox)
        analysis_layout.addRow("点阵宽度:", self.grid_width_edit)
        analysis_layout.addRow("点阵高度:", self.grid_height_edit)
        analysis_layout.addRow("分析步长:", self.analysis_stride_edit)
        analysis_layout.addRow("模型路径:", model_path_layout)
        analysis_layout.addRow(apply_analysis_btn)

        analysis_group.setLayout(analysis_layout)
        layout.addWidget(analysis_group)
        
        # 状态显示
        status_group = QGroupBox("状态")
        status_layout = QVBoxLayout()
        
        self.status_label = QLabel("未连接")
        self.status_label.setStyleSheet("color: red;")
        self.data_count_label = QLabel("接收数据: 0")
        self.perf_label = QLabel("速率: 接收 0/s | 处理 0/s | 队列 0 | 丢包 0 | 字节 0 B/s | 解析 0 us/帧")
        self.perf_label.setStyleSheet("color: #666;")
        self.save_file_label = QLabel("保存文件: 无")
        self.save_file_label.setStyleSheet("color: #666;")
        self.arterial_metrics_label = QLabel("动脉指标: 未启用")
        self.arterial_metrics_label.setStyleSheet("color: #666;")
        self.arterial_pred_label = QLabel("健康评估: 未启用")
        self.arterial_pred_label.setStyleSheet("color: #666;")
        
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.data_count_label)
        status_layout.addWidget(self.perf_label)
        status_layout.addWidget(self.save_file_label)
        status_layout.addWidget(self.arterial_metrics_label)
        status_layout.addWidget(self.arterial_pred_label)
        
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
        self.save_btn.setEnabled(False)
        self.save_btn.setToolTip("请先连接数据源后再开始保存")
        save_layout.addWidget(self.save_btn)
        
        save_group.setLayout(save_layout)
        layout.addWidget(save_group)
        
        # 弹簧，推到底部
        layout.addStretch()
        
    
        panel.setLayout(layout)
        return panel
    
    def init_components(self):
        """初始化组件"""
        self.data_source_manager = DataSourceManager()
        # 分析模块默认关闭，避免影响现有主链路。
        self.arterial_pipeline = self._build_arterial_pipeline_from_ui(enabled=False)
        self.latest_arterial_result = None
        self.data_count = 0
        self.auto_save_enabled = False
        self.last_data_time = None  # 记录最后接收数据的时间
        self.data_timeout = 300  # 数据超时时间（毫秒）
        self.last_justfloat_channel_names = []  # 断开后保留justfloat通道显示名快照
        
        # 将data_source_manager传递给waveform_widget
        self.waveform_widget.data_source_manager = self.data_source_manager
        
        # 原始数据缓冲区（用于优化打印速度）
        self.raw_data_buffer = []
        self.raw_data_queue = queue.Queue(maxsize=2000)  # 原始数据队列（线程安全）
        self.raw_data_update_interval = 100  # UI更新间隔（毫秒）
        self.raw_data_enabled = False  # 默认关闭原始数据显示以保障吞吐
        self.raw_data_encoding = self.encoding_combo.currentText().replace('-', '').lower()
        self.raw_data_display_format = self.display_format_combo.currentText()
        self.raw_data_update_timer = QTimer()
        self.raw_data_update_timer.timeout.connect(self.flush_raw_data_buffer)
        self.raw_data_update_timer.start(self.raw_data_update_interval)
        
        # 多线程架构
        self.data_queue = queue.Queue(maxsize=5000)  # 数据队列，文件回放场景下减少溢出丢帧
        self.stop_event = threading.Event()  # 停止事件
        self.receive_thread = None  # 数据接收线程

        # UI限频更新，避免每个数据点都触发文本渲染
        self.status_update_interval_ms = 50
        self.last_status_update_ms = 0
        self.last_channels_text = "自动检测通道..."

        # 性能统计
        self.last_perf_recv_count = 0
        self.last_perf_proc_count = 0
        self.last_perf_drop_count = 0
        self.last_perf_bytes_count = 0
        self.last_perf_parsed_frames = 0
        self.last_perf_parse_ns_total = 0
        self.last_perf_time = time.perf_counter()

        # 通道颜色表缓存，避免在高频循环里重复创建
        self.channel_colors = [
            (255, 0, 0),
            (0, 255, 0),
            (0, 0, 255),
            (0, 255, 255),
            (255, 0, 255),
            (255, 255, 0),
            (0, 0, 0),
            (255, 165, 0),
            (128, 0, 128),
            (165, 42, 42),
            (255, 192, 203),
            (128, 128, 128),
            (85, 107, 47),
            (0, 128, 128),
            (128, 0, 0),
            (192, 192, 192),
            (255, 215, 0),
            (75, 0, 130),
            (238, 130, 238),
            (255, 105, 180),
            (255, 99, 71),
            (147, 112, 219),
            (64, 224, 208),
            (0, 206, 209),
            (46, 139, 87),
            (245, 245, 220),
            (255, 250, 205),
        ]
        
        # 日志开关已在__init__中初始化
        
        # 初始化状态机
        self.state_machine = StateMachine(self)
        
        # 定义断开回调函数
        def on_disconnect():
            """数据源断开回调（已废弃，使用信号机制）"""
            self.log_print("[断开回调] 数据源已断开（此回调已废弃）")
            # 不再在这里处理断开逻辑，因为现在使用信号机制
        
        # 保存断开回调函数
        self.disconnect_callback = on_disconnect
        
        # 数据更新定时器
        self.data_timer = QTimer()
        self.data_timer.timeout.connect(self.update_data)
        self.data_timer.start(5)  # 5ms更新一次，提升消费吞吐
        
        # 超时检测定时器
        self.timeout_timer = QTimer()
        self.timeout_timer.timeout.connect(self.check_data_timeout)
        self.timeout_timer.start(100)  # 100ms检测一次超时

        # 性能统计定时器
        self.perf_timer = QTimer()
        self.perf_timer.timeout.connect(self.update_perf_stats)
        self.perf_timer.start(500)

    def update_perf_stats(self):
        """更新接收/处理速率统计"""
        now = time.perf_counter()
        dt = now - self.last_perf_time
        if dt <= 0:
            return

        recv_count = 0
        drop_count = 0
        bytes_count = 0
        parsed_frames = 0
        parse_ns_total = 0
        if self.receive_thread and self.receive_thread.isRunning():
            recv_count = self.receive_thread.recv_ok_count
            drop_count = self.receive_thread.drop_count
            source = self.data_source_manager.get_current_source()
            if source is not None:
                bytes_count = getattr(source, 'bytes_read_count', 0)
                parsed_frames = getattr(source, 'parsed_frame_count', 0)
                parse_ns_total = getattr(source, 'parse_time_ns_total', 0)

        proc_count = self.data_count

        recv_rate = int((recv_count - self.last_perf_recv_count) / dt)
        proc_rate = int((proc_count - self.last_perf_proc_count) / dt)
        drop_delta = max(0, drop_count - self.last_perf_drop_count)
        queue_size = self.data_queue.qsize()

        bytes_rate = int((bytes_count - self.last_perf_bytes_count) / dt)
        parsed_delta = max(0, parsed_frames - self.last_perf_parsed_frames)
        parse_ns_delta = max(0, parse_ns_total - self.last_perf_parse_ns_total)
        avg_parse_us = int((parse_ns_delta / parsed_delta) / 1000) if parsed_delta > 0 else 0

        self.perf_label.setText(
            f"速率: 接收 {recv_rate}/s | 处理 {proc_rate}/s | 队列 {queue_size} | 丢包+{drop_delta} | 字节 {bytes_rate} B/s | 解析 {avg_parse_us} us/帧"
        )

        self.last_perf_recv_count = recv_count
        self.last_perf_proc_count = proc_count
        self.last_perf_drop_count = drop_count
        self.last_perf_bytes_count = bytes_count
        self.last_perf_parsed_frames = parsed_frames
        self.last_perf_parse_ns_total = parse_ns_total
        self.last_perf_time = now
    
    def init_connections(self):
        """初始化连接"""
        # 启动波形显示更新
        self.waveform_widget.start_update()

        # 缓存原始数据显示配置，避免在数据线程里访问UI控件
        self.encoding_combo.currentTextChanged.connect(self._on_encoding_changed)
        self.display_format_combo.currentTextChanged.connect(self._on_display_format_changed)
        self.raw_data_enable_checkbox.toggled.connect(self._on_raw_data_toggle)
        
        # 设置空格键快捷键为暂停/继续
        self.space_shortcut = QShortcut(QKeySequence(Qt.Key_Space), self)
        self.space_shortcut.activated.connect(self.toggle_pause)

        # 发送快捷键：Ctrl+Enter发送，Enter保留换行
        self.send_shortcut = QShortcut(QKeySequence("Ctrl+Return"), self.send_edit)
        self.send_shortcut.activated.connect(self.send_current_data)
        
        # 设置初始UI状态
        self.on_source_type_changed(self.source_type_combo.currentText())
        self.on_tcp_mode_changed(self.tcp_mode_combo.currentText())
        self.on_protocol_changed(self.protocol_combo.currentText())
        self.on_file_protocol_changed(self.file_protocol_combo.currentText())

        self.waveform_widget.set_limit_data(self.limit_data_checkbox.isChecked())

    def _on_encoding_changed(self, text: str):
        """编码格式改变时更新缓存"""
        self.raw_data_encoding = text.replace('-', '').lower()

    def _on_display_format_changed(self, text: str):
        """显示格式改变时更新缓存"""
        self.raw_data_display_format = text

    def _on_raw_data_toggle(self, checked: bool):
        """原始数据显示开关"""
        self.raw_data_enabled = checked

    def _debug_channel_state(self, tag: str, incoming_keys=None):
        """打印重命名与自动建通道相关调试信息"""
        waveform_channels = list(self.waveform_widget.channels.keys())
        manager_channels = self.data_source_manager.get_channels()
        mapping = self.data_source_manager.get_channel_name_mapping()
        self.log_print(f"[DEBUG][{tag}] waveform_channels={waveform_channels}")
        self.log_print(f"[DEBUG][{tag}] manager_channels={manager_channels}")
        self.log_print(f"[DEBUG][{tag}] mapping={mapping}")
        if incoming_keys is not None:
            self.log_print(f"[DEBUG][{tag}] incoming_keys={list(incoming_keys)}")

    def _normalize_waveform_data_keys(self, waveform_data):
        """将数据键统一映射为当前显示通道名，避免重命名后旧键回流导致重复建通道。"""
        normalized = {}
        for channel_name, value in waveform_data.items():
            display_name = self.data_source_manager.get_display_channel_name(channel_name)
            normalized[display_name] = value
        return normalized

    def _extract_waveform_data(self, data_dict):
        """应用编排层：提取数据包中的通道数据并归一化通道名。"""
        # 统一帧结构：直接使用channels字段
        if isinstance(data_dict, dict) and 'channels' in data_dict:
            waveform_data = data_dict.get('channels', {})
            if not waveform_data:
                return waveform_data
            return self._normalize_waveform_data_keys(waveform_data)

        # 兼容旧扁平字典结构
        waveform_data = {
            k: v for k, v in data_dict.items()
            if k not in ('header', 'timestamp', 'format_error')
        }
        if not waveform_data:
            return waveform_data
        return self._normalize_waveform_data_keys(waveform_data)

    def _is_format_error_packet(self, data_dict) -> bool:
        """同时兼容统一帧与旧字典的格式错误标识。"""
        if not isinstance(data_dict, dict):
            return False

        if data_dict.get('format_error'):
            return True

        meta = data_dict.get('meta', {})
        return bool(meta.get('format_error'))

    def _ensure_waveform_channels(self, channel_names):
        """表现层协调：确保波形组件包含所有目标通道。"""
        for channel_name in channel_names:
            if channel_name not in self.waveform_widget.channels:
                self.log_print(f"[DEBUG][auto_create] missing_channel={channel_name}")
                color = self.channel_colors[len(self.waveform_widget.channels) % len(self.channel_colors)]
                self.waveform_widget.add_channel(channel_name, color, 2)
                if self.log_enabled:
                    self._debug_channel_state("after_auto_create", incoming_keys=channel_names)

    def _update_waveform_from_packet(self, data_dict):
        """应用编排层：处理单个数据包的波形更新流程。"""
        waveform_data = self._extract_waveform_data(data_dict)
        if not waveform_data:
            return

        if self.log_enabled:
            self._debug_channel_state("before_auto_create", incoming_keys=waveform_data.keys())

        self._ensure_waveform_channels(waveform_data.keys())

        timestamp = data_dict.get('timestamp', 0.0)
        self.waveform_widget.update_channels(waveform_data, timestamp)

    def _submit_arterial_analysis(self, data_dict):
        """提交数据包到动脉分析管线。"""
        if not hasattr(self, 'arterial_pipeline') or self.arterial_pipeline is None:
            return

        result = self.arterial_pipeline.submit_frame(data_dict)
        if result is not None:
            self.latest_arterial_result = result
            self._apply_arterial_result(result)

    def _apply_arterial_result(self, result):
        """将分析结果更新到UI。"""
        if not isinstance(result, dict):
            return

        heatmap = result.get('heatmap', {}) or {}
        matrix = heatmap.get('matrix')
        metrics = result.get('metrics', {}) or {}
        prediction = result.get('prediction', {}) or {}

        self.waveform_widget.update_pressure_matrix(
            matrix,
            result.get('timestamp', 0.0),
            metrics,
            prediction,
        )

        if metrics:
            bpm = float(metrics.get('bpm', 0.0))
            amp = float(metrics.get('amplitude', 0.0))
            consistency = float(metrics.get('consistency', 0.0))
            repeatability = float(metrics.get('repeatability', 0.0))
            self.arterial_metrics_label.setText(
                f"动脉指标: bpm {bpm:.1f} | amp {amp:.3f} | 一致性 {consistency:.2f} | 重复性 {repeatability:.2f}"
            )

        if prediction:
            label = str(prediction.get('label', 'unknown'))
            score = float(prediction.get('score', 0.0))
            risk = str(prediction.get('risk_level', 'unknown'))
            mode = str(prediction.get('mode', 'rule'))
            self.arterial_pred_label.setText(
                f"健康评估: {label} | score {score:.2f} | 风险 {risk} | 模式 {mode}"
            )

    def _reset_arterial_ui_state(self):
        """重置动脉分析显示状态。"""
        self.latest_arterial_result = None
        if hasattr(self, 'waveform_widget') and self.waveform_widget is not None:
            self.waveform_widget.clear_pressure_view()
        if hasattr(self, 'arterial_metrics_label'):
            if self.analysis_enable_checkbox.isChecked():
                self.arterial_metrics_label.setText("动脉指标: 等待数据")
            else:
                self.arterial_metrics_label.setText("动脉指标: 未启用")
        if hasattr(self, 'arterial_pred_label'):
            if self.analysis_enable_checkbox.isChecked():
                self.arterial_pred_label.setText("健康评估: 等待数据")
            else:
                self.arterial_pred_label.setText("健康评估: 未启用")

    def _build_arterial_pipeline_from_ui(self, enabled=None):
        """根据UI配置创建动脉分析管线。"""
        try:
            grid_width = max(1, int(self.grid_width_edit.text().strip() or "16"))
            grid_height = max(1, int(self.grid_height_edit.text().strip() or "16"))
            analysis_stride = max(1, int(self.analysis_stride_edit.text().strip() or "1"))
        except ValueError:
            grid_width = 16
            grid_height = 16
            analysis_stride = 1

        if enabled is None:
            enabled = self.analysis_enable_checkbox.isChecked() if hasattr(self, 'analysis_enable_checkbox') else False

        model_path = self.model_path_edit.text().strip() if hasattr(self, 'model_path_edit') else ""

        return ArterialHealthPipeline(
            enabled=bool(enabled),
            grid_width=grid_width,
            grid_height=grid_height,
            analysis_stride=analysis_stride,
            model_path=model_path,
        )

    def apply_analysis_config(self):
        """应用动脉分析配置。"""
        self.arterial_pipeline = self._build_arterial_pipeline_from_ui()
        self._reset_arterial_ui_state()
        grid_info = f"{self.arterial_pipeline.adapter.grid_width}x{self.arterial_pipeline.adapter.grid_height}"
        model_status = self.arterial_pipeline.get_model_status()
        model_mode = str(model_status.get('mode', 'rule'))
        model_error = str(model_status.get('load_error', '') or '')

        if self.arterial_pipeline.enabled:
            if model_mode == 'external':
                QMessageBox.information(self, "动脉分析", f"分析已启用，点阵: {grid_info}\n模型状态: external（已加载）")
            elif self.model_path_edit.text().strip():
                QMessageBox.warning(
                    self,
                    "动脉分析",
                    f"分析已启用，点阵: {grid_info}\n模型状态: rule（已降级）\n原因: {model_error or '未知错误'}",
                )
            else:
                QMessageBox.information(self, "动脉分析", f"分析已启用，点阵: {grid_info}\n模型状态: rule（未配置模型）")
        else:
            QMessageBox.information(self, "动脉分析", f"分析已禁用，点阵: {grid_info}")

    def on_analysis_enabled_changed(self, checked: bool):
        """分析开关切换。"""
        if self.arterial_pipeline is None:
            return
        self.arterial_pipeline.enabled = bool(checked)
        self._reset_arterial_ui_state()

    def _sync_receiving_indicator(self):
        """兜底同步：接收状态必须保持蓝色闪烁。"""
        if not isinstance(self.state_machine.current_state, ConnectedReceivingState):
            return

        if not getattr(self.connect_btn, '_is_flashing', False):
            self.connect_btn.set_color(QColor(100, 149, 237))
            self.connect_btn.start_flashing(100)
            self.fsm_debug_print("[UI_DEBUG][sync] receiving_state_detected_but_not_flashing -> force_start_flashing")

    def apply_fsm_view(self, view: StateViewModel):
        """表现层适配：应用FSM输出的状态视图模型。"""
        self.connect_btn.set_color(QColor(*view.button_rgb))
        if view.flashing:
            self.connect_btn.start_flashing(view.flash_interval_ms)
        else:
            self.connect_btn.stop_flashing()
        self.data_status_label.setText(view.data_status_text)
        self.data_status_label.setStyleSheet(f"color: {view.data_status_color};")
    
    def on_justfloat_mode_changed(self, mode_text: str):
        """Justfloat模式改变事件处理
        
        Args:
            mode_text: 模式文本（无时间戳、带时间戳）
        """
        if mode_text == "无时间戳":
            # 无时间戳模式：显示Δt设置
            self.delta_t_edit.setVisible(True)
        else:  # 带时间戳
            # 带时间戳模式：隐藏Δt设置
            self.delta_t_edit.setVisible(False)
    
    def on_delta_t_changed(self, delta_t_text: str):
        """Δt改变事件处理
        
        Args:
            delta_t_text: Δt文本
        """
        try:
            # 尝试解析Δt
            delta_t = float(delta_t_text) if delta_t_text else 1.0
            self.log_print(f"[on_delta_t_changed] Δt已改变为: {delta_t} ms")
            
            # 如果当前已连接且是Justfloat无时间戳模式，重置数据点计数器
            if self.data_source_manager.is_connected():
                current_source = self.data_source_manager.current_source
                if hasattr(current_source, 'get_protocol'):
                    protocol = current_source.get_protocol()
                    if protocol == 'justfloat' and hasattr(current_source, 'justfloat_mode'):
                        if current_source.justfloat_mode == 'without_timestamp':
                            # 更新Δt并重置计数器
                            current_source.delta_t = delta_t
                            current_source.reset_data_point_counter()
                            self.log_print(f"[on_delta_t_changed] 已重置数据点计数器")
        except ValueError:
            self.log_print(f"[on_delta_t_changed] 无效的Δt值: {delta_t_text}")
    
    def browse_save_path(self):
        """浏览保存路径"""
        dir_path = QFileDialog.getExistingDirectory(self, "选择保存目录", self.save_path_edit.text())
        if dir_path:
            self.save_path_edit.setText(dir_path)

    def browse_model_path(self):
        """浏览模型文件路径（.joblib）。"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择模型文件",
            self.model_path_edit.text() or os.getcwd(),
            "模型文件 (*.joblib);;所有文件 (*)",
        )
        if file_path:
            self.model_path_edit.setText(file_path)
            self._validate_selected_model_path(show_success=True)

    def _validate_selected_model_path(self, show_success: bool = False) -> bool:
        """校验模型文件可读性。"""
        model_path = self.model_path_edit.text().strip()
        if not model_path:
            return False

        checker = ModelRunner(model_path=model_path)
        status = checker.get_status()
        if str(status.get('mode')) == 'external' and bool(status.get('has_model')):
            if show_success:
                QMessageBox.information(self, "模型校验", "模型文件校验通过，可用于外部推理。")
            return True

        QMessageBox.warning(
            self,
            "模型校验",
            f"模型文件不可用，将在运行时降级为规则模式。\n原因: {status.get('load_error') or '未知错误'}",
        )
        return False
    
    def toggle_saving(self):
        """切换数据保存状态"""
        if not self.data_source_manager.is_connected():
            QMessageBox.information(self, "提示", "请先连接数据源，再开始保存")
            self.save_btn.setEnabled(False)
            self.save_btn.setText("开始保存")
            self.save_file_label.setText("保存文件: 无")
            self.auto_save_enabled = False
            return

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
        self.last_perf_proc_count = 0
    
    def start_receive_thread(self):
        """启动数据接收线程"""
        if self.receive_thread and self.receive_thread.isRunning():
            return
        # 重置停止事件
        self.stop_event.clear()
        # 创建数据接收线程
        self.receive_thread = DataReceiveThread(
            self.data_source_manager,
            self.data_queue,
            self.stop_event,
            self.log_print
        )
        # 连接断开信号
        self.receive_thread.disconnect_signal.connect(self.on_disconnect_from_thread)
        # 启动线程
        self.receive_thread.start()
        self.log_print("[MainWindow] 启动数据接收线程")
    
    def on_disconnect_from_thread(self):
        """从接收线程中处理断开连接（在主线程中执行）"""
        self.log_print("[MainWindow] 收到断开连接信号")
        self._debug_ui_state_snapshot("on_disconnect_signal", event="disconnect_signal")
        # 在主线程中执行强制断开逻辑，避免误进入“连接”分支
        if self.state_machine.is_connected():
            self._disconnect_flow()
        else:
            self.fsm_debug_print("[UI_DEBUG] disconnect_signal收到时已处于未连接状态，忽略重复断开")
    
    def stop_receive_thread(self):
        """停止数据接收线程"""
        if self.receive_thread and self.receive_thread.isRunning():
            # 设置停止事件
            self.stop_event.set()
            # 等待线程结束（最多等待1秒）
            if self.receive_thread.wait(1000):
                self.log_print("[MainWindow] 数据接收线程已停止")
            else:
                self.log_print("[MainWindow] 数据接收线程停止超时")
            # 终止线程（强制停止）
            if self.receive_thread.isRunning():
                self.receive_thread.terminate()
                self.receive_thread.wait(500)
                self.log_print("[MainWindow] 数据接收线程已强制停止")
        # 清空队列
        while not self.data_queue.empty():
            try:
                self.data_queue.get_nowait()
            except queue.Empty:
                break
    
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
            self.log_print("波形显示已恢复")
            self.state_machine.handle_event('resume')
        else:
            # 暂停
            self.waveform_widget.is_paused = True
            self.pause_btn.setText("继续")
            # 触发pause事件
            self.log_print("波形显示已暂停（数据继续接收和保存）")
            self.state_machine.handle_event('pause')
    
    def update_data(self):
        """更新数据 - 高吞吐批处理策略"""
        if not self.state_machine.is_connected():
            return

        # 每轮最多处理固定批次，降低计时和函数调用开销
        max_batch_per_update = 500
        processed_count = 0
        has_valid_data = False
        has_format_error = False

        while processed_count < max_batch_per_update:
            
            try:
                # 从队列中取出数据
                data_dict = self.data_queue.get(block=False)
                
                # 检查是否是格式错误标识
                if self._is_format_error_packet(data_dict):
                    has_format_error = True
                    continue

                has_valid_data = True
                
                self.data_count += 1
                
                # 超时检测使用本机接收时刻，避免发送端相对时间戳导致误判超时
                self.last_data_time = QDateTime.currentMSecsSinceEpoch()

                self._update_waveform_from_packet(data_dict)
                self._submit_arterial_analysis(data_dict)
                
                processed_count += 1
            except queue.Empty:
                # 队列为空，退出循环
                break
            except Exception as e:
                self.log_print(f"[MainWindow] 处理数据失败: {e}")
                break

        # 批量处理后再触发状态机，避免每点一次状态切换开销
        # 对格式错误事件优先上报，确保UI能及时进入红色闪烁状态。
        if has_format_error:
            header_mismatch_count = self.data_source_manager.get_header_mismatch_count()
            self.fsm_debug_print(
                f"[UI_DEBUG][update_data] format_error_detected mismatch_count={header_mismatch_count} has_valid_data={has_valid_data}"
            )
            self.state_machine.handle_event('format_error', mismatch_count=header_mismatch_count)
        elif has_valid_data and not self.waveform_widget.is_paused:
            self.fsm_debug_print("[UI_DEBUG][update_data] data_received_detected")
            self.state_machine.handle_event('data_received')

        # 状态驱动后的UI兜底同步，避免出现“文字已接收但按钮不闪烁”。
        self._sync_receiving_indicator()

        # 限频更新文本UI，避免高频setText导致主线程卡顿
        if processed_count > 0:
            now_ms = QDateTime.currentMSecsSinceEpoch()
            if now_ms - self.last_status_update_ms >= self.status_update_interval_ms:
                self.data_count_label.setText(f"接收数据: {self.data_count}")

                channels = self.data_source_manager.get_channels()
                if channels:
                    channels_text = ", ".join(channels)
                    if channels_text != self.last_channels_text:
                        self.channels_label.setText(f"检测到通道: {channels_text}")
                        self.last_channels_text = channels_text

                self.last_status_update_ms = now_ms
    
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
                self.log_print(f"[check_data_timeout] 数据超时，触发timeout事件")
                self.fsm_debug_print(f"[UI_DEBUG][timeout] elapsed_ms={elapsed}, threshold_ms={self.data_timeout}")
                self.state_machine.handle_event('timeout')
                # 重置last_data_time，避免重复检测超时
                self.last_data_time = None

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