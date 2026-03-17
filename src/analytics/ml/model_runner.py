"""模型运行器。"""

import os
from typing import Dict, List, Optional


class ModelRunner:
    """机器学习推理运行器。

    默认走规则推理；若提供可用模型文件，则走外部模型推理。
    """

    def __init__(self, model_path: str = "", feature_order: Optional[List[str]] = None):
        self.model_path = model_path or ""
        self.feature_order = list(feature_order or [])
        self.model = None
        self.model_mode = "rule"
        self._try_load_model()

    def _try_load_model(self) -> None:
        if not self.model_path or not os.path.isfile(self.model_path):
            return

        try:
            import joblib

            self.model = joblib.load(self.model_path)
            self.model_mode = "external"
        except Exception:
            self.model = None
            self.model_mode = "rule"

    def predict(self, features: Dict[str, float], metrics: Optional[Dict[str, float]] = None) -> Dict[str, object]:
        if not features:
            return {
                "label": "unknown",
                "score": 0.0,
                "risk_level": "unknown",
                "topk": [],
                "anomaly": False,
                "mode": self.model_mode,
            }

        if self.model_mode == "external" and self.model is not None:
            try:
                vector = self._build_feature_vector(features)
                label = self.model.predict([vector])[0]

                score = 0.8
                topk = []
                if hasattr(self.model, "predict_proba"):
                    probs = self.model.predict_proba([vector])[0]
                    score = float(max(probs))
                    topk = sorted([(str(i), float(p)) for i, p in enumerate(probs)], key=lambda x: x[1], reverse=True)[:3]

                risk_level = self._score_to_risk(score)
                return {
                    "label": str(label),
                    "score": score,
                    "risk_level": risk_level,
                    "topk": topk,
                    "anomaly": risk_level == "high",
                    "mode": self.model_mode,
                }
            except Exception:
                # 外部模型推理失败时降级到规则模式
                pass

        return self._rule_predict(features, metrics or {})

    def _build_feature_vector(self, features: Dict[str, float]) -> List[float]:
        if self.feature_order:
            return [float(features.get(k, 0.0)) for k in self.feature_order]
        return [float(features[k]) for k in sorted(features.keys())]

    def _rule_predict(self, features: Dict[str, float], metrics: Dict[str, float]) -> Dict[str, object]:
        bpm = float(metrics.get("bpm", features.get("bpm", 0.0)))
        consistency = float(metrics.get("consistency", features.get("consistency", 0.0)))
        repeatability = float(metrics.get("repeatability", features.get("repeatability", 0.0)))

        bpm_score = 1.0 if 50.0 <= bpm <= 110.0 else 0.5
        consistency_score = max(0.0, min(1.0, consistency))
        repeatability_score = max(0.0, min(1.0, repeatability))

        score = float((bpm_score + consistency_score + repeatability_score) / 3.0)
        risk_level = self._score_to_risk(score)
        label = {
            "low": "healthy",
            "medium": "watch",
            "high": "risk",
        }[risk_level]

        return {
            "label": label,
            "score": score,
            "risk_level": risk_level,
            "topk": [(label, score)],
            "anomaly": risk_level == "high",
            "mode": "rule",
        }

    def _score_to_risk(self, score: float) -> str:
        if score >= 0.75:
            return "low"
        if score >= 0.5:
            return "medium"
        return "high"
