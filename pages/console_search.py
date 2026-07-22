# -*- coding: utf-8 -*-
"""
控制台增强 —— 日志搜索 + 导出 + 清屏 + 输出到日志文件。
"""

import os
from datetime import datetime
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QFileDialog
from qfluentwidgets import FluentIcon, InfoBar

from shared.config import LOG_DIR

# ── 控制台搜索栏组件 ──
class ConsoleSearchBar(QHBoxLayout):
    """内嵌搜索条：查找框 + 上一个/下一个 + 导出 + 清屏。"""

    def __init__(self, parent_widget, log_widget):
        super().__init__()
        self.setSpacing(4)
        self._log = log_widget
        self._parent = parent_widget

        self._input = QLineEdit(parent_widget)
        self._input.setPlaceholderText("搜索日志...")
        self._input.setMaximumWidth(180)
        self._input.returnPressed.connect(self._search_next)
        self.addWidget(self._input)

        prev_btn = QPushButton("▲", parent_widget)
        prev_btn.setMaximumWidth(30)
        prev_btn.clicked.connect(self._search_prev)
        self.addWidget(prev_btn)

        next_btn = QPushButton("▼", parent_widget)
        next_btn.setMaximumWidth(30)
        next_btn.clicked.connect(self._search_next)
        self.addWidget(next_btn)

        export_btn = QPushButton("导出", parent_widget)
        export_btn.clicked.connect(self._export)
        self.addWidget(export_btn)

        clear_btn = QPushButton("清屏", parent_widget)
        clear_btn.clicked.connect(self._log.clear)
        self.addWidget(clear_btn)

        self._last_pos = -1

    def _search(self, backward=False):
        text = self._input.text()
        if not text:
            return
        # 从全文查找所有匹配
        plain = self._log.toPlainText()
        if backward:
            start = max(0, self._last_pos - 1)
            pos = plain.rfind(text, 0, start) if start > 0 else plain.rfind(text)
        else:
            pos = plain.find(text, max(0, self._last_pos))
        if pos >= 0:
            self._last_pos = pos + len(text)
            cursor = self._log.textCursor()
            cursor.setPosition(pos)
            cursor.movePosition(cursor.MoveOperation.Right, cursor.MoveMode.KeepAnchor, len(text))
            self._log.setTextCursor(cursor)
            self._log.ensureCursorVisible()
        else:
            self._last_pos = -1
            # 回绕
            if backward:
                pos = plain.rfind(text)
            else:
                pos = plain.find(text)
            if pos >= 0:
                self._last_pos = pos + len(text)
                cursor = self._log.textCursor()
                cursor.setPosition(pos)
                cursor.movePosition(cursor.MoveOperation.Right, cursor.MoveMode.KeepAnchor, len(text))
                self._log.setTextCursor(cursor)
                self._log.ensureCursorVisible()

    def _search_next(self):
        self._search(backward=False)

    def _search_prev(self):
        self._search(backward=True)

    def _export(self):
        default_name = f"console_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        path, _ = QFileDialog.getSaveFileName(
            self._parent, "导出日志",
            os.path.join(LOG_DIR, default_name),
            "Log Files (*.log);;Text (*.txt)",
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self._log.toPlainText())
                InfoBar.success(title="导出完成", content=os.path.basename(path), parent=self._parent, duration=3000)
            except Exception as e:
                InfoBar.error(title="导出失败", content=str(e), parent=self._parent, duration=3000)
