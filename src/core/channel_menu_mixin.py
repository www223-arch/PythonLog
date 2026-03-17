from PyQt5.QtWidgets import QAction, QColorDialog, QInputDialog, QMenu, QMessageBox


class ChannelMenuMixin:
    """通道右键菜单、颜色设置与重命名逻辑混入。"""

    def show_channel_context_menu(self, position):
        """显示通道右键菜单。

        Args:
            position: 鼠标位置
        """
        channels = self.waveform_widget.get_all_channels()

        self.log_print(f"[show_channel_context_menu] 当前通道: {channels}")

        if not channels:
            return

        menu = QMenu(self)

        color_menu = menu.addMenu("设置通道颜色")
        for channel_name in channels:
            action = QAction(channel_name, self)
            action.triggered.connect(lambda checked, name=channel_name: self.set_channel_color(name))
            color_menu.addAction(action)

        is_justfloat = False
        current_source = self.data_source_manager.get_current_source()
        if hasattr(current_source, 'get_protocol'):
            protocol = current_source.get_protocol()
            is_justfloat = (protocol == 'justfloat')
            self.log_print(f"[show_channel_context_menu] 当前协议: {protocol}, is_justfloat: {is_justfloat}")
        else:
            self.log_print("[show_channel_context_menu] 当前数据源不支持get_protocol方法")

        if is_justfloat:
            self.log_print("[show_channel_context_menu] 显示重命名通道菜单")
            rename_menu = menu.addMenu("重命名通道")
            for channel_name in channels:
                action = QAction(channel_name, self)
                action.triggered.connect(lambda checked, name=channel_name: self.rename_channel(name))
                rename_menu.addAction(action)
        else:
            self.log_print("[show_channel_context_menu] 不显示重命名通道菜单（非Justfloat协议）")

        menu.exec_(self.channels_label.mapToGlobal(position))

    def set_channel_color(self, channel_name: str):
        """设置指定通道的颜色。

        Args:
            channel_name: 通道名称
        """
        if channel_name not in self.waveform_widget.channels:
            QMessageBox.warning(self, "错误", f"通道 '{channel_name}' 不存在")
            return

        current_color = self.waveform_widget.channels[channel_name]['color']

        if isinstance(current_color, tuple):
            from PyQt5.QtGui import QColor
            qcolor = QColor(*current_color)
            initial_color = qcolor
        else:
            from PyQt5.QtGui import QColor
            initial_color = QColor(current_color)

        color = QColorDialog.getColor(initial_color, self, f"选择通道 '{channel_name}' 的颜色")

        if color.isValid():
            rgb = (color.red(), color.green(), color.blue())
            self.waveform_widget.update_channel_color(channel_name, rgb)
            self.log_print(f"通道 '{channel_name}' 颜色已更新为: {color.name()} ({rgb})")
        else:
            self.log_print(f"通道 '{channel_name}' 颜色设置已取消")

    def rename_channel(self, old_name: str):
        """重命名通道。

        Args:
            old_name: 原通道名称
        """
        self.log_print(f"[rename_channel] 开始重命名通道: {old_name}")
        self.log_print(f"[rename_channel] waveform_widget.channels: {list(self.waveform_widget.channels.keys())}")
        self.log_print(f"[rename_channel] data_source_manager.channels: {self.data_source_manager.channels}")
        self.log_print(
            f"[rename_channel] data_source_manager.channel_name_mapping: {self.data_source_manager.get_channel_name_mapping()}"
        )
        self._debug_channel_state("rename_start")

        if old_name not in self.waveform_widget.channels:
            QMessageBox.warning(self, "错误", f"通道 '{old_name}' 不存在")
            return

        new_name, ok = QInputDialog.getText(self, "重命名通道", f"请输入通道 '{old_name}' 的新名称:")

        if ok and new_name:
            new_name = new_name.strip()

            if not new_name:
                QMessageBox.warning(self, "错误", "通道名称不能为空")
                return

            if new_name in self.waveform_widget.channels:
                QMessageBox.warning(self, "错误", f"通道 '{new_name}' 已存在")
                return

            self.log_print(f"[rename_channel] 用户输入新名称: {new_name}")

            self.waveform_widget.rename_channel(old_name, new_name)
            self.log_print("[rename_channel] waveform_widget.rename_channel 完成")
            self._debug_channel_state("rename_after_waveform")

            self.data_source_manager.set_channel_name_mapping(old_name, new_name)
            self.log_print("[rename_channel] data_source_manager.set_channel_name_mapping 完成")
            self._debug_channel_state("rename_after_manager")

            channels_text = ", ".join(self.data_source_manager.get_channels())
            self.channels_label.setText(f"检测到通道: {channels_text}")

            self.log_print(f"[rename_channel] 通道 '{old_name}' 已重命名为 '{new_name}'")
            self.log_print("[rename_channel] 最终状态:")
            self.log_print(f"[rename_channel]   waveform_widget.channels: {list(self.waveform_widget.channels.keys())}")
            self.log_print(f"[rename_channel]   data_source_manager.channels: {self.data_source_manager.channels}")
            self.log_print(
                f"[rename_channel]   data_source_manager.channel_name_mapping: {self.data_source_manager.get_channel_name_mapping()}"
            )
        else:
            self.log_print(f"[rename_channel] 通道 '{old_name}' 重命名已取消")
