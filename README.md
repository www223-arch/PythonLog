# Python上位机 - UDP数据采集

一个支持UDP数据接收和实时波形显示的Python上位机软件。

## ✨ 功能特性

- ✅ **UDP数据接收**：支持UDP协议数据接收
- ✅ **实时波形显示**：多通道实时波形显示
- ✅ **交互功能**：缩放、平移、鼠标吸附数据点
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

```bash
# 发送正弦波数据（默认3通道，1Hz频率，持续10秒）
python tools/udp_sender.py --type sine --channels 3 --frequency 1.0 --duration 10

# 发送随机数据
python tools/udp_sender.py --type random --channels 3 --duration 10

# 查看帮助
python tools/udp_sender.py --help
```

## 📖 使用说明

### 上位机界面

1. **UDP配置**
   - 主机地址：默认 `0.0.0.0`（监听所有接口）
   - 端口：默认 `8888`
   - 点击"连接"按钮开始接收数据

2. **通道配置**
   - 通道名称：如 `ch1`, `ch2`, `ch3`
   - 颜色：`r`(红), `g`(绿), `b`(蓝), `c`(青), `m`(品红), `y`(黄)
   - 点击"添加通道"按钮添加新通道

3. **波形显示**
   - 鼠标滚轮：缩放
   - 鼠标拖拽：平移
   - 点击"暂停"按钮：暂停显示
   - 点击"清空"按钮：清空所有数据

### UDP数据格式

数据格式：多个浮点数（每个4字节），按顺序排列

例如，3通道数据：
``nch1_value, ch2_value, ch3_value```

Python发送示例：
```python
import socket
import struct

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
values = [1.0, 2.0, 3.0]  # 3个通道的数据
data = struct.pack('3f', *values)  # 转换为字节数据
sock.sendto(data, ('127.0.0.1', 8888))
```

## 📁 项目结构

```
Pythonlog/
├── src/
│   ├── data_sources/       # 数据源模块
│   │   ├── base.py        # 数据源抽象基类
│   │   ├── udp_source.py  # UDP数据源实现
│   │   └── manager.py     # 数据源管理器
│   ├── visualization/      # 可视化模块
│   │   └── waveform_widget.py  # 波形显示组件
│   └── main.py            # 主程序
├── tools/
│   └── udp_sender.py      # UDP测试工具
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
- [ ] 串口数据源支持
- [ ] 文件数据源支持
- [ ] 数据分析功能（FFT、滤波等）
- [ ] 数据导出功能
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