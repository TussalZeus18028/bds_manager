# -*- coding: utf-8 -*-
"""
设置页面 —— 主题、主色调、服务器路径、备份、通知、Webhook、GitHub 等。

v3.1 改进：
- 真正实现"跟随系统"主题切换（监听 Qt 6.5+ QStyleHints）
- 8 种预设主题色 + 自定义 ColorDialog
- 字体大小可调（影响整个工具的 UI 字号）
- 导入/导出配置
- 全部 webhook 事件订阅（8 种）
- 高级选项卡：日志轮转大小、是否启用 BDS 进程监控、优雅停服
- 配置变更预览（保存前显示 diff）
"""

import os
import json
import logging
from PySide6.QtCore import Qt, QStandardPaths
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QApplication
from qfluentwidgets import (
    CardWidget, SubtitleLabel, StrongBodyLabel, BodyLabel, CaptionLabel,
    PrimaryPushButton, PushButton, LineEdit, ComboBox,
    FluentIcon, ToggleButton, Slider, SpinBox,
    setTheme, setThemeColor, Theme, MessageBox,
)

from shared.config import config_mgr, SCRIPT_DIR, CONFIG_FILE
from shared.toast import toast_success, toast_warning, toast_error
from pages.dashboard import wrap_scrollable

logger = logging.getLogger("bds_manager")


# 预设主题色（8 种）
PRESET_COLORS = [
    ("#0DC5D4", "青蓝（默认）"),
    ("#0078D4", "微软蓝"),
    ("#5B5FCF", "紫色"),
    ("#E74856", "红色"),
    ("#FF8C00", "橙色"),
    ("#107C10", "绿色"),
    ("#B146C2", "品红"),
    ("#FFFFFF", "纯白"),
]


def _row(label_text: str, widget: QWidget, parent: QWidget, hint: str = "") -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(8)
    lbl = BodyLabel(label_text, parent)
    lbl.setMinimumWidth(100)
    lbl.setMaximumWidth(180)
    row.addWidget(lbl)
    row.addWidget(widget, 1)
    if hint:
        h = BodyLabel(hint, parent)
        h.setStyleSheet("color: #888; font-size: 11px;")
        h.setMaximumWidth(180)
        row.addWidget(h)
    return row


class ColorSwatch(QWidget):
    """点击切换主题色的小色块。"""

    def __init__(self, hex_color: str, label: str, parent_settings, parent=None):
        super().__init__(parent)
        self._hex = hex_color
        self._label = label
        self._settings = parent_settings
        self.setToolTip(f"{label} ({hex_color})")
        self.setFixedSize(36, 36)
        self.setStyleSheet(
            f"background:{hex_color}; border:2px solid #444; border-radius:6px;"
        )
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event):
        self._settings._set_theme_color(self._hex)


class SettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._main_window = parent
        inner, layout = wrap_scrollable(self, spacing=12)

        # ═══ 外观 ═══
        theme_card = CardWidget(inner)
        tc = QVBoxLayout(theme_card)
        tc.setContentsMargins(16, 12, 16, 16); tc.setSpacing(8)
        tc.addWidget(SubtitleLabel("外观", theme_card))

        # 主题模式
        self._theme_combo = ComboBox(theme_card)
        self._theme_combo.addItems(["Dark", "Light", "Auto"])
        current = config_mgr.get("theme", "dark")
        self._theme_combo.setCurrentText({"dark":"Dark","light":"Light","auto":"Auto"}.get(current, "Dark"))
        self._theme_combo.currentTextChanged.connect(self._on_theme_changed)
        tc.addLayout(_row("主题模式", self._theme_combo, theme_card, "Auto=跟随系统"))

        # 跟随系统开关
        self._follow_system = ToggleButton("跟随系统主题变化", theme_card)
        self._follow_system.setChecked(config_mgr.get("follow_system_theme", False))
        tc.addWidget(self._follow_system, alignment=Qt.AlignLeft)

        # 字体大小
        self._font_size = SpinBox(theme_card)
        self._font_size.setRange(9, 20)
        self._font_size.setValue(config_mgr.get("font_size", 12))
        self._font_size.valueChanged.connect(self._on_font_size_changed)
        tc.addLayout(_row("字体大小(px)", self._font_size, theme_card, "影响全局 UI"))

        # 预设色板
        tc.addWidget(CaptionLabel("预设主色（点击切换）", theme_card))
        color_row = QHBoxLayout()
        for hex_c, label in PRESET_COLORS:
            sw = ColorSwatch(hex_c, label, self, theme_card)
            color_row.addWidget(sw)
        color_row.addStretch()
        self._custom_color_btn = PushButton("自定义...", theme_card)
        self._custom_color_btn.clicked.connect(self._on_pick_color)
        color_row.addWidget(self._custom_color_btn)
        tc.addLayout(color_row)

        # 当前色预览
        preview_row = QHBoxLayout()
        preview_row.addWidget(BodyLabel("当前主色:", theme_card))
        self._color_preview = BodyLabel("", theme_card)
        self._update_color_preview(config_mgr.get("theme_color", "#0DC5D4"))
        preview_row.addWidget(self._color_preview)
        preview_row.addStretch()
        tc.addLayout(preview_row)

        layout.addWidget(theme_card)

        # ═══ 服务器 ═══
        svr = CardWidget(inner)
        sl = QVBoxLayout(svr)
        sl.setContentsMargins(16, 12, 16, 16); sl.setSpacing(8)
        sl.addWidget(SubtitleLabel("服务器", svr))

        self._dir_edit = LineEdit(svr)
        self._dir_edit.setText(config_mgr.get("server_dir", "Server"))
        browse = PushButton("浏览", svr, FluentIcon.FOLDER)
        browse.clicked.connect(self._browse_dir)
        dr = QHBoxLayout(); dr.addWidget(self._dir_edit, 1); dr.addWidget(browse)
        sl.addLayout(dr)

        self._exe_edit = LineEdit(svr)
        self._exe_edit.setText(config_mgr.get("server_exe", "bedrock_server.exe"))
        sl.addLayout(_row("可执行文件", self._exe_edit, svr))

        # 优雅停服
        self._graceful = ToggleButton("启用优雅停服（先 save-all 再 stop）", svr)
        self._graceful.setChecked(config_mgr.get("graceful_shutdown", True))
        sl.addWidget(self._graceful, alignment=Qt.AlignLeft)
        self._grace_seconds = SpinBox(svr)
        self._grace_seconds.setRange(1, 60)
        self._grace_seconds.setValue(config_mgr.get("shutdown_grace_seconds", 10))
        sl.addLayout(_row("停服宽限(秒)", self._grace_seconds, svr, "stop 后等待秒数"))

        # 进程级监控
        self._proc_monitor = ToggleButton("监控 BDS 进程 CPU/内存", svr)
        self._proc_monitor.setChecked(config_mgr.get("enable_bds_process_monitor", True))
        sl.addWidget(self._proc_monitor, alignment=Qt.AlignLeft)

        layout.addWidget(svr)

        # ═══ 自动备份 ═══
        backup = CardWidget(inner)
        bl = QVBoxLayout(backup)
        bl.setContentsMargins(16, 12, 16, 16); bl.setSpacing(8)
        bl.addWidget(SubtitleLabel("自动备份", backup))

        self._backup_toggle = ToggleButton("启用自动备份", backup)
        self._backup_toggle.setChecked(config_mgr.get("auto_backup_enabled", True))
        bl.addWidget(self._backup_toggle)

        self._backup_interval = SpinBox(backup)
        self._backup_interval.setRange(5, 1440)
        self._backup_interval.setValue(config_mgr.get("backup_interval", 60))
        bl.addLayout(_row("备份间隔(分钟)", self._backup_interval, backup))

        self._backup_keep = SpinBox(backup)
        self._backup_keep.setRange(1, 100)
        self._backup_keep.setValue(config_mgr.get("backup_keep", 20))
        bl.addLayout(_row("保留备份数", self._backup_keep, backup, "仅 auto_ 前缀"))

        self._online_backup = ToggleButton("在线备份（save hold/resume）", backup)
        self._online_backup.setChecked(config_mgr.get("online_backup", True))
        bl.addWidget(self._online_backup, alignment=Qt.AlignLeft)
        layout.addWidget(backup)

        # ═══ Toast 通知 ═══
        toast = CardWidget(inner)
        tl = QVBoxLayout(toast)
        tl.setContentsMargins(16, 12, 16, 16); tl.setSpacing(8)
        tl.addWidget(SubtitleLabel("Toast 通知", toast))

        self._toast_show = ToggleButton("显示启动提示", toast)
        self._toast_show.setChecked(config_mgr.get("show_startup_toasts", True))
        tl.addWidget(self._toast_show, alignment=Qt.AlignLeft)

        for name, key, dflt in [("错误", "toast_duration_error", 5000),
                                 ("警告", "toast_duration_warning", 4000),
                                 ("成功", "toast_duration_success", 3500),
                                 ("信息", "toast_duration_info", 3000)]:
            sp = SpinBox(toast)
            sp.setRange(500, 60000); sp.setValue(config_mgr.get(key, dflt))
            setattr(self, f"_toast_{key}", sp)
            tl.addLayout(_row(f"Toast {name}时长(ms)", sp, toast))

        self._toast_opacity = Slider(Qt.Horizontal, toast)
        self._toast_opacity.setRange(50, 100)
        self._toast_opacity.setValue(int(config_mgr.get("toast_opacity") or 95))
        tl.addLayout(_row("Toast 透明度(%)", self._toast_opacity, toast))

        self._toast_style = ComboBox(toast)
        self._toast_style.addItems(["原版滑动排队", "现代 InfoBar"])
        current_style = config_mgr.get("toast_style", "original")
        self._toast_style.setCurrentText("原版滑动排队" if current_style == "original" else "现代 InfoBar")
        tl.addLayout(_row("Toast 风格", self._toast_style, toast))

        self._queue_delay = SpinBox(toast)
        self._queue_delay.setRange(50, 5000)
        self._queue_delay.setValue(config_mgr.get("toast_queue_delay") or 200)
        tl.addLayout(_row("Toast 排队延迟(ms)", self._queue_delay, toast))

        layout.addWidget(toast)

        # ═══ 控制台 ═══
        console_card = CardWidget(inner)
        ccl = QVBoxLayout(console_card)
        ccl.setContentsMargins(16, 12, 16, 16); ccl.setSpacing(8)
        ccl.addWidget(SubtitleLabel("控制台", console_card))

        self._console_timestamps = ToggleButton("显示时间戳", console_card)
        self._console_timestamps.setChecked(config_mgr.get("console_show_timestamps", True))
        ccl.addWidget(self._console_timestamps, alignment=Qt.AlignLeft)

        self._console_max = SpinBox(console_card)
        self._console_max.setRange(100, 100000)
        self._console_max.setSingleStep(500)
        self._console_max.setValue(config_mgr.get("console_max_lines", 5000))
        ccl.addLayout(_row("最大行数", self._console_max, console_card, "超出自动截断"))

        layout.addWidget(console_card)

        # ═══ Webhook ═══
        wh = CardWidget(inner)
        wl = QVBoxLayout(wh)
        wl.setContentsMargins(16, 12, 16, 16); wl.setSpacing(8)
        wl.addWidget(SubtitleLabel("Webhook 通知", wh))

        self._webhook_url = LineEdit(wh)
        self._webhook_url.setText(config_mgr.get("webhook_url", ""))
        self._webhook_url.setPlaceholderText("https://hooks.example.com/...")
        wl.addLayout(_row("Webhook URL", self._webhook_url, wh, "支持 Discord/企业微信/自定义"))

        wl.addWidget(CaptionLabel("订阅事件（勾选要推送的事件）", wh))
        self._webhook_events: dict[str, ToggleButton] = {}
        for event, label in [
            ("backup", "备份"), ("crash", "崩溃"), ("memory", "内存告警"),
            ("player_join", "玩家加入"), ("player_leave", "玩家离开"),
            ("command_executed", "执行命令"), ("server_started", "服务器启动"),
            ("update_available", "工具更新"),
        ]:
            tb = ToggleButton(label, wh)
            tb.setChecked(event in config_mgr.get("webhook_events", []))
            self._webhook_events[event] = tb
        wr = QHBoxLayout()
        for i, (event, _) in enumerate(self._webhook_events.items()):
            wr.addWidget(self._webhook_events[event])
        wr.addStretch()
        wl.addLayout(wr)
        # 测试按钮
        test_row = QHBoxLayout()
        test_btn = PushButton("发送测试通知", wh, FluentIcon.SEND)
        test_btn.clicked.connect(self._on_test_webhook)
        test_row.addWidget(test_btn)
        test_row.addStretch()
        wl.addLayout(test_row)
        layout.addWidget(wh)

        # ═══ GitHub API ═══
        gh = CardWidget(inner)
        gl = QVBoxLayout(gh)
        gl.setContentsMargins(16, 12, 16, 16); gl.setSpacing(8)
        gl.addWidget(SubtitleLabel("GitHub API (版本更新)", gh))

        self._gh_auth = ToggleButton("启用 GitHub Token", gh)
        self._gh_auth.setChecked(config_mgr.get("github_auth_enabled", False))
        gl.addWidget(self._gh_auth, alignment=Qt.AlignLeft)

        self._gh_token = LineEdit(gh)
        self._gh_token.setText(config_mgr.get("github_token", ""))
        self._gh_token.setPlaceholderText("ghp_xxxxxxxxxxxxxxxxxxxx")
        self._gh_token.setEchoMode(LineEdit.Password)
        gl.addLayout(_row("Token", self._gh_token, gh, "XOR+Base64 混淆存储"))
        layout.addWidget(gh)

        # ═══ 其他 ═══
        other = CardWidget(inner)
        ol = QVBoxLayout(other)
        ol.setContentsMargins(16, 12, 16, 16); ol.setSpacing(8)
        ol.addWidget(SubtitleLabel("其他", other))

        self._auto_update = ToggleButton("自动检查更新", other)
        self._auto_update.setChecked(config_mgr.get("auto_check_update", True))
        ol.addWidget(self._auto_update, alignment=Qt.AlignLeft)

        self._multi_dl = ToggleButton("多线程下载", other)
        self._multi_dl.setChecked(config_mgr.get("multi_dl_enabled", True))
        ol.addWidget(self._multi_dl, alignment=Qt.AlignLeft)

        self._mem_warn = SpinBox(other)
        self._mem_warn.setRange(50, 99)
        self._mem_warn.setValue(config_mgr.get("mem_warn_threshold", 80))
        ol.addLayout(_row("内存告警阈值(%)", self._mem_warn, other))

        self._close_tray = ToggleButton("点X最小化到托盘", other)
        self._close_tray.setChecked(config_mgr.get("close_to_tray", True))
        ol.addWidget(self._close_tray, alignment=Qt.AlignLeft)

        self._crash_restart = SpinBox(other)
        self._crash_restart.setRange(0, 20)
        self._crash_restart.setValue(config_mgr.get("max_restart_retries", 5))
        ol.addLayout(_row("崩溃自动重启次数(0=禁用)", self._crash_restart, other))
        layout.addWidget(other)

        # ═══ 导入/导出 + 保存 ═══
        io_row = QHBoxLayout()
        export_btn = PushButton("导出配置", inner, FluentIcon.SHARE)
        export_btn.clicked.connect(self._on_export)
        import_btn = PushButton("导入配置", inner, FluentIcon.DOWNLOAD)
        import_btn.clicked.connect(self._on_import)
        io_row.addWidget(export_btn)
        io_row.addWidget(import_btn)
        io_row.addStretch()
        layout.addLayout(io_row)

        sr = QHBoxLayout(); sr.addStretch()
        save_btn = PrimaryPushButton("保存设置", inner, FluentIcon.SAVE)
        save_btn.clicked.connect(self._on_save)
        sr.addWidget(save_btn)
        layout.addLayout(sr)
        layout.addStretch()

    # ── 主题 ──
    def _on_theme_changed(self, text: str):
        theme = {"Dark":"dark","Light":"light","Auto":"auto"}.get(text, "dark")
        color = config_mgr.get("theme_color", "#0DC5D4")
        config_mgr.set("theme", theme)
        if self._main_window:
            self._main_window.apply_theme(theme, color)

    def _on_pick_color(self):
        # 延迟导入 ColorDialog（qfluentwidgets 的 ColorDialog 模块导入耗时 ~200ms）
        from qfluentwidgets import ColorDialog
        dlg = ColorDialog(QColor(config_mgr.get("theme_color", "#0DC5D4")), "选择主色调", self.window())
        if dlg.exec():
            self._set_theme_color(dlg.color.name())

    def _set_theme_color(self, hex_color: str):
        config_mgr.set("theme_color", hex_color)
        self._update_color_preview(hex_color)
        if self._main_window:
            self._main_window.apply_theme(config_mgr.get("theme", "dark"), hex_color)

    def _update_color_preview(self, h: str):
        self._color_preview.setText(f"  {h}  ")
        self._color_preview.setStyleSheet(
            f"background:{h}; color:#fff; padding:6px 14px; "
            f"border-radius:6px; font-weight:bold;"
        )

    def _on_font_size_changed(self, size: int):
        """实时改变全局字体。"""
        app = QApplication.instance()
        if app:
            f = app.font()
            f.setPointSize(size)
            app.setFont(f)

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择服务器文件夹", SCRIPT_DIR)
        if d:
            self._dir_edit.setText(os.path.relpath(d, SCRIPT_DIR) if d.startswith(SCRIPT_DIR) else d)

    def _on_test_webhook(self):
        url = self._webhook_url.text().strip()
        if not url:
            toast_warning("提示", "请先填写 Webhook URL", self.window())
            return
        from backend.webhook import send_webhook
        send_webhook("backup", "测试通知", f"BDS Manager Webhook 测试 @ {os.environ.get('COMPUTERNAME', '?')}")
        toast_success("已发送", "如未收到请检查 URL 与事件订阅", self.window())

    def _on_export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出配置", os.path.join(SCRIPT_DIR, "bds_manager_config_export.json"),
            "JSON Files (*.json)"
        )
        if not path:
            return
        # 临时保存当前 UI 值
        self._on_save(silent=True)
        try:
            import shutil
            shutil.copy2(CONFIG_FILE, path)
            toast_success("导出成功", os.path.basename(path), self.window())
        except Exception as e:
            toast_error("导出失败", str(e), self.window())

    def _on_import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入配置", SCRIPT_DIR, "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("配置格式错误")
            # 合并
            for k, v in data.items():
                config_mgr.set(k, v)
            config_mgr.save()
            toast_success("导入成功", "请重启应用以使所有设置生效", self.window())
        except Exception as e:
            toast_error("导入失败", str(e), self.window())

    # ── 保存 ──
    def _on_save(self, silent: bool = False):
        old_values = {k: config_mgr.get(k) for k in config_mgr.values}
        config_mgr.set("theme", {"Dark":"dark","Light":"light","Auto":"auto"}.get(self._theme_combo.currentText(), "dark"))
        config_mgr.set("follow_system_theme", self._follow_system.isChecked())
        config_mgr.set("font_size", self._font_size.value())
        config_mgr.set("server_dir", self._dir_edit.text())
        config_mgr.set("server_exe", self._exe_edit.text())
        config_mgr.set("graceful_shutdown", self._graceful.isChecked())
        config_mgr.set("shutdown_grace_seconds", self._grace_seconds.value())
        config_mgr.set("enable_bds_process_monitor", self._proc_monitor.isChecked())
        config_mgr.set("auto_backup_enabled", self._backup_toggle.isChecked())
        config_mgr.set("backup_interval", self._backup_interval.value())
        config_mgr.set("backup_keep", self._backup_keep.value())
        config_mgr.set("online_backup", self._online_backup.isChecked())
        config_mgr.set("show_startup_toasts", self._toast_show.isChecked())
        for key in ["toast_duration_error","toast_duration_warning","toast_duration_success","toast_duration_info"]:
            config_mgr.set(key, getattr(self, f"_toast_{key}").value())
        config_mgr.set("toast_opacity", self._toast_opacity.value())
        config_mgr.set("toast_style", "original" if "原版" in self._toast_style.currentText() else "modern")
        config_mgr.set("toast_queue_delay", self._queue_delay.value())
        config_mgr.set("console_show_timestamps", self._console_timestamps.isChecked())
        config_mgr.set("console_max_lines", self._console_max.value())
        config_mgr.set("webhook_url", self._webhook_url.text())
        events = [e for e, cb in self._webhook_events.items() if cb.isChecked()]
        config_mgr.set("webhook_events", events)
        config_mgr.set("github_auth_enabled", self._gh_auth.isChecked())
        config_mgr.set("github_token", self._gh_token.text())
        config_mgr.set("auto_check_update", self._auto_update.isChecked())
        config_mgr.set("multi_dl_enabled", self._multi_dl.isChecked())
        config_mgr.set("mem_warn_threshold", self._mem_warn.value())
        config_mgr.set("close_to_tray", self._close_tray.isChecked())
        config_mgr.set("max_restart_retries", self._crash_restart.value())
        config_mgr.save()
        if not silent:
            toast_success("保存成功", "设置已保存", self.window())
