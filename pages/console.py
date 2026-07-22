# -*- coding: utf-8 -*-
"""
控制台页面 —— 服务器输出、命令发送、玩家列表、启停控制。
使用主窗口共享的 ServerProcess，与仪表盘状态同步。
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame,
    QPlainTextEdit,
)
from PySide6.QtGui import QTextCursor
from qfluentwidgets import (
    CardWidget, SubtitleLabel, StrongBodyLabel, BodyLabel, CaptionLabel,
    PrimaryPushButton, PushButton, LineEdit, FluentIcon,
    ToggleButton,
)

from pages.dashboard import wrap_scrollable
from pages.console_search import ConsoleSearchBar
from shared.toast import toast_warning, toast_error
from shared.config import LOG_DIR

# ── 写入日志文件 ──
import os as _os
from datetime import datetime as _dt
from threading import Lock as _Lock

_log_file = None
_log_lock = _Lock()

def _init_log_file():
    global _log_file
    log_path = _os.path.join(LOG_DIR, f"server_{_dt.now().strftime('%Y%m%d_%H%M%S')}.log")
    try:
        _log_file = open(log_path, "w", encoding="utf-8")
    except Exception:
        _log_file = None

def _write_log(text: str):
    global _log_file
    if _log_file:
        try:
            ts = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
            _log_file.write(f"[{ts}] {text}\n")
            _log_file.flush()
        except Exception:
            pass

def _close_log_file():
    global _log_file
    if _log_file:
        try: _log_file.close()
        except Exception: pass
        _log_file = None

# ---------- 暗色日志 ----------
def make_console_log(parent=None, min_height=200):
    log = QPlainTextEdit(parent)
    log.setReadOnly(True)
    if min_height:
        log.setMinimumHeight(min_height)
    log.setMaximumBlockCount(5000)
    log.setStyleSheet("""
        QPlainTextEdit {
            background: #1e1e1e; color: #ccc;
            border: 1px solid #3a3a3a; border-radius: 6px;
            padding: 6px;
            font-family: Consolas, "Microsoft YaHei", monospace;
            font-size: 12px;
        }
    """)
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
        layout.addWidget(self._list_label)

    def update_players(self, names: list[str]):
        self._count_label.setText(str(len(names)))
        self._list_label.setText(", ".join(names) if names else "—")


# ---------- HTML 转义 ----------
import html as _hmod
import re


def _esc(text: str) -> str:
    return _hmod.escape(text)


# ---------- 控制台页面 ----------
class ConsolePage(QWidget):
    """控制台 —— 使用主窗口的共享 ServerProcess。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._auto_scroll = True
        self._cmd_history: list[str] = []
        self._cmd_history_idx = -1
        inner, layout = wrap_scrollable(self, spacing=12)

        # ── 操作栏 ──
        ctrl_card = CardWidget(inner)
        ctrl_layout = QHBoxLayout(ctrl_card)
        ctrl_layout.setContentsMargins(16, 12, 16, 12)
        ctrl_layout.setSpacing(8)

        self._start_btn = PrimaryPushButton("启动服务器", ctrl_card, FluentIcon.PLAY)
        self._start_btn.clicked.connect(self._on_start)
        self._stop_btn = PushButton("停止", ctrl_card, FluentIcon.CANCEL)
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop)
        self._auto_btn = ToggleButton("自动滚动", ctrl_card)
        self._auto_btn.setChecked(True)
        self._auto_btn.toggled.connect(lambda v: setattr(self, "_auto_scroll", v))

        ctrl_layout.addWidget(self._start_btn)
        ctrl_layout.addWidget(self._stop_btn)
        ctrl_layout.addStretch()
        self._status_label = BodyLabel("● 未运行", ctrl_card)
        self._status_label.setStyleSheet("color: #888;")
        ctrl_layout.addWidget(self._status_label)
        ctrl_layout.addStretch()
        ctrl_layout.addWidget(self._auto_btn)
        layout.addWidget(ctrl_card)

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
        # 搜索栏
        search_card = CardWidget(inner)
        search_layout = QHBoxLayout(search_card)
        search_layout.setContentsMargins(12, 6, 12, 6)
        self._search_bar = ConsoleSearchBar(search_card, self._log)
        search_layout.addLayout(self._search_bar)
        layout.addWidget(search_card)

        # 命令输入
        cmd_card = CardWidget(inner)
        cmd_layout = QHBoxLayout(cmd_card)
        cmd_layout.setContentsMargins(16, 10, 16, 10)
        cmd_layout.setSpacing(8)
        self._cmd_input = LineEdit(cmd_card)
        self._cmd_input.setPlaceholderText("输入命令后回车发送（如 list、say <消息>）")
        self._cmd_input.returnPressed.connect(self._send)
        send_btn = PushButton("发送", cmd_card, FluentIcon.SEND)
        send_btn.clicked.connect(self._send)
        cmd_layout.addWidget(self._cmd_input, 1)
        cmd_layout.addWidget(send_btn)
        layout.addWidget(cmd_card)

        # 命令历史（上下箭头）
        self._cmd_input.installEventFilter(self)
        layout.addStretch()

    # ---------- 输出 + 玩家追踪（公开，供主窗口的 ServerProcess 连接）----------
    # 着色规则：具体事件在前，通用兜底在后（优先级=列表顺序）
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

    def _color_for_line(self, text: str) -> str:
        import re
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

    # 玩家事件模式
    _PLAYER_JOIN = re.compile(r"Player (?:connected|S(?:p|s)awned):\s+([A-Za-z0-9_]+)", re.I)
    _PLAYER_LEAVE = re.compile(r"Player disconnected:\s+([A-Za-z0-9_]+)", re.I)
    _PLAYER_LIST = re.compile(r"players online", re.I)

    def _append_output(self, text: str, color: str = "#ccc"):
        # 写入日志文件
        _write_log(text)
        # 玩家追踪
        self._track_player(text)
        if color == "#ccc":
            color = self._color_for_line(text)
        self._log.appendHtml(
            f'<span style="color:{color}; white-space:pre-wrap;">{_esc(text)}</span>'
        )
        if self._auto_scroll:
            self._log.moveCursor(QTextCursor.End)
        win = self.window()
        if hasattr(win, "check_lag_response"):
            win.check_lag_response(text)

    def _track_player(self, text: str):
        """解析 BDS 输出中的玩家事件，更新玩家列表。"""
        import time as _t
        m = self._PLAYER_JOIN.search(text)
        if m:
            name = m.group(1)
            self._players._known.setdefault(name, _t.time())
            self._players.update_players(list(self._players._known.keys()))
            return
        m = self._PLAYER_LEAVE.search(text)
        if m:
            name = m.group(1)
            self._players._known.pop(name, None)
            self._players.update_players(list(self._players._known.keys()))

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

    # ---------- 命令 ----------
    def _send(self):
        cmd = self._cmd_input.text().strip()
        if not cmd:
            return
        win = self.window()
        if win and win.is_server_running:
            win._server.send_command(cmd)
            self._append_output(f"> {cmd}", "#0DC5D4")
        else:
            toast_warning("提示", "服务器未运行", win or self)
        self._cmd_history.append(cmd)
        self._cmd_history_idx = -1
        self._cmd_input.clear()

    # ---------- 按钮（委托给主窗口）----------
    def _on_start(self):
        win = self.window()
        err = win.start_server()
        if err:
            toast_error("启动失败", err, win)

    def _on_stop(self):
        self.window().stop_server()

    # ---------- 状态更新（由主窗口调用）----------
    def _on_server_started(self):
        _init_log_file()
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._append_output("[系统] 服务器启动中...", "#888")

    def _on_server_stopped(self):
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
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
