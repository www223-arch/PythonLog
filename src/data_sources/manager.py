"""
数据源管理器

管理多个数据源，提供统一的数据访问接口。
"""

from typing import Optional, Dict, Any, List
from .base import DataSource
from .udp_source import UDPDataSource
from .data_saver import DataSaver


class DataSourceManager:
    """数据源管理器
    
    管理当前活动的数据源，提供统一的数据访问接口。
    支持动态切换不同的数据源。
    """
    
    def __init__(self):
        self.current_source: Optional[DataSource] = None
        self.data_buffer = []
        self.max_buffer_size = 1000
        self.data_saver = DataSaver()
        self.channels = []
        self.channel_data = {}  # 存储各通道的数据
        self.timestamps = []  # 存储时间戳
        self.data_header = 'DATA'  # 数据校验头，默认'DATA'
        self.header_enabled = True  # 是否启用数据校验头验证
 
    
    def set_source(self, source: DataSource) -> bool:
        """设置当前数据源
        
        Args:
            source: 数据源对象
        
        Returns:
            bool: 设置成功返回True，失败返回False
        """
        try:
            if self.current_source:
                self.current_source.disconnect()
            
            self.current_source = source
            success = self.current_source.connect()
            
            if success:
                self.data_buffer.clear()
                self.channels.clear()
                self.channel_data.clear()
                self.timestamps.clear()
                print(f"数据源已切换到: {source}")
            
            return success
        except Exception as e:
            print(f"设置数据源失败: {e}")
            return False
    
    def read_data(self) -> Optional[Dict[str, float]]:
        """读取数据
        
        Returns:
            读取到的数据字典，如果没有数据源返回None
            格式: {'header': str, 'timestamp': float, '通道一': float, '通道二': float, ...}
        """
        if not self.current_source:
            return None
        
        data = self.current_source.read_data()
        
        if data is not None and len(data) > 0:
            # 解析数据：第一个元素是数据校验头，第二个是时间戳，后面是通道数据
            header = str(data[0])
            
            # 验证数据校验头
            if self.header_enabled and header != self.data_header:
                print(f"[警告] 数据校验头不匹配: 期望'{self.data_header}', 收到'{header}' - 丢弃数据")
                return None
            
            timestamp = float(data[1])
            
            # 构建数据字典
            data_dict = {'header': header, 'timestamp': timestamp}
            
            # 从UDP数据源获取通道名称
            if hasattr(self.current_source, 'get_channel_names'):
                channel_names = self.current_source.get_channel_names()
                
                # 使用提取到的通道名称
                for i, value in enumerate(data[2:]):
                    if i < len(channel_names):
                        channel_name = channel_names[i]
                    else:
                        channel_name = f'channel{i+1}'
                    data_dict[channel_name] = float(value)
                    
                    # 自动添加新通道
                    if channel_name not in self.channels:
                        self.channels.append(channel_name)
                        print(f"检测到新通道: {channel_name}")
            else:
                # 如果没有get_channel_names方法，使用默认通道名称
                for i, value in enumerate(data[2:], 1):
                    channel_name = f'channel{i}'
                    data_dict[channel_name] = float(value)
                    
                    if channel_name not in self.channels:
                        self.channels.append(channel_name)
                        print(f"检测到新通道: {channel_name}")
            
            # 保存到缓冲区
            self.data_buffer.append(data_dict)
            
            # 限制缓冲区大小
            if len(self.data_buffer) > self.max_buffer_size:
                self.data_buffer = self.data_buffer[-self.max_buffer_size:]
            
            # 保存到CSV文件
            if self.data_saver.is_active():
                self.data_saver.save_data(data_dict)
            
            return data_dict
        
        return None
    
    def get_buffer(self) -> list:
        """获取数据缓冲区
        
        Returns:
            数据缓冲区列表
        """
        return self.data_buffer.copy()
    
    def clear_buffer(self) -> None:
        """清空数据缓冲区"""
        self.data_buffer.clear()
    
    def disconnect(self) -> None:
        """断开当前数据源"""
        if self.current_source:
            self.current_source.disconnect()
            self.current_source = None

        
        # 停止数据保存
        if self.data_saver.is_active():
            self.data_saver.stop_saving()
        
        # 清空通道
        self.channels.clear()
        self.channel_data.clear()
        self.timestamps.clear()
    
    def is_connected(self) -> bool:
        """检查是否已连接数据源
        
        Returns:
            bool: 已连接返回True，否则返回False
        """
        return self.current_source is not None and self.current_source.is_connected
    
    def get_current_source(self) -> Optional[DataSource]:
        """获取当前数据源
        
        Returns:
            当前数据源对象，如果没有返回None
        """
        return self.current_source
    
    def get_channels(self) -> List[str]:
        """获取所有通道名称
        
        Returns:
            通道名称列表
        """
        return self.channels.copy()
    
    def set_save_path(self, save_path: str) -> None:
        """设置数据保存路径
        
        Args:
            save_path: 保存目录路径
        """
        self.data_saver = DataSaver(save_path)
    
    def start_saving(self) -> bool:
        """开始保存数据到CSV
        
        Returns:
            bool: 成功返回True，失败返回False
        """
        # 不传入通道列表，让DataSaver等待检测到真正的通道名称后再写入表头
        # 这样可以确保CSV表头使用的是从数据中提取的真实通道名称
        return self.data_saver.start_saving(None)
    
    def stop_saving(self) -> None:
        """停止保存数据"""
        self.data_saver.stop_saving()
    
    def get_save_file(self) -> Optional[str]:
        """获取当前保存的文件路径
        
        Returns:
            文件路径，如果没有返回None
        """
        return self.data_saver.get_current_file()
    
    def is_saving(self) -> bool:
        """检查是否正在保存数据
        
        Returns:
            bool: 正在保存返回True
        """
        return self.data_saver.is_active()
    
    def set_data_header(self, header: str) -> None:
        """设置数据校验头
        
        Args:
            header: 数据校验头字符串
        """
        self.data_header = header
        print(f"数据校验头已设置为: {header}")
    
    def get_data_header(self) -> str:
        """获取当前数据校验头
        
        Returns:
            数据校验头字符串
        """
        return self.data_header
    
    def set_header_enabled(self, enabled: bool) -> None:
        """设置是否启用数据校验头验证
        
        Args:
            enabled: True为启用，False为禁用
        """
        self.header_enabled = enabled
        print(f"数据校验头验证已{'启用' if enabled else '禁用'}")
    
    def is_header_enabled(self) -> bool:
        """检查是否启用数据校验头验证
        
        Returns:
            True为启用，False为禁用
        """
        return self.header_enabled


# 便捷函数：创建UDP数据源并连接
def create_udp_source(host: str = '0.0.0.0', port: int = 8888) -> UDPDataSource:
    """创建UDP数据源
    
    Args:
        host: 监听主机地址
        port: 监听端口
    
    Returns:
        UDP数据源对象
    """
    return UDPDataSource(host, port)