"""
文件数据源实现

支持从 .log / .bin / .csv 文件回放数据，协议与串口保持一致：
- text
- csv（DataSaver导出格式）
- justfloat（with_timestamp / without_timestamp）
- rawdata
"""

import os
import time
import csv
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
        self._csv_reader = None
        self._csv_file_obj = None
        self.csv_channel_names = []

    def connect(self) -> bool:
        """连接文件数据源（打开文件）"""
        try:
            if not os.path.isfile(self.file_path):
                print(f"文件不存在: {self.file_path}")
                self.is_connected = False
                return False

            if self.protocol == 'csv':
                self._csv_file_obj = open(self.file_path, 'r', newline='', encoding='utf-8-sig')
                self._csv_reader = csv.reader(self._csv_file_obj)
                self._fh = None
            else:
                self._fh = open(self.file_path, 'rb')
            self.is_connected = True

            self.buffer.clear()
            self.text_buffer.clear()
            self.parsed_frames.clear()
            self.csv_channel_names = []
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
        if self._csv_file_obj:
            self._csv_file_obj.close()
            self._csv_file_obj = None
        self._csv_reader = None

    def _read_csv_data(self) -> Optional[Tuple[float, ...]]:
        """读取CSV数据（兼容DataSaver导出的格式）。"""
        if not self._csv_reader:
            return None

        while True:
            try:
                row = next(self._csv_reader)
            except StopIteration:
                # EOF时保持连接，等待追加新行
                return None
            except Exception:
                return ('FORMAT_ERROR', time.time())

            if not row:
                continue

            row = [cell.strip() for cell in row]
            if not any(row):
                continue

            # 首行必须是DataSaver导出的表头：时间戳 + 通道名...
            if not self.csv_channel_names:
                header0 = row[0]
                if header0 not in ('时间戳', 'timestamp', 'Timestamp'):
                    return ('FORMAT_ERROR', time.time())

                channel_names = [name for name in row[1:] if name]
                if not channel_names:
                    return ('FORMAT_ERROR', time.time())

                self.csv_channel_names = channel_names
                continue

            expected_len = 1 + len(self.csv_channel_names)
            if len(row) < expected_len:
                return ('FORMAT_ERROR', time.time())

            try:
                # DataSaver导出的CSV时间戳单位为毫秒；
                # FileDataSource对外需返回“秒”，由Manager统一转回毫秒。
                timestamp_ms = float(row[0])
                timestamp = timestamp_ms / 1000.0
                values = [float(row[i + 1]) for i in range(len(self.csv_channel_names))]
            except (TypeError, ValueError):
                return ('FORMAT_ERROR', time.time())

            if self.raw_data_callback:
                self.raw_data_callback((','.join(row) + '\n').encode('utf-8', errors='ignore'))

            self.parsed_frame_count += 1
            return ('', timestamp, *values)

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
        if not self.is_connected:
            return None

        if self.protocol == 'csv':
            parsed = self._read_csv_data()
            if parsed is not None:
                return parsed
            return None

        if not self._fh:
            return None

        if self.parsed_frames:
            return self.parsed_frames.popleft()

        try:
            chunk = self._fh.read(self.chunk_size)

            if not chunk:
                # 文件尾随读取：到达EOF不主动断开，等待外部追加数据。
                # 不清空text_buffer，避免半包行在下一次追加后无法拼接。
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
            self._close_file()
            self.is_connected = False
            return None

    def disconnect(self) -> None:
        """断开文件数据源"""
        self._close_file()
        self.is_connected = False
        self.buffer.clear()
        self.text_buffer.clear()
        self.parsed_frames.clear()
        self.csv_channel_names = []
        print("文件数据源已断开")

    def send_data(self, data: bytes) -> bool:
        """文件回放源不支持发送。"""
        return False

    def get_channel_names(self) -> list:
        """获取通道名（CSV协议使用表头通道名）。"""
        if self.protocol == 'csv':
            return list(self.csv_channel_names)
        return super().get_channel_names()
