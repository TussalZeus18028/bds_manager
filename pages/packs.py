# -*- coding: utf-8 -*-
"""
资源包 / 行为包管理页面。
"""

import os, json, shutil

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QFileDialog, QLabel,
)
from qfluentwidgets import (
    CardWidget, SubtitleLabel, StrongBodyLabel, BodyLabel, CaptionLabel,
    PrimaryPushButton, PushButton, FluentIcon, ProgressBar,
)

from shared.config import get_context
from shared.toast import toast_success, toast_error
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


def _scan_packs(packs_dir: str) -> list[dict]:
    """扫描目录下所有包。"""
    if not packs_dir or not os.path.exists(packs_dir):
        return []
    result = []
    for name in os.listdir(packs_dir):
        d = os.path.join(packs_dir, name)
        if not os.path.isdir(d):
            continue
        manifest = _read_manifest(d)
        header = manifest.get("header", {})
        result.append({
            "name": header.get("name", name),
            "desc": header.get("description", ""),
            "uuid": header.get("uuid", ""),
            "version": ".".join(str(v) for v in header.get("version", [])),
            "path": d,
            "dirname": name,
        })
    result.sort(key=lambda x: x["name"].lower())
    return result


# ── 复制 Worker（后台线程，不卡 UI）──
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


# ── 页面 ──
class PacksPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        inner, layout = wrap_scrollable(self, spacing=12)
        self._sections = {}

        for key, title in [("resource", "资源包"), ("behavior", "行为包")]:
            card = self._build_section(inner, key, title)
            layout.addWidget(card)
        layout.addStretch()

    def _build_section(self, inner, key: str, title: str) -> CardWidget:
        card = CardWidget(inner)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 12, 16, 16)
        cl.setSpacing(8)

        hdr = QHBoxLayout()
        hdr.addWidget(SubtitleLabel(title, card))
        hdr.addStretch()
        add_btn = PrimaryPushButton(f"添加{title}", card, FluentIcon.ADD)
        refresh_btn = PushButton("刷新", card, FluentIcon.SYNC)
        hdr.addWidget(add_btn)
        hdr.addWidget(refresh_btn)
        cl.addLayout(hdr)

        table = QTableWidget(0, 4, card)
        table.setHorizontalHeaderLabels(["名称", "版本", "UUID", "操作"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setStyleSheet("""
            QTableWidget { background: #1e1e1e; color: #ccc; border: 1px solid #3a3a3a; border-radius: 6px; gridline-color: #3a3a3a; }
            QTableWidget::item { padding: 4px 8px; }
            QHeaderView::section { background: #2a2a2a; color: #aaa; border: none; padding: 6px 8px; font-weight: bold; }
        """)
        cl.addWidget(table)

        hint = CaptionLabel(f"暂无已安装的{title}，点击「添加{title}」导入", card)
        hint.setStyleSheet("color: #888; padding: 12px;")
        cl.addWidget(hint)

        # 存储引用
        self._sections[key] = {
            "table": table, "hint": hint, "add_btn": add_btn, "refresh_btn": refresh_btn,
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
            table.setRowCount(len(packs))
            for i, p in enumerate(packs):
                table.setItem(i, 0, QTableWidgetItem(p["name"]))
                table.setItem(i, 1, QTableWidgetItem(p["version"] or "—"))
                table.setItem(i, 2, QTableWidgetItem(p["uuid"][:12] + "..." if p["uuid"] else "—"))
                remove_btn = PushButton("移除", table)
                remove_btn.clicked.connect(
                    lambda checked, d=p["path"]: self._remove_pack(d, _refresh)
                )
                table.setCellWidget(i, 3, remove_btn)

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
        _refresh()

        return card

    def _remove_pack(self, path: str, refresh_cb):
        name = os.path.basename(path)
        try:
            shutil.rmtree(path)
            toast_success("已移除", name, self.window())
        except Exception as e:
            toast_error("移除失败", str(e), self.window())
        refresh_cb()
