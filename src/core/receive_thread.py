import queue
import time

from PyQt5.QtCore import QThread, pyqtSignal


class DataReceiveThread(QThread):
    """数据接收线程。

    在后台接收和解析数据，将数据放入队列。
    """

    disconnect_signal = pyqtSignal()

    def __init__(self, data_source_manager, data_queue, stop_event, log_print, parent=None):
        super().__init__(parent)
        self.data_source_manager = data_source_manager
        self.data_queue = data_queue
        self.stop_event = stop_event
        self.log_print = log_print
        self.recv_ok_count = 0
        self.drop_count = 0

    def run(self):
        self.log_print("[DataReceiveThread] 启动数据接收线程")

        data_source_manager = self.data_source_manager
        data_queue = self.data_queue
        stop_event = self.stop_event
        log_print = self.log_print

        while not stop_event.is_set():
            try:
                source = data_source_manager.current_source
                if source is None or not source.is_connected:
                    self.disconnect_signal.emit()
                    break

                frame = data_source_manager.read_frame()

                if frame is not None:
                    data_queue.put(frame, block=False)
                    self.recv_ok_count += 1
                    if getattr(source, "port", None) == "FILE":
                        time.sleep(0.0005)
                else:
                    time.sleep(0.0002)
            except queue.Full:
                self.drop_count += 1
                try:
                    data_queue.get_nowait()
                except queue.Empty:
                    pass
                try:
                    data_queue.put_nowait(frame)
                except queue.Full:
                    pass
            except AttributeError as e:
                log_print(f"[DataReceiveThread] 数据源访问失败: {e}")
                self.disconnect_signal.emit()
                break
            except Exception:
                pass

        log_print("[DataReceiveThread] 停止数据接收线程")
