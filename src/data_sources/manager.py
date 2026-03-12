"""
数据源管理器

管理多个数据源，提供统一的数据访问接口。
"""

from typing import Optional, Dict, Any
from .base import DataSource
from .udp_source import UDPDataSource


class DataSourceManager:
    """数据源管理器
    
    管理当前活动的数据源，提供统一的数据访问接口。
    支持动态切换不同的数据源。
    """
    
    def __init__(self):
        self.current_source: Optional[DataSource] = None
        self.data_buffer = []
        self.max_buffer_size = 1000
    
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
                print(f"数据源已切换到: {source}")
            
            return success
        except Exception as e:
            print(f"设置数据源失败: {e}")
            return False
    
    def read_data(self) -> Optional[Any]:
        """读取数据
        
        Returns:
            读取到的数据，如果没有数据源返回None
        """
        if not self.current_source:
            return None
        
        data = self.current_source.read_data()
        
        if data is not None:
            self.data_buffer.append(data)
            
            # 限制缓冲区大小
            if len(self.data_buffer) > self.max_buffer_size:
                self.data_buffer = self.data_buffer[-self.max_buffer_size:]
        
        return data
    
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