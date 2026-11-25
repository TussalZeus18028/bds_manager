# -*- coding: utf-8 -*-
"""
通用文件编辑器对话框 —— 无边框圆角 + 半透明 + 主题感知。

v3.05.02: 从 pages/config.py 的 ConfigPage._open_file 提取为可复用组件
（原实现用于编辑 allowlist.json / permissions.json / packetlimitconfig.json）。
样式保持原样：半透明圆角容器、深/浅色编辑器、标题栏关闭按钮、保存/取消按钮行。
增强：Ctrl+S 保存、Esc 关闭、saved 信号回调。

用法：
    FileEditDialog(r"Server/allowlist.json", parent_widget).exec()

    dlg = FileEditDialog(path, parent)
    dlg.saved.connect(lambda p: print("saved", p))
    dlg.exec()
"""

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QWidget, QPlainTextEdit, QPushButton,
)
from qfluentwidgets import (
    BodyLabel, PushButton, PrimaryPushButton, FluentIcon, isDarkTheme,
)

from shared.toast import toast_success, toast_error


class FileEditDialog(QDialog):
    """无边框圆角文本编辑器对话框。

    属性：
        file_path: 目标文件路径
        title:    标题（默认取文件名）
    信号：
        saved(str): 保存成功，携带文件路径
    快捷键：
        Ctrl+S 保存；Esc 关闭（QDialog 默认）。
    """

    saved = Signal(str)

    def __init__(self, file_path: str, parent=None, title: str = ""):
        super().__init__(parent)
        self._file_path = file_path
        self._title = title or os.path.basename(file_path)
        self._load_error = ""

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setModal(True)
        self.resize(700, 530)
        self.setWindowOpacity(0.96)

        # ── 读取文件 ──
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                original = f.read()
        except (OSError, UnicodeDecodeError) as e:
            self._load_error = str(e)
            toast_error("读取失败", str(e), parent or self)
            original = ""

        dark = isDarkTheme()

        # ── 外层：圆角容器背景 ──
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        container = QWidget(self)
        container.setObjectName("fileEditContainer")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(20, 16, 20, 16)
        container_layout.setSpacing(10)

        if dark:
            container.setStyleSheet("""
                QWidget#fileEditContainer {
                    background: #1e1e1e; border: 1px solid #3a3a3a; border-radius: 12px;
                }
            """)
        else:
            container.setStyleSheet("""
                QWidget#fileEditContainer {
                    background: #fafafa; border: 1px solid #d0d0d0; border-radius: 12px;
                }
            """)
        outer.addWidget(container)

        # ── 标题栏 ──
        title_bar = QHBoxLayout()
        title_lbl = BodyLabel(self._title, container)
        title_lbl.setObjectName("fileEditTitle")
        title_lbl.setStyleSheet(
            "BodyLabel#fileEditTitle { color: #d4d4d4; font-size: 14px; font-weight: 600; }" if dark
            else "BodyLabel#fileEditTitle { color: #333; font-size: 14px; font-weight: 600; }"
        )
        title_bar.addWidget(title_lbl)
        title_bar.addStretch()
        close_btn = QPushButton("✕", container)
        close_btn.setFixedSize(28, 28)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; border-radius: 6px;"
            " color: #888; font-size: 14px; }"
            "QPushButton:hover { background: #e81123; color: #fff; }" if dark
            else "QPushButton { background: transparent; border: none; border-radius: 6px;"
            " color: #999; font-size: 14px; }"
            "QPushButton:hover { background: #e81123; color: #fff; }"
        )
        close_btn.clicked.connect(self.reject)
        title_bar.addWidget(close_btn)
        container_layout.addLayout(title_bar)

        # ── 分隔线 ──
        sep = QWidget(container)
        sep.setFixedHeight(1)
        sep.setStyleSheet(
            "background: #3a3a3a;" if dark
            else "background: #e0e0e0;"
        )
        container_layout.addWidget(sep)

        # ── 编辑器 ──
        self._editor = QPlainTextEdit(container)
        self._editor.setPlainText(original)
        self._editor.setTabStopDistance(20)
        self._editor.setMinimumHeight(300)
        if dark:
            self._editor.setStyleSheet("""
                QPlainTextEdit {
                    background: #1e1e1e; color: #ccc;
                    border: 1px solid #3a3a3a; border-radius: 8px;
                    padding: 12px; font-size: 13px; font-family: Consolas, monospace;
                    selection-background-color: #264f78;
                }
            """)
        else:
            self._editor.setStyleSheet("""
                QPlainTextEdit {
                    background: #fafafa; color: #1a1a1a;
                    border: 1px solid #d0d0d0; border-radius: 8px;
                    padding: 12px; font-size: 13px; font-family: Consolas, monospace;
                    selection-background-color: #cce5ff;
                }
            """)
        container_layout.addWidget(self._editor)

        # ── 按钮行 ──
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = PushButton("取消", container, FluentIcon.CANCEL)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        save_btn = PrimaryPushButton("保存", container, FluentIcon.SAVE)
        save_btn.clicked.connect(self._do_save)
        btn_row.addWidget(save_btn)

        container_layout.addLayout(btn_row)

        # ── 快捷键：Ctrl+S 保存 ──
        self._save_shortcut = QShortcut(QKeySequence("Ctrl+S"), self)
        self._save_shortcut.activated.connect(self._do_save)

    def _do_save(self):
        try:
            with open(self._file_path, "w", encoding="utf-8") as f:
                f.write(self._editor.toPlainText())
        except OSError as e:
            toast_error("保存失败", str(e), self.parent() or self)
            return
        self.saved.emit(self._file_path)
        toast_success("已保存", f"{self._title} 已更新", self.parent() or self)
        self.accept()

    def exec(self):
        """执行对话框；文件读取失败时不显示，直接返回 0。"""
        if self._load_error:
            return 0
        return super().exec()
