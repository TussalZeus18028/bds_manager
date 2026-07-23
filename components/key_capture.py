# -*- coding: utf-8 -*-
"""
键位录制控件（v3.02.00 新增）。

双击进入录制模式 → 监听 keyPressEvent → 捕获下一个键组合（含修饰键）。
Esc 取消录制。

信号：
    capture_completed(str)  —— 捕获完成，参数为人类可读键位字符串（如 "Ctrl+R"）
"""

from PySide6.QtCore import Qt, Signal, QKeyCombination
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtWidgets import QPushButton
from qfluentwidgets import isDarkTheme


class KeyCaptureButton(QPushButton):
    """双击进入录制模式，捕获下一个键组合。"""

    capture_completed = Signal(str)  # QKeySequence.toString()

    def __init__(self, initial: str = "", parent=None):
        super().__init__(initial or "(未设置)", parent)
        self._initial = initial
        self._recording = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(28)
        self.setMinimumWidth(130)  # v3.02.01: 加宽以容纳 "Ctrl+Shift+L" 等长键位
        self._apply_style()
        # 双击进入录制
        self.mouseDoubleClickEvent = lambda e: self._start_recording()

    def set_text(self, key: str):
        """外部更新键位显示（不触发录制）。"""
        self._initial = key
        if not self._recording:
            self.setText(key or "(未设置)")

    def _apply_style(self):
        # v3.02.01 fix: 主题感知颜色（之前硬编码暗色，浅色主题下字看不见）
        if isDarkTheme():
            bg, hover, border, fg = "#2a2a2a", "#353535", "#444", "#ccddee"
        else:
            bg, hover, border, fg = "#fafafa", "#f0f0f0", "#bbb", "#1a1a1a"
        self.setStyleSheet(f"""
            QPushButton {{
                background: {bg}; color: {fg};
                border: 1px solid {border}; border-radius: 4px;
                padding: 2px 12px; font-family: "Consolas", "Microsoft YaHei";
                font-size: 11px;
            }}
            QPushButton:hover {{ background: {hover}; }}
        """)

    def _apply_recording_style(self):
        self.setStyleSheet("""
            QPushButton {
                background: #0DC5D4; color: #ffffff;
                border: 1px solid #0DC5D4; border-radius: 4px;
                padding: 2px 12px; font-weight: bold;
                font-family: "Consolas", "Microsoft YaHei"; font-size: 11px;
            }
        """)

    def _start_recording(self):
        if self._recording:
            return
        self._recording = True
        self.setText("按下任意键… Esc 取消")
        self._apply_recording_style()
        self.setFocus(Qt.OtherFocusReason)

    def _stop_recording(self, key: str = ""):
        self._recording = False
        self.setText(key or self._initial or "(未设置)")
        self._apply_style()

    def keyPressEvent(self, event: QKeyEvent):
        if not self._recording:
            super().keyPressEvent(event)
            return
        # Esc 取消
        if event.key() == Qt.Key_Escape and event.modifiers() == Qt.NoModifier:
            self._stop_recording()
            event.accept()
            return
        # 忽略单独修饰键
        if event.key() in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta):
            return
        # 构造 QKeySequence 并发射
        # v3.02.01 fix: PySide6 中 Qt.KeyboardModifier 是 Flag（非 IntFlag），
        # `event.modifiers() | event.key()` 结果是 KeyboardModifier 类型，传给
        # QKeySequence(int) 会报"called with wrong argument types"。
        # 正确做法是用 QKeyCombination 显式组合 mod + key
        kc = QKeyCombination(event.modifiers(), Qt.Key(event.key()))
        seq = QKeySequence(kc)
        key_str = seq.toString()
        if key_str:
            self.capture_completed.emit(key_str)
            self._stop_recording(key_str)
        event.accept()