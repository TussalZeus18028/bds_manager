# -*- coding: utf-8 -*-
"""
命令面板 —— 仿 VSCode Ctrl+K 跨页面快速跳转 + 常用操作。

v3.04.03 改进:
- 触控/远程桌面 QScroller 惯性滚动
- 深色模式输入框适配 ThemePalette
- 半透明毛玻璃背景（根据主题+bg_opacity）
- 新增「本地回环免除」命令
"""

import os
import subprocess
import sys
from typing import Callable

from PySide6.QtCore import Qt, QStringListModel, QSize
from PySide6.QtGui import QKeyEvent, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListView, QLineEdit, QLabel,
    QDialog, QApplication, QScroller,
)
from qfluentwidgets import (
    CardWidget, BodyLabel, CaptionLabel, FluentIcon, PrimaryPushButton, isDarkTheme,
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
    """命令面板弹窗（v3.04.03: ThemePalette 主题感知 + 触控）。"""

    def __init__(self, commands: list[CommandItem], parent=None):
        super().__init__(parent)
        self.setWindowTitle("命令面板")
        self.setModal(True)
        self.resize(620, 520)

        # v3.04.03: ThemePalette 主题感知 — 每次创建读取当前主题色
        # 不使用 WA_TranslucentBackground（QDialog 在 Windows 下会渲染异常）
        p = theme_palette()
        self.setStyleSheet(f"""
            QDialog {{
                background:{p.surface};
                border:1px solid {p.border};
                border-radius:12px;
            }}
        """)

        self._commands = commands
        self._filtered: list[CommandItem] = list(commands)
        self._build()
        self._input.setFocus()

    def _build(self):
        p = theme_palette()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        # 标题
        title = BodyLabel("命令面板  输入关键词搜索页面或操作", self)
        title.setStyleSheet(f"color: {p.text_secondary}; font-size: 12px;")
        layout.addWidget(title)

        # v3.04.03: 输入框 ThemePalette 适配深色模式
        self._input = QLineEdit(self)
        self._input.setPlaceholderText("搜索：备份、玩家、升级...")
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background:{p.surface}; color:{p.text};
                border:2px solid #0DC5D4; border-radius:8px;
                padding:10px 14px; font-size:14px;
            }}
            QLineEdit:focus {{ border-color: #0DC5D4; }}
        """)
        self._input.textChanged.connect(self._on_search)
        self._input.installEventFilter(self)
        layout.addWidget(self._input)

        # v3.04.03: 列表 + 触控适配
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

        # 底部提示
        hint = CaptionLabel("↑↓ 选择  Enter 确认  Esc 关闭", self)
        hint.setStyleSheet(f"color: {p.text_secondary};")
        layout.addWidget(hint)

        self._refresh_model()

    def _on_search(self, text: str):
        text = text.strip().lower()
        if not text:
            self._filtered = list(self._commands)
        else:
            self._filtered = [c for c in self._commands
                              if text in c.search_text]
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
            except Exception as e:
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

    # v3.02.01 fix: navigationInterface.setCurrentItem 只亮导航不切页面
    def nav_to(key: str):
        def f():
            page = getattr(window, f"{key}_page", None)
            if page is not None:
                window.switchTo(page)
        return f

    # 页面跳转
    cmds.append(CommandItem("仪表盘", "跳转到仪表盘", nav_to("dashboard"),
                            "home 主页 总览 状态", "HOME"))
    cmds.append(CommandItem("控制台", "跳转到控制台", nav_to("console"),
                            "console 日志 命令 玩家", "COMMAND_PROMPT"))
    cmds.append(CommandItem("世界", "跳转到世界/备份", nav_to("world"),
                            "world 备份 backup 还原 restore", "SAVE"))
    cmds.append(CommandItem("资源包", "跳转到资源包", nav_to("packs"),
                            "pack 资源 行为", "FOLDER"))
    cmds.append(CommandItem("配置", "跳转到配置", nav_to("config"),
                            "config 配置 属性 server.properties", "EDIT"))
    cmds.append(CommandItem("升级", "跳转到升级", nav_to("upgrade"),
                            "upgrade 升级 版本 version", "SYNC"))
    cmds.append(CommandItem("隧道", "跳转到隧道", nav_to("tunnel"),
                            "tunnel frp 内网穿透 chmlfrp", "LINK"))
    cmds.append(CommandItem("设置", "跳转到设置", nav_to("settings"),
                            "settings 设置 选项", "SETTING"))
    cmds.append(CommandItem("关于", "跳转到关于", nav_to("about"),
                            "about 关于 版本", "INFO"))

    # 服务器操作
    def start_server():
        if hasattr(window, "start_server"):
            window.start_server()
    def stop_server():
        if hasattr(window, "stop_server"):
            window.stop_server()
    cmds.append(CommandItem("启动服务器", "启动 BDS 服务", start_server,
                            "start 启动 begin", "PLAY"))
    cmds.append(CommandItem("停止服务器", "停止 BDS 服务", stop_server,
                            "stop 停止 halt", "CANCEL"))

    # 控制台命令快捷
    def send_cmd(cmd_text):
        def f():
            if hasattr(window, "console_page") and window.is_server_running:
                window.console_page._send_command(cmd_text)
        return f
    for label, cmd in [
        ("发送 list 命令", "list"),
        ("保存世界（save hold）", "save hold"),
        ("发送 stop 命令", "stop"),
        ("发送 whitelist on 命令", "whitelist on"),
        ("发送 time set day 命令", "time set day"),
    ]:
        cmds.append(CommandItem(label, f"在控制台执行: {cmd}", send_cmd(cmd),
                                f"cmd 命令 send", "SEND"))

    # 备份
    def do_backup():
        if hasattr(window, "world_page"):
            window.world_page._on_backup()
    cmds.append(CommandItem("手动备份", "立即备份当前世界", do_backup,
                            "backup 备份 save", "SAVE"))

    # v3.04.03: 本地回环免除 — 允许 Minecraft UWP 连接本地 BDS
    def do_loopback_exempt():
        cmd = [
            "CheckNetIsolation", "LoopbackExempt", "-a",
            "-n=Microsoft.MinecraftUWP_8wekyb3d8bbwe",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            from shared.toast import toast_success, toast_error
            if result.returncode == 0:
                toast_success("回环免除", "已添加 Minecraft UWP 本地连接权限", window)
            else:
                toast_error("回环免除失败", result.stderr.strip() or "权限不足, 请以管理员运行",
                            window, duration=5000)
        except Exception as e:
            from shared.toast import toast_error
            toast_error("回环免除失败", str(e), window)
    cmds.append(CommandItem("本地回环免除 (管理员)", "允许 Minecraft 连接本机 BDS",
                            do_loopback_exempt, "loopback uwp 本地 回环 免除 管理员", "WIFI"))

    # 主题切换
    def set_theme(t):
        def f():
            if hasattr(window, "apply_theme"):
                color = window._current_color if hasattr(window, "_current_color") else "#0DC5D4"
                window.apply_theme(t, color)
        return f
    for t, label in [("dark", "切换到暗色主题"), ("light", "切换到亮色主题")]:
        cmds.append(CommandItem(label, f"切换主题: {t}", set_theme(t),
                                f"theme 主题 {t}", "BRUSH"))

    return cmds
