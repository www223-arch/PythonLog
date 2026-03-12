"""
波形显示组件

提供实时波形显示功能，支持多通道、缩放、鼠标吸附等交互功能。
"""

import pyqtgraph as pg
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
from typing import Dict, List, Tuple, Optional
import numpy as np


class WaveformWidget(QWidget):
    """波形显示组件
    
    提供实时波形显示功能，支持多通道数据显示。
    """
    
    def __init__(self, parent=None):
        """初始化波形显示组件
        
        Args:
            parent: 父窗口
        """
        super().__init__(parent)
        self.init_ui()
        
        # 数据存储
        self.channels: Dict[str, Dict] = {}  # 通道数据存储
        self.max_points = 1000  # 每个通道最大数据点数
        self.sample_rate = 1.0  # 采样率
        self.time_counter = 0  # 时间计数器
        
        # 状态
        self.is_paused = False
        self.auto_scale = True
        
        # 更新定时器
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_display)
        self.update_interval = 50  # 更新间隔（毫秒）
    
    def init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout()
        
        # 创建绘图组件
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground('w')  # 白色背景
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setLabel('left', '数值')
        self.plot_widget.setLabel('bottom', '时间')
        self.plot_widget.addLegend()
        
        # 设置交互
        self.plot_widget.setMouseEnabled(x=True, y=True)
        self.plot_widget.enableAutoRange(x=True, y=True)
        
        # 鼠标移动事件
        self.plot_widget.scene().sigMouseMoved.connect(self.mouse_moved)
        
        # 信息标签
        self.info_label = QLabel("就绪")
        self.info_label.setFont(QFont("Arial", 9))
        self.info_label.setStyleSheet("color: #666;")
        
        # 控制按钮
        control_layout = QVBoxLayout()
        
        self.pause_btn = QPushButton("暂停")
        self.pause_btn.clicked.connect(self.toggle_pause)
        self.pause_btn.setMaximumWidth(80)
        
        self.clear_btn = QPushButton("清空")
        self.clear_btn.clicked.connect(self.clear_all)
        self.clear_btn.setMaximumWidth(80)
        
        control_layout.addWidget(self.pause_btn)
        control_layout.addWidget(self.clear_btn)
        
        # 添加到主布局
        layout.addWidget(self.info_label)
        layout.addWidget(self.plot_widget)
        
        self.setLayout(layout)
    
    def add_channel(self, name: str, color: str = 'b', width: int = 2) -> None:
        """添加通道
        
        Args:
            name: 通道名称
            color: 曲线颜色
            width: 曲线宽度
        """
        if name in self.channels:
            print(f"通道 {name} 已存在")
            return
        
        # 创建曲线
        pen = pg.mkPen(color=color, width=width)
        curve = self.plot_widget.plot(pen=pen, name=name)
        
        # 存储通道信息
        self.channels[name] = {
            'curve': curve,
            'data': [],
            'x_data': [],
            'color': color,
            'width': width
        }
        
        print(f"通道 {name} 已添加")
    
    def remove_channel(self, name: str) -> None:
        """移除通道
        
        Args:
            name: 通道名称
        """
        if name in self.channels:
            self.plot_widget.removeItem(self.channels[name]['curve'])
            del self.channels[name]
            print(f"通道 {name} 已移除")
    
    def update_channel(self, name: str, x: float, y: float) -> None:
        """更新单个通道数据
        
        Args:
            name: 通道名称
            x: x轴数据
            y: y轴数据
        """
        if name not in self.channels:
            print(f"通道 {name} 不存在")
            return
        
        channel = self.channels[name]
        channel['data'].append(y)
        channel['x_data'].append(x)
        
        # 限制数据点数
        if len(channel['data']) > self.max_points:
            channel['data'] = channel['data'][-self.max_points:]
            channel['x_data'] = channel['x_data'][-self.max_points:]
    
    def update_channels(self, data_dict: Dict[str, float]) -> None:
        """批量更新多个通道数据
        
        Args:
            data_dict: 通道名称到数据的映射
        """
        if self.is_paused:
            return
        
        self.time_counter += 1
        current_time = self.time_counter / self.sample_rate
        
        for name, value in data_dict.items():
            if name in self.channels:
                self.update_channel(name, current_time, value)
    
    def update_display(self) -> None:
        """更新显示"""
        for name, channel in self.channels.items():
            if channel['x_data'] and channel['data']:
                channel['curve'].setData(channel['x_data'], channel['data'])
    
    def start_update(self) -> None:
        """启动定时更新"""
        self.update_timer.start(self.update_interval)
        print("波形显示已启动")
    
    def stop_update(self) -> None:
        """停止定时更新"""
        self.update_timer.stop()
        print("波形显示已停止")
    
    def toggle_pause(self) -> None:
        """切换暂停状态"""
        self.is_paused = not self.is_paused
        self.pause_btn.setText("继续" if self.is_paused else "暂停")
        print(f"波形显示已{'暂停' if self.is_paused else '继续'}")
    
    def clear_all(self) -> None:
        """清空所有数据"""
        for channel in self.channels.values():
            channel['data'].clear()
            channel['x_data'].clear()
            channel['curve'].setData([], [])
        self.time_counter = 0
        print("所有数据已清空")
    
    def clear_channel(self, name: str) -> None:
        """清空指定通道数据
        
        Args:
            name: 通道名称
        """
        if name in self.channels:
            channel = self.channels[name]
            channel['data'].clear()
            channel['x_data'].clear()
            channel['curve'].setData([], [])
    
    def mouse_moved(self, pos) -> None:
        """鼠标移动事件处理
        
        Args:
            pos: 鼠标位置
        """
        if self.is_paused:
            vb = self.plot_widget.plotItem.vb
            mouse_point = vb.mapSceneToView(pos)
            x = mouse_point.x()
            y = mouse_point.y()
            
            # 查找最近的数据点
            closest_point = self.find_closest_point(x, y)
            if closest_point:
                channel_name, point_x, point_y = closest_point
                self.info_label.setText(
                    f"通道: {channel_name} | X: {point_x:.2f} | Y: {point_y:.4f}"
                )
    
    def find_closest_point(self, x: float, y: float) -> Optional[Tuple[str, float, float]]:
        """查找最近的数据点
        
        Args:
            x: 鼠标x坐标
            y: 鼠标y坐标
        
        Returns:
            (通道名称, 点x坐标, 点y坐标) 或 None
        """
        min_distance = float('inf')
        closest_point = None
        
        for name, channel in self.channels.items():
            if not channel['x_data'] or not channel['data']:
                continue
            
            for px, py in zip(channel['x_data'], channel['data']):
                distance = ((px - x) ** 2 + (py - y) ** 2) ** 0.5
                if distance < min_distance:
                    min_distance = distance
                    closest_point = (name, px, py)
        
        return closest_point if min_distance < 10 else None
    
    def set_max_points(self, max_points: int) -> None:
        """设置最大数据点数
        
        Args:
            max_points: 最大数据点数
        """
        self.max_points = max_points
    
    def set_sample_rate(self, sample_rate: float) -> None:
        """设置采样率
        
        Args:
            sample_rate: 采样率（Hz）
        """
        self.sample_rate = sample_rate
    
    def get_channel_data(self, name: str) -> Optional[Tuple[List[float], List[float]]]:
        """获取通道数据
        
        Args:
            name: 通道名称
        
        Returns:
            (x_data, y_data) 或 None
        """
        if name in self.channels:
            channel = self.channels[name]
            return (channel['x_data'].copy(), channel['data'].copy())
        return None
    
    def get_all_channels(self) -> List[str]:
        """获取所有通道名称
        
        Returns:
            通道名称列表
        """
        return list(self.channels.keys())