# -*- coding: utf-8 -*-
"""
资源包 / 行为包管理页面。

v3.1 改进：
- 双击弹出 PackInfoDialog（显示 manifest 全字段 + 依赖链）
- 启用/禁用 ToggleButton（禁用时移到 disabled_packs/ 子目录）
- 添加时检测 pack_id 冲突
- 冲突警告
"""

import os, json, shutil

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QFileDialog, QLabel, QDialog,
)
from qfluentwidgets import (
    CardWidget, SubtitleLabel, StrongBodyLabel, BodyLabel, CaptionLabel,
    PrimaryPushButton, PushButton, FluentIcon, ProgressBar, MessageBox,
    ToggleButton, ScrollArea, isDarkTheme,
)
from PySide6.QtWidgets import QFrame as Frame

from shared.config import get_context
from shared.toast import toast_success, toast_error, toast_warning
from pages.dashboard import wrap_scrollable


# ── manifest 读取 ──
def _read_manifest(pack_dir: str) -> dict:
    fp = os.path.join(pack_dir, "manifest.json")
    if os.path.exists(fp):
        try:
            with open(fp, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _scan_packs(packs_dir: str, include_disabled: bool = False) -> list[dict]:
    """扫描目录下所有包。"""
    if not packs_dir or not os.path.exists(packs_dir):
        return []
    result = []
    for name in os.listdir(packs_dir):
        d = os.path.join(packs_dir, name)
        if not os.path.isdir(d):
            continue
        # 默认跳过 disabled_packs/ 子目录
        if not include_disabled and name == "disabled_packs":
            continue
        # disabled_packs 下的包，dirname 加 .disabled 后缀
        disabled_root = os.path.join(packs_dir, "disabled_packs")
        is_disabled = os.path.dirname(d) == disabled_root
        manifest = _read_manifest(d)
        header = manifest.get("header", {})
        result.append({
            "name": header.get("name", name),
            "desc": header.get("description", ""),
            "uuid": header.get("uuid", ""),
            "version": ".".join(str(v) for v in header.get("version", [])),
            "min_engine": header.get("min_engine_version", []),
            "pack_id": header.get("pack_id", ""),
            "modules": header.get("modules", []),
            "dependencies": header.get("dependencies", []),
            "path": d,
            "dirname": name,
            "is_disabled": is_disabled,
        })
    # 启用的排前面
    result.sort(key=lambda x: (x["is_disabled"], x["name"].lower()))
    return result


# ── 复制 Worker ──
class CopyPackWorker(QThread):
    finished = Signal(bool, str)

    def __init__(self, src: str, dest_dir: str, parent=None):
        super().__init__(parent)
        self.src = src
        self.dest_dir = dest_dir

    def run(self):
        try:
            name = os.path.basename(self.src)
            dest = os.path.join(self.dest_dir, name)
            if os.path.exists(dest):
                self.finished.emit(False, f"已存在同名包: {name}")
                return
            os.makedirs(self.dest_dir, exist_ok=True)
            shutil.copytree(self.src, dest)
            self.finished.emit(True, f"已添加: {name}")
        except Exception as e:
            self.finished.emit(False, str(e))


# ── 详情对话框 ──
class PackInfoDialog(QDialog):
    """点击资源包显示完整 manifest 信息。"""

    def __init__(self, pack_info: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"资源包详情 - {pack_info['name']}")
        self.resize(560, 500)
        self._pack = pack_info
        layout = QVBoxLayout(self)
        scroll = ScrollArea(self)
        scroll.setWidgetResizable(True)
        frame = Frame(scroll)
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(20, 16, 20, 16)
        fl.setSpacing(10)

        def add_field(label: str, value: str):
            row = QHBoxLayout()
            lbl = BodyLabel(label, frame)
            lbl.setMinimumWidth(120)
            lbl.setStyleSheet("color: #888;")
            row.addWidget(lbl)
            val_lbl = BodyLabel(str(value) if value else "—", frame)
            val_lbl.setWordWrap(True)
            val_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            row.addWidget(val_lbl, 1)
            fl.addLayout(row)

        fl.addWidget(SubtitleLabel(pack_info['name'], frame))
        if pack_info['desc']:
            desc = CaptionLabel(pack_info['desc'], frame)
            desc.setWordWrap(True)
            desc.setStyleSheet("color: #aaa;")
            fl.addWidget(desc)

        add_field("路径", pack_info['dirname'])
        add_field("UUID", pack_info['uuid'])
        add_field("版本", pack_info['version'])
        add_field("pack_id", pack_info.get('pack_id', ''))

        modules = pack_info.get('modules', [])
        if modules:
            for m in modules:
                add_field(f"模块 [{m.get('type', '?')}]", f"{m.get('uuid', '?')} ({m.get('version', '?')})")

        deps = pack_info.get('dependencies', [])
        if deps:
            fl.addWidget(SubtitleLabel("依赖", frame))
            for d in deps:
                add_field("  •", f"{d.get('uuid', '?')} ({d.get('version', '?')})")

        min_eng = pack_info.get('min_engine', [])
        if min_eng:
            add_field("最低引擎版本", ".".join(str(v) for v in min_eng))

        add_field("状态", "❌ 禁用" if pack_info.get('is_disabled') else "✅ 启用")

        scroll.setWidget(frame)
        layout.addWidget(scroll)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = PushButton("关闭", self)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)


# ── 冲突检测 ──
def _check_uuid_conflict(packs: list[dict], pack_id: str) -> str | None:
    """检查新加包是否与已有包 pack_id 冲突。返回冲突的包名。"""
    for p in packs:
        if p.get('pack_id') == pack_id and pack_id:
            return p['name']
    return None


# ── 页面 ──
class PacksPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._initialized = False
        self._sections: dict = {}
        inner, layout = wrap_scrollable(self, spacing=12)
        # 只构建 UI 骨架（无 I/O），首次显示时再扫描磁盘
        for key, title in [("resource", "资源包"), ("behavior", "行为包")]:
            card = self._build_section(inner, key, title)
            layout.addWidget(card)
        layout.addStretch()

    def showEvent(self, event):
        """首次显示时扫描磁盘上的包；同时刷新表格主题（应对运行时切换主题）。"""
        if not self._initialized:
            self._initialized = True
            for key in self._sections:
                sec = self._sections[key]
                refresh_fn = sec.get("refresh")
                if refresh_fn:
                    try:
                        refresh_fn()
                    except Exception:
                        pass
        else:
            # v3.02.01 fix: 主题切换后重新应用表格样式（之前只在 __init__ 时设一次）
            self._refresh_all_themes()
        super().showEvent(event)

    def _refresh_all_themes(self):
        """主题切换后调用：重新设表格 + 状态文字 + hint 颜色。"""
        sub_color = "#888" if isDarkTheme() else "#666"
        for sec in self._sections.values():
            self._apply_table_theme(sec["table"])
            sec["status_label"].setStyleSheet(f"color: {sub_color};")
            sec["hint"].setStyleSheet(f"color: {sub_color}; padding: 12px;")

    def refresh_theme(self):
        """v3.02.01：主题切换后由 main.apply_theme() 调用，重设表格 + 文字色。"""
        self._refresh_all_themes()

    def _apply_table_theme(self, table: QTableWidget):
        """v3.02.01：主题感知表格样式（深/浅主题各一套）。"""
        if isDarkTheme():
            table.setStyleSheet("""
                QTableWidget {
                    background: #1e1e1e; color: #ccc;
                    border: 1px solid #3a3a3a; border-radius: 6px;
                    gridline-color: #3a3a3a;
                    selection-background-color: #2d4a5e;
                    selection-color: #ffffff;
                }
                QTableWidget::item { padding: 4px 8px; }
                QHeaderView::section {
                    background: #2a2a2a; color: #aaa;
                    border: none; padding: 6px 8px; font-weight: bold;
                }
            """)
        else:
            table.setStyleSheet("""
                QTableWidget {
                    background: #ffffff; color: #1a1a1a;
                    border: 1px solid #d0d0d0; border-radius: 6px;
                    gridline-color: #e8e8e8;
                    selection-background-color: #d8eef5;
                    selection-color: #1a1a1a;
                }
                QTableWidget::item { padding: 4px 8px; }
                QHeaderView::section {
                    background: #f5f5f5; color: #555;
                    border: none; padding: 6px 8px; font-weight: bold;
                }
            """)

    def _build_section(self, inner, key: str, title: str) -> CardWidget:
        card = CardWidget(inner)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 12, 16, 16)
        cl.setSpacing(8)

        hdr = QHBoxLayout()
        hdr.addWidget(SubtitleLabel(title, card))
        hdr.addStretch()
        # v3.02.01 fix: 主题感知的次要文字色（之前 #888 写死，浅色主题下看不见）
        sub_color = "#888" if isDarkTheme() else "#666"
        self._status_label = CaptionLabel("", card)
        self._status_label.setStyleSheet(f"color: {sub_color};")
        hdr.addWidget(self._status_label)
        add_btn = PrimaryPushButton(f"添加{title}", card, FluentIcon.ADD)
        refresh_btn = PushButton("刷新", card, FluentIcon.SYNC)
        hdr.addWidget(add_btn)
        hdr.addWidget(refresh_btn)
        cl.addLayout(hdr)

        table = QTableWidget(0, 5, card)
        table.setHorizontalHeaderLabels(["名称", "版本", "UUID", "启用", "操作"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        # v3.02.01：启用列加宽到 90px，确保 ToggleButton 文字完整显示（"启用/禁用"）
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        table.setColumnWidth(3, 90)
        # 操作列加宽到 200px，容纳「详情」「移除」两个按钮
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        table.setColumnWidth(4, 200)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.doubleClicked.connect(lambda idx, k=key: self._show_info_for(k, idx))
        # v3.02.01 fix: 主题感知表格样式（之前硬编码暗色，浅色主题下整张表是深色的）
        self._apply_table_theme(table)
        # 行高适应 ToggleButton（默认 30 太矮，ToggleButton 需要 32+）
        table.verticalHeader().setDefaultSectionSize(36)
        cl.addWidget(table)

        hint = CaptionLabel(f"暂无已安装的{title}，点击「添加{title}」导入。提示：双击行查看详情。", card)
        hint.setStyleSheet(f"color: {sub_color}; padding: 12px;")
        cl.addWidget(hint)

        self._sections[key] = {
            "table": table, "hint": hint, "add_btn": add_btn, "refresh_btn": refresh_btn,
            "status_label": self._status_label,
        }

        def _refresh():
            try:
                ctx = get_context()
                dir_map = {"resource": ctx.resource_packs_dir, "behavior": ctx.behavior_packs_dir}
                packs_dir = dir_map.get(key, "")
                packs = _scan_packs(packs_dir)
            except Exception:
                packs = []
            hint.setVisible(len(packs) == 0)
            enabled_count = sum(1 for p in packs if not p["is_disabled"])
            disabled_count = len(packs) - enabled_count
            self._status_label.setText(f"启用 {enabled_count} / 禁用 {disabled_count}")

            table.setRowCount(len(packs))
            for i, p in enumerate(packs):
                # v3.02.01 fix: 去掉行末 "❌" 字符（与 toggle 文字"禁用"视觉冗余）
                table.setItem(i, 0, QTableWidgetItem(p["name"]))
                table.setItem(i, 1, QTableWidgetItem(p["version"] or "—"))
                table.setItem(i, 2, QTableWidgetItem(p["uuid"][:12] + "..." if p["uuid"] else "—"))
                # 启用/禁用 Toggle —— v3.02.01：改用「启用/禁用」完整文字
                toggle = ToggleButton("启用" if not p["is_disabled"] else "禁用", table)
                toggle.setChecked(not p["is_disabled"])
                toggle.toggled.connect(lambda chk, pp=p, t=toggle: self._toggle_pack(pp, chk, t, _refresh))
                table.setCellWidget(i, 3, toggle)
                # 操作按钮
                info_btn = PushButton("详情", table)
                info_btn.clicked.connect(lambda checked, pp=p: self._show_info(pp))
                remove_btn = PushButton("移除", table)
                remove_btn.clicked.connect(
                    lambda checked, pp=p: self._remove_pack(pp, _refresh)
                )
                btn_widget = QWidget()
                bl = QHBoxLayout(btn_widget)
                bl.setContentsMargins(0, 0, 0, 0); bl.setSpacing(2)
                bl.addWidget(info_btn)
                bl.addWidget(remove_btn)
                table.setCellWidget(i, 4, btn_widget)

        def _add():
            try:
                ctx = get_context()
                dir_map = {"resource": ctx.resource_packs_dir, "behavior": ctx.behavior_packs_dir}
                dest = dir_map.get(key, "")
            except Exception as e:
                toast_error("路径错误", str(e), self.window())
                return
            dlg = QFileDialog(self)
            dlg.setFileMode(QFileDialog.Directory)
            dlg.setOption(QFileDialog.ShowDirsOnly, True)
            if dlg.exec():
                src = dlg.selectedFiles()[0]
                # pack_id 冲突检测
                src_manifest = _read_manifest(src)
                src_pack_id = src_manifest.get("header", {}).get("pack_id", "")
                if src_pack_id:
                    existing = _scan_packs(dest)
                    conflict = _check_uuid_conflict(existing, src_pack_id)
                    if conflict:
                        confirm = MessageBox(
                            "包冲突", f"检测到 pack_id 冲突：\n新包: {src_pack_id}\n已存在: {conflict}\n\n是否仍要添加？",
                            self.window(),
                        )
                        if not confirm.exec():
                            return
                self._copy_worker = CopyPackWorker(src, dest, self)
                self._copy_worker.finished.connect(
                    lambda ok, msg: (
                        toast_success("完成", msg, self.window()) if ok else toast_error("失败", msg, self.window()),
                        _refresh()
                    )
                )
                self._copy_worker.start()

        add_btn.clicked.connect(_add)
        refresh_btn.clicked.connect(_refresh)
        # 不在 __init__ 中调用 _refresh()，延迟到首次 showEvent（启动加速）
        # 但要先把 _refresh 存到 sections 以便 showEvent 调用
        self._sections[key]["refresh"] = _refresh
        return card

    def _show_info_for(self, key: str, idx):
        table = self._sections[key]["table"]
        row = idx.row()
        ctx = get_context()
        dir_map = {"resource": ctx.resource_packs_dir, "behavior": ctx.behavior_packs_dir}
        packs_dir = dir_map.get(key, "")
        packs = _scan_packs(packs_dir)
        if row < len(packs):
            self._show_info(packs[row])

    def _show_info(self, pack: dict):
        dlg = PackInfoDialog(pack, self.window())
        dlg.exec()

    def _toggle_pack(self, pack: dict, enabled: bool, btn: ToggleButton, refresh_cb):
        """切换启用/禁用：移动到 disabled_packs/ 子目录。"""
        if not pack.get("path"):
            return
        ctx = get_context()
        # 决定目标目录
        parent = os.path.dirname(pack["path"])
        if pack["is_disabled"]:
            # 启用：从 disabled_packs/ 移回上一级
            new_parent = os.path.dirname(parent)
        else:
            # 禁用：移到 disabled_packs/
            new_parent = os.path.join(parent, "disabled_packs")
        os.makedirs(new_parent, exist_ok=True)
        new_path = os.path.join(new_parent, pack["dirname"])
        if os.path.exists(new_path):
            toast_error("失败", f"目标已存在: {new_path}", self.window())
            btn.setChecked(not enabled)  # 回滚状态
            return
        try:
            shutil.move(pack["path"], new_path)
            btn.setText("启用" if enabled else "禁用")
            toast_success(
                "已切换",
                f"{pack['name']} → {'启用' if enabled else '禁用'}",
                self.window(),
            )
        except Exception as e:
            toast_error("切换失败", str(e), self.window())
            btn.setChecked(not enabled)
        refresh_cb()

    def _remove_pack(self, pack: dict, refresh_cb):
        confirm = MessageBox("确认移除", f"确定要删除包「{pack['name']}」？\n此操作不可撤销。", self.window())
        if not confirm.exec():
            return
        try:
            shutil.rmtree(pack["path"])
            toast_success("已移除", pack["name"], self.window())
        except Exception as e:
            toast_error("移除失败", str(e), self.window())
        refresh_cb()
