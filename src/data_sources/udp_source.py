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
        self.last_raw_text = None  # 存储原始文本，用于提取通道名称
    
    def connect(self) -> bool:
        """连接UDP数据源
        
        Returns:
            bool: 连接成功返回True，失败返回False
        """
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.bind((self.host, self.port))
            self.socket.settimeout(0.01)  # 设置超时时间
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
        
        支持两种格式：
        1. 二进制格式：多个浮点数
        2. 文本格式："时间戳,通道一=数值,通道二=数值"
        
        Args:
            data: 原始字节数据
        
        Returns:
            解析后的数据元组 (时间戳, 通道1值, 通道2值, ...)
        """
        try:
            # 尝试解析为文本格式
            text_data = data.decode('utf-8').strip()
            return self._parse_text_data(text_data)
        except UnicodeDecodeError:
            # 如果不是文本，尝试二进制格式
            return self._parse_binary_data(data)
        except Exception as e:
            print(f"数据解析失败: {e}, 原始数据: {data}")
            return tuple()
    
    def _parse_text_data(self, text: str) -> Tuple[float, ...]:
        """解析文本格式数据
        
        格式: "数据校验头,时间戳,通道一=数值,通道二=数值"
        
        Args:
            text: 文本数据
        
        Returns:
            解析后的数据元组 (数据校验头, 时间戳, 通道1值, 通道2值, ...)
        """
        try:
            # 保存原始文本，用于提取通道名称
            self.last_raw_text = text
            
            parts = text.split(',')
            if not parts:
                return tuple()
            
            # 第一部分是数据校验头
            header = parts[0].strip()
            
            # 第二部分是时间戳
            timestamp = float(parts[1].strip())
            values = [header, timestamp]
            
            # 解析通道数据（从第三部分开始）
            for part in parts[2:]:
                if '=' in part:
                    channel_part, value_part = part.split('=', 1)
                    value = float(value_part)
                    values.append(value)
            
            return tuple(values)
        except Exception as e:
            print(f"文本数据解析失败: {e}, 文本: {text}")
            return tuple()
    
    def get_channel_names(self) -> list:
        """从原始文本中提取通道名称
        
        Returns:
            通道名称列表
        """
        if not self.last_raw_text:
            return []
        
        try:
            parts = self.last_raw_text.split(',')
            if len(parts) < 3:
                return []
            
            # 从第三部分开始提取通道名称
            channel_names = []
            for part in parts[2:]:
                if '=' in part:
                    channel_part, _ = part.split('=', 1)
                    channel_name = channel_part.strip()
                    if channel_name and channel_name not in channel_names:
                        channel_names.append(channel_name)
            
            return channel_names
        except Exception as e:
            print(f"提取通道名称失败: {e}")
            return []
    
    def _parse_binary_data(self, data: bytes) -> Tuple[float, ...]:
        """解析二进制格式数据
        
        格式: 多个浮点数，每个4字节
        
        Args:
            data: 字节数据
        
        Returns:
            解析后的数据元组
        """
        try:
            num_floats = len(data) // 4
            values = struct.unpack(f'{num_floats}f', data)
            return values
        except struct.error:
            print(f"二进制数据解析失败，原始数据: {data}")
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