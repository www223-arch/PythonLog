# C/C++开发者进化手册（贴合本项目）

本文档面向“熟悉C/C++，但不习惯Python工程化开发”的开发者。
目标：读完后可以直接理解并维护本仓库代码，不再只会“照着改”。

---

## 1. 你需要先完成的思维切换

### 1.1 从“编译期中心”切到“运行期中心”

C/C++常见习惯：

- 先设计头文件/类型系统，再编译验证。
- 问题常在编译期暴露（类型不匹配、链接错误）。

Python项目现实：

- 语法层面更宽松，很多错误是运行时暴露。
- 你需要更依赖：
  - 分层边界
  - 测试
  - 日志
  - 类型注解（不是强制，但很有帮助）

在本项目里，防回归的核心不靠“编译器兜底”，而靠：

- 分层约束文档（见 `docs/developer_guide.md`）
- 回归测试（`tests/test_regression_layering.py`）
- SSOT（单一真相源）约束（主要在 `src/data_sources/manager.py`）

### 1.2 从“手工内存生命周期”切到“对象语义 + 资源约束”

C/C++里你关注：

- `new/delete`
- RAII
- copy/move

Python里你主要关注：

- 对象引用是否还被持有
- 资源是否明确关闭（socket/serial/file）
- 循环引用与长生命周期对象（GUI场景尤需注意）

本项目的资源清理点：

- 连接断开统一走 `ConnectionFlowMixin._disconnect_flow`
- 数据源关闭由 `DataSourceManager.disconnect` 负责
- 线程停止由 `stop_receive_thread` + `stop_event` 协作

你可以把它理解成“显式业务生命周期 + Python垃圾回收”。

---

## 2. Python语法与C/C++对照速查（只保留项目高频）

### 2.1 类与构造

C++：

```cpp
class Foo {
public:
    Foo(int x): x_(x) {}
private:
    int x_;
};
```

Python：

```python
class Foo:
    def __init__(self, x: int):
        self.x = x
```

要点：

- `self` 显式写出（类似隐式 `this` 的显式化）。
- 默认没有访问控制关键字（靠约定 `_name`）。

### 2.2 接口/抽象基类

C++常用纯虚函数；Python在本项目使用抽象基类约束：

- `src/data_sources/base.py` 定义数据源契约
- 各数据源实现 `connect/read_data/disconnect/send_data`

这相当于“运行时可替换的统一虚接口”。

### 2.3 枚举与状态

`src/core/connection_fsm.py` 使用 `Enum + State类 + 状态机矩阵`。

和C++状态模式对照：

- `StateMachine.handle_event` 相当于事件分发器
- `transition_matrix` 相当于状态转移表
- `StateViewModel` 把“状态层”与“UI层”解耦

### 2.4 异常替代错误码

Python大量使用 `try/except`。

在本项目中原则是：

- 高频链路不抛给UI（尽量转成可识别状态）
- 协议错误走 `format_error` 路径
- 真正异常日志按开关输出

### 2.5 动态类型不等于“随便写”

你会看到大量 `hasattr`、可选字段、字典结构。

本项目通过“统一帧结构”约束动态数据：

```python
{
    'header': str,
    'timestamp': float,
    'channels': {name: value},
    'meta': {'format_error': bool, 'protocol': str}
}
```

入口在 `DataSourceManager.read_frame`。

---

## 3. 本项目架构：按C/C++工程脑回路理解

把项目理解成五层流水线：

1. L1 传输层：socket/serial/file 读写原始字节
2. L2 协议层：把字节解析成结构化数据
3. L3 领域层：统一规则（通道映射、校验头、保存）
4. L4 编排层：线程、队列、状态机、连接流程
5. L5 UI层：展示与交互

对应代码：

- 传输/协议：`src/data_sources/*_source.py`
- 领域：`src/data_sources/manager.py`
- 编排：`src/core/connection_flow_mixin.py`、`src/core/receive_thread.py`
- 状态机：`src/core/connection_fsm.py`
- UI组装：`src/app_window.py`
- 薄入口：`src/main.py`

你可以把它类比为：

- C++里的 `driver/parser/service/app/ui` 分层。

关键是：不要跨层偷逻辑。

---

## 4. 先读懂这三条主链路

### 4.1 连接链路（Connect）

从UI点击连接开始：

1. `MainWindow.toggle_connection`
2. `ConnectionFlowMixin._connect_flow`
3. `_build_data_source_from_ui` 采集配置
4. `core/data_source_factory.py` 构建具体数据源
5. `DataSourceManager.set_source` 切换并连接
6. 启动 `DataReceiveThread`

理解点：

- 数据源实例化已经下沉到工厂，不要再把构建细节塞回UI。

### 4.2 接收链路（Receive）

高频核心路径：

1. `DataReceiveThread.run` 循环拉取
2. `DataSourceManager.read_frame` 输出统一帧
3. 帧入 `queue.Queue`
4. 主线程消费后更新状态机与波形

理解点：

- 线程只做“取帧 + 入队”，不做UI。
- 队列满时丢最旧，优先新数据（低延迟策略）。

### 4.3 断开链路（Disconnect）

断开时统一清理顺序（非常关键）：

1. 停接收线程
2. 停导出/分析
3. 断数据源
4. UI复位
5. 状态机回到未连接

理解点：

- 这就是Python GUI项目中的“手工析构流程”。

---

## 5. 为什么 `MainWindow` 是多Mixin继承（C++开发者常见困惑）

定义：

```python
class MainWindow(ChannelMenuMixin, RawDataMixin, ConnectionFlowMixin, DockLayoutMixin, QMainWindow, DockTopmostMixin):
    ...
```

这不是“乱继承”，而是把超大窗口类按职责切块：

- `ConnectionFlowMixin`：连接编排
- `RawDataMixin`：原始数据区逻辑
- `ChannelMenuMixin`：通道菜单和重命名
- `DockLayoutMixin`：Dock布局行为
- `DockTopmostMixin`：置顶逻辑

C++对应思路：

- 类似“组合 + 多重继承辅助模块”，用于避免单文件巨类。

实践规则：

- 新功能先判断属于哪个mixin职责。
- 不要在mixin间循环依赖状态。
- 状态真相尽量在 manager/FSM，不在多个mixin重复持有。

---

## 6. 数据契约与兼容策略（这是项目稳定性的关键）

### 6.1 统一帧是“新协议层契约”

`DataSourceManager.read_frame` 是当前主契约。

意义：

- 上游数据源可不同
- 下游应用统一处理
- 更容易加新协议/新源

### 6.2 `read_data` 仍保留（兼容旧路径）

`read_data` 通过 `_frame_to_legacy_dict` 适配旧调用。

这相当于C++重构中的“兼容层/适配层”。

原则：

- 新代码优先消费 `read_frame`
- 老代码可逐步迁移

### 6.3 通道重命名的收敛逻辑

`set_channel_name_mapping` 支持链式映射收敛：

- `channel1 -> 111`
- `111 -> 222`
- 最终 `channel1` 和 `111` 都收敛到 `222`

这是为了解决重命名期间在途数据包导致的“旧名回生”。

---

## 7. 线程、GIL与Qt主线程：你必须明确的边界

### 7.1 GIL不等于“不能并发”

对本项目这种 I/O 密集场景（串口/网络读取）：

- QThread + 队列是有效方案
- UI保持在主线程更新

### 7.2 线程分工（必须遵守）

- 后台线程：收数据、解析、入队
- 主线程：控件更新、绘图、状态显示

不要在后台线程直接操作Qt控件。

### 7.3 信号槽是跨线程安全桥

例如 `train_finished_signal` 的设计，属于“跨线程回主线程”的标准方式。

你可以把它理解成“消息分发到UI线程执行”。

---

## 8. 作为C/C++开发者，最容易踩的Python项目坑

1. 把UI当成业务层
- 现象：在控件回调里直接做协议判断、通道映射。
- 后果：切换数据源就回归。
- 正确做法：业务规则收敛到 `DataSourceManager` / 编排层。

2. 把 print 当日志系统
- 高频路径大量输出会直接拖垮实时性。
- 按项目约定使用可开关日志。

3. 忽视“字典契约”演化
- Python字段改名不会编译报错，容易运行时炸。
- 修改统一帧字段时必须连同测试一起改。

4. 过度依赖“鸭子类型”
- `hasattr` 可以用，但要有默认分支与容错。
- 关键路径最好保留清晰协议字段。

5. 忘记断开流程
- GUI项目最典型问题不是崩，而是“下一次连接异常”。
- 每次改连接逻辑都要完整测 connect -> receive -> disconnect -> reconnect。

---

## 9. 建议你采用的阅读顺序（按收益最大化）

1. `src/main.py`
- 先确认入口非常薄，不要误判业务在这里。

2. `src/app_window.py`
- 识别UI装配、mixin组合、信号定义。

3. `src/core/connection_flow_mixin.py`
- 看清连接/断开编排。

4. `src/core/receive_thread.py`
- 看高频数据线程是如何与队列协作。

5. `src/data_sources/manager.py`
- 看统一帧、通道映射、保存与兼容层。

6. `src/core/connection_fsm.py`
- 看状态机矩阵和UI视图模型解耦。

7. `tests/test_regression_layering.py`
- 用测试反推设计意图（最稳）。

---

## 10. 两个典型任务：按这个模板做不会偏

### 10.1 任务A：新增一种数据源

步骤：

1. 在 `src/data_sources/base.py` 契约下实现新 source。
2. 在 `src/core/data_source_factory.py` 加构建分支。
3. 在 `ConnectionFlowMixin._build_data_source_from_ui` 补配置采集。
4. 确保 `read_frame` 能稳定给出统一帧。
5. 增加回归测试（至少覆盖 connect/read/disconnect）。

验收：

- 不影响 UDP/TCP/串口/文件默认行为。

### 10.2 任务B：新增一个分析指标

步骤：

1. 在 `src/analytics/` 增加指标逻辑（旁路，不阻塞接收）。
2. 输出结果遵守现有分析结果结构。
3. UI只展示结果，不复制计算逻辑。
4. 补充相关测试与文档。

验收：

- 关闭分析开关时行为与旧版一致。

---

## 11. 你可以直接照抄的调试流程

当出现“已连接但没曲线”：

1. 看状态机是否已从等待态进入接收态。
2. 看 `read_frame` 是否返回有效帧。
3. 看 `meta.format_error` 是否持续为真。
4. 看队列是否积压/丢包增加。
5. 最后才看绘图层。

当出现“重命名后又冒出旧通道”：

1. 检查 `set_channel_name_mapping` 是否走了链式收敛。
2. 检查缓存通道替换 `_replace_channel_in_cache`。
3. 跑 `tests/test_regression_layering.py` 的重命名相关用例。

---

## 12. 实用命令（当前项目）

安装依赖：

```bash
pip install -r requirements.txt
```

启动程序：

```bash
python src/main.py
```

跑回归：

```bash
python -m unittest tests/test_regression_layering.py
```

UDP联调发送：

```bash
python tools/udp_sender.py --type sine --channels 3 --duration 10
```

TCP联调发送：

```bash
python tools/tcp_sender.py --host 127.0.0.1 --port 9999 --type sine --channels 3 --duration 10
```

---

## 13. C/C++开发者在本项目的“完成态标准”

你可以认为自己完成进化，当你能独立做到：

1. 不看他人提示，能解释 connect/read/disconnect 全链路。
2. 能在不破坏分层的前提下新增一个小功能。
3. 能用回归测试证明改动没有破坏旧协议。
4. 出现问题时优先用“状态机 + 统一帧 + 队列”定位，而不是盲改UI。

达到这四条，你就已经不是“会写Python语法”，而是“能维护这个Python工程”。

---

## 14. 建议的下一步学习节奏（7天）

- 第1天：只读架构和链路，画一张你自己的数据流图。
- 第2天：单步调试一次连接和断开。
- 第3天：跟踪 `read_frame` 到 UI 更新全过程。
- 第4天：阅读并执行回归测试，理解每个断言在防什么。
- 第5天：做一个极小改动（例如新增日志开关项）。
- 第6天：自测 + 回归。
- 第7天：把你的改动写入开发文档（形成团队可复用知识）。

如果你愿意，我下一步可以再给你一份“C/C++到Python项目的对照检查清单（逐项打勾版）”，用于你每次提交前自检。

---

## 15. 从语法起步：C/C++开发者的Python最小必修课

这一章不依赖本项目，你可以单独练。

### 15.1 变量、对象、可变性

先记住一句话：Python变量是“名字绑定到对象”，不是“变量盒子里存值”。

```python
a = [1, 2]
b = a
b.append(3)
print(a)  # [1, 2, 3]
```

对C/C++开发者的翻译：

- `a`/`b`更像“对象引用句柄”，不是两个独立数组。
- 需要拷贝时用 `copy()`、切片或 `copy.deepcopy()`。

### 15.2 条件、循环、推导式

```python
nums = [1, 2, 3, 4, 5]
evens_square = [n * n for n in nums if n % 2 == 0]
print(evens_square)  # [4, 16]
```

推导式相当于“过滤 + 变换”一行表达，能写清楚就用；一旦逻辑复杂，回到普通 `for` 循环。

### 15.3 函数：默认参数与可变参数陷阱

```python
def append_item(x, arr=None):
    if arr is None:
        arr = []
    arr.append(x)
    return arr
```

不要写 `def f(arr=[])`，因为默认参数只初始化一次。

### 15.4 类、继承、鸭子类型

```python
class Reader:
    def read(self):
        raise NotImplementedError


class FileReader(Reader):
    def read(self):
        return "from file"
```

Python里“接口”常通过约定和抽象基类保证，不是必须有头文件。

### 15.5 异常处理替代错误码

```python
def parse_port(text: str) -> int:
    try:
        p = int(text)
    except ValueError as e:
        raise ValueError(f"invalid port: {text}") from e
    if not (1 <= p <= 65535):
        raise ValueError("port out of range")
    return p
```

实践建议：

- 底层抛明确异常。
- 中间层做语义包装。
- UI层做最终提示，不要吞异常细节。

### 15.6 模块与包

```text
src/
  pkg/
    __init__.py
    worker.py
```

`__init__.py` 代表目录是包。用“按层导入”代替“全局include”。

### 15.7 typing：把动态语言写得可维护

```python
from typing import Dict, Any


def normalize_frame(raw: Dict[str, Any]) -> Dict[str, Any]:
    ...
```

即便Python不强制，类型注解可以让你在重构时少踩坑。

### 15.8 文件与资源管理（with语句）

```python
with open("demo.txt", "w", encoding="utf-8") as f:
    f.write("hello")
```

可把 `with` 理解为Python版RAII块级资源管理。

---

## 16. 手把手代码解读：从读懂到能改

这一章按“代码阅读模板”来讲，你可以照着任何Python项目复用。

### 16.1 解读模板（每个函数都按这6步）

1. 输入是什么（参数/成员状态/外部依赖）。
2. 输出是什么（返回值/副作用）。
3. 正常路径是什么。
4. 异常路径是什么。
5. 性能敏感点在哪里。
6. 改动后如何验证。

### 16.2 示例A：DataReceiveThread.run（高频路径）

阅读目标：理解“线程只拉取数据，不碰UI”的核心边界。

定位文件：`src/core/receive_thread.py`

逐段理解：

1. `while not stop_event.is_set()`
- 线程生命受停止事件控制，这是退出总开关。

2. `source = data_source_manager.current_source`
- 每轮都取当前数据源，保证切源后线程看到新状态。

3. `frame = data_source_manager.read_frame()`
- 线程只依赖统一帧契约，不关心UDP/TCP/串口细节。

4. `data_queue.put(frame, block=False)`
- 非阻塞入队，避免线程被UI消费速度拖死。

5. `except queue.Full` 分支
- 满队列时主动丢最旧数据，再尝试塞最新帧。
- 这是典型“低延迟优先”策略。

改动警戒线：

- 不要在这里直接访问Qt控件。
- 不要在循环里加高频 `print`。

### 16.3 示例B：DataSourceManager.read_frame（统一契约核心）

定位文件：`src/data_sources/manager.py`

阅读目标：理解“多协议输入 -> 统一帧输出”的收敛逻辑。

逐段理解：

1. 无数据源直接 `None`
- 应用层据此判定“当前无帧”。

2. `data = current_source.read_data()`
- source层负责协议解析前半段，manager负责业务统一。

3. 空元组处理
- 对格式敏感协议转成 `format_error` 帧，而非直接抛异常。

4. header校验
- 校验失败累计计数并返回错误帧。

5. 通道映射
- 原始名经过 `get_display_channel_name` 收敛到最终显示名。

6. 缓冲与CSV
- 仅有效帧入缓冲，保存开关打开时写CSV。

改动警戒线：

- 不能破坏 `read_frame` 的字段稳定性。
- 改字段要同步改 `read_data` 兼容层和测试。

### 16.4 示例C：StateMachine.handle_event（状态与表现解耦）

定位文件：`src/core/connection_fsm.py`

阅读目标：理解“状态真相在FSM，UI只渲染视图模型”。

逐段理解：

1. 根据 `current_state` 和 `event` 查 `transition_matrix`。
2. 无定义转换则丢弃事件（防非法状态跳转）。
3. 同状态事件走 `_handle_self_transition`。
4. 真正切换调用 `transition_to`。
5. `apply_view` 下发 `StateViewModel` 给UI。

改动警戒线：

- 不要在State类里直接操作按钮控件。
- 新增状态必须补事件矩阵与视图映射。

---

## 17. 基础训练任务（不局限本项目）

下面的任务是“通用Python工程训练”，建议按顺序做。

### 17.1 任务Lv1：语法稳定度（30-60分钟）

任务1：实现一个端口解析函数

```python
def parse_port(text: str) -> int:
    """要求:
    1) text可转int
    2) 范围1-65535
    3) 非法时抛ValueError并给出可读消息
    """
    pass
```

任务2：实现一个固定大小环形缓冲

```python
class RingBuffer:
    def __init__(self, capacity: int):
        pass

    def push(self, item):
        pass

    def snapshot(self):
        pass
```

验收标准：

- `capacity=3` 连续push 1,2,3,4 后 `snapshot()==[2,3,4]`。

### 17.2 任务Lv2：模块化与异常边界（1-2小时）

任务：写一个“配置加载器”

目标：

- 从json文件读取配置。
- 校验必填字段：`host`、`port`。
- 将错误分为：文件不存在、JSON格式错误、字段错误。

建议结构：

```text
config_loader/
  __init__.py
  errors.py
  loader.py
  test_loader.py
```

验收标准：

- 单测覆盖三类错误路径。
- 调用方能通过异常类型区分错误。

### 17.3 任务Lv3：并发与队列（2-3小时）

任务：实现生产者/消费者模型

目标：

- 生产者线程每10ms生产一个数据。
- 消费者线程批量消费并统计速率。
- 队列满时丢弃最旧数据保最新。

验收标准：

- 连续运行60秒无死锁。
- 能打印吞吐与丢包统计。

### 17.4 任务Lv4：可测试重构（2-4小时）

任务：把一个300行函数拆成3层

建议拆分：

- 输入校验层
- 纯业务计算层
- I/O输出层

验收标准：

- 纯业务层可单测、无I/O副作用。
- 主流程可读性明显提升。

---

## 18. 项目内训练任务（语法 + 开发逻辑结合）

### 18.1 任务P1：给统一帧加一个可选字段

目标：在 `meta` 新增字段 `source_type`。

要求：

1. `read_frame` 增加该字段。
2. `read_data` 兼容逻辑不被破坏。
3. 回归测试补至少1条断言。

训练价值：

- 练习“契约演进 + 兼容层”。

### 18.2 任务P2：新增一个可开关调试日志

目标：增加环境变量开关，控制某类调试日志输出。

要求：

1. 默认关闭。
2. 高频路径不额外显著降速。
3. 文档写清开关名与用法。

训练价值：

- 练习“可观测性与性能平衡”。

### 18.3 任务P3：补一个防回归测试

目标：围绕你最近改动，增加最小失败用例。

建议：

- 修改前先让测试失败。
- 修复后测试通过。
- 说明这个测试防止了哪类回归。

训练价值：

- 建立“先证明再提交”的工程习惯。

---
