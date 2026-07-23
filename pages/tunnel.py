# -*- coding: utf-8 -*-
"""
内网穿透页面 —— ChmlFrp / frpc 隧道管理。
"""

import os, subprocess, sys

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QFileDialog,
    QMessageBox,
)
from PySide6.QtGui import QTextCursor
from qfluentwidgets import (
    CardWidget, SubtitleLabel, StrongBodyLabel, BodyLabel, CaptionLabel,
    PrimaryPushButton, PushButton, LineEdit, FluentIcon, ToggleButton, isDarkTheme,
)

from shared.config import config_mgr
from shared.toast import toast_success, toast_error, toast_warning
from pages.dashboard import wrap_scrollable

import html as _hmod


def _plaintext_style() -> str:
    """v3.02.01: QPlainTextEdit 主题感知样式。"""
    if isDarkTheme():
        return """
            QPlainTextEdit {
                background: #1e1e1e; color: #ccc;
                border: 1px solid #3a3a3a; border-radius: 6px;
                padding: 6px; font-family: Consolas, monospace; font-size: 12px;
            }
        """
    return """
        QPlainTextEdit {
            background: #fafafa; color: #1a1a1a;
            border: 1px solid #d0d0d0; border-radius: 6px;
            padding: 6px; font-family: Consolas, monospace; font-size: 12px;
        }
    """


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
        # v3.02.01 fix: 给按钮显式 min_w（之前 ToggleButton 的文字被 check indicator
        # 挤压，「自动滚动」显示成「自动滚」+ 图标；PrimaryPushButton 也需要 padding buffer）
        self._start_btn = PrimaryPushButton("启动", ctrl_card, FluentIcon.PLAY)
        self._start_btn.setMinimumWidth(96)
        self._start_btn.clicked.connect(self._start)
        self._stop_btn = PushButton("停止", ctrl_card, FluentIcon.CANCEL)
        self._stop_btn.setMinimumWidth(80)
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._stop)
        self._auto_btn = ToggleButton("自动滚动", ctrl_card)
        self._auto_btn.setMinimumWidth(108)  # ← 关键：ToggleButton 默认宽度让 4 字被截断
        self._auto_btn.setChecked(True)
        self._auto_btn.toggled.connect(lambda v: setattr(self, "_auto_scroll", v))
        hdr.addWidget(self._start_btn)
        hdr.addSpacing(6)
        hdr.addWidget(self._stop_btn)
        hdr.addSpacing(6)
        hdr.addWidget(self._auto_btn)
        cl.addLayout(hdr)

        self._log = QPlainTextEdit(ctrl_card)
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(5000)
        self._log.setMinimumHeight(250)
        self._log.setStyleSheet(_plaintext_style())
        cl.addWidget(self._log)
        layout.addWidget(ctrl_card)

        # ── frpc.ini 编辑 ──
        cfg_card = CardWidget(inner)
        cfl = QVBoxLayout(cfg_card)
        cfl.setContentsMargins(16, 12, 16, 16)
        cfl.setSpacing(8)
        cfl.addWidget(SubtitleLabel("frpc.ini 配置", cfg_card))
        self._cfg_edit = QPlainTextEdit(cfg_card)
        self._cfg_edit.setPlaceholderText("...")
        self._cfg_edit.setReadOnly(True)
        self._cfg_edit.setMinimumHeight(120)
        self._cfg_edit.setStyleSheet(_plaintext_style())
        cfl.addWidget(self._cfg_edit)

        # 按钮行（对齐旧版：锁定/保存/加载/打开目录/模板）
        # v3.02.01 fix: 移除 setMaximumWidth（之前 max_w 太窄导致 "打开目录" → "打开目"、
        # "模板" → "模" 等被截断）。改用 setMinimumWidth 保证最小可读宽度
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self._edit_lock_btn = PushButton("点击编辑", cfg_card, FluentIcon.EDIT)
        self._edit_lock_btn.setCheckable(True)
        self._edit_lock_btn.toggled.connect(self._toggle_ini_edit)
        self._edit_lock_btn.setMinimumWidth(96)
        btn_row.addWidget(self._edit_lock_btn)

        save_btn = PrimaryPushButton("保存", cfg_card, FluentIcon.SAVE)
        save_btn.clicked.connect(self._save_config)
        save_btn.setMinimumWidth(72)
        btn_row.addWidget(save_btn)

        load_btn = PushButton("加载", cfg_card, FluentIcon.FOLDER)
        load_btn.clicked.connect(self._load_ini_from_file)
        load_btn.setMinimumWidth(72)
        btn_row.addWidget(load_btn)

        open_dir_btn = PushButton("打开目录", cfg_card, FluentIcon.FOLDER)
        open_dir_btn.clicked.connect(self._open_frpc_dir)
        open_dir_btn.setMinimumWidth(88)
        btn_row.addWidget(open_dir_btn)

        template_btn = PushButton("模板", cfg_card, FluentIcon.HELP)
        template_btn.clicked.connect(self._load_template)
        template_btn.setMinimumWidth(72)
        btn_row.addWidget(template_btn)

        btn_row.addStretch()
        cfl.addLayout(btn_row)
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
            os.makedirs(os.path.dirname(cfg), exist_ok=True)
            with open(cfg, "w", encoding="utf-8") as f:
                f.write(self._cfg_edit.toPlainText())
            self._append_log(f"✅ frpc.ini 已保存: {cfg}", "#4CAF50")
            toast_success("已保存", cfg, self.window())
        except Exception as e:
            toast_error("保存失败", str(e), self.window())

    def _toggle_ini_edit(self, checked):
        """锁定/解锁编辑器"""
        self._cfg_edit.setReadOnly(not checked)
        if checked:
            self._edit_lock_btn.setText("编辑中")
            self._edit_lock_btn.setIcon(FluentIcon.PENCIL_INK)
            self._edit_lock_btn.setStyleSheet("color: #ffaa33; font-weight: bold;")
        else:
            self._edit_lock_btn.setText("点击编辑")
            self._edit_lock_btn.setIcon(FluentIcon.EDIT)
            self._edit_lock_btn.setStyleSheet("")

    def _load_ini_from_file(self):
        """从文件加载 frpc.ini（不清空，追加到编辑器）"""
        cfg = self._cfg_path()
        if not os.path.exists(cfg):
            toast_warning("文件不存在", f"frpc.ini 不存在：{cfg}", self.window())
            return
        try:
            with open(cfg, "r", encoding="utf-8") as f:
                self._cfg_edit.setPlainText(f.read())
            self._append_log(f"📂 已加载: {cfg}", "#888")
            toast_success("已加载", cfg, self.window())
        except Exception as e:
            toast_error("加载失败", str(e), self.window())

    def _open_frpc_dir(self):
        """打开 frpc.exe 所在目录"""
        dir_path = os.path.dirname(self._path_edit.text())
        if not dir_path or not os.path.exists(dir_path):
            toast_warning("目录不存在", "请先设置正确的 frpc.exe 路径", self.window())
            return
        try:
            os.startfile(dir_path) if sys.platform == "win32" else subprocess.Popen(["xdg-open", dir_path])
        except Exception as e:
            toast_error("打开目录失败", str(e), self.window())

    def _load_template(self):
        """加载 frpc.ini 模板"""
        template = (
            "# frpc.ini 配置模板\n"
            "# 请访问 ChmlFrp 官网获取隧道信息：https://www.chmlfrp.net/\n"
            "# 在官网创建隧道后，复制生成的配置到下方\n"
            "#\n"
            "# 示例配置:\n"
            "# [common]\n"
            "# server_addr = 你的服务器地址\n"
            "# server_port = 7000\n"
            "# token = 你的token\n"
            "#\n"
            "# [你的隧道名称]\n"
            "# type = tcp\n"
            "# local_ip = 127.0.0.1\n"
            "# local_port = 19132\n"
            "# remote_port = 外网端口\n"
        )
        reply = QMessageBox.question(
            self, "加载模板",
            "将用模板替换当前编辑内容，是否继续？\n\n"
            "提示：请前往 https://www.chmlfrp.net/ 创建隧道。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._cfg_edit.setPlainText(template)

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
