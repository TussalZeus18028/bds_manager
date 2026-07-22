# -*- coding: utf-8 -*-
"""
系统资源监控（纯后端，无 UI 依赖）。

提供 CPU / 内存 / 磁盘 / 网络数据采集，通过 PySide6 信号推送到 UI。
"""

import time
import logging
from collections import deque

import psutil
from PySide6.QtCore import QTimer, QObject, Signal

logger = logging.getLogger("bds_manager")


class SystemStatsSnapshot:
    """系统资源快照（数据对象）。"""

    __slots__ = (
        "cpu_percent", "mem_percent", "mem_used_gb", "mem_total_gb",
        "disk_percent", "disk_used_gb", "disk_total_gb",
        "net_sent_kb_per_sec", "net_recv_kb_per_sec",
        "timestamp",
    )

    def __init__(self):
        self.cpu_percent: float = 0.0
        self.mem_percent: float = 0.0
        self.mem_used_gb: float = 0.0
        self.mem_total_gb: float = 0.0
        self.disk_percent: float = 0.0
        self.disk_used_gb: float = 0.0
        self.disk_total_gb: float = 0.0
        self.net_sent_kb_per_sec: float = 0.0
        self.net_recv_kb_per_sec: float = 0.0
        self.timestamp: float = 0.0


class SystemResourceMonitor(QObject):
    """系统资源采集器（非 GUI，通过信号推送到任意 UI 组件）。

    用法：
        monitor = SystemResourceMonitor()
        monitor.stats_updated.connect(ui.update_stats)
        monitor.start(2000)
        ...
        monitor.stop()
    """

    stats_updated = Signal(SystemStatsSnapshot)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer: QTimer | None = None
        self._last_net_io = None
        self._last_time = time.time()
        self._cpu_history = deque(maxlen=60)

    def start(self, interval_ms: int = 2000):
        """启动定时采集。"""
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._collect)
        self._timer.start(interval_ms)
        logger.info("系统资源监控已启动 (间隔 %dms)", interval_ms)

    def stop(self):
        """停止定时采集。"""
        if self._timer and self._timer.isActive():
            self._timer.stop()
            logger.info("系统资源监控已停止")

    def set_interval(self, interval_ms: int):
        if self._timer:
            self._timer.setInterval(interval_ms)

    def _collect(self):
        """采集一次系统资源数据并发射信号。"""
        snap = SystemStatsSnapshot()
        snap.timestamp = time.time()

        try:
            # CPU
            cpu = psutil.cpu_percent(interval=None)
            snap.cpu_percent = cpu
            self._cpu_history.append(cpu)

            # 内存
            mem = psutil.virtual_memory()
            snap.mem_percent = mem.percent
            snap.mem_used_gb = mem.used / (1024**3)
            snap.mem_total_gb = mem.total / (1024**3)

            # 网络
            net = psutil.net_io_counters()
            if self._last_net_io is not None:
                dt = snap.timestamp - self._last_time
                if dt > 0:
                    snap.net_sent_kb_per_sec = (net.bytes_sent - self._last_net_io.bytes_sent) / dt / 1024
                    snap.net_recv_kb_per_sec = (net.bytes_recv - self._last_net_io.bytes_recv) / dt / 1024
            self._last_net_io = net
            self._last_time = snap.timestamp

            # 磁盘
            disk = psutil.disk_usage("/")
            snap.disk_percent = disk.percent
            snap.disk_used_gb = disk.used / (1024**3)
            snap.disk_total_gb = disk.total / (1024**3)
        except Exception as e:
            logger.debug("资源采集异常: %s", e)

        self.stats_updated.emit(snap)
