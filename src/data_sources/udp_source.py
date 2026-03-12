"""
UDP数据源实现

支持UDP协议的数据接收，为上位机提供实时数据。
"""

import socket
import struct
from typing import Optional, Tuple
from .base import DataSource


class UDPDataSource(DataSource):
    """UDP数据源
    
    通过UDP协议接收数据，支持自定义主机和端口。
    """
    
    def __init__(self, host: str = '0.0.0.0', port: int = 8888):
        """初始化UDP数据源
        
        Args:
            host: 监听主机地址，默认为'0.0.0.0'（所有接口）
            port: 监听端口，默认为8888
        """
        super().__init__()
        self.host = host
        self.port = port
        self.socket = None
        self.buffer_size = 1024
        self.data_format = 'f'  # 默认浮点数格式
    
    def connect(self) -> bool:
        """连接UDP数据源
        
        Returns:
            bool: 连接成功返回True，失败返回False
        """
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.bind((self.host, self.port))
            self.socket.settimeout(1.0)  # 设置超时时间
            self.is_connected = True
            print(f"UDP数据源已连接: {self.host}:{self.port}")
            return True
        except Exception as e:
            print(f"UDP连接失败: {e}")
            self.is_connected = False
            return False
    
    def read_data(self) -> Optional[Tuple[float, ...]]:
        """读取UDP数据
        
        Returns:
            解析后的数据元组，如果读取失败返回None
        """
        if not self.is_connected or not self.socket:
            return None
        
        try:
            data, addr = self.socket.recvfrom(self.buffer_size)
            return self._parse_data(data)
        except socket.timeout:
            return None
        except Exception as e:
            print(f"读取UDP数据失败: {e}")
            return None
    
    def _parse_data(self, data: bytes) -> Tuple[float, ...]:
        """解析UDP数据
        
        Args:
            data: 原始字节数据
        
        Returns:
            解析后的数据元组
        """
        try:
            # 假设数据是多个浮点数，每个4字节
            num_floats = len(data) // 4
            values = struct.unpack(f'{num_floats}f', data)
            return values
        except struct.error:
            # 如果解析失败，尝试其他格式
            print(f"数据解析失败，原始数据: {data}")
            return tuple()
    
    def disconnect(self) -> None:
        """断开UDP连接"""
        if self.socket:
            self.socket.close()
            self.socket = None
        self.is_connected = False
        print("UDP数据源已断开")
    
    def set_data_format(self, format_str: str) -> None:
        """设置数据解析格式
        
        Args:
            format_str: struct格式字符串，如'f'表示浮点数
        """
        self.data_format = format_str
    
    def set_buffer_size(self, size: int) -> None:
        """设置接收缓冲区大小
        
        Args:
            size: 缓冲区大小（字节）
        """
        self.buffer_size = size
        if self.socket:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, size)