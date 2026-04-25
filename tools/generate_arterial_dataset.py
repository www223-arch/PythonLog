"""生成动脉压力训练数据集。

输出CSV包含特征列与label列，可直接供训练脚本使用。
"""

import argparse
import csv
import math
import os
import random
from typing import Dict, List

import numpy as np


def synth_matrix(
    t: float,
    width: int,
    height: int,
    heart_rate: float,
    amplitude: float,
    baseline: float,
    noise: float,
) -> np.ndarray:
    matrix = np.zeros((height, width), dtype=np.float32)
    pulse = 0.5 * (1.0 + math.sin(2.0 * math.pi * (heart_rate / 60.0) * t))
    cx = (width - 1) * 0.5
    cy = (height - 1) * 0.5
    sx = max(1.0, width * 0.18)
    sy = max(1.0, height * 0.16)

    for r in range(height):
        for c in range(width):
            dx = (c - cx) / sx
            dy = (r - cy) / sy
            spatial = math.exp(-0.5 * (dx * dx + dy * dy))
            value = baseline + amplitude * pulse * spatial + random.uniform(-noise, noise)
            matrix[r, c] = float(value)
    return matrix


def extract_features(matrix_seq: List[np.ndarray], heart_rate: float) -> Dict[str, float]:
    latest = matrix_seq[-1]
    valid = latest.reshape(-1)

    features = {
        "mean_pressure": float(np.mean(valid)),
        "std_pressure": float(np.std(valid)),
        "max_pressure": float(np.max(valid)),
        "min_pressure": float(np.min(valid)),
        "rms_pressure": float(np.sqrt(np.mean(valid * valid))),
        "bpm_hint": float(heart_rate),
    }

    th = float(np.quantile(valid, 0.85))
    features["high_area_ratio"] = float(np.mean(valid >= th))

    total = float(np.sum(latest))
    if total > 1e-6:
        h, w = latest.shape
        ys, xs = np.mgrid[0:h, 0:w]
        features["centroid_x"] = float(np.sum(xs * latest) / total)
        features["centroid_y"] = float(np.sum(ys * latest) / total)
    else:
        features["centroid_x"] = 0.0
        features["centroid_y"] = 0.0

    series = np.array([float(np.mean(m)) for m in matrix_seq], dtype=np.float32)
    features["amplitude"] = float(np.max(series) - np.min(series))
    features["series_std"] = float(np.std(series))
    return features


def sample_params(label: str):
    if label == "healthy":
        return {
            "heart_rate": random.uniform(60, 90),
            "amplitude": random.uniform(30, 50),
            "baseline": random.uniform(15, 30),
            "noise": random.uniform(0.8, 2.0),
        }
    if label == "watch":
        return {
            "heart_rate": random.uniform(90, 120),
            "amplitude": random.uniform(20, 38),
            "baseline": random.uniform(12, 28),
            "noise": random.uniform(1.5, 3.0),
        }
    return {
        "heart_rate": random.uniform(35, 58),
        "amplitude": random.uniform(8, 25),
        "baseline": random.uniform(8, 24),
        "noise": random.uniform(2.5, 6.0),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="生成动脉压力训练数据集")
    parser.add_argument("--output", type=str, default="data/arterial_train_dataset.csv", help="输出CSV路径")
    parser.add_argument("--samples", type=int, default=1500, help="总样本数")
    parser.add_argument("--grid-width", type=int, default=16, help="点阵宽度")
    parser.add_argument("--grid-height", type=int, default=16, help="点阵高度")
    parser.add_argument("--seq-len", type=int, default=24, help="每样本序列长度")
    parser.add_argument("--rate", type=float, default=30.0, help="模拟采样率Hz")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    args = parser.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)

    labels = ["healthy", "watch", "risk"]
    rows = []

    for i in range(args.samples):
        label = labels[i % len(labels)]
        params = sample_params(label)

        seq = []
        for k in range(args.seq_len):
            t = k / max(1.0, args.rate)
            seq.append(
                synth_matrix(
                    t=t,
                    width=args.grid_width,
                    height=args.grid_height,
                    heart_rate=params["heart_rate"],
                    amplitude=params["amplitude"],
                    baseline=params["baseline"],
                    noise=params["noise"],
                )
            )

        feat = extract_features(seq, params["heart_rate"])
        feat["label"] = label
        rows.append(feat)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    fieldnames = sorted([k for k in rows[0].keys() if k != "label"]) + ["label"]
    with open(args.output, "w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    print(f"数据集生成完成: {args.output}")
    print(f"样本数: {len(rows)}")


if __name__ == "__main__":
    main()
