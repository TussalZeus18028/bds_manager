# -*- coding: utf-8 -*-
"""
资源包 / 行为包管理页面。

v3.02.01 重写（对齐旧版正确逻辑）：
- 不再用 disabled_packs/ 子目录（那是错误抽象）
- 启用/禁用 = 注册到 world_resource_packs.json / 从其中注销
- 所有包始终显示在列表中（✓已激活 / —未激活）
- 新添加的包默认不激活（用户手动点启用）
"""
import os, json, shutil

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QFileDialog, QLabel, QDialog,
)
from qfluentwidgets import (
    CardWidget, SubtitleLabel, StrongBodyLabel, BodyLabel, CaptionLabel,
    PrimaryPushButton, PushButton, FluentIcon, MessageBox,
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


# ── world JSON 读写 ──
def _get_world_json_path(world_path: str, pack_type: str) -> str:
    if pack_type == "resource":
        return os.path.join(world_path, "world_resource_packs.json")
    return os.path.join(world_path, "world_behavior_packs.json")


def _read_world_json(world_path: str, pack_type: str) -> list:
    """读取世界包注册文件，返回包列表。"""
    json_path = _get_world_json_path(world_path, pack_type)
    if not os.path.exists(json_path):
        return []
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _write_world_json(world_path: str, pack_type: str, data: list) -> bool:
    """写入世界包注册文件。"""
    json_path = _get_world_json_path(world_path, pack_type)
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        return True
    except Exception:
        return False


def register_pack_to_world(world_path: str, pack_uuid: str, pack_version: str, pack_type: str) -> bool:
    """注册包到世界（写入 world_resource_packs.json 或 world_behavior_packs.json）。"""
    data = _read_world_json(world_path, pack_type)
    for entry in data:
        if entry.get("pack_id") == pack_uuid:
            return False  # 已存在
    data.append({"pack_id": pack_uuid, "version": list(map(int, str(pack_version).split(".")))
                if isinstance(pack_version, str) else pack_version})
    return _write_world_json(world_path, pack_type, data)


def unregister_pack_from_world(world_path: str, pack_uuid: str, pack_type: str) -> bool:
    """从世界注销包。"""
    data = _read_world_json(world_path, pack_type)
    new_data = [e for e in data if e.get("pack_id") != pack_uuid]
    if len(new_data) == len(data):
        return False  # 不存在
    return _write_world_json(world_path, pack_type, new_data)


def _get_world_path(cfg) -> str:
    """获取当前世界文件夹路径。"""
    ctx = get_context()
    server_props = ctx.server_properties
    level_name = "Bedrock level"
    if os.path.exists(server_props):
        try:
            with open(server_props, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("level-name="):
                        level_name = line.split("=", 1)[1]
                        break
        except Exception:
            pass
    return os.path.join(ctx.worlds_dir, level_name)


# ── 扫描包 ──
def _scan_packs(pack_type: str) -> list[dict]:
    """扫描资源包/行为包目录，检查世界注册状态。"""
    ctx = get_context()
    packs_dir = ctx.resource_packs_dir if pack_type == "resource" else ctx.behavior_packs_dir
    world_path = _get_world_path(ctx)
    active_uuids = set()
    if os.path.exists(world_path):
        for entry in _read_world_json(world_path, pack_type):
            active_uuids.add(entry.get("pack_id", ""))

    if not packs_dir or not os.path.exists(packs_dir):
        return []
    result = []
    for name in os.listdir(packs_dir):
        d = os.path.join(packs_dir, name)
        if not os.path.isdir(d):
            continue
        manifest = _read_manifest(d)
        header = manifest.get("header", {})
        uuid = header.get("uuid", "")
        result.append({
            "name": header.get("name", name),
            "desc": header.get("description", ""),
            "uuid": uuid,
            "version": ".".join(str(v) for v in header.get("version", [])),
            "min_engine": header.get("min_engine_version", []),
            "pack_id": header.get("pack_id", ""),
            "modules": header.get("modules", []),
            "dependencies": header.get("dependencies", []),
            "path": d,
            "dirname": name,
            "is_active": uuid in active_uuids,
        })
    # 激活的排前面
    result.sort(key=lambda x: (-x["is_active"], x["name"].lower()))
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
            self.finished.emit(True, f"已添加: {name}（未激活，请点击启用注册到世界）")
        except Exception as e:
            self.finished.emit(False, str(e))


# ── 详情对话框 ──
class PackInfoDialog(QDialog):
    """双击 / 右键查看 manifest 完整信息。"""
    def __init__(self, pack_info: dict, pack_type: str, is_active: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"包详情 - {pack_info['name']}")
        self.resize(560, 500)
        self._pack = pack_info
        self._pack_type = pack_type
        self._is_active = is_active
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

        fl.addWidget(SubtitleLabel(pack_info["name"], frame))
        fl.addWidget(BodyLabel(
            f"类型: {'资源包' if pack_type == 'resource' else '行为包'}  ·  "
            f"状态: {'✅ 已激活' if is_active else '— 未激活'}", frame))
        if pack_info["desc"]:
            desc = CaptionLabel(pack_info["desc"], frame)
            desc.setWordWrap(True)
            desc.setStyleSheet("color: #aaa;")
            fl.addWidget(desc)

        add_field("路径", pack_info["dirname"])
        add_field("UUID", pack_info["uuid"])
        add_field("版本", pack_info["version"])
        add_field("pack_id", pack_info.get("pack_id", ""))

        modules = pack_info.get("modules", [])
        if modules:
            for m in modules:
                add_field(f"模块 [{m.get('type', '?')}]",
                          f"{m.get('uuid', '?')} ({m.get('version', '?')})")

        deps = pack_info.get("dependencies", [])
        if deps:
            fl.addWidget(SubtitleLabel("依赖", frame))
            for d in deps:
                add_field("  •", f"{d.get('uuid', '?')} ({d.get('version', '?')})")

        min_eng = pack_info.get("min_engine", [])
        if min_eng:
            add_field("最低引擎版本", ".".join(str(v) for v in min_eng))

        scroll.setWidget(frame)
        layout.addWidget(scroll)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = PushButton("关闭", self)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)


# ── 页面 ──
class PacksPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._initialized = False
        self._sections: dict = {}
        self._main_window = parent
        inner, layout = wrap_scrollable(self, spacing=12)
        for key, title in [("resource", "资源包"), ("behavior", "行为包")]:
            card = self._build_section(inner, key, title)
            layout.addWidget(card)
        layout.addStretch()

    def showEvent(self, event):
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
            self._refresh_all_themes()
        super().showEvent(event)

    def _refresh_all_themes(self):
        sub_color = "#888" if isDarkTheme() else "#666"
        for sec in self._sections.values():
            self._apply_table_theme(sec["table"])
            sec["status_label"].setStyleSheet(f"color: {sub_color};")
            sec["hint"].setStyleSheet(f"color: {sub_color}; padding: 12px;")

    def refresh_theme(self):
        self._refresh_all_themes()

    def _apply_table_theme(self, table: QTableWidget):
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

    def _build_section(self, inner, pack_type: str, title: str) -> CardWidget:
        card = CardWidget(inner)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 12, 16, 16)
        cl.setSpacing(8)

        hdr = QHBoxLayout()
        hdr.addWidget(SubtitleLabel(title, card))
        hdr.addStretch()
        sub_color = "#888" if isDarkTheme() else "#666"
        # 状态统计
        self._status_label = CaptionLabel("", card)
        self._status_label.setStyleSheet(f"color: {sub_color};")
        hdr.addWidget(self._status_label)
        add_btn = PrimaryPushButton(f"添加{title}", card, FluentIcon.ADD)
        refresh_btn = PushButton("刷新", card, FluentIcon.SYNC)
        hdr.addWidget(add_btn)
        hdr.addWidget(refresh_btn)
        cl.addLayout(hdr)

        # 表格：名称 / 版本 / UUID / 状态 / 操作
        table = QTableWidget(0, 5, card)
        table.setHorizontalHeaderLabels(["名称", "版本", "UUID", "状态", "操作"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        table.setColumnWidth(3, 90)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        table.setColumnWidth(4, 200)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.doubleClicked.connect(lambda idx: self._show_info_for_section(pack_type, idx))
        self._apply_table_theme(table)
        table.verticalHeader().setDefaultSectionSize(36)
        cl.addWidget(table)

        hint = CaptionLabel(
            f"暂无已安装的{title}，点击「添加{title}」导入。\n"
            f"提示：双击行查看详情；启用 = 注册到世界（需停止服务器）", card)
        hint.setStyleSheet(f"color: {sub_color}; padding: 12px;")
        cl.addWidget(hint)

        self._sections[pack_type] = {
            "table": table, "hint": hint, "add_btn": add_btn, "refresh_btn": refresh_btn,
            "status_label": self._status_label, "type": pack_type,
        }

        def _refresh():
            packs = _scan_packs(pack_type)
            hint.setVisible(len(packs) == 0)
            active = sum(1 for p in packs if p["is_active"])
            inactive = len(packs) - active
            self._status_label.setText(f"激活 {active} / 未激活 {inactive}")

            table.setRowCount(len(packs))
            for i, p in enumerate(packs):
                # 名称 + 状态图标
                table.setItem(i, 0, QTableWidgetItem(p["name"]))
                table.setItem(i, 1, QTableWidgetItem(p["version"] or "—"))
                table.setItem(i, 2, QTableWidgetItem(
                    p["uuid"][:12] + "..." if p["uuid"] else "—"))

                # 状态列：✓ 已激活 / — 未激活
                status_item = QTableWidgetItem("✅ 已激活" if p["is_active"] else "— 未激活")
                status_item.setForeground(
                    QColor("#4CAF50") if p["is_active"] else QColor("#888"))
                table.setItem(i, 3, status_item)

                # 操作按钮
                info_btn = PushButton("详情", table)
                info_btn.clicked.connect(lambda checked, pp=p, pt=pack_type: self._show_info(pp, pt))
                toggle_btn = PushButton("禁用" if p["is_active"] else "启用", table)
                toggle_btn.clicked.connect(
                    lambda checked, pp=p, pt=pack_type: self._toggle_pack(pp, pt, _refresh))
                remove_btn = PushButton("移除", table)
                remove_btn.clicked.connect(
                    lambda checked, pp=p: self._remove_pack(pp, _refresh))
                btn_widget = QWidget()
                bl = QHBoxLayout(btn_widget)
                bl.setContentsMargins(0, 0, 0, 0)
                bl.setSpacing(2)
                bl.addWidget(info_btn)
                bl.addWidget(toggle_btn)
                bl.addWidget(remove_btn)
                table.setCellWidget(i, 4, btn_widget)

        def _add():
            ctx = get_context()
            dest = ctx.resource_packs_dir if pack_type == "resource" else ctx.behavior_packs_dir
            if not os.path.isdir(dest):
                os.makedirs(dest, exist_ok=True)
            dlg = QFileDialog(self)
            dlg.setFileMode(QFileDialog.Directory)
            dlg.setOption(QFileDialog.ShowDirsOnly, True)
            if dlg.exec():
                src = dlg.selectedFiles()[0]
                src_manifest = _read_manifest(src)
                src_pack_id = src_manifest.get("header", {}).get("pack_id", "")
                if src_pack_id:
                    existing = _scan_packs(pack_type)
                    for ex in existing:
                        if ex.get("pack_id") == src_pack_id:
                            confirm = MessageBox(
                                "包冲突",
                                f"已存在 pack_id 相同的包：{ex['name']}\n是否仍要添加？",
                                self.window())
                            if not confirm.exec():
                                return
                            break
                self._copy_worker = CopyPackWorker(src, dest, self)
                self._copy_worker.finished.connect(
                    lambda ok, msg: (
                        (toast_success("完成", msg, self.window()) if ok
                         else toast_error("失败", msg, self.window())),
                        _refresh()))
                self._copy_worker.start()

        add_btn.clicked.connect(_add)
        refresh_btn.clicked.connect(_refresh)
        self._sections[pack_type]["refresh"] = _refresh
        return card

    # ── 启用 / 禁用（= 注册到世界 / 从世界注销）──
    def _toggle_pack(self, pack: dict, pack_type: str, refresh_cb):
        world_path = _get_world_path(get_context())
        if not os.path.exists(world_path):
            toast_warning("世界不存在", "请先启动一次服务器以生成世界文件夹",
                          self.window())
            return
        if pack["is_active"]:
            ok = unregister_pack_from_world(world_path, pack["uuid"], pack_type)
            if ok:
                toast_success("已禁用", f"{pack['name']} 已从世界注销", self.window())
            else:
                toast_warning("未注册", f"{pack['name']} 未在激活列表中", self.window())
        else:
            ok = register_pack_to_world(world_path, pack["uuid"], pack["version"], pack_type)
            if ok:
                toast_success("已启用", f"{pack['name']} 已注册到世界", self.window())
            else:
                toast_warning("已注册", f"{pack['name']} 已在激活列表中", self.window())
        refresh_cb()

    def _show_info_for_section(self, pack_type: str, idx):
        table = self._sections[pack_type]["table"]
        row = idx.row()
        packs = _scan_packs(pack_type)
        if row < len(packs):
            self._show_info(packs[row], pack_type)

    def _show_info(self, pack: dict, pack_type: str):
        dlg = PackInfoDialog(pack, pack_type, pack["is_active"], self.window())
        dlg.exec()

    def _remove_pack(self, pack: dict, refresh_cb):
        confirm = MessageBox("确认移除",
                             f"确定要删除包「{pack['name']}」？\n此操作不可撤销。",
                             self.window())
        if not confirm.exec():
            return
        # 先从世界注销
        world_path = _get_world_path(get_context())
        if os.path.exists(world_path) and pack["uuid"]:
            for pt in ("resource", "behavior"):
                unregister_pack_from_world(world_path, pack["uuid"], pt)
        try:
            shutil.rmtree(pack["path"])
            toast_success("已移除", pack["name"], self.window())
        except Exception as e:
            toast_error("移除失败", str(e), self.window())
        refresh_cb()
