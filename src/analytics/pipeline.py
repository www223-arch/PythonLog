"""动脉健康分析管线。"""

from collections import deque
from typing import Deque, Dict, Optional

import numpy as np

from .contracts import AnalysisResult
from .heatmap.pressure_grid_adapter import PressureGridAdapter
from .ml.feature_extractor import FeatureExtractor
from .ml.model_runner import ModelRunner


class ArterialHealthPipeline:
    """动脉压力分析管线。

    默认可关闭；关闭时不产生任何分析结果。
    """

    def __init__(
        self,
        enabled: bool = False,
        grid_width: int = 16,
        grid_height: int = 16,
        analysis_stride: int = 1,
        history_size: int = 120,
        model_path: str = "",
    ):
        self.enabled = bool(enabled)
        self.analysis_stride = max(1, int(analysis_stride))
        self.frame_index = 0
        self.latest_result: Optional[AnalysisResult] = None

        self.adapter = PressureGridAdapter(grid_width=grid_width, grid_height=grid_height)
        self.extractor = FeatureExtractor()
        self.runner = ModelRunner(model_path=model_path)

        self.matrix_history: Deque[np.ndarray] = deque(maxlen=max(10, int(history_size)))
        self.time_history: Deque[float] = deque(maxlen=max(10, int(history_size)))

    def reset(self) -> None:
        self.frame_index = 0
        self.latest_result = None
        self.matrix_history.clear()
        self.time_history.clear()

    def submit_frame(self, frame: Dict[str, object]) -> Optional[AnalysisResult]:
        if not self.enabled:
            return None

        if not isinstance(frame, dict):
            return None

        meta = frame.get("meta", {}) or {}
        if bool(meta.get("format_error")):
            return None

        channels = frame.get("channels", {}) or {}
        if not channels:
            return None

        matrix = self.adapter.build_matrix(channels)
        if matrix is None:
            return None

        timestamp = float(frame.get("timestamp", 0.0))
        self.matrix_history.append(matrix)
        self.time_history.append(timestamp)
        self.frame_index += 1

        if self.frame_index % self.analysis_stride != 0:
            return None

        metrics = self._compute_metrics()
        features = self.extractor.extract_from_sequence(list(self.matrix_history), metrics)
        prediction = self.runner.predict(features, metrics)

        result: AnalysisResult = {
            "timestamp": timestamp,
            "heatmap": {
                "matrix": matrix,
                "x_axis": list(range(matrix.shape[1])),
                "y_axis": list(range(matrix.shape[0])),
                "meta": {
                    "grid_width": matrix.shape[1],
                    "grid_height": matrix.shape[0],
                },
            },
            "metrics": metrics,
            "features": {
                "values": features,
                "window": {
                    "history": len(self.matrix_history),
                },
            },
            "prediction": prediction,
            "health": {
                "warnings": [],
            },
        }

        self.latest_result = result
        return result

    def get_latest_result(self) -> Optional[AnalysisResult]:
        return self.latest_result

    def get_model_status(self) -> Dict[str, object]:
        return self.runner.get_status()

    def _compute_metrics(self) -> Dict[str, float]:
        if not self.matrix_history:
            return {
                "bpm": 0.0,
                "amplitude": 0.0,
                "consistency": 0.0,
                "repeatability": 0.0,
            }

        # 使用每帧平均压力序列做时间域分析
        mean_series = []
        for matrix in self.matrix_history:
            valid = matrix[~np.isnan(matrix)]
            mean_series.append(float(np.mean(valid)) if valid.size > 0 else 0.0)
        signal = np.asarray(mean_series, dtype=np.float32)

        amplitude = float(np.max(signal) - np.min(signal)) if signal.size > 0 else 0.0
        bpm = self._estimate_bpm(signal, list(self.time_history))

        latest = np.asarray(self.matrix_history[-1], dtype=np.float32)
        valid = latest[~np.isnan(latest)]
        if valid.size > 0:
            cv = float(np.std(valid) / (abs(np.mean(valid)) + 1e-6))
            consistency = float(np.clip(1.0 - cv, 0.0, 1.0))
        else:
            consistency = 0.0

        repeatability = self._estimate_repeatability()

        return {
            "bpm": float(bpm),
            "amplitude": float(amplitude),
            "consistency": float(consistency),
            "repeatability": float(repeatability),
        }

    def _estimate_bpm(self, signal: np.ndarray, timestamps: list) -> float:
        if signal.size < 5 or len(timestamps) < 5:
            return 0.0

        peaks = self._find_peaks(signal)
        if len(peaks) < 2:
            return 0.0

        peak_times = [timestamps[i] for i in peaks if i < len(timestamps)]
        if len(peak_times) < 2:
            return 0.0

        intervals_ms = [
            peak_times[i] - peak_times[i - 1]
            for i in range(1, len(peak_times))
            if peak_times[i] > peak_times[i - 1]
        ]
        if not intervals_ms:
            return 0.0

        median_interval_ms = float(np.median(intervals_ms))
        if median_interval_ms <= 0:
            return 0.0

        return float(60000.0 / median_interval_ms)

    def _find_peaks(self, signal: np.ndarray) -> list:
        peaks = []
        if signal.size < 3:
            return peaks

        threshold = float(np.mean(signal) + 0.25 * np.std(signal))
        for i in range(1, len(signal) - 1):
            if signal[i] > signal[i - 1] and signal[i] >= signal[i + 1] and signal[i] >= threshold:
                peaks.append(i)
        return peaks

    def _estimate_repeatability(self) -> float:
        if len(self.matrix_history) < 2:
            return 0.0

        a = np.nan_to_num(np.asarray(self.matrix_history[-1], dtype=np.float32), nan=0.0).reshape(-1)
        b = np.nan_to_num(np.asarray(self.matrix_history[-2], dtype=np.float32), nan=0.0).reshape(-1)
        if a.size == 0 or b.size == 0:
            return 0.0

        if np.std(a) < 1e-9 or np.std(b) < 1e-9:
            return 0.0

        corr = float(np.corrcoef(a, b)[0, 1])
        if np.isnan(corr):
            return 0.0
        return float(np.clip((corr + 1.0) / 2.0, 0.0, 1.0))
