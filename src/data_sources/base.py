"""
数据源抽象基类

定义所有数据源的通用接口，支持多种数据源扩展。
"""

from abc import ABC, abstractmethod
from typing import Optional, Any


class DataSource(ABC):
    """数据源抽象基类
    
    所有数据源都必须继承此类并实现抽象方法。
    支持的数据源类型：UDP、串口、文件等。
    """
    
    def __init__(self):
        self.is_connected = False
        self.config = {}
    
    @abstractmethod
    def connect(self) -> bool:
        """连接数据源
        
        Returns:
            bool: 连接成功返回True，失败返回False
        """
        pass
    
    @abstractmethod
    def read_data(self) -> Optional[Any]:
        """读取数据
        
        Returns:
            读取到的数据，如果读取失败返回None
        """
        pass
    
    @abstractmethod
    def disconnect(self) -> None:
        """断开数据源连接"""
        pass
    
    def configure(self, **kwargs) -> None:
        """配置数据源参数
        
        Args:
            **kwargs: 配置参数
        """
        self.config.update(kwargs)
    
    def get_config(self) -> dict:
        """获取当前配置
        
        Returns:
            dict: 当前配置字典
        """
        return self.config.copy()
    
    def __str__(self):
        return f"{self.__class__.__name__}(connected={self.is_connected})"