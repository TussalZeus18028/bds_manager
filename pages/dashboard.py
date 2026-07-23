# -*- coding: utf-8 -*-
"""
仪表盘页面 —— 服务器概览 + 系统资源监控 + 快捷操作 + 资源曲线。

v3.1 改进：
- 60 点资源历史曲线（CPU/内存/磁盘）QPainter 自绘
- 服务器运行时间计时器
- 后台任务卡片（实时显示正在运行的 Worker）
- 最近备份时间实时刷新（监听 WorldPage.backup_completed）
- 进程级资源卡片（BDS CPU/内存/线程数）
- 假死检测徽章（输出停止超过 60s）
- 操作日志 mini 视图
"""

import os
import time
import logging
from collections import deque
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, QPointF
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame, QSizePolicy,
)
from PySide6.QtGui import QPainter, QPen, QColor, QBrush, QLinearGradient, QFont
from qfluentwidgets import (
    CardWidget, SubtitleLabel, StrongBodyLabel, BodyLabel,
    CaptionLabel, PrimaryPushButton, PushButton,
    FluentIcon, ProgressBar, InfoBar, InfoBarPosition, isDarkTheme,
)

from backend.monitor import SystemStatsSnapshot
from shared.config import config_mgr, get_context
from shared.toast import toast_error, toast_success
from shared.errors import ServerNotRunningError

logger = logging.getLogger("bds_manager")


# ---------- 可滚动页面封装 ----------
def wrap_scrollable(page_widget: QWidget, spacing: int = 12) -> tuple[QWidget, QVBoxLayout]:
    outer = QVBoxLayout(page_widget)
    outer.setContentsMargins(0, 0, 0, 0)
    scroll = QScrollArea(page_widget)
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
    scroll.viewport().setStyleSheet("background: transparent;")
    inner = QWidget()
    inner.setStyleSheet("background: transparent;")
    layout = QVBoxLayout(inner)
    layout.setContentsMargins(24, 16, 24, 16)
    layout.setSpacing(spacing)
    scroll.setWidget(inner)
    outer.addWidget(scroll)
    return inner, layout


# ---------- 资源曲线组件（QPainter 自绘）----------
class ResourceCurveWidget(QWidget):
    """60 点折线/面积图。set_data(label, values, color) 即可。"""

    def __init__(self, label: str = "", color: str = "#0DC5D4", max_value: float = 100.0,
                 unit: str = "%", parent=None):
        super().__init__(parent)
        self._label = label
        self._color = color
        self._max = max_value
        self._unit = unit
        self._values: deque = deque(maxlen=60)
        self._current_text = "—"
        self.setMinimumHeight(80)
        self.setMinimumWidth(160)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_data(self, current: float, values: deque):
        self._current_text = f"{current:.1f}{self._unit}"
        self._values = values
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        # v3.02.01 fix: 主题感知 —— 浅色主题用浅灰底，深色用深灰底
        if isDarkTheme():
            bg_c = QColor("#1e1e1e")
            grid_c = QColor("#2a2a2a")
            empty_c = QColor("#666")
            text_c = QColor("#fff")
        else:
            bg_c = QColor("#f5f5f5")
            grid_c = QColor("#e0e0e0")
            empty_c = QColor("#aaa")
            text_c = QColor("#1a1a1a")
        p.fillRect(self.rect(), bg_c)
        # 网格线（4 条）
        p.setPen(QPen(grid_c, 1, Qt.DashLine))
        for i in range(1, 4):
            y = int(h * i / 4)
            p.drawLine(0, y, w, y)
        # 折线
        if not self._values:
            # 空状态
            p.setPen(QPen(empty_c, 1))
            p.drawText(self.rect(), Qt.AlignCenter, "(等待数据...)")
        else:
            n = len(self._values)
            color = QColor(self._color)
            # 面积渐变
            grad = QLinearGradient(0, 0, 0, h)
            grad.setColorAt(0, QColor(color.red(), color.green(), color.blue(), 80))
            grad.setColorAt(1, QColor(color.red(), color.green(), color.blue(), 5))
            points = []
            for i, v in enumerate(self._values):
                x = int(w * i / max(n - 1, 1))
                y = h - int(h * min(v / self._max, 1.0))
                points.append(QPointF(x, y))
            # 面积
            poly = points + [QPointF(w, h), QPointF(0, h)]
            p.setBrush(QBrush(grad))
            p.setPen(Qt.NoPen)
            from PySide6.QtGui import QPolygonF
            p.drawPolygon(QPolygonF(poly))
            # 折线
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(color, 2))
            p.drawPolyline(QPolygonF(points))
        # 当前值（大字显示在右上）
        p.setPen(QPen(text_c, 1))
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        p.setFont(font)
        p.drawText(self.rect().adjusted(8, 4, -8, -4), Qt.AlignTop | Qt.AlignLeft,
                   f"{self._label}  {self._current_text}")
        p.end()


# ---------- 状态卡片 ----------
class StatusCard(CardWidget):
    """服务器状态：运行状态 / 版本 / 启停按钮 / 运行时间 / 假死徽章。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()
        self._start_time: float = 0.0
        self._last_output_time: float = 0.0
        # 1 秒刷新运行时间
        self._ticker = QTimer(self)
        self._ticker.setInterval(1000)
        self._ticker.timeout.connect(self._tick)
        self._ticker.start()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(8)

        # 标题行
        header = QHBoxLayout()
        title = SubtitleLabel("服务器状态", self)
        header.addWidget(title)
        header.addStretch()
        # v3.02.01 fix: 主题感知的次要文字色（之前 #888 写死，浅色主题下看不见）
        sub_color = "#888" if isDarkTheme() else "#666"
        self._status_badge = BodyLabel("● 未运行", self)
        self._status_badge.setStyleSheet(f"color: {sub_color};")
        header.addWidget(self._status_badge)
        layout.addLayout(header)

        # 信息行（v3.02.01：拆成两行，避免窗口窄时挤压/截断）
        info_row = QHBoxLayout()
        info_row.setSpacing(12)
        self._cpu_label = CaptionLabel("CPU: —%", self)
        self._mem_label = CaptionLabel("内存: —%", self)
        self._disk_label = CaptionLabel("磁盘: —%", self)
        self._rtt_label = CaptionLabel("RTT: —ms", self)
        self._uptime_label = CaptionLabel("运行: —", self)
        info_row.addWidget(self._cpu_label)
        info_row.addWidget(self._mem_label)
        info_row.addWidget(self._disk_label)
        info_row.addWidget(self._rtt_label)
        info_row.addWidget(self._uptime_label)
        info_row.addStretch()
        layout.addLayout(info_row)
        # 第二行：备份 + 目录（次要信息，单独一行不会被挤压）
        sub_row = QHBoxLayout()
        sub_row.setSpacing(12)
        self._backup_label = CaptionLabel("备份: —", self)
        ctx = get_context()
        self._dir_label = CaptionLabel(f"目录: {os.path.basename(ctx.server_dir)}", self)
        # 目录标签太宽时会省略，避免挤压其他控件
        self._dir_label.setMaximumWidth(280)
        self._dir_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        sub_row.addWidget(self._backup_label)
        sub_row.addWidget(self._dir_label)
        sub_row.addStretch()
        layout.addLayout(sub_row)

        # 假死徽章
        self._stale_label = CaptionLabel("", self)
        self._stale_label.setStyleSheet("color: #ff5555; font-weight: bold;")
        self._stale_label.setVisible(False)
        layout.addWidget(self._stale_label)

        # 按钮行
        btn_row = QHBoxLayout()
        self._start_btn = PrimaryPushButton("启动服务器", self, FluentIcon.PLAY)
        self._stop_btn = PushButton("停止", self, FluentIcon.CANCEL)
        self._restart_btn = PushButton("重启", self, FluentIcon.SYNC)
        self._stop_btn.setEnabled(False)
        self._restart_btn.setEnabled(False)
        btn_row.addWidget(self._start_btn)
        btn_row.addWidget(self._stop_btn)
        btn_row.addWidget(self._restart_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _tick(self):
        if self._start_time > 0:
            elapsed = int(time.time() - self._start_time)
            h, rem = divmod(elapsed, 3600)
            m, s = divmod(rem, 60)
            self._uptime_label.setText(f"运行: {h:02d}:{m:02d}:{s:02d}")
            # 假死检测
            if self._last_output_time > 0:
                idle = time.time() - self._last_output_time
                if idle > 60:
                    self._stale_label.setText(f"⚠️ 已 {int(idle)}s 无输出，可能卡死")
                    self._stale_label.setVisible(True)
                else:
                    self._stale_label.setVisible(False)
        else:
            self._uptime_label.setText("运行: —")
            self._stale_label.setVisible(False)

    def mark_output(self):
        """每次有输出时调用，用于假死检测。"""
        self._last_output_time = time.time()

    def update_server_stats(self, snap: SystemStatsSnapshot):
        self._cpu_label.setText(f"CPU: {snap.cpu_percent:.1f}%")
        self._mem_label.setText(f"内存: {snap.mem_percent:.1f}%")
        self._disk_label.setText(f"磁盘: {snap.disk_percent:.1f}%")

    def set_backup_time(self, text: str):
        self._backup_label.setText(f"备份: {text}")

    def set_running_ui(self, running: bool):
        if running:
            self._status_badge.setText("● 运行中")
            self._status_badge.setStyleSheet("color: #4CAF50;")
            self._start_btn.setEnabled(False)
            self._stop_btn.setEnabled(True)
            self._restart_btn.setEnabled(True)
            self._start_time = time.time()
            self._last_output_time = time.time()
        else:
            self._status_badge.setText("● 未运行")
            # v3.02.01 fix: 主题感知次要色
            sub_color = "#888" if isDarkTheme() else "#666"
            self._status_badge.setStyleSheet(f"color: {sub_color};")
            self._start_btn.setEnabled(True)
            self._stop_btn.setEnabled(False)
            self._restart_btn.setEnabled(False)
            self._rtt_label.setText("RTT: —ms")
            self._rtt_label.setStyleSheet("")
            self._start_time = 0.0
            self._last_output_time = 0.0
            self._stale_label.setVisible(False)

    def update_rtt(self, ms: float, color: str):
        self._rtt_label.setText(f"RTT: {ms:.0f}ms")
        self._rtt_label.setStyleSheet(f"color: {color}; font-weight: bold;")


# ---------- 资源卡片（带曲线）----------
class ResourceCard(CardWidget):
    """系统资源：CPU/内存/磁盘 曲线图。"""

    def __init__(self, monitor, parent=None):
        super().__init__(parent)
        self._monitor = monitor
        self._build()
        # 注意：_cpu_curve / _mem_curve / _disk_curve 已在 _build() 内通过 setattr 创建，
        # 千万不要在这里再赋 None，否则 update_stats() 会因 'NoneType' 报错。

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(8)
        header = QHBoxLayout()
        header.addWidget(SubtitleLabel("系统资源（60 秒历史）", self))
        header.addStretch()
        header.addWidget(CaptionLabel("阈值 ≥ 80% 触发告警", self))
        layout.addLayout(header)
        # 三条曲线
        for name, key, color in [("CPU", "cpu", "#0DC5D4"),
                                  ("内存", "mem", "#FFA726"),
                                  ("磁盘", "disk", "#66BB6A")]:
            bar = ProgressBar(self)
            curve = ResourceCurveWidget(label=name, color=color, parent=self)
            row = QHBoxLayout()
            val = CaptionLabel("—%", self)
            val.setMinimumWidth(60)
            val.setStyleSheet("font-weight: bold;")
            row.addWidget(curve, 1)
            row.addWidget(val, 0, Qt.AlignBottom)
            layout.addLayout(row)
            layout.addWidget(bar)
            setattr(self, f"_{key}_val", val)
            setattr(self, f"_{key}_bar", bar)
            setattr(self, f"_{key}_curve", curve)

    def update_stats(self, snap: SystemStatsSnapshot):
        self._set("cpu", snap.cpu_percent)
        self._set("mem", snap.mem_percent)
        self._set("disk", snap.disk_percent)

    def _set(self, key: str, value: float):
        val = getattr(self, f"_{key}_val", None)
        bar = getattr(self, f"_{key}_bar", None)
        curve = getattr(self, f"_{key}_curve", None)
        if val is not None:
            val.setText(f"{value:.1f}%")
        if bar is not None:
            bar.setValue(int(value))
        # 同步历史曲线（健壮性：任意子部件为 None 都直接跳过，不影响其它指标）
        if curve is None or self._monitor is None:
            return
        hist = self._monitor.history.get(key)
        if hist:
            curve.set_data(value, hist)


# ---------- BDS 进程级资源卡 ----------
class BDSProcessCard(CardWidget):
    """BDS 进程级资源：CPU/内存/线程数/打开文件数。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(8)
        layout.addWidget(SubtitleLabel("BDS 进程", self))
        # v3.02.01 fix: 主题感知次要色
        sub_color = "#888" if isDarkTheme() else "#666"
        self._info = BodyLabel("(未运行)", self)
        self._info.setStyleSheet(f"color: {sub_color};")
        layout.addWidget(self._info)
        self._bar = ProgressBar(self)
        self._bar.setVisible(False)
        layout.addWidget(self._bar)

    def update_proc_stats(self, stats: dict):
        sub_color = "#888" if isDarkTheme() else "#666"
        main_color = "#ccc" if isDarkTheme() else "#1a1a1a"
        if not stats:
            self._info.setText("(未运行)")
            self._info.setStyleSheet(f"color: {sub_color};")
            self._bar.setVisible(False)
            return
        cpu = stats.get("cpu", 0)
        mem = stats.get("mem_mb", 0)
        threads = stats.get("threads", 0)
        ofiles = stats.get("open_files", -1)
        ofiles_text = f"· 打开文件: {ofiles}" if ofiles >= 0 else ""
        self._info.setText(
            f"CPU: <b>{cpu:.1f}%</b>  ·  内存: <b>{mem:.1f} MB</b>  ·  线程: <b>{threads}</b>  {ofiles_text}"
        )
        # v3.02.01 fix: 主题感知主色
        self._info.setStyleSheet(f"color: {main_color};")
        self._bar.setVisible(True)
        self._bar.setValue(min(int(cpu), 100))


# ---------- 快捷操作 ----------
class QuickActionsCard(CardWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(8)
        layout.addWidget(SubtitleLabel("快捷操作", self))

        # 运维
        layout.addWidget(CaptionLabel("运维", self))
        row1 = QHBoxLayout()
        btn_backup = PushButton("手动备份", self, FluentIcon.SAVE)
        btn_console = PushButton("打开控制台", self, FluentIcon.COMMAND_PROMPT)
        row1.addWidget(btn_backup)
        row1.addWidget(btn_console)
        row1.addStretch()
        layout.addLayout(row1)

        # 管理
        layout.addWidget(CaptionLabel("管理", self))
        row2 = QHBoxLayout()
        btn_props = PushButton("服务器属性", self, FluentIcon.EDIT)
        btn_packs = PushButton("资源包", self, FluentIcon.FOLDER)
        row2.addWidget(btn_props)
        row2.addWidget(btn_packs)
        row2.addStretch()
        layout.addLayout(row2)

        # 升级
        layout.addWidget(CaptionLabel("升级", self))
        row3 = QHBoxLayout()
        btn_update = PushButton("检查更新", self, FluentIcon.SYNC)
        btn_tunnel = PushButton("隧道", self, FluentIcon.LINK)
        row3.addWidget(btn_update)
        row3.addWidget(btn_tunnel)
        row3.addStretch()
        layout.addLayout(row3)

        # v3.02.01 fix: navigationInterface.setCurrentItem 只亮导航不切页面，
        # 改用 switchTo(page) — 同时更新导航高亮和 stackedWidget
        def _nav(page_key):
            win = self.window()
            page = getattr(win, f"{page_key}_page", None)
            if page is not None:
                win.switchTo(page)

        btn_backup.clicked.connect(lambda: _nav("world"))
        btn_console.clicked.connect(lambda: _nav("console"))
        btn_props.clicked.connect(lambda: _nav("config"))
        btn_packs.clicked.connect(lambda: _nav("packs"))
        btn_update.clicked.connect(lambda: _nav("upgrade"))
        btn_tunnel.clicked.connect(lambda: _nav("tunnel"))


# ---------- 后台任务卡 ----------
class BackgroundTasksCard(CardWidget):
    """显示正在运行的 Worker 线程。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()
        self._tasks: dict[int, dict] = {}
        self._ticker = QTimer(self)
        self._ticker.setInterval(1000)
        self._ticker.timeout.connect(self._tick)
        self._ticker.start()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(4)
        header = QHBoxLayout()
        header.addWidget(SubtitleLabel("后台任务", self))
        header.addStretch()
        # v3.02.01 fix: 主题感知次要色
        sub_color = "#888" if isDarkTheme() else "#666"
        self._count_label = CaptionLabel("0 个运行中", self)
        self._count_label.setStyleSheet(f"color: {sub_color};")
        header.addWidget(self._count_label)
        layout.addLayout(header)
        self._list_label = BodyLabel("(无)", self)
        self._list_label.setStyleSheet(f"color: {sub_color};")
        self._list_label.setWordWrap(True)
        layout.addWidget(self._list_label)

    def add_task(self, name: str):
        self._tasks[id(self) + len(self._tasks)] = {
            "name": name,
            "started_at": time.time(),
        }
        self._refresh()

    def remove_all_with(self, predicate):
        to_del = [k for k, v in self._tasks.items() if predicate(v)]
        for k in to_del:
            del self._tasks[k]
        self._refresh()

    def _tick(self):
        self._refresh()

    def _refresh(self):
        self._count_label.setText(f"{len(self._tasks)} 个运行中")
        # v3.02.01 fix: 主题感知次要色 / 主色
        sub_color = "#888" if isDarkTheme() else "#666"
        main_color = "#ccc" if isDarkTheme() else "#1a1a1a"
        if not self._tasks:
            self._list_label.setText("(无)")
            self._list_label.setStyleSheet(f"color: {sub_color};")
        else:
            lines = []
            for v in self._tasks.values():
                elapsed = int(time.time() - v["started_at"])
                lines.append(f"⏳ {v['name']}（{elapsed}s）")
            self._list_label.setText("\n".join(lines))
            self._list_label.setStyleSheet(f"color: {main_color};")


# ---------- 仪表盘页面 ----------
class DashboardPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._monitor = None  # 由 main.py 注入
        inner, layout = wrap_scrollable(self)

        self.status_card = StatusCard(inner)
        layout.addWidget(self.status_card)

        # 资源卡（需要 monitor 实例，由 main.py 注入）
        self.resource_card = ResourceCard(self._monitor or _DummyMonitor(), inner)
        layout.addWidget(self.resource_card)

        # BDS 进程卡
        self.bds_card = BDSProcessCard(inner)
        layout.addWidget(self.bds_card)

        # 后台任务
        self.tasks_card = BackgroundTasksCard(inner)
        layout.addWidget(self.tasks_card)

        # 快捷操作
        self.quick_card = QuickActionsCard(inner)
        layout.addWidget(self.quick_card)

        layout.addStretch()

        # 连接按钮
        self.status_card._start_btn.clicked.connect(self._on_start)
        self.status_card._stop_btn.clicked.connect(self._on_stop)
        self.status_card._restart_btn.clicked.connect(self._on_restart)

    def set_monitor(self, monitor):
        """由 main.py 调用，注入真实的 monitor 实例后重建资源卡曲线。"""
        self._monitor = monitor
        # 资源卡需要 monitor.history dict 才能绘制曲线
        # 简单做法：把 monitor.history 引用替换 resource_card 内部的
        self.resource_card._monitor = monitor

    def set_backup_time(self, text: str):
        self.status_card.set_backup_time(text)

    def update_proc_stats(self, stats: dict):
        self.bds_card.update_proc_stats(stats)

    def on_output(self):
        """主窗口在收到服务器输出时调用，用于假死检测。"""
        self.status_card.mark_output()

    def refresh_theme(self):
        """v3.02.01：主题切换后调用，重新设 status_badge/bds_card/tasks_card 的文字色，
        并强制重绘资源曲线（paintEvent 中读 isDarkTheme()）。"""
        sub_color = "#888" if isDarkTheme() else "#666"
        main_color = "#ccc" if isDarkTheme() else "#1a1a1a"
        # status_badge：恢复"未运行"颜色（如果当前不是运行中）
        if not self._server_running_cached():
            self.status_card._status_badge.setStyleSheet(f"color: {sub_color};")
        # bds_card / tasks_card：重画
        self.bds_card._info.setStyleSheet(f"color: {sub_color};")
        self.tasks_card._count_label.setStyleSheet(f"color: {sub_color};")
        self.tasks_card._list_label.setStyleSheet(f"color: {sub_color};")
        # resource curve：强制 repaint（paintEvent 会读 isDarkTheme）
        for key in ("cpu", "mem", "disk"):
            curve = getattr(self.resource_card, f"_{key}_curve", None)
            if curve is not None:
                curve.update()

    def _server_running_cached(self) -> bool:
        """简化的运行状态探测（仅用于 refresh_theme 时判断 status_badge 颜色）。"""
        try:
            win = self.window()
            return bool(win and getattr(win, "is_server_running", False))
        except Exception:
            return False

    # ---------- v3.02.01 fix: 与 ConsolePage 对齐的服务器状态回调 ----------
    # main.py 启动/停止服务器时会调用这些方法（dashboard_page._on_server_started 等），
    # 但 dashboard.py 之前没有实现 → 启动服务器直接崩 'object has no attribute'。
    # 这里转发到 status_card.set_running_ui()（已存在的核心逻辑）
    def _on_server_started(self):
        """服务器启动时由 main.start_server() 调用。"""
        self.status_card.set_running_ui(True)
        self.status_card.mark_output()

    def _on_server_stopped(self):
        """服务器停止时由 main._on_server_stopped() 调用。"""
        self.status_card.set_running_ui(False)

    def _on_status_changed(self, running: bool):
        """ServerProcess.status_changed 信号回调（与 console.py 接口一致）。"""
        self.status_card.set_running_ui(running)

    def _on_start(self):
        win = self.window()
        err = win.start_server()
        if err:
            toast_error("启动失败", err, win)

    def _on_stop(self):
        self.window().stop_server()

    def _on_restart(self):
        win = self.window()
        win.stop_server()
        # 延迟 3 秒后启动
        QTimer.singleShot(3000, lambda: self._on_start() if not win.is_server_running else None)


class _DummyMonitor:
    """资源卡构造时若 monitor 还没注入，先用这个占位。"""
    history = {}
