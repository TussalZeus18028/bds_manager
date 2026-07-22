# -*- coding: utf-8 -*-
"""
内网穿透页面 —— ChmlFrp / frpc 隧道管理。
"""

import os, subprocess

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QFileDialog,
)
from PySide6.QtGui import QTextCursor
from qfluentwidgets import (
    CardWidget, SubtitleLabel, StrongBodyLabel, BodyLabel, CaptionLabel,
    PrimaryPushButton, PushButton, LineEdit, FluentIcon, ToggleButton,
)

from shared.config import config_mgr
from shared.toast import toast_success, toast_error, toast_warning
from pages.dashboard import wrap_scrollable

import html as _hmod


def _esc(text: str) -> str:
    return _hmod.escape(text)


# ── frpc 输出读取 Worker（QThread，不卡 UI）──
class FrpcReader(QThread):
    line_received = Signal(str, str)  # (text, color)

    def __init__(self, process: subprocess.Popen, parent=None):
        super().__init__(parent)
        self._proc = process
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        for line in self._proc.stdout:
            if self._stop:
                break
            text = line.rstrip()
            c = "#ccc"
            ls = text.lower()
            if "error" in ls:
                c = "#ff5555"
            elif "warn" in ls:
                c = "#ffaa00"
            elif "success" in ls or "start proxy" in ls or "login" in ls:
                c = "#4CAF50"
            elif "new connection" in ls:
                c = "#64b5f6"
            self.line_received.emit(text, c)


class TunnelPage(QWidget):
    """frpc 内网穿透管理。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process: subprocess.Popen | None = None
        self._reader: FrpcReader | None = None
        self._running = False
        self._auto_scroll = True

        inner, layout = wrap_scrollable(self, spacing=12)

        # ── 路径设置 ──
        path_card = CardWidget(inner)
        pl = QVBoxLayout(path_card)
        pl.setContentsMargins(16, 12, 16, 16)
        pl.setSpacing(8)
        pl.addWidget(SubtitleLabel("frpc 设置", path_card))

        dir_row = QHBoxLayout()
        frpc_path = config_mgr.get("frpc_path", "")
        self._path_edit = LineEdit(path_card)
        self._path_edit.setText(frpc_path)
        self._path_edit.setPlaceholderText("frpc.exe 完整路径")
        browse_btn = PushButton("浏览", path_card, FluentIcon.FOLDER)
        browse_btn.clicked.connect(self._browse)
        dir_row.addWidget(self._path_edit, 1)
        dir_row.addWidget(browse_btn)
        pl.addLayout(dir_row)
        layout.addWidget(path_card)

        # ── 控制 ──
        ctrl_card = CardWidget(inner)
        cl = QVBoxLayout(ctrl_card)
        cl.setContentsMargins(16, 12, 16, 16)
        cl.setSpacing(8)
        hdr = QHBoxLayout()
        hdr.addWidget(SubtitleLabel("隧道控制", ctrl_card))
        hdr.addStretch()
        self._start_btn = PrimaryPushButton("启动隧道", ctrl_card, FluentIcon.PLAY)
        self._start_btn.clicked.connect(self._start)
        self._stop_btn = PushButton("停止", ctrl_card, FluentIcon.CANCEL)
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._stop)
        self._auto_btn = ToggleButton("自动滚动", ctrl_card)
        self._auto_btn.setChecked(True)
        self._auto_btn.toggled.connect(lambda v: setattr(self, "_auto_scroll", v))
        hdr.addWidget(self._start_btn)
        hdr.addWidget(self._stop_btn)
        hdr.addWidget(self._auto_btn)
        cl.addLayout(hdr)

        self._log = QPlainTextEdit(ctrl_card)
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(5000)
        self._log.setMinimumHeight(250)
        self._log.setStyleSheet("""
            QPlainTextEdit { background: #1e1e1e; color: #ccc; border: 1px solid #3a3a3a; border-radius: 6px;
                             padding: 6px; font-family: Consolas, monospace; font-size: 12px; }
        """)
        cl.addWidget(self._log)
        layout.addWidget(ctrl_card)

        # ── frpc.ini 编辑 ──
        cfg_card = CardWidget(inner)
        cfl = QVBoxLayout(cfg_card)
        cfl.setContentsMargins(16, 12, 16, 16)
        cfl.setSpacing(8)
        cfl.addWidget(SubtitleLabel("frpc.ini 配置", cfg_card))
        self._cfg_edit = QPlainTextEdit(cfg_card)
        self._cfg_edit.setPlaceholderText("[common]\nserver_addr = example.com\nserver_port = 7000\ntoken = your_token\n\n[your_service]\ntype = udp\nlocal_ip = 127.0.0.1\nlocal_port = 19132\nremote_port = 19132")
        self._cfg_edit.setMinimumHeight(120)
        self._cfg_edit.setStyleSheet("""
            QPlainTextEdit { background: #1e1e1e; color: #ccc; border: 1px solid #3a3a3a; border-radius: 6px;
                             padding: 6px; font-family: Consolas, monospace; font-size: 12px; }
        """)
        cfl.addWidget(self._cfg_edit)
        save_btn = PrimaryPushButton("保存 frpc.ini", cfg_card, FluentIcon.SAVE)
        save_btn.clicked.connect(self._save_config)
        cfl.addWidget(save_btn)
        layout.addWidget(cfg_card)

        layout.addStretch()

        self._load_config()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 frpc.exe")
        if path:
            self._path_edit.setText(path)
            config_mgr.set("frpc_path", path)
            config_mgr.save()

    def _cfg_path(self) -> str:
        return os.path.join(os.path.dirname(self._path_edit.text() or "."), "frpc.ini")

    def _load_config(self):
        cfg = self._cfg_path()
        if os.path.exists(cfg):
            try:
                with open(cfg, "r", encoding="utf-8") as f:
                    self._cfg_edit.setPlainText(f.read())
            except Exception:
                pass

    def _save_config(self):
        cfg = self._cfg_path()
        try:
            with open(cfg, "w", encoding="utf-8") as f:
                f.write(self._cfg_edit.toPlainText())
            toast_success("已保存", cfg, self.window())
        except Exception as e:
            toast_error("保存失败", str(e), self.window())

    def _append_log(self, text: str, color="#ccc"):
        self._log.appendHtml(
            f'<span style="color:{color}; white-space:pre-wrap;">{_esc(text)}</span>'
        )
        if self._auto_scroll:
            self._log.moveCursor(QTextCursor.End)

    def _start(self):
        frpc = self._path_edit.text().strip()
        if not frpc or not os.path.exists(frpc):
            toast_error("错误", f"frpc.exe 不存在: {frpc}", self.window())
            return
        cfg = self._cfg_path()
        if not os.path.exists(cfg):
            toast_warning("提示", f"frpc.ini 不存在，已创建: {cfg}", self.window())
            self._save_config()

        self._save_config()
        config_mgr.set("frpc_path", frpc)
        config_mgr.save()

        try:
            self._process = subprocess.Popen(
                [frpc, "-c", cfg],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            self._running = True
            self._start_btn.setEnabled(False)
            self._stop_btn.setEnabled(True)
            self._append_log("[系统] frpc 已启动", "#4CAF50")

            self._reader = FrpcReader(self._process, self)
            self._reader.line_received.connect(self._append_log)
            self._reader.start()
        except Exception as e:
            toast_error("启动失败", str(e), self.window())

    def _stop(self):
        self._running = False
        if self._reader:
            self._reader.stop()
            self._reader.wait(2000)
            self._reader = None
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(3)
            except Exception:
                pass
        self._process = None
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._append_log("[系统] frpc 已停止", "#888")

    def cleanup(self):
        self._stop()
