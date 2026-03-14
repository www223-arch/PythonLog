"""
数据源管理器

管理多个数据源，提供统一的数据访问接口。
"""

import time
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
        self.channel_set = set()
        self.channel_data = {}  # 存储各通道的数据
        self.timestamps = []  # 存储时间戳
        self.data_header = 'DATA'  # 数据校验头，默认'DATA'
        self.header_enabled = True  # 是否启用数据校验头验证
        self.header_mismatch_count = 0  # 校验头不匹配计数器
        self.last_valid_data_time = None  # 最后一次有效数据的时间
        self.channel_name_mapping = {}  # 通道名映射字典 {原始名: 新名}
        self.log_enabled = False  # 日志开关，默认关闭以提高性能

    def _frame_to_legacy_dict(self, frame: Dict[str, Any]) -> Dict[str, float]:
        """将统一帧转换为旧版扁平字典，便于兼容旧调用路径。"""
        data_dict = {
            'header': frame.get('header', ''),
            'timestamp': frame.get('timestamp', 0.0)
        }

        if frame.get('meta', {}).get('format_error'):
            data_dict['format_error'] = True
            return data_dict

        channels = frame.get('channels', {})
        if channels:
            data_dict.update(channels)

        return data_dict

    def _is_format_sensitive_protocol(self, protocol: str) -> bool:
        """判断当前协议是否需要格式校验失败触发format_error状态。"""
        if protocol == 'rawdata':
            return False
        # 文本协议及带结构要求的协议都属于格式敏感。
        return True

 
    
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
                self.channel_set.clear()
                self.channel_data.clear()
                self.timestamps.clear()
                self.channel_name_mapping.clear()  # 清空通道名映射
                print(f"数据源已切换到: {source}")
            
            return success
        except Exception as e:
            print(f"设置数据源失败: {e}")
            return False
    
    def read_frame(self) -> Optional[Dict[str, Any]]:
        """读取统一帧数据

        Returns:
            统一帧结构：
            {
                'header': str,
                'timestamp': float(ms),
                'channels': {name: value, ...},
                'meta': {'format_error': bool, 'protocol': str}
            }
            无数据时返回None。
        """
        if not self.current_source:
            return None

        data = self.current_source.read_data()
        if data is None:
            return None

        protocol = ''
        if hasattr(self.current_source, 'get_protocol'):
            protocol = self.current_source.get_protocol()

        # 空元组通常表示收到数据但解析失败（非超时）；对格式敏感协议上报format_error。
        if len(data) == 0:
            if self._is_format_sensitive_protocol(protocol):
                self.header_mismatch_count += 1
                timestamp_ms = time.time() * 1000.0
                return {
                    'header': 'FORMAT_ERROR',
                    'timestamp': timestamp_ms,
                    'channels': {},
                    'meta': {'format_error': True, 'protocol': protocol}
                }
            return None

        # 解析基础字段
        header = str(data[0])
        timestamp_seconds = float(data[1])
        timestamp_ms = timestamp_seconds * 1000.0

        # 更新最后接收数据时间（包括校验错误）
        self.last_data_time = timestamp_ms
        self.last_valid_data_time = timestamp_ms

        # Rawdata模式：仅透传基础信息
        if protocol == 'rawdata':
            return {
                'header': header,
                'timestamp': timestamp_ms,
                'channels': {},
                'meta': {'format_error': False, 'protocol': protocol}
            }

        # 数据格式错误
        if header == 'FORMAT_ERROR':
            self.header_mismatch_count += 1
            if self.log_enabled:
                print(f"[警告] 数据格式不匹配 - 丢弃数据")
            return {
                'header': header,
                'timestamp': timestamp_ms,
                'channels': {},
                'meta': {'format_error': True, 'protocol': protocol}
            }

        # 没有通道数据（仅更新状态）
        if len(data) < 3:
            return {
                'header': header,
                'timestamp': timestamp_ms,
                'channels': {},
                'meta': {'format_error': False, 'protocol': protocol}
            }

        # 校验头验证（仅在header非空时）
        if self.header_enabled and header != '' and header != self.data_header:
            self.header_mismatch_count += 1
            if self.log_enabled:
                print(f"[警告] 数据校验头不匹配: 期望'{self.data_header}', 收到'{header}' - 丢弃数据")
            return {
                'header': header,
                'timestamp': timestamp_ms,
                'channels': {},
                'meta': {'format_error': True, 'protocol': protocol}
            }

        self.header_mismatch_count = 0
        self.last_valid_data_time = timestamp_ms

        # 通道名来源：优先使用数据源提供的通道名，否则按channel{i}
        channel_names = []
        if hasattr(self.current_source, 'get_channel_names'):
            channel_names = self.current_source.get_channel_names()

        channels = {}
        for i, value in enumerate(data[2:]):
            if i < len(channel_names):
                original_channel_name = channel_names[i]
            else:
                original_channel_name = f'channel{i+1}'

            display_channel_name = self.get_display_channel_name(original_channel_name)
            channels[display_channel_name] = float(value)

            # 自动添加新通道（使用映射后的名称）
            if display_channel_name not in self.channel_set and original_channel_name not in self.channel_set:
                self.channels.append(display_channel_name)
                self.channel_set.add(display_channel_name)
                if self.log_enabled:
                    print(f"[read_frame] 检测到新通道: {display_channel_name} (原始名: {original_channel_name})")

        frame = {
            'header': header,
            'timestamp': timestamp_ms,
            'channels': channels,
            'meta': {'format_error': False, 'protocol': protocol}
        }

        # 与旧read_data行为保持一致：仅在有效通道数据帧时写入缓冲和CSV
        legacy_data_dict = self._frame_to_legacy_dict(frame)
        self.data_buffer.append(legacy_data_dict)

        if len(self.data_buffer) > self.max_buffer_size:
            self.data_buffer = self.data_buffer[-self.max_buffer_size:]

        if self.data_saver.is_active():
            self.data_saver.save_data(legacy_data_dict)

        return frame

    def read_data(self) -> Optional[Dict[str, float]]:
        """读取数据（兼容旧接口）

        Returns:
            读取到的数据字典，如果没有数据源返回None
            格式: {'header': str, 'timestamp': float, '通道一': float, '通道二': float, ...}
        """
        frame = self.read_frame()
        if frame is None:
            return None

        return self._frame_to_legacy_dict(frame)
    
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
        self.channel_set.clear()
        self.channel_data.clear()
        self.timestamps.clear()
        # 清空通道名映射
        self.channel_name_mapping.clear()
    
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
    
    def get_header_mismatch_count(self) -> int:
        """获取校验头不匹配的次数
        
        Returns:
            校验头不匹配的次数
        """
        return self.header_mismatch_count
    
    def reset_header_mismatch_count(self) -> None:
        """重置校验头不匹配计数器"""
        self.header_mismatch_count = 0
    
    def get_delta_t(self) -> Optional[float]:
        """获取当前数据源的Δt值（仅用于Justfloat无时间戳模式）
        
        Returns:
            Δt值（ms），如果不是Justfloat无时间戳模式，返回None
        """
        source = self.current_source
        if source is None:
            return None

        protocol = None
        if hasattr(source, 'get_protocol'):
            try:
                protocol = source.get_protocol()
            except Exception:
                return None
        elif hasattr(source, 'protocol'):
            protocol = getattr(source, 'protocol', None)

        if protocol != 'justfloat':
            return None

        if not hasattr(source, 'justfloat_mode'):
            return None

        if getattr(source, 'justfloat_mode', None) != 'without_timestamp':
            return None

        delta_t = getattr(source, 'delta_t', None)
        if delta_t is None:
            return None

        try:
            return float(delta_t)
        except (TypeError, ValueError):
            return None
    
    def set_channel_name_mapping(self, old_name: str, new_name: str) -> None:
        """设置通道名映射
        
        Args:
            old_name: 原始通道名
            new_name: 新通道名
        """
        old_name = old_name.strip()
        new_name = new_name.strip()

        if not old_name or not new_name:
            return

        if old_name == new_name:
            return

        # 将所有当前映射到old_name的键统一更新为new_name，支持多次重命名。
        # 例如: channel1->111 后再 111->222，则 channel1 也应直接映射到 222。
        alias_keys = [
            key for key, mapped_name in self.channel_name_mapping.items()
            if mapped_name == old_name
        ]

        if not alias_keys:
            alias_keys = [old_name]

        for key in alias_keys:
            self.channel_name_mapping[key] = new_name

        # 记录显示名别名，吸收重命名瞬间队列中在途的旧显示名数据包。
        self.channel_name_mapping[old_name] = new_name

        # 同步更新缓存中的通道列表与集合
        self._replace_channel_in_cache(old_name, new_name)

        print(f"通道名映射已设置: {old_name} -> {new_name}")

    def _replace_channel_in_cache(self, old_name: str, new_name: str) -> None:
        """同步替换通道缓存中的名称并保持唯一性"""
        if old_name in self.channels:
            idx = self.channels.index(old_name)
            self.channels[idx] = new_name

        # 去重并保持顺序
        dedup_channels = []
        seen = set()
        for channel in self.channels:
            if channel not in seen:
                seen.add(channel)
                dedup_channels.append(channel)

        self.channels = dedup_channels
        self.channel_set = set(self.channels)
    
    def get_channel_name_mapping(self) -> dict:
        """获取通道名映射字典
        
        Returns:
            通道名映射字典
        """
        return self.channel_name_mapping.copy()
    
    def clear_channel_name_mapping(self) -> None:
        """清空通道名映射"""
        self.channel_name_mapping.clear()
        print("通道名映射已清空")
    
    def get_display_channel_name(self, original_name: str) -> str:
        """获取显示用的通道名
        
        Args:
            original_name: 原始通道名
        
        Returns:
            显示用的通道名（如果有映射则返回新名，否则返回原名）
        """
        current_name = original_name
        visited = set()

        # 解析链式映射，直到收敛到最终显示名。
        while current_name in self.channel_name_mapping and current_name not in visited:
            visited.add(current_name)
            current_name = self.channel_name_mapping[current_name]

        return current_name


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


def create_serial_source(port: str = 'COM1', baudrate: int = 115200, protocol: str = 'text', data_header: str = 'DATA', justfloat_mode: str = 'without_timestamp', delta_t: float = 1.0):
    """创建串口数据源
    
    Args:
        port: 串口名称
        baudrate: 波特率
        protocol: 协议类型，'text'为文本协议，'binary'为二进制协议
        data_header: 数据校验头，用于文本协议
        justfloat_mode: Justfloat模式，'without_timestamp'为无时间戳，'with_timestamp'为带时间戳
        delta_t: 数据点间隔（毫秒），仅用于无时间戳模式
    
    Returns:
        串口数据源对象
    """
    from .serial_source import SerialDataSource
    return SerialDataSource(port, baudrate, protocol, data_header, justfloat_mode, delta_t)