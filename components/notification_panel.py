# -*- coding: utf-8 -*-
"""
通知面板组件（v3.02.00 新增）。

包含：
- BellButton：顶部导航栏右侧的铃铛按钮，未读数小红点
- NotificationDrawer：右侧滑出抽屉，承载通知列表
- NotificationItemWidget：单条通知行（点击 → 触发跳转）

设计原则：
- 铃铛父级 = 主窗口（不挂到 NavigationInterface 内部，避免依赖其内部结构）
- 抽屉 = 主窗口的子控件，使用 QPropertyAnimation 做滑入滑出
- 通知列表 = 简单 QWidget 列表（避免 QListView 复杂度，按需扩展）
"""

import time
from datetime import datetime
from PySide6.QtCore import Qt, Signal, QPoint, QPropertyAnimation, QEasingCurve, QSize, QTimer
from PySide6.QtGui import QPainter, QColor, QFont, QFontMetrics, QPen, QBrush, QIcon, QCursor
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QScrollArea, QPushButton,
    QFrame, QSizePolicy, QApplication, QGraphicsDropShadowEffect,
)

from qfluentwidgets import FluentIcon, isDarkTheme

from backend.notifications import (
    get_all, get_unread_count, mark_all_read, clear_all, parse_action_target,
    Notification, get_bus,
)


# ---------- 颜色常量（按等级 + 深浅主题）----------
LEVEL_COLORS = {
    "error":   ("#ff4444", "#ff7777"),
    "warning": ("#ffaa33", "#ffcc66"),
    "success": ("#44cc66", "#66dd88"),
    "info":    ("#4488ff", "#77aaff"),
}
CATEGORY_ICONS = {
    "server":  "🖥",
    "backup":  "📦",
    "update":  "🔄",
    "player":  "👤",
    "webhook": "🔗",
    "system":  "⚙",
}


def _format_time(ts: float) -> str:
    """时间戳转可读字符串（相对时间 + 短日期）。"""
    delta = time.time() - ts
    if delta < 60:
        return "刚刚"
    elif delta < 3600:
        return f"{int(delta // 60)} 分钟前"
    elif delta < 86400:
        return f"{int(delta // 3600)} 小时前"
    elif delta < 7 * 86400:
        return f"{int(delta // 86400)} 天前"
    else:
        return datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")


# ════════════════════════════════════════════
#  铃铛按钮
# ════════════════════════════════════════════
class BellButton(QWidget):
    """顶部导航栏右侧的铃铛按钮。

    视觉：
    - 圆形 36×36 按钮
    - 铃铛图标 + 未读数红点（>99 显示 99+）
    """
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._unread = 0
        self._hovered = False
        self.setFixedSize(36, 36)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("通知中心")
        self.setAttribute(Qt.WA_TranslucentBackground)

    def set_unread(self, n: int):
        self._unread = max(0, n)
        self.update()
        self.setToolTip(f"通知中心（{self._unread} 条未读）" if self._unread else "通知中心")

    def enterEvent(self, event):
        self._hovered = True
        self.update()

    def leaveEvent(self, event):
        self._hovered = False
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        # 悬停背景
        if self._hovered:
            p.setBrush(QColor(255, 255, 255, 25))
            p.setPen(Qt.NoPen)
            p.drawEllipse(rect)
        # 铃铛图标（Unicode + 大字号）
        p.setPen(QColor("#ccddee"))
        f = QFont("Segoe UI Symbol", 14)
        p.setFont(f)
        p.drawText(rect, Qt.AlignCenter, "🔔")
        # 未读小红点
        if self._unread > 0:
            badge_size = 16 if self._unread < 10 else 20
            badge_x = rect.right() - badge_size + 2
            badge_y = rect.top() - 2
            # 红圈背景
            p.setBrush(QColor("#ff4444"))
            p.setPen(QPen(QColor("#1e1e1e"), 1.5))
            p.drawEllipse(badge_x, badge_y, badge_size, badge_size)
            # 数字
            text = str(self._unread) if self._unread < 100 else "99+"
            p.setPen(QColor("#ffffff"))
            f2 = QFont("Microsoft YaHei", 8)
            f2.setBold(True)
            p.setFont(f2)
            p.drawText(badge_x, badge_y, badge_size, badge_size,
                       Qt.AlignCenter, text)


# ════════════════════════════════════════════
#  单条通知行
# ════════════════════════════════════════════
class NotificationItemWidget(QFrame):
    """单条通知行：色块 + 标题 + body + 时间 + 跳转箭头。"""
    clicked = Signal(object)  # 携带 Notification

    def __init__(self, notification: Notification, parent=None):
        super().__init__(parent)
        self.n = notification
        self._hovered = False
        self.setFixedHeight(64)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("notifItem")
        # 未读项左侧细线标识
        bg = "#2a2a2a" if isDarkTheme() else "#f5f5f5"
        self.setStyleSheet(f"""
            QFrame#notifItem {{ background: {bg}; border-radius: 6px; }}
            QFrame#notifItem:hover {{ background: {"#353535" if isDarkTheme() else "#eaeaea"}; }}
        """)

    def enterEvent(self, event):
        self._hovered = True
        self.update()

    def leaveEvent(self, event):
        self._hovered = False
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.n)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        # 左侧色条（按 level）
        accent_hex, _ = LEVEL_COLORS.get(self.n.level, LEVEL_COLORS["info"])
        p.setBrush(QColor(accent_hex))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(0, 8, 4, rect.height() - 16, 2, 2)
        # 类别图标
        icon = CATEGORY_ICONS.get(self.n.category, "•")
        p.setPen(QColor("#aabbcc"))
        f = QFont("Segoe UI Symbol", 13)
        p.setFont(f)
        p.drawText(rect.adjusted(14, 8, 0, 0), Qt.AlignLeft | Qt.AlignTop, icon)
        # 标题（粗体）
        title_color = "#ffffff" if isDarkTheme() else "#1a1a1a"
        body_color = "#a0a8b0" if isDarkTheme() else "#666666"
        time_color = "#777" if isDarkTheme() else "#999"
        title_font = QFont("Microsoft YaHei", 10)
        title_font.setBold(True)
        p.setFont(title_font)
        p.setPen(QColor(title_color))
        title_rect = rect.adjusted(40, 8, -50, 0)
        fm = QFontMetrics(title_font)
        p.drawText(title_rect, Qt.AlignLeft | Qt.AlignTop,
                   fm.elidedText(self.n.title, Qt.ElideRight, title_rect.width()))
        # body（小字 + 灰）
        if self.n.body:
            body_font = QFont("Microsoft YaHei", 9)
            p.setFont(body_font)
            p.setPen(QColor(body_color))
            body_rect = rect.adjusted(40, 28, -50, -8)
            fm2 = QFontMetrics(body_font)
            p.drawText(body_rect, Qt.AlignLeft | Qt.AlignTop,
                       fm2.elidedText(self.n.body, Qt.ElideRight, body_rect.width()))
        # 时间（右上）
        time_font = QFont("Microsoft YaHei", 8)
        p.setFont(time_font)
        p.setPen(QColor(time_color))
        time_text = _format_time(self.n.ts)
        p.drawText(rect.adjusted(0, 10, -10, 0), Qt.AlignRight | Qt.AlignTop, time_text)
        # 跳转箭头（右下）
        if self.n.action_target:
            arrow_font = QFont("Segoe UI Symbol", 10)
            p.setFont(arrow_font)
            p.setPen(QColor("#666"))
            p.drawText(rect.adjusted(0, 0, -10, -8), Qt.AlignRight | Qt.AlignBottom, "→")
        # 未读项：小蓝点
        if not self.n.read:
            p.setBrush(QColor("#4488ff"))
            p.setPen(Qt.NoPen)
            p.drawEllipse(rect.right() - 14, rect.top() + 10, 6, 6)


# ════════════════════════════════════════════
#  抽屉（右侧滑出）
# ════════════════════════════════════════════
class NotificationDrawer(QWidget):
    """右侧滑出抽屉。

    视觉：
    - 宽度 380px
    - 顶部：标题 + "全部已读" + "清空"按钮
    - 过滤行：chip（全部/错误/服务器/备份/更新/webhook）
    - 中部：可滚动列表
    """
    closed = Signal()
    navigate_requested = Signal(str, dict)  # (page_name, params)

    FILTER_ALL = "all"
    FILTER_MAP = {
        "all":     ("全部",     None),
        "error":   ("错误",     "error"),
        "server":  ("服务器",   "server"),
        "backup":  ("备份",     "backup"),
        "update":  ("更新",     "update"),
        "webhook": ("Webhook",  "webhook"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filter = self.FILTER_ALL
        self._build_ui()
        self._bus = get_bus()
        self._bus.notification_added.connect(self._on_notification_event)
        self._bus.unread_count_changed.connect(self._on_unread_changed)
        self.refresh()

    # ---------- UI 构建 ----------
    def _build_ui(self):
        self.setFixedWidth(380)
        # 主布局
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        bg = "#1e1e1e" if isDarkTheme() else "#fafafa"
        border = "#333" if isDarkTheme() else "#ddd"
        self.setStyleSheet(f"""
            NotificationDrawer {{ background: {bg}; border-left: 1px solid {border}; }}
        """)
        # 标题栏
        header = QWidget()
        header.setFixedHeight(50)
        hlay = QHBoxLayout(header)
        hlay.setContentsMargins(16, 8, 12, 8)
        title = QLabel("通知")
        title_font = QFont("Microsoft YaHei", 13)
        title_font.setBold(True)
        title.setFont(title_font)
        hlay.addWidget(title)
        hlay.addStretch(1)
        self._btn_read = QPushButton("全部已读")
        self._btn_read.setCursor(Qt.PointingHandCursor)
        self._btn_read.clicked.connect(self._on_mark_all_read)
        self._btn_clear = QPushButton("清空")
        self._btn_clear.setCursor(Qt.PointingHandCursor)
        self._btn_clear.clicked.connect(self._on_clear_all)
        btn_font = QFont("Microsoft YaHei", 9)
        self._btn_read.setFont(btn_font)
        self._btn_clear.setFont(btn_font)
        hlay.addWidget(self._btn_read)
        hlay.addSpacing(6)
        hlay.addWidget(self._btn_clear)
        outer.addWidget(header)
        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"color: {border};")
        outer.addWidget(line)
        # 过滤行
        filter_row = QWidget()
        filter_row.setFixedHeight(40)
        flay = QHBoxLayout(filter_row)
        flay.setContentsMargins(12, 6, 12, 6)
        flay.setSpacing(6)
        self._chip_buttons: dict[str, QPushButton] = {}
        for key, (label, _) in self.FILTER_MAP.items():
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedHeight(26)
            btn.setCursor(Qt.PointingHandCursor)
            f = QFont("Microsoft YaHei", 9)
            btn.setFont(f)
            btn.clicked.connect(lambda _checked=False, k=key: self._set_filter(k))
            self._chip_buttons[key] = btn
            flay.addWidget(btn)
        flay.addStretch(1)
        outer.addWidget(filter_row)
        # 滚动区
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._list_container = QWidget()
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(10, 4, 10, 10)
        self._list_layout.setSpacing(6)
        self._list_layout.addStretch(1)
        self._scroll.setWidget(self._list_container)
        outer.addWidget(self._scroll, 1)
        # 初始化 chip 样式
        self._update_chip_style()
        self._set_filter(self.FILTER_ALL)

    # ---------- 过滤 ----------
    def _set_filter(self, key: str):
        self._filter = key
        for k, btn in self._chip_buttons.items():
            btn.setChecked(k == key)
        self._update_chip_style()
        self.refresh()

    def _update_chip_style(self):
        for k, btn in self._chip_buttons.items():
            if btn.isChecked():
                btn.setStyleSheet("""
                    QPushButton {
                        background: #0DC5D4; color: #ffffff;
                        border: none; border-radius: 13px;
                        padding: 2px 12px;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background: #2a2a2a; color: #aabbcc;
                        border: none; border-radius: 13px;
                        padding: 2px 12px;
                    }
                    QPushButton:hover { background: #353535; }
                """)

    # ---------- 列表渲染 ----------
    def refresh(self):
        # 清空现有项（保留 addStretch）
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        # 加载并过滤
        items = get_all()
        if self._filter != self.FILTER_ALL:
            _, ftype = self.FILTER_MAP[self._filter]
            if ftype in ("error",):
                items = [n for n in items if n.level == "error"]
            else:
                items = [n for n in items if n.category == ftype]
        if not items:
            empty = QLabel("暂无通知")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet("color: #666; padding: 40px; font-size: 12px;")
            self._list_layout.insertWidget(0, empty)
            return
        # 渲染（最多 200 条，避免卡顿）
        for n in items[:200]:
            row = NotificationItemWidget(n, self._list_container)
            row.clicked.connect(self._on_item_clicked)
            self._list_layout.insertWidget(self._list_layout.count() - 1, row)

    # ---------- 信号处理 ----------
    def _on_notification_event(self, n):
        """通知添加 / mark_all_read / clear_all 时刷新列表。"""
        self.refresh()

    def _on_unread_changed(self, n):
        """未读数变化由主窗口的 bell 处理，这里不用管。"""
        pass

    def _on_mark_all_read(self):
        mark_all_read()

    def _on_clear_all(self):
        from qfluentwidgets import MessageBox
        if MessageBox(
            "清空通知", "确定要清空全部通知吗？此操作不可撤销。",
            self.window()
        ).exec():
            clear_all()

    def _on_item_clicked(self, n: Notification):
        # 标记单条已读（如果未读）
        if not n.read:
            # 直接更新 JSON，简单粗暴
            import json
            from backend.notifications import NOTIFY_FILE
            try:
                with open(NOTIFY_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for item in data:
                    if item.get("id") == n.id:
                        item["read"] = True
                        break
                with open(NOTIFY_FILE + ".tmp", "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                import os
                os.replace(NOTIFY_FILE + ".tmp", NOTIFY_FILE)
            except Exception:
                pass
            n.read = True
        # 触发跳转
        page, params = parse_action_target(n.action_target)
        if page:
            self.navigate_requested.emit(page, params)
        # 关闭抽屉
        self.hide_drawer()

    # ---------- 显隐控制 ----------
    def show_drawer(self):
        """在主窗口右侧显示。"""
        if self.parent() is None:
            return
        parent = self.parent()
        pw = parent.width()
        ph = parent.height()
        # 起始位置：屏幕外右侧
        self.setGeometry(pw, 0, self.width(), ph)
        self.show()
        self.raise_()
        self.refresh()
        # 滑入动画
        anim = QPropertyAnimation(self, b"geometry")
        anim.setDuration(280)
        anim.setStartValue(self.geometry())
        anim.setEndValue(self.geometry().adjusted(-self.width(), 0, -self.width(), 0))
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()
        # 标记已读（仅关闭时）

    def hide_drawer(self):
        """滑出隐藏。"""
        if not self.isVisible():
            self.closed.emit()
            return
        anim = QPropertyAnimation(self, b"geometry")
        anim.setDuration(220)
        anim.setStartValue(self.geometry())
        anim.setEndValue(self.geometry().adjusted(self.width(), 0, self.width(), 0))
        anim.setEasingCurve(QEasingCurve.InCubic)
        anim.finished.connect(self._on_hide_finished)
        anim.start()

    def _on_hide_finished(self):
        self.hide()
        self.closed.emit()