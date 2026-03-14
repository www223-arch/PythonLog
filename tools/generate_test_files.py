"""
测试数据文件生成工具

可生成上位机文件回放所需的 .log / .bin 文件。
- .log: 文本协议（DATA,timestamp,ch=value...）
- .bin: justfloat二进制协议（float数组 + 帧尾 00 00 80 7F）
"""

import argparse
import math
import os
import random
import struct
import time
from datetime import datetime

FRAME_TAIL = bytes([0x00, 0x00, 0x80, 0x7F])


def default_channel_names(channels: int) -> list:
    return [f'通道{i + 1}' for i in range(channels)]


def build_frame_values(
    sample_idx: int,
    channels: int,
    sample_rate: int,
    data_type: str,
    frequency: float,
    amplitude: float,
) -> list:
    t = sample_idx / sample_rate
    values = []
    for ch in range(channels):
        if data_type == 'sine':
            freq = frequency * (ch + 1)
            phase = ch * (2 * math.pi / channels)
            value = amplitude * math.sin(2 * math.pi * freq * t + phase)
        else:
            value = random.uniform(-amplitude, amplitude)
        values.append(float(value))
    return values


def generate_log_file(
    output_path: str,
    channels: int,
    samples: int,
    sample_rate: int,
    data_type: str,
    frequency: float,
    amplitude: float,
    channel_names: list,
    header: str,
) -> None:
    with open(output_path, 'w', encoding='utf-8') as f:
        for i in range(samples):
            timestamp = i / sample_rate
            frame_values = build_frame_values(i, channels, sample_rate, data_type, frequency, amplitude)

            parts = [header, f"{timestamp:.6f}"]
            for ch, val in enumerate(frame_values):
                parts.append(f"{channel_names[ch]}={val:.6f}")
            f.write(','.join(parts) + '\n')


def generate_bin_file(
    output_path: str,
    channels: int,
    samples: int,
    sample_rate: int,
    data_type: str,
    frequency: float,
    amplitude: float,
    with_timestamp: bool,
) -> None:
    with open(output_path, 'wb') as f:
        for i in range(samples):
            t = i / sample_rate
            frame_values = build_frame_values(i, channels, sample_rate, data_type, frequency, amplitude)

            if with_timestamp:
                frame_values.append(float(t * 1000.0))

            f.write(struct.pack(f'{len(frame_values)}f', *frame_values))
            f.write(FRAME_TAIL)


def stream_log_file(
    output_path: str,
    channels: int,
    sample_rate: int,
    data_type: str,
    frequency: float,
    amplitude: float,
    channel_names: list,
    header: str,
) -> int:
    """持续写入log文件，直到Ctrl+C。"""
    sample_idx = 0
    print(f"开始持续写入: {output_path}")
    print(f"实时模式采样率: {sample_rate}Hz，按 Ctrl+C 停止")

    with open(output_path, 'a', encoding='utf-8') as f:
        last_print_time = time.time()
        try:
            while True:
                timestamp = sample_idx / sample_rate
                frame_values = build_frame_values(sample_idx, channels, sample_rate, data_type, frequency, amplitude)

                parts = [header, f"{timestamp:.6f}"]
                for ch, val in enumerate(frame_values):
                    parts.append(f"{channel_names[ch]}={val:.6f}")

                f.write(','.join(parts) + '\n')
                f.flush()
                sample_idx += 1

                now = time.time()
                if now - last_print_time >= 1.0:
                    print(f"已写入 {sample_idx} 行")
                    last_print_time = now

                time.sleep(1.0 / sample_rate)
        except KeyboardInterrupt:
            print("\n实时写入已停止")

    return sample_idx


def stream_bin_file(
    output_path: str,
    channels: int,
    sample_rate: int,
    data_type: str,
    frequency: float,
    amplitude: float,
    with_timestamp: bool,
) -> int:
    """持续写入bin文件，直到Ctrl+C。"""
    sample_idx = 0
    print(f"开始持续写入: {output_path}")
    print(f"实时模式采样率: {sample_rate}Hz，按 Ctrl+C 停止")

    with open(output_path, 'ab') as f:
        last_print_time = time.time()
        try:
            while True:
                t = sample_idx / sample_rate
                frame_values = build_frame_values(sample_idx, channels, sample_rate, data_type, frequency, amplitude)
                if with_timestamp:
                    frame_values.append(float(t * 1000.0))

                f.write(struct.pack(f'{len(frame_values)}f', *frame_values))
                f.write(FRAME_TAIL)
                f.flush()
                sample_idx += 1

                now = time.time()
                if now - last_print_time >= 1.0:
                    print(f"已写入 {sample_idx} 帧")
                    last_print_time = now

                time.sleep(1.0 / sample_rate)
        except KeyboardInterrupt:
            print("\n实时写入已停止")

    return sample_idx


def build_default_output_path(output_dir: str, suffix: str) -> str:
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    return os.path.join(output_dir, f'test_{ts}.{suffix}')


def main() -> None:
    parser = argparse.ArgumentParser(description='测试数据文件生成工具')
    parser.add_argument('--format', choices=['log', 'bin'], default='log', help='输出格式')
    parser.add_argument('--output', type=str, default='', help='输出文件路径（不填则自动生成）')
    parser.add_argument('--output-dir', type=str, default='data', help='输出目录（默认 data）')
    parser.add_argument('--channels', type=int, default=3, help='通道数量')
    parser.add_argument('--samples', type=int, default=1000, help='样本数')
    parser.add_argument('--rate', type=int, default=50, help='采样率Hz')
    parser.add_argument('--type', choices=['sine', 'random'], default='sine', help='数据类型')
    parser.add_argument('--frequency', type=float, default=1.0, help='正弦波基频Hz')
    parser.add_argument('--amplitude', type=float, default=1.0, help='振幅')
    parser.add_argument('--names', nargs='+', default=None, help='文本格式自定义通道名')
    parser.add_argument('--header', type=str, default='DATA', help='文本格式数据校验头')
    parser.add_argument('--with-timestamp', action='store_true', help='bin模式下追加时间戳(ms)')
    parser.add_argument('--live', action='store_true', help='持续写入模式（不按samples停止，Ctrl+C停止）')

    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    output_path = args.output
    if not output_path:
        suffix = 'log' if args.format == 'log' else 'bin'
        output_path = build_default_output_path(args.output_dir, suffix)

    channel_names = args.names if args.names else default_channel_names(args.channels)
    if len(channel_names) != args.channels:
        print('警告: 通道名称数量与通道数不一致，已回退默认命名')
        channel_names = default_channel_names(args.channels)

    written_count = args.samples

    if args.live:
        if args.format == 'log':
            written_count = stream_log_file(
                output_path=output_path,
                channels=args.channels,
                sample_rate=args.rate,
                data_type=args.type,
                frequency=args.frequency,
                amplitude=args.amplitude,
                channel_names=channel_names,
                header=args.header,
            )
        else:
            written_count = stream_bin_file(
                output_path=output_path,
                channels=args.channels,
                sample_rate=args.rate,
                data_type=args.type,
                frequency=args.frequency,
                amplitude=args.amplitude,
                with_timestamp=args.with_timestamp,
            )
    else:
        if args.format == 'log':
            generate_log_file(
                output_path=output_path,
                channels=args.channels,
                samples=args.samples,
                sample_rate=args.rate,
                data_type=args.type,
                frequency=args.frequency,
                amplitude=args.amplitude,
                channel_names=channel_names,
                header=args.header,
            )
        else:
            generate_bin_file(
                output_path=output_path,
                channels=args.channels,
                samples=args.samples,
                sample_rate=args.rate,
                data_type=args.type,
                frequency=args.frequency,
                amplitude=args.amplitude,
                with_timestamp=args.with_timestamp,
            )

    print('文件生成完成:')
    print(f'  路径: {output_path}')
    print(f'  格式: {args.format}')
    print(f'  通道: {args.channels}')
    print(f'  样本: {written_count}')
    print(f'  采样率: {args.rate}Hz')
    mode_text = '实时写入(live)' if args.live else '定长生成'
    print(f'  模式: {mode_text}')
    if args.format == 'bin':
        mode = 'with_timestamp' if args.with_timestamp else 'without_timestamp'
        print(f'  Justfloat模式: {mode}')


if __name__ == '__main__':
    main()
