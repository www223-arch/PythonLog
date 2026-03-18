"""动脉压力模型训练脚本。"""

import os
import sys

# 允许从项目根目录直接执行: python tools/train_arterial_model.py
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_ROOT = os.path.join(PROJECT_ROOT, "src")
if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)

from analytics.ml.training_service import build_arg_parser, run_training


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    result = run_training(args)
    print(result.get("stdout", ""))


if __name__ == "__main__":
    main()
