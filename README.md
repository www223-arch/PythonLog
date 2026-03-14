# Python上位机 - 用户使用手册

一个面向实时采集的上位机工具，支持 UDP、TCP、串口与文件数据源，提供时域波形、频域分析、双向通信和 CSV 保存。

## 文档说明

- 本文档面向使用者，关注安装、配置和操作。
- 开发与架构文档请查看 [README_DEV.md](README_DEV.md)。
- 详细开发指南请查看 [docs/developer_guide.md](docs/developer_guide.md)。

## 功能总览

### 数据源
- UDP 接收（文本数据）
- TCP 接收（协议格式与 UDP 一致）
- 串口接收
- 文件回放（`.log` / `.bin`）
- 串口文本协议
- 串口 Justfloat 协议（无时间戳/带时间戳）
- 串口 Rawdata 模式（仅原始接收显示）

### 可视化与分析
- 多通道实时波形显示
- 自动检测通道并分配颜色
- 频域 FFT 分析
- 波形点位吸附与双击标记
- 通道颜色自定义

### 数据管理
- 数据发送（按当前数据源协议路由：串口/UDP/TCP）
- CSV 保存（手动开启）
- 缓存区大小可配置
- 限制数据点数开关
- 清空所有通道

### 运行状态
- 连接状态显示
- 接收计数与速率统计
- 队列长度、丢包、字节速率、解析耗时统计
- 数据格式不匹配时红色闪烁；若发送停止，会自动回到等待数据状态

## 安装

```bash
pip install -r requirements.txt
```

## 快速开始

### 1. 启动上位机

```bash
python src/main.py
```

### 2. UDP 测试发送

```bash
# 帮助
python tools/udp_sender.py --help

# 正弦波 3 通道
python tools/udp_sender.py --type sine --channels 3 --frequency 1.0 --duration 10 --rate 50

# 随机波形 3 通道
python tools/udp_sender.py --type random --channels 3 --duration 10

# 自定义通道名
python tools/udp_sender.py --type sine --channels 3 --frequency 1.0 --duration 10 --names 电压 电流 温度

# 边发UDP边实时追加到文件（用于“文件源”实时读取联调）
python tools/udp_sender.py --type sine --duration 30 --dump-log data/live_udp.log

# 启用UDP接收调试（文本显示）
python tools/udp_sender.py --type sine --duration 10 --recv --recv-port 8889 --recv-format text

# 启用UDP接收调试（十六进制显示）
python tools/udp_sender.py --type sine --duration 10 --recv --recv-port 8889 --recv-format hex
```

### 3. TCP 测试发送（与 UDP 发送器风格一致）

使用前请先在上位机选择 `TCP` 并连接监听端口（默认 `9999`）。

```bash
# 帮助
python tools/tcp_sender.py --help

# 正弦波 3 通道
python tools/tcp_sender.py --host 127.0.0.1 --port 9999 --type sine --channels 3 --frequency 1.0 --duration 10 --rate 50

# 随机波形 3 通道
python tools/tcp_sender.py --host 127.0.0.1 --port 9999 --type random --channels 3 --duration 10 --rate 20

# 自定义通道名
python tools/tcp_sender.py --type sine --channels 3 --duration 10 --names 电压 电流 温度

# 边发TCP边实时追加到文件（用于“文件源”实时读取联调）
python tools/tcp_sender.py --host 127.0.0.1 --port 9999 --type sine --duration 30 --dump-log data/live_tcp.log

# 启用TCP接收调试（文本显示）
python tools/tcp_sender.py --host 127.0.0.1 --port 9999 --type sine --duration 10 --recv --recv-format text

# 启用TCP接收调试（十六进制显示）
python tools/tcp_sender.py --host 127.0.0.1 --port 9999 --type sine --duration 10 --recv --recv-format hex
```

### 4. 生成文件测试流程（.log / .bin）

```bash
# 帮助
python tools/generate_test_files.py --help

# 生成文本协议 .log（可用于文件源+文本协议）
python tools/generate_test_files.py --format log --channels 3 --samples 1000 --rate 50 --type sine

# 生成 justfloat .bin（无时间戳）
python tools/generate_test_files.py --format bin --channels 3 --samples 2000 --rate 100 --type sine

# 生成 justfloat .bin（带时间戳）
python tools/generate_test_files.py --format bin --channels 3 --samples 2000 --rate 100 --type sine --with-timestamp

# 持续写入 .log（实时模式，Ctrl+C停止）
python tools/generate_test_files.py --format log --rate 50 --type sine --live --output data/live_file.log

# 持续写入 .bin（实时模式，Ctrl+C停止）
python tools/generate_test_files.py --format bin --rate 100 --type sine --with-timestamp --live --output data/live_file.bin
```

文件生成后，在上位机中：
- 选择数据源类型为 `文件`
- 选择对应文件路径
- `.log` 选 `文本协议`
- `.bin` 选 `Justfloat`（根据生成参数选择带/不带时间戳）

文件源实时读取说明：
- 文件模式采用实时尾随读取（tail）策略。
- 当 `.log/.bin` 文件有新增数据时，上位机会继续解析并实时显示/打印。
- 可配合 `udp_sender.py` 或 `tcp_sender.py` 的 `--dump-log` 参数做在线联调。

## 界面使用

### 数据源配置
- 数据源类型可选 UDP、TCP、串口、文件。
- UDP 默认监听地址 `0.0.0.0`，端口 `8888`。
- TCP 默认监听地址 `0.0.0.0`，端口 `9999`。
- 串口可配置端口、波特率、协议类型。
- 文件可选择 `.log/.bin` 并配置协议类型。
- 文本协议可配置数据校验头，默认 `DATA`。

### 数据发送
- 发送入口位于控制面板“数据发送”区域。
- 串口模式：通过当前串口发送。
- UDP模式：通过UDP发送到配置的“发送目标IP/端口”。
- TCP模式：通过当前已连接TCP客户端发送。
- 文件模式：仅回放，不支持发送。

### 连接与暂停
- 点击连接按钮开始接收。
- 点击暂停按钮仅暂停绘图，数据接收和保存可继续。
- 快捷键空格可切换暂停/继续。

### 通道与显示
- 通道会自动创建。
- 可设置缓存区大小（默认 1000）。
- 可开启或关闭限制数据点数。
- 支持右键菜单设置通道颜色。
- Justfloat 模式下支持通道重命名。
- Justfloat 模式断开后会保留上次自定义通道名；重连后：
- 若通道变多，新增通道使用默认名（如 channel4）。
- 若通道变少，多余历史通道名不再显示。

### 原始数据区
- 默认关闭（避免影响性能）。
- 可选择 UTF-8 或 GBK。
- 可选择文本或十六进制显示。

### CSV 保存
- 默认不自动保存。
- 点击“开始保存”后写入 CSV。
- 默认目录 `data/`，文件名格式 `data_YYYYMMDD_HHMMSS.csv`。

## 数据格式

### UDP 文本格式

```text
数据校验头,时间戳,通道名1=值1,通道名2=值2,...
```

示例：

```text
DATA,123.456,电压=1.23,电流=0.56,温度=25.1
```

说明：
- 第 1 列为校验头。
- 第 2 列为时间戳（秒）。
- 后续列为 `通道名=数值`。

### 串口协议
- 文本协议：同 UDP 文本格式。
- Justfloat：二进制 float 帧，帧尾固定 `00 00 80 7F`。
- Justfloat（带时间戳）：帧尾前最后一个 float 为时间戳（ms），其前面的 float 为通道数据。
- Justfloat（无时间戳）：帧内仅通道数据，时间戳由上位机按用户设置的 Δt 推算。
- Rawdata：只显示原始数据，不参与曲线解析。

### 文件协议
- 文件：支持 `.log` 与 `.bin`，可按文本 / Justfloat / Rawdata 回放。

说明：下位机若通过 USB CDC 或串口转 TTL 连接，上位机统一按“串口”配置使用。

## 常见问题

### 1. 为什么看不到曲线
- 未连接成功。
- 数据校验头不匹配。
- 数据格式不符合约定。
- 当前通道无有效数据。

### 2. 为什么实时性下降
- 原始数据显示开关已开启。
- 发送频率超过链路物理上限。
- 缓存区过大导致 UI 压力上升。

### 3. 为什么重命名后又出现旧通道
- 使用旧版本时可能因在途数据包导致旧键回流。
- 已在新版本中通过通道名映射归一化处理修复。

## 项目结构（用户关注）

```text
Pythonlog/
|-- src/
|   |-- main.py
|   |-- data_sources/
|   |-- visualization/
|-- tools/
|-- data/
|-- README.md
|-- README_DEV.md
```

## 许可证

MIT License
