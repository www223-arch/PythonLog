"""
串口数据源实现

支持串口协议的数据接收，为上位机提供实时数据。
支持文本协议和二进制协议。
"""

import time
import struct
from collections import deque
from typing import Optional, Tuple
from .base import DataSource


class SerialDataSource(DataSource):
    """串口数据源
    
    通过串口协议接收数据，支持自定义端口和波特率。
    支持文本协议和二进制协议。
    """
    
    def __init__(self, port: str = 'COM1', baudrate: int = 115200, protocol: str = 'text', data_header: str = 'DATA', justfloat_mode: str = 'without_timestamp', delta_t: float = 1.0):
        """初始化串口数据源
        
        Args:
            port: 串口名称，默认为'COM1'
            baudrate: 波特率，默认为115200
            protocol: 协议类型，'text'为文本协议，'binary'为二进制协议
            data_header: 数据校验头，用于文本协议
            justfloat_mode: Justfloat模式，'without_timestamp'为无时间戳，'with_timestamp'为带时间戳
            delta_t: 数据点间隔（毫秒），仅用于无时间戳模式
        """
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.protocol = protocol  # 'text' 或 'binary'
        self.data_header = data_header  # 数据校验头
        self.justfloat_mode = justfloat_mode  # Justfloat模式
        self.delta_t = delta_t  # 数据点间隔（毫秒）
        self.serial = None
        self.last_raw_text = None  # 存储原始文本，用于提取通道名称
        self.buffer = bytearray()  # 二进制数据缓冲区
        self.text_buffer = bytearray()  # 文本协议缓冲区
        self.parsed_frames = deque()  # 已解析待消费的帧队列
        self.frame_tail = bytes([0x00, 0x00, 0x80, 0x7f])  # 二进制帧尾标识
        self.raw_data_callback = None  # 原始数据回调函数
        self.data_point_counter = 0  # 数据点计数器（用于无时间戳模式）
        self.start_time = None  # 起始时间（用于无时间戳模式）
        self.bytes_read_count = 0  # 累计读取字节数
        self.parsed_frame_count = 0  # 累计解析帧数
        self.parse_time_ns_total = 0  # 累计解析耗时（ns）
    
    def reset_data_point_counter(self) -> None:
        """重置数据点计数器（用于改变Δt后）
        """
        self.data_point_counter = 0
        self.start_time = None
        print(f"[reset_data_point_counter] 数据点计数器已重置")
    
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
                timeout=0  # 非阻塞，降低高频数据接收等待
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

        # 优先返回已经解析好的帧，避免读取频率限制吞吐
        if self.parsed_frames:
            return self.parsed_frames.popleft()
        
        try:
            if self.serial.in_waiting > 0:
                if self.protocol == 'text':
                    # 文本协议：批量读取并解析完整行
                    data = self.serial.read(self.serial.in_waiting)
                    self.bytes_read_count += len(data)
                    # 调用原始数据回调
                    if self.raw_data_callback:
                        self.raw_data_callback(data)
                    self._parse_text_buffer_data(data)
                    if self.parsed_frames:
                        return self.parsed_frames.popleft()
                    return None
                elif self.protocol == 'justfloat':
                    # Justfloat协议：纯浮点数，无数据校验头和时间戳
                    data = self.serial.read(self.serial.in_waiting)
                    self.bytes_read_count += len(data)
                    # 调用原始数据回调
                    if self.raw_data_callback:
                        self.raw_data_callback(data)
                    self._parse_justfloat_data(data)
                    if self.parsed_frames:
                        return self.parsed_frames.popleft()
                    return None
                else:  # rawdata
                    # Rawdata协议：原始数据，直接显示
                    data = self.serial.read(self.serial.in_waiting)
                    self.bytes_read_count += len(data)
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
            # 调用断开回调
            if self.disconnect_callback:
                self.disconnect_callback()
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

    def _parse_text_buffer_data(self, data: bytes) -> None:
        """批量解析文本协议缓冲区，提取完整行并入队"""
        if not data:
            return

        start_ns = time.perf_counter_ns()
        self.text_buffer.extend(data)
        parse_error_detected = False

        while True:
            newline_pos = self.text_buffer.find(b'\n')
            if newline_pos == -1:
                break

            line_bytes = self.text_buffer[:newline_pos]
            # 丢弃当前行（包含换行符）
            self.text_buffer = self.text_buffer[newline_pos + 1:]

            if not line_bytes:
                continue

            # 去掉可能存在的回车符
            if line_bytes.endswith(b'\r'):
                line_bytes = line_bytes[:-1]

            try:
                text_data = line_bytes.decode('utf-8', errors='ignore').strip()
                if not text_data:
                    continue
                parsed = self._parse_text_data(text_data)
                if parsed and len(parsed) > 0:
                    self.parsed_frames.append(parsed)
                    self.parsed_frame_count += 1
                else:
                    parse_error_detected = True
            except Exception:
                parse_error_detected = True
                continue

        # 对文本协议：若本批出现解析失败且未产出有效帧，补一个FORMAT_ERROR帧。
        # 这样上层FSM能够进入“数据格式不匹配”而不是一直停留在“等待数据”。
        if parse_error_detected and not self.parsed_frames:
            self.parsed_frames.append(('FORMAT_ERROR', time.time()))

        self.parse_time_ns_total += time.perf_counter_ns() - start_ns
    
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
        
        Justfloat协议格式（无时间戳）：
        struct Frame {
            float fdata[CH_COUNT];
            unsigned char tail[4]{0x00, 0x00, 0x80, 0x7f};
        };
        
        Justfloat协议格式（带时间戳）：
        struct Frame {
            float fdata[CH_COUNT];
            float time;
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

            while True:
                # 查找帧尾标识
                tail_pos = self.buffer.find(self.frame_tail)
                if tail_pos == -1:
                    break

                # 帧尾位置 + 4字节帧尾 = 总长度
                frame_length = tail_pos + 4
                if frame_length < 4:
                    self.buffer = self.buffer[frame_length:]
                    continue

                # 提取帧数据（不包括帧尾）
                frame_data = self.buffer[:tail_pos]
                # 移除已消费帧
                self.buffer = self.buffer[frame_length:]

                # 每个浮点数4字节
                num_floats = len(frame_data) // 4
                if num_floats == 0:
                    continue

                values = struct.unpack(f'{num_floats}f', frame_data)
                header = ''

                if self.justfloat_mode == 'with_timestamp':
                    # 带时间戳模式：最后一个浮点数是时间戳（单位：ms）
                    if num_floats < 2:
                        continue
                    timestamp_ms = values[-1]
                    timestamp = timestamp_ms / 1000.0
                    values = values[:-1]
                else:
                    # 无时间戳模式：使用Δt计算时间戳
                    timestamp_ms = self.data_point_counter * self.delta_t
                    timestamp = timestamp_ms / 1000.0
                    self.data_point_counter += 1

                result = (header, timestamp) + values
                self.parsed_frames.append(result)
                self.parsed_frame_count += 1

            if self.parsed_frames:
                return self.parsed_frames[0]
            return None
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
        self.buffer.clear()
        self.text_buffer.clear()
        self.parsed_frames.clear()
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

    def send_data(self, data: bytes) -> bool:
        """发送数据到串口。"""
        if not self.is_connected or not self.serial:
            return False

        try:
            self.serial.write(data)
            return True
        except Exception as e:
            print(f"串口发送失败: {e}")
            return False