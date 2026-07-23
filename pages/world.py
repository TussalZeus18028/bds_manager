# -*- coding: utf-8 -*-
"""
世界页面 —— 备份列表、手动备份/还原、自动备份开关、内容预览。

v3.1 改进：
- 备份列表显示 metadata（世界名/BDS 版本/文件数）
- 选中备份时右侧展开 QTreeWidget 内容预览
- 顶部"世界详情"卡片（名称/种子/难度/游戏模式/磁盘大小/最后备份时间）
- 时间轴分组（今日/昨日/本周/更早）
- 备份大小/数量统计摘要
"""

import os
import time
from datetime import datetime, timedelta

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QTreeWidget, QTreeWidgetItem,
    QSplitter, QSizePolicy,
)
from qfluentwidgets import (
    CardWidget, SubtitleLabel, StrongBodyLabel, BodyLabel, CaptionLabel,
    PrimaryPushButton, PushButton, FluentIcon,
    ToggleButton, ProgressBar, MessageBox,
)

from shared.config import config_mgr, get_context
from shared.toast import toast_info, toast_success, toast_warning, toast_error
from shared.errors import FileMissingError
from backend.webhook import send_webhook
from backend.backup import (
    BackupWorker, RestoreWorker, get_backup_files, get_backup_info,
    build_backup_tree, read_backup_metadata,
)
from pages.dashboard import wrap_scrollable


def _format_size(size_bytes: int) -> str:
    if size_bytes > 1024 ** 3:
        return f"{size_bytes/1024**3:.2f} GB"
    if size_bytes > 1024 ** 2:
        return f"{size_bytes/1024**2:.1f} MB"
    if size_bytes > 1024:
        return f"{size_bytes/1024:.1f} KB"
    return f"{size_bytes} B"


def _format_size_mb(size_mb: float) -> str:
    if size_mb >= 1024:
        return f"{size_mb/1024:.2f} GB"
    return f"{size_mb:.1f} MB"


def _time_bucket(mtime: float) -> str:
    """把时间戳分桶：今日/昨日/本周/本月/更早。"""
    now = datetime.now()
    dt = datetime.fromtimestamp(mtime)
    if dt.date() == now.date():
        return "今日"
    if dt.date() == (now - timedelta(days=1)).date():
        return "昨日"
    if (now - dt).days < 7:
        return "本周"
    if dt.year == now.year and dt.month == now.month:
        return "本月"
    return "更早"


class WorldPage(QWidget):
    """世界管理 —— 备份与还原（v3.1）。"""

    # 信号：备份完成时通知 Dashboard 刷新"最近备份"时间
    backup_completed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._initialized = False
        self._refresh_timer = None
        self._auto_backup_timer = None
        inner, layout = wrap_scrollable(self, spacing=12)

        # ── 世界详情卡 ──
        self._detail_card = CardWidget(inner)
        dl = QVBoxLayout(self._detail_card)
        dl.setContentsMargins(16, 12, 16, 16); dl.setSpacing(4)
        dl.addWidget(SubtitleLabel("世界详情", self._detail_card))
        self._world_info = BodyLabel("", self._detail_card)
        self._world_info.setStyleSheet("color: #ccc; line-height: 1.6;")
        dl.addWidget(self._world_info)
        # 摘要：备份数 / 占用空间 / 最近备份
        self._summary_label = CaptionLabel("", self._detail_card)
        self._summary_label.setStyleSheet("color: #888; margin-top: 6px;")
        dl.addWidget(self._summary_label)
        layout.addWidget(self._detail_card)

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
        self._restore_btn = PushButton("还原选中", action_card, FluentIcon.CANCEL)
        self._restore_btn.setEnabled(False)
        self._restore_btn.clicked.connect(self._on_restore_selected)
        self._delete_btn = PushButton("删除选中", action_card, FluentIcon.DELETE)
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._on_delete_selected)

        action_layout.addWidget(self._backup_btn)
        action_layout.addWidget(self._auto_toggle)
        action_layout.addStretch()
        action_layout.addWidget(self._restore_btn)
        action_layout.addWidget(self._delete_btn)

        self._progress = ProgressBar(action_card)
        self._progress.setVisible(False)
        self._progress.setMaximumWidth(160)
        action_layout.addWidget(self._progress)
        layout.addWidget(action_card)

        # ── 备份列表 + 预览（Splitter）──
        list_card = CardWidget(inner)
        list_outer = QVBoxLayout(list_card)
        list_outer.setContentsMargins(12, 10, 12, 12)
        list_outer.setSpacing(8)
        list_outer.addWidget(StrongBodyLabel("备份列表（点击查看内容）", list_card))

        splitter = QSplitter(Qt.Horizontal, list_card)
        splitter.setHandleWidth(6)

        # 左：表格
        self._table = QTableWidget(0, 5, splitter)
        self._table.setHorizontalHeaderLabels(["文件名", "大小", "时间", "分桶", "源版本"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for col, w in [(1, 90), (2, 150), (3, 70), (4, 90)]:
            self._table.horizontalHeader().setSectionResizeMode(col, QHeaderView.Fixed)
            self._table.setColumnWidth(col, w)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.itemSelectionChanged.connect(self._on_table_selection_changed)
        self._table.setStyleSheet("""
            QTableWidget {
                background: #1e1e1e; color: #ccc;
                border: 1px solid #3a3a3a; border-radius: 6px;
                gridline-color: #3a3a3a;
            }
            QTableWidget::item { padding: 4px 8px; }
            QTableWidget::item:selected { background: rgba(13, 197, 212, 0.25); }
            QHeaderView::section {
                background: #2a2a2a; color: #aaa;
                border: none; padding: 6px 8px; font-weight: bold;
            }
        """)
        splitter.addWidget(self._table)

        # 右：内容预览
        self._preview_tree = QTreeWidget(splitter)
        self._preview_tree.setHeaderLabels(["名称", "大小"])
        self._preview_tree.setColumnWidth(0, 220)
        self._preview_tree.setStyleSheet("""
            QTreeWidget {
                background: #1e1e1e; color: #ccc;
                border: 1px solid #3a3a3a; border-radius: 6px;
            }
            QTreeWidget::item { padding: 3px 4px; }
            QTreeWidget::item:selected { background: rgba(13, 197, 212, 0.25); }
            QHeaderView::section {
                background: #2a2a2a; color: #aaa;
                border: none; padding: 6px 8px; font-weight: bold;
            }
        """)
        self._preview_tree.setMinimumWidth(280)
        splitter.addWidget(self._preview_tree)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([600, 400])

        list_outer.addWidget(splitter)

        refresh_row = QHBoxLayout()
        self._status_label = CaptionLabel("", list_card)
        self._status_label.setStyleSheet("color: #888;")
        refresh_row.addWidget(self._status_label)
        refresh_row.addStretch()
        refresh_btn = PushButton("刷新", list_card, FluentIcon.SYNC)
        refresh_btn.clicked.connect(self._refresh_list)
        refresh_row.addWidget(refresh_btn)
        list_outer.addLayout(refresh_row)

        layout.addWidget(list_card)
        layout.addStretch()

        # 数据加载 + 定时器延迟到 showEvent（启动加速）

    def showEvent(self, event):
        """首次显示时再做磁盘扫描和数据加载（启动加速）。"""
        if not self._initialized:
            self._initialized = True
            # 定时刷新
            self._refresh_timer = QTimer(self)
            self._refresh_timer.setInterval(15000)
            self._refresh_timer.timeout.connect(self._refresh_list)
            self._refresh_timer.start()
            # 自动备份
            self._auto_backup_timer = QTimer(self)
            self._auto_backup_timer.timeout.connect(self._on_auto_backup_tick)
            self._schedule_auto_backup()
            # 数据加载
            self._refresh_list()
            self._refresh_world_info()
        super().showEvent(event)

    # ---------- 表格事件 ----------
    def _on_table_selection_changed(self):
        rows = self._table.selectionModel().selectedRows()
        has_sel = bool(rows)
        self._restore_btn.setEnabled(has_sel)
        self._delete_btn.setEnabled(has_sel)
        if has_sel:
            self._show_preview_for_row(rows[0].row())
        else:
            self._preview_tree.clear()

    def _show_preview_for_row(self, row: int):
        filename = self._table.item(row, 0).text() if self._table.item(row, 0) else None
        if not filename:
            return
        ctx = get_context()
        backup_path = os.path.join(ctx.backup_dir, filename)
        tree_data = build_backup_tree(backup_path)
        self._preview_tree.clear()
        if not tree_data:
            placeholder = QTreeWidgetItem(["(无法读取备份，可能已损坏)", ""])
            self._preview_tree.addTopLevelItem(placeholder)
            return
        # 根
        root_item = QTreeWidgetItem([
            f"📦 {tree_data['name']}",
            f"{tree_data['total_files']} 个文件 · {_format_size(tree_data['total_size'])}",
        ])
        root_item.setExpanded(True)
        self._preview_tree.addTopLevelItem(root_item)
        # 递归填充
        self._fill_tree(root_item, tree_data["root"])
        # 元数据
        info = get_backup_info(ctx.backup_dir, filename)
        if info and info.get("metadata"):
            meta = info["metadata"]
            meta_text = f"  · 世界: {meta.get('world_name', '?')}  · BDS: {meta.get('bds_version', '?')}  · 工具: v{meta.get('tool_version', '?')}"
            for i in range(self._preview_tree.topLevelItemCount()):
                self._preview_tree.topLevelItem(i).setText(0, self._preview_tree.topLevelItem(i).text(0) + meta_text)

    def _fill_tree(self, parent_item: QTreeWidgetItem, node: dict):
        for name, child in node.get("children", {}).items():
            dir_item = QTreeWidgetItem([f"📁 {child['name']}/", ""])
            parent_item.addChild(dir_item)
            self._fill_tree(dir_item, child)
        for f in node.get("files", []):
            file_item = QTreeWidgetItem([f"📄 {f['name']}", _format_size(f.get("size", 0))])
            parent_item.addChild(file_item)

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
            self._table.setItem(i, 1, QTableWidgetItem(_format_size_mb(info["size_mb"])))
            self._table.setItem(i, 2, QTableWidgetItem(info["modified"]))
            try:
                mtime = os.path.getmtime(os.path.join(ctx.backup_dir, fn))
                bucket = _time_bucket(mtime)
            except OSError:
                bucket = "?"
            self._table.setItem(i, 3, QTableWidgetItem(bucket))
            bds_ver = ""
            if info.get("metadata"):
                bds_ver = info["metadata"].get("bds_version", "")
            self._table.setItem(i, 4, QTableWidgetItem(bds_ver or "—"))
        # 状态栏
        self._status_label.setText(f"共 {len(files)} 个备份")
        self._refresh_summary()
        # 保持选中
        sel = self._table.selectionModel().selectedRows()
        if sel:
            self._show_preview_for_row(sel[0].row())

    def _refresh_summary(self):
        """更新顶部摘要：总占用 / 数量 / 最近一次。"""
        ctx = get_context()
        files = get_backup_files(ctx.backup_dir)
        if not files:
            self._summary_label.setText("尚无备份")
            return
        total_mb = 0.0
        latest = None
        latest_t = 0
        for fn in files:
            try:
                fp = os.path.join(ctx.backup_dir, fn)
                st = os.stat(fp)
                total_mb += st.st_size / (1024 * 1024)
                if st.st_mtime > latest_t:
                    latest_t = st.st_mtime
                    latest = fn
            except OSError:
                pass
        ago = ""
        if latest_t > 0:
            delta = int(time.time() - latest_t)
            if delta < 60: ago = f"{delta} 秒前"
            elif delta < 3600: ago = f"{delta // 60} 分钟前"
            elif delta < 86400: ago = f"{delta // 3600} 小时前"
            else: ago = f"{delta // 86400} 天前"
        size_text = f"{total_mb/1024:.2f} GB" if total_mb >= 1024 else f"{total_mb:.1f} MB"
        self._summary_label.setText(
            f"共 {len(files)} 个备份 · 总占用 {size_text} · 最近备份: {latest}（{ago}）"
        )

    def _refresh_world_info(self):
        ctx = get_context()
        props = ctx.server_properties
        info_lines = []
        size_text = ""
        # 从 server.properties 提取
        if os.path.exists(props):
            try:
                with open(props, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        if k == "level-name":
                            info_lines.append(f"世界名: <b>{v}</b>")
                        elif k == "level-seed":
                            info_lines.append(f"种子: {v if v else '(随机)'}")
                        elif k == "difficulty":
                            info_lines.append(f"难度: {v}")
                        elif k == "gamemode":
                            info_lines.append(f"游戏模式: {v}")
                        elif k == "max-players":
                            info_lines.append(f"最大玩家: {v}")
                        elif k == "server-port":
                            info_lines.append(f"端口: {v}")
            except Exception:
                pass
        if not info_lines:
            info_lines.append("(未检测到 server.properties)")
        # 磁盘大小
        if os.path.isdir(ctx.worlds_dir):
            worlds = [d for d in os.listdir(ctx.worlds_dir)
                      if os.path.isdir(os.path.join(ctx.worlds_dir, d))]
            if worlds:
                wp = os.path.join(ctx.worlds_dir, worlds[0])
                total_size = 0
                try:
                    for root, _, files in os.walk(wp):
                        for f in files:
                            try:
                                total_size += os.path.getsize(os.path.join(root, f))
                            except OSError:
                                pass
                except Exception:
                    pass
                size_text = _format_size(total_size)
                info_lines.append(f"磁盘占用: <b>{size_text}</b>")
        # HTML 渲染
        self._world_info.setText("<br>".join(info_lines))

    # ---------- 手动备份 ----------
    def _on_backup(self):
        ctx = get_context()
        worlds = [d for d in os.listdir(ctx.worlds_dir)
                  if os.path.isdir(os.path.join(ctx.worlds_dir, d))]
        if not worlds:
            toast_warning("提示", "未找到世界目录", self.window())
            return
        level = worlds[0]
        world_path = os.path.join(ctx.worlds_dir, level)

        self._backup_btn.setEnabled(False)
        self._restore_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setRange(0, 0)

        # 尝试读取当前 BDS 版本
        bds_ver = ""
        try:
            import main
            bds_ver = main.__version__
        except Exception:
            pass

        self._worker = BackupWorker(
            level, world_path, ctx.backup_dir, parent=self, prefix="manual_",
            bds_version=bds_ver,
        )
        self._worker.progress.connect(self._on_backup_progress)
        self._worker.finished.connect(self._on_backup_done)
        self._worker.start()

    def _on_backup_progress(self, msg: str):
        self._status_label.setText(msg)

    def _on_backup_done(self, success: bool, message: str):
        self._backup_btn.setEnabled(True)
        self._progress.setVisible(False)
        self._progress.setRange(0, 100)
        if success:
            toast_success("备份完成", message, self.window())
            send_webhook("backup", "备份完成", message)
            # v3.02.00 通知中心：备份成功由 main._on_backup_completed 统一发（携带文件名跳转）
            self._cleanup_backups()
            self.backup_completed.emit()
        else:
            toast_error("备份失败", message, self.window())
            # v3.02.00 通知中心：备份失败单独通知
            try:
                from backend.notifications import notify
                notify("error", "backup", "备份失败", message, "page:world")
            except Exception:
                pass
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
    def _on_restore_selected(self):
        sel = self._table.selectionModel().selectedRows()
        if not sel:
            return
        fn = self._table.item(sel[0].row(), 0).text()
        self._on_restore(fn)

    def _on_restore(self, filename: str):
        # 二次确认
        confirm = MessageBox(
            "确认还原",
            f"即将从备份还原世界：\n{filename}\n\n当前世界会被覆盖，失败将自动回滚。\n\n是否继续？",
            self.window(),
        )
        if not confirm.exec():
            return

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
        try:
            info_bar.close()
        except Exception:
            pass
        if success:
            toast_success("还原完成", message, self.window())
            try:
                from backend.notifications import notify
                notify("success", "backup", "世界已还原", message, "page:world")
            except Exception:
                pass
        else:
            toast_error("还原失败", message, self.window())
            try:
                from backend.notifications import notify
                notify("error", "backup", "还原失败", message, "page:world")
            except Exception:
                pass

    def _on_delete_selected(self):
        sel = self._table.selectionModel().selectedRows()
        if not sel:
            return
        fn = self._table.item(sel[0].row(), 0).text()
        self._on_delete(fn)

    def _on_delete(self, filename: str):
        ctx = get_context()
        fp = os.path.join(ctx.backup_dir, filename)
        confirm = MessageBox("确认删除", f"确定删除备份 {filename}？此操作不可撤销。", self.window())
        if not confirm.exec():
            return
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
        if self._refresh_timer is not None:
            self._refresh_timer.stop()
        if self._auto_backup_timer is not None:
            self._auto_backup_timer.stop()
