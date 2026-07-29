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
import re

# ── ANSI → HTML 转换 ──
_ANSI_RE = re.compile(r'\x1b\[([0-9;]*)m')
_ANSI_COLORS = {
    "30": "#000", "31": "#f55", "32": "#5f5", "33": "#ff5",
    "34": "#55f", "35": "#f5f", "36": "#5ff", "37": "#fff",
    "90": "#888", "91": "#f88", "92": "#8f8", "93": "#ff8",
    "94": "#88f", "95": "#f8f", "96": "#8ff", "97": "#fff",
}

def _ansi_to_html(text: str) -> str:
    """将 ANSI 转义序列转换为 HTML span 标签。裸文本其余部分 html.escape。"""
    parts = []
    stack = []
    last = 0
    for m in _ANSI_RE.finditer(text):
        # 未匹配的前缀
        if m.start() > last:
            parts.append(html.escape(text[last:m.start()]))
        codes = m.group(1).split(";") if m.group(1) else ["0"]
        style = ""
        i = 0
        while i < len(codes):
            c = codes[i]
            if c == "0":
                stack = []
            elif c == "1":
                style += "font-weight:bold;"
            elif c == "4":
                style += "text-decoration:underline;"
            elif c == "38" and i + 2 < len(codes) and codes[i + 1] == "2":
                # 24bit 前景色
                r, g, b = codes[i + 2], codes[i + 3] if i + 3 < len(codes) else "0", codes[i + 4] if i + 4 < len(codes) else "0"
                style += f"color:rgb({r},{g},{b});"
                i += 4
            elif c == "48" and i + 2 < len(codes) and codes[i + 1] == "2":
                # 24bit 背景色
                r, g, b = codes[i + 2], codes[i + 3] if i + 3 < len(codes) else "0", codes[i + 4] if i + 4 < len(codes) else "0"
                style += f"background:rgb({r},{g},{b});"
                i += 4
            elif c in _ANSI_COLORS:
                style += f"color:{_ANSI_COLORS[c]};"
            elif c in ("39",):  # default fg
                style += "color:inherit;"
            elif c in ("49",):  # default bg
                style += "background:inherit;"
            i += 1
        if style:
            stack.append(style)
            parts.append(f'<span style="{style}">')
        else:
            # 关闭标签
            for _ in stack:
                parts.append("</span>")
            stack = []
        last = m.end()
    # 尾部
    if last < len(text):
        parts.append(html.escape(text[last:]))
    # 关闭所有
    for _ in stack:
        parts.append("</span>")
    return "".join(parts)
import time
from datetime import datetime
from threading import Lock

from PySide6.QtCore import Qt, QTimer, QStringListModel, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame,
    QPlainTextEdit, QCompleter,
)
from PySide6.QtGui import QTextCursor, QTextCharFormat, QColor
from qfluentwidgets import (
    CardWidget, SubtitleLabel, StrongBodyLabel, BodyLabel, CaptionLabel,
    PrimaryPushButton, PushButton, LineEdit, FluentIcon,
    ToggleButton, CheckBox, ComboBox, isDarkTheme,
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
    except OSError:
        _log_file = None


_log_write_count = 0


def _write_log(text: str):
    global _log_file, _log_write_count
    if _log_file is None:
        return
    try:
        ts = datetime.now().strftime("%H:%M:%S")
        with _log_lock:
            _log_file.write(f"[{ts}] {text}\n")
            # v3.03.00: 每 50 行 flush 一次，避免每条输出都同步写磁盘
            _log_write_count += 1
            if _log_write_count % 50 == 0:
                _log_file.flush()
    except OSError as e:
        logger.debug("控制台日志写入磁盘失败: %s", e)


def _close_log_file():
    global _log_file, _log_write_count
    if _log_file:
        try:
            _log_file.flush()
            _log_file.close()
        except OSError:
            pass  # close 失败不影响
        _log_file = None
    _log_write_count = 0


# ── 暗色日志 ──
def _log_style() -> str:
    """v3.02.01: 控制台日志 QPlainTextEdit 主题感知样式。"""
    size = config_mgr.get("font_size", 12)
    if isDarkTheme():
        return f"""
            QPlainTextEdit {{ background:#1e1e1e; color:#ccc; border:1px solid #3a3a3a;
                border-radius:6px; padding:6px; font-family:Consolas,"Microsoft YaHei",monospace; font-size:{size}px; }}
        """
    return f"""
        QPlainTextEdit {{ background:#fafafa; color:#1a1a1a; border:1px solid #d0d0d0;
            border-radius:6px; padding:6px; font-family:Consolas,"Microsoft YaHei",monospace; font-size:{size}px; }}
    """


def make_console_log(parent=None, min_height=200):
    log = QPlainTextEdit(parent)
    log.setReadOnly(True)
    if min_height:
        log.setMinimumHeight(min_height)
    max_lines = config_mgr.get("console_max_lines", 5000)
    # v3.02.02: 截断前保存快照到 logs/console_snapshot.log
    log.blockCountChanged.connect(lambda new: _dump_snapshot_if_full(log, new, max_lines))
    log.setMaximumBlockCount(max_lines)
    log.setStyleSheet(_log_style())
    # v3.02.02: 右键菜单
    log.setContextMenuPolicy(Qt.CustomContextMenu)
    log.customContextMenuRequested.connect(lambda pos: _console_context_menu(log, pos))
    return log


def _console_context_menu(log, pos):
    """v3.02.02: 控制台右键菜单。"""
    from PySide6.QtWidgets import QMenu
    from PySide6.QtGui import QAction
    menu = QMenu(log)
    a_copy = QAction("复制选中", log)
    a_copy.triggered.connect(log.copy)
    a_select = QAction("全选", log)
    a_select.triggered.connect(log.selectAll)
    a_clear = QAction("清屏", log)
    a_clear.triggered.connect(log.clear)
    menu.addAction(a_copy)
    menu.addAction(a_select)
    menu.addSeparator()
    menu.addAction(a_clear)
    menu.exec(log.mapToGlobal(pos))


_snapshot_dumped = False  # 每次会话只 dump 一次避免磁盘轰炸


def _dump_snapshot_if_full(log, new_count: int, limit: int):
    """v3.02.02: 达到上限时，截断前保存日志快照。"""
    global _snapshot_dumped
    if new_count >= limit and not _snapshot_dumped:
        _snapshot_dumped = True
        try:
            path = os.path.join(LOG_DIR, f"console_snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
            with open(path, "w", encoding="utf-8") as f:
                f.write(log.toPlainText()[-100000:])
        except OSError as e:
            logger.debug("控制台快照写入失败: %s", e)


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

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(CaptionLabel("过滤:", self))
        layout.addSpacing(4)
        self._filters: dict[str, CheckBox] = {}
        for label, key in [("信息", "info"), ("警告", "warn"),
                           ("错误", "error"), ("聊天", "chat")]:
            cb = CheckBox(label, self)
            cb.setChecked(True)
            cb.toggled.connect(lambda: self.changed.emit())
            self._filters[key] = cb
            layout.addWidget(cb)
        self._filter_count = CaptionLabel("", self)
        layout.addWidget(self._filter_count)
        self._show_all = PushButton("显示全部", self)
        self._show_all.setFixedWidth(72)
        self._show_all.clicked.connect(self._show_all_filters)
        self._show_all.hide()
        layout.addWidget(self._show_all)
        layout.addStretch()

    def _show_all_filters(self):
        for cb in self._filters.values():
            cb.setChecked(True)
        self._show_all.hide()

    def is_enabled(self, level: str) -> bool:
        return self._filters.get(level, CheckBox(self)).isChecked()

    def levels_enabled(self) -> set[str]:
        return {k for k, cb in self._filters.items() if cb.isChecked()}

    def set_visible_count(self, visible: int, total: int):
        if visible < total:
            self._filter_count.setText(f"({visible}/{total})")
            self._show_all.show()
        else:
            self._filter_count.setText("")
            self._show_all.hide()


# ---------- 控制台页面 ----------
class ConsolePage(QWidget):
    """控制台 —— v3.1。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._auto_scroll = config_mgr.get("console_auto_scroll", True)
        self._cmd_history: list[str] = config_mgr.get("cmd_history", [])
        self._cmd_history_idx = -1
        self._crash_marker_visible = False
        self._show_timestamps = config_mgr.get("console_show_timestamps", True)
        inner, layout, _scroll = wrap_scrollable(self, spacing=12)

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
        self._stop_btn.setMinimumWidth(60)

        # 服务器类型选择
        self._server_type = ComboBox(ctrl_card)
        self._server_type.addItems(["纯 BDS", "BDS + LL"])
        self._server_type.currentIndexChanged.connect(self._on_server_type_changed)
        self._server_type.setMinimumWidth(100)  # 先占位

        # 延迟设置选中项：确保在 SettingsPage _connect_auto_save 之后执行
        def _apply_saved_type():
            stype = config_mgr.get("server_type", "bds")
            self._server_type.blockSignals(True)
            self._server_type.setCurrentIndex(1 if stype == "ll" else 0)
            self._server_type.blockSignals(False)
            self._start_btn.setText("启动 (LL)" if stype == "ll" else "启动服务器")
        QTimer.singleShot(50, _apply_saved_type)

        self._restart_btn = PushButton("重启", ctrl_card, FluentIcon.SYNC)
        self._restart_btn.setEnabled(False)
        self._restart_btn.clicked.connect(self._on_restart)
        self._auto_btn = ToggleButton("自动滚动", ctrl_card)
        self._auto_btn.setChecked(self._auto_scroll)
        self._auto_btn.toggled.connect(self._on_auto_scroll_toggle)
        self._auto_btn.setMinimumWidth(90)

        ctrl_layout.addWidget(self._start_btn)
        ctrl_layout.addWidget(self._stop_btn)
        ctrl_layout.addWidget(self._server_type)
        ctrl_layout.addWidget(self._restart_btn)
        ctrl_layout.addStretch()

        self._folder_btn = PushButton("目录", ctrl_card, FluentIcon.FOLDER)
        self._folder_btn.clicked.connect(self._open_server_dir)
        ctrl_layout.addWidget(self._folder_btn)

        self._status_label = BodyLabel("未运行", ctrl_card)
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
        preset_layout.addWidget(CaptionLabel("命令:", preset_card))
        self._preset_combo = ComboBox(preset_card)
        self._preset_combo.setMinimumWidth(120)
        for label, cmd in [
            ("保存世界 - save hold", "save hold"),
            ("查询保存 - save query", "save query"),
            ("恢复保存 - save resume", "save resume"),
            ("玩家列表 - list", "list"),
            ("停服 - stop", "stop"),
            ("白名单开 - whitelist on", "whitelist on"),
            ("天气晴 - weather clear", "weather clear"),
            ("白天 - time set day", "time set day"),
        ]:
            self._preset_combo.addItem(label, cmd)
        self._preset_combo.currentIndexChanged.connect(
            lambda idx: self._send_command(self._preset_combo.currentData()) if idx >= 0 else None)
        self._preset_combo.setCurrentIndex(-1)
        self._preset_combo.setPlaceholderText("选择预设命令...")
        preset_layout.addWidget(self._preset_combo)
        preset_layout.addStretch()
        layout.addWidget(preset_card)

        layout.addStretch()

    def refresh_theme(self):
        """v3.02.01: 主题切换后重新设置输出区+状态标签样式。"""
        self._log.setStyleSheet(_log_style())
        # 刷新状态标签颜色
        hint = "#888" if isDarkTheme() else "#666"
        if "未运行" in self._status_label.text() or "离线" in self._status_label.text():
            self._status_label.setStyleSheet(f"color: {hint};")

    # ---------- 补全 ----------
    def _refresh_completer(self):
        cmds = [
            "list", "stop",
            # BDS 存档
            "save hold", "save query", "save resume",
            # 聊天
            "say ", "tell ", "msg ", "w ",
            # 权限
            "op ", "deop ",
            "kick ", "ban ", "pardon ", "banlist",
            "whitelist on", "whitelist off", "whitelist list",
            "whitelist add ", "whitelist remove ", "whitelist reload",
            "permission add ", "permission remove ", "permission list",
            # 游戏规则
            "gamemode ", "difficulty ", "weather ", "time ",
            "alwaysday ", "gamerule ",
            # 传送 / 实体
            "tp ", "give ", "effect ", "summon ",
            "spreadplayers ", "setworldspawn ", "spawnpoint ",
            "kill ", "clear ", "enchant ", "xp ", "replaceitem ",
            "ride ", "event ", "damage ",
            # 常加载区块
            "tickingarea add ", "tickingarea remove ", "tickingarea list",
            # 计分板
            "scoreboard objectives add ", "scoreboard objectives remove ",
            "scoreboard objectives list", "scoreboard players ",
            # 结构
            "structure save ", "structure load ", "structure delete ",
            # 信息 / 管理
            "reload", "help", "version", "about", "me ",
            "title ", "titleraw ",
            "ability ", "stopsound ", "setmaxplayers ",
            "transferserver ", "checkspawnpoint ", "clearspawnpoint",
            "schedule ", "camerashake ", "fog ", "music ", "playanimation ",
        ]
        self._completer_model.setStringList(cmds)

    # ── 着色规则（两套：暗色 / 浅色，第一值暗色，第二值浅色）──
    _COLOR_MAP = [
        ("joined the game|connected",                              "#4CAF50", "#388E3C"),
        ("left the game|disconnected|timed out|Connection lost",   "#ff7043", "#E64A19"),
        ("<[^>]+>",                                                "#ffd700", "#b8860b"),
        ("^> ",                                                     "#0DC5D4", "#00838F"),
        ("\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}:\\d+",       "#64b5f6", "#1976D2"),
        ("[\\da-f]{8}-[\\da-f]{4}-[\\da-f]{4}-[\\da-f]{4}-[\\da-f]{12}", "#ab47bc", "#8E24AA"),
        ("^\\[系统\\]|^\\[System\\]",                                "#888",     "#555"),
        ("\\[.*?\\] .*\\bERROR\\b",                                 "#ff5555", "#D32F2F"),
        ("\\[.*?\\] .*\\bWARN\\b",                                  "#ffaa00", "#E65100"),
        ("\\[.*?\\] .*\\bINFO\\b",                                  "#aaa",     "#666"),
        ("\\bERROR\\b|!!!ERROR|\\[ERROR\\]",                       "#ff5555", "#D32F2F"),
        ("\\bFAIL\\b|FATAL|CRITICAL",                              "#ff5555", "#D32F2F"),
        ("\\bWARN\\b|\\[WARN\\]|WARNING",                          "#ffaa00", "#E65100"),
        ("\\[SUCCESS\\]|Done\\!|started\\!",                       "#4CAF50", "#388E3C"),
    ]

    @classmethod
    def _resolve_color(cls, dark: str, light: str) -> str:
        """按当前主题返回暗色或浅色值。"""
        return dark if isDarkTheme() else light

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
        for pattern, dark, light in self._COLOR_MAP:
            if re.search(pattern, text, re.IGNORECASE):
                return self._resolve_color(dark, light)
        lower = text.lower()
        if any(kw in lower for kw in ("starting minecraft server", "server started", "startup done")):
            return "#4CAF50"
        if any(kw in lower for kw in ("error", "exception", "traceback", "cannot", "failed")):
            return "#ff5555"
        if any(kw in lower for kw in ("warning", "deprecated")):
            return "#ffaa00"
        return "#ccc" if isDarkTheme() else "#555"

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
        # ANSI → HTML + 拼接前缀
        if self._show_timestamps:
            prefix = f'[{datetime.now().strftime("%H:%M:%S")}] '
        else:
            prefix = ""
        content = _ansi_to_html(prefix + text) if "\x1b" in text else html.escape(prefix + text)
        self._log.appendHtml(
            f'<span style="color:{color}; white-space:pre-wrap;">{content}</span>'
        )
        if self._auto_scroll:
            self._log.moveCursor(QTextCursor.End)
        # RTT 探测
        win = self.window()
        if hasattr(win, "check_lag_response"):
            try:
                win.check_lag_response(text)
            except (AttributeError, RuntimeError):
                pass  # check_lag_response 不可用

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
            except (AttributeError, RuntimeError):
                pass  # 仪表盘未加载或已被销毁

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
        cmd_lower = cmd.strip().lower()
        if not win.is_server_running:
            if cmd_lower == "start":
                from backend.server_lifecycle import start_server
                start_server(win)
                self._append_output(f"> start（启动服务器）", "#0DC5D4")
                self._save_cmd_history()
                self._cmd_input.clear()
                return
            toast_warning("提示", "服务器未运行，输入 start 可启动", win or self)
            self._cmd_history.append(cmd)
            self._save_cmd_history()
            return
        win._server.send_command(cmd)
        self._append_output(f"> {cmd}", "#0DC5D4")
        from backend.webhook import send_webhook
        send_webhook("command_executed", "执行命令", cmd)
        self._cmd_history.append(cmd)
        self._save_cmd_history()
        self._cmd_history_idx = -1

    def _save_cmd_history(self):
        """持久化最近 50 条命令历史。"""
        if len(self._cmd_history) > 100:
            self._cmd_history = self._cmd_history[-100:]
        config_mgr.set("cmd_history", self._cmd_history[-50:])
        config_mgr.save()

    def _on_auto_scroll_toggle(self, v: bool):
        self._auto_scroll = v
        config_mgr.set("console_auto_scroll", v)
        config_mgr.save()

    def _open_server_dir(self):
        from shared.config import get_context
        import webbrowser
        ctx = get_context()
        webbrowser.open(ctx.server_dir)

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
    def _on_server_type_changed(self, idx):
        stype = "ll" if idx == 1 else "bds"
        config_mgr.set("server_type", stype)
        config_mgr.save()
        # 刷新 ServerContext，所有 ctx.* 路径跟随切换
        from shared.config import refresh_context_from_config
        refresh_context_from_config()
        # 更新按钮文字
        self._start_btn.setText("启动 (LL)" if stype == "ll" else "启动服务器")

    def _on_start(self):
        win = self.window()
        err = win.start_server()
        if err:
            toast_error("启动失败", err, win)
        else:
            from backend.webhook import send_webhook
            send_webhook("server_started", "服务器启动", "BDS 已启动")

    def _on_stop(self):
        win = self.window()
        if win.is_server_running:
            from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel
            from qfluentwidgets import MessageBox
            if MessageBox("确认停止", "确定要停止服务器吗？", win).exec():
                win.stop_server()
            return

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
            self._status_label.setText("运行中")
            self._status_label.setStyleSheet("color: #4CAF50;")
        else:
            self._status_label.setText("未运行")
            hint = "#888" if isDarkTheme() else "#666"
            self._status_label.setStyleSheet(f"color: {hint};")
