"""特征提取器。"""

from typing import Dict, List, Optional

import numpy as np


class FeatureExtractor:
    """从压力矩阵提取可用于推理的特征。"""

    def __init__(self, high_pressure_quantile: float = 0.85):
        self.high_pressure_quantile = max(0.5, min(0.99, float(high_pressure_quantile)))

    def extract_from_sequence(
        self,
        matrices: List[np.ndarray],
        metrics: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        if not matrices:
            return {}

        latest = np.asarray(matrices[-1], dtype=np.float32)
        valid = latest[~np.isnan(latest)]
        if valid.size == 0:
            return {}

        features = {
            "mean_pressure": float(np.mean(valid)),
            "std_pressure": float(np.std(valid)),
            "max_pressure": float(np.max(valid)),
            "min_pressure": float(np.min(valid)),
            "rms_pressure": float(np.sqrt(np.mean(np.square(valid)))),
        }

        threshold = float(np.quantile(valid, self.high_pressure_quantile))
        high_area_ratio = float(np.mean(valid >= threshold))
        features["high_area_ratio"] = high_area_ratio

        # 压力重心
        filled = np.nan_to_num(latest, nan=0.0)
        total = float(np.sum(filled))
        if total > 1e-9:
            h, w = filled.shape
            ys, xs = np.mgrid[0:h, 0:w]
            cx = float(np.sum(xs * filled) / total)
            cy = float(np.sum(ys * filled) / total)
        else:
            cx = 0.0
            cy = 0.0
        features["centroid_x"] = cx
        features["centroid_y"] = cy

        if len(matrices) >= 2:
            prev = np.nan_to_num(np.asarray(matrices[-2], dtype=np.float32), nan=0.0)
            curr = np.nan_to_num(latest, nan=0.0)
            features["frame_delta_mean"] = float(np.mean(np.abs(curr - prev)))
        else:
            features["frame_delta_mean"] = 0.0

        if metrics:
            for key in ("bpm", "amplitude", "consistency", "repeatability"):
                if key in metrics:
                    features[key] = float(metrics[key])

        return features
