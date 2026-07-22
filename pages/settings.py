# -*- coding: utf-8 -*-
"""
设置页面 —— 主题、主色调、服务器路径、备份、通知、Webhook、GitHub 等。
"""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFileDialog
from PySide6.QtGui import QColor
from qfluentwidgets import (
    CardWidget, SubtitleLabel, StrongBodyLabel, BodyLabel,
    PrimaryPushButton, PushButton, LineEdit, ComboBox,
    FluentIcon, ToggleButton, Slider, SpinBox, ColorDialog,
    setTheme, setThemeColor, Theme,
)

from shared.config import config_mgr, SCRIPT_DIR
from shared.toast import toast_success
from pages.dashboard import wrap_scrollable


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
        h.setStyleSheet("color: #888; font-size: 12px;")
        h.setMaximumWidth(160)
        row.addWidget(h)
    return row


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

        self._theme_combo = ComboBox(theme_card)
        self._theme_combo.addItems(["Dark", "Light", "Auto"])
        current = config_mgr.get("theme", "dark")
        self._theme_combo.setCurrentText({"dark":"Dark","light":"Light","auto":"Auto"}.get(current, "Dark"))
        self._theme_combo.currentTextChanged.connect(self._on_theme_changed)
        tc.addLayout(_row("主题模式", self._theme_combo, theme_card))

        cb = QHBoxLayout()
        self._color_btn = PrimaryPushButton("选择主色调", theme_card)
        self._color_btn.clicked.connect(self._on_pick_color)
        self._color_preview = BodyLabel("", theme_card)
        self._update_color_preview(config_mgr.get("theme_color", "#0DC5D4"))
        cb.addWidget(self._color_btn)
        cb.addWidget(self._color_preview); cb.addStretch()
        tc.addLayout(cb)
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
        bl.addLayout(_row("保留备份数", self._backup_keep, backup))

        self._online_backup = ToggleButton("在线备份", backup)
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

        # Toast 透明度
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

        # ═══ Webhook ═══
        wh = CardWidget(inner)
        wl = QVBoxLayout(wh)
        wl.setContentsMargins(16, 12, 16, 16); wl.setSpacing(8)
        wl.addWidget(SubtitleLabel("Webhook 通知", wh))

        self._webhook_url = LineEdit(wh)
        self._webhook_url.setText(config_mgr.get("webhook_url", ""))
        self._webhook_url.setPlaceholderText("https://hooks.example.com/...")
        wl.addLayout(_row("Webhook URL", self._webhook_url, wh))

        self._webhook_backup = ToggleButton("备份通知", wh)
        self._webhook_backup.setChecked("backup" in config_mgr.get("webhook_events", []))
        self._webhook_crash = ToggleButton("崩溃通知", wh)
        self._webhook_crash.setChecked("crash" in config_mgr.get("webhook_events", []))
        self._webhook_mem = ToggleButton("内存告警", wh)
        self._webhook_mem.setChecked("memory" in config_mgr.get("webhook_events", []))
        wr = QHBoxLayout()
        wr.addWidget(self._webhook_backup); wr.addWidget(self._webhook_crash)
        wr.addWidget(self._webhook_mem); wr.addStretch()
        wl.addLayout(wr)
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
        gl.addLayout(_row("Token", self._gh_token, gh))
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

        # ═══ 保存 ═══
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
        dlg = ColorDialog(QColor(config_mgr.get("theme_color", "#0DC5D4")), "选择主色调", self.window())
        if dlg.exec():
            color = dlg.color.name()
            config_mgr.set("theme_color", color)
            self._update_color_preview(color)
            if self._main_window:
                self._main_window.apply_theme(config_mgr.get("theme", "dark"), color)

    def _update_color_preview(self, h: str):
        self._color_preview.setText(f"  {h}")
        self._color_preview.setStyleSheet(f"background:{h}; color:#fff; padding:4px 12px; border-radius:4px; font-weight:bold;")

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择服务器文件夹", SCRIPT_DIR)
        if d:
            self._dir_edit.setText(os.path.relpath(d, SCRIPT_DIR) if d.startswith(SCRIPT_DIR) else d)

    # ── 保存 ──
    def _on_save(self):
        config_mgr.set("theme", {"Dark":"dark","Light":"light","Auto":"auto"}.get(self._theme_combo.currentText(), "dark"))
        config_mgr.set("server_dir", self._dir_edit.text())
        config_mgr.set("server_exe", self._exe_edit.text())
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
        config_mgr.set("webhook_url", self._webhook_url.text())
        events = []
        if self._webhook_backup.isChecked(): events.append("backup")
        if self._webhook_crash.isChecked(): events.append("crash")
        if self._webhook_mem.isChecked(): events.append("memory")
        config_mgr.set("webhook_events", events)
        config_mgr.set("github_auth_enabled", self._gh_auth.isChecked())
        config_mgr.set("github_token", self._gh_token.text())
        config_mgr.set("auto_check_update", self._auto_update.isChecked())
        config_mgr.set("multi_dl_enabled", self._multi_dl.isChecked())
        config_mgr.set("mem_warn_threshold", self._mem_warn.value())
        config_mgr.set("close_to_tray", self._close_tray.isChecked())
        config_mgr.set("max_restart_retries", self._crash_restart.value())
        config_mgr.save()
        toast_success("保存成功", "设置已保存", self.window())
