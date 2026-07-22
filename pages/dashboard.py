# -*- coding: utf-8 -*-
"""
仪表盘页面 —— 服务器概览 + 系统资源监控 + 快捷操作。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame,
    QLabel,
)
from qfluentwidgets import (
    CardWidget, SubtitleLabel, StrongBodyLabel, BodyLabel,
    CaptionLabel, PrimaryPushButton, PushButton,
    FluentIcon, InfoBar, InfoBarPosition, ProgressBar,
)

from backend.monitor import SystemStatsSnapshot
from shared.config import config_mgr, get_context
from shared.toast import toast_error, toast_success


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


# ---------- 状态卡片 ----------
class StatusCard(CardWidget):
    """服务器状态：运行状态 / 版本 / 系统信息 / 启停按钮。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(8)

        # 标题行
        header = QHBoxLayout()
        title = SubtitleLabel("服务器状态", self)
        header.addWidget(title)
        header.addStretch()
        self._status_badge = BodyLabel("● 未运行", self)
        self._status_badge.setStyleSheet("color: #888;")
        header.addWidget(self._status_badge)
        layout.addLayout(header)

        # 信息行
        info_row = QHBoxLayout()
        info_row.setSpacing(16)
        self._cpu_label = CaptionLabel("CPU: —%", self)
        self._mem_label = CaptionLabel("内存: —%", self)
        self._disk_label = CaptionLabel("磁盘: —%", self)
        self._rtt_label = CaptionLabel("RTT: —ms", self)
        info_row.addWidget(self._cpu_label)
        info_row.addWidget(self._mem_label)
        info_row.addWidget(self._disk_label)
        info_row.addWidget(self._rtt_label)
        info_row.addStretch()
        ctx = get_context()
        info_row.addWidget(CaptionLabel(f"目录: {ctx.server_dir}", self))
        layout.addLayout(info_row)

        # 按钮行
        btn_row = QHBoxLayout()
        self._start_btn = PrimaryPushButton("启动服务器", self, FluentIcon.PLAY)
        self._stop_btn = PushButton("停止", self, FluentIcon.CANCEL)
        self._stop_btn.setEnabled(False)
        btn_row.addWidget(self._start_btn)
        btn_row.addWidget(self._stop_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    # --- 公开方法（由主窗口调用）---
    def update_server_stats(self, snap: SystemStatsSnapshot):
        self._cpu_label.setText(f"CPU: {snap.cpu_percent:.1f}%")
        self._mem_label.setText(f"内存: {snap.mem_percent:.1f}%")
        self._disk_label.setText(f"磁盘: {snap.disk_percent:.1f}%")

    def set_running_ui(self, running: bool):
        if running:
            self._status_badge.setText("● 运行中")
            self._status_badge.setStyleSheet("color: #4CAF50;")
            self._start_btn.setEnabled(False)
            self._stop_btn.setEnabled(True)
        else:
            self._status_badge.setText("● 未运行")
            self._status_badge.setStyleSheet("color: #888;")
            self._start_btn.setEnabled(True)
            self._stop_btn.setEnabled(False)
            self._rtt_label.setText("RTT: —ms")
            self._rtt_label.setStyleSheet("")

    def update_rtt(self, ms: float, color: str):
        self._rtt_label.setText(f"RTT: {ms:.0f}ms")
        self._rtt_label.setStyleSheet(f"color: {color}; font-weight: bold;")


# ---------- 资源卡片 ----------
class ResourceCard(CardWidget):
    """系统资源：CPU / 内存 / 磁盘 进度条。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(8)
        layout.addWidget(SubtitleLabel("系统资源", self))

        for name, key in [("CPU 使用率", "cpu"), ("内存使用率", "mem"), ("磁盘使用率", "disk")]:
            row = QHBoxLayout()
            row.addWidget(BodyLabel(name, self))
            row.addStretch()
            val = CaptionLabel("—%", self)
            setattr(self, f"_{key}_val", val)
            row.addWidget(val)
            layout.addLayout(row)
            bar = ProgressBar(self)
            setattr(self, f"_{key}_bar", bar)
            layout.addWidget(bar)

    def update_stats(self, snap: SystemStatsSnapshot):
        self._set("cpu", snap.cpu_percent)
        self._set("mem", snap.mem_percent)
        self._set("disk", snap.disk_percent)

    def _set(self, key: str, value: float):
        getattr(self, f"_{key}_val").setText(f"{value:.1f}%")
        getattr(self, f"_{key}_bar").setValue(int(value))


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

        row1 = QHBoxLayout()
        btn_backup = PushButton("手动备份", self, FluentIcon.SAVE)
        btn_props = PushButton("服务器属性", self, FluentIcon.EDIT)
        row1.addWidget(btn_backup)
        row1.addWidget(btn_props)
        row1.addStretch()
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        btn_console = PushButton("打开控制台", self, FluentIcon.COMMAND_PROMPT)
        btn_update = PushButton("检查更新", self, FluentIcon.SYNC)
        row2.addWidget(btn_console)
        row2.addWidget(btn_update)
        row2.addStretch()
        layout.addLayout(row2)

        # 按钮回调——导航到对应页面
        def _nav(page_key):
            win = self.window()
            if hasattr(win, "navigationInterface"):
                win.navigationInterface.setCurrentItem(page_key)

        btn_backup.clicked.connect(lambda: _nav("world"))
        btn_console.clicked.connect(lambda: _nav("console"))
        btn_props.clicked.connect(lambda: _nav("config"))
        btn_update.clicked.connect(lambda: _nav("upgrade"))


# ---------- 仪表盘页面 ----------
class DashboardPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        inner, layout = wrap_scrollable(self)

        self.status_card = StatusCard(inner)
        layout.addWidget(self.status_card)

        self.resource_card = ResourceCard(inner)
        layout.addWidget(self.resource_card)

        self.quick_card = QuickActionsCard(inner)
        layout.addWidget(self.quick_card)

        layout.addStretch()

        # 连接按钮（通过主窗口操作服务器）
        main_win = self.window()
        self.status_card._start_btn.clicked.connect(self._on_start)
        self.status_card._stop_btn.clicked.connect(self._on_stop)

    # ----- 按钮回调（委托给主窗口）-----
    def _on_start(self):
        win = self.window()
        err = win.start_server()
        if err:
            toast_error("启动失败", err, win)

    def _on_stop(self):
        self.window().stop_server()

    # ----- 被主窗口调用的状态更新 -----
    def _on_server_started(self):
        self.status_card.set_running_ui(True)

    def _on_server_stopped(self):
        self.status_card.set_running_ui(False)

    def _on_status_changed(self, running: bool):
        self.status_card.set_running_ui(running)
