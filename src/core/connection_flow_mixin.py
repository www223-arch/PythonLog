import os

from PyQt5.QtWidgets import QComboBox, QFileDialog, QMessageBox

from core.data_source_factory import build_data_source


class ConnectionFlowMixin:
    """连接编排与数据源构建混入。"""

    def toggle_connection(self):
        """切换连接/断开状态"""
        if self.data_source_manager.is_connected():
            self._disconnect_flow()
        else:
            self._connect_flow()

    def _disconnect_flow(self):
        """连接编排层：统一处理断开流程（不改业务语义）"""
        self._debug_ui_state_snapshot("before_disconnect_flow", event="disconnect")
        self._snapshot_justfloat_channel_names_before_disconnect()
        if hasattr(self, 'arterial_pipeline') and self.arterial_pipeline is not None:
            self.arterial_pipeline.reset()
        if hasattr(self, '_reset_arterial_ui_state'):
            self._reset_arterial_ui_state()
        # 断开时重置暂停状态，避免下次连接仍停在暂停显示
        self.waveform_widget.is_paused = False
        self.pause_btn.setText("暂停")
        # 先停止数据接收线程，避免访问已断开的数据源
        self.stop_receive_thread()
        if hasattr(self, '_stop_metrics_export'):
            self._stop_metrics_export()
        # 再断开数据源连接
        self.data_source_manager.disconnect()
        self.status_label.setText("未连接")
        self.status_label.setStyleSheet("color: red;")
        self.pause_btn.setEnabled(False)
        self.send_btn.setEnabled(False)
        self.send_result_label.setText("发送状态: 未发送")
        # 断开后恢复配置编辑
        self._set_connection_config_enabled(True)
        self.data_count = 0
        self.data_count_label.setText("接收数据: 0")
        self.perf_label.setText("速率: 接收 0/s | 处理 0/s | 队列 0 | 丢包 0 | 字节 0 B/s | 解析 0 us/帧")
        self.save_file_label.setText("保存文件: 无")
        self.channels_label.setText("自动检测通道...")
        self.last_channels_text = "自动检测通道..."
        self.save_btn.setText("开始保存")
        self.save_btn.setEnabled(False)
        self.auto_save_enabled = False
        self.clear_raw_data()  # 清空原始数据接收区

        # 转换到未连接状态
        self.state_machine.handle_event('disconnect')
        # 重置last_data_time，避免check_data_timeout继续检测超时
        self.last_data_time = None
        self.log_print("数据源已断开")
        self._debug_ui_state_snapshot("after_disconnect_flow", event="disconnect")

    def _snapshot_justfloat_channel_names_before_disconnect(self):
        """断开前保存justfloat通道显示名，用于下次重连恢复。"""
        source = self.data_source_manager.get_current_source()
        if source is None or not hasattr(source, 'get_protocol'):
            return

        if source.get_protocol() != 'justfloat':
            return

        current_count = len(self.waveform_widget.channels)
        if current_count <= 0:
            self.last_justfloat_channel_names = []
            return

        saved_names = []
        for i in range(1, current_count + 1):
            default_name = f'channel{i}'
            saved_names.append(self.data_source_manager.get_display_channel_name(default_name))

        self.last_justfloat_channel_names = saved_names
        self.fsm_debug_print(
            f"[UI_DEBUG][justfloat_snapshot] count={current_count} names={self.last_justfloat_channel_names}"
        )

    def _restore_justfloat_channel_names_after_connect(self):
        """justfloat重连后恢复上次通道显示名映射。"""
        if not self.last_justfloat_channel_names:
            return

        used_names = set()
        restored = []

        for index, saved_name in enumerate(self.last_justfloat_channel_names, start=1):
            default_name = f'channel{index}'
            if not saved_name or saved_name == default_name:
                continue

            # 避免异常情况下的重名恢复
            if saved_name in used_names:
                continue

            self.data_source_manager.set_channel_name_mapping(default_name, saved_name)
            used_names.add(saved_name)
            restored.append((default_name, saved_name))

        if restored:
            self.fsm_debug_print(f"[UI_DEBUG][justfloat_restore] mappings={restored}")

    def _build_data_source_from_ui(self, source_type: str, header: str):
        """应用编排层：采集/校验UI配置，并委托工厂构建数据源。"""
        if source_type == "UDP":
            config = {
                "host": self.host_edit.text(),
                "port": int(self.port_edit.text()),
                "send_host": self.udp_send_host_edit.text().strip() or "127.0.0.1",
                "send_port": int(self.udp_send_port_edit.text()),
                "header": header,
            }
            return build_data_source(source_type, config)

        if source_type == "TCP":
            mode_text = self.tcp_mode_combo.currentText()
            config = {
                "mode": "client" if mode_text == "主动连接" else "server",
                "local_host": self.tcp_host_edit.text(),
                "local_port": int(self.tcp_port_edit.text()),
                "target_host": self.tcp_target_host_edit.text().strip() or "127.0.0.1",
                "target_port": int(self.tcp_target_port_edit.text()),
            }
            return build_data_source(source_type, config)

        if source_type == "串口":
            serial_port = self.serial_port_combo.currentData()  # 获取实际的串口号（如COM1）
            if not serial_port:
                QMessageBox.warning(self, "错误", "请选择有效的端口")
                return None, None, None

            protocol_text = self.protocol_combo.currentText()
            baudrate = int(self.baudrate_combo.currentText())

            if protocol_text == '文本协议':
                config = {
                    "serial_port": serial_port,
                    "baudrate": baudrate,
                    "protocol": 'text',
                    "header": header,
                }
                return build_data_source(source_type, config)

            if protocol_text in ['Justfloat', 'Firewater']:
                justfloat_mode_text = self.justfloat_mode_combo.currentText()
                justfloat_mode = 'with_timestamp' if justfloat_mode_text == '带时间戳' else 'without_timestamp'
                delta_t = float(self.delta_t_edit.text()) if self.delta_t_edit.text() else 1.0
                protocol = 'justfloat' if protocol_text == 'Justfloat' else 'firewater'
                config = {
                    "serial_port": serial_port,
                    "baudrate": baudrate,
                    "protocol": protocol,
                    "justfloat_mode": justfloat_mode,
                    "delta_t": delta_t,
                }
                return build_data_source(source_type, config)

            config = {
                "serial_port": serial_port,
                "baudrate": baudrate,
                "protocol": 'rawdata',
            }
            return build_data_source(source_type, config)

        # 文件数据源
        file_path = self.file_path_edit.text().strip()
        if not file_path or not os.path.isfile(file_path):
            QMessageBox.warning(self, "错误", "请选择有效的 .log/.bin/.csv 文件")
            return None, None, None

        ext = os.path.splitext(file_path)[1].lower()
        if ext not in ('.log', '.bin', '.csv'):
            QMessageBox.warning(self, "错误", "仅支持 .log/.bin/.csv 文件")
            return None, None, None

        protocol_text = self.file_protocol_combo.currentText()
        if protocol_text == '文本协议':
            config = {
                "file_path": file_path,
                "protocol": 'text',
                "header": header,
            }
            return build_data_source(source_type, config)

        if protocol_text == 'CSV':
            if ext != '.csv':
                QMessageBox.warning(self, "错误", "CSV协议仅支持 .csv 文件")
                return None, None, None
            config = {
                "file_path": file_path,
                "protocol": 'csv',
            }
            return build_data_source(source_type, config)

        if protocol_text == 'Justfloat':
            justfloat_mode_text = self.justfloat_mode_combo.currentText()
            justfloat_mode = 'with_timestamp' if justfloat_mode_text == '带时间戳' else 'without_timestamp'
            delta_t = float(self.delta_t_edit.text()) if self.delta_t_edit.text() else 1.0
            config = {
                "file_path": file_path,
                "protocol": 'justfloat',
                "justfloat_mode": justfloat_mode,
                "delta_t": delta_t,
            }
            return build_data_source(source_type, config)

        config = {
            "file_path": file_path,
            "protocol": 'rawdata',
        }
        return build_data_source(source_type, config)

    def _connect_flow(self):
        """连接编排层：统一处理连接流程（不改业务语义）"""
        try:
            source_type = self.source_type_combo.currentText()
            header = self.header_edit.text().strip() or 'DATA'

            # 设置数据校验头
            self.data_source_manager.set_data_header(header)

            data_source, success_log, justfloat_mode = self._build_data_source_from_ui(source_type, header)
            if data_source is None:
                return

            # 设置原始数据回调函数
            data_source.set_raw_data_callback(self.on_raw_data_received)
            # 设置断开回调函数
            data_source.set_disconnect_callback(self.disconnect_callback)
            success = self.data_source_manager.set_source(data_source)

            # 如果是Justfloat无时间戳模式，重置数据点计数器
            if success and justfloat_mode == 'without_timestamp':
                data_source.reset_data_point_counter()

            # justfloat重连后恢复历史通道名映射
            if success and hasattr(data_source, 'get_protocol') and data_source.get_protocol() == 'justfloat':
                self._restore_justfloat_channel_names_after_connect()

            if success:
                self.log_print(success_log)
                if hasattr(self, 'arterial_pipeline') and self.arterial_pipeline is not None:
                    self.arterial_pipeline.reset()
                if hasattr(self, '_reset_arterial_ui_state'):
                    self._reset_arterial_ui_state()
                self.status_label.setText("已连接")
                self.status_label.setStyleSheet("color: green;")
                # 每次连接都恢复为“继续接收显示”状态
                self.waveform_widget.is_paused = False
                self.pause_btn.setText("暂停")
                self.pause_btn.setEnabled(True)
                self.send_btn.setEnabled(source_type in ("UDP", "TCP", "串口"))
                self.save_btn.setEnabled(True)
                # 连接后锁定配置，防止运行中误改
                self._set_connection_config_enabled(False)
                # 启动数据接收线程
                self.start_receive_thread()

                # 清空旧通道
                self.waveform_widget.clear_all()
                self.channels_label.setText("自动检测通道...")
                self.last_channels_text = "自动检测通道..."

                # 重置校验头不匹配计数器
                self.data_source_manager.reset_header_mismatch_count()

                # 转换到已连接-等待数据状态
                self.state_machine.handle_event('connect')

                # 默认不自动保存，避免磁盘IO影响实时接收性能
                self.save_btn.setText("开始保存")
                self.save_file_label.setText("保存文件: 无")
                self.auto_save_enabled = False
            else:
                QMessageBox.warning(self, "失败", "连接失败，请检查配置")
        except ValueError:
            QMessageBox.warning(self, "错误", "请输入有效的端口号或波特率")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"连接失败: {str(e)}")

    def on_source_type_changed(self, source_type: str):
        """数据源类型改变事件处理。"""
        if source_type == "UDP":
            self.udp_group.setVisible(True)
            self.tcp_group.setVisible(False)
            self.serial_group.setVisible(False)
            self.file_group.setVisible(False)
            # UDP模式：启用数据校验头配置
            self.header_group.setEnabled(True)
            self.justfloat_group.setVisible(False)
            self.header_group.setVisible(True)
            return

        if source_type == "TCP":
            self.udp_group.setVisible(False)
            self.tcp_group.setVisible(True)
            self.serial_group.setVisible(False)
            self.file_group.setVisible(False)
            self.header_group.setEnabled(True)
            self.justfloat_group.setVisible(False)
            self.header_group.setVisible(True)
            self.on_tcp_mode_changed(self.tcp_mode_combo.currentText())
            return

        if source_type == "串口":
            self.udp_group.setVisible(False)
            self.tcp_group.setVisible(False)
            self.serial_group.setVisible(True)
            self.file_group.setVisible(False)
            self.serial_group.setTitle("串口配置")
            # 根据协议类型控制数据校验头配置的启用/禁用
            self.on_protocol_changed(self.protocol_combo.currentText())
            return

        # 文件
        self.udp_group.setVisible(False)
        self.tcp_group.setVisible(False)
        self.serial_group.setVisible(False)
        self.file_group.setVisible(True)
        self.on_file_protocol_changed(self.file_protocol_combo.currentText())

    def _apply_protocol_ui(self, protocol_text: str):
        """统一处理协议相关UI显隐，供串口/文件复用。"""
        if protocol_text == "文本协议":
            self.header_group.setVisible(True)
            self.justfloat_group.setVisible(False)
        elif protocol_text in ["Justfloat", "Firewater"]:
            self.header_group.setVisible(False)
            self.justfloat_group.setVisible(True)
            self.on_justfloat_mode_changed(self.justfloat_mode_combo.currentText())
        else:  # Rawdata
            self.header_group.setVisible(False)
            self.justfloat_group.setVisible(False)

    def refresh_serial_ports(self):
        """刷新串口列表，扫描所有可用的COM端口。"""
        try:
            import serial.tools.list_ports

            # 获取所有可用的串口
            ports = serial.tools.list_ports.comports()

            # 清空当前列表
            self.serial_port_combo.clear()

            if ports:
                # 添加所有可用的串口
                for port in ports:
                    port_info = f"{port.device} - {port.description}"
                    self.serial_port_combo.addItem(port_info, port.device)
                self.log_print(f"扫描到 {len(ports)} 个串口")
            else:
                # 没有找到串口
                self.serial_port_combo.addItem("无可用串口", "")
                self.log_print("未扫描到可用串口")
        except ImportError:
            # pyserial未安装
            self.serial_port_combo.clear()
            self.serial_port_combo.addItem("请安装pyserial库", "")
            self.log_print("错误: 未安装pyserial库，请运行: pip install pyserial")
        except Exception as e:
            # 扫描失败
            self.serial_port_combo.clear()
            self.serial_port_combo.addItem("扫描失败", "")
            self.log_print(f"扫描串口失败: {e}")

    def refresh_serial_ports_and_show_popup(self):
        """刷新串口列表并显示下拉框。"""
        self.refresh_serial_ports()
        QComboBox.showPopup(self.serial_port_combo)

    def on_protocol_changed(self, protocol_text: str):
        """串口协议改变事件处理。"""
        self._apply_protocol_ui(protocol_text)

    def on_file_protocol_changed(self, protocol_text: str):
        """文件协议改变事件处理。"""
        self._apply_protocol_ui(protocol_text)

    def on_tcp_mode_changed(self, mode_text: str):
        """TCP模式切换：监听/主动连接。"""
        is_client = (mode_text == "主动连接")

        self.tcp_host_edit.setEnabled(not is_client)
        self.tcp_port_edit.setEnabled(not is_client)
        self.tcp_target_host_edit.setEnabled(is_client)
        self.tcp_target_port_edit.setEnabled(is_client)

    def browse_input_file(self):
        """浏览输入数据文件（.log/.bin/.csv）。"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择数据文件",
            self.file_path_edit.text() or os.getcwd(),
            "数据文件 (*.log *.bin *.csv);;所有文件 (*)",
        )
        if file_path:
            self.file_path_edit.setText(file_path)

    def _set_connection_config_enabled(self, enabled: bool):
        """统一控制连接相关配置项是否可编辑。"""
        self.source_type_combo.setEnabled(enabled)
        self.udp_group.setEnabled(enabled)
        self.tcp_group.setEnabled(enabled)
        self.serial_group.setEnabled(enabled)
        self.file_group.setEnabled(enabled)
        self.header_group.setEnabled(enabled)
        self.justfloat_group.setEnabled(enabled)