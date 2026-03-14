"""
TCP数据源实现

协议解析与UDP一致：优先文本解析，失败后尝试二进制浮点解析。
"""

import socket
import struct
from typing import Optional, Tuple

from .base import DataSource


class TCPDataSource(DataSource):
    """TCP数据源（服务端监听模式）"""

    def __init__(self, host: str = '0.0.0.0', port: int = 9999):
        super().__init__()
        self.host = host
        self.port = port
        self.server_socket = None
        self.client_socket = None
        self.client_addr = None
        self.buffer_size = 4096
        self.last_raw_text = None
        self.raw_data_callback = None

    def connect(self) -> bool:
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(1)
            self.server_socket.settimeout(0.001)
            self.is_connected = True
            print(f"TCP数据源已监听: {self.host}:{self.port}")
            return True
        except Exception as e:
            print(f"TCP连接失败: {e}")
            self.is_connected = False
            return False

    def _ensure_client(self) -> bool:
        if self.client_socket is not None:
            return True

        if self.server_socket is None:
            return False

        try:
            client_socket, client_addr = self.server_socket.accept()
            client_socket.settimeout(0.001)
            self.client_socket = client_socket
            self.client_addr = client_addr
            print(f"TCP客户端已连接: {client_addr}")
            return True
        except socket.timeout:
            return False
        except Exception as e:
            print(f"TCP接受客户端失败: {e}")
            return False

    def _close_client(self) -> None:
        if self.client_socket:
            try:
                self.client_socket.close()
            except Exception:
                pass
            self.client_socket = None
            self.client_addr = None

    def read_data(self) -> Optional[Tuple[float, ...]]:
        if not self.is_connected:
            return None

        if not self._ensure_client():
            return None

        try:
            data = self.client_socket.recv(self.buffer_size)
            if not data:
                self._close_client()
                return None

            if self.raw_data_callback:
                self.raw_data_callback(data)

            return self._parse_data(data)
        except socket.timeout:
            return None
        except Exception as e:
            print(f"读取TCP数据失败: {e}")
            self._close_client()
            return None

    def _parse_data(self, data: bytes) -> Tuple[float, ...]:
        try:
            text_data = data.decode('utf-8').strip()
            return self._parse_text_data(text_data)
        except UnicodeDecodeError:
            return self._parse_binary_data(data)
        except Exception as e:
            print(f"TCP数据解析失败: {e}, 原始数据: {data}")
            return tuple()

    def _parse_text_data(self, text: str) -> Tuple[float, ...]:
        try:
            self.last_raw_text = text
            parts = text.split(',')
            if len(parts) < 2:
                return tuple()

            header = parts[0].strip()
            timestamp = float(parts[1].strip())
            values = [header, timestamp]

            for part in parts[2:]:
                if '=' in part:
                    _, value_part = part.split('=', 1)
                    values.append(float(value_part))

            return tuple(values)
        except Exception as e:
            print(f"TCP文本数据解析失败: {e}, 文本: {text}")
            return tuple()

    def get_channel_names(self) -> list:
        if not self.last_raw_text:
            return []

        try:
            parts = self.last_raw_text.split(',')
            channel_names = []
            for part in parts[2:]:
                if '=' in part:
                    channel_part, _ = part.split('=', 1)
                    channel_name = channel_part.strip()
                    if channel_name and channel_name not in channel_names:
                        channel_names.append(channel_name)
            return channel_names
        except Exception as e:
            print(f"TCP提取通道名称失败: {e}")
            return []

    def _parse_binary_data(self, data: bytes) -> Tuple[float, ...]:
        try:
            num_floats = len(data) // 4
            if num_floats <= 0:
                return tuple()
            values = struct.unpack(f'{num_floats}f', data[:num_floats * 4])
            return values
        except struct.error:
            print(f"TCP二进制数据解析失败，原始数据: {data}")
            return tuple()

    def send_data(self, data: bytes) -> bool:
        if not self.is_connected or self.client_socket is None:
            return False

        try:
            self.client_socket.sendall(data)
            return True
        except Exception as e:
            print(f"TCP发送失败: {e}")
            self._close_client()
            return False

    def disconnect(self) -> None:
        self._close_client()
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
            self.server_socket = None
        self.is_connected = False
        print("TCP数据源已断开")

    def set_raw_data_callback(self, callback) -> None:
        self.raw_data_callback = callback
