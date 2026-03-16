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
                             QGroupBox, QFormLayout, QMessageBox, QFileDialog, QCheckBox, QColorDialog, QMenu, QAction, QShortcut, QComboBox, QTextEdit, QSplitter, QInputDialog, QDockWidget, QToolBar)
from PyQt5.QtCore import Qt, QTimer, QDateTime, QSize, QThread, pyqtSignal, QEvent
from PyQt5.QtGui import QFont, QPainter, QColor, QPen, QBrush, QRadialGradient, QKeySequence

from data_sources.manager import (
    DataSourceManager,
    create_udp_source,
    create_tcp_source,
    create_serial_source,
    create_file_source,
)
from visualization.waveform_widget import WaveformWidget
from enum import Enum


class DataReceiveThread(QThread):
    """数据接收线程
    
    在后台接收和解析数据，将数据放入队列
    """
    
    # 定义信号
    disconnect_signal = pyqtSignal()  # 断开连接信号
    
    def __init__(self, data_source_manager, data_queue, stop_event, log_print, parent=None):
        """初始化数据接收线程
        
        Args:
            data_source_manager: 数据源管理器
            data_queue: 数据队列
            stop_event: 停止事件
            log_print: 日志打印函数
            parent: 父对象
        """
        super().__init__(parent)
        self.data_source_manager = data_source_manager
        self.data_queue = data_queue
        self.stop_event = stop_event
        self.log_print = log_print
        self.recv_ok_count = 0
        self.drop_count = 0
    
    def run(self):
        """运行线程"""
        self.log_print("[DataReceiveThread] 启动数据接收线程")
        
        # 缓存数据源引用，减少属性访问
        data_source_manager = self.data_source_manager
        data_queue = self.data_queue
        stop_event = self.stop_event
        log_print = self.log_print
        
        while not stop_event.is_set():
            try:
                # 数据源断开时退出线程，避免空转
                source = data_source_manager.current_source
                if source is None or not source.is_connected:
                    self.disconnect_signal.emit()
                    break

                # 读取统一帧数据（canonical API）
                frame = data_source_manager.read_frame()
                
                if frame is not None:
                    # 将数据放入队列
                    data_queue.put(frame, block=False)
                    self.recv_ok_count += 1
                    # 文件回放源在本地磁盘读取速度可能远高于UI消费速度，
                    # 轻微限流避免队列抖动丢帧导致波形“长直线跨点”。
                    if getattr(source, 'port', None) == 'FILE':
                        time.sleep(0.0005)
                else:
                    # 无数据时短暂休眠，降低CPU占用并减少对UI线程抢占
                    time.sleep(0.0002)
            except queue.Full:
                # 队列已满时丢弃最旧数据，优先保留最新数据，降低显示延迟
                self.drop_count += 1
                try:
                    data_queue.get_nowait()
                except queue.Empty:
                    pass
                try:
                    data_queue.put_nowait(frame)
                except queue.Full:
                    pass
            except AttributeError as e:
                # 数据源已断开
                log_print(f"[DataReceiveThread] 数据源访问失败: {e}")
                self.disconnect_signal.emit()
                break
            except Exception as e:
                # 其他异常，继续运行
                pass  # 静默处理，避免日志输出影响性能
        
        log_print("[DataReceiveThread] 停止数据接收线程")

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

    def log_print(self, *args, **kwargs) -> None:
        """统一日志输出，委托给主窗口"""
        context = self.state_machine.context
        if hasattr(context, 'log_print'):
            context.log_print(*args, **kwargs)
        else:
            print(*args, **kwargs)


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
        self.log_print(f"[状态] 进入未连接状态")
    
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
        self.log_print(f"[状态] 进入等待数据状态")
    
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
        self.log_print(f"[状态] 进入接收数据状态")
    
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
        self.log_print(f"[状态] 进入数据格式不匹配状态，次数: {self.mismatch_count}")
    
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
            self.log_print(f"[状态] 更新数据格式不匹配次数: {self.mismatch_count}")
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
        self.log_print(f"[状态] 进入数据停止状态")
    
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
        self.log_print(f"[状态] 进入暂停状态")
    
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
        self.transition_matrix = self._build_transition_matrix()
        self.debug_print("[FSM] 已加载状态-事件矩阵")
        for line in self.get_transition_matrix_readable():
            self.debug_print(f"[FSM] {line}")
        # 初始状态为未连接
        self.transition_to(DisconnectedState(self))

    def _build_transition_matrix(self):
        """显式状态-事件矩阵，统一管理状态跳转。"""
        return {
            DisconnectedState: {
                'connect': ConnectedWaitingState,
            },
            ConnectedWaitingState: {
                'data_received': ConnectedReceivingState,
                'format_error': DataFormatMismatchState,
                'disconnect': DisconnectedState,
                'timeout': DataStoppedState,
            },
            ConnectedReceivingState: {
                'data_received': ConnectedReceivingState,
                'timeout': DataStoppedState,
                'format_error': DataFormatMismatchState,
                'pause': PausedState,
                'disconnect': DisconnectedState,
            },
            DataFormatMismatchState: {
                'data_received': ConnectedReceivingState,
                'timeout': ConnectedWaitingState,
                'format_error': DataFormatMismatchState,
                'disconnect': DisconnectedState,
            },
            DataStoppedState: {
                'data_received': ConnectedReceivingState,
                'format_error': DataFormatMismatchState,
                'disconnect': DisconnectedState,
            },
            PausedState: {
                'resume': ConnectedReceivingState,
                'disconnect': DisconnectedState,
                'format_error': DataFormatMismatchState,
            },
        }

    def get_transition_matrix_readable(self):
        """返回可读的状态-事件矩阵行，便于日志和排查。"""
        lines = []
        for state_cls, event_map in self.transition_matrix.items():
            for event, target_cls in event_map.items():
                lines.append(f"{state_cls.__name__} --({event})-> {target_cls.__name__}")
        return lines

    def debug_print(self, message: str) -> None:
        """FSM专用调试输出（不受普通log开关影响）。"""
        if hasattr(self.context, 'fsm_debug_print'):
            self.context.fsm_debug_print(message)
        else:
            print(message)
    
    def transition_to(self, new_state: State, event: str = 'manual', **kwargs) -> None:
        """转换到新状态
        
        Args:
            new_state: 新状态
        """
        old_name = self.current_state.__class__.__name__ if self.current_state else 'None'
        new_name = new_state.__class__.__name__
        self.debug_print(f"[FSM][TRANSITION] {old_name} --({event})-> {new_name} | kwargs={kwargs}")

        if self.current_state:
            self.log_print(f"[状态机] 退出状态: {self.current_state.__class__.__name__}")
            self.current_state.exit()
        
        self.log_print(f"[状态机] 进入状态: {new_state.__class__.__name__}")
        self.current_state = new_state
        self.current_state.enter()
        if hasattr(self.context, '_debug_ui_state_snapshot'):
            self.context._debug_ui_state_snapshot("after_transition", event=event)

    def _handle_self_transition(self, event: str, **kwargs) -> None:
        """处理同状态内事件（如格式错误次数累加）。"""
        if isinstance(self.current_state, DataFormatMismatchState) and event == 'format_error':
            self.current_state.mismatch_count = kwargs.get('mismatch_count', self.current_state.mismatch_count + 1)
            context = self.context
            context.data_status_label.setText(f"数据状态: 数据格式不匹配 ({self.current_state.mismatch_count}次)")
            self.debug_print(
                f"[FSM][SELF] DataFormatMismatchState format_error mismatch_count={self.current_state.mismatch_count}"
            )
            if hasattr(context, '_debug_ui_state_snapshot'):
                context._debug_ui_state_snapshot("after_self_transition", event=event)
            return

        self.debug_print(f"[FSM][SELF] 忽略同状态事件: state={self.current_state.__class__.__name__}, event={event}")
    
    def handle_event(self, event: str, **kwargs) -> None:
        """处理事件
        
        Args:
            event: 事件名称
            **kwargs: 事件参数
        """
        if not self.current_state:
            return

        state_cls = self.current_state.__class__
        current_name = state_cls.__name__
        self.debug_print(f"[FSM][EVENT] state={current_name}, event={event}, kwargs={kwargs}")

        event_map = self.transition_matrix.get(state_cls, {})
        target_cls = event_map.get(event)

        if target_cls is None:
            self.debug_print(f"[FSM][DROP] 未定义转换: state={current_name}, event={event}")
            return

        if target_cls == state_cls:
            self._handle_self_transition(event, **kwargs)
            return

        self.transition_to(target_cls(self), event=event, **kwargs)

    def log_print(self, *args, **kwargs) -> None:
        """统一日志输出，委托给主窗口"""
        if hasattr(self.context, 'log_print'):
            self.context.log_print(*args, **kwargs)
        else:
            print(*args, **kwargs)
    
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
        self.log_print(f"[状态转换] 当前状态: {self.current_state}, 新状态: {new_state}")
        if new_state == self.current_state:
            # 状态相同，只更新动态内容
            self._update_dynamic_content(new_state, **kwargs)
            return
        
        # 状态不同，执行完整的状态转换
        self.current_state = new_state
        config = self.state_config[new_state]
        
        self.log_print(f"[状态转换] 执行状态转换: {new_state}")
        
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
        # 提前初始化日志开关，确保init_ui阶段可安全调用log_print
        self.log_enabled = False  # 默认关闭日志
        self.fsm_debug_enabled = True  # FSM/UI调试日志默认开启，便于定位状态切换问题
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
            QMainWindow.AnimatedDocks |
            QMainWindow.GroupedDragging
        )

        # 主面板
        control_panel = self.create_control_panel()
        self.waveform_widget = WaveformWidget()
        raw_data_panel = self.create_raw_data_panel()

        self.control_dock = self._create_panel_dock("控制面板", "dock_control", control_panel, Qt.LeftDockWidgetArea)
        self.waveform_dock = self._create_panel_dock("波形区", "dock_waveform", self.waveform_widget, Qt.LeftDockWidgetArea)
        self.raw_data_dock = self._create_panel_dock("原始数据与发送", "dock_raw_data", raw_data_panel, Qt.LeftDockWidgetArea)

        # 默认布局：左控制，右上波形，右下原始数据/发送（覆盖整个工作区，避免中央空白区）
        self.splitDockWidget(self.control_dock, self.waveform_dock, Qt.Horizontal)
        self.splitDockWidget(self.waveform_dock, self.raw_data_dock, Qt.Vertical)
        self.resizeDocks([self.control_dock, self.waveform_dock], [380, 980], Qt.Horizontal)
        self.resizeDocks([self.waveform_dock, self.raw_data_dock], [560, 240], Qt.Vertical)

        # 工具栏：锁定尺寸 + 一键复原
        self._init_layout_toolbar()
        self._install_layer_switching()
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
    padding: 6px 12px;
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
""")

        # 保存默认布局，供一键复原
        self._default_geometry = self.saveGeometry()
        self._default_dock_state = self.saveState()

    def _create_panel_dock(self, title: str, object_name: str, widget: QWidget, area) -> QDockWidget:
        """创建可拖拽/可分离的Dock面板。"""
        dock = QDockWidget(title, self)
        dock.setObjectName(object_name)
        dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        dock.setWidget(widget)
        self.addDockWidget(area, dock)
        return dock

    def _init_layout_toolbar(self):
        """布局控制工具栏：锁定尺寸、复原布局。"""
        self.layout_toolbar = QToolBar("布局工具栏", self)
        self.layout_toolbar.setObjectName("layoutToolbar")
        self.layout_toolbar.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, self.layout_toolbar)

        self.lock_layout_action = QAction("锁定布局", self)
        self.lock_layout_action.setCheckable(True)
        self.lock_layout_action.toggled.connect(self._set_layout_locked)
        self.layout_toolbar.addAction(self.lock_layout_action)

        restore_layout_action = QAction("一键复原布局", self)
        restore_layout_action.triggered.connect(self._restore_default_layout)
        self.layout_toolbar.addAction(restore_layout_action)

        self.layout_toolbar.addSeparator()


    def _install_layer_switching(self):
        """安装图层切换行为：点击任意面板即置顶。"""
        docks = [self.control_dock, self.waveform_dock, self.raw_data_dock]
        for dock in docks:
            dock.installEventFilter(self)
            if dock.widget() is not None:
                dock.widget().installEventFilter(self)

    def _bring_main_window_front(self):
        """将主窗口置顶。"""
        self.raise_()
        self.activateWindow()

    def _bring_layer_to_front(self, dock: QDockWidget):
        """将指定Dock层置顶。"""
        if dock is None:
            return

        if not dock.isVisible():
            dock.show()

        if dock.isFloating():
            dock.raise_()
            dock.activateWindow()
            return

        # 在停靠模式下，抬升当前Dock并聚焦，确保用户感知到“切到最上层”
        dock.raise_()
        dock.setFocus(Qt.OtherFocusReason)

    def eventFilter(self, obj, event):
        """点击任意页面时自动切换到最上层。"""
        if event.type() in (QEvent.MouseButtonPress, QEvent.FocusIn):
            mapping = (
                (self.control_dock, self.control_dock.widget()),
                (self.waveform_dock, self.waveform_dock.widget()),
                (self.raw_data_dock, self.raw_data_dock.widget()),
            )
            for dock, widget in mapping:
                if obj is dock or obj is widget:
                    self._bring_layer_to_front(dock)
                    break

        return super().eventFilter(obj, event)

    def _set_layout_locked(self, locked: bool):
        """锁定/解锁布局：锁定后固定当前面板尺寸并禁止拖动分离。"""
        self._layout_locked = locked
        docks = [self.control_dock, self.waveform_dock, self.raw_data_dock]
        for dock in docks:
            if locked:
                if dock.isFloating():
                    size = dock.size()
                    dock.setMinimumSize(size)
                    dock.setMaximumSize(size)
                else:
                    area = self.dockWidgetArea(dock)
                    if area in (Qt.LeftDockWidgetArea, Qt.RightDockWidgetArea):
                        width = max(200, dock.width())
                        dock.setMinimumWidth(width)
                        dock.setMaximumWidth(width)
                    elif area in (Qt.TopDockWidgetArea, Qt.BottomDockWidgetArea):
                        height = max(120, dock.height())
                        dock.setMinimumHeight(height)
                        dock.setMaximumHeight(height)

                dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
            else:
                dock.setMinimumSize(QSize(0, 0))
                dock.setMaximumSize(QSize(16777215, 16777215))
                dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)

    def _restore_default_layout(self):
        """一键恢复初始布局与尺寸。"""
        if getattr(self, '_layout_locked', False):
            self.lock_layout_action.setChecked(False)

        self.restoreGeometry(self._default_geometry)
        self.restoreState(self._default_dock_state)
        self.resizeDocks([self.control_dock, self.waveform_dock], [380, 980], Qt.Horizontal)
        self.resizeDocks([self.waveform_dock, self.raw_data_dock], [560, 240], Qt.Vertical)
    
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
        
        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.data_count_label)
        status_layout.addWidget(self.perf_label)
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

        self.raw_data_enable_checkbox = QCheckBox("启用原始数据显示（会降低性能）")
        self.raw_data_enable_checkbox.setChecked(False)
        
        format_layout.addWidget(encoding_label)
        format_layout.addWidget(self.encoding_combo)
        format_layout.addWidget(display_label)
        format_layout.addWidget(self.display_format_combo)
        raw_data_layout.addLayout(format_layout)
        raw_data_layout.addWidget(self.raw_data_enable_checkbox)
        
        # 原始数据显示区域
        self.raw_data_text = QTextEdit()
        self.raw_data_text.setReadOnly(True)
        self.raw_data_text.setStyleSheet("font-family: Consolas, monospace; font-size: 10pt;")
        
        # 发送区域（与原始数据区放在一起，风格参考串口助手）
        send_group = QGroupBox("发送区")
        send_layout = QVBoxLayout()

        self.send_edit = QTextEdit()
        self.send_edit.setPlaceholderText("输入发送内容（Enter换行，Ctrl+Enter发送）")
        self.send_edit.setMinimumHeight(90)

        send_button_row = QHBoxLayout()
        self.send_btn = QPushButton("发送")
        self.send_btn.clicked.connect(self.send_current_data)
        self.send_btn.setEnabled(False)
        send_button_row.addWidget(self.send_btn)
        send_button_row.addStretch()

        self.send_result_label = QLabel("发送状态: 未发送")
        self.send_result_label.setStyleSheet("color: #666;")

        send_layout.addWidget(self.send_edit)
        send_layout.addLayout(send_button_row)
        send_layout.addWidget(self.send_result_label)
        send_group.setLayout(send_layout)

        # 使用分割器让“接收区/发送区”都可拖拽调节高度
        io_splitter = QSplitter(Qt.Vertical)
        io_splitter.addWidget(self.raw_data_text)
        io_splitter.addWidget(send_group)
        io_splitter.setStretchFactor(0, 7)
        io_splitter.setStretchFactor(1, 3)
        io_splitter.setChildrenCollapsible(False)
        io_splitter.setHandleWidth(5)

        raw_data_layout.addWidget(io_splitter)
        
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

    def _sync_receiving_indicator(self):
        """兜底同步：接收状态必须保持蓝色闪烁。"""
        if not isinstance(self.state_machine.current_state, ConnectedReceivingState):
            return

        if not getattr(self.connect_btn, '_is_flashing', False):
            self.connect_btn.set_color(QColor(100, 149, 237))
            self.connect_btn.start_flashing(100)
            self.fsm_debug_print("[UI_DEBUG][sync] receiving_state_detected_but_not_flashing -> force_start_flashing")
    
    def toggle_connection(self):
        """切换连接/断开状态"""
        if self.data_source_manager.is_connected():
            self._disconnect_flow()
        else:
            self._connect_flow()

    def _disconnect_flow(self):
        """连接编排层：统一处理断开流程（不改业务语义）"""
        self._debug_ui_state_snapshot("before_disconnect_flow", event="disconnect")
        self._snapshot_justfloat_channel_names_before_disconnect()
        # 断开时重置暂停状态，避免下次连接仍停在暂停显示
        self.waveform_widget.is_paused = False
        self.pause_btn.setText("暂停")
        # 先停止数据接收线程，避免访问已断开的数据源
        self.stop_receive_thread()
        # 再断开数据源连接
        self.data_source_manager.disconnect()
        self.status_label.setText("未连接")
        self.status_label.setStyleSheet("color: red;")
        self.pause_btn.setEnabled(False)
        self.send_btn.setEnabled(False)
        self.send_result_label.setText("发送状态: 未发送")
        # 断开后恢复配置编辑
        self._set_connection_config_enabled(True)
        self.data_count = 0
        self.data_count_label.setText("接收数据: 0")
        self.perf_label.setText("速率: 接收 0/s | 处理 0/s | 队列 0 | 丢包 0 | 字节 0 B/s | 解析 0 us/帧")
        self.save_file_label.setText("保存文件: 无")
        self.channels_label.setText("自动检测通道...")
        self.last_channels_text = "自动检测通道..."
        self.save_btn.setText("开始保存")
        self.auto_save_enabled = False
        self.clear_raw_data()  # 清空原始数据接收区

        # 转换到未连接状态
        self.state_machine.handle_event('disconnect')
        # 重置last_data_time，避免check_data_timeout继续检测超时
        self.last_data_time = None
        self.log_print("数据源已断开")
        self._debug_ui_state_snapshot("after_disconnect_flow", event="disconnect")

    def _snapshot_justfloat_channel_names_before_disconnect(self):
        """断开前保存justfloat通道显示名，用于下次重连恢复。"""
        source = self.data_source_manager.get_current_source()
        if source is None or not hasattr(source, 'get_protocol'):
            return

        if source.get_protocol() != 'justfloat':
            return

        current_count = len(self.waveform_widget.channels)
        if current_count <= 0:
            self.last_justfloat_channel_names = []
            return

        saved_names = []
        for i in range(1, current_count + 1):
            default_name = f'channel{i}'
            saved_names.append(self.data_source_manager.get_display_channel_name(default_name))

        self.last_justfloat_channel_names = saved_names
        self.fsm_debug_print(
            f"[UI_DEBUG][justfloat_snapshot] count={current_count} names={self.last_justfloat_channel_names}"
        )

    def _restore_justfloat_channel_names_after_connect(self):
        """justfloat重连后恢复上次通道显示名映射。

        规则：
        - 只恢复已有快照中的前N个通道（N由新连接数据决定）。
        - 新增通道使用默认名（channel{n}）。
        - 若新连接通道变少，多余历史名称自然不会生效。
        """
        if not self.last_justfloat_channel_names:
            return

        used_names = set()
        restored = []

        for index, saved_name in enumerate(self.last_justfloat_channel_names, start=1):
            default_name = f'channel{index}'
            if not saved_name or saved_name == default_name:
                continue

            # 避免异常情况下的重名恢复
            if saved_name in used_names:
                continue

            self.data_source_manager.set_channel_name_mapping(default_name, saved_name)
            used_names.add(saved_name)
            restored.append((default_name, saved_name))

        if restored:
            self.fsm_debug_print(f"[UI_DEBUG][justfloat_restore] mappings={restored}")

    def _build_data_source_from_ui(self, source_type: str, header: str):
        """应用编排层：根据UI配置创建数据源并返回连接日志。"""
        if source_type == "UDP":
            host = self.host_edit.text()
            port = int(self.port_edit.text())
            data_source = create_udp_source(host, port)
            send_host = self.udp_send_host_edit.text().strip() or "127.0.0.1"
            send_port = int(self.udp_send_port_edit.text())
            data_source.set_send_target(send_host, send_port)
            return data_source, f"已连接到UDP {host}:{port}，数据校验头: {header}", None

        if source_type == "TCP":
            mode_text = self.tcp_mode_combo.currentText()
            local_host = self.tcp_host_edit.text()
            local_port = int(self.tcp_port_edit.text())
            target_host = self.tcp_target_host_edit.text().strip() or "127.0.0.1"
            target_port = int(self.tcp_target_port_edit.text())

            if mode_text == "主动连接":
                data_source = create_tcp_source(
                    host=local_host,
                    port=local_port,
                    mode='client',
                    peer_host=target_host,
                    peer_port=target_port,
                )
                return data_source, f"已连接TCP服务端 {target_host}:{target_port}，协议: UDP同格式", None

            data_source = create_tcp_source(host=local_host, port=local_port, mode='server')
            return data_source, f"已监听TCP {local_host}:{local_port}，协议: UDP同格式", None

        if source_type == "串口":
            serial_port = self.serial_port_combo.currentData()  # 获取实际的串口号（如COM1）
            if not serial_port:
                QMessageBox.warning(self, "错误", "请选择有效的端口")
                return None, None, None

            baudrate = int(self.baudrate_combo.currentText())
            protocol_text = self.protocol_combo.currentText()
            source_label = "串口"
            source_factory = create_serial_source

            if protocol_text == '文本协议':
                protocol = 'text'
                serial_header = header
                data_source = source_factory(serial_port, baudrate, protocol, serial_header)
                return data_source, f"已连接到{source_label} {serial_port} @ {baudrate}bps，协议: {protocol_text}，数据校验头: {serial_header}", None

            if protocol_text == 'Justfloat':
                protocol = 'justfloat'
                serial_header = ''
                justfloat_mode_text = self.justfloat_mode_combo.currentText()
                justfloat_mode = 'with_timestamp' if justfloat_mode_text == '带时间戳' else 'without_timestamp'
                delta_t = float(self.delta_t_edit.text()) if self.delta_t_edit.text() else 1.0
                data_source = source_factory(serial_port, baudrate, protocol, serial_header, justfloat_mode, delta_t)
                return data_source, f"已连接到{source_label} {serial_port} @ {baudrate}bps，协议: {protocol_text}", justfloat_mode

            protocol = 'rawdata'
            serial_header = ''
            data_source = source_factory(serial_port, baudrate, protocol, serial_header)
            return data_source, f"已连接到{source_label} {serial_port} @ {baudrate}bps，协议: {protocol_text}", None

        # 文件数据源
        file_path = self.file_path_edit.text().strip()
        if not file_path or not os.path.isfile(file_path):
            QMessageBox.warning(self, "错误", "请选择有效的 .log/.bin/.csv 文件")
            return None, None, None

        ext = os.path.splitext(file_path)[1].lower()
        if ext not in ('.log', '.bin', '.csv'):
            QMessageBox.warning(self, "错误", "仅支持 .log/.bin/.csv 文件")
            return None, None, None

        protocol_text = self.file_protocol_combo.currentText()
        if protocol_text == '文本协议':
            protocol = 'text'
            file_header = header
            data_source = create_file_source(file_path, protocol, file_header)
            return data_source, f"已连接到文件 {file_path}，协议: {protocol_text}，数据校验头: {file_header}", None

        if protocol_text == 'CSV':
            if ext != '.csv':
                QMessageBox.warning(self, "错误", "CSV协议仅支持 .csv 文件")
                return None, None, None
            data_source = create_file_source(file_path, 'csv', '')
            return data_source, f"已连接到文件 {file_path}，协议: {protocol_text}（需与导出CSV表头一致）", None

        if protocol_text == 'Justfloat':
            protocol = 'justfloat'
            justfloat_mode_text = self.justfloat_mode_combo.currentText()
            justfloat_mode = 'with_timestamp' if justfloat_mode_text == '带时间戳' else 'without_timestamp'
            delta_t = float(self.delta_t_edit.text()) if self.delta_t_edit.text() else 1.0
            data_source = create_file_source(file_path, protocol, '', justfloat_mode, delta_t)
            return data_source, f"已连接到文件 {file_path}，协议: {protocol_text}", justfloat_mode

        data_source = create_file_source(file_path, 'rawdata', '')
        return data_source, f"已连接到文件 {file_path}，协议: {protocol_text}", None

    def _connect_flow(self):
        """连接编排层：统一处理连接流程（不改业务语义）"""
        try:
            source_type = self.source_type_combo.currentText()
            header = self.header_edit.text().strip() or 'DATA'

            # 设置数据校验头
            self.data_source_manager.set_data_header(header)

            data_source, success_log, justfloat_mode = self._build_data_source_from_ui(source_type, header)
            if data_source is None:
                return

            # 设置原始数据回调函数
            data_source.set_raw_data_callback(self.on_raw_data_received)
            # 设置断开回调函数
            data_source.set_disconnect_callback(self.disconnect_callback)
            success = self.data_source_manager.set_source(data_source)

            # 如果是Justfloat无时间戳模式，重置数据点计数器
            if success and justfloat_mode == 'without_timestamp':
                data_source.reset_data_point_counter()

            # justfloat重连后恢复历史通道名映射
            if success and hasattr(data_source, 'get_protocol') and data_source.get_protocol() == 'justfloat':
                self._restore_justfloat_channel_names_after_connect()

            if success:
                self.log_print(success_log)
                self.status_label.setText("已连接")
                self.status_label.setStyleSheet("color: green;")
                # 每次连接都恢复为“继续接收显示”状态
                self.waveform_widget.is_paused = False
                self.pause_btn.setText("暂停")
                self.pause_btn.setEnabled(True)
                self.send_btn.setEnabled(source_type in ("UDP", "TCP", "串口"))
                # 连接后锁定配置，防止运行中误改
                self._set_connection_config_enabled(False)
                # 启动数据接收线程
                self.start_receive_thread()

                # 清空旧通道
                self.waveform_widget.clear_all()
                self.channels_label.setText("自动检测通道...")
                self.last_channels_text = "自动检测通道..."

                # 重置校验头不匹配计数器
                self.data_source_manager.reset_header_mismatch_count()

                # 转换到已连接-等待数据状态
                self.state_machine.handle_event('connect')

                # 默认不自动保存，避免磁盘IO影响实时接收性能
                self.save_btn.setText("开始保存")
                self.save_file_label.setText("保存文件: 无")
                self.auto_save_enabled = False
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
            self.tcp_group.setVisible(False)
            self.serial_group.setVisible(False)
            self.file_group.setVisible(False)
            # UDP模式：启用数据校验头配置
            self.header_group.setEnabled(True)
            self.justfloat_group.setVisible(False)
            self.header_group.setVisible(True)
            return

        if source_type == "TCP":
            self.udp_group.setVisible(False)
            self.tcp_group.setVisible(True)
            self.serial_group.setVisible(False)
            self.file_group.setVisible(False)
            self.header_group.setEnabled(True)
            self.justfloat_group.setVisible(False)
            self.header_group.setVisible(True)
            self.on_tcp_mode_changed(self.tcp_mode_combo.currentText())
            return

        if source_type == "串口":
            self.udp_group.setVisible(False)
            self.tcp_group.setVisible(False)
            self.serial_group.setVisible(True)
            self.file_group.setVisible(False)
            self.serial_group.setTitle("串口配置")
            # 根据协议类型控制数据校验头配置的启用/禁用
            self.on_protocol_changed(self.protocol_combo.currentText())
            return

        # 文件
        self.udp_group.setVisible(False)
        self.tcp_group.setVisible(False)
        self.serial_group.setVisible(False)
        self.file_group.setVisible(True)
        self.on_file_protocol_changed(self.file_protocol_combo.currentText())

    def _apply_protocol_ui(self, protocol_text: str):
        """统一处理协议相关UI显隐，供串口/文件复用。"""
        if protocol_text == "文本协议":
            self.header_group.setVisible(True)
            self.justfloat_group.setVisible(False)
        elif protocol_text == "Justfloat":
            self.header_group.setVisible(False)
            self.justfloat_group.setVisible(True)
            self.on_justfloat_mode_changed(self.justfloat_mode_combo.currentText())
        else:  # Rawdata
            self.header_group.setVisible(False)
            self.justfloat_group.setVisible(False)
    
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
                self.log_print(f"扫描到 {len(ports)} 个串口")
            else:
                # 没有找到串口
                self.serial_port_combo.addItem("无可用串口", "")
                self.log_print("未扫描到可用串口")
        except ImportError:
            # pyserial未安装
            self.serial_port_combo.clear()
            self.serial_port_combo.addItem("请安装pyserial库", "")
            self.log_print("错误: 未安装pyserial库，请运行: pip install pyserial")
        except Exception as e:
            # 扫描失败
            self.serial_port_combo.clear()
            self.serial_port_combo.addItem("扫描失败", "")
            self.log_print(f"扫描串口失败: {e}")
    
    def refresh_serial_ports_and_show_popup(self):
        """刷新串口列表并显示下拉框"""
        self.refresh_serial_ports()
        QComboBox.showPopup(self.serial_port_combo)
    
    def on_protocol_changed(self, protocol_text: str):
        """串口协议改变事件处理
        
        Args:
            protocol_text: 协议文本（文本协议、Justfloat、Rawdata）
        """
        self._apply_protocol_ui(protocol_text)

    def on_file_protocol_changed(self, protocol_text: str):
        """文件协议改变事件处理。"""
        self._apply_protocol_ui(protocol_text)

    def on_tcp_mode_changed(self, mode_text: str):
        """TCP模式切换：监听/主动连接。"""
        is_client = (mode_text == "主动连接")

        self.tcp_host_edit.setEnabled(not is_client)
        self.tcp_port_edit.setEnabled(not is_client)
        self.tcp_target_host_edit.setEnabled(is_client)
        self.tcp_target_port_edit.setEnabled(is_client)

    def browse_input_file(self):
        """浏览输入数据文件（.log/.bin/.csv）。"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择数据文件",
            self.file_path_edit.text() or os.getcwd(),
            "数据文件 (*.log *.bin *.csv);;所有文件 (*)",
        )
        if file_path:
            self.file_path_edit.setText(file_path)

    def _set_connection_config_enabled(self, enabled: bool):
        """统一控制连接相关配置项是否可编辑。"""
        self.source_type_combo.setEnabled(enabled)
        self.udp_group.setEnabled(enabled)
        self.tcp_group.setEnabled(enabled)
        self.serial_group.setEnabled(enabled)
        self.file_group.setEnabled(enabled)
        self.header_group.setEnabled(enabled)
        self.justfloat_group.setEnabled(enabled)

    def send_current_data(self):
        """通过当前数据源发送文本数据。"""
        if not self.data_source_manager.is_connected():
            self.send_result_label.setText("发送状态: 失败（未连接）")
            self.send_result_label.setStyleSheet("color: red;")
            return

        text = self.send_edit.toPlainText()
        if not text:
            return

        source_type = self.source_type_combo.currentText()
        protocol_text = None
        if source_type == "串口":
            protocol_text = self.protocol_combo.currentText()
        elif source_type == "文件":
            protocol_text = self.file_protocol_combo.currentText()
        else:
            protocol_text = "文本协议"

        payload = text
        if protocol_text == "文本协议" and not payload.endswith("\n"):
            payload += "\n"

        success = self.data_source_manager.send_data(payload.encode('utf-8'))
        if success:
            self.send_result_label.setText("发送状态: 成功")
            self.send_result_label.setStyleSheet("color: green;")
            self.log_print(f"[发送] {source_type} 发送成功: {text}")
            self._append_tx_to_raw_data_view(text)
        else:
            self.send_result_label.setText("发送状态: 失败（当前源不支持或目标不可达）")
            self.send_result_label.setStyleSheet("color: red;")
            self.log_print(f"[发送] {source_type} 发送失败: {text}")

    def _append_tx_to_raw_data_view(self, text: str):
        """在原始数据区追加发送内容，带TX标识。"""
        timestamp = QDateTime.currentDateTime().toString("HH:mm:ss.zzz")
        lines = text.splitlines() or [""]
        tx_text = "\n".join([f"[TX][{timestamp}] {line}" for line in lines])
        self.raw_data_text.append(tx_text)
        self._trim_raw_data_text_lines()

    def _trim_raw_data_text_lines(self):
        """限制原始数据区最大行数，避免内存占用持续增长。"""
        max_lines = 1000
        document = self.raw_data_text.document()
        if document.blockCount() <= max_lines:
            return

        cursor = self.raw_data_text.textCursor()
        cursor.movePosition(cursor.Start)
        cursor.movePosition(cursor.Down, cursor.KeepAnchor, document.blockCount() - max_lines)
        cursor.removeSelectedText()

        scrollbar = self.raw_data_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
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
        self.last_perf_proc_count = 0
    
    def on_raw_data_received(self, data: bytes):
        """原始数据接收回调
        
        Args:
            data: 原始字节数据
        """
        # 暂停时不刷新原始数据栏
        if self.waveform_widget.is_paused or not self.raw_data_enabled:
            return

        # 仅入队，解码和文本拼接在主线程定时器中批量处理
        try:
            self.raw_data_queue.put_nowait(data)
        except queue.Full:
            pass
    
    def flush_raw_data_buffer(self):
        """刷新原始数据缓冲区到UI"""
        try:
            # 每次限量处理，避免原始数据显示占用过多主线程
            max_packets_per_flush = 200
            packets = []
            while len(packets) < max_packets_per_flush:
                try:
                    packets.append(self.raw_data_queue.get_nowait())
                except queue.Empty:
                    break

            if not packets and not self.raw_data_buffer:
                return

            encoding = self.raw_data_encoding
            display_format = self.raw_data_display_format

            for data in packets:
                if display_format == "文本":
                    try:
                        self.raw_data_buffer.append(data.decode(encoding))
                    except UnicodeDecodeError:
                        if self._is_binary_data(data):
                            self.raw_data_buffer.append("[二进制数据 - 请切换到十六进制格式查看]\n")
                        else:
                            self.raw_data_buffer.append(f"[解码失败: {data.hex()}]\n")
                else:
                    self.raw_data_buffer.append(f"{data.hex(' ').upper()}\n")

            if not self.raw_data_buffer:
                return

            # 将缓冲区中的所有文本一次性添加到UI
            all_text = ''.join(self.raw_data_buffer)
            self.raw_data_buffer.clear()
            self.raw_data_text.append(all_text)
            
            # 限制行数并滚动到底部
            self._trim_raw_data_text_lines()
        except Exception as e:
            self.log_print(f"刷新原始数据缓冲区失败: {e}")
    
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
        self.raw_data_buffer.clear()
        while not self.raw_data_queue.empty():
            try:
                self.raw_data_queue.get_nowait()
            except queue.Empty:
                break
    
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
    
    def show_channel_context_menu(self, position):
        """显示通道右键菜单
        
        Args:
            position: 鼠标位置
        """
        channels = self.waveform_widget.get_all_channels()
        
        self.log_print(f"[show_channel_context_menu] 当前通道: {channels}")
        
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
            self.log_print(f"[show_channel_context_menu] 当前协议: {protocol}, is_justfloat: {is_justfloat}")
        else:
            self.log_print(f"[show_channel_context_menu] 当前数据源不支持get_protocol方法")
        
        # 只有Justfloat协议才显示重命名通道菜单
        if is_justfloat:
            self.log_print(f"[show_channel_context_menu] 显示重命名通道菜单")
            rename_menu = menu.addMenu("重命名通道")
            for channel_name in channels:
                action = QAction(channel_name, self)
                action.triggered.connect(lambda checked, name=channel_name: self.rename_channel(name))
                rename_menu.addAction(action)
        else:
            self.log_print(f"[show_channel_context_menu] 不显示重命名通道菜单（非Justfloat协议）")
        
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
            self.log_print(f"通道 '{channel_name}' 颜色已更新为: {color.name()} ({rgb})")
        else:
            self.log_print(f"通道 '{channel_name}' 颜色设置已取消")
    
    def rename_channel(self, old_name: str):
        """重命名通道
        
        Args:
            old_name: 原通道名称
        """
        self.log_print(f"[rename_channel] 开始重命名通道: {old_name}")
        self.log_print(f"[rename_channel] waveform_widget.channels: {list(self.waveform_widget.channels.keys())}")
        self.log_print(f"[rename_channel] data_source_manager.channels: {self.data_source_manager.channels}")
        self.log_print(f"[rename_channel] data_source_manager.channel_name_mapping: {self.data_source_manager.get_channel_name_mapping()}")
        self._debug_channel_state("rename_start")
        
        if old_name not in self.waveform_widget.channels:
            QMessageBox.warning(self, "错误", f"通道 '{old_name}' 不存在")
            return
        
        # 弹出输入对话框
        new_name, ok = QInputDialog.getText(self, "重命名通道", f"请输入通道 '{old_name}' 的新名称:")
        
        if ok and new_name:
            new_name = new_name.strip()

            # 检查新名称是否为空
            if not new_name:
                QMessageBox.warning(self, "错误", "通道名称不能为空")
                return

            if new_name in self.waveform_widget.channels:
                QMessageBox.warning(self, "错误", f"通道 '{new_name}' 已存在")
                return
            
            self.log_print(f"[rename_channel] 用户输入新名称: {new_name}")
            
            # 更新waveform_widget中的通道名
            self.waveform_widget.rename_channel(old_name, new_name)
            self.log_print(f"[rename_channel] waveform_widget.rename_channel 完成")
            self._debug_channel_state("rename_after_waveform")
            
            # 更新data_source_manager中的通道名映射
            self.data_source_manager.set_channel_name_mapping(old_name, new_name)
            self.log_print(f"[rename_channel] data_source_manager.set_channel_name_mapping 完成")
            self._debug_channel_state("rename_after_manager")
            
            # 更新通道显示
            channels_text = ", ".join(self.data_source_manager.get_channels())
            self.channels_label.setText(f"检测到通道: {channels_text}")
            
            self.log_print(f"[rename_channel] 通道 '{old_name}' 已重命名为 '{new_name}'")
            self.log_print(f"[rename_channel] 最终状态:")
            self.log_print(f"[rename_channel]   waveform_widget.channels: {list(self.waveform_widget.channels.keys())}")
            self.log_print(f"[rename_channel]   data_source_manager.channels: {self.data_source_manager.channels}")
            self.log_print(f"[rename_channel]   data_source_manager.channel_name_mapping: {self.data_source_manager.get_channel_name_mapping()}")
        else:
            self.log_print(f"[rename_channel] 通道 '{old_name}' 重命名已取消")
    

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