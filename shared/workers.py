# -*- coding: utf-8 -*-
"""
共享工作线程模块：BaseWorker 基类及通用后台任务模式。

设计原则：
- 轻量级，只依赖 PySide6.QtCore (QThread, Signal)，不依赖 Widgets。
- 使用 PySide6 的 Signal 语法（非 pyqtSignal）。
- 提供标准生命周期：进度 → 日志 → 完成/错误。
"""

import traceback
from PySide6.QtCore import QThread, Signal


class BaseWorker(QThread):
    """通用后台工作者基类。

    信号：
        progress(str)  — 进度描述
        log(str, str)   — (消息, 级别: INFO/WARN/ERROR/SUCCESS)
        finished(bool, str) — (成功, 描述)
    """

    progress = Signal(str)
    log_signal = Signal(str, str)
    finished = Signal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel = False

    def cancel(self):
        """请求取消当前任务（子类应在 run() 中检查此标志）。"""
        self._cancel = True

    def _emit_log(self, msg: str, level: str = "INFO"):
        """发送日志信号（非线程安全则自动排队投递）。"""
        self.log_signal.emit(msg, level)


class SimpleWorker(BaseWorker):
    """简单的后台任务：执行无参 callable，完成时发送 finished 信号。

    用法:
        worker = SimpleWorker(lambda: do_heavy_work())
        worker.finished.connect(on_done)
        worker.start()
    """

    def __init__(self, func, parent=None):
        super().__init__(parent)
        self._func = func

    def run(self):
        try:
            result = self._func()
            self.finished.emit(True, str(result) if result else "完成")
        except Exception:
            self._emit_log(traceback.format_exc(), "ERROR")
            self.finished.emit(False, traceback.format_exc())
