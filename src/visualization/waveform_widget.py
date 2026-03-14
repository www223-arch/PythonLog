"""
波形显示组件

提供实时波形显示功能，支持多通道、缩放、鼠标吸附等交互功能。
"""

import pyqtgraph as pg
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QComboBox, QHBoxLayout
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
from typing import Dict, List, Tuple, Optional
import numpy as np
from scipy.fft import fft, fftfreq


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
        self.limit_data = True  # 是否限制数据点数
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
        
        # 频域分析相关
        self.freq_hover_scatter = None  # 频域鼠标悬停时的临时标识
        self.freq_peak_scatter = None  # 频域峰值点标识
        self.freq_peaks = []  # 存储频域峰值点 [(freq, magnitude), ...]
        self.freq_curves = {}  # 存储频域曲线 {channel_name: curve_item}
        self.freq_user_markers = []  # 存储用户双击设置的标记点 [(scatter, text), ...]
        
        # 更新定时器
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_display)
        self.update_interval = 5  # 更新间隔（毫秒）
    
    def init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout()
        
        # 频域分析控制面板
        fft_control_layout = QHBoxLayout()
        
        fft_label = QLabel("频域分析:")
        fft_label.setFont(QFont("Arial", 10, QFont.Bold))
        
        self.channel_combo = QComboBox()
        self.channel_combo.setMinimumWidth(150)
        self.channel_combo.currentTextChanged.connect(self.on_channel_changed)
        
        self.fft_btn = QPushButton("分析")
        self.fft_btn.clicked.connect(self.perform_fft_analysis)
        self.fft_btn.setMaximumWidth(80)
        
        self.fft_clear_btn = QPushButton("清除标记")
        self.fft_clear_btn.clicked.connect(self.clear_freq_markers)
        self.fft_clear_btn.setMaximumWidth(80)
        
        self.fft_show_all_btn = QPushButton("显示全部")
        self.fft_show_all_btn.clicked.connect(self.show_all_channels_fft)
        self.fft_show_all_btn.setMaximumWidth(80)
        
        fft_control_layout.addWidget(fft_label)
        fft_control_layout.addWidget(self.channel_combo)
        fft_control_layout.addWidget(self.fft_btn)
        fft_control_layout.addWidget(self.fft_clear_btn)
        fft_control_layout.addWidget(self.fft_show_all_btn)
        fft_control_layout.addStretch()
        
        layout.addLayout(fft_control_layout)
        
        # 创建选项卡
        from PyQt5.QtWidgets import QTabWidget
        self.tab_widget = QTabWidget()
        
        # 时域分析选项卡
        self.time_tab = QWidget()
        time_layout = QVBoxLayout()
        
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
        
        # 添加到时域布局
        time_layout.addWidget(self.info_label)
        time_layout.addWidget(self.plot_widget)
        
        self.time_tab.setLayout(time_layout)
        
        # 频域分析选项卡
        self.freq_tab = QWidget()
        freq_layout = QVBoxLayout()
        
        # 创建频域绘图组件
        self.freq_plot_widget = pg.PlotWidget()
        self.freq_plot_widget.setBackground('w')  # 白色背景
        self.freq_plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.freq_plot_widget.setLabel('left', '幅值')
        self.freq_plot_widget.setLabel('bottom', '频率 (Hz)')
        self.freq_plot_widget.setTitle('频域分析')
        self.freq_plot_widget.setLogMode(x=False, y=False)
        
        # 设置交互
        self.freq_plot_widget.setMouseEnabled(x=True, y=True)
        self.freq_plot_widget.enableAutoRange(x=True, y=True)
        
        # 鼠标移动事件
        self.freq_plot_widget.scene().sigMouseMoved.connect(self.freq_mouse_moved)
        print("频域鼠标移动事件已连接")
        
        # 鼠标双击事件
        self.freq_plot_widget.scene().sigMouseClicked.connect(self.freq_mouse_clicked)
        
        # 双击防抖
        self.freq_last_click_time = 0
        self.freq_is_processing = False
        
        # 频域信息标签
        self.freq_info_label = QLabel("请选择通道并点击'分析'按钮")
        self.freq_info_label.setFont(QFont("Arial", 9))
        self.freq_info_label.setStyleSheet("color: #666;")
        self.freq_info_label.setWordWrap(True)
        
        freq_layout.addWidget(self.freq_info_label)
        freq_layout.addWidget(self.freq_plot_widget)
        
        self.freq_tab.setLayout(freq_layout)
        
        # 添加选项卡
        self.tab_widget.addTab(self.time_tab, "时域")
        self.tab_widget.addTab(self.freq_tab, "频域")
        
        layout.addWidget(self.tab_widget)
        
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
        
        # 更新通道选择下拉框
        self.channel_combo.addItem(name)
        
        print(f"通道 {name} 已添加")
    
    def remove_channel(self, name: str) -> None:
        """移除通道
        
        Args:
            name: 通道名称
        """
        if name in self.channels:
            self.plot_widget.removeItem(self.channels[name]['curve'])
            del self.channels[name]
            
            # 从通道选择下拉框中移除
            index = self.channel_combo.findText(name)
            if index >= 0:
                self.channel_combo.removeItem(index)
            
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
        
        # 限制数据点数（如果启用）
        if self.limit_data and len(channel['data']) > self.max_points:
            channel['data'] = channel['data'][-self.max_points:]
            channel['x_data'] = channel['x_data'][-self.max_points:]
    
    def update_channels(self, data_dict: Dict[str, float], timestamp: Optional[float] = None) -> None:
        """批量更新多个通道数据
        
        Args:
            data_dict: 通道名称到数据的映射
            timestamp: 时间戳（可选），如果不提供则使用内部计数器
        
        注意：暂停时仍然保存数据到曲线中，只是不更新显示
        """
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
        """更新显示
        
        注意：暂停时不更新显示，但数据仍然保存到曲线中
        """
        if self.is_paused:
            return
        
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
        print(f"波形显示已{'暂停' if self.is_paused else '继续'}")
    
    def clear_all(self) -> None:
        """清空所有数据"""
        for channel in self.channels.values():
            channel['data'].clear()
            channel['x_data'].clear()
            channel['curve'].setData([], [])
        self.time_counter = 0
        self.clear_marked_points()  # 清空标记点
        
        # 清空频域分析
        self.freq_plot_widget.clear()
        self.freq_peak_scatter = None
        self.freq_hover_scatter = None
        self.freq_curves.clear()
        self.freq_peaks.clear()
        self.freq_user_markers.clear()
        self.freq_info_label.setText("请选择通道并点击'分析'按钮")
        
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
            # 检查曲线是否可见
            if not channel['curve'].isVisible():
                continue
            
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
    
    def set_limit_data(self, limit: bool) -> None:
        """设置是否限制数据点数
        
        Args:
            limit: True表示限制数据点数，False表示不限制
        """
        self.limit_data = limit
        print(f"数据限制已{'启用' if limit else '禁用'}，最大点数: {self.max_points if limit else '无限制'}")
    
    def set_sample_rate(self, sample_rate: float) -> None:
        """设置采样率
        
        Args:
            sample_rate: 采样率（Hz）
        """
        self.sample_rate = sample_rate
    
    def update_channel_color(self, name: str, color: tuple) -> None:
        """更新通道颜色
        
        Args:
            name: 通道名称
            color: 颜色（RGB元组）
        """
        if name in self.channels:
            channel = self.channels[name]
            
            # 更新颜色
            channel['color'] = color
            
            # 更新曲线颜色
            pen = pg.mkPen(color=color, width=channel['width'])
            channel['curve'].setPen(pen)
            
            # 更新频域曲线颜色（如果存在）
            if name in self.freq_curves:
                self.freq_curves[name]['color'] = color
                freq_curve = self.freq_curves[name]['curve']
                freq_pen = pg.mkPen(color=color, width=2)
                freq_curve.setPen(freq_pen)
            
            print(f"通道 '{name}' 颜色已更新为: {color}")
    
    def rename_channel(self, old_name: str, new_name: str) -> None:
        """重命名通道
        
        Args:
            old_name: 原通道名称
            new_name: 新通道名称
        """
        if old_name not in self.channels:
            print(f"通道 '{old_name}' 不存在")
            return
        
        if new_name in self.channels:
            print(f"通道 '{new_name}' 已存在")
            return
        
        # 更新channels字典
        self.channels[new_name] = self.channels[old_name]
        del self.channels[old_name]
        
        # 更新channel_data字典
        if old_name in self.channel_data:
            self.channel_data[new_name] = self.channel_data[old_name]
            del self.channel_data[old_name]
        
        # 更新freq_curves字典（如果存在）
        if old_name in self.freq_curves:
            self.freq_curves[new_name] = self.freq_curves[old_name]
            del self.freq_curves[old_name]
        
        print(f"通道 '{old_name}' 已重命名为 '{new_name}'")
    
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
    
    def on_channel_changed(self, channel_name: str) -> None:
        """通道选择改变事件
        
        Args:
            channel_name: 选中的通道名称
        """
        if channel_name:
            print(f"已选择通道: {channel_name}")
    
    def perform_fft_analysis(self) -> None:
        """执行FFT频域分析"""
        channel_name = self.channel_combo.currentText()
        
        if not channel_name or channel_name not in self.channels:
            self.freq_info_label.setText("请先选择一个有效的通道")
            return
        
        channel = self.channels[channel_name]
        data = channel['data']
        
        if len(data) < 10:
            self.freq_info_label.setText(f"数据点太少（{len(data)}个），无法进行频域分析")
            return
        
        try:
            # 执行FFT
            n = len(data)
            fft_result = fft(data)
            fft_freq = fftfreq(n, d=1.0/self.sample_rate)
            
            # 只取正频率部分
            positive_freq_idx = fft_freq >= 0
            freq = fft_freq[positive_freq_idx]
            magnitude = np.abs(fft_result[positive_freq_idx])
            
            # 归一化幅值
            magnitude = magnitude / n
            
            # 检测峰值
            peaks = self.detect_peaks(freq, magnitude)
            self.freq_peaks = peaks
            
            # 找到主频
            if len(magnitude) > 1:
                # 跳过直流分量（索引0）
                main_freq_idx = np.argmax(magnitude[1:]) + 1
                main_freq = freq[main_freq_idx]
                main_magnitude = magnitude[main_freq_idx]
            else:
                main_freq = 0.0
                main_magnitude = 0.0
            
            # 清除旧的频域曲线
            self.freq_plot_widget.clear()
            
            # 绘制频域曲线
            pen = pg.mkPen(color=channel['color'], width=2)
            curve = self.freq_plot_widget.plot(freq, magnitude, pen=pen, name=channel_name)
            
            # 保存曲线引用
            self.freq_curves[channel_name] = {
                'curve': curve,
                'freq': freq,
                'magnitude': magnitude,
                'color': channel['color']
            }
            
            # 标记主频
            self.mark_main_frequency(main_freq, main_magnitude, channel['color'])
            
            # 更新频域信息
            peak_info = " | ".join([f"{f:.2f}Hz({m:.4f})" for f, m in peaks[:5]])
            info_text = (f"通道: {channel_name} | 数据点数: {n} | 采样率: {self.sample_rate:.1f} Hz\n"
                        f"主频: {main_freq:.2f} Hz | 幅值: {main_magnitude:.4f}\n"
                        f"频率范围: 0 ~ {freq[-1]:.2f} Hz\n"
                        f"峰值: {peak_info}")
            self.freq_info_label.setText(info_text)
            
            print(f"频域分析完成: 通道={channel_name}, 主频={main_freq:.2f} Hz, 峰值数={len(peaks)}")
            
        except Exception as e:
            self.freq_info_label.setText(f"频域分析失败: {str(e)}")
            print(f"频域分析失败: {e}")
    
    def detect_peaks(self, freq: np.ndarray, magnitude: np.ndarray, threshold: float = 0.1) -> List[Tuple[float, float]]:
        """检测频域峰值
        
        Args:
            freq: 频率数组
            magnitude: 幅值数组
            threshold: 峰值检测阈值（相对于最大幅值）
        
        Returns:
            峰值列表 [(频率, 幅值), ...]
        """
        if len(magnitude) < 3:
            return []
        
        # 计算阈值
        max_magnitude = np.max(magnitude[1:])  # 跳过直流分量
        threshold_value = max_magnitude * threshold
        
        peaks = []
        
        # 检测局部峰值
        for i in range(1, len(magnitude) - 1):
            if (magnitude[i] > magnitude[i - 1] and 
                magnitude[i] > magnitude[i + 1] and 
                magnitude[i] > threshold_value):
                peaks.append((freq[i], magnitude[i]))
        
        # 按幅值降序排序
        peaks.sort(key=lambda x: x[1], reverse=True)
        
        return peaks
    
    def mark_main_frequency(self, freq: float, magnitude: float, color: str) -> None:
        """标记主频
        
        Args:
            freq: 主频
            magnitude: 主频幅值
            color: 标记颜色
        """
        # 移除旧的主频标记
        if self.freq_peak_scatter:
            self.freq_plot_widget.removeItem(self.freq_peak_scatter)
        
        # 创建主频标记（红色星形）
        self.freq_peak_scatter = pg.ScatterPlotItem(
            x=[freq],
            y=[magnitude],
            size=25,
            pen=pg.mkPen('r', width=2),
            brush=pg.mkBrush(255, 0, 0, 150),
            symbol='star'
        )
        self.freq_plot_widget.addItem(self.freq_peak_scatter)
        
        # 添加文本标签
        text = pg.TextItem(text=f"主频: {freq:.2f}Hz", color='r', anchor=(0.5, 1.5))
        text.setPos(freq, magnitude)
        self.freq_plot_widget.addItem(text)
    
    def freq_mouse_moved(self, pos: Tuple[float, float]) -> None:
        """频域鼠标移动事件
        
        Args:
            pos: 鼠标位置 (x, y)
        """
        if self.tab_widget.currentIndex() != 1:  # 不是频域选项卡
            return
        
        try:
            # 转换坐标
            mouse_point = self.freq_plot_widget.plotItem.vb.mapSceneToView(pos)
            x, y = mouse_point.x(), mouse_point.y()
            
            # 查找最近的频域点
            closest_point = self.find_closest_freq_point(x, y)
            
            if closest_point:
                freq, magnitude = closest_point
                
                # 移除旧的临时标识
                if self.freq_hover_scatter:
                    self.freq_plot_widget.removeItem(self.freq_hover_scatter)
                
                # 创建新的临时标识（黄色圆点）
                self.freq_hover_scatter = pg.ScatterPlotItem(
                    x=[freq],
                    y=[magnitude],
                    size=20,
                    pen=pg.mkPen('y', width=2),
                    brush=pg.mkBrush(255, 255, 0, 150),
                    symbol='o'
                )
                self.freq_plot_widget.addItem(self.freq_hover_scatter)
                
                # 更新频域信息
                self.freq_info_label.setText(
                    f"频率: {freq:.2f} Hz | 幅值: {magnitude:.4f}\n"
                    f"双击标记此频率点"
                )
        except Exception as e:
            pass
    
    def freq_mouse_clicked(self, event) -> None:
        """频域鼠标点击事件（双击标记峰值）
        
        Args:
            event: 鼠标事件
        """
        if self.tab_widget.currentIndex() != 1:  # 不是频域选项卡
            return
        
        if event.double():
            try:
                # 转换坐标
                pos = event.scenePos()
                mouse_point = self.freq_plot_widget.plotItem.vb.mapSceneToView(pos)
                x, y = mouse_point.x(), mouse_point.y()
                
                print(f"双击位置: ({x:.2f}, {y:.4f})")
                
                # 查找最近的频域点
                closest_point = self.find_closest_freq_point(x, y)
                
                if closest_point:
                    freq, magnitude = closest_point
                    
                    # 添加标记
                    self.mark_frequency_point(freq, magnitude)
                    
                    # 更新频域信息
                    self.freq_info_label.setText(
                        f"已标记频域点: 频率={freq:.2f}Hz, 幅值={magnitude:.4f}"
                    )
                else:
                    print("未找到附近的频域点")
                    self.freq_info_label.setText(
                        f"未找到附近的频域点\n"
                        f"请点击频域曲线上的点"
                    )
            except Exception as e:
                print(f"标记频域点失败: {e}")
                self.freq_info_label.setText(f"标记失败: {str(e)}")
    
    def find_closest_freq_point(self, x: float, y: float) -> Optional[Tuple[float, float]]:
        """查找最近的频域点
        
        Args:
            x: 鼠标x坐标
            y: 鼠标y坐标
        
        Returns:
            (频率, 幅值) 或 None
        """
        if not self.freq_curves:
            return None
        
        min_distance = float('inf')
        closest_point = None
        
        for channel_name, curve_data in self.freq_curves.items():
            freq = curve_data['freq']
            magnitude = curve_data['magnitude']
            
            for f, m in zip(freq, magnitude):
                distance = ((f - x) ** 2 + (m - y) ** 2) ** 0.5
                if distance < min_distance:
                    min_distance = distance
                    closest_point = (f, m)
        
        # 增加距离阈值，让双击更容易标记频率点
        return closest_point if min_distance < 100 else None
    
    def mark_frequency_point(self, freq: float, magnitude: float) -> None:
        """标记频域点
        
        Args:
            freq: 频率
            magnitude: 幅值
        """
        # 创建标记点（绿色三角形）
        scatter = pg.ScatterPlotItem(
            x=[freq],
            y=[magnitude],
            size=25,
            pen=pg.mkPen('g', width=2),
            brush=pg.mkBrush(0, 255, 0, 150),
            symbol='t1'
        )
        self.freq_plot_widget.addItem(scatter)
        
        # 添加文本标签
        text = pg.TextItem(text=f"{freq:.2f}Hz", color='g', anchor=(0.5, 1.5))
        text.setPos(freq, magnitude)
        self.freq_plot_widget.addItem(text)
        
        # 保存标记点
        self.freq_user_markers.append((scatter, text))
        
        print(f"已标记频域点: 频率={freq:.2f}Hz, 幅值={magnitude:.4f}")
    
    def clear_freq_markers(self) -> None:
        """清除用户双击设置的标记点"""
        # 移除用户双击设置的标记点
        for scatter, text in self.freq_user_markers:
            self.freq_plot_widget.removeItem(scatter)
            self.freq_plot_widget.removeItem(text)
        
        # 清空标记点列表
        self.freq_user_markers.clear()
        
        self.freq_info_label.setText("已清除用户标记点")
        print(f"已清除 {len(self.freq_user_markers)} 个用户标记点")
    
    def show_all_channels_fft(self) -> None:
        """显示所有通道的频域分析"""
        if not self.channels:
            self.freq_info_label.setText("没有可分析的通道")
            return
        
        try:
            # 清除旧的频域曲线
            self.freq_plot_widget.clear()
            self.freq_curves.clear()
            
            all_peaks = []
            
            # 对每个通道进行FFT分析
            for channel_name, channel in self.channels.items():
                data = channel['data']
                
                if len(data) < 10:
                    continue
                
                # 执行FFT
                n = len(data)
                fft_result = fft(data)
                fft_freq = fftfreq(n, d=1.0/self.sample_rate)
                
                # 只取正频率部分
                positive_freq_idx = fft_freq >= 0
                freq = fft_freq[positive_freq_idx]
                magnitude = np.abs(fft_result[positive_freq_idx])
                
                # 归一化幅值
                magnitude = magnitude / n
                
                # 绘制频域曲线
                pen = pg.mkPen(color=channel['color'], width=2)
                curve = self.freq_plot_widget.plot(freq, magnitude, pen=pen, name=channel_name)
                
                # 保存曲线引用
                self.freq_curves[channel_name] = {
                    'curve': curve,
                    'freq': freq,
                    'magnitude': magnitude,
                    'color': channel['color']
                }
                
                # 检测峰值
                peaks = self.detect_peaks(freq, magnitude)
                all_peaks.extend([(channel_name, f, m) for f, m in peaks[:3]])
            
            # 更新频域信息
            peak_info = " | ".join([f"{n}:{f:.2f}Hz" for n, f, m in all_peaks[:10]])
            info_text = (f"已显示 {len(self.freq_curves)} 个通道的频域分析\n"
                        f"采样率: {self.sample_rate:.1f} Hz\n"
                        f"峰值: {peak_info}")
            self.freq_info_label.setText(info_text)
            
            print(f"已显示 {len(self.freq_curves)} 个通道的频域分析")
            
        except Exception as e:
            self.freq_info_label.setText(f"显示全部频域分析失败: {str(e)}")
            print(f"显示全部频域分析失败: {e}")