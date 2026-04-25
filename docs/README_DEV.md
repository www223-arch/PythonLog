# Python上位机 - 开发与架构手册

本文档面向开发者，目标是防止“新增串口功能后影响 UDP”这类回归，并指导后续扩展。

## 文档导航

- 详细开发指南（推荐先读）：[docs/developer_guide.md](docs/developer_guide.md)
- 学习路径（面向新人）：[docs/learning_guide.md](docs/learning_guide.md)
- C/C++开发者进化手册（项目实战版）：[docs/cpp_to_python_evolution_manual.md](docs/cpp_to_python_evolution_manual.md)
- 热力图/机器学习模块开发指南：[docs/heatmap_ml_module_guide.md](docs/heatmap_ml_module_guide.md)

说明：
- 本文档强调架构约束与回归风险。
- `docs/developer_guide.md` 提供更完整的“新增功能/调试/规范/清单”执行手册。

## 近期架构演进（2026-03）

- `src/main.py` 已收敛为薄入口，仅负责启动应用。
- 主窗口编排主实现迁移到 `src/app_window.py`。
- `src/core/` 已形成职责模块化：
    - `dock_topmost_mixin.py`：浮动页置顶与层级管理。
    - `dock_layout_mixin.py`：Dock 布局、工具栏、事件联动。
    - `connection_flow_mixin.py`：连接/断开编排与配置路由。
    - `raw_data_mixin.py`：原始数据区、发送区与缓冲刷新。
    - `channel_menu_mixin.py`：通道菜单、改色与重命名。
    - `receive_thread.py`、`widgets.py`：接收线程与通用组件。
- 状态机已与 UI 控件解耦：
    - `connection_fsm.py` 输出 `StateViewModel`。
    - `app_window.py` 通过 `apply_fsm_view` 统一渲染状态。
- 数据源实例化已从连接编排中下沉：
    - 新增 `core/data_source_factory.py`。
    - `connection_flow_mixin.py` 保留 UI 配置校验与流程控制。


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
- Dock 拖拽/浮动与工具栏交互
- 浮动页返回/图钉置顶交互

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
- 主流程编排放在 src/app_window.py 与 src/core/。
- src/main.py 仅保留入口，不承载业务逻辑。

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
- 已实现 Dock 三面板布局：拖拽重排、浮动分离、图标化锁定/复原。
- 已实现浮动页右上角返回/图钉控制。
- 已实现钉住页状态机：唯一钉住页、跨应用置顶重申、取消钉住恢复普通层级。
- 已实现钉住页防停靠机制：钉住时禁止停靠，避免“先停靠再弹回”视觉抖动。
- 已实现时域"跟随最新"图标开关：开启时自动调整一次视图，随后用户可自由缩放。
- 已实现波特图分析功能：位于可视化层，支持选择输入/输出通道，通过FFT计算频率响应并显示幅值(dB)和相位(度)曲线，采样率自动适配（有Δt配置时优先使用，无则从时间戳估算）。
- 已完成主窗口拆分：连接流程、原始数据、通道菜单、Dock 行为均已迁入 core mixin。
- 已完成 DataSourceManager 第二阶段分层重构：新增统一帧接口 read_frame()（header/timestamp/channels/meta），read_data() 作为兼容适配层保留旧行为。
- 已完成第三阶段主路径切换：DataReceiveThread 改为消费 read_frame()，UI 侧兼容统一帧与旧扁平字典。
- 已完成 FSM->UI 解耦：状态层不直接访问控件，改由视图模型下发。
- 已完成数据源构建下沉：connection_flow 仅编排，factory 负责实例化细节。
- 已新增最小回归测试: tests/test_regression_layering.py，覆盖切源状态清理、Justfloat多次重命名收敛、read_frame/read_data兼容、read_frame路径CSV保存。

## 窗口层级实现备注

1. 钉住页置顶
- 采用 Qt 与 Win32 双层重申策略：
- Qt 侧：QWindow 级 `WindowStaysOnTopHint`（避免直接对 QDockWidget 调整 QWidget flags 引发副作用）。
- Win32 侧：`SetWindowPos(HWND_NOTOPMOST -> HWND_TOPMOST)` + owner/transient 修正。

2. 状态机与清理策略
- `_pinned_dock` 仅在“主动取消置顶”或“主动返回主布局”时清空。
- 避免在短暂可见性/浮动态抖动时误清空，防止守护链断开。

3. 调试开关
- 窗口层级诊断日志通过环境变量启用：`PYTHONLOG_WIN_DEBUG=1`。

## 提交流程建议

1. 先修改单层代码，再跑回归矩阵。
2. 提交信息包含：影响层、回归范围、验证结果。
3. 合并前检查 README.md 与 README_DEV.md 是否同步。

## 打包规范（跨机器可用）

1. 首选脚本
- 使用项目根目录 `build_reliable.bat`，不要依赖个人机器的绝对路径。

2. 脚本约定
- 自动查找或创建虚拟环境（优先 `.venv`，其次 `venv`）。
- 使用 `python -m PyInstaller main.spec`，避免 PATH 下 `pyinstaller` 命令缺失。

3. 产物与验收
- 产物默认在 `dist/Python上位机.exe`。
- 提交前至少在干净环境跑一次脚本，确保克隆后可直接打包。

## 打包常见问题（维护者视角）

1. 脚本报找不到 Python
- 先在终端确认：`py --version` 和 `python --version`。
- 若都失败，属于机器环境问题，不是项目代码问题。

2. 依赖安装失败
- 优先检查网络与 pip 配置。
- 建议先执行：`python -m pip install --upgrade pip` 再重试。

3. EXE 启动即退出
- 先清理旧产物后重打包（`build/`、`dist/`）。
- 在终端直接运行 `dist/Python上位机.exe` 读取错误输出。
- 排查杀软隔离与系统权限问题。

4. 新增依赖后打包异常
- 必须同步更新 `requirements.txt`。
- 如为动态导入模块，必要时补充到 `main.spec` 的 hiddenimports。

5. 机器间“我这里能打，别人不行”
- 优先核对 Python 版本与架构（建议统一 x64）。
- 要求按项目脚本打包，不允许使用个人本地硬编码路径。

## 回归测试命令

```bash
python -m unittest tests/test_regression_layering.py
```
