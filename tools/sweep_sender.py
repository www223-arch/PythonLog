import argparse
import math
import socket
import time
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime

# 设置matplotlib中文和负号显示
plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False


class SweepSender:
    """动态采样扫频信号发送器（直接加Sleep防丢包）"""

    def __init__(self, protocol: str = 'udp', host: str = '127.0.0.1', port: int = 8888,
                 f_start: float = 0.1, f_end: float = 10.0,
                 channels: int = 2, amplitude: float = 1.0, header: str = 'DATA',
                 system_type: str = '1st', time_constant: float = 0.1,
                 natural_freq: float = 2.0, damping_ratio: float = 0.7,
                 cycles_per_decade: int = 10, points_per_cycle: int = 50):
        self.protocol = protocol.lower()
        self.host = host
        self.port = port
        self.f_start = f_start
        self.f_end = f_end
        self.points_per_cycle = points_per_cycle
        self.min_sample_interval = 0.0001

        self.channels = channels
        self.amplitude = amplitude
        self.header = header
        self.system_type = system_type.lower()
        self.time_constant = time_constant
        self.natural_freq = natural_freq
        self.damping_ratio = damping_ratio
        self.cycles_per_decade = cycles_per_decade

        self.channel_names = ['输入', '输出'] if channels == 2 else [f'ch{i+1}' for i in range(channels)]

        if self.protocol == 'udp':
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.settimeout(0.2)
        else:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    def connect(self):
        if self.protocol == 'tcp':
            self.socket.connect((self.host, self.port))
            self.socket.settimeout(0.2)
            print(f"TCP连接成功: {self.host}:{self.port}")
        else:
            print(f"UDP目标地址: {self.host}:{self.port}")

    def send_data(self, timestamp: float, channel_data: dict):
        parts = [self.header, f"{timestamp:.6f}"]
        for name, val in channel_data.items():
            parts.append(f"{name}={val:.8f}")
        data = (",".join(parts) + '\n').encode('utf-8')
        if self.protocol == 'udp':
            self.socket.sendto(data, (self.host, self.port))
        else:
            self.socket.sendall(data)

    def _calculate_duration(self):
        if self.f_end <= self.f_start:
            return 10.0
        decades = math.log10(self.f_end / self.f_start)
        total_cycles = self.cycles_per_decade * decades
        duration = total_cycles / self.f_start
        return max(duration, 5.0)

    def _generate_sweep_data(self, duration: float):
        data = []
        current_t = 0.0
        while current_t < duration:
            current_freq = self._get_frequency(current_t, duration)
            sample_interval = 1.0 / (current_freq * self.points_per_cycle)
            sample_interval = max(sample_interval, self.min_sample_interval)
            phase = self._get_phase(current_t, duration)
            input_sig = self.amplitude * math.sin(phase)
            output_sig = self._calculate_system_output(input_sig, current_freq, phase)
            
            channel_data = {self.channel_names[0]: input_sig}
            if self.channels >= 2:
                channel_data[self.channel_names[1]] = output_sig
            
            data.append((current_t, channel_data))
            current_t += sample_interval
        return data

    def send_sweep(self, duration: float = None):
        if duration is None:
            duration = self._calculate_duration()

        print("===== 动态采样扫频已启动 =====")
        print(f"频率范围: {self.f_start}Hz → {self.f_end}Hz")
        print(f"信号总时长: {duration:.1f}s")
        print(f"采样规则: 每周期{self.points_per_cycle}个点")
        print("正在预计算所有采样点...")

        sweep_data = self._generate_sweep_data(duration)
        total_points = len(sweep_data)
        print(f"预计算完成，总采样点数: {total_points}")
        print(f"开始发送数据...\n")

        try:
            for t, channel_data in sweep_data:
                self.send_data(t, channel_data)
                # 🔥 直接在这里加Sleep！100微秒，防丢包
                time.sleep(0.0001)

            print(f"\n✅ 发送完成！")
        except KeyboardInterrupt:
            print("\n❌ 手动停止发送")
        except Exception as e:
            print(f"\n❌ 发送错误: {e}")

    # ==================== 核心算法（不变）====================
    def _get_frequency(self, t: float, duration: float) -> float:
        decades = math.log10(self.f_end / self.f_start)
        return self.f_start * (10 ** (t / duration * decades))

    def _get_phase(self, t: float, duration: float) -> float:
        decades = math.log10(self.f_end / self.f_start)
        if decades < 1e-10:
            return 2 * math.pi * self.f_start * t
        ln10 = math.log(10)
        return (2 * math.pi * self.f_start * duration / (ln10 * decades)) * (10 ** (decades * t / duration) - 1)

    def _calculate_system_output(self, in_sig, freq, phase):
        return self._calculate_first_order(in_sig, freq, self.time_constant, phase) if self.system_type == '1st' \
            else self._calculate_second_order(in_sig, freq, self.natural_freq, self.damping_ratio, phase)

    def _calculate_first_order(self, in_sig, freq, tau, phase):
        omega = 2 * math.pi * freq
        mag = 1 / math.sqrt(1 + (omega*tau)**2)
        shift = -math.atan(omega*tau)
        return mag * self.amplitude * math.sin(phase + shift)

    def _calculate_second_order(self, in_sig, freq, wn, zeta, phase):
        omega = 2 * math.pi * freq
        wn2, w2 = wn**2, omega**2
        mag = wn2 / math.sqrt((wn2-w2)**2 + (2*zeta*wn*omega)**2)
        if wn2 > w2:
            shift = -math.atan(2*zeta*wn*omega/(wn2-w2))
        else:
            shift = -math.pi - math.atan(2*zeta*wn*omega/(w2-wn2))
        return mag * self.amplitude * math.sin(phase + shift)

    def plot_theoretical_bode(self):
        frequencies = np.logspace(np.log10(self.f_start), np.log10(self.f_end), 1000)
        mag_db, phase_deg = [], []
        for f in frequencies:
            omega = 2*np.pi*f
            if self.system_type == '1st':
                ot = omega*self.time_constant
                mag = 1/np.sqrt(1+ot**2)
                ph = -np.arctan(ot)
            else:
                wn2, w2 = self.natural_freq**2, omega**2
                mag = self.natural_freq**2 / np.sqrt((wn2-w2)**2 + (2*self.damping_ratio*self.natural_freq*omega)**2)
                ph = -np.arctan(2*self.damping_ratio*self.natural_freq*omega/(wn2-w2)) if wn2>w2 else -np.pi-np.arctan(2*self.damping_ratio*self.natural_freq*omega/(w2-wn2))
            mag_db.append(20*np.log10(mag))
            phase_deg.append(np.degrees(ph))

        plt.figure(figsize=(12,8))
        plt.subplot(211);plt.semilogx(frequencies,mag_db,'b-',linewidth=2);plt.title('理论波特图');plt.ylabel('幅值(dB)');plt.grid(True,which='both')
        plt.subplot(212);plt.semilogx(frequencies,phase_deg,'r-',linewidth=2);plt.xlabel('频率(Hz)');plt.ylabel('相位(°)');plt.grid(True,which='both')
        plt.tight_layout()
        plt.savefig(f'bode_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png')
        plt.show()

    def close(self):
        if self.socket:
            self.socket.close()


def main():
    parser = argparse.ArgumentParser(description='动态采样扫频信号发生器')
    parser.add_argument('--protocol', default='udp', choices=['udp','tcp'])
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8888)
    parser.add_argument('--f-start', type=float, default=0.1)
    parser.add_argument('--f-end', type=float, default=10)
    parser.add_argument('--duration', type=float)
    parser.add_argument('--channels', type=int, default=2)
    parser.add_argument('--amplitude', type=float, default=1.0)
    parser.add_argument('--points', type=int, default=30)
    parser.add_argument('--system', default='1st', choices=['1st','2nd'])
    parser.add_argument('--tau', type=float, default=0.1)
    parser.add_argument('--wn', type=float, default=2.0)
    parser.add_argument('--zeta', type=float, default=0.7)
    parser.add_argument('--plot', action='store_true')
    args = parser.parse_args()

    sender = SweepSender(
        protocol=args.protocol, host=args.host, port=args.port,
        f_start=args.f_start, f_end=args.f_end, channels=args.channels,
        amplitude=args.amplitude, system_type=args.system,
        time_constant=args.tau, natural_freq=args.wn, damping_ratio=args.zeta,
        points_per_cycle=args.points
    )

    if args.plot:
        sender.plot_theoretical_bode()
        return

    try:
        sender.connect()
        sender.send_sweep(duration=args.duration)
        print("\n正在生成理论波特图...")
        sender.plot_theoretical_bode()
    except Exception as e:
        print(f"错误: {e}")
    finally:
        sender.close()


if __name__ == '__main__':
    main()