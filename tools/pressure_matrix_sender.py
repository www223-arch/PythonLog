"""点阵压力发送工具。

支持向上位机发送文本协议点阵压力帧：
DATA,timestamp,p_0_0=...,p_0_1=...,...
"""

import argparse
import math
import random
import socket
import time
from typing import List


def build_matrix(
    t: float,
    width: int,
    height: int,
    heart_rate: float,
    amplitude: float,
    baseline: float,
    noise: float,
    drift_speed: float,
) -> List[List[float]]:
    """生成一帧合成压力矩阵。"""
    matrix = [[0.0 for _ in range(width)] for _ in range(height)]

    # 心搏主频
    freq = max(0.2, heart_rate / 60.0)
    pulse = 0.5 * (1.0 + math.sin(2.0 * math.pi * freq * t))

    # 压力中心做慢速漂移，模拟探头轻微移动
    cx = (width - 1) * (0.5 + 0.25 * math.sin(2.0 * math.pi * drift_speed * t))
    cy = (height - 1) * (0.5 + 0.20 * math.cos(2.0 * math.pi * drift_speed * t))

    sigma_x = max(1.0, width * 0.18)
    sigma_y = max(1.0, height * 0.16)

    for r in range(height):
        for c in range(width):
            dx = (c - cx) / sigma_x
            dy = (r - cy) / sigma_y
            spatial = math.exp(-0.5 * (dx * dx + dy * dy))
            value = baseline + amplitude * pulse * spatial
            if noise > 0:
                value += random.uniform(-noise, noise)
            matrix[r][c] = float(value)

    return matrix


def encode_text_frame(header: str, timestamp: float, matrix: List[List[float]]) -> str:
    parts = [header, f"{timestamp:.6f}"]
    for r, row in enumerate(matrix):
        for c, value in enumerate(row):
            parts.append(f"p_{r}_{c}={value:.6f}")
    return ",".join(parts)


def send_udp(host: str, port: int, payload: bytes) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.sendto(payload, (host, port))


class TcpSender:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.sock = None

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((self.host, self.port))

    def send(self, payload: bytes) -> None:
        if self.sock is None:
            self.connect()
        self.sock.sendall(payload)

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None


def main() -> None:
    parser = argparse.ArgumentParser(description="点阵压力发送工具")
    parser.add_argument("--mode", choices=["udp", "tcp"], default="udp", help="发送模式")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="目标地址")
    parser.add_argument("--port", type=int, default=8888, help="目标端口")
    parser.add_argument("--grid-width", type=int, default=16, help="点阵宽度")
    parser.add_argument("--grid-height", type=int, default=16, help="点阵高度")
    parser.add_argument("--rate", type=float, default=30.0, help="发送帧率Hz")
    parser.add_argument("--duration", type=float, default=20.0, help="持续时间秒")
    parser.add_argument("--heart-rate", type=float, default=72.0, help="模拟心率bpm")
    parser.add_argument("--amplitude", type=float, default=40.0, help="波动幅值")
    parser.add_argument("--baseline", type=float, default=20.0, help="基线压力")
    parser.add_argument("--noise", type=float, default=1.5, help="噪声幅度")
    parser.add_argument("--drift-speed", type=float, default=0.08, help="压力中心漂移频率Hz")
    parser.add_argument("--header", type=str, default="DATA", help="数据头")
    parser.add_argument("--dump-log", type=str, default="", help="可选日志输出路径")
    args = parser.parse_args()

    interval = 1.0 / max(1.0, float(args.rate))
    start = time.time()
    frame_count = 0

    tcp_sender = TcpSender(args.host, args.port) if args.mode == "tcp" else None
    fp = open(args.dump_log, "a", encoding="utf-8") if args.dump_log else None

    print(f"开始发送点阵压力数据: mode={args.mode} target={args.host}:{args.port}")
    print(f"点阵: {args.grid_width}x{args.grid_height}, rate={args.rate}Hz, duration={args.duration}s")

    try:
        while time.time() - start < args.duration:
            now = time.time() - start
            matrix = build_matrix(
                now,
                args.grid_width,
                args.grid_height,
                args.heart_rate,
                args.amplitude,
                args.baseline,
                args.noise,
                args.drift_speed,
            )

            frame = encode_text_frame(args.header, now, matrix)
            payload = (frame + "\n").encode("utf-8")

            if args.mode == "udp":
                send_udp(args.host, args.port, payload)
            else:
                tcp_sender.send(payload)

            if fp:
                fp.write(frame + "\n")

            frame_count += 1
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n手动停止发送")
    finally:
        if tcp_sender:
            tcp_sender.close()
        if fp:
            fp.flush()
            fp.close()

    print(f"发送完成，共发送 {frame_count} 帧")


if __name__ == "__main__":
    main()
