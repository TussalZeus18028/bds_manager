# -*- coding: utf-8 -*-
"""
通知中心 —— 持久化存储 + 事件分发（v3.02.00 新增）。

设计：
- 数据存储在 bds_manager_notifications.json（500 条环形缓冲 + 30 天过期）
- notify() 可从任何线程调用，写入存储后通过 Qt 信号广播
- Qt 信号默认 QueuedConnection 跨线程，所以 Worker 线程调用安全
- 等级：error / warning / success / info
- 分类：server / backup / update / player / webhook / system
- action_target：点击通知跳转目标，格式 "page:<name>?key=value"

用法：
    from backend.notifications import notify

    notify("error", "server", "服务器启动失败", str(e), action_target="page:dashboard")
    notify("success", "backup", "备份完成", backup_name, action_target=f"page:world?backup={fn}")
"""

import json
import os
import time
import uuid
import logging
import threading
from dataclasses import dataclass, asdict
from PySide6.QtCore import QObject, Signal

logger = logging.getLogger("bds_manager")

# ---------- 路径 ----------
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOTIFY_FILE = os.path.join(SCRIPT_DIR, "bds_manager_notifications.json")

# ---------- 常量 ----------
MAX_NOTIFICATIONS = 500          # 环形缓冲上限
MAX_AGE_SECONDS = 30 * 86400     # 30 天强制过期

# 允许的 level / category 取值（用于校验 + UI 颜色映射）
LEVELS = ("error", "warning", "success", "info")
CATEGORIES = ("server", "backup", "update", "player", "webhook", "system")


# ---------- 数据模型 ----------
@dataclass
class Notification:
    """单条通知。"""
    id: str
    ts: float          # Unix 秒
    level: str         # error/warning/success/info
    category: str      # server/backup/update/player/webhook/system
    title: str
    body: str = ""
    action_target: str = ""  # 例如 "page:world?backup=Bedrock_xxx.zip"
    read: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "Notification":
        return cls(
            id=str(d.get("id", "")),
            ts=float(d.get("ts", 0.0)),
            level=str(d.get("level", "info")),
            category=str(d.get("category", "system")),
            title=str(d.get("title", "")),
            body=str(d.get("body", "")),
            action_target=str(d.get("action_target", "")),
            read=bool(d.get("read", False)),
        )

    def to_dict(self) -> dict:
        return asdict(self)


# ---------- Qt 事件总线 ----------
class NotificationBus(QObject):
    """全局事件总线。

    信号：
        notification_added(Notification)  —— 新通知写入后发射（含 None = 批量变更后刷新用）
        unread_count_changed(int)        —— 未读数变化
    """
    notification_added = Signal(object)
    unread_count_changed = Signal(int)


_BUS_INSTANCE: NotificationBus | None = None
_BUS_LOCK = threading.Lock()


def get_bus() -> NotificationBus:
    """惰性获取总线（首次调用必须在 QApplication 创建之后）。"""
    global _BUS_INSTANCE
    if _BUS_INSTANCE is not None:
        return _BUS_INSTANCE
    with _BUS_LOCK:
        if _BUS_INSTANCE is None:
            _BUS_INSTANCE = NotificationBus()
        return _BUS_INSTANCE


# ---------- 存储 ----------
class _Store:
    """线程安全的 JSON 文件存储。"""

    def __init__(self):
        self._lock = threading.RLock()  # 必须用 RLock：add() 内调用 _load() 会重入
        self._items: list[dict] = []
        self._loaded = False

    def _load(self):
        """惰性加载（只在第一次访问时读盘）。用 RLock 防止 add() 内重入死锁。"""
        with self._lock:
            if self._loaded:
                return
            try:
                if os.path.exists(NOTIFY_FILE):
                    with open(NOTIFY_FILE, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, list):
                        self._items = data
                    else:
                        logger.warning("通知文件格式异常，应为 list")
                        self._items = []
            except (json.JSONDecodeError, OSError) as e:
                logger.error("加载通知失败: %s", e)
                self._items = []
            self._loaded = True

    def _save(self):
        """原子写入：tmp + fsync + os.replace。"""
        try:
            tmp = NOTIFY_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._items, f, ensure_ascii=False, indent=2)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            os.replace(tmp, NOTIFY_FILE)
        except Exception as e:
            logger.error("保存通知失败: %s", e)

    def _prune(self):
        """清理过期 + 超出上限。"""
        now = time.time()
        # 1. 按时间过期
        self._items = [n for n in self._items if (now - float(n.get("ts", 0))) < MAX_AGE_SECONDS]
        # 2. 按数量上限（最新的在前面，所以直接切片）
        if len(self._items) > MAX_NOTIFICATIONS:
            self._items = self._items[:MAX_NOTIFICATIONS]

    def add(self, n: Notification):
        """新增一条通知到头部。"""
        with self._lock:
            self._load()
            self._items.insert(0, n.to_dict())
            self._prune()
            self._save()

    def get_all(self) -> list[Notification]:
        """返回全部通知（最新在前）。"""
        with self._lock:
            self._load()
            return [Notification.from_dict(d) for d in self._items]

    def get_unread_count(self) -> int:
        """未读数。"""
        with self._lock:
            self._load()
            return sum(1 for n in self._items if not n.get("read", False))

    def mark_all_read(self):
        """全部标记已读。"""
        with self._lock:
            self._load()
            for n in self._items:
                n["read"] = True
            self._save()

    def clear(self):
        """清空全部。"""
        with self._lock:
            self._items = []
            self._save()


_STORE = _Store()


# ---------- 公开 API ----------
def notify(
    level: str,
    category: str,
    title: str,
    body: str = "",
    action_target: str = "",
) -> Notification | None:
    """从任何线程调用：写入存储 + 广播信号。

    Args:
        level: error/warning/success/info（其他值归为 info）
        category: server/backup/update/player/webhook/system（其他值归为 system）
        title: 简短标题（自动截断 80 字）
        body: 详细说明（自动截断 500 字）
        action_target: 点击跳转目标，例 "page:world?backup=xxx"
    """
    if level not in LEVELS:
        level = "info"
    if category not in CATEGORIES:
        category = "system"
    n = Notification(
        id=f"n_{int(time.time() * 1000)}_{uuid.uuid4().hex[:4]}",
        ts=time.time(),
        level=level,
        category=category,
        title=title[:80],
        body=body[:500],
        action_target=action_target,
        read=False,
    )
    _STORE.add(n)
    # 广播信号（跨线程时 Qt 自动 QueuedConnection）
    try:
        bus = get_bus()
        bus.notification_added.emit(n)
        unread = _STORE.get_unread_count()
        bus.unread_count_changed.emit(unread)
    except RuntimeError:
        # QApplication 尚未初始化，仅写存储
        pass
    except Exception as e:
        logger.debug("广播通知信号失败: %s", e)
    return n


def get_all() -> list[Notification]:
    """获取全部通知（最新在前）。"""
    return _STORE.get_all()


def get_unread_count() -> int:
    """未读数。"""
    return _STORE.get_unread_count()


def mark_all_read():
    """标记全部已读 + 广播信号。"""
    _STORE.mark_all_read()
    try:
        bus = get_bus()
        # 用 None 触发 UI 刷新（notification_added 槽应能处理 None）
        bus.notification_added.emit(None)
        bus.unread_count_changed.emit(0)
    except RuntimeError:
        pass


def clear_all():
    """清空全部 + 广播信号。"""
    _STORE.clear()
    try:
        bus = get_bus()
        bus.notification_added.emit(None)
        bus.unread_count_changed.emit(0)
    except RuntimeError:
        pass


def parse_action_target(target: str) -> tuple[str, dict]:
    """解析 action_target 为 (page_name, params)。

    例：'page:world?backup=xxx&highlight=true'
       → ('world', {'backup': 'xxx', 'highlight': 'true'})
    """
    if not target or not target.startswith("page:"):
        return ("", {})
    body = target[5:]
    page, _, query = body.partition("?")
    params: dict[str, str] = {}
    if query:
        for kv in query.split("&"):
            if "=" in kv:
                k, _, v = kv.partition("=")
                params[k] = v
    return (page, params)