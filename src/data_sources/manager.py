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
        self.channel_set = set()
        self.channel_data = {}  # 存储各通道的数据
        self.timestamps = []  # 存储时间戳
        self.data_header = 'DATA'  # 数据校验头，默认'DATA'
        self.header_enabled = True  # 是否启用数据校验头验证
        self.header_mismatch_count = 0  # 校验头不匹配计数器
        self.last_valid_data_time = None  # 最后一次有效数据的时间
        self.channel_name_mapping = {}  # 通道名映射字典 {原始名: 新名}
        self.log_enabled = False  # 日志开关，默认关闭以提高性能

 
    
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
            timestamp_seconds = float(data[1])
            # 将时间戳转换为ms（统一单位）
            timestamp_ms = timestamp_seconds * 1000.0
            
            # 更新最后接收数据的时间（包括校验头不匹配的数据）
            self.last_data_time = timestamp_ms
            # 更新最后有效数据的时间（用于计算采样率）
            self.last_valid_data_time = timestamp_ms
            
            # 检查是否是Rawdata模式
            if hasattr(self.current_source, 'get_protocol'):
                protocol = self.current_source.get_protocol()
                if protocol == 'rawdata':
                    # Rawdata模式，直接返回数据，不进行任何校验
                    data_dict = {'header': header, 'timestamp': timestamp_ms}
                    return data_dict
            
            # 检查是否是数据格式错误标识（先检查这个）
            if header == 'FORMAT_ERROR':
                self.header_mismatch_count += 1
                if self.log_enabled:
                    print(f"[警告] 数据格式不匹配 - 丢弃数据")
                # 返回特殊标识，表示有格式错误
                return {'format_error': True, 'header': header, 'timestamp': timestamp_ms}
            
            # 检查是否有通道数据（Rawdata模式可能没有）
            if len(data) < 3:
                # 没有通道数据，返回空数据字典以更新状态
                data_dict = {'header': header, 'timestamp': timestamp_ms}
                return data_dict
            
            # 验证数据校验头（只在数据校验头不为空时才验证）
            if self.header_enabled and header != '' and header != self.data_header:
                self.header_mismatch_count += 1
                if self.log_enabled:
                    print(f"[警告] 数据校验头不匹配: 期望'{self.data_header}', 收到'{header}' - 丢弃数据")
                return None
            
            # 重置校验头不匹配计数器
            self.header_mismatch_count = 0
            self.last_valid_data_time = timestamp_ms
            
            # 构建数据字典
            data_dict = {'header': header, 'timestamp': timestamp_ms}
            
            # 从UDP数据源获取通道名称
            if hasattr(self.current_source, 'get_channel_names'):
                channel_names = self.current_source.get_channel_names()
                
                # 使用提取到的通道名称
                for i, value in enumerate(data[2:]):
                    if i < len(channel_names):
                        original_channel_name = channel_names[i]
                    else:
                        original_channel_name = f'channel{i+1}'
                    # 应用通道名映射
                    display_channel_name = self.get_display_channel_name(original_channel_name)
                    data_dict[display_channel_name] = float(value)
                    
                    # 自动添加新通道（使用映射后的名称）
                    # 检查：映射后的通道名是否已存在，或者原始通道名是否已存在
                    if display_channel_name not in self.channel_set and original_channel_name not in self.channel_set:
                        self.channels.append(display_channel_name)
                        self.channel_set.add(display_channel_name)
                        if self.log_enabled:
                            print(f"[read_data] 检测到新通道: {display_channel_name} (原始名: {original_channel_name})")
            else:
                # 如果没有get_channel_names方法，使用默认通道名称（Justfloat模式）
                for i, value in enumerate(data[2:], 1):
                    original_channel_name = f'channel{i}'
                    # 应用通道名映射
                    display_channel_name = self.get_display_channel_name(original_channel_name)
                    data_dict[display_channel_name] = float(value)
                    
                    # 自动添加新通道（使用映射后的名称）
                    # 检查：映射后的通道名是否已存在，或者原始通道名是否已存在
                    if display_channel_name not in self.channel_set and original_channel_name not in self.channel_set:
                        self.channels.append(display_channel_name)
                        self.channel_set.add(display_channel_name)
                        if self.log_enabled:
                            print(f"[read_data] 检测到新通道: {display_channel_name} (原始名: {original_channel_name})")
            
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
        print(f"[get_delta_t] 开始检查...")
        print(f"[get_delta_t] current_source: {self.current_source}")
        
        if self.current_source:
            print(f"[get_delta_t] current_source.protocol: {self.current_source.protocol}")
            print(f"[get_delta_t] hasattr(current_source, 'protocol'): {hasattr(self.current_source, 'protocol')}")
            print(f"[get_delta_t] hasattr(current_source, 'justfloat_mode'): {hasattr(self.current_source, 'justfloat_mode')}")
            
            if hasattr(self.current_source, 'protocol'):
                if self.current_source.protocol == 'justfloat':
                    print(f"[get_delta_t] protocol == 'justfloat'，检查justfloat_mode...")
                    if hasattr(self.current_source, 'justfloat_mode'):
                        print(f"[get_delta_t] justfloat_mode: {self.current_source.justfloat_mode}")
                        if self.current_source.justfloat_mode == 'without_timestamp':
                            print(f"[get_delta_t] justfloat_mode == 'without_timestamp'，返回delta_t: {self.current_source.delta_t}")
                            return self.current_source.delta_t
                        else:
                            print(f"[get_delta_t] justfloat_mode不是'without_timestamp'，返回None")
                    else:
                        print(f"[get_delta_t] 没有justfloat_mode属性，返回None")
                else:
                    print(f"[get_delta_t] protocol不是'justfloat'，返回None")
            else:
                print(f"[get_delta_t] 没有protocol属性，返回None")
        else:
            print(f"[get_delta_t] current_source为None，返回None")
        
        return None
    
    def set_channel_name_mapping(self, old_name: str, new_name: str) -> None:
        """设置通道名映射
        
        Args:
            old_name: 原始通道名
            new_name: 新通道名
        """
        self.channel_name_mapping[old_name] = new_name
        print(f"通道名映射已设置: {old_name} -> {new_name}")
    
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
        return self.channel_name_mapping.get(original_name, original_name)


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