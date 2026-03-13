# Python上位机 - 数据采集与显示

一个支持多种数据源、实时波形显示和CSV数据保存的Python上位机软件。

## ✨ 功能特性

- ✅ **多数据源支持**：支持UDP、串口、文件等数据源
- ✅ **实时波形显示**：多通道实时波形显示
- ✅ **自动通道检测**：根据接收到的数据自动创建通道
- ✅ **CSV数据保存**：自动保存接收到的数据为CSV格式（Excel可打开）
- ✅ **时间戳支持**：使用发送方发送的时间戳作为X轴坐标
- ✅ **交互功能**：缩放、平移、鼠标吸附数据点、双击标记
- ✅ **暂停/继续**：支持暂停和继续显示
- ✅ **可扩展架构**：为其他数据源（串口、文件）预留接口

## 📦 安装依赖

```bash
pip install -r requirements.txt
```

## 🚀 快速开始

### 1. 启动上位机

```bash
python src/main.py
```

### 2. 发送测试数据

打开另一个终端，发送测试数据到上位机：

**基本用法**：
```bash
# 查看帮助信息
python tools/udp_sender.py --help
```

**发送正弦波数据**：
```bash
# 发送3通道正弦波，50Hz采样率，持续10秒
python tools/udp_sender.py --type sine --channels 3 --frequency 1.0 --duration 10 --rate 50

# 发送3通道正弦波，使用自定义通道名称
python tools/udp_sender.py --type sine --channels 3 --frequency 1.0 --duration 10 --names 电压 电流 温度
```

**发送随机数据**：
```bash
# 发送3通道随机数据，持续10秒
python tools/udp_sender.py --type random --channels 3 --duration 10
# 发送3通道随机数据，使用自定义通道名称
python tools/udp_sender.py --type random --channels 3 --duration 10 --names 电压 电流 温度
```

**参数说明**：
- `--host`: 目标主机地址（默认：127.0.0.1）
- `--port`: 目标端口（默认：8888）
- `--type`: 数据类型，`sine`（正弦波）或 `random`（随机数据）
- `--channels`: 通道数量（默认：3）
- `--frequency`: 正弦波频率（Hz，默认：1.0，仅正弦波有效）
- `--amplitude`: 正弦波振幅（默认：1.0，仅正弦波有效）
- `--duration`: 发送持续时间（秒，默认：10.0）
- `--rate`: 采样率（Hz，默认：50，建议50-100Hz）
- `--names`: 自定义通道名称，用空格分隔（例如：`--names 电压 电流 温度`）
- `--header`: 数据校验头（默认：DATA）

**示例**：
```bash
# 示例1：发送正弦波数据（默认配置）
python tools/udp_sender.py --type sine

# 示例2：发送随机数据（默认配置）
python tools/udp_sender.py --type random

# 示例3：发送正弦波数据，自定义参数
python tools/udp_sender.py --type sine --channels 2 --frequency 2.0 --amplitude 1.5 --duration 20 --rate 100

# 示例4：发送随机数据，自定义通道名称
python tools/udp_sender.py --type random --channels 3 --duration 15 --names 电压 电流 温度 --header DATA

# 示例5：发送到指定主机和端口
python tools/udp_sender.py --type sine --host 192.168.1.100 --port 9999 --duration 5
```

## 📖 使用说明

### 上位机界面

1. **UDP配置**
   - 主机地址：默认 `0.0.0.0`（监听所有接口）
   - 端口：默认 `8888`
   - 点击"连接"按钮开始接收数据

2. **通道配置**
   - 自动检测：程序会自动检测接收到的通道
   - 无需手动添加：根据数据格式自动创建通道
   - 显示检测到的通道名称

3. **数据保存**
   - 点击"开始保存"按钮开始保存数据
   - 数据保存为CSV格式，保存在 `data/` 目录
   - 文件名格式：`data_YYYYMMDD_HHMMSS.csv`
   - Excel可直接打开
   - 点击"停止保存"按钮停止保存

4. **波形显示**
   - 鼠标滚轮：缩放
   - 鼠标拖拽：平移
   - 鼠标移动：显示吸附点坐标和鼠标坐标
   - 双击：标记数据点（最多2个点，计算差值）
   - 点击"暂停"按钮：暂停显示
   - 点击"清空"按钮：清空所有数据

### UDP数据格式

**文本格式（推荐）**：
```
时间戳,通道一=数值,通道二=数值,通道三=数值
```

例如，3通道数据：
```
123.456,通道一=1.234,通道二=2.567,通道三=0.890
```

**说明**：
- **时间戳**：第一个字段必须是时间戳（浮点数）
- **通道名称**：`=` 前面的名称将作为通道名
- **通道数量**：根据实际数据自动检测
- **无需手动添加**：程序会自动根据通道名创建对应的显示通道


**Python发送示例**：
```python
import socket

import time

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# 构建数据
timestamp = time.time()
data = f"{timestamp},通道一=1.234,通道二=2.567,通道三=0.890"

# 发送数据
sock.sendto(data.encode('utf-8'), ('127.0.0.1', 8888))
```

**CSV数据格式**：
```
时间戳,通道一,通道二,通道三
123.456,1.234,2.567,0.890
123.457,1.235,2.568,0.891
...
```

- 文件保存在 `data/` 目录
- 文件名格式：`data_YYYYMMDD_HHMMSS.csv`
- Excel可直接打开

## 📁 项目结构

```
Pythonlog/
├── src/
│   ├── data_sources/       # 数据源模块
│   │   ├── base.py        # 数据源抽象基类
│   │   ├── udp_source.py  # UDP数据源实现
│   │   ├── data_saver.py  # CSV数据保存模块
│   │   └── manager.py     # 数据源管理器
│   ├── visualization/      # 可视化模块
│   │   └── waveform_widget.py  # 波形显示组件
│   └── main.py            # 主程序
├── tools/
│   └── udp_sender.py      # UDP测试工具
├── data/                 # CSV数据保存目录
├── requirements.txt       # 依赖包
└── README.md             # 项目说明
```

## 🔧 开发指南

### 添加新的数据源

1. 继承 `DataSource` 基类：
```python
from src.data_sources.base import DataSource

class MyDataSource(DataSource):
    def connect(self) -> bool:
        # 实现连接逻辑
        pass
    
    def read_data(self):
        # 实现读取数据逻辑
        pass
    
    def disconnect(self) -> None:
        # 实现断开连接逻辑
        pass
```

2. 在主程序中使用：
```python
from src.data_sources.manager import DataSourceManager

manager = DataSourceManager()
source = MyDataSource()
manager.set_source(source)
```

### 自定义数据处理

在 `src/main.py` 的 `update_data()` 方法中添加自定义处理逻辑：
```python
def update_data(self):
    data = self.data_source_manager.read_data()
    if data is not None:
        # 添加自定义数据处理
        processed_data = your_processing_function(data)
        
        # 更新波形显示
        self.waveform_widget.update_channels(processed_data)
```

## 🎯 后续扩展

计划中的功能：
- [x] UDP数据源支持
- [ ] 串口数据源支持
- [ ] 文件数据源支持
- [x] CSV数据保存
- [ ] 数据分析功能（FFT、滤波等）
- [ ] 数据导出功能（其他格式）
- [ ] 配置保存和加载
- [ ] 多语言支持

## 📚 技术栈

- **GUI框架**：PyQt5
- **数据可视化**：PyQtGraph
- **数据处理**：NumPy
- **网络通信**：Python socket

## 🤝 贡献

欢迎提交Issue和Pull Request！

## 📄 许可证

MIT License

## 👤 作者

Python上位机开发团队

---

**祝你使用愉快！** 🎉