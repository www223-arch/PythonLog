import queue

from PyQt5.QtCore import QDateTime, Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class RawDataMixin:
    """原始数据面板与发送/刷新逻辑混入。"""

    def create_raw_data_panel(self):
        """创建原始数据接收区面板"""
        panel = QWidget()
        layout = QVBoxLayout()

        # 原始数据接收区
        raw_data_group = QGroupBox("原始数据")
        raw_data_layout = QVBoxLayout()

        # 编码格式和显示格式选择
        format_layout = QHBoxLayout()

        encoding_label = QLabel("编码格式:")
        self.encoding_combo = QComboBox()
        self.encoding_combo.addItems(["UTF-8", "GBK"])
        self.encoding_combo.setCurrentText("UTF-8")

        display_label = QLabel("显示格式:")
        self.display_format_combo = QComboBox()
        self.display_format_combo.addItems(["文本", "十六进制"])
        self.display_format_combo.setCurrentText("文本")

        self.raw_data_enable_checkbox = QCheckBox("原始数据")
        self.raw_data_enable_checkbox.setChecked(False)

        format_layout.addWidget(encoding_label)
        format_layout.addWidget(self.encoding_combo)
        format_layout.addWidget(display_label)
        format_layout.addWidget(self.display_format_combo)
        raw_data_layout.addLayout(format_layout)
        raw_data_layout.addWidget(self.raw_data_enable_checkbox)

        # 原始数据显示区域
        self.raw_data_text = QTextEdit()
        self.raw_data_text.setReadOnly(True)
        self.raw_data_text.setStyleSheet("font-family: Consolas, monospace; font-size: 10pt;")

        # 发送区域（与原始数据区放在一起，风格参考串口助手）
        send_group = QGroupBox("发送区")
        send_layout = QVBoxLayout()

        self.send_edit = QTextEdit()
        self.send_edit.setPlaceholderText("输入发送内容（Enter换行，Ctrl+Enter发送）")
        self.send_edit.setMinimumHeight(90)

        send_button_row = QHBoxLayout()
        self.send_btn = QPushButton("发送")
        self.send_btn.clicked.connect(self.send_current_data)
        self.send_btn.setEnabled(False)
        send_button_row.addWidget(self.send_btn)
        send_button_row.addStretch()

        self.send_result_label = QLabel("发送状态: 未发送")
        self.send_result_label.setStyleSheet("color: #666;")

        send_layout.addWidget(self.send_edit)
        send_layout.addLayout(send_button_row)
        send_layout.addWidget(self.send_result_label)
        send_group.setLayout(send_layout)

        # 使用分割器让“接收区/发送区”都可拖拽调节高度
        io_splitter = QSplitter(Qt.Vertical)
        io_splitter.addWidget(self.raw_data_text)
        io_splitter.addWidget(send_group)
        io_splitter.setStretchFactor(0, 7)
        io_splitter.setStretchFactor(1, 3)
        io_splitter.setChildrenCollapsible(False)
        io_splitter.setHandleWidth(5)

        raw_data_layout.addWidget(io_splitter)

        # 清空按钮
        clear_raw_data_btn = QPushButton("清空原始数据")
        clear_raw_data_btn.clicked.connect(self.clear_raw_data)
        raw_data_layout.addWidget(clear_raw_data_btn)

        raw_data_group.setLayout(raw_data_layout)
        layout.addWidget(raw_data_group)

        panel.setLayout(layout)
        return panel

    def send_current_data(self):
        """通过当前数据源发送文本数据。"""
        if not self.data_source_manager.is_connected():
            self.send_result_label.setText("发送状态: 失败（未连接）")
            self.send_result_label.setStyleSheet("color: red;")
            return

        text = self.send_edit.toPlainText()
        if not text:
            return

        source_type = self.source_type_combo.currentText()
        protocol_text = None
        if source_type == "串口":
            protocol_text = self.protocol_combo.currentText()
        elif source_type == "文件":
            protocol_text = self.file_protocol_combo.currentText()
        else:
            protocol_text = "文本协议"

        payload = text
        if protocol_text == "文本协议" and not payload.endswith("\n"):
            payload += "\n"

        success = self.data_source_manager.send_data(payload.encode('utf-8'))
        if success:
            self.send_result_label.setText("发送状态: 成功")
            self.send_result_label.setStyleSheet("color: green;")
            self.log_print(f"[发送] {source_type} 发送成功: {text}")
            self._append_tx_to_raw_data_view(text)
        else:
            self.send_result_label.setText("发送状态: 失败（当前源不支持或目标不可达）")
            self.send_result_label.setStyleSheet("color: red;")
            self.log_print(f"[发送] {source_type} 发送失败: {text}")

    def _append_tx_to_raw_data_view(self, text: str):
        """在原始数据区追加发送内容，带TX标识。"""
        timestamp = QDateTime.currentDateTime().toString("HH:mm:ss.zzz")
        lines = text.splitlines() or [""]
        tx_text = "\n".join([f"[TX][{timestamp}] {line}" for line in lines])
        self.raw_data_text.append(tx_text)
        self._trim_raw_data_text_lines()

    def _trim_raw_data_text_lines(self):
        """限制原始数据区最大行数，避免内存占用持续增长。"""
        max_lines = 1000
        document = self.raw_data_text.document()
        if document.blockCount() <= max_lines:
            return

        cursor = self.raw_data_text.textCursor()
        cursor.movePosition(cursor.Start)
        cursor.movePosition(cursor.Down, cursor.KeepAnchor, document.blockCount() - max_lines)
        cursor.removeSelectedText()

        scrollbar = self.raw_data_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def on_raw_data_received(self, data: bytes):
        """原始数据接收回调。"""
        # 暂停时不刷新原始数据栏
        if self.waveform_widget.is_paused or not self.raw_data_enabled:
            return

        # 仅入队，解码和文本拼接在主线程定时器中批量处理
        try:
            self.raw_data_queue.put_nowait(data)
        except queue.Full:
            pass

    def flush_raw_data_buffer(self):
        """刷新原始数据缓冲区到UI"""
        try:
            # 每次限量处理，避免原始数据显示占用过多主线程
            max_packets_per_flush = 200
            packets = []
            while len(packets) < max_packets_per_flush:
                try:
                    packets.append(self.raw_data_queue.get_nowait())
                except queue.Empty:
                    break

            if not packets and not self.raw_data_buffer:
                return

            encoding = self.raw_data_encoding
            display_format = self.raw_data_display_format

            for data in packets:
                if display_format == "文本":
                    try:
                        self.raw_data_buffer.append(data.decode(encoding))
                    except UnicodeDecodeError:
                        if self._is_binary_data(data):
                            self.raw_data_buffer.append("[二进制数据 - 请切换到十六进制格式查看]\n")
                        else:
                            self.raw_data_buffer.append(f"[解码失败: {data.hex()}]\n")
                else:
                    self.raw_data_buffer.append(f"{data.hex(' ').upper()}\n")

            if not self.raw_data_buffer:
                return

            # 将缓冲区中的所有文本一次性添加到UI
            all_text = ''.join(self.raw_data_buffer)
            self.raw_data_buffer.clear()
            self.raw_data_text.append(all_text)

            # 限制行数并滚动到底部
            self._trim_raw_data_text_lines()
        except Exception as e:
            self.log_print(f"刷新原始数据缓冲区失败: {e}")

    def _is_binary_data(self, data: bytes) -> bool:
        """判断数据是否是二进制数据。"""
        if not data:
            return False

        # 检查前100个字节（或全部字节，如果少于100个）
        sample_size = min(100, len(data))
        sample = data[:sample_size]

        # 统计不可打印字符的数量
        non_printable_count = 0
        for byte in sample:
            # ASCII码小于32（除了\t, \n, \r）或大于126的字符被认为是不可打印的
            if byte < 32 and byte not in (9, 10, 13):
                non_printable_count += 1
            elif byte > 126:
                non_printable_count += 1

        # 如果不可打印字符超过20%，认为是二进制数据
        return non_printable_count / sample_size > 0.2

    def clear_raw_data(self):
        """清空原始数据"""
        self.raw_data_text.clear()
        self.raw_data_buffer.clear()
        while not self.raw_data_queue.empty():
            try:
                self.raw_data_queue.get_nowait()
            except queue.Empty:
                break