# -*- coding: utf-8 -*-
"""
世界页面 —— 备份列表、手动备份/还原、自动备份开关。
"""

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView,
)
from qfluentwidgets import (
    CardWidget, SubtitleLabel, StrongBodyLabel, BodyLabel, CaptionLabel,
    PrimaryPushButton, PushButton, FluentIcon,
    ToggleButton, ProgressBar, SpinBox,
)

from shared.config import config_mgr, get_context
from shared.toast import toast_info, toast_success, toast_warning, toast_error
from backend.webhook import send_webhook
from backend.backup import BackupWorker, RestoreWorker, get_backup_files, get_backup_info
from pages.dashboard import wrap_scrollable


class WorldPage(QWidget):
    """世界管理 —— 备份与还原。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        inner, layout = wrap_scrollable(self, spacing=12)

        # ── 操作栏 ──
        action_card = CardWidget(inner)
        action_layout = QHBoxLayout(action_card)
        action_layout.setContentsMargins(16, 12, 16, 12)
        action_layout.setSpacing(8)

        self._backup_btn = PrimaryPushButton("手动备份", action_card, FluentIcon.SAVE)
        self._backup_btn.clicked.connect(self._on_backup)
        self._auto_toggle = ToggleButton("自动备份", action_card)
        self._auto_toggle.setChecked(config_mgr.get("auto_backup_enabled", True))
        self._auto_toggle.toggled.connect(
            lambda v: config_mgr.set("auto_backup_enabled", v)
        )

        action_layout.addWidget(self._backup_btn)
        action_layout.addWidget(self._auto_toggle)
        action_layout.addStretch()

        self._progress = ProgressBar(action_card)
        self._progress.setVisible(False)
        action_layout.addWidget(self._progress)
        layout.addWidget(action_card)

        # ── 备份列表 ──
        list_card = CardWidget(inner)
        list_layout = QVBoxLayout(list_card)
        list_layout.setContentsMargins(12, 10, 12, 12)
        list_layout.setSpacing(8)
        list_layout.addWidget(StrongBodyLabel("备份列表", list_card))

        self._table = QTableWidget(0, 4, list_card)
        self._table.setHorizontalHeaderLabels(["文件名", "大小", "时间", "操作"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self._table.setColumnWidth(3, 120)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setStyleSheet("""
            QTableWidget {
                background: #1e1e1e; color: #ccc;
                border: 1px solid #3a3a3a; border-radius: 6px;
                gridline-color: #3a3a3a;
            }
            QTableWidget::item { padding: 4px 8px; }
            QHeaderView::section {
                background: #2a2a2a; color: #aaa;
                border: none; padding: 6px 8px; font-weight: bold;
            }
        """)
        list_layout.addWidget(self._table)

        refresh_row = QHBoxLayout()
        refresh_row.addStretch()
        refresh_btn = PushButton("刷新", list_card, FluentIcon.SYNC)
        refresh_btn.clicked.connect(self._refresh_list)
        refresh_row.addWidget(refresh_btn)
        list_layout.addLayout(refresh_row)

        layout.addWidget(list_card)

        layout.addStretch()

        # 定时刷新 + 自动备份
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(15000)
        self._refresh_timer.timeout.connect(self._refresh_list)
        self._refresh_timer.start()

        self._auto_backup_timer = QTimer(self)
        self._auto_backup_timer.timeout.connect(self._on_auto_backup_tick)
        self._schedule_auto_backup()

        self._refresh_list()

    # ---------- 备份列表 ----------
    def _refresh_list(self):
        ctx = get_context()
        files = get_backup_files(ctx.backup_dir)
        self._table.setRowCount(len(files))
        for i, fn in enumerate(files):
            info = get_backup_info(ctx.backup_dir, fn)
            if not info:
                continue
            self._table.setItem(i, 0, QTableWidgetItem(info["name"]))
            self._table.setItem(i, 1, QTableWidgetItem(f"{info['size_mb']:.1f} MB"))
            self._table.setItem(i, 2, QTableWidgetItem(info["modified"]))
            restore_btn = PushButton("还原", self._table, FluentIcon.CANCEL)
            restore_btn.setMaximumWidth(50)
            backup_filename = fn
            restore_btn.clicked.connect(lambda checked, fn=backup_filename: self._on_restore(fn))
            delete_btn = PushButton("删除", self._table)
            delete_btn.setMaximumWidth(50)
            delete_btn.clicked.connect(lambda checked, fn=backup_filename: self._on_delete(fn))
            btn_widget = QWidget()
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(0, 0, 0, 0)
            btn_layout.setSpacing(2)
            btn_layout.addWidget(restore_btn)
            btn_layout.addWidget(delete_btn)
            self._table.setCellWidget(i, 3, btn_widget)

    # ---------- 手动备份 ----------
    def _on_backup(self):
        ctx = get_context()
        worlds = [d for d in os.listdir(ctx.worlds_dir)
                  if os.path.isdir(os.path.join(ctx.worlds_dir, d))]
        if not worlds:
            toast_warning("提示", "未找到世界目录", self.window())
            return
        level = worlds[0]  # 默认第一个世界
        world_path = os.path.join(ctx.worlds_dir, level)

        self._backup_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)  # 不确定模式

        self._worker = BackupWorker(
            level, world_path, ctx.backup_dir, parent=self, prefix="manual_"
        )
        self._worker.progress.connect(lambda m: self._progress.setVisible(True))
        self._worker.finished.connect(self._on_backup_done)
        self._worker.start()

    def _on_backup_done(self, success: bool, message: str):
        self._backup_btn.setEnabled(True)
        self._progress.setVisible(False)
        self._progress.setRange(0, 100)
        if success:
            toast_success("备份完成", message, self.window())
            send_webhook("backup", "备份完成", message)
            self._cleanup_backups()
        else:
            toast_error("备份失败", message, self.window())
        self._refresh_list()

    def _cleanup_backups(self):
        """只轮转 auto_ 前缀的自动备份，手动备份不受影响。"""
        keep = config_mgr.get("backup_keep", 20)
        ctx = get_context()
        try:
            files = sorted(
                [f for f in os.listdir(ctx.backup_dir) if f.startswith("auto_") and f.endswith(".zip")],
                key=lambda f: os.path.getmtime(os.path.join(ctx.backup_dir, f)),
                reverse=True,
            )
            for old in files[keep:]:
                os.remove(os.path.join(ctx.backup_dir, old))
        except Exception:
            pass

    # ---------- 还原 ----------
    def _on_restore(self, filename: str):
        ctx = get_context()
        worlds = [d for d in os.listdir(ctx.worlds_dir)
                  if os.path.isdir(os.path.join(ctx.worlds_dir, d))]
        if not worlds:
            return
        level = worlds[0]
        world_path = os.path.join(ctx.worlds_dir, level)
        backup_path = os.path.join(ctx.backup_dir, filename)

        info = toast_info("还原中", f"正在还原 {filename} ...", self.window(), duration=-1)

        self._restore_worker = RestoreWorker(
            level, world_path, backup_path, parent=self
        )
        self._restore_worker.finished.connect(
            lambda s, m: self._on_restore_done(s, m, info)
        )
        self._restore_worker.start()

    def _on_restore_done(self, success: bool, message: str, info_bar):
        info_bar.close()
        if success:
            toast_success("还原完成", message, self.window())
        else:
            toast_error("还原失败", message, self.window())

    def _on_delete(self, filename: str):
        ctx = get_context()
        fp = os.path.join(ctx.backup_dir, filename)
        try:
            os.remove(fp)
            toast_success("已删除", filename, self.window())
        except Exception as e:
            toast_error("删除失败", str(e), self.window())
        self._refresh_list()

    # ---------- 自动备份 ----------
    def _schedule_auto_backup(self):
        interval_min = config_mgr.get("backup_interval", 60)
        self._auto_backup_timer.start(interval_min * 60 * 1000)

    def _on_auto_backup_tick(self):
        if self._auto_toggle.isChecked():
            self._on_backup()

    # ---------- 清理 ----------
    def cleanup(self):
        self._refresh_timer.stop()
        self._auto_backup_timer.stop()
