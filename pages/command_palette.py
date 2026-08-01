# -*- coding: utf-8 -*-
"""
命令面板 —— 仿 VSCode Ctrl+K 跨页面快速跳转 + 常用操作。

v3.04.03 改进:
- 触控/远程桌面 QScroller 惯性滚动
- ThemePalette 主题感知（深色/浅色自动跟随）
- FramelessWindowHint + WA_TranslucentBackground 透明毛玻璃
- 输入框样式对齐项目 QPlainTextEdit 风格
- 「本地回环免除」命令
"""

import os
import subprocess
import sys
from typing import Callable

from PySide6.QtCore import Qt, QStringListModel, QPoint
from PySide6.QtGui import QKeyEvent, QFont, QPainter, QColor, QBrush, QPen, QMouseEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListView, QLineEdit, QLabel,
    QDialog, QApplication, QScroller, QFrame,
)
from qfluentwidgets import (
    BodyLabel, CaptionLabel, isDarkTheme,
)

from shared.theme import theme_palette


class CommandItem:
    """命令面板中的一个条目。"""
    def __init__(self, title: str, description: str, action: Callable,
                 keywords: str = "", icon_name: str = "SEND"):
        self.title = title
        self.description = description
        self.action = action
        self.keywords = keywords.lower()
        self.search_text = (title + " " + description + " " + keywords).lower()


class CommandPaletteDialog(QDialog):
    """命令面板弹窗（可拖动 + 半透明 + ThemePalette 主题感知）。"""

    def __init__(self, commands: list[CommandItem], parent=None):
        super().__init__(parent)
        self.setWindowTitle("命令面板")
        self.setModal(True)
        self.resize(600, 500)

        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._drag_pos = QPoint()

        self._commands = commands
        self._filtered: list[CommandItem] = list(commands)

        self._build_ui()
        self._input.setFocus()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if event.buttons() & Qt.LeftButton and not self._drag_pos.isNull():
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def _build_ui(self):
        p = theme_palette()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)  # 留边给透明底

        # 内部卡片 — 半透明圆角背景
        card = QFrame(self)
        card.setObjectName("paletteCard")
        alpha_val = "DC" if isDarkTheme() else "F0"
        bg_rgb = "24,24,27" if isDarkTheme() else "245,245,247"
        card.setStyleSheet(f"""
            QFrame#paletteCard {{
                background:rgba({bg_rgb},{alpha_val});
                border:1px solid {p.border};
                border-radius:14px;
            }}
        """)
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        # 标题
        title = CaptionLabel("命令面板  ·  输入关键词搜索页面或操作", card)
        title.setStyleSheet(f"color: {p.text_secondary}; font-size: 12px;")
        layout.addWidget(title)

        # v3.04.03: 输入框 — 对齐项目 plaintext_style()
        from shared.theme import plaintext_style as _ps
        self._input = QLineEdit(card)
        self._input.setPlaceholderText("搜索：备份、玩家、升级、回环...")
        self._input.setFont(QFont("Consolas", 12))
        self._input.setStyleSheet(f"""
            QLineEdit {{
                {_ps(font_family="Consolas, Microsoft YaHei", font_size=12, padding=8)}
                border:2px solid #0DC5D4; border-radius:8px;
            }}
            QLineEdit:focus {{ border-color: #0DC5D4; }}
        """)
        self._input.textChanged.connect(self._on_search)
        self._input.installEventFilter(self)
        layout.addWidget(self._input)

        # v3.04.03: 列表 + 触控
        self._list = QListView(card)
        QScroller.grabGesture(self._list, QScroller.LeftMouseButtonGesture)
        self._model = QStringListModel(card)
        self._list.setModel(self._model)
        item_border = p.border
        self._list.setStyleSheet(f"""
            QListView {{
                background:{p.card_bg}; color:{p.text};
                border:1px solid {item_border}; border-radius:8px; outline:0;
            }}
            QListView::item {{
                padding:10px 12px; border-bottom:1px solid {item_border};
            }}
            QListView::item:selected {{
                background:rgba(13,197,212,0.2); color:{p.text};
            }}
        """)
        self._list.setFont(QFont("Microsoft YaHei", 11))
        self._list.doubleClicked.connect(self._on_activate)
        self._list.activated.connect(self._on_activate)
        layout.addWidget(self._list, 1)

        # 底部提示
        hint = CaptionLabel("↑↓ 选择  Enter 确认  Esc 关闭", card)
        hint.setStyleSheet(f"color: {p.text_secondary};")
        layout.addWidget(hint)

        self._refresh_model()

    def _on_search(self, text: str):
        text = text.strip().lower()
        if not text:
            self._filtered = list(self._commands)
        else:
            self._filtered = [c for c in self._commands if text in c.search_text]
        self._refresh_model()

    def _refresh_model(self):
        items = [f"  {c.title}  —  {c.description}" for c in self._filtered]
        self._model.setStringList(items)
        if items:
            self._list.setCurrentIndex(self._model.index(0, 0))

    def _on_activate(self, *_):
        idx = self._list.currentIndex().row()
        if 0 <= idx < len(self._filtered):
            cmd = self._filtered[idx]
            self.accept()
            try:
                cmd.action()
            except Exception:
                pass

    def eventFilter(self, obj, event):
        if obj == self._input and event.type() == QKeyEvent.KeyPress:
            if event.key() in (Qt.Key_Down, Qt.Key_Up):
                row = self._list.currentIndex().row()
                if event.key() == Qt.Key_Down:
                    row = min(row + 1, self._model.rowCount() - 1)
                else:
                    row = max(row - 1, 0)
                self._list.setCurrentIndex(self._model.index(row, 0))
                return True
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._on_activate()
                return True
            if event.key() == Qt.Key_Escape:
                self.reject()
                return True
        return super().eventFilter(obj, event)


def build_default_commands(window) -> list[CommandItem]:
    """构造主窗口的命令列表。"""
    cmds: list[CommandItem] = []

    def nav_to(key: str):
        def f():
            page = getattr(window, f"{key}_page", None)
            if page is not None:
                window.switchTo(page)
        return f

    # 页面跳转
    for key, label, kw in [
        ("dashboard", "仪表盘", "home 主页 总览"), ("console", "控制台", "console 日志 命令"),
        ("world", "世界/备份", "world backup 还原"), ("packs", "资源包", "pack 资源 行为"),
        ("config", "配置", "config server.properties"), ("upgrade", "升级/版本", "upgrade 版本"),
        ("tunnel", "隧道/内网穿透", "tunnel frp"), ("settings", "设置", "settings 选项"),
        ("about", "关于", "about 版本"),
    ]:
        cmds.append(CommandItem(label, f"跳转到{label}", nav_to(key), kw))

    # 服务器操作
    def start_server():
        if hasattr(window, "start_server"): window.start_server()
    def stop_server():
        if hasattr(window, "stop_server"): window.stop_server()
    cmds.append(CommandItem("启动服务器", "启动 BDS", start_server, "start"))
    cmds.append(CommandItem("停止服务器", "停止 BDS", stop_server, "stop"))

    # 控制台命令
    def send_cmd(cmd_text):
        def f():
            if hasattr(window, "console_page") and window.is_server_running:
                window.console_page._send_command(cmd_text)
        return f
    for label, cmd in [("发送 list", "list"), ("保存世界", "save hold"),
                        ("发送 stop", "stop"), ("开启白名单", "whitelist on"),
                        ("设为白天", "time set day")]:
        cmds.append(CommandItem(label, f"控制台: {cmd}", send_cmd(cmd), f"cmd {cmd}"))

    # 备份
    def do_backup():
        if hasattr(window, "world_page"): window.world_page._on_backup()
    cmds.append(CommandItem("手动备份", "立即备份世界", do_backup, "backup"))

    # v3.04.03: 本地回环免除
    def do_loopback_exempt():
        cmd = ["CheckNetIsolation", "LoopbackExempt", "-a",
               "-n=Microsoft.MinecraftUWP_8wekyb3d8bbwe"]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            from shared.toast import toast_success, toast_error
            if r.returncode == 0:
                toast_success("回环免除", "已添加 Minecraft UWP 本地连接权限", window)
            else:
                toast_error("回环免除失败", r.stderr.strip() or "请以管理员运行", window)
        except Exception as e:
            from shared.toast import toast_error
            toast_error("回环免除失败", str(e), window)
    cmds.append(CommandItem("本地回环免除 (管理员)", "允许 Minecraft 连接本机 BDS",
                            do_loopback_exempt, "loopback uwp 回环"))

    # 主题切换
    def set_theme(t):
        def f():
            if hasattr(window, "apply_theme"):
                c = window._current_color if hasattr(window, "_current_color") else "#0DC5D4"
                window.apply_theme(t, c)
        return f
    for t, label in [("dark", "暗色主题"), ("light", "亮色主题")]:
        cmds.append(CommandItem(f"切换{label}", f"{label}", set_theme(t), f"theme {t}"))

    return cmds
