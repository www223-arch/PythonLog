# Python上位机 - 开发与架构手册

本文档面向开发者，目标是防止“新增串口功能后影响 UDP”这类回归，并指导后续扩展。

## 文档导航

- 详细开发指南（推荐先读）：[docs/developer_guide.md](docs/developer_guide.md)
- 学习路径（面向新人）：[docs/learning_guide.md](docs/learning_guide.md)

说明：
- 本文档强调架构约束与回归风险。
- `docs/developer_guide.md` 提供更完整的“新增功能/调试/规范/清单”执行手册。

## 结论先行

你的分层思路本身是对的，但当前代码中存在边界泄漏，导致跨数据源回归风险：

1. UI 层包含了部分数据域规则（例如通道自动创建、通道名归一化处理时机）。
2. DataSourceManager 同时承担协议适配、业务状态、持久化触发，职责偏重。
3. 一些协议分支通过 hasattr 动态判断，契约不够强，新增协议时容易误伤已有路径。
4. 仍有零散调试逻辑与历史状态管理并存，增加维护复杂度。

结论不是“框架无效”，而是“框架定义存在，但执行没有完全收敛到统一契约”。

## 当前分层模型（必须遵守）

### L1. 传输层（Transport）
职责：从设备/网络读取原始字节。

- UDP socket
- serial 串口

约束：
- 不做业务状态更新。
- 不操作 UI。
- 不管理通道显示名。

### L2. 协议层（Protocol Parser）
职责：把原始字节解析成统一帧。

实现原则：
- 协议层允许按数据源类型选择解析规则（UDP 文本解析、串口文本解析、Justfloat 解析、Rawdata 透传）。
- 解析分支只在协议层内部发生，向上层暴露的结果必须是统一帧语义。
- Justfloat 需要同时支持两种模式并统一时间语义：
- Justfloat（带时间戳）：帧尾前最后一个 float 作为时间戳（ms）。
- Justfloat（无时间戳）：时间戳由数据点计数器和用户配置的 Δt 推算。

统一帧建议：

```python
{
    "header": str,
    "timestamp": float,  # ms
    "channels": {"channel1": 1.23, "channel2": 2.34},
    "meta": {...}
}
```

约束：
- 协议层只负责解析，不做 UI 命名策略。
- 解析失败返回明确错误标识，不抛到 UI。

### L3. 数据域层（Domain / Manager）
职责：跨协议统一业务规则。

- 校验头判定
- 通道名映射与重命名
- 通道集合管理
- 缓冲与保存触发

约束：
- 所有“通道名最终态”规则只允许在此层定义。
- UI 只能消费最终显示名，不能重复实现命名策略。

### L4. 应用编排层（Application）
职责：线程、队列、状态机、节流。

- 数据接收线程
- 队列背压策略
- 状态机事件派发

约束：
- 不解析协议。
- 不维护额外的通道命名真相源。

### L5. 表现层（UI）
职责：显示与交互。

- 波形绘制
- 频域分析
- 用户重命名输入

约束：
- UI 不存储业务真相，只持有显示状态。
- UI 触发的命令（重命名、改色）应走 Domain API。

## 单一真相源（SSOT）原则

以下状态只能存在一个真相源：

1. 当前数据源连接对象：DataSourceManager.current_source。
2. 通道最终显示名映射：DataSourceManager.channel_name_mapping。
3. 通道列表：DataSourceManager.channels（UI 读取，不反向定义）。
4. 保存状态：DataSourceManager.data_saver。

禁止在 UI 层维护另一套同义状态并与 Manager 双向同步。

## 扩展新数据源的标准流程

1. 在 src/data_sources/base.py 的契约下实现新 DataSource。
2. 仅返回原始协议可解析的数据，不改 UI 命名。
3. 在 manager.read_data 中接入统一帧转换。
4. 在 main.py 仅增加配置入口，不增加协议判断分叉业务。
5. 补充回归测试矩阵（见下文）。

## 回归测试矩阵（每次改动必跑）

### 数据源切换
- UDP -> 串口 -> UDP，连接/断开状态正确。
- 串口不同协议切换（文本/Justfloat/Rawdata）无残留状态。

### 通道行为
- 自动建通道正确。
- Justfloat 重命名一次、二次、多次均不回生旧通道。
- 通道颜色与图例一致。

### 性能与稳定性
- 原始数据显示关闭时，吞吐不明显下降。
- 队列满时丢最旧保最新策略生效。
- 暂停/恢复不影响接收线程稳定。

### 保存
- 手动开启保存后 CSV 表头正确。
- 停止保存后文件句柄释放。

## 开发规范

### 代码组织
- 传输与协议逻辑放在 src/data_sources/。
- UI 绘图逻辑放在 src/visualization/。
- 主流程编排放在 src/main.py。

### 命名与注释
- 使用清晰英文符号名，中文用于界面文案。
- 只在复杂逻辑前写简短注释，避免噪声注释。

### 日志规范
- 高频链路默认禁止逐包 print。
- 调试日志必须可开关。
- 异常日志保留，正常路径日志最小化。

### 兼容性规范
- 新增协议不得修改其他协议默认行为。
- 任何跨层调用都要先检查是否破坏 SSOT。

### Bug记录规范（强制）
- 每次修复 Bug，必须同步更新 `BUGLIST.md`，禁止只改代码不留分析记录。
- 记录模板必须包含：现象、复现条件、分析过程、根因结论、修复方案、验证结果、影响范围。
- 若修复涉及协议/时间戳/队列/状态机，必须补充对应回归测试并在记录中写明测试名称。
- 合并前评审需要检查：代码改动、测试改动、`BUGLIST.md` 三者是否一致。

## 建议的短期重构路线

1. 将 manager.read_data 输出改为统一帧结构（header/timestamp/channels/meta）。
2. 将 main.update_data 中通道自动创建逻辑收敛为一个私有方法。
3. 将 ConnectionStateManager 与 StateMachine 收敛为单一状态系统，避免双轨维护。
4. 为 DataSource 增加能力声明接口（例如 supports_channel_names），替代 hasattr 分支。

## 当前功能状态（开发视角）

- 已支持 UDP、TCP、串口、文件数据源。
- USB CDC / 串口转TTL设备统一按串口数据源接入，避免重复数据源抽象。
- 文件数据源支持 `.log/.bin` 回放，并沿用统一帧链路（read_frame -> FSM/UI）。
- 已支持统一发送入口（DataSource.send_data）：串口/UDP/TCP可发送，文件源不支持发送。
- 已实现高吞吐批处理与 UI 限频。
- 已实现通道重命名映射链式收敛。
- 已支持原始数据区降载开关。
- 已具备实时性能指标显示。
- 已完成 main.py 第一阶段分层重构：连接流程拆分为 _connect_flow/_disconnect_flow，数据消费拆分为 _extract_waveform_data/_ensure_waveform_channels/_update_waveform_from_packet（功能保持不变）。
- 已完成 DataSourceManager 第二阶段分层重构：新增统一帧接口 read_frame()（header/timestamp/channels/meta），read_data() 作为兼容适配层保留旧行为。
- 已完成第三阶段主路径切换：DataReceiveThread 改为消费 read_frame()，UI 侧兼容统一帧与旧扁平字典。
- 已新增最小回归测试: tests/test_regression_layering.py，覆盖切源状态清理、Justfloat多次重命名收敛、read_frame/read_data兼容、read_frame路径CSV保存。

## 提交流程建议

1. 先修改单层代码，再跑回归矩阵。
2. 提交信息包含：影响层、回归范围、验证结果。
3. 合并前检查 README.md 与 README_DEV.md 是否同步。

## 回归测试命令

```bash
python -m unittest tests/test_regression_layering.py
```
