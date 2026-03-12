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
    
    def send_data(self, timestamp: float, channel_data: dict) -> None:
        """发送数据
        
        Args:
            timestamp: 时间戳
            channel_data: 通道名称到数值的映射
        """
        # 构建文本数据：时间戳,通道一=数值,通道二=数值
        parts = [str(timestamp)]
        for channel_name, value in channel_data.items():
            parts.append(f"{channel_name}={value:.6f}")
        
        text_data = ",".join(parts)
        data = text_data.encode('utf-8')
        self.socket.sendto(data, (self.host, self.port))
    
    def send_sine_wave(self, channels: int = 3, frequency: float = 1.0, 
                       amplitude: float = 1.0, duration: float = 10.0):
        """发送正弦波数据
        
        Args:
            channels: 通道数量
            frequency: 频率（Hz）
            amplitude: 振幅
            duration: 发送持续时间（秒）
        """
        self.is_running = True
        start_time = time.time()
        sample_rate = 100  # 采样率
        
        print(f"开始发送正弦波数据...")
        print(f"目标: {self.host}:{self.port}")
        print(f"通道数: {channels}, 频率: {frequency}Hz, 振幅: {amplitude}")
        print(f"持续时间: {duration}秒")
        print("按Ctrl+C停止")
        
        try:
            sample_interval = 1.0 / sample_rate  # 采样间隔
            sample_count = 0  # 采样计数器
            
            while self.is_running and (time.time() - start_time) < duration:
                # 使用累积计数器生成均匀的时间戳
                timestamp = sample_count * sample_interval
                t = timestamp  # 使用均匀的时间戳计算波形
                
                # 生成多通道正弦波数据
                channel_data = {}
                for i in range(channels):
                    # 每个通道有不同的频率和相位
                    freq = frequency * (i + 1)
                    phase = i * (2 * math.pi / channels)
                    value = amplitude * math.sin(2 * math.pi * freq * t + phase)
                    channel_name = f'通道{i+1}'
                    channel_data[channel_name] = value
                
                # 发送文本格式数据
                self.send_data(timestamp, channel_data)
                
                sample_count += 1
                time.sleep(sample_interval)
                
        except KeyboardInterrupt:
            print("\n发送已停止")
        finally:
            self.is_running = False
            self.socket.close()
            print("UDP发送器已关闭")
    
    def send_random_data(self, channels: int = 3, duration: float = 10.0):
        """发送随机数据
        
        Args:
            channels: 通道数量
            duration: 发送持续时间（秒）
        """
        import random
        
        self.is_running = True
        start_time = time.time()
        sample_rate = 100
        
        print(f"开始发送随机数据...")
        print(f"目标: {self.host}:{self.port}")
        print(f"通道数: {channels}")
        print(f"持续时间: {duration}秒")
        print("按Ctrl+C停止")
        
        try:
            sample_interval = 1.0 / sample_rate  # 采样间隔
            sample_count = 0  # 采样计数器
            
            while self.is_running and (time.time() - start_time) < duration:
                # 使用累积计数器生成均匀的时间戳
                timestamp = sample_count * sample_interval
                
                # 生成多通道随机数据
                channel_data = {}
                for i in range(channels):
                    value = random.uniform(-1, 1)
                    channel_name = f'通道{i+1}'
                    channel_data[channel_name] = value
                
                # 发送文本格式数据
                self.send_data(timestamp, channel_data)
                
                sample_count += 1
                time.sleep(sample_interval)
                
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
    parser.add_argument('--host', type=str, default='127.0.0.1', 
                       help='目标主机地址 (默认: 127.0.0.1)')
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
    
    args = parser.parse_args()
    
    # 创建发送器
    sender = UDPSender(args.host, args.port)
    
    # 发送数据
    if args.type == 'sine':
        sender.send_sine_wave(args.channels, args.frequency, 
                             args.amplitude, args.duration)
    else:
        sender.send_random_data(args.channels, args.duration)


if __name__ == "__main__":
    main()