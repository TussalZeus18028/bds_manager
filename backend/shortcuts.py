# -*- coding: utf-8 -*-
"""
快捷键管理器（v3.02.00 新增）。

设计：
- 单例 ShortcutManager，挂在主窗口上
- 持有 (action_id, label, scope, default_key, current_key, callback) 记录
- QShortcut 重建式注册：用户改键后销毁旧的、注册新的
- 作用域（scope）：global / console / dashboard / world / ...
- 冲突检测：同 scope 内 + 全局 vs 局部
- 持久化：用户覆盖写入 bds_manager_config.json 的 shortcuts 字段

用法：
    mgr = ShortcutManager.get_instance()
    mgr.set_main_window(self)
    mgr.register("restart_server", "重启服务器", "global", "Ctrl+R", self._on_restart)
    mgr.set_scope("dashboard")  # 切页时调用
    mgr.apply_user_overrides()  # 从 config 加载用户自定义
"""

import logging
from dataclasses import dataclass, field, asdict
from typing import Callable
from PySide6.QtCore import Qt, QObject
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtWidgets import QWidget

from shared.config import config_mgr

logger = logging.getLogger("bds_manager")


# ---------- 数据模型 ----------
@dataclass
class ShortcutRecord:
    """单条快捷键记录。"""
    action_id: str           # 唯一 id
    label: str               # UI 显示名
    scope: str               # "global" / page_name
    default_key: str         # 默认键位（人类可读）
    current_key: str = ""    # 当前键位（用户可改）
    callback_id: str = ""    # 注册时分配的回调 id（内部用）

    def __post_init__(self):
        if not self.current_key:
            self.current_key = self.default_key


# ---------- 单例 ----------
class ShortcutManager(QObject):
    """快捷键管理器单例。"""

    _instance: "ShortcutManager | None" = None

    @classmethod
    def get_instance(cls) -> "ShortcutManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        super().__init__()
        self._main_window: QWidget | None = None
        self._records: dict[str, ShortcutRecord] = {}
        self._shortcuts: dict[str, QShortcut] = {}
        self._callbacks: dict[str, Callable] = {}
        self._current_scope = "global"

    # ---------- 初始化 ----------
    def set_main_window(self, mw: QWidget):
        self._main_window = mw

    def register(
        self,
        action_id: str,
        label: str,
        scope: str,
        default_key: str,
        callback: Callable,
    ):
        """注册一个快捷键。重复注册同一 action_id 会覆盖。"""
        self._records[action_id] = ShortcutRecord(
            action_id=action_id,
            label=label,
            scope=scope,
            default_key=default_key,
        )
        self._callbacks[action_id] = callback
        self._rebuild_shortcut(action_id)

    # ---------- 作用域 ----------
    def set_scope(self, scope: str):
        """切换当前页面时调用，重新评估哪些快捷键应启用。"""
        self._current_scope = scope
        for aid, sc in self._shortcuts.items():
            rec = self._records.get(aid)
            if rec is None:
                continue
            sc.setEnabled(rec.scope in ("global", scope))

    def current_scope(self) -> str:
        return self._current_scope

    # ---------- 用户改键 ----------
    def remap(self, action_id: str, new_key: str) -> tuple[bool, list[str]]:
        """改键。返回 (是否成功, 冲突的 action_id 列表)。"""
        if action_id not in self._records:
            return (False, [])
        conflicts = self.detect_conflicts(new_key, self._records[action_id].scope, action_id)
        if conflicts:
            return (False, conflicts)
        self._records[action_id].current_key = new_key
        self._rebuild_shortcut(action_id)
        return (True, [])

    def force_remap(self, action_id: str, new_key: str):
        """强制改键（用户已确认覆盖冲突）。"""
        if action_id not in self._records:
            return
        self._records[action_id].current_key = new_key
        self._rebuild_shortcut(action_id)

    def reset_to_default(self, action_id: str = ""):
        """恢复默认（action_id 为空时全部恢复）。"""
        targets = [action_id] if action_id else list(self._records.keys())
        for aid in targets:
            rec = self._records.get(aid)
            if rec is None:
                continue
            rec.current_key = rec.default_key
            self._rebuild_shortcut(aid)

    # ---------- 冲突检测 ----------
    def detect_conflicts(
        self, key: str, scope: str, exclude_action_id: str = "",
    ) -> list[str]:
        """返回与 (key, scope) 冲突的所有 action_id。

        冲突规则：
        - 同 scope 内 + 同 key → 冲突
        - scope="global" 与任何具体 scope 同 key → 冲突
        - 具体 scope 与 scope="global" 同 key → 冲突
        """
        if not key:
            return []
        conflicts: list[str] = []
        for aid, rec in self._records.items():
            if aid == exclude_action_id:
                continue
            if rec.current_key != key:
                continue
            # 任一为 global 即视为冲突
            if rec.scope == "global" or scope == "global":
                conflicts.append(aid)
                continue
            # 否则需 scope 完全相等
            if rec.scope == scope:
                conflicts.append(aid)
        return conflicts

    # ---------- 查询 ----------
    def get_record(self, action_id: str) -> ShortcutRecord | None:
        return self._records.get(action_id)

    def list_records(self, scope: str = "") -> list[ShortcutRecord]:
        items = list(self._records.values())
        if scope:
            items = [r for r in items if r.scope == scope]
        return items

    def get_user_overrides(self) -> dict[str, str]:
        """返回所有非默认键位 {action_id: current_key}。"""
        return {
            aid: rec.current_key
            for aid, rec in self._records.items()
            if rec.current_key != rec.default_key
        }

    # ---------- 持久化 ----------
    def apply_user_overrides(self, overrides: dict[str, str] | None = None):
        """从 config 加载用户自定义键位并应用。"""
        if overrides is None:
            overrides = config_mgr.get("shortcuts") or {}
        for aid, key in overrides.items():
            rec = self._records.get(aid)
            if rec and key:
                rec.current_key = key
                self._rebuild_shortcut(aid)

    def save_user_overrides(self):
        """把当前非默认键位写入 config。"""
        overrides = self.get_user_overrides()
        config_mgr.set("shortcuts", overrides)
        config_mgr.save()

    # ---------- 内部 ----------
    def _rebuild_shortcut(self, action_id: str):
        """销毁旧的 QShortcut，创建新的。"""
        if self._main_window is None:
            return
        # 销毁旧的
        old = self._shortcuts.pop(action_id, None)
        if old is not None:
            try:
                old.setParent(None)
                old.deleteLater()
            except RuntimeError:
                pass
        # 创建新的
        rec = self._records.get(action_id)
        callback = self._callbacks.get(action_id)
        if rec is None or callback is None or not rec.current_key:
            return
        try:
            sc = QShortcut(QKeySequence(rec.current_key), self._main_window)
        except Exception as e:
            logger.warning("创建 QShortcut 失败 [%s]: %s", action_id, e)
            return
        sc.setContext(Qt.WindowShortcut)
        sc.activated.connect(callback)
        sc.setEnabled(rec.scope in ("global", self._current_scope))
        self._shortcuts[action_id] = sc


# ---------- 默认快捷键定义 ----------
# 启动时由 main.py 用 register() 注册；此处集中维护便于文档化
DEFAULT_SHORTCUTS: list[tuple[str, str, str, str]] = [
    # (action_id, label, scope, default_key)
    ("command_palette",      "打开命令面板",   "global",    "Ctrl+K"),
    ("restart_tool",         "重启工具",       "global",    "Ctrl+Shift+R"),
    ("restart_server",       "重启服务器",     "global",    "Ctrl+R"),
    ("manual_backup",        "立即手动备份",   "global",    "Ctrl+B"),
    ("save_world",           "保存世界",       "global",    "Ctrl+S"),
    ("stop_server",          "停止服务器",     "global",    "Ctrl+T"),
    ("open_settings",        "打开设置页",     "global",    "Ctrl+,"),
    ("toggle_theme",         "切换深浅主题",   "global",    "Ctrl+Shift+L"),
    ("open_world",           "打开世界页",     "global",    "Ctrl+Shift+B"),
    ("clear_console",        "清屏控制台",     "console",   "Ctrl+L"),
    ("search_console",       "搜索控制台",     "console",   "Ctrl+F"),
    ("refresh_dashboard",    "刷新仪表盘",     "dashboard", "F5"),
    # Ctrl+1..7 切页（保留旧实现，在 main.py 中单独处理）
]