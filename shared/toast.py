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

        # v3.02.01 fix: 主题感知 —— 浅色主题用浅灰底+深色字，避免视觉割裂
        if isDarkTheme():
            colors = {
                "error":   ("#ff7777", "#2a181a"),
                "warning": ("#ffcc66", "#2a2218"),
                "success": ("#66dd88", "#182a1e"),
                "info":    ("#77aaff", "#181e2a"),
            }
            title_fg_extra = ""  # 暗色背景下用 accent 已够亮
            msg_color = "#ccddee"
        else:
            colors = {
                "error":   ("#c03030", "#fdecec"),
                "warning": ("#b86a00", "#fdf3e3"),
                "success": ("#2a8a4a", "#e6f5ec"),
                "info":    ("#1c66c0", "#e6f0fa"),
            }
            msg_color = "#333333"
        accent_hex, bg_hex = colors.get(level, colors["info"])
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

_queued_parent = None
_queue: list[tuple] = []
_timer_active = False


def _set_toast_parent(parent):
    global _queued_parent
    _queued_parent = parent


def _flush_queue():
    global _queue, _timer_active
    if _queue and _queued_parent:
        args = _queue.pop(0)
        ToastNotification(_queued_parent, *args)
    if _queue:
        delay = config_mgr.get("toast_queue_delay") or 200
        QTimer.singleShot(max(delay, 0), _flush_queue)
    else:
        _timer_active = False


def _enqueue(title, msg, level, duration):
    global _queue, _timer_active
    _queue.append((title, msg, level, duration))
    if not _timer_active:
        _timer_active = True
        QTimer.singleShot(50, _flush_queue)
    # v3.02.01 fix: 入队时就同步进通知中心，不要等 4 秒后 _dismiss
    # （否则用户看到的瞬间抽屉是空的，体验割裂）
    _sync_to_notification_center(level, title, msg)


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
        _set_toast_parent(parent)
        _enqueue(title, content, "info", duration or _get_duration("info"))
    else:
        _show_modern(InfoBarIcon.INFORMATION, title, content, parent, duration, "info", closable)
    _log_to_terminal("INFO", title, content)


def toast_success(title: str, content: str, parent, duration: int | None = None, closable: bool = True):
    if _use_original():
        _set_toast_parent(parent)
        _enqueue(title, content, "success", duration or _get_duration("success"))
    else:
        _show_modern(InfoBarIcon.SUCCESS, title, content, parent, duration, "success", closable)
    _log_to_terminal("OK  ", title, content)


def toast_warning(title: str, content: str, parent, duration: int | None = None, closable: bool = True):
    if _use_original():
        _set_toast_parent(parent)
        _enqueue(title, content, "warning", duration or _get_duration("warning"))
    else:
        _show_modern(InfoBarIcon.WARNING, title, content, parent, duration, "warning", closable)
    _log_to_terminal("WARN", title, content)


def toast_error(title: str, content: str, parent, duration: int | None = None, closable: bool = True):
    if _use_original():
        _set_toast_parent(parent)
        _enqueue(title, content, "error", duration or _get_duration("error"))
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
    """把 toast 通知同步进通知中心（抽屉能记录所有 toast）。

    重要：这是"可选"的——如果 backend.notifications 还没初始化好（比如极早期启动时），
    静默忽略，不让 toast 流程崩。
    """
    try:
        from backend.notifications import notify as _notify
        _notify(level, "toast", title, content)
    except Exception:
        pass
