"""模型运行器。"""

import os
from typing import Any, Dict, List, Optional

import pandas as pd


class ModelRunner:
    """机器学习推理运行器。

    默认走规则推理；若提供可用模型文件，则走外部模型推理。
    """

    SUPPORTED_MODEL_TYPES = {
        "auto",
        "rule",
        "random_forest",
        "logistic_regression",
        "svm",
        "gradient_boosting",
    }

    def __init__(
        self,
        model_path: str = "",
        feature_order: Optional[List[str]] = None,
        model_preference: str = "auto",
    ):
        self.model_path = model_path or ""
        self.feature_order = list(feature_order or [])
        self.model = None
        self.model_mode = "rule"
        self.load_error = ""
        self.detected_model_type = "unknown"
        self.model_preference = self._normalize_model_preference(model_preference)
        self._try_load_model()

    def _normalize_model_preference(self, preference: str) -> str:
        value = str(preference or "auto").strip().lower()
        return value if value in self.SUPPORTED_MODEL_TYPES else "auto"

    def _try_load_model(self) -> None:
        if self.model_preference == "rule":
            self.model_mode = "rule"
            self.model = None
            self.load_error = ""
            self.detected_model_type = "rule"
            return

        if not self.model_path:
            self.load_error = ""
            return

        if not os.path.isfile(self.model_path):
            self.load_error = "模型文件不存在"
            return

        try:
            import joblib

            loaded_obj = joblib.load(self.model_path)
            self.model = self._extract_model_from_loaded_object(loaded_obj)
            if self.model is None:
                self.model_mode = "rule"
                self.load_error = "模型文件内容无效: 未找到可用模型对象"
                self.detected_model_type = "unknown"
                return

            self.detected_model_type = self._detect_model_type(self.model)
            if self.model_preference not in ("auto", self.detected_model_type):
                self.model = None
                self.model_mode = "rule"
                self.load_error = f"模型类型不匹配: 期望 {self.model_preference}, 实际 {self.detected_model_type}"
                return

            self.model_mode = "external"
            self.load_error = ""
        except Exception as e:
            self.model = None
            self.model_mode = "rule"
            self.detected_model_type = "unknown"
            self.load_error = f"模型加载失败: {e}"

    def _extract_model_from_loaded_object(self, loaded_obj: Any):
        if isinstance(loaded_obj, dict) and "model" in loaded_obj:
            if not self.feature_order:
                feature_order = loaded_obj.get("feature_order", [])
                if isinstance(feature_order, list):
                    self.feature_order = [str(i) for i in feature_order]
            return loaded_obj.get("model")
        return loaded_obj

    def _detect_model_type(self, model: Any) -> str:
        if model is None:
            return "unknown"

        estimator_name = model.__class__.__name__.lower()
        if "randomforest" in estimator_name:
            return "random_forest"
        if "logisticregression" in estimator_name:
            return "logistic_regression"
        if estimator_name == "svc":
            return "svm"
        if "gradientboosting" in estimator_name:
            return "gradient_boosting"

        # 兼容 sklearn pipeline 场景，取最后一步估计器
        if hasattr(model, "steps") and isinstance(getattr(model, "steps"), list):
            try:
                last_estimator = model.steps[-1][1]
                return self._detect_model_type(last_estimator)
            except Exception:
                return "unknown"

        return "unknown"

    def get_status(self) -> Dict[str, object]:
        return {
            "mode": self.model_mode,
            "model_path": self.model_path,
            "has_model": self.model is not None,
            "load_error": self.load_error,
            "requested_model": self.model_preference,
            "detected_model": self.detected_model_type,
        }

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
                model_input = self._build_model_input(features)
                label = self.model.predict(model_input)[0]

                score = 0.8
                topk = []
                if hasattr(self.model, "predict_proba"):
                    probs = self.model.predict_proba(model_input)[0]
                    score = float(max(probs))
                    classes = list(getattr(self.model, "classes_", []))
                    if len(classes) == len(probs):
                        pairs = [(str(classes[i]), float(p)) for i, p in enumerate(probs)]
                    else:
                        pairs = [(str(i), float(p)) for i, p in enumerate(probs)]
                    topk = sorted(pairs, key=lambda x: x[1], reverse=True)[:3]

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

    def _build_model_input(self, features: Dict[str, float]):
        if self.feature_order:
            ordered_keys = list(self.feature_order)
        else:
            ordered_keys = sorted(features.keys())

        row = {k: float(features.get(k, 0.0)) for k in ordered_keys}
        # 使用带列名DataFrame，避免sklearn在训练带列名时推理报特征名告警。
        return pd.DataFrame([row], columns=ordered_keys)

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
