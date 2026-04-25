"""
Python上位机主程序

支持UDP数据源和实时波形显示的上位机软件。

使用方法:
    python src/main.py
"""

import sys
import os
import json
import csv
import subprocess
import queue
import threading
import time
import shlex
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                             QGroupBox, QFormLayout, QMessageBox, QFileDialog, QCheckBox, QShortcut, QComboBox, QDockWidget, QToolButton)
from PyQt5.QtCore import Qt, QTimer, QDateTime, pyqtSignal
from PyQt5.QtGui import QFont, QColor, QKeySequence, QImage, QPainter, QPen

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

    train_finished_signal = pyqtSignal(object)
    METRIC_EXPORT_ITEMS = [
        ("训练指标: accuracy", "train_accuracy", True),
        ("训练指标: macro-f1", "train_macro_f1", True),
        ("训练指标: 混淆矩阵摘要", "train_confusion_summary", False),
        ("健康指标: bpm", "health_bpm", True),
        ("健康指标: amplitude", "health_amplitude", True),
        ("健康指标: consistency", "health_consistency", True),
        ("健康指标: repeatability", "health_repeatability", True),
        ("健康评估: label", "eval_label", True),
        ("健康评估: score", "eval_score", True),
        ("健康评估: risk_level", "eval_risk_level", True),
        ("健康评估: mode", "eval_mode", False),
    ]
    
    def __init__(self):
        super().__init__()
        # 提前初始化日志开关，确保init_ui阶段可安全调用log_print
        self.log_enabled = False  # 默认关闭日志
        self.fsm_debug_enabled = (os.environ.get("PYTHONLOG_FSM_DEBUG", "0") == "1")
        self.export_debug_enabled = True
        self.window_debug_enabled = (os.environ.get("PYTHONLOG_WIN_DEBUG", "0") == "1")  # 窗口层级调试默认关闭
        self.train_finished_signal.connect(self._handle_train_finished_signal)
        self.init_ui()
        self.init_components()
        self.init_connections()

    def log_print(self, *args, **kwargs) -> None:
        """统一日志输出接口"""
        if self.log_enabled:
            print(*args, **kwargs)

    def fsm_debug_print(self, *args, **kwargs) -> None:
        """FSM/UI调试日志输出接口（不受普通日志开关影响）。"""
        first = str(args[0]) if args else ""
        if first.startswith("[EXPORT]") and self.export_debug_enabled:
            print(*args, **kwargs)
            return
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
        self.create_ml_subwindow()
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
        self.protocol_combo.addItems(["文本协议", "Justfloat", "Firewater", "Rawdata"])
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

        # 机器学习入口：配置迁移到独立子窗口，避免和数据配置混杂。
        ml_entry_group = QGroupBox("机器学习")
        ml_entry_layout = QVBoxLayout()
        self.open_ml_center_btn = QPushButton("打开机器学习中心")
        self.open_ml_center_btn.clicked.connect(self.open_ml_center_window)
        ml_entry_hint = QLabel("推理与离线训练配置已独立到子窗口")
        ml_entry_hint.setStyleSheet("color: #666;")
        ml_entry_hint.setWordWrap(True)
        ml_entry_layout.addWidget(self.open_ml_center_btn)
        ml_entry_layout.addWidget(ml_entry_hint)
        ml_entry_group.setLayout(ml_entry_layout)
        layout.addWidget(ml_entry_group)
        
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

    def create_ml_subwindow(self):
        """创建机器学习配置子窗口。"""
        self.ml_window = QWidget(self)
        self.ml_window.setWindowTitle("机器学习中心")
        self.ml_window.setWindowFlag(Qt.Window, True)
        self.ml_window.resize(560, 680)

        ml_layout = QVBoxLayout()

        inference_group = QGroupBox("在线推理配置")
        inference_layout = QFormLayout()

        self.analysis_enable_checkbox = QCheckBox("启用分析")
        self.analysis_enable_checkbox.setChecked(False)
        self.analysis_enable_checkbox.toggled.connect(self.on_analysis_enabled_changed)

        self.grid_width_edit = QLineEdit("16")
        self.grid_height_edit = QLineEdit("16")
        self.analysis_stride_edit = QLineEdit("1")

        self.inference_model_combo = QComboBox()
        self.inference_model_combo.addItems([
            "自动加载(按模型文件)",
            "规则引擎",
            "随机森林",
            "逻辑回归",
            "支持向量机(SVM)",
            "梯度提升树",
        ])
        self.inference_model_combo.setCurrentText("自动加载(按模型文件)")
        self.inference_model_combo.currentTextChanged.connect(self.on_inference_model_changed)

        self.model_path_edit = QLineEdit("")
        self.model_path_edit.setPlaceholderText("可选: joblib模型路径")
        self.model_browse_btn = QPushButton("浏览...")
        self.model_browse_btn.clicked.connect(self.browse_model_path)

        model_path_layout = QHBoxLayout()
        model_path_layout.addWidget(self.model_path_edit)
        model_path_layout.addWidget(self.model_browse_btn)

        apply_analysis_btn = QPushButton("应用推理配置")
        apply_analysis_btn.clicked.connect(self.apply_analysis_config)

        inference_layout.addRow("分析开关:", self.analysis_enable_checkbox)
        inference_layout.addRow("模型选择:", self.inference_model_combo)
        inference_layout.addRow("点阵宽度:", self.grid_width_edit)
        inference_layout.addRow("点阵高度:", self.grid_height_edit)
        inference_layout.addRow("分析步长:", self.analysis_stride_edit)
        inference_layout.addRow("模型路径:", model_path_layout)
        inference_layout.addRow(apply_analysis_btn)
        inference_group.setLayout(inference_layout)

        training_group = QGroupBox("离线训练配置")
        training_layout = QFormLayout()

        default_train_dataset = "" if getattr(sys, 'frozen', False) else "data/arterial_train_dataset.csv"
        self.train_dataset_edit = QLineEdit(default_train_dataset)
        self.train_dataset_edit.setPlaceholderText("训练数据CSV路径")
        self.train_dataset_browse_btn = QPushButton("浏览...")
        self.train_dataset_browse_btn.clicked.connect(self.browse_train_dataset)

        train_dataset_layout = QHBoxLayout()
        train_dataset_layout.addWidget(self.train_dataset_edit)
        train_dataset_layout.addWidget(self.train_dataset_browse_btn)

        self.train_model_type_combo = QComboBox()
        self.train_model_type_combo.addItems([
            "随机森林",
            "逻辑回归",
            "支持向量机(SVM)",
            "梯度提升树",
        ])
        self.train_model_type_combo.setCurrentText("随机森林")

        self.train_test_size_edit = QLineEdit("0.2")
        self.train_test_size_edit.setPlaceholderText("0.1~0.4")
        self.train_seed_edit = QLineEdit("42")
        self.train_seed_edit.setPlaceholderText("随机种子")

        train_basic_param_layout = QHBoxLayout()
        train_basic_param_layout.addWidget(QLabel("test_size:"))
        train_basic_param_layout.addWidget(self.train_test_size_edit)
        train_basic_param_layout.addWidget(QLabel("seed:"))
        train_basic_param_layout.addWidget(self.train_seed_edit)

        self.train_extra_args_edit = QLineEdit("")
        self.train_extra_args_edit.setPlaceholderText("可选高级参数: --rf-n-estimators 320 --rf-max-depth 12")

        default_model_output = "data/models/arterial_model.joblib"
        self.train_output_edit = QLineEdit(default_model_output)
        self.train_output_edit.setPlaceholderText("训练输出模型路径")
        self.train_output_browse_btn = QPushButton("浏览...")
        self.train_output_browse_btn.clicked.connect(self.browse_train_output)

        train_output_layout = QHBoxLayout()
        train_output_layout.addWidget(self.train_output_edit)
        train_output_layout.addWidget(self.train_output_browse_btn)

        self.train_model_btn = QPushButton("开始训练并加载")
        self.train_model_btn.clicked.connect(self.train_model_from_ui)
        self.train_model_busy = False

        self.train_metrics_summary_label = QLabel("测试指标: 暂无")
        self.train_metrics_summary_label.setWordWrap(True)
        self.train_metrics_summary_label.setStyleSheet("color: #666;")

        self.train_conf_matrix_label = QLabel("混淆矩阵摘要: 暂无")
        self.train_conf_matrix_label.setWordWrap(True)
        self.train_conf_matrix_label.setStyleSheet("color: #666;")

        training_layout.addRow("训练数据:", train_dataset_layout)
        training_layout.addRow("训练算法:", self.train_model_type_combo)
        training_layout.addRow("训练参数:", train_basic_param_layout)
        training_layout.addRow("高级参数:", self.train_extra_args_edit)
        training_layout.addRow("模型输出:", train_output_layout)
        training_layout.addRow(self.train_model_btn)
        training_layout.addRow("测试指标:", self.train_metrics_summary_label)
        training_layout.addRow("混淆矩阵:", self.train_conf_matrix_label)
        training_group.setLayout(training_layout)

        export_group = QGroupBox("指标导出配置")
        export_layout = QVBoxLayout()

        self.metric_export_enable_checkbox = QCheckBox("启用指标导出（随数据保存同步）")
        self.metric_export_enable_checkbox.setChecked(False)
        self.metric_export_enable_checkbox.toggled.connect(self.on_metric_export_enabled_changed)

        self.metric_export_checkboxes = {}

        self.metric_export_select_btn = QToolButton()
        self.metric_export_select_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.metric_export_select_btn.clicked.connect(self.show_metric_export_popup)
        self._create_metric_export_popup()
        self._update_metric_export_selector_text()

        self.metric_export_path_edit = QLineEdit("")
        self.metric_export_path_edit.setPlaceholderText("可选: 指标导出CSV路径，留空自动生成")
        self.metric_export_path_edit.textChanged.connect(self.on_metric_export_path_changed)
        self.metric_export_browse_btn = QPushButton("浏览...")
        self.metric_export_browse_btn.clicked.connect(self.browse_metric_export_output)

        metric_export_path_layout = QHBoxLayout()
        metric_export_path_layout.addWidget(self.metric_export_path_edit)
        metric_export_path_layout.addWidget(self.metric_export_browse_btn)

        self.metric_export_chart_checkbox = QCheckBox("保存时同步导出趋势图(PNG)")
        self.metric_export_chart_checkbox.setChecked(False)
        self.metric_export_chart_checkbox.toggled.connect(self.on_metric_export_chart_toggled)
        self.metric_export_chart_path_edit = QLineEdit("")
        self.metric_export_chart_path_edit.setPlaceholderText("可选: 图表PNG路径，留空自动生成")
        self.metric_export_chart_path_edit.textChanged.connect(self.on_metric_chart_path_changed)
        self.metric_export_chart_browse_btn = QPushButton("浏览...")
        self.metric_export_chart_browse_btn.clicked.connect(self.browse_metric_export_chart_output)

        metric_export_chart_path_layout = QHBoxLayout()
        metric_export_chart_path_layout.addWidget(self.metric_export_chart_path_edit)
        metric_export_chart_path_layout.addWidget(self.metric_export_chart_browse_btn)

        self.metric_export_file_label = QLabel("指标导出文件: 未启用")
        self.metric_export_file_label.setStyleSheet("color: #666;")
        self.metric_export_file_label.setWordWrap(True)

        export_layout.addWidget(self.metric_export_enable_checkbox)
        export_layout.addWidget(self.metric_export_select_btn)
        export_layout.addLayout(metric_export_path_layout)
        export_layout.addWidget(self.metric_export_chart_checkbox)
        export_layout.addLayout(metric_export_chart_path_layout)
        export_layout.addWidget(self.metric_export_file_label)
        export_group.setLayout(export_layout)

        ml_layout.addWidget(inference_group)
        ml_layout.addWidget(training_group)
        ml_layout.addWidget(export_group)
        ml_layout.addStretch()
        self.ml_window.setLayout(ml_layout)

    def open_ml_center_window(self):
        """打开机器学习配置子窗口。"""
        if not hasattr(self, 'ml_window') or self.ml_window is None:
            return
        self.ml_window.show()
        self.ml_window.raise_()
        self.ml_window.activateWindow()
    
    def init_components(self):
        """初始化组件"""
        self.data_source_manager = DataSourceManager()
        # 分析模块默认关闭，避免影响现有主链路。
        self.arterial_pipeline = self._build_arterial_pipeline_from_ui(enabled=False)
        self.latest_arterial_result = None
        self.latest_training_metrics = {
            'accuracy': None,
            'macro_f1': None,
            'confusion_summary': '',
        }
        self.train_start_ts = None
        self.train_elapsed_timer = QTimer(self)
        self.train_elapsed_timer.timeout.connect(self._update_train_elapsed_text)
        self.metrics_export_file = None
        self.metrics_export_fp = None
        self.metrics_export_writer = None
        self.metrics_export_fields = []
        self.metrics_export_rows = []
        self.last_metrics_export_summary = "指标导出文件: 未启用"
        self.pressure_ui_min_interval_ms = 80
        self.last_pressure_ui_update_ms = 0
        self.analysis_submit_interval_ms = 40
        self.analysis_backlog_interval_ms = 120
        self.last_analysis_submit_ms = 0
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
        self.ui_trim_drop_total = 0
        self.last_perf_ui_trim_drop = 0
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
        ui_trim_delta = max(0, self.ui_trim_drop_total - self.last_perf_ui_trim_drop)
        queue_size = self.data_queue.qsize()

        bytes_rate = int((bytes_count - self.last_perf_bytes_count) / dt)
        parsed_delta = max(0, parsed_frames - self.last_perf_parsed_frames)
        parse_ns_delta = max(0, parse_ns_total - self.last_perf_parse_ns_total)
        avg_parse_us = int((parse_ns_delta / parsed_delta) / 1000) if parsed_delta > 0 else 0

        self.perf_label.setText(
            f"速率: 接收 {recv_rate}/s | 处理 {proc_rate}/s | 队列 {queue_size} | 丢包+{drop_delta} | 追帧丢弃+{ui_trim_delta} | 字节 {bytes_rate} B/s | 解析 {avg_parse_us} us/帧"
        )

        self.last_perf_recv_count = recv_count
        self.last_perf_proc_count = proc_count
        self.last_perf_drop_count = drop_count
        self.last_perf_ui_trim_drop = self.ui_trim_drop_total
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

        now_ms = QDateTime.currentMSecsSinceEpoch()
        if now_ms - self.last_pressure_ui_update_ms >= self.pressure_ui_min_interval_ms:
            self.waveform_widget.update_pressure_matrix(
                matrix,
                result.get('timestamp', 0.0),
                metrics,
                prediction,
            )
            self.last_pressure_ui_update_ms = now_ms

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

        self._append_metrics_export_row(result)

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
        model_preference = self._ui_model_choice_to_preference(
            self.inference_model_combo.currentText() if hasattr(self, 'inference_model_combo') else "自动加载(按模型文件)"
        )

        return ArterialHealthPipeline(
            enabled=bool(enabled),
            grid_width=grid_width,
            grid_height=grid_height,
            analysis_stride=analysis_stride,
            model_path=model_path,
            model_preference=model_preference,
        )

    def apply_analysis_config(self):
        """应用动脉分析配置。"""
        self.arterial_pipeline = self._build_arterial_pipeline_from_ui()
        self._reset_arterial_ui_state()
        grid_info = f"{self.arterial_pipeline.adapter.grid_width}x{self.arterial_pipeline.adapter.grid_height}"
        model_status = self.arterial_pipeline.get_model_status()
        model_mode = str(model_status.get('mode', 'rule'))
        model_error = str(model_status.get('load_error', '') or '')
        model_requested = str(model_status.get('requested_model', 'auto'))
        model_detected = str(model_status.get('detected_model', 'unknown'))

        if self.arterial_pipeline.enabled:
            if model_mode == 'external':
                QMessageBox.information(
                    self,
                    "动脉分析",
                    f"分析已启用，点阵: {grid_info}\n模型状态: external（已加载）\n请求模型: {model_requested} | 检测模型: {model_detected}",
                )
            elif self.model_path_edit.text().strip():
                QMessageBox.warning(
                    self,
                    "动脉分析",
                    f"分析已启用，点阵: {grid_info}\n模型状态: rule（已降级）\n请求模型: {model_requested} | 检测模型: {model_detected}\n原因: {model_error or '未知错误'}",
                )
            else:
                QMessageBox.information(
                    self,
                    "动脉分析",
                    f"分析已启用，点阵: {grid_info}\n模型状态: rule（未配置模型）\n请求模型: {model_requested}",
                )
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

    def on_inference_model_changed(self, _: str):
        """推理模型类型改变时，若已选择模型文件则即时重新校验。"""
        if self.model_path_edit.text().strip():
            self._validate_selected_model_path(show_success=False)

    def _ui_model_choice_to_preference(self, choice_text: str) -> str:
        mapping = {
            "自动加载(按模型文件)": "auto",
            "规则引擎": "rule",
            "随机森林": "random_forest",
            "逻辑回归": "logistic_regression",
            "支持向量机(SVM)": "svm",
            "梯度提升树": "gradient_boosting",
        }
        return mapping.get(choice_text, "auto")

    def _ui_training_choice_to_arg(self, choice_text: str) -> str:
        mapping = {
            "随机森林": "rf",
            "逻辑回归": "logreg",
            "支持向量机(SVM)": "svm",
            "梯度提升树": "gbdt",
        }
        return mapping.get(choice_text, "rf")

    def _model_arg_to_ui_choice(self, model_arg: str) -> str:
        mapping = {
            "rf": "随机森林",
            "logreg": "逻辑回归",
            "svm": "支持向量机(SVM)",
            "gbdt": "梯度提升树",
        }
        return mapping.get(model_arg, "随机森林")

    def _safe_float(self, value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _summarize_confusion_matrix(self, matrix, classes) -> str:
        if not isinstance(matrix, list) or not matrix or not isinstance(matrix[0], list):
            return "混淆矩阵摘要: 不可用"

        row_count = len(matrix)
        col_count = len(matrix[0]) if matrix[0] else 0
        if row_count == 0 or col_count == 0:
            return "混淆矩阵摘要: 空矩阵"

        total = 0
        diag_correct = 0
        row_sums = []
        col_sums = [0 for _ in range(col_count)]

        for r_idx, row in enumerate(matrix):
            if not isinstance(row, list) or len(row) != col_count:
                return "混淆矩阵摘要: 矩阵格式不规则"

            row_total = 0
            for c_idx, raw_cell in enumerate(row):
                cell = self._safe_float(raw_cell)
                if cell is None:
                    return "混淆矩阵摘要: 包含非数值项"
                row_total += cell
                col_sums[c_idx] += cell
                total += cell
                if r_idx == c_idx:
                    diag_correct += cell
            row_sums.append(row_total)

        overall = diag_correct / total if total > 0 else 0.0
        parts = [f"规模 {row_count}x{col_count}，总样本 {int(total)}，对角正确率 {overall:.2%}"]

        detail_rows = min(row_count, 4)
        for i in range(detail_rows):
            label = str(classes[i]) if isinstance(classes, list) and i < len(classes) else str(i)
            tp = self._safe_float(matrix[i][i]) or 0.0
            recall = (tp / row_sums[i]) if row_sums[i] > 0 else 0.0
            precision = (tp / col_sums[i]) if col_sums[i] > 0 else 0.0
            parts.append(f"{label}: 召回 {recall:.2%}，精确 {precision:.2%}")

        if row_count > detail_rows:
            parts.append(f"其余 {row_count - detail_rows} 类已省略")

        return "；".join(parts)

    def _read_training_meta_summary(self, meta_output: str):
        metrics_text = "测试指标: 暂无"
        matrix_text = "混淆矩阵摘要: 暂无"
        if not meta_output or not os.path.isfile(meta_output):
            return metrics_text, matrix_text

        try:
            with open(meta_output, "r", encoding="utf-8") as fp:
                meta = json.load(fp)
        except (OSError, json.JSONDecodeError):
            return metrics_text, "混淆矩阵摘要: meta 文件读取失败"

        metrics = meta.get("metrics", {})
        accuracy = self._safe_float(metrics.get("accuracy"))
        macro_f1 = self._safe_float(metrics.get("macro avg", {}).get("f1-score"))
        if accuracy is not None or macro_f1 is not None:
            acc_text = "N/A" if accuracy is None else f"{accuracy:.4f}"
            f1_text = "N/A" if macro_f1 is None else f"{macro_f1:.4f}"
            metrics_text = f"测试指标: accuracy={acc_text}，macro-f1={f1_text}"

        matrix = meta.get("confusion_matrix")
        classes = meta.get("classes", [])
        matrix_text = self._summarize_confusion_matrix(matrix, classes)
        return metrics_text, matrix_text

    def _extract_training_meta_values(self, meta_output: str):
        values = {
            'accuracy': None,
            'macro_f1': None,
            'confusion_summary': '',
        }
        if not meta_output or not os.path.isfile(meta_output):
            return values

        try:
            with open(meta_output, "r", encoding="utf-8") as fp:
                meta = json.load(fp)
        except (OSError, json.JSONDecodeError):
            return values

        metrics = meta.get("metrics", {})
        values['accuracy'] = self._safe_float(metrics.get("accuracy"))
        values['macro_f1'] = self._safe_float(metrics.get("macro avg", {}).get("f1-score"))
        values['confusion_summary'] = self._summarize_confusion_matrix(
            meta.get("confusion_matrix"),
            meta.get("classes", []),
        )
        return values

    def _selected_metric_export_fields(self):
        fields = []
        for _, field_key, _ in self.METRIC_EXPORT_ITEMS:
            checkbox = self.metric_export_checkboxes.get(field_key)
            if checkbox is not None and checkbox.isChecked():
                fields.append(field_key)
        return fields

    def _create_metric_export_popup(self):
        self.metric_export_popup = QWidget(self.ml_window, Qt.Popup)
        popup_layout = QVBoxLayout()
        popup_layout.setContentsMargins(8, 8, 8, 8)
        popup_layout.setSpacing(6)

        for label, field_key, default_checked in self.METRIC_EXPORT_ITEMS:
            checkbox = QCheckBox(label)
            checkbox.setChecked(default_checked)
            checkbox.toggled.connect(self._update_metric_export_selector_text)
            self.metric_export_checkboxes[field_key] = checkbox
            popup_layout.addWidget(checkbox)

        self.metric_export_popup.setLayout(popup_layout)
        self.metric_export_popup.setMinimumWidth(300)

    def show_metric_export_popup(self):
        if not hasattr(self, 'metric_export_popup'):
            return
        button = self.metric_export_select_btn
        global_pos = button.mapToGlobal(button.rect().bottomLeft())
        self.metric_export_popup.move(global_pos)
        self.metric_export_popup.show()
        self.metric_export_popup.raise_()
        self.metric_export_popup.activateWindow()

    def _update_metric_export_selector_text(self):
        selected_count = len(self._selected_metric_export_fields())
        self.metric_export_select_btn.setText(f"导出指标选择（已选 {selected_count} 项）")

    def browse_metric_export_output(self):
        """浏览指标导出文件路径。"""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "选择指标导出路径",
            self.metric_export_path_edit.text() or os.path.join("data", "metrics_export.csv"),
            "CSV文件 (*.csv);;所有文件 (*)",
        )
        if file_path:
            self.metric_export_path_edit.setText(file_path)

    def browse_metric_export_chart_output(self):
        """浏览指标图表导出路径。"""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "选择指标图表导出路径",
            self.metric_export_chart_path_edit.text() or os.path.join("data", "metrics_chart.png"),
            "PNG图片 (*.png);;所有文件 (*)",
        )
        if file_path:
            self.metric_export_chart_path_edit.setText(file_path)

    def _resolve_metric_export_file_path(self):
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        custom_path = self.metric_export_path_edit.text().strip() if hasattr(self, 'metric_export_path_edit') else ""
        if custom_path:
            path = custom_path
            if not os.path.isabs(path):
                path = os.path.abspath(os.path.join(project_root, path))
            root, ext = os.path.splitext(path)
            if not ext:
                path = f"{root}.csv"
            target_dir = os.path.dirname(path)
            if target_dir:
                os.makedirs(target_dir, exist_ok=True)
            return path

        save_dir = self.save_path_edit.text().strip() or "data"
        if not os.path.isabs(save_dir):
            save_dir = os.path.abspath(os.path.join(project_root, save_dir))
        os.makedirs(save_dir, exist_ok=True)
        file_name = f"metrics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        return os.path.join(save_dir, file_name)

    def _resolve_metric_chart_output_path(self, csv_path: str):
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        custom_path = self.metric_export_chart_path_edit.text().strip() if hasattr(self, 'metric_export_chart_path_edit') else ""
        if custom_path:
            path = custom_path
            if not os.path.isabs(path):
                path = os.path.abspath(os.path.join(project_root, path))
            root, ext = os.path.splitext(path)
            if ext.lower() != '.png':
                path = f"{root}.png"
            target_dir = os.path.dirname(path)
            if target_dir:
                os.makedirs(target_dir, exist_ok=True)
            return path

        base, _ = os.path.splitext(csv_path)
        return f"{base}_chart.png"

    def _start_metrics_export_if_needed(self):
        self._stop_metrics_export()

        if not hasattr(self, 'metric_export_enable_checkbox') or not self.metric_export_enable_checkbox.isChecked():
            self.last_metrics_export_summary = "指标导出文件: 未启用"
            self.metric_export_file_label.setText(self.last_metrics_export_summary)
            return {
                'started': False,
                'csv_path': None,
                'reason': self.last_metrics_export_summary,
            }

        selected_fields = self._selected_metric_export_fields()
        if not selected_fields:
            self.last_metrics_export_summary = "指标导出文件: 未选择任何指标"
            self.metric_export_file_label.setText(self.last_metrics_export_summary)
            return {
                'started': False,
                'csv_path': None,
                'reason': self.last_metrics_export_summary,
            }

        file_path = self._resolve_metric_export_file_path()

        try:
            self.metrics_export_fp = open(file_path, 'w', newline='', encoding='utf-8-sig')
            self.metrics_export_writer = csv.DictWriter(
                self.metrics_export_fp,
                fieldnames=['timestamp'] + selected_fields,
            )
            self.metrics_export_writer.writeheader()
            self.metrics_export_file = file_path
            self.metrics_export_fields = selected_fields
            self.metrics_export_rows = []
            self.fsm_debug_print(
                f"[EXPORT][START] csv={file_path} fields={selected_fields} chart_enabled={self.metric_export_chart_checkbox.isChecked()}"
            )
            self.last_metrics_export_summary = f"指标导出文件: {file_path}"
            self.metric_export_file_label.setText(self.last_metrics_export_summary)
            return {
                'started': True,
                'csv_path': file_path,
                'reason': '',
            }
        except OSError as e:
            self.metrics_export_fp = None
            self.metrics_export_writer = None
            self.metrics_export_file = None
            self.metrics_export_fields = []
            self.fsm_debug_print(f"[EXPORT][START][ERROR] path={file_path} error={e}")
            self.last_metrics_export_summary = f"指标导出文件: 打开失败 ({e})"
            self.metric_export_file_label.setText(self.last_metrics_export_summary)
            return {
                'started': False,
                'csv_path': None,
                'reason': self.last_metrics_export_summary,
            }

    def on_metric_export_chart_toggled(self, checked: bool):
        """勾选PNG导出时自动开启CSV导出，并给出路径与时机提示。"""
        if checked and not self.metric_export_enable_checkbox.isChecked():
            self.metric_export_enable_checkbox.setChecked(True)

        csv_target = self._resolve_metric_export_file_path()
        chart_target = self._resolve_metric_chart_output_path(csv_target)

        if checked:
            self.metric_export_file_label.setText(
                f"指标导出文件: {csv_target}\n图表导出文件: {chart_target}"
            )
            if self.data_source_manager.is_connected():
                self._ensure_metrics_export_runtime(silent=False)
            QMessageBox.information(
                self,
                "趋势图导出",
                f"已启用PNG趋势图导出。\nCSV: {csv_target}\nPNG: {chart_target}\n\n提示: PNG会在停止保存或断开连接时生成。",
            )
        else:
            if self.metric_export_enable_checkbox.isChecked():
                self.metric_export_file_label.setText(f"指标导出文件: {csv_target}")
            else:
                self.metric_export_file_label.setText("指标导出文件: 未启用")

    def on_metric_export_path_changed(self, _: str):
        """导出路径修改后，若会话已运行则立即切换到新路径。"""
        if self.metrics_export_writer is not None:
            self.fsm_debug_print("[EXPORT][PATH] csv_path_changed -> restart session")
            self._start_metrics_export_if_needed()
        else:
            if self.metric_export_enable_checkbox.isChecked():
                target = self._resolve_metric_export_file_path()
                self.metric_export_file_label.setText(f"指标导出文件: {target}")

    def on_metric_chart_path_changed(self, _: str):
        """图表路径修改提示。"""
        if self.metric_export_chart_checkbox.isChecked():
            csv_target = self._resolve_metric_export_file_path()
            target = self._resolve_metric_chart_output_path(csv_target)
            self.metric_export_file_label.setText(f"指标导出文件: {csv_target}\n图表导出文件: {target}")

    def on_metric_export_enabled_changed(self, checked: bool):
        """保存过程中允许动态启停指标导出。"""
        if checked:
            csv_target = self._resolve_metric_export_file_path()
            if self.metric_export_chart_checkbox.isChecked():
                chart_target = self._resolve_metric_chart_output_path(csv_target)
                self.metric_export_file_label.setText(f"指标导出文件: {csv_target}\n图表导出文件: {chart_target}")
            else:
                self.metric_export_file_label.setText(f"指标导出文件: {csv_target}")
        
        if not self.data_source_manager.is_connected():
            if checked:
                QMessageBox.information(
                    self,
                    "指标导出",
                    "已启用CSV导出。\n当前未连接数据源，连接并开始保存后将自动写入。",
                )
            else:
                self.last_metrics_export_summary = "指标导出文件: 未启用"
                self.metric_export_file_label.setText(self.last_metrics_export_summary)
            return

        if checked:
            start_result = self._start_metrics_export_if_needed()
            if start_result.get('started'):
                csv_path = str(start_result.get('csv_path') or '')
                if self.metric_export_chart_checkbox.isChecked():
                    chart_target = self._resolve_metric_chart_output_path(csv_path)
                    QMessageBox.information(self, "指标导出", f"已启用指标导出:\nCSV: {csv_path}\nPNG: {chart_target}")
                else:
                    QMessageBox.information(self, "指标导出", f"已启用CSV导出:\n{csv_path}")
            else:
                QMessageBox.warning(self, "指标导出", str(start_result.get('reason') or '启动失败'))
        else:
            stop_result = self._stop_metrics_export()
            summary = str(stop_result.get('summary') or '指标导出已关闭')
            QMessageBox.information(self, "指标导出", summary)

    def _ensure_metrics_export_runtime(self, silent: bool = True):
        """按连接状态与导出开关自动维护指标导出会话。"""
        connected = self.data_source_manager.is_connected()
        enabled = self.metric_export_enable_checkbox.isChecked() if hasattr(self, 'metric_export_enable_checkbox') else False

        if connected and enabled:
            if self.metrics_export_writer is None:
                start_result = self._start_metrics_export_if_needed()
                if not silent and not start_result.get('started'):
                    QMessageBox.warning(self, "指标导出", str(start_result.get('reason') or '指标导出未成功启动'))
        else:
            if self.metrics_export_writer is not None:
                self._stop_metrics_export()

    def _stop_metrics_export(self):
        file_path = self.metrics_export_file
        rows_snapshot = self.metrics_export_rows.copy()
        fields_snapshot = self.metrics_export_fields.copy()
        self.fsm_debug_print(
            f"[EXPORT][STOP] csv={file_path} rows={len(rows_snapshot)} fields={fields_snapshot} chart_enabled={self.metric_export_chart_checkbox.isChecked() if hasattr(self, 'metric_export_chart_checkbox') else False}"
        )
        if self.metrics_export_fp is not None:
            try:
                self.metrics_export_fp.close()
            except OSError:
                pass

        chart_path = None
        chart_reason = ""
        chart_enabled = hasattr(self, 'metric_export_chart_checkbox') and self.metric_export_chart_checkbox.isChecked()
        if chart_enabled:
            if not file_path:
                chart_reason = "未创建指标CSV导出"
            else:
                chart_path = self._resolve_metric_chart_output_path(file_path)
                exported = self._export_metrics_chart_image(rows_snapshot, fields_snapshot, chart_path)
                if not exported:
                    if not rows_snapshot:
                        chart_reason = "保存期间没有可导出的分析样本"
                    elif not fields_snapshot:
                        chart_reason = "未选择导出指标"
                    else:
                        chart_reason = "所选指标均为非数值或保存失败"
                    placeholder_ok = self._export_chart_placeholder(chart_path, chart_reason)
                    if placeholder_ok:
                        self.fsm_debug_print(f"[EXPORT][CHART] output={chart_path} (placeholder)")
                    else:
                        self.fsm_debug_print(
                            f"[EXPORT][CHART][ERROR] output={chart_path} reason={chart_reason}"
                        )
                        chart_path = None
                else:
                    self.fsm_debug_print(f"[EXPORT][CHART] output={chart_path}")

        self.metrics_export_fp = None
        self.metrics_export_writer = None
        self.metrics_export_file = None
        self.metrics_export_fields = []
        self.metrics_export_rows = []

        if file_path and chart_path:
            self.last_metrics_export_summary = f"指标导出文件: {file_path}\n图表导出文件: {chart_path}"
        elif file_path and chart_reason:
            if chart_path:
                self.last_metrics_export_summary = f"指标导出文件: {file_path}\n图表导出文件: {chart_path}（占位图：{chart_reason}）"
            else:
                self.last_metrics_export_summary = f"指标导出文件: {file_path}\n未生成图表：{chart_reason}"
        elif file_path:
            self.last_metrics_export_summary = f"指标导出文件: {file_path}"
        elif chart_reason:
            self.last_metrics_export_summary = chart_reason
        else:
            self.last_metrics_export_summary = "指标导出文件: 未启用"

        self.metric_export_file_label.setText(self.last_metrics_export_summary)
        return {
            'csv_path': file_path,
            'chart_path': chart_path,
            'chart_reason': chart_reason,
            'summary': self.last_metrics_export_summary,
        }

    def _export_chart_placeholder(self, output_path: str, reason: str) -> bool:
        image = QImage(1200, 680, QImage.Format_ARGB32)
        image.fill(QColor(255, 255, 255))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor(40, 40, 40), 2))
        painter.drawRect(40, 40, 1120, 600)
        painter.setPen(QPen(QColor(70, 70, 70), 1))
        painter.drawText(80, 120, "指标趋势图（占位图）")
        painter.drawText(80, 170, f"原因: {reason}")
        painter.drawText(80, 220, "提示: 请确认已启用分析并接收到有效数据帧后再导出。")
        painter.end()
        try:
            return bool(image.save(output_path, "PNG"))
        except Exception:
            return False

    def _export_metrics_chart_image(self, rows, fields, output_path: str) -> bool:
        if not rows or not fields:
            return False

        numeric_series = {}
        for field in fields:
            values = []
            for row in rows:
                value = self._safe_float(row.get(field))
                values.append(value)
            if any(v is not None for v in values):
                numeric_series[field] = values

        if not numeric_series:
            return False

        width = 1200
        height = 680
        margin_left = 70
        margin_right = 30
        margin_top = 40
        margin_bottom = 70
        plot_w = width - margin_left - margin_right
        plot_h = height - margin_top - margin_bottom

        image = QImage(width, height, QImage.Format_ARGB32)
        image.fill(QColor(255, 255, 255))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)

        painter.setPen(QPen(QColor(40, 40, 40), 1))
        painter.drawLine(margin_left, margin_top + plot_h, margin_left + plot_w, margin_top + plot_h)
        painter.drawLine(margin_left, margin_top, margin_left, margin_top + plot_h)

        min_v = None
        max_v = None
        for values in numeric_series.values():
            for v in values:
                if v is None:
                    continue
                min_v = v if min_v is None else min(min_v, v)
                max_v = v if max_v is None else max(max_v, v)

        if min_v is None or max_v is None:
            painter.end()
            return False

        if abs(max_v - min_v) < 1e-12:
            max_v += 1.0
            min_v -= 1.0

        color_pool = [
            QColor(220, 20, 60), QColor(30, 144, 255), QColor(34, 139, 34),
            QColor(255, 140, 0), QColor(138, 43, 226), QColor(47, 79, 79),
            QColor(199, 21, 133), QColor(0, 128, 128), QColor(70, 130, 180),
        ]

        total_points = max(2, len(rows))
        legend_y = 20
        for idx, (field, values) in enumerate(numeric_series.items()):
            color = color_pool[idx % len(color_pool)]
            painter.setPen(QPen(color, 2))

            prev_x = None
            prev_y = None
            for i, v in enumerate(values):
                if v is None:
                    prev_x = None
                    prev_y = None
                    continue
                x = margin_left + int((i / (total_points - 1)) * plot_w)
                ratio = (v - min_v) / (max_v - min_v)
                y = margin_top + int((1.0 - ratio) * plot_h)
                if prev_x is not None:
                    painter.drawLine(prev_x, prev_y, x, y)
                prev_x, prev_y = x, y

            painter.setPen(QPen(color, 8))
            painter.drawPoint(margin_left + idx * 120, legend_y)
            painter.setPen(QPen(QColor(30, 30, 30), 1))
            painter.drawText(margin_left + 10 + idx * 120, legend_y + 5, field)

        painter.setPen(QPen(QColor(60, 60, 60), 1))
        painter.drawText(margin_left, height - 30, "样本序号")
        painter.drawText(10, margin_top + 10, "数值")
        painter.drawText(width - 280, height - 10, f"范围: [{min_v:.4f}, {max_v:.4f}]")
        painter.end()

        try:
            return bool(image.save(output_path, "PNG"))
        except Exception:
            return False

    def _append_metrics_export_row(self, result):
        if self.metrics_export_writer is None:
            return

        metrics = result.get('metrics', {}) or {}
        prediction = result.get('prediction', {}) or {}
        row = {
            'timestamp': result.get('timestamp', 0.0),
        }

        if 'train_accuracy' in self.metrics_export_fields:
            row['train_accuracy'] = self.latest_training_metrics.get('accuracy')
        if 'train_macro_f1' in self.metrics_export_fields:
            row['train_macro_f1'] = self.latest_training_metrics.get('macro_f1')
        if 'train_confusion_summary' in self.metrics_export_fields:
            row['train_confusion_summary'] = self.latest_training_metrics.get('confusion_summary', '')

        if 'health_bpm' in self.metrics_export_fields:
            row['health_bpm'] = metrics.get('bpm')
        if 'health_amplitude' in self.metrics_export_fields:
            row['health_amplitude'] = metrics.get('amplitude')
        if 'health_consistency' in self.metrics_export_fields:
            row['health_consistency'] = metrics.get('consistency')
        if 'health_repeatability' in self.metrics_export_fields:
            row['health_repeatability'] = metrics.get('repeatability')

        if 'eval_label' in self.metrics_export_fields:
            row['eval_label'] = prediction.get('label')
        if 'eval_score' in self.metrics_export_fields:
            row['eval_score'] = prediction.get('score')
        if 'eval_risk_level' in self.metrics_export_fields:
            row['eval_risk_level'] = prediction.get('risk_level')
        if 'eval_mode' in self.metrics_export_fields:
            row['eval_mode'] = prediction.get('mode')

        try:
            self.metrics_export_writer.writerow(row)
            self.metrics_export_fp.flush()
            self.metrics_export_rows.append(dict(row))
            if len(self.metrics_export_rows) in (1, 10, 100):
                self.fsm_debug_print(
                    f"[EXPORT][APPEND] csv={self.metrics_export_file} rows={len(self.metrics_export_rows)}"
                )
        except OSError:
            self._stop_metrics_export()
            self.metric_export_file_label.setText("指标导出文件: 写入失败，已停止")

    def _update_train_elapsed_text(self):
        if self.train_start_ts is None:
            return
        elapsed_s = max(0.0, time.time() - self.train_start_ts)
        self.train_metrics_summary_label.setText(f"测试指标: 训练中... 已运行 {elapsed_s:.1f}s")

    def _handle_train_finished_signal(self, payload):
        if not isinstance(payload, dict):
            return
        self._on_train_model_finished(
            bool(payload.get('success', False)),
            str(payload.get('dataset_path', '')),
            str(payload.get('model_output', '')),
            str(payload.get('meta_output', '')),
            str(payload.get('model_arg', 'rf')),
            str(payload.get('stdout', '')),
            str(payload.get('stderr', '')),
        )

    def _validate_selected_model_path(self, show_success: bool = False) -> bool:
        """校验模型文件可读性。"""
        model_path = self.model_path_edit.text().strip()
        if not model_path:
            return False

        checker = ModelRunner(
            model_path=model_path,
            model_preference=self._ui_model_choice_to_preference(self.inference_model_combo.currentText()),
        )
        status = checker.get_status()
        if str(status.get('mode')) == 'external' and bool(status.get('has_model')):
            if show_success:
                QMessageBox.information(
                    self,
                    "模型校验",
                    f"模型文件校验通过，可用于外部推理。\n模型类型: {status.get('detected_model', 'unknown')}",
                )
            return True

        QMessageBox.warning(
            self,
            "模型校验",
            f"模型文件不可用，将在运行时降级为规则模式。\n原因: {status.get('load_error') or '未知错误'}",
        )
        return False

    def browse_train_dataset(self):
        """浏览训练数据CSV。"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择训练数据CSV",
            self.train_dataset_edit.text() or os.getcwd(),
            "CSV文件 (*.csv);;所有文件 (*)",
        )
        if file_path:
            self.train_dataset_edit.setText(file_path)

    def browse_train_output(self):
        """浏览训练模型输出文件。"""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "选择模型输出路径",
            self.train_output_edit.text() or os.path.join("data", "models", "arterial_model.joblib"),
            "模型文件 (*.joblib);;所有文件 (*)",
        )
        if file_path:
            self.train_output_edit.setText(file_path)

    def _resolve_path_from_ui(self, ui_path: str) -> str:
        raw = str(ui_path or "").strip()
        if not raw:
            return ""

        if os.path.isabs(raw):
            return os.path.abspath(raw)

        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        return os.path.abspath(os.path.join(project_root, raw))

    def _resolve_training_launcher(self):
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        default_script = os.path.join(project_root, "tools", "train_arterial_model.py")

        if getattr(sys, 'frozen', False):
            # 打包版优先走内置训练服务，避免sys.executable自启动上位机窗口。
            return ["__internal_training__"], project_root, ""

        if not getattr(sys, 'frozen', False):
            if not os.path.isfile(default_script):
                return None, None, "训练脚本不存在，请检查 tools/train_arterial_model.py。"
            return [sys.executable, default_script], project_root, ""

        return None, None, "训练环境不可用。"

    def train_model_from_ui(self):
        """在上位机中触发训练脚本，完成后自动加载模型。"""
        if self.train_model_busy:
            QMessageBox.information(self, "训练任务", "训练任务正在执行，请稍候。")
            return

        dataset_path = self._resolve_path_from_ui(self.train_dataset_edit.text())
        model_output = self._resolve_path_from_ui(self.train_output_edit.text())
        if not dataset_path:
            QMessageBox.warning(self, "训练任务", "请先选择训练数据CSV。")
            return
        if not model_output:
            QMessageBox.warning(self, "训练任务", "请先设置模型输出路径。")
            return

        if not os.path.isfile(dataset_path):
            QMessageBox.warning(self, "训练任务", f"训练数据不存在:\n{dataset_path}")
            return
        if os.path.splitext(dataset_path)[1].lower() != ".csv":
            QMessageBox.warning(self, "训练任务", "训练数据必须是CSV文件。")
            return

        model_dir = os.path.dirname(model_output)
        try:
            if model_dir:
                os.makedirs(model_dir, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(self, "训练任务", f"模型输出目录不可用:\n{model_dir}\n错误: {e}")
            return

        train_launcher, train_cwd, train_error = self._resolve_training_launcher()
        if train_launcher is None:
            QMessageBox.warning(self, "训练任务", train_error or "训练环境不可用。")
            return

        # 将解析后的绝对路径回填到UI，避免用户误判默认相对路径。
        self.train_dataset_edit.setText(dataset_path)
        self.train_output_edit.setText(model_output)

        test_size_text = self.train_test_size_edit.text().strip() or "0.2"
        seed_text = self.train_seed_edit.text().strip() or "42"
        try:
            test_size = float(test_size_text)
            if test_size <= 0 or test_size >= 1:
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "训练任务", "测试集比例必须是 0 到 1 之间的小数（建议0.1~0.4）。")
            return

        try:
            seed = int(seed_text)
        except ValueError:
            QMessageBox.warning(self, "训练任务", "随机种子必须是整数。")
            return

        extra_args_text = self.train_extra_args_edit.text().strip()
        try:
            extra_args = shlex.split(extra_args_text) if extra_args_text else []
        except ValueError as e:
            QMessageBox.warning(self, "训练任务", f"高级参数格式错误: {e}")
            return

        model_arg = self._ui_training_choice_to_arg(self.train_model_type_combo.currentText())
        self.train_model_busy = True
        self.train_start_ts = time.time()
        self.train_elapsed_timer.start(500)
        self.train_model_btn.setEnabled(False)
        self.train_model_btn.setText("训练中...")
        self.train_metrics_summary_label.setText("测试指标: 训练中...")
        self.train_conf_matrix_label.setText("混淆矩阵摘要: 训练中...")

        worker = threading.Thread(
            target=self._train_model_worker,
            args=(train_launcher, train_cwd, dataset_path, model_output, model_arg, test_size, seed, extra_args),
            daemon=True,
        )
        worker.start()

    def _train_model_worker(self, train_launcher, train_cwd: str, dataset_path: str, model_output: str, model_arg: str, test_size: float, seed: int, extra_args):
        """后台执行训练脚本，完成后切回主线程更新UI。"""
        base_name, _ = os.path.splitext(model_output)
        meta_output = f"{base_name}_meta.json"

        cmd = list(train_launcher) + [
            "--input",
            dataset_path,
            "--model-output",
            model_output,
            "--meta-output",
            meta_output,
            "--model-type",
            model_arg,
            "--test-size",
            str(test_size),
            "--seed",
            str(seed),
        ]
        if extra_args:
            cmd.extend(extra_args)

        try:
            if train_launcher and train_launcher[0] == "__internal_training__":
                from analytics.ml.training_service import build_arg_parser, run_training

                parser = build_arg_parser()
                args = parser.parse_args(cmd[1:])
                result = run_training(args)
                stdout = str(result.get("stdout", ""))
                stderr = ""
                success = True
            else:
                proc = subprocess.run(
                    cmd,
                    cwd=train_cwd,
                    capture_output=True,
                    text=True,
                    timeout=300,
                    check=False,
                )
                stdout = proc.stdout or ""
                stderr = proc.stderr or ""
                success = proc.returncode == 0
        except subprocess.TimeoutExpired:
            success = False
            stdout = ""
            stderr = "训练超时（300秒），已终止。可先减小数据量或改用更快模型（如logreg/rf）。"
        except SystemExit as e:
            success = False
            stdout = ""
            stderr = f"训练参数错误: {e}"
        except Exception as e:
            success = False
            stdout = ""
            stderr = str(e)

        self.train_finished_signal.emit(
            {
                'success': success,
                'dataset_path': dataset_path,
                'model_output': model_output,
                'meta_output': meta_output,
                'model_arg': model_arg,
                'stdout': stdout,
                'stderr': stderr,
            }
        )

    def _on_train_model_finished(
        self,
        success: bool,
        dataset_path: str,
        model_output: str,
        meta_output: str,
        model_arg: str,
        stdout: str,
        stderr: str,
    ):
        """训练完成后的UI反馈与自动加载。"""
        self.train_elapsed_timer.stop()
        self.train_start_ts = None
        self.train_model_busy = False
        self.train_model_btn.setEnabled(True)
        self.train_model_btn.setText("开始训练并加载")

        if not success:
            detail = (stderr or stdout or "未知错误")[-1200:]
            self.train_metrics_summary_label.setText("测试指标: 训练失败")
            self.train_conf_matrix_label.setText("混淆矩阵摘要: 训练失败")
            QMessageBox.warning(self, "训练失败", f"训练脚本执行失败。\n数据集: {dataset_path}\n详情:\n{detail}")
            return

        metrics_text, matrix_text = self._read_training_meta_summary(meta_output)
        self.train_metrics_summary_label.setText(metrics_text)
        self.train_conf_matrix_label.setText(matrix_text)
        self.latest_training_metrics = self._extract_training_meta_values(meta_output)

        self.model_path_edit.setText(model_output)
        self.inference_model_combo.setCurrentText(self._model_arg_to_ui_choice(model_arg))
        self._validate_selected_model_path(show_success=False)
        self.apply_analysis_config()
        QMessageBox.information(self, "训练完成", "模型训练成功，已自动回填模型路径并应用推理配置。")
    
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
            export_result = self._stop_metrics_export()
            self.save_btn.setText("开始保存")
            self.save_file_label.setText("保存文件: 无")
            if export_result.get('csv_path'):
                detail = f"CSV: {export_result.get('csv_path')}"
                if export_result.get('chart_path'):
                    detail += f"\nPNG: {export_result.get('chart_path')}"
                elif export_result.get('chart_reason'):
                    detail += f"\n{export_result.get('chart_reason')}"
                QMessageBox.information(self, "导出完成", detail)
            self.auto_save_enabled = False
        else:
            save_path = self.save_path_edit.text()
            if save_path:
                self.data_source_manager.set_save_path(save_path)
            success = self.data_source_manager.start_saving()
            if success:
                export_start_result = self._start_metrics_export_if_needed() if self.metric_export_enable_checkbox.isChecked() else {'started': False, 'reason': ''}
                self.save_btn.setText("停止保存")
                save_file = self.data_source_manager.get_save_file()
                self.save_file_label.setText(f"保存文件: {save_file}")
                if not export_start_result.get('started') and self.metric_export_enable_checkbox.isChecked():
                    QMessageBox.warning(self, "指标导出", str(export_start_result.get('reason') or '指标导出未成功启动'))
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

        # 指标导出与“开始保存”按钮解耦：连接中且勾选导出时自动启动。
        self._ensure_metrics_export_runtime(silent=True)

        queue_size_start = self.data_queue.qsize()

        # 低延迟优先：队列积压时主动追帧，必要时丢弃最旧数据。
        if queue_size_start > 3200:
            trim_target = 900
            trim_count = max(0, queue_size_start - trim_target)
            trimmed = 0
            while trimmed < trim_count:
                try:
                    self.data_queue.get_nowait()
                    trimmed += 1
                except queue.Empty:
                    break
            self.ui_trim_drop_total += trimmed
            queue_size_start = self.data_queue.qsize()

        # 每轮处理上限 + 时间预算，队列高水位时自适应加大消费能力。
        if queue_size_start > 1600:
            max_batch_per_update = 1200
            update_budget_s = 0.030
        elif queue_size_start > 600:
            max_batch_per_update = 700
            update_budget_s = 0.020
        else:
            max_batch_per_update = 320
            update_budget_s = 0.012

        loop_start = time.perf_counter()
        processed_count = 0
        has_valid_data = False
        has_format_error = False
        latest_packet_for_analysis = None

        while processed_count < max_batch_per_update:
            if processed_count > 0 and (time.perf_counter() - loop_start) >= update_budget_s:
                break
            
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
                latest_packet_for_analysis = data_dict
                
                processed_count += 1
            except queue.Empty:
                # 队列为空，退出循环
                break
            except Exception as e:
                self.log_print(f"[MainWindow] 处理数据失败: {e}")
                break

        # 分析链路采用“当前轮最新帧”策略：减轻CPU压力，优先降低端到端延迟。
        if latest_packet_for_analysis is not None:
            now_ms = QDateTime.currentMSecsSinceEpoch()
            backlog_size = self.data_queue.qsize()
            interval_ms = self.analysis_backlog_interval_ms if backlog_size > 300 else self.analysis_submit_interval_ms
            if now_ms - self.last_analysis_submit_ms >= interval_ms:
                self._submit_arterial_analysis(latest_packet_for_analysis)
                self.last_analysis_submit_ms = now_ms

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
        self._stop_metrics_export()
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