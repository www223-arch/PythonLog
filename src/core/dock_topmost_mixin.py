import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDockWidget, QWidget


class DockTopmostMixin:
    """Dock浮动窗口置顶与层级管理混入。"""

    def _resolve_windows_root_hwnd(self, widget: QWidget):
        """获取窗口根句柄，避免对子控件句柄置顶无效。"""
        if os.name != 'nt' or widget is None:
            return None

        try:
            import ctypes
            hwnd = int(widget.winId())
            GA_ROOT = 2
            root = ctypes.windll.user32.GetAncestor(hwnd, GA_ROOT)
            return int(root) if root else int(hwnd)
        except Exception:
            return None

    def _set_windows_owner(self, widget: QWidget, owner: QWidget):
        """设置Windows窗口owner；浮动页设为None可避免随主窗口最小化。"""
        if os.name != 'nt' or widget is None:
            return

        try:
            import ctypes
            hwnd = self._resolve_windows_root_hwnd(widget)
            if hwnd is None:
                return

            owner_hwnd = 0
            if owner is not None:
                resolved_owner = self._resolve_windows_root_hwnd(owner)
                owner_hwnd = int(resolved_owner) if resolved_owner is not None else 0

            GWL_HWNDPARENT = -8
            set_window_long_ptr = ctypes.windll.user32.SetWindowLongPtrW
            set_window_long_ptr.restype = ctypes.c_void_p
            set_window_long_ptr.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
            set_window_long_ptr(ctypes.c_void_p(hwnd), GWL_HWNDPARENT, ctypes.c_void_p(owner_hwnd))
            self.window_debug_print(
                f"[WIN_DEBUG] set_owner widget_hwnd={hwnd} owner_hwnd={owner_hwnd} "
                f"widget={type(widget).__name__}"
            )
        except Exception:
            pass

    def _set_dock_transient_parent(self, dock: QDockWidget, parent_widget: QWidget):
        """设置或清空浮动Dock的transient parent，降低被主窗口状态绑定概率。"""
        if dock is None:
            return

        try:
            dock_window = dock.windowHandle()
            parent_window = parent_widget.windowHandle() if parent_widget is not None else None
            if dock_window is not None:
                dock_window.setTransientParent(parent_window)
                self.window_debug_print(
                    f"[WIN_DEBUG] transient_parent dock={self._dock_tag(dock)} "
                    f"set={'main' if parent_widget is not None else 'None'}"
                )
        except Exception as e:
            self.window_debug_print(f"[WIN_DEBUG] transient_parent_failed dock={self._dock_tag(dock)} err={e}")

    def _apply_qt_topmost_flag(self, widget: QWidget, on_top: bool):
        """按 test.py 方案切换Qt置顶标志，并通过show()立即生效。"""
        if widget is None:
            return

        try:
            current_top = bool(widget.windowFlags() & Qt.WindowStaysOnTopHint)
            if current_top == bool(on_top):
                return

            was_visible = widget.isVisible()
            flags = widget.windowFlags() | Qt.Window
            if on_top:
                flags |= Qt.WindowStaysOnTopHint
            else:
                flags &= ~Qt.WindowStaysOnTopHint
            widget.setWindowFlags(flags)
            if was_visible:
                widget.show()
            self.window_debug_print(
                f"[WIN_DEBUG] qt_topmost widget={type(widget).__name__} on_top={on_top} "
                f"was_visible={was_visible}"
            )
        except Exception:
            pass

    def _apply_qwindow_topmost_flag(self, dock: QDockWidget, on_top: bool):
        """对浮动Dock的QWindow设置置顶标志，避免QWidget setWindowFlags副作用。"""
        if dock is None:
            return
        try:
            window_handle = dock.windowHandle()
            if window_handle is None:
                return
            window_handle.setFlag(Qt.WindowStaysOnTopHint, bool(on_top))
        except Exception:
            pass

    def _apply_windows_topmost(self, widget: QWidget, on_top: bool, aggressive: bool = False):
        """Windows下使用原生API设置窗口是否置于所有应用上方。"""
        if os.name != 'nt' or widget is None:
            return

        try:
            import ctypes
            hwnd = self._resolve_windows_root_hwnd(widget)
            if hwnd is None:
                return
            HWND_TOPMOST = -1
            HWND_NOTOPMOST = -2
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOOWNERZORDER = 0x0200
            SWP_NOACTIVATE = 0x0010
            SWP_SHOWWINDOW = 0x0040
            flags_on_soft = SWP_NOMOVE | SWP_NOSIZE | SWP_NOOWNERZORDER | SWP_NOACTIVATE
            flags_on_hard = SWP_NOMOVE | SWP_NOSIZE | SWP_NOOWNERZORDER | SWP_SHOWWINDOW
            flags_off = SWP_NOMOVE | SWP_NOSIZE | SWP_NOOWNERZORDER | SWP_NOACTIVATE

            if on_top:
                if aggressive:
                    # 仅在用户显式置顶等关键时机做强置顶，避免高频守护导致闪烁。
                    ctypes.windll.user32.SetWindowPos(
                        hwnd,
                        HWND_NOTOPMOST,
                        0,
                        0,
                        0,
                        0,
                        flags_on_hard,
                    )
                    ctypes.windll.user32.SetWindowPos(
                        hwnd,
                        HWND_TOPMOST,
                        0,
                        0,
                        0,
                        0,
                        flags_on_hard,
                    )
                    try:
                        ctypes.windll.user32.SetForegroundWindow(hwnd)
                    except Exception:
                        pass
                else:
                    ctypes.windll.user32.SetWindowPos(
                        hwnd,
                        HWND_TOPMOST,
                        0,
                        0,
                        0,
                        0,
                        flags_on_soft,
                    )
            else:
                ctypes.windll.user32.SetWindowPos(
                    hwnd,
                    HWND_NOTOPMOST,
                    0,
                    0,
                    0,
                    0,
                    flags_off,
                )
            self.window_debug_print(f"[WIN_DEBUG] win32_topmost hwnd={hwnd} on_top={on_top} aggressive={aggressive}")
        except Exception:
            pass

    def _on_topmost_guard_tick(self):
        """周期守护：确保钉住页始终在所有应用上方。"""
        if os.name != 'nt':
            return

        # 高频守护优先钉住页，主窗口低频重申避免重排干扰。
        self._keep_pinned_dock_front()

        tick = getattr(self, '_topmost_tick_counter', 0) + 1
        self._topmost_tick_counter = tick
        if getattr(self, '_global_above_taskbar', False) and tick % 10 == 0:
            self._apply_windows_topmost(self, True)

    def _keep_pinned_dock_front(self):
        """若存在钉住页面，始终保持其位于其他页面之上。"""
        dock = getattr(self, '_pinned_dock', None)
        if dock is None:
            return
        if not dock.isFloating():
            self._force_refloat_pinned_dock(dock)
            if not dock.isFloating():
                self._pinned_dock = None
            return

        if not dock.isVisible():
            return

        # 钉住页持续保持“独立于主窗口”的关系，避免被主窗口层级覆盖。
        self._set_dock_transient_parent(dock, None)
        self._set_windows_owner(dock, None)
        self._apply_qwindow_topmost_flag(dock, True)

        dock.raise_()
        if os.name == 'nt':
            self._apply_windows_topmost(dock, True, aggressive=False)

    def _force_refloat_pinned_dock(self, dock: QDockWidget):
        """防止已钉住页面被系统/布局回收到主窗口停靠态。"""
        if dock is None:
            return
        if self._reasserting_pinned_dock:
            return
        if not getattr(dock, '_is_on_top', False) and self._pinned_dock is not dock:
            return
        if dock.isFloating():
            return

        self._reasserting_pinned_dock = True
        try:
            dock.setFloating(True)
            dock.show()
            self._set_dock_transient_parent(dock, None)
            self._set_windows_owner(dock, None)
            if os.name == 'nt':
                self._apply_windows_topmost(dock, True, aggressive=True)
            dock.raise_()
            dock.activateWindow()
            self._pinned_dock = dock
        finally:
            self._reasserting_pinned_dock = False

    def _enforce_global_topmost(self):
        """主窗口与浮动页统一保持高层级，避免被任务栏/导航层覆盖。"""
        if not getattr(self, '_global_above_taskbar', False):
            return

        if os.name == 'nt':
            self._apply_windows_topmost(self, True, aggressive=False)
            pinned = getattr(self, '_pinned_dock', None)
            for dock in (self.control_dock, self.waveform_dock, self.raw_data_dock):
                if dock.isFloating() and dock.isVisible():
                    should_top = bool(pinned is dock or getattr(dock, '_is_on_top', False))
                    self._apply_windows_topmost(dock, should_top, aggressive=False)
        else:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
            self.show()
        self._keep_pinned_dock_front()

    def _set_floating_dock_on_top(self, dock: QDockWidget, on_top: bool):
        """设置浮动页是否置顶显示。"""
        if dock is None:
            return

        if not dock.isFloating() and on_top:
            return

        dock._is_on_top = bool(on_top)
        if on_top:
            for other in (self.control_dock, self.waveform_dock, self.raw_data_dock):
                if other is dock:
                    continue
                if getattr(other, '_is_on_top', False):
                    other._is_on_top = False
                    other_pin_btn = getattr(other, '_pin_btn', None)
                    if other_pin_btn is not None and other_pin_btn.isChecked():
                        other_pin_btn.blockSignals(True)
                        other_pin_btn.setChecked(False)
                        other_pin_btn.setIcon(self._build_pin_icon(False))
                        other_pin_btn.setToolTip("置顶（显示在所有应用上方）")
                        other_pin_btn.blockSignals(False)
                    self._unlock_pinned_dock_docking(other)
            self._pinned_dock = dock
            self._lock_pinned_dock_docking(dock)
        else:
            if self._pinned_dock is dock:
                self._pinned_dock = None
            self._unlock_pinned_dock_docking(dock)

        should_top = bool(on_top)
        self.window_debug_print(
            f"[WIN_DEBUG] pin_toggle dock={self._dock_tag(dock)} on_top={on_top} "
            f"should_top={should_top} floating={dock.isFloating()} visible={dock.isVisible()}"
        )
        if dock.isFloating():
            self._set_dock_transient_parent(dock, None)
            self._set_windows_owner(dock, None)
            self._apply_qwindow_topmost_flag(dock, should_top)
        # 对QDockWidget避免使用setWindowFlags路径，防止浮动页被回收进主布局。
        if not isinstance(dock, QDockWidget):
            self._apply_qt_topmost_flag(dock, should_top)
        if os.name == 'nt':
            self._apply_windows_topmost(dock, should_top, aggressive=should_top)
        else:
            if not isinstance(dock, QDockWidget):
                dock.setWindowFlag(Qt.WindowStaysOnTopHint, should_top)
                dock.show()

        if on_top:
            dock.raise_()
            dock.activateWindow()

        pin_btn = getattr(dock, '_pin_btn', None)
        if pin_btn is not None:
            pin_btn.setIcon(self._build_pin_icon(on_top))
            pin_btn.setToolTip("取消置顶（恢复普通层级）" if on_top else "置顶（显示在所有应用上方）")

        self._position_floating_controls(dock)
        self._keep_pinned_dock_front()