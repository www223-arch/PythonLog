"""
UDP数据发送工具

用于测试上位机的UDP数据接收功能。
可以发送模拟的波形数据到指定的UDP端口。
"""

import socket
import struct
import time
import math
import argparse


class UDPSender:
    """UDP数据发送器"""
    
    def __init__(self, host: str = '127.0.0.1', port: int = 8888):
        """初始化UDP发送器
        
        Args:
            host: 目标主机地址
            port: 目标端口
        """
        self.host = host
        self.port = port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.is_running = False
    
    def send_data(self, timestamp: float, channel_data: dict, header: str = 'DATA') -> None:
        """发送数据
        
        Args:
            timestamp: 时间戳
            channel_data: 通道名称到数值的映射
            header: 数据校验头（默认'DATA'）
        """
        # 构建文本数据：数据校验头,时间戳,通道一=数值,通道二=数值
        parts = [header, f"{timestamp:.6f}"]
        for channel_name, value in channel_data.items():
            parts.append(f"{channel_name}={value:.6f}")
        
        text_data = ",".join(parts)
        data = text_data.encode('utf-8')
        self.socket.sendto(data, (self.host, self.port))
    
    def send_sine_wave(self, channels: int = 3, frequency: float = 1.0, 
                       amplitude: float = 1.0, duration: float = 10.0, 
                       channel_names: list = None, header: str = 'DATA'):
        """发送正弦波数据
        
        Args:
            channels: 通道数量
            frequency: 频率（Hz）
            amplitude: 振幅
            duration: 发送持续时间（秒）
            channel_names: 自定义通道名称列表
            header: 数据校验头（默认'DATA'）
        """
        self.is_running = True
        start_time = time.time()
        sample_rate = 100
          # 采样率
        
        # 使用自定义通道名称，如果没有则使用默认
        if channel_names is None:
            channel_names = [f'通道{i+1}' for i in range(channels)]
        elif len(channel_names) != channels:
            print(f"警告: 通道名称数量({len(channel_names)})与通道数({channels})不匹配")
            channel_names = [f'通道{i+1}' for i in range(channels)]
        
        print(f"开始发送正弦波数据...")
        print(f"目标: {self.host}:{self.port}")
        print(f"通道数: {channels}, 频率: {frequency}Hz, 振幅: {amplitude}")
        print(f"通道名称: {channel_names}")
        print(f"数据校验头: {header}")
        print(f"持续时间: {duration}秒")
        print("按Ctrl+C停止")
        
        try:
            sample_count = 0  # 采样计数器
            
            while self.is_running and (time.time() - start_time) < duration:
                # 使用整数计算时间戳，避免浮点误差
                timestamp = sample_count / sample_rate  # sample_count / 100
                t = timestamp  # 使用均匀的时间戳计算波形
                
                # 生成多通道正弦波数据
                channel_data = {}
                for i in range(channels):
                    # 每个通道有不同的频率和相位
                    freq = frequency * (i + 1)
                    phase = i * (2 * math.pi / channels)
                    value = amplitude * math.sin(2 * math.pi * freq * t + phase)
                    channel_name = channel_names[i]
                    channel_data[channel_name] = value
                
                # 发送文本格式数据（带数据校验头）
                self.send_data(timestamp, channel_data, header)
                
                sample_count += 1
                time.sleep(1.0 / sample_rate)
                
        except KeyboardInterrupt:
            print("\n发送已停止")
        finally:
            self.is_running = False
            self.socket.close()
            print("UDP发送器已关闭")
    
    def send_random_data(self, channels: int = 3, duration: float = 10.0, 
                        channel_names: list = None, header: str = 'www'):
        """发送随机数据
        
        Args:
            channels: 通道数量
            duration: 发送持续时间（秒）
            channel_names: 自定义通道名称列表
            header: 数据校验头（默认'DATA'）
        """
        import random
        
        self.is_running = True
        start_time = time.time()
        sample_rate = 20
        
        # 使用自定义通道名称，如果没有则使用默认
        if channel_names is None:
            channel_names = [f'通道{i+1}' for i in range(channels)]
        elif len(channel_names) != channels:
            print(f"警告: 通道名称数量({len(channel_names)})与通道数({channels})不匹配")
            channel_names = [f'通道{i+1}' for i in range(channels)]
        
        print(f"开始发送随机数据...")
        print(f"目标: {self.host}:{self.port}")
        print(f"通道数: {channels}")
        print(f"通道名称: {channel_names}")
        print(f"数据校验头: {header}")
        print(f"持续时间: {duration}秒")
        print("按Ctrl+C停止")
        
        try:
            sample_count = 0  # 采样计数器
            
            while self.is_running and (time.time() - start_time) < duration:
                # 使用整数计算时间戳，避免浮点误差
                timestamp = sample_count / sample_rate
                
                # 生成多通道随机数据
                channel_data = {}
                for i in range(channels):
                    value = random.uniform(-1, 1)
                    channel_name = channel_names[i]
                    channel_data[channel_name] = value
                
                # 发送文本格式数据（带数据校验头）
                self.send_data(timestamp, channel_data, header)
                
                sample_count += 1
                time.sleep(1.0 / sample_rate)
                
        except KeyboardInterrupt:
            print("\n发送已停止")
        finally:
            self.is_running = False
            self.socket.close()
            print("UDP发送器已关闭")
    
    def stop(self):
        """停止发送"""
        self.is_running = False


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='UDP数据发送工具')
    parser.add_argument('--host', type=str, default='192.168.114.238', 
                       help='目标主机地址 (默认: 192.168.114.238)')
    parser.add_argument('--port', type=int, default=8888, 
                       help='目标端口 (默认: 8888)')
    parser.add_argument('--type', type=str, choices=['sine', 'random'], 
                       default='sine', help='数据类型: sine(正弦波) 或 random(随机)')
    parser.add_argument('--channels', type=int, default=3, 
                       help='通道数量 (默认: 3)')
    parser.add_argument('--frequency', type=float, default=1.0, 
                       help='正弦波频率 (默认: 1.0Hz)')
    parser.add_argument('--amplitude', type=float, default=1.0, 
                       help='正弦波振幅 (默认: 1.0)')
    parser.add_argument('--duration', type=float, default=10.0, 
                       help='发送持续时间 (默认: 10.0秒)')
    parser.add_argument('--rate', type=int, default=50, 
                       help='采样率 (默认: 50Hz，建议50-100Hz)')
    parser.add_argument('--names', type=str, nargs='+', default=None,
                       help='自定义通道名称，用空格分隔 (例如: --names 电压 电流 温度)')
    parser.add_argument('--header', type=str, default='DATA',
                       help='数据校验头 (默认: DATA)')
    
    args = parser.parse_args()
    
    # 创建发送器
    sender = UDPSender(args.host, args.port)
    
    # 发送数据
    if args.type == 'sine':
        sender.send_sine_wave(args.channels, args.frequency, 
                             args.amplitude, args.duration, args.names, args.header)
    else:
        sender.send_random_data(args.channels, args.duration, args.names, args.header)


if __name__ == "__main__":
    main()