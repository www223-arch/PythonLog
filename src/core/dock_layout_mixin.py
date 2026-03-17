from PyQt5.QtCore import QEvent, QTimer, QSize, Qt, QRectF, QPointF
from PyQt5.QtGui import QBrush, QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PyQt5.QtWidgets import QAction, QDockWidget, QHBoxLayout, QToolBar, QToolButton, QWidget


class DockLayoutMixin:
    """Dock布局、工具栏与交互行为混入。"""

    def _create_panel_dock(self, title: str, object_name: str, widget: QWidget, area) -> QDockWidget:
        """创建可拖拽/可分离的Dock面板。"""
        dock = QDockWidget(title, self)
        dock.setObjectName(object_name)
        dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        dock.setWidget(widget)
        dock.setMinimumSize(QSize(220, 140))
        # 记录原始标题栏，便于在“单页/合并页”间切换样式
        dock._default_title_bar = dock.titleBarWidget()
        dock._last_dock_area = area
        self.addDockWidget(area, dock)
        self._setup_floating_controls(dock)
        return dock

    def _setup_floating_controls(self, dock: QDockWidget):
        """为每个Dock创建浮动时显示的右上角控制按钮（返回/置顶）。"""
        controls = QWidget(dock)
        controls.setObjectName(f"{dock.objectName()}_floatControls")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(2)

        return_btn = QToolButton(controls)
        return_btn.setText("↩")
        return_btn.setToolTip("放回主布局")
        return_btn.setFixedSize(18, 18)
        return_btn.clicked.connect(lambda _=False, d=dock: self._return_floating_dock(d))

        pin_btn = QToolButton(controls)
        pin_btn.setIcon(self._build_pin_icon(False))
        pin_btn.setIconSize(QSize(12, 12))
        pin_btn.setToolTip("置顶（显示在所有应用上方）")
        pin_btn.setCheckable(True)
        pin_btn.setFixedSize(18, 18)
        pin_btn.toggled.connect(lambda checked, d=dock: self._set_floating_dock_on_top(d, checked))

        controls_layout.addWidget(return_btn)
        controls_layout.addWidget(pin_btn)
        controls.setStyleSheet(
            "QToolButton {"
            "border: 1px solid #A9BFEA;"
            "border-radius: 5px;"
            "background: #FFFFFF;"
            "padding: 0px;"
            "font-size: 11px;"
            "}"
            "QToolButton:hover {"
            "background: #EAF2FF;"
            "}"
            "QToolButton:checked {"
            "background: #2E6CE6;"
            "color: #FFFFFF;"
            "border-color: #2E6CE6;"
            "}"
        )
        controls.hide()

        dock._float_controls = controls
        dock._return_btn = return_btn
        dock._pin_btn = pin_btn
        dock._is_on_top = False

    def _build_pin_icon(self, pinned: bool) -> QIcon:
        """绘制图钉图标（置顶开/关）。"""
        pixmap = QPixmap(12, 12)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        color = QColor("#FFFFFF") if pinned else QColor("#24406F")
        painter.setPen(QPen(color, 1.1))
        painter.setBrush(QBrush(color))

        # 图钉头
        head = QPolygonF([
            QPointF(2.0, 2.2),
            QPointF(10.0, 2.2),
            QPointF(8.0, 5.2),
            QPointF(4.0, 5.2),
        ])
        painter.drawPolygon(head)

        # 图钉针身
        painter.drawLine(QPointF(6.0, 5.2), QPointF(6.0, 10.2))
        painter.drawLine(QPointF(6.0, 10.2), QPointF(4.8, 11.0))

        painter.end()
        return QIcon(pixmap)

    def _position_floating_controls(self, dock: QDockWidget):
        """将浮动控制按钮定位到浮动页右上角。"""
        controls = getattr(dock, '_float_controls', None)
        if controls is None:
            return

        controls.adjustSize()
        x = max(4, dock.width() - controls.width() - 6)
        y = 6
        controls.move(x, y)

    def _update_floating_controls_visibility(self, dock: QDockWidget):
        """仅在Dock浮动时显示右上角返回/置顶按钮。"""
        controls = getattr(dock, '_float_controls', None)
        if controls is None:
            return

        pin_btn = getattr(dock, '_pin_btn', None)
        is_on_top = bool(getattr(dock, '_is_on_top', False))
        if pin_btn is not None:
            pin_btn.blockSignals(True)
            pin_btn.setChecked(is_on_top)
            pin_btn.setIcon(self._build_pin_icon(is_on_top))
            pin_btn.setToolTip("取消置顶（恢复普通层级）" if is_on_top else "置顶（显示在所有应用上方）")
            pin_btn.blockSignals(False)

        if dock.isFloating() and dock.isVisible():
            controls.show()
            controls.raise_()
            self._position_floating_controls(dock)
            self._keep_pinned_dock_front()
        else:
            controls.hide()
            # 仅当不再浮动时清除单窗口置顶状态，避免窗口重排瞬时过程误清空
            if (
                not dock.isFloating()
                and getattr(dock, '_is_on_top', False)
                and self._pinned_dock is not dock
            ):
                dock._is_on_top = False
                self._apply_windows_topmost(dock, False)
            # 钉住状态不在这里清空；由“主动取消置顶/主动返回停靠”路径负责清空。

    def _return_floating_dock(self, dock: QDockWidget):
        """将当前浮动页放回主布局。"""
        if dock is None or not dock.isFloating():
            return

        pin_btn = getattr(dock, '_pin_btn', None)
        if pin_btn is not None and pin_btn.isChecked():
            pin_btn.setChecked(False)

        self._unlock_pinned_dock_docking(dock)
        dock._is_on_top = False
        self._apply_windows_topmost(dock, False)
        self._set_windows_owner(dock, self)
        if self._pinned_dock is dock:
            self._pinned_dock = None

        area = getattr(dock, '_last_dock_area', Qt.LeftDockWidgetArea)
        dock.setFloating(False)
        self.addDockWidget(area, dock)
        dock.show()
        self._rebalance_collapsed_docks()

    def _lock_pinned_dock_docking(self, dock: QDockWidget):
        """钉住后锁定为仅浮动态，避免触发停靠再弹回。"""
        if dock is None:
            return

        if not hasattr(dock, '_pre_pin_allowed_areas'):
            dock._pre_pin_allowed_areas = dock.allowedAreas()
        if not hasattr(dock, '_pre_pin_features'):
            dock._pre_pin_features = dock.features()

        dock.setAllowedAreas(Qt.NoDockWidgetArea)
        dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        if not dock.isFloating():
            dock.setFloating(True)
            dock.show()

    def _unlock_pinned_dock_docking(self, dock: QDockWidget):
        """取消钉住后恢复原始停靠能力。"""
        if dock is None:
            return

        pre_allowed_areas = getattr(dock, '_pre_pin_allowed_areas', None)
        if pre_allowed_areas is not None:
            dock.setAllowedAreas(pre_allowed_areas)
            delattr(dock, '_pre_pin_allowed_areas')
        else:
            dock.setAllowedAreas(Qt.AllDockWidgetAreas)

        pre_features = getattr(dock, '_pre_pin_features', None)
        if pre_features is not None:
            dock.setFeatures(pre_features)
            delattr(dock, '_pre_pin_features')
        elif not getattr(self, '_layout_locked', False):
            dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)

    def _init_layout_toolbar(self):
        """布局控制工具栏：锁定尺寸、复原布局。"""
        self.layout_toolbar = QToolBar("布局工具栏", self)
        self.layout_toolbar.setObjectName("layoutToolbar")
        self.layout_toolbar.setMovable(False)
        self.layout_toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.layout_toolbar.setIconSize(QSize(14, 14))
        self.addToolBar(Qt.TopToolBarArea, self.layout_toolbar)

        self.lock_layout_action = QAction(self._build_lock_icon(False), "", self)
        self.lock_layout_action.setCheckable(True)
        self.lock_layout_action.setToolTip("锁定布局")
        self.lock_layout_action.setStatusTip("锁定布局")
        self.lock_layout_action.toggled.connect(self._set_layout_locked)
        self.layout_toolbar.addAction(self.lock_layout_action)

        restore_layout_action = QAction(self._build_restore_icon(), "", self)
        restore_layout_action.setToolTip("复原布局")
        restore_layout_action.setStatusTip("复原布局")
        restore_layout_action.triggered.connect(self._restore_default_layout)
        self.layout_toolbar.addAction(restore_layout_action)

        self.layout_toolbar.addSeparator()

    def _build_lock_icon(self, locked: bool) -> QIcon:
        """绘制同一把锁的闭锁/开锁图标。"""
        pixmap = QPixmap(14, 14)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        outline = QColor("#24406F")
        fill = QColor("#DDE8FF")
        painter.setPen(QPen(outline, 1.4))
        painter.setBrush(QBrush(fill))
        painter.drawRoundedRect(QRectF(3.2, 6.8, 7.6, 5.0), 1.2, 1.2)

        painter.setBrush(Qt.NoBrush)
        if locked:
            # 闭锁：锁梁闭合
            painter.drawArc(3, 1, 8, 8, 0, 180 * 16)
        else:
            # 开锁：锁梁向左上打开
            painter.drawArc(1, 1, 8, 8, 35 * 16, 215 * 16)
            painter.drawLine(QPointF(7.8, 5.0), QPointF(10.6, 3.6))

        painter.end()
        return QIcon(pixmap)

    def _build_restore_icon(self) -> QIcon:
        """绘制复原布局图标。"""
        pixmap = QPixmap(14, 14)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        color = QColor("#24406F")
        painter.setPen(QPen(color, 1.4))
        painter.setBrush(Qt.NoBrush)
        painter.drawArc(2, 2, 10, 10, 35 * 16, 300 * 16)

        painter.setBrush(QBrush(color))
        arrow = QPolygonF([
            QPointF(8.9, 1.7),
            QPointF(12.0, 2.5),
            QPointF(9.7, 4.5),
        ])
        painter.drawPolygon(arrow)

        painter.end()
        return QIcon(pixmap)

    def _install_layer_switching(self):
        """安装图层切换行为：点击任意面板即置顶。"""
        docks = [self.control_dock, self.waveform_dock, self.raw_data_dock]
        for dock in docks:
            dock.installEventFilter(self)
            if dock.widget() is not None:
                dock.widget().installEventFilter(self)

    def _bind_dock_signals(self):
        """绑定Dock信号，动态处理合并页样式。"""
        docks = [self.control_dock, self.waveform_dock, self.raw_data_dock]
        for dock in docks:
            dock.topLevelChanged.connect(lambda _f, d=dock: self._on_dock_top_level_changed(d))
            dock.visibilityChanged.connect(lambda _v, d=dock: self._on_dock_visibility_changed(d))
            dock.dockLocationChanged.connect(lambda a, d=dock: self._on_dock_layout_changed(d, a))

        # Tab切换后同步样式，避免新合成页出现冗余标题/关闭UI
        self.tabifiedDockWidgetActivated.connect(lambda _d: self._update_all_dock_chrome())
        self._update_all_dock_chrome()

    def _update_all_dock_chrome(self):
        docks = [self.control_dock, self.waveform_dock, self.raw_data_dock]
        for dock in docks:
            self._update_dock_chrome(dock)

    def _update_dock_chrome(self, dock: QDockWidget):
        """始终使用系统标题栏，不在停靠态隐藏。"""
        if dock is None:
            return

        if getattr(dock, '_default_title_bar', None) is None:
            dock.setTitleBarWidget(None)
        else:
            dock.setTitleBarWidget(dock._default_title_bar)

    def _on_dock_layout_changed(self, dock: QDockWidget, area=None):
        """布局变化时同步样式并防止页面被挤压到不可操作状态。"""
        if area is not None and area != Qt.NoDockWidgetArea:
            dock._last_dock_area = area
        self._update_dock_chrome(dock)
        self._update_floating_controls_visibility(dock)
        QTimer.singleShot(0, self._rebalance_collapsed_docks)

    def _on_dock_top_level_changed(self, dock: QDockWidget):
        """处理Dock浮动状态变化。"""
        self.window_debug_print(
            f"[WIN_DEBUG] top_level_changed dock={self._dock_tag(dock)} "
            f"floating={dock.isFloating()} visible={dock.isVisible()}"
        )
        if dock.isFloating():
            # 浮动态仅维护owner/transient，避免setWindowFlag触发布局重建回停靠。
            self._set_dock_transient_parent(dock, None)
            self._set_windows_owner(dock, None)
        else:
            if (self._pinned_dock is dock or getattr(dock, '_is_on_top', False)) and not self._reasserting_pinned_dock:
                QTimer.singleShot(0, lambda d=dock: self._force_refloat_pinned_dock(d))
                return
            self._set_dock_transient_parent(dock, self)
            self._set_windows_owner(dock, self)

        self._update_dock_chrome(dock)
        self._update_floating_controls_visibility(dock)
        self._enforce_global_topmost()

    def changeEvent(self, event):
        """主窗口状态变化时，保持分离页独立可见且层级正确。"""
        super().changeEvent(event)

        if event.type() != QEvent.WindowStateChange:
            return

        if self.windowState() & Qt.WindowMinimized:
            self.window_debug_print("[WIN_DEBUG] main_window minimized, enforce floating docks visible")
            for dock in (self.control_dock, self.waveform_dock, self.raw_data_dock):
                if not dock.isFloating():
                    continue
                dock.showNormal()
                dock.raise_()
                self._set_dock_transient_parent(dock, None)
                self._set_windows_owner(dock, None)
                should_top = bool(getattr(dock, '_is_on_top', False))
                self._apply_windows_topmost(dock, should_top)

    def _on_dock_visibility_changed(self, dock: QDockWidget):
        """处理Dock可见性变化。"""
        if getattr(self, '_handling_visibility_change', False):
            return

        self._handling_visibility_change = True
        try:
            self.window_debug_print(
                f"[WIN_DEBUG] visibility_changed dock={self._dock_tag(dock)} "
                f"floating={dock.isFloating()} visible={dock.isVisible()}"
            )
            self._update_dock_chrome(dock)
            self._update_floating_controls_visibility(dock)
            if self._pinned_dock is dock and dock.isFloating() and dock.isVisible():
                self._keep_pinned_dock_front()
            self._enforce_global_topmost()
        finally:
            self._handling_visibility_change = False

    def _rebalance_collapsed_docks(self):
        """当某个停靠页面被挤压过小时，恢复到可见可操作尺寸。"""
        docks = [self.control_dock, self.waveform_dock, self.raw_data_dock]
        collapsed = False
        for dock in docks:
            if dock.isFloating() or not dock.isVisible():
                continue
            if dock.width() < 120 or dock.height() < 90:
                collapsed = True
                break

        if not collapsed:
            return

        self.resizeDocks([self.control_dock, self.waveform_dock], [380, 980], Qt.Horizontal)
        self.resizeDocks([self.waveform_dock, self.raw_data_dock], [560, 240], Qt.Vertical)

    def _bring_main_window_front(self):
        """将主窗口置顶。"""
        self.raise_()
        self.activateWindow()
        self._enforce_global_topmost()

    def _bring_layer_to_front(self, dock: QDockWidget):
        """将指定Dock层置顶。"""
        if dock is None:
            return

        if not dock.isVisible():
            dock.show()

        if dock.isFloating():
            dock.raise_()
            dock.activateWindow()
            self._keep_pinned_dock_front()
            return

        # 在停靠模式下，抬升当前Dock并聚焦，确保用户感知到“切到最上层”
        dock.raise_()
        dock.setFocus(Qt.OtherFocusReason)
        self._update_dock_chrome(dock)

    def eventFilter(self, obj, event):
        """点击任意页面时自动切换到最上层。"""
        if event.type() in (QEvent.Resize, QEvent.Move, QEvent.Show):
            for dock in (self.control_dock, self.waveform_dock, self.raw_data_dock):
                if obj is dock:
                    self._position_floating_controls(dock)
                    break

        if event.type() in (QEvent.MouseButtonPress, QEvent.FocusIn):
            mapping = (
                (self.control_dock, self.control_dock.widget()),
                (self.waveform_dock, self.waveform_dock.widget()),
                (self.raw_data_dock, self.raw_data_dock.widget()),
            )
            for dock, widget in mapping:
                if obj is dock or obj is widget:
                    self._bring_layer_to_front(dock)
                    self._keep_pinned_dock_front()
                    break

        return super().eventFilter(obj, event)

    def _set_layout_locked(self, locked: bool):
        """锁定/解锁布局：锁定后固定当前面板尺寸并禁止拖动分离。"""
        self._layout_locked = locked
        self.lock_layout_action.setIcon(self._build_lock_icon(locked))
        self.lock_layout_action.setToolTip("解锁布局" if locked else "锁定布局")
        self.lock_layout_action.setStatusTip("解锁布局" if locked else "锁定布局")
        docks = [self.control_dock, self.waveform_dock, self.raw_data_dock]
        for dock in docks:
            if locked:
                if dock.isFloating():
                    size = dock.size()
                    dock.setMinimumSize(size)
                    dock.setMaximumSize(size)
                else:
                    area = self.dockWidgetArea(dock)
                    if area in (Qt.LeftDockWidgetArea, Qt.RightDockWidgetArea):
                        width = max(200, dock.width())
                        dock.setMinimumWidth(width)
                        dock.setMaximumWidth(width)
                    elif area in (Qt.TopDockWidgetArea, Qt.BottomDockWidgetArea):
                        height = max(120, dock.height())
                        dock.setMinimumHeight(height)
                        dock.setMaximumHeight(height)

                dock.setFeatures(QDockWidget.NoDockWidgetFeatures)
            else:
                dock.setMinimumSize(QSize(0, 0))
                dock.setMaximumSize(QSize(16777215, 16777215))
                dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)

    def _restore_default_layout(self):
        """一键恢复初始布局与尺寸。"""
        if getattr(self, '_layout_locked', False):
            self.lock_layout_action.setChecked(False)

        self.restoreGeometry(self._default_geometry)
        self.restoreState(self._default_dock_state)
        self.resizeDocks([self.control_dock, self.waveform_dock], [380, 980], Qt.Horizontal)
        self.resizeDocks([self.waveform_dock, self.raw_data_dock], [560, 240], Qt.Vertical)
        self._update_all_dock_chrome()
        self._enforce_global_topmost()