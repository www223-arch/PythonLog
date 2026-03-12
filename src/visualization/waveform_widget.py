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
        
        # 标记点存储
        self.marked_points = []  # 存储标记的点 [(channel_name, x, y), ...]
        self.marked_scatter = None  # 标记点的散点图
        
        # 临时吸附点标识
        self.hover_scatter = None  # 鼠标悬停时的临时标识
        
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
        print("鼠标移动事件已连接")
        
        # 鼠标双击事件
        self.plot_widget.scene().sigMouseClicked.connect(self.mouse_clicked)
        
        # 双击防抖
        self.last_click_time = 0
        self.is_processing = False
        
        # 鼠标双击事件
        self.plot_widget.scene().sigMouseClicked.connect(self.mouse_clicked)
        
        # 信息标签
        self.info_label = QLabel("就绪")
        self.info_label.setFont(QFont("Arial", 9))
        self.info_label.setStyleSheet("color: #666;")
        self.info_label.setWordWrap(True)  # 允许换行
        self.info_label.setWordWrap(True)  # 允许换行
        
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
    
    def update_channels(self, data_dict: Dict[str, float], timestamp: Optional[float] = None) -> None:
        """批量更新多个通道数据
        
        Args:
            data_dict: 通道名称到数据的映射
            timestamp: 时间戳（可选），如果不提供则使用内部计数器
        """
        if self.is_paused:
            return
        
        # 使用传入的时间戳，如果没有则使用内部计数器
        if timestamp is not None:
            current_time = timestamp
        else:
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
        self.clear_marked_points()  # 清空标记点
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
        vb = self.plot_widget.plotItem.vb
        mouse_point = vb.mapSceneToView(pos)
        mouse_x = mouse_point.x()
        mouse_y = mouse_point.y()
        
        # 查找最近的数据点
        closest_point = self.find_closest_point(mouse_x, mouse_y)
        
        if closest_point:
            channel_name, point_x, point_y = closest_point
            
            # 更新临时吸附点标识
            self.update_hover_point(point_x, point_y)
            
            # 如果有标记点，显示标记点信息
            if self.marked_points:
                info_text = self.get_marked_points_info()
                # 添加鼠标坐标信息
                mouse_info = f"\n鼠标: X={mouse_x:.2f} | Y={mouse_y:.4f}"
                self.info_label.setText(info_text + mouse_info)
            else:
                # 无论是否暂停，都显示最近点信息和鼠标坐标
                self.info_label.setText(
                    f"通道: {channel_name} | 吸附: X={point_x:.2f} | Y={point_y:.4f}\n"
                    f"鼠标: X={mouse_x:.2f} | Y={mouse_y:.4f}"
                )
        else:
            # 如果没有找到最近点，隐藏临时标识
            self.hide_hover_point()
            
            # 显示就绪或标记点信息
            if self.marked_points:
                info_text = self.get_marked_points_info()
                # 添加鼠标坐标信息
                mouse_info = f"\n鼠标: X={mouse_x:.2f} | Y={mouse_y:.4f}"
                self.info_label.setText(info_text + mouse_info)
            else:
                # 只显示鼠标坐标
                self.info_label.setText(
                    f"鼠标: X={mouse_x:.2f} | Y={mouse_y:.4f}"
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
        
        # 降低距离阈值，让吸附更容易
        return closest_point if min_distance < 50 else None
    
    def mouse_clicked(self, event) -> None:
        """鼠标点击事件处理
        
        Args:
            event: 鼠标事件
        """
        from PyQt5.QtCore import QTime
        
        # 如果正在处理，直接返回
        if self.is_processing:
            return
        
        # 只处理双击事件
        if not event.double():
            return  # 单击不处理
        
        # 防抖：检查距离上次双击的时间
        current_time = QTime.currentTime().msecsSinceStartOfDay()
        if current_time - self.last_click_time < 300:  # 300ms内不重复处理
            return
        
        self.is_processing = True
        self.handle_double_click(event)
        self.last_click_time = current_time
        self.is_processing = False
    
    def handle_double_click(self, event) -> None:
        """处理双击事件
        
        Args:
            event: 鼠标事件
        """
        print(f"处理双击事件，当前标记点数量: {len(self.marked_points)}")
        
        # 获取鼠标位置
        pos = event.scenePos()
        vb = self.plot_widget.plotItem.vb
        mouse_point = vb.mapSceneToView(pos)
        x = mouse_point.x()
        y = mouse_point.y()
        
        # 查找最近的数据点
        closest_point = self.find_closest_point(x, y)
        
        if closest_point:
            channel_name, point_x, point_y = closest_point
            
            # 检查是否已经标记过这个点（避免重复标记）
            for marked in self.marked_points:
                if (abs(marked[1] - point_x) < 0.01 and 
                    abs(marked[2] - point_y) < 0.0001):
                    print("该点已标记")
                    return
            
            # 如果已经有2个标记点，清空所有标记
            if len(self.marked_points) >= 2:
                print("检测到已有2个标记点，清空所有标记")
                self.clear_marked_points()
                print("标记点已清空")
                return  # 直接返回，不要添加新标记点
            
            # 添加新的标记点
            print(f"添加新标记点: 通道={channel_name}, X={point_x:.2f}, Y={point_y:.4f}")
            self.marked_points.append((channel_name, point_x, point_y))
            
            # 更新标记点显示
            self.update_marked_points_display()
            
            # 更新信息标签
            self.info_label.setText(self.get_marked_points_info())
            
            print(f"标记完成，当前标记点数量: {len(self.marked_points)}")
        else:
            # 双击空白处，清空标记点
            print("双击空白处，清空标记点")
            self.clear_marked_points()
            self.info_label.setText("标记点已清空")
    
    def update_marked_points_display(self) -> None:
        """更新标记点的显示"""
        # 移除旧的标记点
        if self.marked_scatter:
            self.plot_widget.removeItem(self.marked_scatter)
        
        # 如果没有标记点，直接返回
        if not self.marked_points:
            self.marked_scatter = None
            return
        
        # 提取标记点的坐标
        x_coords = [point[1] for point in self.marked_points]
        y_coords = [point[2] for point in self.marked_points]
        
        # 创建新的标记点散点图
        self.marked_scatter = pg.ScatterPlotItem(
            x=x_coords,
            y=y_coords,
            size=15,
            pen=pg.mkPen('r', width=2),
            brush=pg.mkBrush(255, 0, 0, 150),
            symbol='o'
        )
        self.plot_widget.addItem(self.marked_scatter)
    
    def clear_marked_points(self) -> None:
        """清空所有标记点"""
        self.marked_points.clear()
        
        # 移除标记点显示
        if self.marked_scatter:
            self.plot_widget.removeItem(self.marked_scatter)
            self.marked_scatter = None
        
        # 隐藏临时吸附点
        self.hide_hover_point()
        
        print("标记点已清空")
    
    def update_hover_point(self, x: float, y: float) -> None:
        """更新临时吸附点标识
        
        Args:
            x: x坐标
            y: y坐标
        """
        # 移除旧的临时标识
        if self.hover_scatter:
            self.plot_widget.removeItem(self.hover_scatter)
        
        # 创建新的临时标识（黄色圆点）
        self.hover_scatter = pg.ScatterPlotItem(
            x=[x],
            y=[y],
            size=20,
            pen=pg.mkPen('y', width=2),
            brush=pg.mkBrush(255, 255, 0, 150),
            symbol='o'
        )
        self.plot_widget.addItem(self.hover_scatter)
    
    def hide_hover_point(self) -> None:
        """隐藏临时吸附点标识"""
        if self.hover_scatter:
            self.plot_widget.removeItem(self.hover_scatter)
            self.hover_scatter = None
    
    def get_marked_points_info(self) -> str:
        """获取标记点信息
        
        Returns:
            标记点信息字符串
        """
        if not self.marked_points:
            return "就绪"
        
        if len(self.marked_points) == 1:
            channel, x, y = self.marked_points[0]
            return f"标记点1: 通道={channel} | X={x:.2f} | Y={y:.4f}"
        
        if len(self.marked_points) == 2:
            channel1, x1, y1 = self.marked_points[0]
            channel2, x2, y2 = self.marked_points[1]
            
            # 计算差值
            dx = x2 - x1
            dy = y2 - y1
            
            return (f"标记点1: 通道={channel1} | X={x1:.2f} | Y={y1:.4f}\n"
                    f"标记点2: 通道={channel2} | X={x2:.2f} | Y={y2:.4f}\n"
                    f"差值: ΔX={dx:.2f} | ΔY={dy:.4f}")
        
        return "就绪"
    
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