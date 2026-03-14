"""
TCP数据发送工具

用于测试上位机的TCP数据接收功能。
发送格式与UDP发送工具保持一致：
    数据校验头,时间戳,通道一=数值,通道二=数值
"""

import argparse
import math
import socket
import time


class TCPSender:
    """TCP数据发送器（客户端模式）"""

    def __init__(self, host: str = '127.0.0.1', port: int = 9999, dump_log_path: str = ''):
        self.host = host
        self.port = port
        self.socket = None
        self.is_running = False
        self.dump_log_path = dump_log_path
        self._dump_fp = None

        if self.dump_log_path:
            self._dump_fp = open(self.dump_log_path, 'a', encoding='utf-8')

    def connect(self) -> None:
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect((self.host, self.port))

    def close(self) -> None:
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
            self.socket = None
        if self._dump_fp:
            self._dump_fp.close()
            self._dump_fp = None

    def send_data(self, timestamp: float, channel_data: dict, header: str = 'DATA') -> None:
        if self.socket is None:
            raise RuntimeError('TCP未连接')

        parts = [header, f"{timestamp:.6f}"]
        for channel_name, value in channel_data.items():
            parts.append(f"{channel_name}={value:.6f}")

        payload = (','.join(parts) + '\n').encode('utf-8')
        self.socket.sendall(payload)

        if self._dump_fp:
            self._dump_fp.write(payload.decode('utf-8'))
            self._dump_fp.flush()

    def send_sine_wave(
        self,
        channels: int = 3,
        frequency: float = 1.0,
        amplitude: float = 1.0,
        duration: float = 10.0,
        sample_rate: int = 50,
        channel_names: list = None,
        header: str = 'DATA',
    ) -> None:
        self.is_running = True
        start_time = time.time()

        if channel_names is None:
            channel_names = [f'通道{i + 1}' for i in range(channels)]
        elif len(channel_names) != channels:
            print(f"警告: 通道名称数量({len(channel_names)})与通道数({channels})不匹配，已回退默认命名")
            channel_names = [f'通道{i + 1}' for i in range(channels)]

        print('开始发送TCP正弦波数据...')
        print(f'目标: {self.host}:{self.port}')
        print(f'通道数: {channels}, 频率: {frequency}Hz, 振幅: {amplitude}, 采样率: {sample_rate}Hz')
        print(f'通道名称: {channel_names}')
        print(f'数据校验头: {header}')
        print(f'持续时间: {duration}秒')
        print('按Ctrl+C停止')

        try:
            sample_count = 0
            while self.is_running and (time.time() - start_time) < duration:
                timestamp = sample_count / sample_rate
                t = timestamp

                channel_data = {}
                for i in range(channels):
                    freq = frequency * (i + 1)
                    phase = i * (2 * math.pi / channels)
                    value = amplitude * math.sin(2 * math.pi * freq * t + phase)
                    channel_data[channel_names[i]] = value

                self.send_data(timestamp, channel_data, header)
                sample_count += 1
                time.sleep(1.0 / sample_rate)
        except KeyboardInterrupt:
            print('\n发送已停止')
        finally:
            self.is_running = False

    def send_random_data(
        self,
        channels: int = 3,
        duration: float = 10.0,
        sample_rate: int = 20,
        channel_names: list = None,
        header: str = 'DATA',
    ) -> None:
        import random

        self.is_running = True
        start_time = time.time()

        if channel_names is None:
            channel_names = [f'通道{i + 1}' for i in range(channels)]
        elif len(channel_names) != channels:
            print(f"警告: 通道名称数量({len(channel_names)})与通道数({channels})不匹配，已回退默认命名")
            channel_names = [f'通道{i + 1}' for i in range(channels)]

        print('开始发送TCP随机数据...')
        print(f'目标: {self.host}:{self.port}')
        print(f'通道数: {channels}, 采样率: {sample_rate}Hz')
        print(f'通道名称: {channel_names}')
        print(f'数据校验头: {header}')
        print(f'持续时间: {duration}秒')
        print('按Ctrl+C停止')

        try:
            sample_count = 0
            while self.is_running and (time.time() - start_time) < duration:
                timestamp = sample_count / sample_rate
                channel_data = {
                    channel_names[i]: random.uniform(-1, 1)
                    for i in range(channels)
                }
                self.send_data(timestamp, channel_data, header)
                sample_count += 1
                time.sleep(1.0 / sample_rate)
        except KeyboardInterrupt:
            print('\n发送已停止')
        finally:
            self.is_running = False


def main() -> None:
    parser = argparse.ArgumentParser(description='TCP数据发送工具')
    parser.add_argument('--host', type=str, default='127.0.0.1', help='目标主机地址 (默认: 127.0.0.1)')
    parser.add_argument('--port', type=int, default=9999, help='目标端口 (默认: 9999)')
    parser.add_argument('--type', type=str, choices=['sine', 'random'], default='sine', help='数据类型')
    parser.add_argument('--channels', type=int, default=3, help='通道数量 (默认: 3)')
    parser.add_argument('--frequency', type=float, default=1.0, help='正弦波频率 (默认: 1.0Hz)')
    parser.add_argument('--amplitude', type=float, default=1.0, help='正弦波振幅 (默认: 1.0)')
    parser.add_argument('--duration', type=float, default=10.0, help='发送持续时间 (默认: 10.0秒)')
    parser.add_argument('--rate', type=int, default=50, help='采样率 (默认: 50Hz)')
    parser.add_argument('--names', type=str, nargs='+', default=None, help='自定义通道名称')
    parser.add_argument('--header', type=str, default='DATA', help='数据校验头 (默认: DATA)')
    parser.add_argument('--dump-log', type=str, default='', help='可选：同步追加写入日志文件（用于文件源实时联调）')

    args = parser.parse_args()
    sender = TCPSender(args.host, args.port, args.dump_log)

    try:
        sender.connect()
        print('TCP连接成功')
        if args.type == 'sine':
            sender.send_sine_wave(
                channels=args.channels,
                frequency=args.frequency,
                amplitude=args.amplitude,
                duration=args.duration,
                sample_rate=args.rate,
                channel_names=args.names,
                header=args.header,
            )
        else:
            sender.send_random_data(
                channels=args.channels,
                duration=args.duration,
                sample_rate=args.rate,
                channel_names=args.names,
                header=args.header,
            )
    except Exception as e:
        print(f'发送失败: {e}')
    finally:
        sender.close()
        print('TCP发送器已关闭')


if __name__ == '__main__':
    main()
