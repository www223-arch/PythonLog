"""动脉压力模型训练脚本。"""

import argparse
import json
import os

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import train_test_split


def main() -> None:
    parser = argparse.ArgumentParser(description="训练动脉压力分类模型")
    parser.add_argument("--input", type=str, default="data/arterial_train_dataset.csv", help="输入CSV")
    parser.add_argument("--model-output", type=str, default="data/models/arterial_rf.joblib", help="模型输出路径")
    parser.add_argument("--meta-output", type=str, default="data/models/arterial_rf_meta.json", help="元信息输出路径")
    parser.add_argument("--test-size", type=float, default=0.2, help="测试集比例")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    args = parser.parse_args()

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

    model = RandomForestClassifier(
        n_estimators=220,
        max_depth=10,
        min_samples_leaf=2,
        random_state=args.seed,
    )
    model.fit(x_train, y_train)

    y_pred = model.predict(x_test)
    report = classification_report(y_test, y_pred, output_dict=True)
    matrix = confusion_matrix(y_test, y_pred).tolist()

    os.makedirs(os.path.dirname(args.model_output) or ".", exist_ok=True)
    os.makedirs(os.path.dirname(args.meta_output) or ".", exist_ok=True)

    joblib.dump(model, args.model_output)

    meta = {
        "model_type": "RandomForestClassifier",
        "feature_order": feature_cols,
        "classes": list(model.classes_),
        "metrics": report,
        "confusion_matrix": matrix,
        "input": args.input,
    }
    with open(args.meta_output, "w", encoding="utf-8") as fp:
        json.dump(meta, fp, ensure_ascii=False, indent=2)

    print(f"训练完成，模型已保存: {args.model_output}")
    print(f"元信息已保存: {args.meta_output}")
    print("测试集分类报告:")
    print(classification_report(y_test, y_pred))


if __name__ == "__main__":
    main()
