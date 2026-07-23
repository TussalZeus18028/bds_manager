# -*- coding: utf-8 -*-
"""
BDS 服务器进程管理（PySide6 版）。

从旧 PyQt5 版本提取并改写：pyqtSignal → Signal，保持相同逻辑。

v3.1 改进：
- 进程级资源监控（psutil 采集 BDS 进程 CPU/内存/线程数）
- 优雅停服流程：save-all → save-on → stop → 等待 → terminate → kill
- 启动参数注入（命令行参数）
- 假死检测（is_running 增加健康检查）
"""

import sys
import os
import time
import locale
import threading
import subprocess
import logging
from PySide6.QtCore import QThread, Signal
import psutil

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
        output_received(str)       — 服务器控制台输出（已解码）
        process_stopped()          — 进程已退出
        error_occurred(str)        — 错误消息
        status_changed(bool)       — 运行状态变化 (True=运行中, False=已停止)
        proc_stats(dict)           — 进程级资源快照 {cpu, mem_mb, threads, open_files}
    """

    output_received = Signal(str)
    process_stopped = Signal()
    error_occurred = Signal(str)
    status_changed = Signal(bool)
    proc_stats = Signal(dict)

    def __init__(self, server_exe: str, work_dir: str, extra_args: list[str] | None = None,
                 parent=None):
        super().__init__(parent)
        self.server_exe = server_exe
        self.work_dir = work_dir
        self.extra_args = extra_args or []
        self.process: subprocess.Popen | None = None
        self._stop_event = threading.Event()
        self._started_at: float = 0.0
        self._psutil_proc: psutil.Process | None = None
        self._monitor_thread: threading.Thread | None = None
        self._monitor_active = False
        self._last_output_time: float = 0.0

    @property
    def started_at(self) -> float:
        return self._started_at

    @property
    def uptime_seconds(self) -> float:
        if self._started_at <= 0:
            return 0.0
        return time.time() - self._started_at

    @property
    def is_running(self) -> bool:
        return (
            self.process is not None
            and self.process.poll() is None
            and not self._stop_event.is_set()
        )

    def run(self):
        self._stop_event.clear()
        cmd = [self.server_exe] + list(self.extra_args)
        try:
            self.process = subprocess.Popen(
                cmd,
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

        # 绑定 psutil 进程对象
        try:
            self._psutil_proc = psutil.Process(self.process.pid)
        except (psutil.NoSuchProcess, OSError):
            self._psutil_proc = None

        self._started_at = time.time()
        self._last_output_time = time.time()
        self.status_changed.emit(True)

        # 启动进程级监控线程
        self._start_proc_monitor()

        for raw in iter(self.process.stdout.readline, b""):
            if self._stop_event.is_set():
                break
            text = _decode_server_line(raw).rstrip()
            self._last_output_time = time.time()
            self.output_received.emit(text)
        self.process.stdout.close()
        self._stop_proc_monitor()
        retcode = self.process.wait()
        if retcode != 0 and not self._stop_event.is_set():
            logger.error("服务器异常退出，返回码: %d", retcode)
            self.error_occurred.emit(f"服务器异常退出，返回码: {retcode}")
        self.status_changed.emit(False)
        self.process_stopped.emit()

    # ---------- 进程级监控 ----------
    def _start_proc_monitor(self):
        self._monitor_active = True
        self._monitor_thread = threading.Thread(target=self._proc_monitor_loop, daemon=True)
        self._monitor_thread.start()

    def _stop_proc_monitor(self):
        self._monitor_active = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=2.0)
            self._monitor_thread = None

    def _proc_monitor_loop(self):
        """每 1.5 秒采集一次 BDS 进程级资源并发射信号。"""
        if not self._psutil_proc:
            return
        while self._monitor_active and self.is_running:
            try:
                cpu = self._psutil_proc.cpu_percent(interval=None)
                mem = self._psutil_proc.memory_info().rss / (1024 * 1024)
                threads = self._psutil_proc.num_threads()
                try:
                    open_files = len(self._psutil_proc.open_files())
                except (psutil.AccessDenied, OSError):
                    open_files = -1
                self.proc_stats.emit({
                    "cpu": cpu,
                    "mem_mb": mem,
                    "threads": threads,
                    "open_files": open_files,
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break
            except Exception as e:
                logger.debug("进程监控异常: %s", e)
            time.sleep(1.5)

    # ---------- 假死检测 ----------
    def is_responsive(self, idle_seconds: float = 60.0) -> bool:
        """最近 N 秒是否有输出。用于检测假死。"""
        if self._last_output_time <= 0:
            return True
        return (time.time() - self._last_output_time) < idle_seconds

    # ---------- 命令发送 ----------
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

    def send_save_all(self):
        """保存世界（先 save-all, save-on 让区块写回）。"""
        self.send_command("save-all")
        self.send_command("save-on")

    def stop_server(self, graceful: bool = True, grace_seconds: int = 10):
        """停止 BDS。

        graceful=True: 先 save-all → save-on → stop → 等待 grace 秒 → terminate → 1s 后 kill
        graceful=False: stop → 等 3s → 未退出则 terminate → 1s 后 kill
        """
        if not self.process:
            return
        if graceful:
            try:
                logger.info("优雅停服: save-all → stop")
                self.send_command("save-all")
                time.sleep(0.5)
                self.send_command("stop")
            except Exception:
                pass
            self._stop_event.set()
            # 等待 grace 秒让 BDS 自行退出
            for _ in range(grace_seconds * 10):
                if self.process.poll() is not None:
                    return
                time.sleep(0.1)
        else:
            try:
                self.send_command("stop")
            except Exception:
                pass
            self._stop_event.set()
            # v3.02.01: 等 3 秒让 BDS 处理 stop 命令并自行退出
            for _ in range(30):  # 3 秒 / 0.1 秒步进
                if self.process.poll() is not None:
                    return
                time.sleep(0.1)
        if self.process.poll() is None:
            if graceful:
                logger.warning("BDS 未在 %ds 内退出，强制 terminate", grace_seconds)
            else:
                logger.info("BDS 未在 3s 内退出，强制 terminate")
            try:
                self.process.terminate()
            except Exception:
                pass
            time.sleep(1)
            if self.process.poll() is None:
                logger.warning("terminate 失败，强制 kill")
                try:
                    self.process.kill()
                except Exception:
                    pass
