# -*- coding: utf-8 -*-
"""
命令面板 —— 仿 VSCode Ctrl+K 跨页面快速跳转 + 常用操作。

v3.04.03:
- 可拖动无边框窗口
- ThemePalette 深色/浅色自动跟随
- 输入框对齐控制台编辑器风格
- 触控 QScroller
- 「本地回环免除」命令
"""

import os, subprocess, sys
from typing import Callable

from PySide6.QtCore import Qt, QStringListModel, QPoint, QRect
from PySide6.QtGui import QKeyEvent, QFont, QMouseEvent, QPainterPath, QRegion
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListView, QLineEdit, QLabel,
    QDialog, QScroller, QFrame,
)
from qfluentwidgets import BodyLabel, CaptionLabel, isDarkTheme

from shared.theme import theme_palette


class CommandItem:
    def __init__(self, title, description, action, keywords="", icon_name="SEND"):
        self.title = title
        self.description = description
        self.action = action
        self.keywords = keywords.lower()
        self.search_text = (title + " " + description + " " + keywords).lower()


class CommandPaletteDialog(QDialog):
    """命令面板弹窗（可拖动 + 半透明 + 深色适配 + 触控）。"""

    def __init__(self, commands: list[CommandItem], parent=None):
        super().__init__(parent)
        self.setWindowTitle("命令面板")
        self.setModal(True)
        self.resize(600, 500)

        # Popup = 无边框 + 无任务栏图标
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._drag_pos = QPoint()

        self._commands = commands
        self._filtered: list[CommandItem] = list(commands)
        self._build_ui()
        self._input.setFocus()

    def resizeEvent(self, event):
        """圆角遮罩裁剪。"""
        path = QPainterPath()
        path.addRoundedRect(QRect(0, 0, self.width(), self.height()), 14, 14)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))
        super().resizeEvent(event)

    # ── 拖动 ──
    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent):
        if e.buttons() & Qt.LeftButton and not self._drag_pos.isNull():
            self.move(e.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(e)

    # ── UI ──
    def _build_ui(self):
        p = theme_palette()

        # 半透明背景
        a = "CC" if isDarkTheme() else "EE"
        rgb = "22,22,26" if isDarkTheme() else "240,240,244"
        self.setStyleSheet(f"""
            QDialog {{ background:rgba({rgb},{a}); border:none; border-radius:14px; }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        # 标题
        title = CaptionLabel("命令面板  ·  输入关键词搜索页面或操作", self)
        title.setStyleSheet(f"color: {p.text_secondary}; font-size: 12px;")
        layout.addWidget(title)

        # 输入框 — 深色适配
        self._input = QLineEdit(self)
        self._input.setPlaceholderText("搜索：备份、玩家、升级、回环...")
        self._input.setFont(QFont("Consolas", 12))
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background:{p.card_bg}; color:{p.text};
                border:2px solid #0DC5D4; border-radius:8px;
                padding:9px 12px; font-size:14px;
            }}
        """)
        self._input.textChanged.connect(self._on_search)
        self._input.installEventFilter(self)
        layout.addWidget(self._input)

        # 列表 + 触控
        self._list = QListView(self)
        QScroller.grabGesture(self._list, QScroller.LeftMouseButtonGesture)
        self._model = QStringListModel(self)
        self._list.setModel(self._model)
        self._list.setStyleSheet(f"""
            QListView {{
                background:{p.card_bg}; color:{p.text};
                border:1px solid {p.border}; border-radius:8px; outline:0;
            }}
            QListView::item {{
                padding:10px 12px; border-bottom:1px solid {p.border};
            }}
            QListView::item:selected {{
                background:rgba(13,197,212,0.2); color:{p.text};
            }}
        """)
        self._list.setFont(QFont("Microsoft YaHei", 11))
        self._list.doubleClicked.connect(self._on_activate)
        self._list.activated.connect(self._on_activate)
        layout.addWidget(self._list, 1)

        hint = CaptionLabel("↑↓ 选择  Enter 确认  Esc 关闭", self)
        hint.setStyleSheet(f"color: {p.text_secondary};")
        layout.addWidget(hint)

        self._refresh_model()

    def _on_search(self, text):
        text = text.strip().lower()
        self._filtered = list(self._commands) if not text else [c for c in self._commands if text in c.search_text]
        self._refresh_model()

    def _refresh_model(self):
        items = [f"  {c.title}  —  {c.description}" for c in self._filtered]
        self._model.setStringList(items)
        if items:
            self._list.setCurrentIndex(self._model.index(0, 0))

    def _on_activate(self, *_):
        idx = self._list.currentIndex().row()
        if 0 <= idx < len(self._filtered):
            self.accept()
            try:
                self._filtered[idx].action()
            except Exception:
                pass

    def eventFilter(self, obj, event):
        if obj == self._input and event.type() == QKeyEvent.KeyPress:
            if event.key() in (Qt.Key_Down, Qt.Key_Up):
                row = self._list.currentIndex().row()
                row = min(row + 1, self._model.rowCount() - 1) if event.key() == Qt.Key_Down else max(row - 1, 0)
                self._list.setCurrentIndex(self._model.index(row, 0))
                return True
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self._on_activate(); return True
            if event.key() == Qt.Key_Escape:
                self.reject(); return True
        return super().eventFilter(obj, event)


def build_default_commands(window) -> list[CommandItem]:
    cmds: list[CommandItem] = []

    def nav_to(key):
        def f():
            page = getattr(window, f"{key}_page", None)
            if page: window.switchTo(page)
        return f

    for key, label, kw in [
        ("dashboard","仪表盘","home"), ("console","控制台","console 日志"),
        ("world","世界/备份","world backup"), ("packs","资源包","pack"),
        ("config","配置","config"), ("upgrade","升级","upgrade 版本"),
        ("tunnel","隧道","tunnel frp"), ("settings","设置","settings"),
        ("about","关于","about"),
    ]:
        cmds.append(CommandItem(label, f"跳转到{label}", nav_to(key), kw))

    def srv_start():
        if hasattr(window,"start_server"): window.start_server()
    def srv_stop():
        if hasattr(window,"stop_server"): window.stop_server()
    cmds.append(CommandItem("启动服务器","启动 BDS", srv_start, "start"))
    cmds.append(CommandItem("停止服务器","停止 BDS", srv_stop, "stop"))

    def send_cmd(t):
        def f():
            if hasattr(window,"console_page") and window.is_server_running:
                window.console_page._send_command(t)
        return f
    for l, c in [("发送 list","list"),("保存世界","save hold"),("发送 stop","stop"),
                 ("开启白名单","whitelist on"),("设为白天","time set day")]:
        cmds.append(CommandItem(l, f"控制台: {c}", send_cmd(c), f"cmd {c}"))

    def backup():
        if hasattr(window,"world_page"): window.world_page._on_backup()
    cmds.append(CommandItem("手动备份","立即备份世界", backup, "backup"))

    def loopback():
        r = subprocess.run(
            ["CheckNetIsolation","LoopbackExempt","-a","-n=Microsoft.MinecraftUWP_8wekyb3d8bbwe"],
            capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        from shared.toast import toast_success, toast_error
        if r.returncode == 0:
            toast_success("回环免除","已添加 Minecraft UWP 本地连接权限", window)
        else:
            toast_error("回环免除失败", r.stderr.strip() or "请以管理员运行", window)
    cmds.append(CommandItem("本地回环免除 (管理员)","允许 Minecraft 连接本机 BDS",
                            loopback, "loopback uwp 回环"))

    def set_theme(t):
        def f():
            if hasattr(window,"apply_theme"):
                c = getattr(window,"_current_color","#0DC5D4")
                window.apply_theme(t, c)
        return f
    for t, l in [("dark","暗色"),("light","亮色")]:
        cmds.append(CommandItem(f"切换{l}主题", l, set_theme(t), f"theme {t}"))

    return cmds
