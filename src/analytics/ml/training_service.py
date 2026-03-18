"""动脉压力模型训练服务。"""

import argparse
import json
import os
from typing import Dict

import joblib
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="训练动脉压力分类模型")
    parser.add_argument("--input", type=str, default="data/arterial_train_dataset.csv", help="输入CSV")
    parser.add_argument("--model-output", type=str, default="data/models/arterial_rf.joblib", help="模型输出路径")
    parser.add_argument("--meta-output", type=str, default="data/models/arterial_rf_meta.json", help="元信息输出路径")
    parser.add_argument(
        "--model-type",
        type=str,
        default="rf",
        choices=["rf", "logreg", "svm", "gbdt"],
        help="模型类型: rf/logreg/svm/gbdt",
    )
    parser.add_argument("--test-size", type=float, default=0.2, help="测试集比例")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    parser.add_argument("--rf-n-estimators", type=int, default=220, help="随机森林树数量")
    parser.add_argument("--rf-max-depth", type=int, default=10, help="随机森林最大深度")
    parser.add_argument("--rf-min-samples-leaf", type=int, default=2, help="随机森林叶节点最小样本")
    parser.add_argument("--logreg-max-iter", type=int, default=1500, help="逻辑回归最大迭代")
    parser.add_argument("--logreg-c", type=float, default=1.0, help="逻辑回归正则强度倒数C")
    parser.add_argument("--svm-c", type=float, default=1.0, help="SVM参数C")
    parser.add_argument("--svm-gamma", type=str, default="scale", help="SVM参数gamma")
    parser.add_argument("--gbdt-n-estimators", type=int, default=100, help="GBDT弱学习器数量")
    parser.add_argument("--gbdt-learning-rate", type=float, default=0.1, help="GBDT学习率")
    parser.add_argument("--gbdt-max-depth", type=int, default=3, help="GBDT基学习器最大深度")
    return parser


def build_model(args: argparse.Namespace):
    model_type = args.model_type
    if model_type == "rf":
        return RandomForestClassifier(
            n_estimators=args.rf_n_estimators,
            max_depth=args.rf_max_depth,
            min_samples_leaf=args.rf_min_samples_leaf,
            random_state=args.seed,
        )
    if model_type == "logreg":
        return make_pipeline(
            StandardScaler(),
            LogisticRegression(
                max_iter=args.logreg_max_iter,
                C=args.logreg_c,
                random_state=args.seed,
            ),
        )
    if model_type == "svm":
        return make_pipeline(
            StandardScaler(),
            SVC(
                kernel="rbf",
                C=args.svm_c,
                gamma=args.svm_gamma,
                probability=True,
                random_state=args.seed,
            ),
        )
    if model_type == "gbdt":
        return GradientBoostingClassifier(
            n_estimators=args.gbdt_n_estimators,
            learning_rate=args.gbdt_learning_rate,
            max_depth=args.gbdt_max_depth,
            random_state=args.seed,
        )

    raise ValueError(f"不支持的模型类型: {model_type}")


def run_training(args: argparse.Namespace) -> Dict[str, str]:
    if not os.path.isfile(args.input):
        raise FileNotFoundError(f"输入文件不存在: {args.input}")

    df = pd.read_csv(args.input)
    if "label" not in df.columns:
        raise ValueError("输入CSV必须包含 label 列")

    feature_cols = [c for c in df.columns if c != "label"]
    x = df[feature_cols]
    y = df["label"]

    x_train, x_test, y_train, y_test = train_test_split(
        x,
        y,
        test_size=max(0.1, min(0.4, args.test_size)),
        random_state=args.seed,
        stratify=y,
    )

    model = build_model(args)
    model.fit(x_train, y_train)

    y_pred = model.predict(x_test)
    report = classification_report(y_test, y_pred, output_dict=True)
    matrix = confusion_matrix(y_test, y_pred).tolist()

    os.makedirs(os.path.dirname(args.model_output) or ".", exist_ok=True)
    os.makedirs(os.path.dirname(args.meta_output) or ".", exist_ok=True)

    bundle = {
        "model": model,
        "feature_order": feature_cols,
        "model_type": args.model_type,
        "classes": list(getattr(model, "classes_", [])),
    }
    joblib.dump(bundle, args.model_output)

    meta = {
        "model_type": args.model_type,
        "feature_order": feature_cols,
        "classes": list(getattr(model, "classes_", [])),
        "metrics": report,
        "confusion_matrix": matrix,
        "input": args.input,
    }
    with open(args.meta_output, "w", encoding="utf-8") as fp:
        json.dump(meta, fp, ensure_ascii=False, indent=2)

    report_text = classification_report(y_test, y_pred)
    stdout = "\n".join(
        [
            f"训练完成，模型已保存: {args.model_output}",
            f"元信息已保存: {args.meta_output}",
            f"模型类型: {args.model_type}",
            "测试集分类报告:",
            report_text,
        ]
    )
    return {
        "stdout": stdout,
        "report_text": report_text,
    }
