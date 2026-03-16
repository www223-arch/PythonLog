from enum import Enum
from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class StateViewModel:
    """状态层输出到表现层的最小视图模型。"""

    button_rgb: Tuple[int, int, int]
    flashing: bool
    flash_interval_ms: int
    data_status_text: str
    data_status_color: str


class ConnectionState(Enum):
    """连接状态枚举。"""

    DISCONNECTED = "未连接"
    CONNECTED_WAITING = "已连接-等待数据"
    CONNECTED_RECEIVING = "已连接-接收数据"
    DATA_FORMAT_MISMATCH = "数据格式不匹配"
    DATA_STOPPED = "数据停止"
    PAUSED = "暂停"


class State:
    """状态基类。"""

    def __init__(self, state_machine):
        self.state_machine = state_machine

    def enter(self) -> None:
        pass

    def exit(self) -> None:
        pass

    def handle_event(self, event: str, **kwargs) -> None:
        pass

    def log_print(self, *args, **kwargs) -> None:
        context = self.state_machine.context
        if hasattr(context, "log_print"):
            context.log_print(*args, **kwargs)
        else:
            print(*args, **kwargs)


class DisconnectedState(State):
    def enter(self) -> None:
        self.state_machine.apply_view(
            StateViewModel(
                button_rgb=(100, 100, 100),
                flashing=False,
                flash_interval_ms=0,
                data_status_text="数据状态: 无数据",
                data_status_color="#666",
            )
        )
        self.log_print("[状态] 进入未连接状态")


class ConnectedWaitingState(State):
    def enter(self) -> None:
        self.state_machine.apply_view(
            StateViewModel(
                button_rgb=(100, 149, 237),
                flashing=False,
                flash_interval_ms=0,
                data_status_text="数据状态: 等待数据",
                data_status_color="#666",
            )
        )
        self.log_print("[状态] 进入等待数据状态")


class ConnectedReceivingState(State):
    def enter(self) -> None:
        self.state_machine.apply_view(
            StateViewModel(
                button_rgb=(100, 149, 237),
                flashing=True,
                flash_interval_ms=100,
                data_status_text="数据状态: 正常接收",
                data_status_color="green",
            )
        )
        self.log_print("[状态] 进入接收数据状态")


class DataFormatMismatchState(State):
    def __init__(self, state_machine):
        super().__init__(state_machine)
        self.mismatch_count = 0

    def enter(self) -> None:
        self.state_machine.apply_view(
            StateViewModel(
                button_rgb=(220, 20, 60),
                flashing=True,
                flash_interval_ms=500,
                data_status_text=f"数据状态: 数据格式不匹配 ({self.mismatch_count}次)",
                data_status_color="red",
            )
        )
        self.log_print(f"[状态] 进入数据格式不匹配状态，次数: {self.mismatch_count}")


class DataStoppedState(State):
    def enter(self) -> None:
        self.state_machine.apply_view(
            StateViewModel(
                button_rgb=(100, 149, 237),
                flashing=False,
                flash_interval_ms=0,
                data_status_text="数据状态: 数据停止",
                data_status_color="#666",
            )
        )
        self.log_print("[状态] 进入数据停止状态")


class PausedState(State):
    def enter(self) -> None:
        self.state_machine.apply_view(
            StateViewModel(
                button_rgb=(100, 149, 237),
                flashing=False,
                flash_interval_ms=0,
                data_status_text="数据状态: 已暂停",
                data_status_color="#666",
            )
        )
        self.log_print("[状态] 进入暂停状态")


class StateMachine:
    """有限状态机。"""

    def __init__(self, context):
        self.context = context
        self.current_state = None
        self.transition_matrix = self._build_transition_matrix()
        self.debug_print("[FSM] 已加载状态-事件矩阵")
        for line in self.get_transition_matrix_readable():
            self.debug_print(f"[FSM] {line}")
        self.transition_to(DisconnectedState(self))

    def _build_transition_matrix(self):
        return {
            DisconnectedState: {
                "connect": ConnectedWaitingState,
            },
            ConnectedWaitingState: {
                "data_received": ConnectedReceivingState,
                "format_error": DataFormatMismatchState,
                "disconnect": DisconnectedState,
                "timeout": DataStoppedState,
            },
            ConnectedReceivingState: {
                "data_received": ConnectedReceivingState,
                "timeout": DataStoppedState,
                "format_error": DataFormatMismatchState,
                "pause": PausedState,
                "disconnect": DisconnectedState,
            },
            DataFormatMismatchState: {
                "data_received": ConnectedReceivingState,
                "timeout": ConnectedWaitingState,
                "format_error": DataFormatMismatchState,
                "disconnect": DisconnectedState,
            },
            DataStoppedState: {
                "data_received": ConnectedReceivingState,
                "format_error": DataFormatMismatchState,
                "disconnect": DisconnectedState,
            },
            PausedState: {
                "resume": ConnectedReceivingState,
                "disconnect": DisconnectedState,
                "format_error": DataFormatMismatchState,
            },
        }

    def get_transition_matrix_readable(self):
        lines = []
        for state_cls, event_map in self.transition_matrix.items():
            for event, target_cls in event_map.items():
                lines.append(f"{state_cls.__name__} --({event})-> {target_cls.__name__}")
        return lines

    def debug_print(self, message: str) -> None:
        if hasattr(self.context, "fsm_debug_print"):
            self.context.fsm_debug_print(message)
        else:
            print(message)

    def apply_view(self, view: StateViewModel) -> None:
        """将状态视图模型下发给表现层。"""
        if hasattr(self.context, "apply_fsm_view"):
            self.context.apply_fsm_view(view)

    def transition_to(self, new_state, event: str = "manual", **kwargs) -> None:
        old_name = self.current_state.__class__.__name__ if self.current_state else "None"
        new_name = new_state.__class__.__name__
        self.debug_print(f"[FSM][TRANSITION] {old_name} --({event})-> {new_name} | kwargs={kwargs}")

        if self.current_state:
            self.log_print(f"[状态机] 退出状态: {self.current_state.__class__.__name__}")
            self.current_state.exit()

        self.log_print(f"[状态机] 进入状态: {new_state.__class__.__name__}")
        self.current_state = new_state
        if isinstance(self.current_state, DataFormatMismatchState):
            self.current_state.mismatch_count = kwargs.get("mismatch_count", self.current_state.mismatch_count)
        self.current_state.enter()
        if hasattr(self.context, "_debug_ui_state_snapshot"):
            self.context._debug_ui_state_snapshot("after_transition", event=event)

    def _handle_self_transition(self, event: str, **kwargs) -> None:
        if isinstance(self.current_state, DataFormatMismatchState) and event == "format_error":
            self.current_state.mismatch_count = kwargs.get("mismatch_count", self.current_state.mismatch_count + 1)
            self.apply_view(
                StateViewModel(
                    button_rgb=(220, 20, 60),
                    flashing=True,
                    flash_interval_ms=500,
                    data_status_text=f"数据状态: 数据格式不匹配 ({self.current_state.mismatch_count}次)",
                    data_status_color="red",
                )
            )
            self.debug_print(
                f"[FSM][SELF] DataFormatMismatchState format_error mismatch_count={self.current_state.mismatch_count}"
            )
            if hasattr(self.context, "_debug_ui_state_snapshot"):
                self.context._debug_ui_state_snapshot("after_self_transition", event=event)
            return

        self.debug_print(f"[FSM][SELF] 忽略同状态事件: state={self.current_state.__class__.__name__}, event={event}")

    def handle_event(self, event: str, **kwargs) -> None:
        if not self.current_state:
            return

        state_cls = self.current_state.__class__
        current_name = state_cls.__name__
        self.debug_print(f"[FSM][EVENT] state={current_name}, event={event}, kwargs={kwargs}")

        event_map = self.transition_matrix.get(state_cls, {})
        target_cls = event_map.get(event)

        if target_cls is None:
            self.debug_print(f"[FSM][DROP] 未定义转换: state={current_name}, event={event}")
            return

        if target_cls == state_cls:
            self._handle_self_transition(event, **kwargs)
            return

        self.transition_to(target_cls(self), event=event, **kwargs)

    def log_print(self, *args, **kwargs) -> None:
        if hasattr(self.context, "log_print"):
            self.context.log_print(*args, **kwargs)
        else:
            print(*args, **kwargs)

    def get_current_state_name(self) -> str:
        if self.current_state:
            return self.current_state.__class__.__name__
        return "None"

    def is_connected(self) -> bool:
        return not isinstance(self.current_state, DisconnectedState)

    def is_receiving(self) -> bool:
        return isinstance(self.current_state, ConnectedReceivingState)

    def is_paused(self) -> bool:
        return isinstance(self.current_state, PausedState)


class ConnectionStateManager:
    """连接状态管理器（兼容保留）。"""

    def __init__(self, connect_btn, data_status_label):
        self.connect_btn = connect_btn
        self.data_status_label = data_status_label
        self.current_state = ConnectionState.DISCONNECTED

    def transition_to(self, new_state: ConnectionState, **kwargs):
        self.current_state = new_state

    def get_current_state(self) -> ConnectionState:
        return self.current_state

    def is_connected(self) -> bool:
        return self.current_state != ConnectionState.DISCONNECTED

    def is_receiving(self) -> bool:
        return self.current_state == ConnectionState.CONNECTED_RECEIVING

    def is_paused(self) -> bool:
        return self.current_state == ConnectionState.PAUSED
