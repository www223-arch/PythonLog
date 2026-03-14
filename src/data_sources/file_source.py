"""
文件数据源实现

支持从 .log / .bin 文件回放数据，协议与串口保持一致：
- text
- justfloat（with_timestamp / without_timestamp）
- rawdata
"""

import os
import time
from typing import Optional, Tuple

from .serial_source import SerialDataSource


class FileDataSource(SerialDataSource):
    """文件数据源

    复用串口协议解析逻辑，通过分块读取文件来保持与实时链路一致的上层行为。
    """

    def __init__(
        self,
        file_path: str,
        protocol: str = 'text',
        data_header: str = 'DATA',
        justfloat_mode: str = 'without_timestamp',
        delta_t: float = 1.0,
        chunk_size: int = 4096,
    ):
        super().__init__(
            port='FILE',
            baudrate=0,
            protocol=protocol,
            data_header=data_header,
            justfloat_mode=justfloat_mode,
            delta_t=delta_t,
        )
        self.file_path = file_path
        self.chunk_size = max(128, int(chunk_size))
        self._fh = None

    def connect(self) -> bool:
        """连接文件数据源（打开文件）"""
        try:
            if not os.path.isfile(self.file_path):
                print(f"文件不存在: {self.file_path}")
                self.is_connected = False
                return False

            self._fh = open(self.file_path, 'rb')
            self.is_connected = True

            self.buffer.clear()
            self.text_buffer.clear()
            self.parsed_frames.clear()
            self.data_point_counter = 0
            self.bytes_read_count = 0
            self.parsed_frame_count = 0
            self.parse_time_ns_total = 0

            print(f"文件数据源已连接: {self.file_path}")
            return True
        except Exception as e:
            print(f"文件连接失败: {e}")
            self.is_connected = False
            return False

    def _close_file(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None

    def _mark_eof(self) -> None:
        self.is_connected = False
        self._close_file()

    def _flush_text_tail_on_eof(self) -> None:
        """EOF时处理最后一行无换行的文本数据。"""
        if not self.text_buffer:
            return

        line_bytes = bytes(self.text_buffer).rstrip(b'\r')
        self.text_buffer.clear()
        if not line_bytes:
            return

        try:
            text_data = line_bytes.decode('utf-8', errors='ignore').strip()
            if text_data:
                parsed = self._parse_text_data(text_data)
                if parsed and len(parsed) > 0:
                    self.parsed_frames.append(parsed)
                    self.parsed_frame_count += 1
                else:
                    self.parsed_frames.append(('FORMAT_ERROR', time.time()))
        except Exception:
            self.parsed_frames.append(('FORMAT_ERROR', time.time()))

    def read_data(self) -> Optional[Tuple[float, ...]]:
        """读取文件数据，保持与串口读接口一致。"""
        if not self.is_connected or not self._fh:
            return None

        if self.parsed_frames:
            return self.parsed_frames.popleft()

        try:
            chunk = self._fh.read(self.chunk_size)

            if not chunk:
                if self.protocol == 'text':
                    self._flush_text_tail_on_eof()
                    if self.parsed_frames:
                        return self.parsed_frames.popleft()
                self._mark_eof()
                return None

            self.bytes_read_count += len(chunk)
            if self.raw_data_callback:
                self.raw_data_callback(chunk)

            if self.protocol == 'text':
                self._parse_text_buffer_data(chunk)
            elif self.protocol == 'justfloat':
                self._parse_justfloat_data(chunk)
            else:  # rawdata
                return ('', time.time())

            if self.parsed_frames:
                return self.parsed_frames.popleft()

            return None
        except Exception as e:
            print(f"读取文件数据失败: {e}")
            self._mark_eof()
            return None

    def disconnect(self) -> None:
        """断开文件数据源"""
        self._close_file()
        self.is_connected = False
        self.buffer.clear()
        self.text_buffer.clear()
        self.parsed_frames.clear()
        print("文件数据源已断开")

    def send_data(self, data: bytes) -> bool:
        """文件回放源不支持发送。"""
        return False
