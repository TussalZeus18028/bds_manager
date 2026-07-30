# -*- coding: utf-8 -*-
"""
Toast 通知 —— 双模式：原版自定义 Widget（圆角+滑入+排队） 或 QFluentWidgets InfoBar（现代）。

用法:
    from shared.toast import toast_info, toast_success, toast_warning, toast_error

    toast_success("操作完成", "世界已成功备份", parent_widget)
    toast_error("启动失败", "找不到 bedrock_server.exe", parent_widget)
"""

from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QPoint, QTimer, QEvent
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QBitmap

from qfluentwidgets import InfoBar, InfoBarIcon, InfoBarPosition, isDarkTheme

from shared.config import config_mgr
from shared.theme import theme_palette

# ══════════════════════════════════════════
#  原版 ToastNotification（完全照抄旧 PyQt5 版，适配 PySide6）
# ══════════════════════════════════════════

class ToastNotification(QWidget):
    """现代化右上角弹窗通知（主窗口内嵌，自动裁剪）"""
    _instances: list["ToastNotification"] = []

    def __init__(self, parent, title, message, level="info", duration=4000):
        super().__init__(parent)
        self._window = parent
        self._title = title
        self._message = message
        self._level = level
        self.raise_()

        # v3.04.01: 使用 ThemePalette 统一管理颜色
        p = theme_palette()
        accent_hex = p.level_accent(level)
        bg_hex = p.level_bg(level)
        msg_color = p.toast_msg_color()

        self._bg = QColor(bg_hex)
        self._accent = QColor(accent_hex)
        self._radius = 12

        self.setFixedWidth(320)

        icon_text = {"error": "\u274c", "warning": "\u26a0\ufe0f", "success": "\u2705", "info": "\u2139\ufe0f"}.get(level, "\u2139\ufe0f")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        icon_label = QLabel(icon_text)
        icon_label.setStyleSheet("font-size:18px; background:transparent;")
        layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        title_label = QLabel(title)
        title_label.setStyleSheet(f"font-weight:bold; font-size:12px; color:{accent_hex}; background:transparent;")
        msg_label = QLabel(message)
        msg_label.setWordWrap(True)
        msg_label.setStyleSheet(f"font-size:11px; color:{msg_color}; background:transparent;")
        text_layout.addWidget(title_label)
        text_layout.addWidget(msg_label)
        layout.addLayout(text_layout, 1)

        self.setStyleSheet(f"ToastNotification {{ background-color: {bg_hex}; }}")

        self.adjustSize()
        h = max(60, self.sizeHint().height() + 10)
        self.setFixedHeight(h)
        self._apply_mask()

        self._calc_position()
        self._start_slide_in()
        self.show()
        self._clicked = False
        self.mousePressEvent = lambda e: self._dismiss()
        QTimer.singleShot(duration, self._dismiss)
        ToastNotification._instances.append(self)
        parent.installEventFilter(self)

    def _apply_mask(self):
        mask = QBitmap(self.size())
        mask.fill(Qt.GlobalColor.color0)
        p = QPainter(mask)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(Qt.GlobalColor.color1)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(self.rect(), self._radius, self._radius)
        p.end()
        self.setMask(mask)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(self._bg)
        p.setPen(QPen(self._accent, 2))
        r = self.rect().adjusted(1, 1, -1, -1)
        p.drawRoundedRect(r, self._radius, self._radius)

    def _calc_position(self):
        w = self._window
        # v3.02.01：垂直起点在 titleBar 下方（48px），水平靠右偏移 12px，
        # 避开 titleBar 右上角的最小化/最大化/关闭按钮。
        offset_y = 56
        # 如果窗口是 FluentWindow 且有 titleBar，从 titleBar 下方开始
        tb = getattr(w, "titleBar", None)
        if tb is not None:
            offset_y = tb.height() + 8
        for inst in ToastNotification._instances:
            offset_y += inst.height() + 8
        x = w.width() - self.width() - 12
        y = offset_y
        self.move(x, y)

    def _start_slide_in(self):
        w = self._window
        self._anim_in = QPropertyAnimation(self, b"pos")
        self._anim_in.setDuration(300)
        self._anim_in.setStartValue(QPoint(w.width(), self.y()))
        self._anim_in.setEndValue(self.pos())
        self._anim_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim_in.start()

    def _dismiss(self):
        if self._clicked:
            return
        self._clicked = True
        self._anim_out = QPropertyAnimation(self, b"pos")
        self._anim_out.setDuration(250)
        self._anim_out.setStartValue(self.pos())
        self._anim_out.setEndValue(QPoint(self._window.width(), self.y()))
        self._anim_out.setEasingCurve(QEasingCurve.Type.InCubic)
        self._anim_out.finished.connect(self._cleanup)
        self._anim_out.start()
        # v3.02.01 fix: 同步在 _enqueue 时已经做了，dismiss 不再重复
        # （否则同一条 toast 在通知中心会出现两次）

    def _cleanup(self):
        if self in ToastNotification._instances:
            ToastNotification._instances.remove(self)
            self._window.removeEventFilter(self)
        self.deleteLater()
        for inst in ToastNotification._instances:
            inst._calc_position()

    def eventFilter(self, obj, event):
        if obj == self._window and event.type() in (QEvent.Type.Resize, QEvent.Type.Move):
            for inst in ToastNotification._instances:
                inst._calc_position()
        return super().eventFilter(obj, event)


# ══════════════════════════════════════════
#  排队系统（鱼贯而入）
# ══════════════════════════════════════════

class ToastQueue:
    """v3.02.02: 封装 toast 队列状态，避免模块级全局变量。"""

    def __init__(self):
        self._parent = None
        self._queue: list[tuple] = []
        self._timer_active = False

    def set_parent(self, parent):
        self._parent = parent

    def enqueue(self, title, msg, level, duration):
        self._queue.append((title, msg, level, duration))
        if not self._timer_active:
            self._timer_active = True
            QTimer.singleShot(50, self._flush)
        _sync_to_notification_center(level, title, msg)

    def _flush(self):
        if self._queue and self._parent:
            args = self._queue.pop(0)
            ToastNotification(self._parent, *args)
        if self._queue:
            if self._parent is None:
                try:
                    from main import _MAIN_WINDOW_REF
                    self._parent = _MAIN_WINDOW_REF[0]
                except (ImportError, IndexError, RuntimeError):
                    self._timer_active = False
                    return
                if self._parent is None:
                    self._timer_active = False
                    return
            delay = config_mgr.get("toast_queue_delay") or 200
            QTimer.singleShot(max(delay, 0), self._flush)
        else:
            self._timer_active = False


_TOAST_Q = ToastQueue()


def _set_toast_parent(parent):
    _TOAST_Q.set_parent(parent)


# ══════════════════════════════════════════
#  公开 API —— 根据 config 选择模式
# ══════════════════════════════════════════

def _use_original() -> bool:
    return config_mgr.get("toast_style", "original") == "original"


def _get_duration(level: str) -> int:
    key_map = {"error": "toast_duration_error", "warning": "toast_duration_warning",
               "success": "toast_duration_success", "info": "toast_duration_info"}
    return config_mgr.get(key_map.get(level, "toast_duration_info"), 3000)


def _show_modern(icon, title: str, content: str, parent, duration=None, level="info", closable=True):
    if duration is None:
        duration = _get_duration(level)
    # v3.02.01：改用 TOP（顶部居中），避开 titleBar 右上角的最小化/最大化/关闭按钮
    w = InfoBar.new(icon, title, content, parent=parent, position=InfoBarPosition.TOP,
                    duration=duration, isClosable=closable)
    w.setMinimumWidth(300)
    w.setMaximumWidth(420)
    w.titleLabel.setStyleSheet("font-weight: bold; font-size: 13px;")
    w.contentLabel.setStyleSheet("font-size: 12px;")
    w.show()
    # v3.02.01：同步进通知中心（让抽屉能记录所有 toast）
    _sync_to_notification_center(level, title, content)
    return w


def toast_info(title: str, content: str, parent, duration: int | None = None, closable: bool = True):
    if _use_original():
        _TOAST_Q.set_parent(parent)
        _TOAST_Q.enqueue(title, content, "info", duration or _get_duration("info"))
    else:
        _show_modern(InfoBarIcon.INFORMATION, title, content, parent, duration, "info", closable)
    _log_to_terminal("INFO", title, content)


def toast_success(title: str, content: str, parent, duration: int | None = None, closable: bool = True):
    if _use_original():
        _TOAST_Q.set_parent(parent)
        _TOAST_Q.enqueue(title, content, "success", duration or _get_duration("success"))
    else:
        _show_modern(InfoBarIcon.SUCCESS, title, content, parent, duration, "success", closable)
    _log_to_terminal("OK  ", title, content)


def toast_warning(title: str, content: str, parent, duration: int | None = None, closable: bool = True):
    if _use_original():
        _TOAST_Q.set_parent(parent)
        _TOAST_Q.enqueue(title, content, "warning", duration or _get_duration("warning"))
    else:
        _show_modern(InfoBarIcon.WARNING, title, content, parent, duration, "warning", closable)
    _log_to_terminal("WARN", title, content)


def toast_error(title: str, content: str, parent, duration: int | None = None, closable: bool = True):
    if _use_original():
        _TOAST_Q.set_parent(parent)
        _TOAST_Q.enqueue(title, content, "error", duration or _get_duration("error"))
    else:
        _show_modern(InfoBarIcon.ERROR, title, content, parent, duration, "error", closable)
    _log_to_terminal("ERR ", title, content)


def _log_to_terminal(level: str, title: str, content: str):
    import sys
    target = sys.stderr if level in ("ERR ", "WARN") else sys.stdout
    print(f"[TOAST][{level}] {title}: {content}", file=target, flush=True)


# ══════════════════════════════════════════
#  通知中心同步（v3.02.01 新增）
# ══════════════════════════════════════════
def _sync_to_notification_center(level: str, title: str, content: str):
    """把 toast 通知同步进通知中心（抽屉能记录所有 toast）。"""
    try:
        from backend.notifications import _STORE, get_bus
        _STORE.add_raw(level, "toast", title, content)
        bus = get_bus()
        bus.notification_added.emit(None)
        bus.unread_count_changed.emit(_STORE.get_unread_count())
    except (AttributeError, RuntimeError):
        pass  # 通知总线未初始化
