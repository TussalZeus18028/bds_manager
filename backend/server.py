# -*- coding: utf-8 -*-
"""
BDS 服务器进程管理（PySide6 版）。

从旧 PyQt5 版本提取并改写：pyqtSignal → Signal，保持相同逻辑。
"""

import sys
import os
import time
import locale
import threading
import subprocess
import logging
from PySide6.QtCore import QThread, Signal

logger = logging.getLogger("bds_manager")


# ---------- 输出解码 ----------
def _decode_server_line(raw: bytes) -> str:
    """解码服务器输出行：优先系统代码页，UTF-8 兜底。"""
    encodings = [
        locale.getpreferredencoding(False),
        "utf-8",
        "gbk",
        "latin-1",
    ]
    for enc in encodings:
        if not enc:
            continue
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1", errors="replace")


# ---------- 服务器进程 ----------
class ServerProcess(QThread):
    """BDS 服务器进程管理器。

    信号：
        output_received(str)  — 服务器控制台输出（已解码）
        process_stopped()     — 进程已退出
        error_occurred(str)   — 错误消息
        status_changed(bool)  — 运行状态变化 (True=运行中, False=已停止)
    """

    output_received = Signal(str)
    process_stopped = Signal()
    error_occurred = Signal(str)
    status_changed = Signal(bool)

    def __init__(self, server_exe: str, work_dir: str):
        super().__init__()
        self.server_exe = server_exe
        self.work_dir = work_dir
        self.process: subprocess.Popen | None = None
        self._stop_event = threading.Event()

    @property
    def is_running(self) -> bool:
        return (
            self.process is not None
            and self.process.poll() is None
            and not self._stop_event.is_set()
        )

    def run(self):
        self._stop_event.clear()
        try:
            self.process = subprocess.Popen(
                [self.server_exe],
                cwd=self.work_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                bufsize=0,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        except Exception as e:
            logger.error("启动服务器进程失败: %s", e)
            self.error_occurred.emit(f"启动失败: {e}")
            self.status_changed.emit(False)
            self.process_stopped.emit()
            return

        self.status_changed.emit(True)
        for raw in iter(self.process.stdout.readline, b""):
            if self._stop_event.is_set():
                break
            self.output_received.emit(_decode_server_line(raw).rstrip())
        self.process.stdout.close()
        retcode = self.process.wait()
        if retcode != 0 and not self._stop_event.is_set():
            logger.error("服务器异常退出，返回码: %d", retcode)
            self.error_occurred.emit(f"服务器异常退出，返回码: {retcode}")
        self.status_changed.emit(False)
        self.process_stopped.emit()

    def send_command(self, command: str):
        """向服务器发送命令。"""
        if self.process and self.process.stdin and not self._stop_event.is_set():
            try:
                line = command + "\n"
                enc = None
                try:
                    enc = locale.getpreferredencoding(False)
                except Exception:
                    pass
                try:
                    data = line.encode(enc) if enc else line.encode("utf-8")
                except (UnicodeEncodeError, LookupError):
                    data = line.encode("utf-8")
                self.process.stdin.write(data)
                self.process.stdin.flush()
            except Exception as e:
                logger.error("发送命令失败: %s", e)

    def stop_server(self):
        """发送 stop 命令并等待进程退出；超时则强制终止。"""
        if self.process:
            self._stop_event.set()
            try:
                self.send_command("stop")
            except Exception:
                pass
            for _ in range(50):
                if self.process.poll() is not None:
                    break
                time.sleep(0.1)
            if self.process.poll() is None:
                logger.warning("服务器未响应 stop 命令，强制终止")
                self.process.terminate()
                time.sleep(1)
                if self.process.poll() is None:
                    self.process.kill()
        self._stop_event.set()
