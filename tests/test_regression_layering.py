import os
import sys
import tempfile
import unittest
import struct

# 允许直接从仓库根目录运行: python -m unittest
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.data_sources.base import DataSource
from src.data_sources.manager import DataSourceManager, create_file_source, create_tcp_source
from src.data_sources.serial_source import SerialDataSource
from src.data_sources.tcp_source import TCPDataSource


class FakeSource(DataSource):
    def __init__(self, protocol='text', packets=None, channel_names=None):
        super().__init__()
        self._protocol = protocol
        self._packets = list(packets or [])
        self._channel_names = list(channel_names or [])

    def connect(self) -> bool:
        self.is_connected = True
        return True

    def read_data(self):
        if not self._packets:
            return None
        return self._packets.pop(0)

    def disconnect(self) -> None:
        self.is_connected = False

    def get_protocol(self):
        return self._protocol

    def get_channel_names(self):
        return list(self._channel_names)


class NoProtocolSource(DataSource):
    """模拟不提供protocol/get_protocol能力的数据源（如UDP场景）。"""

    def connect(self) -> bool:
        self.is_connected = True
        return True

    def read_data(self):
        return None

    def disconnect(self) -> None:
        self.is_connected = False


class SendCapableSource(DataSource):
    def __init__(self):
        super().__init__()
        self.last_sent = None

    def connect(self) -> bool:
        self.is_connected = True
        return True

    def read_data(self):
        return None

    def disconnect(self) -> None:
        self.is_connected = False

    def send_data(self, data: bytes) -> bool:
        self.last_sent = data
        return True


class ManagerLayeringRegressionTests(unittest.TestCase):
    def test_udp_default_buffer_is_large_enough_for_matrix_frames(self):
        from src.data_sources.manager import create_udp_source

        src = create_udp_source('0.0.0.0', 8888)
        self.assertGreaterEqual(getattr(src, 'buffer_size', 0), 65535)

    def test_tcp_factory_returns_tcp_source(self):
        src = create_tcp_source('0.0.0.0', 9999)
        self.assertIsInstance(src, TCPDataSource)

    def test_manager_send_data_routes_to_current_source(self):
        manager = DataSourceManager()
        self.assertFalse(manager.send_data(b'hello'))

        src = SendCapableSource()
        self.assertTrue(manager.set_source(src))
        self.assertTrue(manager.send_data(b'ping'))
        self.assertEqual(src.last_sent, b'ping')

    def test_get_delta_t_is_safe_for_non_protocol_source(self):
        manager = DataSourceManager()
        src = NoProtocolSource()
        self.assertTrue(manager.set_source(src))

        self.assertIsNone(manager.get_delta_t())

    def test_serial_text_invalid_line_emits_format_error_frame(self):
        serial_source = SerialDataSource(protocol='text')
        serial_source._parse_text_buffer_data(b"this is invalid\n")

        self.assertTrue(serial_source.parsed_frames)
        frame = serial_source.parsed_frames.popleft()
        self.assertEqual(frame[0], 'FORMAT_ERROR')

    def test_header_mismatch_reports_format_error_frame(self):
        manager = DataSourceManager()
        manager.set_data_header('DATA')

        src = FakeSource(
            protocol='text',
            packets=[('BAD', 1.0, 1.23)],
            channel_names=['ch1']
        )
        self.assertTrue(manager.set_source(src))

        frame = manager.read_frame()
        self.assertIsNotNone(frame)
        self.assertTrue(frame.get('meta', {}).get('format_error'))
        self.assertGreater(manager.get_header_mismatch_count(), 0)

    def test_switch_source_resets_channel_and_mapping_state(self):
        manager = DataSourceManager()

        src1 = FakeSource(
            protocol='text',
            packets=[('DATA', 1.0, 1.1, 2.2)],
            channel_names=['a', 'b']
        )
        self.assertTrue(manager.set_source(src1))
        frame1 = manager.read_frame()
        self.assertIsNotNone(frame1)
        self.assertEqual(manager.get_channels(), ['a', 'b'])

        manager.set_channel_name_mapping('a', 'A')
        self.assertEqual(manager.get_display_channel_name('a'), 'A')

        src2 = FakeSource(
            protocol='text',
            packets=[('DATA', 2.0, 3.3)],
            channel_names=['x']
        )
        self.assertTrue(manager.set_source(src2))

        # 切源后应清空历史通道与映射
        self.assertEqual(manager.get_channels(), [])
        self.assertEqual(manager.get_channel_name_mapping(), {})

        frame2 = manager.read_frame()
        self.assertIsNotNone(frame2)
        self.assertEqual(manager.get_channels(), ['x'])

    def test_multi_step_rename_alias_chain(self):
        manager = DataSourceManager()
        src = FakeSource(
            protocol='justfloat',
            packets=[('', 1.0, 10.0)],
            channel_names=[]
        )
        self.assertTrue(manager.set_source(src))

        manager.read_frame()
        self.assertEqual(manager.get_channels(), ['channel1'])

        manager.set_channel_name_mapping('channel1', '111')
        manager.set_channel_name_mapping('111', '222')

        # 原始名和中间名都应收敛到最终显示名
        self.assertEqual(manager.get_display_channel_name('channel1'), '222')
        self.assertEqual(manager.get_display_channel_name('111'), '222')

    def test_read_frame_and_read_data_compat(self):
        manager = DataSourceManager()
        src = FakeSource(
            protocol='text',
            packets=[('DATA', 1.5, 5.0, 6.0), ('DATA', 1.6, 7.0, 8.0)],
            channel_names=['u', 'i']
        )
        self.assertTrue(manager.set_source(src))

        frame = manager.read_frame()
        self.assertIsNotNone(frame)
        self.assertIn('channels', frame)
        self.assertEqual(frame['channels']['u'], 5.0)

        legacy = manager.read_data()
        self.assertIsNotNone(legacy)
        self.assertIn('u', legacy)
        self.assertEqual(legacy['u'], 7.0)

    def test_csv_save_still_works_with_read_frame(self):
        manager = DataSourceManager()

        with tempfile.TemporaryDirectory() as tmp_dir:
            manager.set_save_path(tmp_dir)
            self.assertTrue(manager.start_saving())

            src = FakeSource(
                protocol='text',
                packets=[('DATA', 3.0, 1.0, 2.0)],
                channel_names=['v1', 'v2']
            )
            self.assertTrue(manager.set_source(src))

            frame = manager.read_frame()
            self.assertIsNotNone(frame)

            save_file = manager.get_save_file()
            self.assertIsNotNone(save_file)
            manager.stop_saving()
            self.assertTrue(os.path.exists(save_file))
            self.assertTrue(os.path.getsize(save_file) > 0)

    def test_file_text_source_replay_keeps_manager_contract(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, 'demo.log')
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write('DATA,1.0,a=1.5,b=2.5\n')
                f.write('DATA,2.0,a=3.5,b=4.5\n')

            manager = DataSourceManager()
            src = create_file_source(file_path, protocol='text', data_header='DATA')
            self.assertTrue(manager.set_source(src))

            frame1 = manager.read_frame()
            self.assertIsNotNone(frame1)
            self.assertEqual(frame1['channels']['a'], 1.5)
            self.assertEqual(frame1['channels']['b'], 2.5)

            frame2 = manager.read_frame()
            self.assertIsNotNone(frame2)
            self.assertEqual(frame2['channels']['a'], 3.5)

            # 到达EOF后保持连接，等待文件追加数据
            while manager.read_frame() is not None:
                pass
            self.assertTrue(src.is_connected)
            manager.disconnect()

    def test_file_justfloat_without_timestamp_replay(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, 'demo.bin')
            frame_tail = bytes([0x00, 0x00, 0x80, 0x7f])
            payload = struct.pack('2f', 1.0, 2.0) + frame_tail
            payload += struct.pack('2f', 3.0, 4.0) + frame_tail

            with open(file_path, 'wb') as f:
                f.write(payload)

            manager = DataSourceManager()
            src = create_file_source(
                file_path,
                protocol='justfloat',
                justfloat_mode='without_timestamp',
                delta_t=2.0,
            )
            self.assertTrue(manager.set_source(src))

            frame1 = manager.read_frame()
            frame2 = manager.read_frame()
            self.assertIsNotNone(frame1)
            self.assertIsNotNone(frame2)
            self.assertAlmostEqual(frame1['timestamp'], 0.0, places=6)
            self.assertAlmostEqual(frame2['timestamp'], 2.0, places=6)

            while manager.read_frame() is not None:
                pass
            self.assertTrue(src.is_connected)
            manager.disconnect()

    def test_file_text_source_can_tail_new_appended_lines(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, 'tail.log')
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write('DATA,0.0,a=1.0\n')

            manager = DataSourceManager()
            src = create_file_source(file_path, protocol='text', data_header='DATA')
            self.assertTrue(manager.set_source(src))

            frame1 = manager.read_frame()
            self.assertIsNotNone(frame1)
            self.assertEqual(frame1['channels']['a'], 1.0)

            # 到达EOF时无数据返回None，但保持连接
            self.assertIsNone(manager.read_frame())
            self.assertTrue(src.is_connected)

            # 追加新行后应可继续读取
            with open(file_path, 'a', encoding='utf-8') as f:
                f.write('DATA,0.02,a=2.5\n')
                f.flush()

            frame2 = None
            for _ in range(10):
                frame2 = manager.read_frame()
                if frame2 is not None:
                    break

            self.assertIsNotNone(frame2)
            self.assertEqual(frame2['channels']['a'], 2.5)
            manager.disconnect()

    def test_file_csv_source_replay_matches_export_schema(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, 'demo.csv')
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write('时间戳,ch1,ch2\n')
                f.write('1.0,3.5,4.5\n')

            manager = DataSourceManager()
            src = create_file_source(file_path, protocol='csv')
            self.assertTrue(manager.set_source(src))

            frame = manager.read_frame()
            self.assertIsNotNone(frame)
            self.assertEqual(frame['channels']['ch1'], 3.5)
            self.assertEqual(frame['channels']['ch2'], 4.5)
            manager.disconnect()

    def test_file_csv_source_timestamp_keeps_export_millisecond_scale(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, 'ts.csv')
            with open(file_path, 'w', encoding='utf-8') as f:
                # 模拟DataSaver导出：时间戳列为毫秒
                f.write('时间戳,ch1\n')
                f.write('1000,1.25\n')

            manager = DataSourceManager()
            src = create_file_source(file_path, protocol='csv')
            self.assertTrue(manager.set_source(src))

            frame = manager.read_frame()
            self.assertIsNotNone(frame)
            # read_frame对外统一是毫秒，这里应保持1000而非被放大到1_000_000
            self.assertAlmostEqual(frame['timestamp'], 1000.0, places=6)
            manager.disconnect()

    def test_file_csv_source_invalid_header_reports_format_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, 'bad.csv')
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write('wrong,ch1\n')
                f.write('1.0,3.5\n')

            manager = DataSourceManager()
            src = create_file_source(file_path, protocol='csv')
            self.assertTrue(manager.set_source(src))

            frame = manager.read_frame()
            self.assertIsNotNone(frame)
            self.assertTrue(frame.get('meta', {}).get('format_error'))
            manager.disconnect()

    def test_file_csv_source_replay_reads_all_rows(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = os.path.join(tmp_dir, 'many.csv')
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write('时间戳,ch1\n')
                for i in range(100):
                    f.write(f'{i * 10}, {float(i)}\n')

            manager = DataSourceManager()
            src = create_file_source(file_path, protocol='csv')
            self.assertTrue(manager.set_source(src))

            count = 0
            while True:
                frame = manager.read_frame()
                if frame is None:
                    break
                if frame.get('meta', {}).get('format_error'):
                    self.fail('CSV读取过程中不应出现format_error')
                count += 1

            self.assertEqual(count, 100)
            self.assertTrue(src.is_connected)
            manager.disconnect()


if __name__ == '__main__':
    unittest.main()
