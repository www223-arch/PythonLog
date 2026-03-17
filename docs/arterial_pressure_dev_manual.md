# 动脉压力模块开发指导手册

本文档用于指导开发人员按统一流程实现“动脉压力二维分布 + 健康评估”。

## 1. 开发原则

- 最小侵入：不改数据源协议逻辑，不破坏现有波形链路。
- 旁路分析：分析计算不阻塞接收线程。
- 默认关闭：新模块默认禁用，逐步灰度开启。
- 可降级：模型不可用时回落规则评估。

## 2. 代码结构

建议结构：

```text
src/analytics/
  __init__.py
  contracts.py
  pipeline.py
  heatmap/
    __init__.py
    pressure_grid_adapter.py
  ml/
    __init__.py
    feature_extractor.py
    model_runner.py
```

## 3. 输入输出约定

输入帧：

- 使用 Manager 统一帧。
- 关键字段：`timestamp`、`channels`、`meta.format_error`。

输出结果：

- pressure_matrix
- metrics（bpm、amplitude、一致性、重复性）
- prediction（label、score、risk_level）

## 4. 开发步骤

1. 先完成点阵适配器

- 输入 channels。
- 输出 HxW 压力矩阵。
- 校验点数是否完整。

2. 再完成分析管线

- 接收帧。
- 过滤错帧。
- 产出基础指标。

3. 再完成特征与模型

- 特征提取先做简单统计。
- 模型先支持规则降级。
- 外部模型加载失败不抛出到 UI。

4. 最后接入主窗口

- 在 `update_data` 中提交分析帧。
- 断开连接时重置分析缓存。

## 5. 配置建议

- `analysis_enabled`: false
- `grid_width`: 16
- `grid_height`: 16
- `analysis_stride`: 1
- `model_path`: 空

## 6. 测试清单

单元测试：

- 适配器解析正确。
- 缺失点位处理正确。
- 指标输出字段完整。
- 默认关闭时不产出结果。

集成测试：

- 不影响现有 `tests/test_regression_layering.py`。
- 开启后可持续产出分析结果。
- 断连后状态被重置。

## 7. 交付要求

- 文档、代码、测试同时提交。
- 新增配置必须有默认值。
- 关键错误日志必须可开关。
