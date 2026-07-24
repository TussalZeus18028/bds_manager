# -*- coding: utf-8 -*-
"""
控制台页面 —— 服务器输出、命令发送、玩家列表、启停控制。

v3.1 改进：
- 4 个级别过滤 CheckBox（INFO/WARN/ERROR/玩家聊天）
- 每行时间戳前缀
- BDS 内置命令 Tab 自动补全 + 玩家名补全
- 崩溃重启时在顶部插红条
- 日志按天轮转（logs/server_YYYY-MM-DD.log）
- 假死检测标记
"""

import os
import re
import html
import time
from datetime import datetime
from threading import Lock

from PySide6.QtCore import Qt, QTimer, QStringListModel
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame,
    QPlainTextEdit, QCompleter,
)
from PySide6.QtGui import QTextCursor, QTextCharFormat, QColor
from qfluentwidgets import (
    CardWidget, SubtitleLabel, StrongBodyLabel, BodyLabel, CaptionLabel,
    PrimaryPushButton, PushButton, LineEdit, FluentIcon,
    ToggleButton, CheckBox, isDarkTheme,
)

from pages.dashboard import wrap_scrollable
from pages.console_search import ConsoleSearchBar
from shared.toast import toast_warning, toast_error
from shared.config import LOG_DIR, config_mgr

# ── 写入日志文件（按天轮转）──
_log_file = None
_log_file_path = None
_log_lock = Lock()


def _init_log_file():
    """初始化或轮转日志文件：logs/server_YYYY-MM-DD.log。"""
    global _log_file, _log_file_path
    today = datetime.now().strftime("%Y-%m-%d")
    new_path = os.path.join(LOG_DIR, f"server_{today}.log")
    if _log_file_path == new_path and _log_file is not None:
        return
    _close_log_file()
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        _log_file = open(new_path, "a", encoding="utf-8")
        _log_file_path = new_path
    except Exception:
        _log_file = None


def _write_log(text: str):
    global _log_file
    if _log_file is None:
        return
    try:
        ts = datetime.now().strftime("%H:%M:%S")
        with _log_lock:
            _log_file.write(f"[{ts}] {text}\n")
            _log_file.flush()
    except Exception:
        pass


def _close_log_file():
    global _log_file
    if _log_file:
        try:
            _log_file.close()
        except Exception:
            pass
        _log_file = None


# ── 暗色日志 ──
def _log_style() -> str:
    """v3.02.01: 控制台日志 QPlainTextEdit 主题感知样式。"""
    if isDarkTheme():
        return """
            QPlainTextEdit { background:#1e1e1e; color:#ccc; border:1px solid #3a3a3a;
                border-radius:6px; padding:6px; font-family:Consolas,"Microsoft YaHei",monospace; font-size:12px; }
        """
    return """
        QPlainTextEdit { background:#fafafa; color:#1a1a1a; border:1px solid #d0d0d0;
            border-radius:6px; padding:6px; font-family:Consolas,"Microsoft YaHei",monospace; font-size:12px; }
    """


def make_console_log(parent=None, min_height=200):
    log = QPlainTextEdit(parent)
    log.setReadOnly(True)
    if min_height:
        log.setMinimumHeight(min_height)
    max_lines = config_mgr.get("console_max_lines", 5000)
    log.setMaximumBlockCount(max_lines)
    log.setStyleSheet(_log_style())
    return log


# ---------- 玩家列表 ----------
class PlayerListWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._known: dict[str, float] = {}  # name -> join_time
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        header = QHBoxLayout()
        header.addWidget(CaptionLabel("在线玩家", self))
        self._count_label = CaptionLabel("0", self)
        header.addWidget(self._count_label)
        header.addStretch()
        layout.addLayout(header)
        self._list_label = BodyLabel("—", self)
        self._list_label.setWordWrap(True)
        self._list_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self._list_label)

    def update_players(self, names: list[str]):
        self._count_label.setText(str(len(names)))
        self._list_label.setText(", ".join(names) if names else "—")


# ---------- 级别过滤器 ----------
class LevelFilterBar(QWidget):
    """4 个 CheckBox 用于过滤显示哪些级别的日志。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(CaptionLabel("过滤:", self))
        self._filters: dict[str, CheckBox] = {}
        for label, key in [("信息", "info"), ("警告", "warn"),
                           ("错误", "error"), ("聊天", "chat")]:
            cb = CheckBox(label, self)
            cb.setChecked(True)
            self._filters[key] = cb
            layout.addWidget(cb)
        layout.addStretch()

    def is_enabled(self, level: str) -> bool:
        return self._filters.get(level, CheckBox(self)).isChecked()

    def levels_enabled(self) -> set[str]:
        return {k for k, cb in self._filters.items() if cb.isChecked()}


# ---------- 控制台页面 ----------
class ConsolePage(QWidget):
    """控制台 —— v3.1。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._auto_scroll = config_mgr.get("console_auto_scroll", True)
        self._cmd_history: list[str] = []
        self._cmd_history_idx = -1
        self._crash_marker_visible = False
        self._show_timestamps = config_mgr.get("console_show_timestamps", True)
        inner, layout = wrap_scrollable(self, spacing=12)

        # ── 操作栏 ──
        ctrl_card = CardWidget(inner)
        ctrl_layout = QHBoxLayout(ctrl_card)
        ctrl_layout.setContentsMargins(16, 12, 16, 12)
        ctrl_layout.setSpacing(8)

        self._start_btn = PrimaryPushButton("启动服务器", ctrl_card, FluentIcon.PLAY)
        self._start_btn.clicked.connect(self._on_start)
        self._start_btn.setMinimumWidth(100)
        self._stop_btn = PushButton("停止", ctrl_card, FluentIcon.CANCEL)
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop)
        self._restart_btn = PushButton("重启", ctrl_card, FluentIcon.SYNC)
        self._restart_btn.setEnabled(False)
        self._restart_btn.clicked.connect(self._on_restart)
        self._auto_btn = ToggleButton("自动滚动", ctrl_card)
        self._auto_btn.setChecked(self._auto_scroll)
        self._auto_btn.toggled.connect(self._on_auto_scroll_toggle)
        self._auto_btn.setMinimumWidth(90)

        ctrl_layout.addWidget(self._start_btn)
        ctrl_layout.addWidget(self._stop_btn)
        ctrl_layout.addWidget(self._restart_btn)
        ctrl_layout.addStretch()
        self._status_label = BodyLabel("● 未运行", ctrl_card)
        self._status_label.setStyleSheet("color: #888;")
        ctrl_layout.addWidget(self._status_label)
        ctrl_layout.addStretch()
        ctrl_layout.addWidget(self._auto_btn)
        layout.addWidget(ctrl_card)

        # ── 级别过滤 + 假死提示 ──
        filter_card = CardWidget(inner)
        filter_layout = QVBoxLayout(filter_card)
        filter_layout.setContentsMargins(16, 6, 16, 6)
        filter_layout.setSpacing(4)
        self._level_filter = LevelFilterBar(filter_card)
        filter_layout.addWidget(self._level_filter)
        self._stale_label = CaptionLabel("", filter_card)
        self._stale_label.setStyleSheet("color: #ff5555; font-weight: bold;")
        self._stale_label.setVisible(False)
        filter_layout.addWidget(self._stale_label)
        layout.addWidget(filter_card)

        # ── 日志 + 玩家 ──
        log_player = QHBoxLayout()
        log_player.setSpacing(12)

        log_card = CardWidget(inner)
        log_inner = QVBoxLayout(log_card)
        log_inner.setContentsMargins(12, 10, 12, 12)
        log_inner.setSpacing(8)
        log_inner.addWidget(StrongBodyLabel("服务器输出", log_card))
        self._log = make_console_log(log_card, min_height=280)
        log_inner.addWidget(self._log)
        log_player.addWidget(log_card, 3)

        player_card = CardWidget(inner)
        player_inner = QVBoxLayout(player_card)
        player_inner.setContentsMargins(12, 10, 12, 12)
        player_inner.setSpacing(8)
        player_inner.addWidget(StrongBodyLabel("玩家", player_card))
        self._players = PlayerListWidget(player_card)
        player_inner.addWidget(self._players)
        player_inner.addStretch()
        log_player.addWidget(player_card, 1)
        layout.addLayout(log_player)

        # ── 搜索 + 命令输入 ──
        search_card = CardWidget(inner)
        search_layout = QHBoxLayout(search_card)
        search_layout.setContentsMargins(12, 6, 12, 6)
        self._search_bar = ConsoleSearchBar(search_card, self._log)
        search_layout.addLayout(self._search_bar)
        layout.addWidget(search_card)

        # 命令输入（带 Tab 补全）
        cmd_card = CardWidget(inner)
        cmd_layout = QHBoxLayout(cmd_card)
        cmd_layout.setContentsMargins(16, 10, 16, 10)
        cmd_layout.setSpacing(8)
        self._cmd_input = LineEdit(cmd_card)
        self._cmd_input.setPlaceholderText("输入命令后回车发送（Tab 自动补全）")
        self._cmd_input.returnPressed.connect(self._send)
        send_btn = PushButton("发送", cmd_card, FluentIcon.SEND)
        send_btn.clicked.connect(self._send)
        # 命令补全
        self._completer_model = QStringListModel()
        self._completer = QCompleter(self._completer_model, self)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._cmd_input.setCompleter(self._completer)
        self._refresh_completer()
        cmd_layout.addWidget(self._cmd_input, 1)
        cmd_layout.addWidget(send_btn)
        layout.addWidget(cmd_card)

        self._cmd_input.installEventFilter(self)

        # 命令预设按钮
        preset_card = CardWidget(inner)
        preset_layout = QHBoxLayout(preset_card)
        preset_layout.setContentsMargins(16, 8, 16, 8)
        preset_layout.setSpacing(6)
        preset_layout.addWidget(CaptionLabel("命令预设:", preset_card))
        for label, cmd in [
            ("save-all", "save-all"),
            ("list", "list"),
            ("stop", "stop"),
            ("白名单开", "whitelist on"),
            ("天气晴", "weather clear"),
            ("白天", "time set day"),
        ]:
            b = PushButton(label, preset_card)
            b.setMinimumWidth(70)
            b.clicked.connect(lambda checked, c=cmd: self._send_command(c))
            preset_layout.addWidget(b)
        preset_layout.addStretch()
        layout.addWidget(preset_card)

        layout.addStretch()

    def refresh_theme(self):
        """v3.02.01: 主题切换后重新设置输出区样式。"""
        self._log.setStyleSheet(_log_style())

    # ---------- 补全 ----------
    def _refresh_completer(self):
        cmds = [
            "list", "stop", "save-all", "save-on", "save-off", "save query",
            "say ", "tell ", "msg ",
            "op ", "deop ",
            "kick ", "ban ", "pardon ", "banlist",
            "whitelist on", "whitelist off", "whitelist list",
            "whitelist add ", "whitelist remove ", "whitelist reload",
            "permission add ", "permission remove ", "permission list",
            "gamemode ", "difficulty ", "weather ", "time ",
            "tp ", "give ", "effect ", "summon ",
            "setworldspawn ", "spawnpoint ", "kill ",
            "reload", "help", "version", "about", "me ",
        ]
        self._completer_model.setStringList(cmds)

    # ---------- 着色规则 ----------
    _COLOR_MAP = [
        ("joined the game|connected",                              "#4CAF50"),
        ("left the game|disconnected|timed out|Connection lost",   "#ff7043"),
        ("<[^>]+>",                                                "#ffd700"),
        ("^> ",                                                     "#0DC5D4"),
        ("\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}:\\d+",       "#64b5f6"),
        ("[\\da-f]{8}-[\\da-f]{4}-[\\da-f]{4}-[\\da-f]{4}-[\\da-f]{12}", "#ab47bc"),
        ("^\\[系统\\]|^\\[System\\]",                                "#888"),
        ("\\[.*?\\] .*\\bERROR\\b",                                 "#ff5555"),
        ("\\[.*?\\] .*\\bWARN\\b",                                  "#ffaa00"),
        ("\\[.*?\\] .*\\bINFO\\b",                                  "#aaa"),
        ("\\bERROR\\b|!!!ERROR|\\[ERROR\\]",                       "#ff5555"),
        ("\\bFAIL\\b|FATAL|CRITICAL",                              "#ff5555"),
        ("\\bWARN\\b|\\[WARN\\]|WARNING",                          "#ffaa00"),
        ("\\[SUCCESS\\]|Done\\!|started\\!",                       "#4CAF50"),
    ]

    def _classify_level(self, text: str) -> str:
        """返回日志级别：info/warn/error/chat。"""
        lower = text.lower()
        # 玩家聊天（<Name> 格式）
        if re.search(r"<[^>]+>", text):
            return "chat"
        # 玩家进出
        if re.search(r"joined the game|connected|left the game|disconnected", lower):
            return "info"
        if re.search(r"\bERROR\b|FAIL\b|FATAL|CRITICAL|Exception|Traceback", text, re.IGNORECASE):
            return "error"
        if re.search(r"\bWARN\b|WARNING", text, re.IGNORECASE):
            return "warn"
        return "info"

    def _color_for_line(self, text: str) -> str:
        for pattern, color in self._COLOR_MAP:
            if re.search(pattern, text, re.IGNORECASE):
                return color
        lower = text.lower()
        if any(kw in lower for kw in ("starting minecraft server", "server started", "startup done")):
            return "#4CAF50"
        if any(kw in lower for kw in ("error", "exception", "traceback", "cannot", "failed")):
            return "#ff5555"
        if any(kw in lower for kw in ("warning", "deprecated")):
            return "#ffaa00"
        return "#ccc"

    _PLAYER_JOIN = re.compile(r"Player (?:connected|S(?:p|s)awned):\s+([A-Za-z0-9_]+)", re.I)
    _PLAYER_LEAVE = re.compile(r"Player disconnected:\s+([A-Za-z0-9_]+)", re.I)

    def _append_output(self, text: str, color: str = "#ccc"):
        _write_log(text)
        self._track_player(text)
        # 级别过滤
        level = self._classify_level(text)
        if not self._level_filter.is_enabled(level):
            return
        if color == "#ccc":
            color = self._color_for_line(text)
        # 拼接前缀（时间戳）
        if self._show_timestamps:
            prefix = f'[{datetime.now().strftime("%H:%M:%S")}] '
        else:
            prefix = ""
        # HTML 转义后插入
        safe = html.escape(prefix + text)
        self._log.appendHtml(
            f'<span style="color:{color}; white-space:pre-wrap;">{safe}</span>'
        )
        if self._auto_scroll:
            self._log.moveCursor(QTextCursor.End)
        # RTT 探测
        win = self.window()
        if hasattr(win, "check_lag_response"):
            win.check_lag_response(text)

    def _track_player(self, text: str):
        m = self._PLAYER_JOIN.search(text)
        if m:
            name = m.group(1)
            self._players._known.setdefault(name, time.time())
            self._players.update_players(list(self._players._known.keys()))
            # 玩家加入事件
            from backend.webhook import send_webhook
            send_webhook("player_join", "玩家加入", name)
            return
        m = self._PLAYER_LEAVE.search(text)
        if m:
            name = m.group(1)
            self._players._known.pop(name, None)
            self._players.update_players(list(self._players._known.keys()))
            from backend.webhook import send_webhook
            send_webhook("player_leave", "玩家离开", name)

    # ---------- 崩溃标记 ----------
    def mark_crash(self, restart_count: int, max_retries: int):
        """崩溃重启时调用，在日志顶部插红条。"""
        if not self._crash_marker_visible:
            sep = "─" * 60
            msg = f"{sep}\n⚠️ 服务异常退出，已自动重启 ({restart_count}/{max_retries})\n{sep}"
            self._log.appendHtml(
                f'<span style="color:#ff5555; font-weight:bold; background:#2a1818;">{html.escape(msg)}</span>'
            )
            self._crash_marker_visible = True
            self._log.moveCursor(QTextCursor.End)
        # 通知 Dashboard
        win = self.window()
        if hasattr(win, "dashboard_page"):
            try:
                win.dashboard_page.on_output()  # 重置假死计时
            except Exception:
                pass

    def mark_recovered(self):
        """恢复运行时清理崩溃标记。"""
        if self._crash_marker_visible:
            self._log.appendHtml(
                '<span style="color:#4CAF50; font-weight:bold;">✅ 服务已恢复正常运行</span>'
            )
            self._crash_marker_visible = False
            self._log.moveCursor(QTextCursor.End)

    # ---------- 命令 ----------
    def _send(self):
        cmd = self._cmd_input.text().strip()
        if not cmd:
            return
        self._send_command(cmd)
        self._cmd_input.clear()

    def _send_command(self, cmd: str):
        if not cmd:
            return
        win = self.window()
        if win and win.is_server_running:
            win._server.send_command(cmd)
            self._append_output(f"> {cmd}", "#0DC5D4")
            from backend.webhook import send_webhook
            send_webhook("command_executed", "执行命令", cmd)
        else:
            toast_warning("提示", "服务器未运行", win or self)
        self._cmd_history.append(cmd)
        if len(self._cmd_history) > 100:
            self._cmd_history = self._cmd_history[-100:]
        self._cmd_history_idx = -1

    def _on_auto_scroll_toggle(self, v: bool):
        self._auto_scroll = v
        config_mgr.set("console_auto_scroll", v)

    # ---------- 事件过滤（命令历史 + Tab）----------
    def eventFilter(self, obj, event):
        if obj == self._cmd_input and event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key_Up:
                if self._cmd_history and self._cmd_history_idx < len(self._cmd_history) - 1:
                    self._cmd_history_idx += 1
                    idx = len(self._cmd_history) - 1 - self._cmd_history_idx
                    self._cmd_input.setText(self._cmd_history[idx])
                return True
            if event.key() == Qt.Key_Down:
                if self._cmd_history_idx > 0:
                    self._cmd_history_idx -= 1
                    idx = len(self._cmd_history) - 1 - self._cmd_history_idx
                    self._cmd_input.setText(self._cmd_history[idx])
                elif self._cmd_history_idx == 0:
                    self._cmd_history_idx = -1
                    self._cmd_input.clear()
                return True
        return super().eventFilter(obj, event)

    # ---------- 按钮 ----------
    def _on_start(self):
        win = self.window()
        err = win.start_server()
        if err:
            toast_error("启动失败", err, win)
        else:
            from backend.webhook import send_webhook
            send_webhook("server_started", "服务器启动", "BDS 已启动")

    def _on_stop(self):
        self.window().stop_server()

    def _on_restart(self):
        win = self.window()
        win.stop_server()
        QTimer.singleShot(3000, self._on_start)

    # ---------- 状态更新（由主窗口调用）----------
    def _on_server_started(self):
        _init_log_file()
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._restart_btn.setEnabled(True)
        self._append_output("[系统] 服务器启动中...", "#888")
        self.mark_recovered()

    def _on_server_stopped(self):
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._restart_btn.setEnabled(False)
        self._players.update_players([])
        self._append_output("[系统] 服务器已停止", "#888")
        _close_log_file()

    def _on_status_changed(self, running: bool):
        if running:
            self._status_label.setText("● 运行中")
            self._status_label.setStyleSheet("color: #4CAF50;")
        else:
            self._status_label.setText("● 未运行")
            self._status_label.setStyleSheet("color: #888;")
