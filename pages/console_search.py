# -*- coding: utf-8 -*-
"""
控制台增强 —— 日志搜索 + 导出 + 清屏 + 输出到日志文件。

v3.1 改进：
- 多匹配高亮（QTextEdit.ExtraSelection）
- 全部高亮按钮
- 区分大小写 / 全字匹配开关
"""

import os
from datetime import datetime
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCharFormat, QColor, QTextCursor
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QFileDialog, QCheckBox
from qfluentwidgets import FluentIcon, InfoBar

from shared.config import LOG_DIR


class ConsoleSearchBar(QHBoxLayout):
    """内嵌搜索条：查找框 + 上一个/下一个 + 高亮全部 + 导出 + 清屏。"""

    def __init__(self, parent_widget, log_widget):
        super().__init__()
        self.setSpacing(4)
        self._log = log_widget
        self._parent = parent_widget

        self._input = QLineEdit(parent_widget)
        self._input.setPlaceholderText("搜索日志...")
        self._input.setMaximumWidth(180)
        self._input.textChanged.connect(self._on_text_changed)
        self._input.returnPressed.connect(self._search_next)
        self.addWidget(self._input)

        prev_btn = QPushButton("▲", parent_widget)
        prev_btn.setMaximumWidth(30)
        prev_btn.setToolTip("上一个匹配")
        prev_btn.clicked.connect(self._search_prev)
        self.addWidget(prev_btn)

        next_btn = QPushButton("▼", parent_widget)
        next_btn.setMaximumWidth(30)
        next_btn.setToolTip("下一个匹配")
        next_btn.clicked.connect(self._search_next)
        self.addWidget(next_btn)

        self._highlight_all_btn = QCheckBox("全部高亮", parent_widget)
        self._highlight_all_btn.toggled.connect(self._refresh_highlight)
        self.addWidget(self._highlight_all_btn)

        self._case_sensitive = QCheckBox("Aa", parent_widget)
        self._case_sensitive.setMaximumWidth(40)
        self._case_sensitive.setToolTip("区分大小写")
        self._case_sensitive.toggled.connect(self._refresh_highlight)
        self.addWidget(self._case_sensitive)

        export_btn = QPushButton("导出", parent_widget)
        export_btn.clicked.connect(self._export)
        self.addWidget(export_btn)

        clear_btn = QPushButton("清屏", parent_widget)
        clear_btn.clicked.connect(self._log.clear)
        self.addWidget(clear_btn)

        self._last_pos = -1
        self._highlight_format = QTextCharFormat()
        self._highlight_format.setBackground(QColor("#FFA726"))
        self._highlight_format.setForeground(QColor("#000"))

    def _on_text_changed(self, _text):
        self._last_pos = -1
        self._refresh_highlight()

    def _refresh_highlight(self):
        """在全部匹配位置添加高亮 ExtraSelection。"""
        if not isinstance(self._log, type(self._log)) or not hasattr(self._log, "extraSelections"):
            return
        text = self._input.text()
        selections = []
        if text and self._highlight_all_btn.isChecked():
            flags = QTextDocument.FindFlag(0)
            if self._case_sensitive.isChecked():
                flags = QTextDocument.FindFlag(0)  # 0=case sensitive 在 PySide6 是默认行为
            cursor = self._log.document().find(text, 0, flags)
            while not cursor.isNull():
                sel = QTextEdit.ExtraSelection()
                sel.cursor = cursor
                sel.format = self._highlight_format
                selections.append(sel)
                cursor = self._log.document().find(text, cursor, flags)
        try:
            self._log.setExtraSelections(selections)
        except Exception:
            pass

    def _search(self, backward=False):
        text = self._input.text()
        if not text:
            return
        flags = QTextDocument.FindFlag(0)
        if self._case_sensitive.isChecked():
            flags = QTextDocument.FindFlag(0)
        else:
            from PySide6.QtGui import QTextDocument as _TD
            flags = _TD.FindFlag(0)  # 0
        # 用 QTextDocument.find 替代手写 rfind
        if backward:
            start = max(0, self._last_pos - 1)
            cursor = self._log.document().find(text, start, flags)
            if cursor.isNull():
                cursor = self._log.document().find(text, 0, flags)
        else:
            start = max(0, self._last_pos)
            cursor = self._log.document().find(text, start, flags)
            if cursor.isNull():
                cursor = self._log.document().find(text, 0, flags)
        if not cursor.isNull():
            self._log.setTextCursor(cursor)
            self._log.ensureCursorVisible()
            self._last_pos = cursor.selectionEnd()

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


# PySide6 imports at module level for type hints
from PySide6.QtWidgets import QTextEdit
from PySide6.QtGui import QTextDocument
