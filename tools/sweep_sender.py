"""
扫频信号发送工具

用于测试上位机的波特图分析功能。
发送扫频信号到 UDP 或 TCP 端口，支持配置起始频率、终止频率、采样率和通道数。

用法:
    UDP扫频: python sweep_sender.py --protocol udp --port 8888 --f-start 0.1 --f-end 10 --duration 20
    TCP扫频: python sweep_sender.py --protocol tcp --port 9999 --f-start 0.1 --f-end 10 --duration 20
"""

import argparse
import math
import socket
import time
import threading


class SweepSender:
    """扫频信号发送器"""

    def __init__(self, protocol: str = 'udp', host: str = '127.0.0.1', port: int = 8888,
                 f_start: float = 0.1, f_end: float = 10.0, sample_rate: int = 100,
                 channels: int = 2, amplitude: float = 1.0, header: str = 'DATA',
                 system_type: str = '1st', time_constant: float = 0.1,
                 natural_freq: float = 2.0, damping_ratio: float = 0.7):
        """初始化扫频发送器

        Args:
            protocol: 协议类型 ('udp' 或 'tcp')
            host: 目标主机地址
            port: 目标端口
            f_start: 起始频率（Hz）
            f_end: 终止频率（Hz）
            sample_rate: 采样率（Hz）
            channels: 通道数量
            amplitude: 信号振幅
            header: 数据校验头
            system_type: 系统类型 ('1st' 一阶系统, '2nd' 二阶系统)
            time_constant: 一阶系统时间常数 (tau)
            natural_freq: 二阶系统自然频率 (wn, rad/s)
            damping_ratio: 二阶系统阻尼比 (zeta)
        """
        self.protocol = protocol.lower()
        self.host = host
        self.port = port
        self.f_start = f_start
        self.f_end = f_end
        self.sample_rate = sample_rate
        self.channels = channels
        self.amplitude = amplitude
        self.header = header
        self.system_type = system_type.lower()
        self.time_constant = time_constant  # 一阶系统时间常数 tau
        self.natural_freq = natural_freq  # 二阶系统自然频率 wn (rad/s)
        self.damping_ratio = damping_ratio  # 二阶系统阻尼比 zeta
        self.is_running = False

        # 通道名称
        self.channel_names = ['输入', '输出'] if channels == 2 else [f'ch{i+1}' for i in range(channels)]

        # 创建 socket
        if self.protocol == 'udp':
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.settimeout(0.2)
        else:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    def connect(self):
        """建立 TCP 连接"""
        if self.protocol == 'tcp':
            self.socket.connect((self.host, self.port))
            self.socket.settimeout(0.2)
            print(f"TCP连接成功: {self.host}:{self.port}")
        else:
            print(f"UDP目标地址: {self.host}:{self.port}")

    def send_data(self, timestamp: float, channel_data: dict):
        """发送数据

        Args:
            timestamp: 时间戳
            channel_data: 通道名称到数值的映射
        """
        parts = [self.header, f"{timestamp:.6f}"]
        for channel_name, value in channel_data.items():
            parts.append(f"{channel_name}={value:.6f}")

        text_data = ",".join(parts)
        data = (text_data + '\n').encode('utf-8')

        if self.protocol == 'udp':
            self.socket.sendto(data, (self.host, self.port))
        else:
            self.socket.sendall(data)

    def send_sweep(self, duration: float = 20.0):
        """发送扫频信号

        Args:
            duration: 扫频持续时间（秒）
        """
        self.is_running = True
        start_time = time.time()

        print(f"开始发送扫频信号...")
        print(f"协议: {self.protocol.upper()}")
        print(f"目标: {self.host}:{self.port}")
        print(f"通道数: {self.channels}")
        print(f"通道名称: {self.channel_names}")
        print(f"频率范围: {self.f_start}Hz -> {self.f_end}Hz")
        print(f"持续时间: {duration}秒")
        print(f"采样率: {self.sample_rate}Hz")
        print(f"振幅: {self.amplitude}")
        
        if self.system_type == '1st':
            print(f"系统模型: 一阶系统 (tau={self.time_constant}s)")
        else:
            print(f"系统模型: 二阶系统 (wn={self.natural_freq}rad/s, zeta={self.damping_ratio})")
        
        print("按Ctrl+C停止")

        try:
            sample_count = 0

            while self.is_running and (time.time() - start_time) < duration:
                # 使用理想的时间戳，确保均匀递增
                ideal_time = sample_count / self.sample_rate
                
                # 线性扫频：频率随理想时间线性变化
                # f(t) = f_start + (f_end - f_start) * t / duration
                t = ideal_time
                current_freq = self.f_start + (self.f_end - self.f_start) * t / duration

                # 计算相位（确保连续性）
                # 相位 = 2π * ∫f(t)dt = 2π * (f_start*t + (f_end-f_start)*t²/(2*duration))
                phase = 2 * math.pi * (self.f_start * t + (self.f_end - self.f_start) * t * t / (2 * duration))

                # 输入信号
                input_signal = self.amplitude * math.sin(phase)

                # 计算系统输出
                output_signal = self._calculate_system_output(input_signal, current_freq)

                # 生成通道数据
                channel_data = {}

                if self.channels == 2:
                    # 通道1: 输入信号
                    channel_data[self.channel_names[0]] = input_signal
                    # 通道2: 系统输出信号
                    channel_data[self.channel_names[1]] = output_signal
                else:
                    # 多通道模式：第一个通道为输入，其余为不同系统参数的输出
                    channel_data[self.channel_names[0]] = input_signal
                    for i in range(1, self.channels):
                        # 每个输出通道使用不同的系统参数
                        if self.system_type == '1st':
                            # 不同时间常数
                            tau = self.time_constant * (i + 1)
                            output = self._calculate_first_order(input_signal, current_freq, tau)
                        else:
                            # 不同阻尼比
                            zeta = max(0.1, min(1.0, self.damping_ratio * (i + 0.5)))
                            output = self._calculate_second_order(input_signal, current_freq, self.natural_freq, zeta)
                        channel_data[self.channel_names[i]] = output

                timestamp = ideal_time
                self.send_data(timestamp, channel_data)

                sample_count += 1
                time.sleep(1.0 / self.sample_rate)

        except KeyboardInterrupt:
            print("\n发送已停止")
        finally:
            self.is_running = False
    
    def _calculate_system_output(self, input_signal: float, frequency: float) -> float:
        """计算系统输出
        
        Args:
            input_signal: 输入信号
            frequency: 当前频率 (Hz)
            
        Returns:
            系统输出信号
        """
        if self.system_type == '1st':
            return self._calculate_first_order(input_signal, frequency, self.time_constant)
        else:
            return self._calculate_second_order(input_signal, frequency, self.natural_freq, self.damping_ratio)
    
    def _calculate_first_order(self, input_signal: float, frequency: float, tau: float) -> float:
        """计算一阶系统输出
        
        一阶系统传递函数: H(s) = 1 / (tau*s + 1)
        频率响应: H(jw) = 1 / (1 + jw*tau)
        幅值: 1 / sqrt(1 + (w*tau)^2)
        相位: -arctan(w*tau)
        
        Args:
            input_signal: 输入信号
            frequency: 当前频率 (Hz)
            tau: 时间常数
            
        Returns:
            系统输出信号
        """
        omega = 2 * math.pi * frequency
        omega_tau = omega * tau
        
        # 计算幅值响应
        magnitude = 1.0 / math.sqrt(1 + (omega_tau)**2)
        
        # 计算相位响应 (弧度)
        phase = -math.atan(omega_tau)
        
        # 计算输出信号
        output = magnitude * input_signal * math.cos(phase)  # 简化计算
        return output
    
    def _calculate_second_order(self, input_signal: float, frequency: float, wn: float, zeta: float) -> float:
        """计算二阶系统输出
        
        二阶系统传递函数: H(s) = wn² / (s² + 2*zeta*wn*s + wn²)
        频率响应: H(jw) = wn² / (-w² + j2*zeta*wn*w + wn²)
        幅值: wn² / sqrt((wn² - w²)^2 + (2*zeta*wn*w)^2)
        相位: -arctan(2*zeta*wn*w / (wn² - w²))
        
        Args:
            input_signal: 输入信号
            frequency: 当前频率 (Hz)
            wn: 自然频率 (rad/s)
            zeta: 阻尼比
            
        Returns:
            系统输出信号
        """
        omega = 2 * math.pi * frequency
        omega_squared = omega ** 2
        wn_squared = wn ** 2
        
        # 计算幅值响应
        numerator = wn_squared
        denominator = math.sqrt((wn_squared - omega_squared)**2 + (2 * zeta * wn * omega)**2)
        magnitude = numerator / denominator
        
        # 计算相位响应 (弧度)
        if wn_squared > omega_squared:
            # 低频区域
            phase = -math.atan((2 * zeta * wn * omega) / (wn_squared - omega_squared))
        else:
            # 高频区域
            phase = -math.pi - math.atan((2 * zeta * wn * omega) / (omega_squared - wn_squared))
        
        # 计算输出信号
        output = magnitude * input_signal * math.cos(phase)  # 简化计算
        return output

    def stop(self):
        """停止发送"""
        self.is_running = False

    def close(self):
        """关闭连接"""
        self.socket.close()
        print(f"{self.protocol.upper()}连接已关闭")


def main():
    parser = argparse.ArgumentParser(description='扫频信号发送工具（用于测试波特图）')
    parser.add_argument('--protocol', type=str, choices=['udp', 'tcp'], default='udp',
                       help='协议类型: udp 或 tcp (默认: udp)')
    parser.add_argument('--host', type=str, default='127.0.0.1',
                       help='目标主机地址 (默认: 127.0.0.1)')
    parser.add_argument('--port', type=int, default=8888,
                       help='目标端口 (默认: 8888)')
    parser.add_argument('--f-start', type=float, default=0.1,
                       help='起始频率 Hz (默认: 0.1Hz)')
    parser.add_argument('--f-end', type=float, default=10.0,
                       help='终止频率 Hz (默认: 10Hz)')
    parser.add_argument('--duration', type=float, default=20.0,
                       help='扫频持续时间 秒 (默认: 20秒)')
    parser.add_argument('--rate', type=int, default=100,
                       help='采样率 Hz (默认: 100Hz)')
    parser.add_argument('--channels', type=int, default=2,
                       help='通道数量 (默认: 2)')
    parser.add_argument('--amplitude', type=float, default=1.0,
                       help='信号振幅 (默认: 1.0)')
    parser.add_argument('--header', type=str, default='DATA',
                       help='数据校验头 (默认: DATA)')
    parser.add_argument('--system', type=str, choices=['1st', '2nd'], default='1st',
                       help='系统类型: 1st (一阶系统) 或 2nd (二阶系统) (默认: 1st)')
    parser.add_argument('--tau', type=float, default=0.1,
                       help='一阶系统时间常数 (tau, 单位: 秒) (默认: 0.1)')
    parser.add_argument('--wn', type=float, default=2.0,
                       help='二阶系统自然频率 (wn, 单位: rad/s) (默认: 2.0)')
    parser.add_argument('--zeta', type=float, default=0.7,
                       help='二阶系统阻尼比 (zeta) (默认: 0.7)')

    args = parser.parse_args()

    sender = SweepSender(
        protocol=args.protocol,
        host=args.host,
        port=args.port,
        f_start=args.f_start,
        f_end=args.f_end,
        sample_rate=args.rate,
        channels=args.channels,
        amplitude=args.amplitude,
        header=args.header,
        system_type=args.system,
        time_constant=args.tau,
        natural_freq=args.wn,
        damping_ratio=args.zeta,
    )

    try:
        sender.connect()
        sender.send_sweep(duration=args.duration)
    except Exception as e:
        print(f"错误: {e}")
    finally:
        sender.close()


if __name__ == '__main__':
    main()
