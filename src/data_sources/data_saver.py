"""
数据保存模块

将接收到的数据保存为CSV格式，支持Excel打开。
"""

import csv
import os
from datetime import datetime
from typing import List, Dict, Optional


class DataSaver:
    """数据保存器
    
    将数据保存为CSV格式，支持Excel打开。
    """
    
    def __init__(self, save_dir: str = 'data'):
        """初始化数据保存器
        
        Args:
            save_dir: 保存目录
        """
        self.save_dir = save_dir
        self.current_file = None
        self.csv_writer = None
        self.csv_file = None
        self.channels = []
        self.is_saving = False
        self.header_written = False  # 标记是否已写入表头
        
        # 确保保存目录存在
        os.makedirs(self.save_dir, exist_ok=True)
    
    def start_saving(self, channels: List[str] = None) -> bool:
        """开始保存数据
        
        Args:
            channels: 通道名称列表（可选，如果为None则等待检测通道）
        
        Returns:
            bool: 成功返回True，失败返回False
        """
        try:
            # 生成文件名：data_YYYYMMDD_HHMMSS.csv
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'data_{timestamp}.csv'
            filepath = os.path.join(self.save_dir, filename)
            
            # 打开CSV文件
            self.csv_file = open(filepath, 'w', newline='', encoding='utf-8-sig')
            self.csv_writer = csv.writer(self.csv_file)
            
            # 如果提供了通道列表，立即写入表头
            if channels:
                self.channels = channels
                header = ['时间戳'] + channels
                self.csv_writer.writerow(header)
                self.header_written = True
                print(f"[CSV] 数据保存已启动: {filepath}")
                print(f"[CSV] 通道: {channels}")
            else:
                # 没有提供通道列表，等待检测到通道后再写入表头
                self.channels = []
                self.header_written = False
                print(f"[CSV] 数据保存已启动: {filepath}")
                print(f"[CSV] 等待检测通道...")
            
            self.current_file = filepath
            self.is_saving = True
            
            return True
        except Exception as e:
            print(f"[CSV] 启动数据保存失败: {e}")
            return False
    
    def save_data(self, data: Dict[str, float]) -> None:
        """保存数据
        
        Args:
            data: 通道名称到数据的映射，必须包含'timestamp'键
        """
        if not self.is_saving or not self.csv_writer:
            return
        
        try:
            # 提取时间戳
            timestamp = data.get('timestamp', 0.0)
            
            # 获取当前数据中的所有通道（排除时间戳）
            data_channels = [k for k in data.keys() if k != 'timestamp']
            
            # 检查是否有新通道
            new_channels = [ch for ch in data_channels if ch not in self.channels]
            if new_channels:
                # 有新通道，添加到通道列表
                self.channels.extend(new_channels)
                print(f"[CSV] 检测到新通道: {new_channels}")
                
                # 如果还未写入表头，现在写入
                if not self.header_written:
                    header = ['时间戳'] + self.channels
                    self.csv_writer.writerow(header)
                    self.header_written = True
                    print(f"[CSV] 写入表头: {header}")
            
            # 构建数据行：时间戳 + 各通道数据
            row = [timestamp]
            for channel in self.channels:
                value = data.get(channel, 0.0)
                row.append(value)
            
            # 写入CSV文件
            self.csv_writer.writerow(row)
            
        except Exception as e:
            print(f"[CSV] 保存数据失败: {e}")
    
    def stop_saving(self) -> None:
        """停止保存数据"""
        if self.csv_file:
            self.csv_file.close()
            self.csv_file = None
            self.csv_writer = None
        
        self.is_saving = False
        print(f"数据保存已停止: {self.current_file}")
        self.current_file = None
    
    def get_current_file(self) -> Optional[str]:
        """获取当前保存的文件路径
        
        Returns:
            当前文件路径，如果没有返回None
        """
        return self.current_file
    
    def is_active(self) -> bool:
        """检查是否正在保存
        
        Returns:
            bool: 正在保存返回True
        """
        return self.is_saving