"""压力点阵适配器。"""

import re
from typing import Dict, Optional

import numpy as np


class PressureGridAdapter:
    """将通道字典重排为二维压力矩阵。"""

    def __init__(self, grid_width: int, grid_height: int, completeness_threshold: float = 1.0):
        self.grid_width = max(1, int(grid_width))
        self.grid_height = max(1, int(grid_height))
        self.point_count = self.grid_width * self.grid_height
        self.completeness_threshold = max(0.1, min(1.0, float(completeness_threshold)))
        self._pattern = re.compile(r"^p_(\d+)_(\d+)$")

    def build_matrix(self, channels: Dict[str, float]) -> Optional[np.ndarray]:
        """构建二维压力矩阵。

        优先解析 p_row_col 命名；若不存在该命名则尝试顺序通道兜底。
        """
        if not channels:
            return None

        matrix = np.full((self.grid_height, self.grid_width), np.nan, dtype=np.float32)
        filled = 0

        for key, value in channels.items():
            match = self._pattern.match(str(key))
            if not match:
                continue

            row = int(match.group(1))
            col = int(match.group(2))
            if row < 0 or row >= self.grid_height or col < 0 or col >= self.grid_width:
                continue

            matrix[row, col] = float(value)
            filled += 1

        if filled == 0:
            return self._fallback_from_sequential_channels(channels)

        coverage = filled / float(self.point_count)
        if coverage < self.completeness_threshold:
            return None

        return matrix

    def _fallback_from_sequential_channels(self, channels: Dict[str, float]) -> Optional[np.ndarray]:
        """顺序通道兜底：按 key 排序后前 point_count 个值映射为点阵。"""
        if len(channels) < self.point_count:
            return None

        matrix = np.zeros((self.grid_height, self.grid_width), dtype=np.float32)
        values = [float(channels[k]) for k in sorted(channels.keys())[: self.point_count]]

        for idx, value in enumerate(values):
            row = idx // self.grid_width
            col = idx % self.grid_width
            matrix[row, col] = value

        return matrix
