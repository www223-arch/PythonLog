"""
串口数据源实现

支持串口协议的数据接收，为上位机提供实时数据。
支持文本协议和二进制协议。
"""

import time
import struct
from typing import Optional, Tuple
from .base import DataSource


class SerialDataSource(DataSource):
    """串口数据源
    
    通过串口协议接收数据，支持自定义端口和波特率。
    支持文本协议和二进制协议。
    """
    
    def __init__(self, port: str = 'COM1', baudrate: int = 115200, protocol: str = 'text', data_header: str = 'DATA'):
        """初始化串口数据源
        
        Args:
            port: 串口名称，默认为'COM1'
            baudrate: 波特率，默认为115200
            protocol: 协议类型，'text'为文本协议，'binary'为二进制协议
            data_header: 数据校验头，用于文本协议
        """
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.protocol = protocol  # 'text' 或 'binary'
        self.data_header = data_header  # 数据校验头
        self.serial = None
        self.last_raw_text = None  # 存储原始文本，用于提取通道名称
        self.buffer = bytearray()  # 二进制数据缓冲区
        self.frame_tail = bytes([0x00, 0x00, 0x80, 0x7f])  # 二进制帧尾标识
        self.raw_data_callback = None  # 原始数据回调函数
    
    def connect(self) -> bool:
        """连接串口数据源
        
        Returns:
            bool: 连接成功返回True，失败返回False
        """
        try:
            import serial
            self.serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=0.001  # 1ms超时
            )
            self.is_connected = True
            print(f"串口数据源已连接: {self.port} @ {self.baudrate}bps")
            return True
        except Exception as e:
            print(f"串口连接失败: {e}")
            self.is_connected = False
            return False
    
    def read_data(self) -> Optional[Tuple[float, ...]]:
        """读取串口数据
        
        Returns:
            解析后的数据元组，如果读取失败返回None
        """
        if not self.is_connected or not self.serial:
            return None
        
        try:
            if self.serial.in_waiting > 0:
                if self.protocol == 'text':
                    # 文本协议：按行读取
                    data = self.serial.readline()
                    # 调用原始数据回调
                    if self.raw_data_callback:
                        self.raw_data_callback(data)
                    return self._parse_data(data)
                elif self.protocol == 'justfloat':
                    # Justfloat协议：纯浮点数，无数据校验头和时间戳
                    data = self.serial.read(self.serial.in_waiting)
                    # 调用原始数据回调
                    if self.raw_data_callback:
                        self.raw_data_callback(data)
                    return self._parse_justfloat_data(data)
                else:  # rawdata
                    # Rawdata协议：原始数据，直接显示
                    data = self.serial.read(self.serial.in_waiting)
                    # 调用原始数据回调
                    if self.raw_data_callback:
                        self.raw_data_callback(data)
                    # 返回空数据元组以更新last_data_time
                    # 格式: (数据校验头, 时间戳)
                    import time
                    return ('', time.time())  # Rawdata返回空数据元组
            return None
        except Exception as e:
            print(f"读取串口数据失败: {e}")
            # 串口断开，更新连接状态
            self.is_connected = False
            return None
    
    def _parse_data(self, data: bytes) -> Tuple[float, ...]:
        """解析串口数据（文本协议）
        
        支持文本格式："数据校验头,时间戳,通道一=数值,通道二=数值"
        
        Args:
            data: 原始字节数据
        
        Returns:
            解析后的数据元组 (数据校验头, 时间戳, 通道1值, 通道2值, ...)
        """
        try:
            text_data = data.decode('utf-8').strip()
            return self._parse_text_data(text_data)
        except Exception as e:
            print(f"串口数据解析失败: {e}, 原始数据: {data}")
            # 返回错误标识，用于触发数据格式不匹配状态
            import time
            return ('FORMAT_ERROR', time.time())
    
    def _parse_binary_data(self, data: bytes) -> Optional[Tuple[float, ...]]:
        """解析二进制数据
        
        二进制协议格式：
        struct Frame {
            float fdata[CH_COUNT];
            unsigned char tail[4]{0x00, 0x00, 0x80, 0x7f};
        };
        
        Args:
            data: 原始字节数据
        
        Returns:
            解析后的数据元组，如果解析失败返回None
        """
        try:
            # 将新数据添加到缓冲区
            self.buffer.extend(data)
            
            # 查找帧尾标识
            tail_pos = self.buffer.find(self.frame_tail)
            
            if tail_pos == -1:
                # 没有找到帧尾，继续等待
                return None
            
            # 检查帧长度是否合理
            # 帧尾位置 + 4字节帧尾 = 总长度
            frame_length = tail_pos + 4
            
            if frame_length < 4:
                # 帧太短，丢弃
                self.buffer = self.buffer[frame_length:]
                return None
            
            # 提取帧数据（不包括帧尾）
            frame_data = self.buffer[:tail_pos]
            
            # 清空缓冲区
            self.buffer = self.buffer[frame_length:]
            
            # 解析浮点数数据
            # 每个浮点数4字节
            num_floats = len(frame_data) // 4
            
            if num_floats == 0:
                return None
            
            # 解析浮点数
            values = struct.unpack(f'{num_floats}f', frame_data)
            
            # 返回数据元组
            return tuple(values)
        except Exception as e:
            print(f"二进制数据解析失败: {e}, 原始数据: {data}")
            return None
    
    def _parse_justfloat_data(self, data: bytes) -> Optional[Tuple[float, ...]]:
        """解析Justfloat数据（纯浮点数，无数据校验头和时间戳）
        
        Justfloat协议格式：
        struct Frame {
            float fdata[CH_COUNT];
            unsigned char tail[4]{0x00, 0x00, 0x80, 0x7f};
        };
        
        Args:
            data: 原始字节数据
        
        Returns:
            解析后的数据元组 (数据校验头, 时间戳, 通道1值, 通道2值, ...)
        """
        try:
            # 将新数据添加到缓冲区
            self.buffer.extend(data)
            
            # 查找帧尾标识
            tail_pos = self.buffer.find(self.frame_tail)
            
            if tail_pos == -1:
                # 没有找到帧尾，继续等待
                return None
            
            # 检查帧长度是否合理
            # 帧尾位置 + 4字节帧尾 = 总长度
            frame_length = tail_pos + 4
            
            if frame_length < 4:
                # 帧太短，丢弃
                self.buffer = self.buffer[frame_length:]
                return None
            
            # 提取帧数据（不包括帧尾）
            frame_data = self.buffer[:tail_pos]
            
            # 清空缓冲区
            self.buffer = self.buffer[frame_length:]
            
            # 解析浮点数数据
            # 每个浮点数4字节
            num_floats = len(frame_data) // 4
            
            if num_floats == 0:
                return None
            
            # 解析浮点数
            values = struct.unpack(f'{num_floats}f', frame_data)
            
            # 返回数据元组（添加数据校验头和时间戳）
            # 数据校验头：使用空字符串
            # 时间戳：使用当前时间
            import time
            header = ''
            timestamp = time.time()
            result = (header, timestamp) + values
            
            return result
        except Exception as e:
            print(f"Justfloat数据解析失败: {e}, 原始数据: {data}")
            # 返回错误标识，用于触发数据格式不匹配状态
            import time
            return ('FORMAT_ERROR', time.time())
    
    def _parse_text_data(self, text: str) -> Tuple[float, ...]:
        """解析文本格式数据
        
        格式: "数据校验头,时间戳,通道一=数值,通道二=数值"
        
        Args:
            text: 文本数据
        
        Returns:
            解析后的数据元组 (数据校验头, 时间戳, 通道1值, 通道2值, ...)
        """
        try:
            self.last_raw_text = text
            
            parts = text.split(',')
            if not parts:
                return tuple()
            
            header = parts[0].strip()
            timestamp = float(parts[1].strip())
            values = [header, timestamp]
            
            for part in parts[2:]:
                if '=' in part:
                    channel_part, value_part = part.split('=', 1)
                    value = float(value_part)
                    values.append(value)
            
            return tuple(values)
        except Exception as e:
            print(f"串口文本数据解析失败: {e}, 文本: {text}")
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
    
    def disconnect(self) -> None:
        """断开串口连接"""
        if self.serial:
            self.serial.close()
            self.serial = None
        self.is_connected = False
        print("串口数据源已断开")
    
    def set_baudrate(self, baudrate: int) -> None:
        """设置波特率
        
        Args:
            baudrate: 波特率
        """
        self.baudrate = baudrate
        if self.serial:
            self.serial.baudrate = baudrate
    
    def set_port(self, port: str) -> None:
        """设置端口
        
        Args:
            port: 串口名称
        """
        self.port = port
    
    def set_protocol(self, protocol: str) -> None:
        """设置协议类型
        
        Args:
            protocol: 协议类型，'text'或'binary'
        """
        self.protocol = protocol
        print(f"协议类型已设置为: {protocol}")
    
    def set_data_header(self, header: str) -> None:
        """设置数据校验头
        
        Args:
            header: 数据校验头
        """
        self.data_header = header
        print(f"数据校验头已设置为: {header}")
    
    def set_raw_data_callback(self, callback) -> None:
        """设置原始数据回调函数
        
        Args:
            callback: 回调函数，接收原始字节数据
        """
        self.raw_data_callback = callback
    
    def get_protocol(self) -> str:
        """获取当前协议类型
        
        Returns:
            协议类型：'text', 'justfloat', 'rawdata'
        """
        return self.protocol