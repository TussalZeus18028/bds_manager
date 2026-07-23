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
from PySide6.QtCore import Qt, Signal, QPoint, QRect, QEvent, QPropertyAnimation, QEasingCurve, QSize, QTimer
from PySide6.QtGui import QPainter, QColor, QFont, QFontMetrics, QPen, QBrush, QIcon, QCursor
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QScrollArea, QPushButton, QToolButton,
    QFrame, QSizePolicy, QApplication, QGraphicsDropShadowEffect,
)

from qfluentwidgets import (
    FluentIcon, isDarkTheme,
    PushButton as FluentPushButton,
    StrongBodyLabel, BodyLabel, CaptionLabel,
)

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
class BellButton(QToolButton):
    """顶部导航栏右侧的通知按钮。

    设计原则（v3.02.01 重设计）：
    - 使用 FluentIcon.MESSAGE（Fluent 风格矢量图，主题感知）替代丑的 Unicode emoji
    - QToolButton 提供原生 hover/pressed 态
    - 右上角徽章用 Qt 抗锯齿绘制，超过 99 显示 99+
    - 整体尺寸 36×36，与主窗口的标题栏按钮一致
    """
    # 注意：不要在这里重新定义 clicked = Signal()！会 shadow 掉 QToolButton 的原生 clicked，
    # 导致用户点击按钮时父类 emit 的 clicked 信号不会传到我们的 connect 槽。

    def __init__(self, parent=None):
        super().__init__(parent)
        self._unread = 0
        self.setFixedSize(QSize(36, 36))
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("通知中心")
        # 图标（theme-aware，自适应深浅主题）
        self.setIcon(FluentIcon.MESSAGE.icon())
        self.setIconSize(QSize(18, 18))
        # 透明背景
        self.setStyleSheet("QToolButton { background: transparent; border: none; }")

    def set_unread(self, n: int):
        self._unread = max(0, n)
        self.setToolTip(f"通知中心（{self._unread} 条未读）" if self._unread else "通知中心")
        self.update()  # 触发 paintEvent 重绘徽章

    def paintEvent(self, event):
        super().paintEvent(event)
        # 仅在有未读时绘制右上角徽章
        if self._unread <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        # 徽章尺寸：个位数 16，双位数 20
        badge_w = 16 if self._unread < 10 else 20
        badge_h = 16
        # 定位右上角
        bx = rect.right() - badge_w + 3
        by = rect.top() - 2
        # 阴影/外圈（深色背景时让红点更立体）
        ring_color = QColor("#1e1e1e") if isDarkTheme() else QColor("#fafafa")
        p.setPen(QPen(ring_color, 1.5))
        p.setBrush(QColor("#e74856"))  # Fluent 红色
        p.drawRoundedRect(bx, by, badge_w, badge_h, badge_w / 2, badge_h / 2)
        # 数字
        text = str(self._unread) if self._unread < 100 else "99+"
        text_color = QColor("#ffffff")
        p.setPen(text_color)
        f = QFont("Microsoft YaHei", 8)
        f.setBold(True)
        p.setFont(f)
        p.drawText(bx, by, badge_w, badge_h, Qt.AlignCenter, text)


# ════════════════════════════════════════════
#  单条通知行
# ════════════════════════════════════════════
class NotificationItemWidget(QFrame):
    """单条通知行：色块 + 标题 + body + 时间 + 跳转箭头。

    交互（v3.02.01）：
    - **单击**：展开/收起详情（完整 body + action_target 路径）
    - **双击**：跳转目标页（如果有 action_target）→ 触发 navigate_requested
    - **右侧 → 按钮**：跳转目标页（明确的跳转意图）
    """
    clicked = Signal(object)  # 单击展开（携带 Notification）
    navigate_requested = Signal(object)  # 双击/按钮跳转（携带 Notification）

    def __init__(self, notification: Notification, parent=None):
        super().__init__(parent)
        self.n = notification
        self._hovered = False
        self._expanded = False  # 是否展开详情
        self._collapsed_height = 64
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("notifItem")
        # v3.02.01: 现代化主题（暗色用 #2f3136，亮色用 #f0f0f0）
        bg = "#2f3136" if isDarkTheme() else "#f0f0f0"
        bg_hover = "#36393f" if isDarkTheme() else "#e6e6e6"
        self.setStyleSheet(f"""
            QFrame#notifItem {{ background: {bg}; border-radius: 6px; }}
            QFrame#notifItem:hover {{ background: {bg_hover}; }}
        """)
        # v3.02.01: 根据 body 长度初始化高度
        self._update_height()

    def enterEvent(self, event):
        super().enterEvent(event)  # v3.02.01: 让 QSS :hover 选择器生效
        self._hovered = True
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._hovered = False
        self.update()

    def _has_body(self) -> bool:
        """是否有非空 body 需要展示。"""
        return bool(self.n.body) or bool(self.n.action_target)

    def _update_height(self):
        """根据展开状态 + body 长度动态调整高度。"""
        if not self._has_body():
            self.setMinimumHeight(self._collapsed_height)
            self.setMaximumHeight(self._collapsed_height)
            self.setFixedHeight(self._collapsed_height)
            return
        # 估算行数：每 35 字符 1 行（中文），每行 14px
        full_text = self.n.body or ""
        if self.n.action_target:
            full_text = f"{full_text}\n  → {self.n.action_target}" if full_text else f"  → {self.n.action_target}"
        lines = max(2, len(full_text) // 35 + 1)
        # 标题区 36px + body 区 = lines * 16
        h = 36 + lines * 16 + 12  # +12 padding
        if self._expanded:
            h = max(h, 100)
        h = min(200, max(self._collapsed_height, h))
        # 关键：用 setFixedHeight（不用 min/max），让 layout 立即生效
        self.setFixedHeight(h)
        # 同时设 min/max（防止 layout 改变时被压扁）
        self.setMinimumHeight(h)
        self.setMaximumHeight(h)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # 单击：切换展开
            if self._has_body():
                self._expanded = not self._expanded
                self._update_height()
                self.update()
                # 通知容器调整（list layout 需要刷新）
                if self.parent():
                    self.parent().updateGeometry()
            self.clicked.emit(self.n)
            # v3.02.01 fix: accept 阻止事件冒泡到外层 mask（mask 会错误地关闭抽屉）
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        # 双击：触发跳转（如果有 action_target）
        if event.button() == Qt.LeftButton and self.n.action_target:
            self.navigate_requested.emit(self.n)
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        # 左侧色条（按 level）
        accent_hex, _ = LEVEL_COLORS.get(self.n.level, LEVEL_COLORS["info"])
        p.setBrush(QColor(accent_hex))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(0, 8, 4, rect.height() - 16, 2, 2)
        # 类别图标（主题感知：深色用浅蓝灰，浅色用深灰）
        icon = CATEGORY_ICONS.get(self.n.category, "•")
        icon_color = "#aabbcc" if isDarkTheme() else "#666666"
        p.setPen(QColor(icon_color))
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
            # v3.02.01: 展开时显示完整 body，否则单行省略
            if self._expanded:
                p.drawText(body_rect, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, self.n.body)
            else:
                p.drawText(body_rect, Qt.AlignLeft | Qt.AlignTop,
                           fm2.elidedText(self.n.body, Qt.ElideRight, body_rect.width()))
        # 跳转路径（仅展开时显示）
        if self._expanded and self.n.action_target:
            link_font = QFont("Consolas", 8)
            p.setFont(link_font)
            p.setPen(QColor("#0DC5D4"))
            link_rect = rect.adjusted(40, rect.height() - 22, -10, -4)
            fm3 = QFontMetrics(link_font)
            p.drawText(link_rect, Qt.AlignLeft | Qt.AlignTop,
                       fm3.elidedText(self.n.action_target, Qt.ElideRight, link_rect.width()))
        # 时间（右上）
        time_font = QFont("Microsoft YaHei", 8)
        p.setFont(time_font)
        p.setPen(QColor(time_color))
        time_text = _format_time(self.n.ts)
        p.drawText(rect.adjusted(0, 10, -10, 0), Qt.AlignRight | Qt.AlignTop, time_text)
        # 跳转箭头（右下，主题感知）—— 可点击（仅在有 action_target 时）
        if self.n.action_target:
            arrow_font = QFont("Segoe UI Symbol", 11)
            p.setFont(arrow_font)
            # v3.02.01: hover 时高亮（蓝色），告诉用户「可点击」
            arrow_color = "#0DC5D4" if self._hovered else ("#666" if isDarkTheme() else "#aaa")
            p.setPen(QColor(arrow_color))
            p.drawText(rect.adjusted(0, 0, -10, -8), Qt.AlignRight | Qt.AlignBottom, "→")
        # 展开/收起标记（右下角，仅有 body 的项显示）
        if self._has_body():
            mark_font = QFont("Segoe UI Symbol", 9)
            p.setFont(mark_font)
            mark_color = "#888" if isDarkTheme() else "#aaa"
            p.setPen(QColor(mark_color))
            # ▼ 展开 / ▶ 收起
            mark_text = "▲" if self._expanded else "▼"
            mark_x = rect.right() - (40 if self.n.action_target else 14)
            p.drawText(mark_x, rect.bottom() - 8, mark_text)
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

    关闭机制（v3.02.01 fix）：
    - 早期版本用 mask widget（透明遮罩）吃点击 → 但 QWidget::mousePressEvent 默认
      event.ignore()，所有子控件的点击都会冒泡到 mask → 连单击展开/双击跳转都被吃掉
    - 现在改用 eventFilter 监听主窗口，按点击位置精确判断是否在 drawer 外
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
        "player":  ("玩家",     "player"),
        "toast":   ("通知",     "toast"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filter = self.FILTER_ALL
        self._is_installed = False  # eventFilter 安装状态（避免重复 install）
        self._bus = get_bus()
        self._bus.notification_added.connect(self._on_notification_event)
        self._bus.unread_count_changed.connect(self._on_unread_changed)
        self._build_ui()
        self.refresh()

    def eventFilter(self, obj, event):
        """v3.02.01：监听主窗口的鼠标按下事件，按点击位置判断要不要关闭抽屉。

        比 mask widget 更可靠：
        - 精确判断点击位置是否在 drawer 矩形内 → 不会误吃 drawer 内部点击
        - 不影响 drawer 子控件的事件冒泡（mask 方案会拦截所有事件）
        """
        if (self._is_installed and obj is self.parent()
                and event.type() == QEvent.Type.MouseButtonPress):
            # event.position() 是相对 obj（主窗口）的坐标（PySide6 推荐）
            try:
                click_pos = event.position().toPoint()
            except Exception:
                click_pos = event.pos()
            drawer_topleft = self.mapTo(self.parent(), QPoint(0, 0))
            drawer_rect = QRect(drawer_topleft, self.size())
            if not drawer_rect.contains(click_pos):
                # 点击在 drawer 外 → 异步关闭（避免在 eventFilter 中直接销毁自己）
                QTimer.singleShot(0, self.hide_drawer)
                # 不消费，让事件继续传给原本的目标
        return super().eventFilter(obj, event)

    # ---------- UI 构建 ----------
    def _build_ui(self):
        self.setFixedWidth(420)
        # 主布局
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        # v3.02.01: 抽样式到 _build_styles，主题切换可复用
        self._build_styles()
        # ── 标题栏（用 qfluentwidgets 主题感知控件）──
        header = QWidget()
        header.setFixedHeight(44)  # v3.02.01: 从 50 → 44，更紧凑，与按钮基线对齐
        hlay = QHBoxLayout(header)
        hlay.setContentsMargins(16, 6, 12, 6)
        hlay.setSpacing(0)
        # v3.02.01 fix: 改用 StrongBodyLabel（主题感知，之前 QLabel 黑色不跟随主题）
        title = StrongBodyLabel("通知", header)
        title.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        hlay.addWidget(title)
        hlay.addStretch(1)
        # v3.02.01 fix: 改用 FluentPushButton（主题感知，之前 QPushButton 白底黑字）
        # 不固定最小宽度，按文字内容自适应，避免大按钮显得空旷
        self._btn_read = FluentPushButton("全部已读", header)
        self._btn_read.setCursor(Qt.PointingHandCursor)
        self._btn_clear = FluentPushButton("清空", header)
        self._btn_clear.setCursor(Qt.PointingHandCursor)
        self._btn_read.clicked.connect(self._on_mark_all_read)
        self._btn_clear.clicked.connect(self._on_clear_all)
        hlay.addWidget(self._btn_read)
        hlay.addSpacing(6)
        hlay.addWidget(self._btn_clear)
        outer.addWidget(header)
        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        if isDarkTheme():
            _border = "#3a3d42"
        else:
            _border = "#e0e0e0"
        line.setStyleSheet(f"color: {_border};")
        outer.addWidget(line)
        # ── 过滤行 ──
        # v3.02.01 fix: 8 个 chip 撑不下，用 FlowLayout 自动换行（之前 QHBoxLayout 会溢出隐藏）
        from qfluentwidgets import FlowLayout
        self._filter_scroll = QScrollArea()
        self._filter_scroll.setWidgetResizable(True)
        self._filter_scroll.setFixedHeight(80)  # 加高以容纳两行 chip
        self._filter_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._filter_inner = QWidget()
        # FlowLayout 签名 (parent=None, needAni=False, isTight=False)
        self._filter_layout = FlowLayout(self._filter_inner, needAni=False, isTight=True)
        self._filter_layout.setContentsMargins(12, 8, 12, 8)
        self._filter_layout.setSpacing(6)
        self._chip_buttons: dict[str, QPushButton] = {}
        for key, (label, _) in self.FILTER_MAP.items():
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedHeight(28)
            # v3.02.01 fix: 按 label 长度动态计算最小宽度（避免 "Webhook" 截断）
            # 经验值：每字符 ~9px（中英文混排）+ padding 16px + buffer 8px
            min_w = max(56, len(label) * 10 + 24)
            btn.setMinimumWidth(min_w)
            btn.setCursor(Qt.PointingHandCursor)
            f = QFont("Microsoft YaHei", 9)
            btn.setFont(f)
            btn.clicked.connect(lambda _checked=False, k=key: self._set_filter(k))
            self._chip_buttons[key] = btn
            self._filter_layout.addWidget(btn)
        self._filter_scroll.setWidget(self._filter_inner)
        outer.addWidget(self._filter_scroll)
        # 滚动区（通知列表）
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
        # v3.02.01 fix: 主题感知（之前 chip 在浅色主题下背景太深看不清楚）
        if isDarkTheme():
            unselected_bg, unselected_hover, unselected_fg = "#2a2a2a", "#353535", "#aabbcc"
        else:
            unselected_bg, unselected_hover, unselected_fg = "#e8e8e8", "#d8d8d8", "#444"
        for k, btn in self._chip_buttons.items():
            if btn.isChecked():
                btn.setStyleSheet("""
                    QPushButton {
                        background: #0DC5D4; color: #ffffff;
                        border: none; border-radius: 13px;
                        padding: 2px 10px;
                    }
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {unselected_bg}; color: {unselected_fg};
                        border: none; border-radius: 13px;
                        padding: 2px 10px;
                    }}
                    QPushButton:hover {{ background: {unselected_hover}; }}
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
            # v3.02.01 fix: 改用 CaptionLabel（主题感知，之前 QLabel 黑色）
            empty = CaptionLabel("暂无通知", self._list_container)
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet(f"color: {'#666' if isDarkTheme() else '#999'}; padding: 40px; font-size: 12px;")
            self._list_layout.insertWidget(0, empty)
            return
        # 渲染（最多 200 条，避免卡顿）
        for n in items[:200]:
            row = NotificationItemWidget(n, self._list_container)
            # 单击展开（不再触发跳转，跳转由双击/箭头按钮触发）
            row.clicked.connect(lambda _n: self._on_item_expanded(_n))
            # 双击跳转
            row.navigate_requested.connect(self._on_item_navigate)
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

    def _on_item_expanded(self, n: Notification):
        """单击通知：标记已读 + 关闭抽屉（如果有跳转意图）。"""
        # 标记单条已读（如果未读）
        if not n.read:
            try:
                import json
                import os
                from backend.notifications import NOTIFY_FILE
                with open(NOTIFY_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for item in data:
                    if item.get("id") == n.id:
                        item["read"] = True
                        break
                with open(NOTIFY_FILE + ".tmp", "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(NOTIFY_FILE + ".tmp", NOTIFY_FILE)
            except Exception:
                pass
            n.read = True
        # v3.02.01: 单击不关闭抽屉，只展开详情；用户继续浏览其他通知
        # 双击或点箭头才跳转 + 关闭

    def _on_item_navigate(self, n: Notification):
        """双击通知 / 点箭头：跳转到目标页 + 关闭抽屉。"""
        page, params = parse_action_target(n.action_target)
        if page:
            self.navigate_requested.emit(page, params)
        # 标记已读
        if not n.read:
            try:
                import json
                import os
                from backend.notifications import NOTIFY_FILE
                with open(NOTIFY_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for item in data:
                    if item.get("id") == n.id:
                        item["read"] = True
                        break
                with open(NOTIFY_FILE + ".tmp", "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(NOTIFY_FILE + ".tmp", NOTIFY_FILE)
                n.read = True
            except Exception:
                pass
        # 关闭抽屉
        self.hide_drawer()

    def _resolve_top_offset(self) -> int:
        """抽屉顶部 y 起点：必须在 titleBar 下方，避开最小化/最大化/关闭按钮。

        之前固定从 0 开始，会把抽屉 header（50px 高的"全部已读/清空"按钮）压在系统按钮上方。
        """
        parent = self.parent()
        if parent is None:
            return 0
        # 优先用 FluentWindow 的 titleBar 高度
        tb = getattr(parent, "titleBar", None)
        if tb is not None:
            return tb.height()
        # 兜底：从窗口标志判断标题栏高度（frameless 窗口 titleBar 通常 48px）
        return 48

    # ---------- 显隐控制 ----------
    def refresh_theme(self):
        """主题切换后调用：重建背景色 + chip 样式 + 重渲染列表。"""
        self._build_styles()  # 重设 stylesheet
        self._update_chip_style()
        self.refresh()

    def _build_styles(self):
        # v3.02.01: 现代化主题（VSCode 风格深灰，而非纯黑）
        if isDarkTheme():
            bg, border = "#202225", "#3a3d42"   # 柔和深灰
        else:
            bg, border = "#fafafa", "#e0e0e0"   # 干净浅色
        # v3.02.01 fix: 用 QWidget#objectName 明确指向自己，避免样式被覆盖或失效
        self.setObjectName("notificationDrawer")
        self.setStyleSheet(f"""
            QWidget#notificationDrawer {{ background: {bg}; border-left: 1px solid {border}; }}
            QWidget#notificationDrawer QWidget {{ background: transparent; }}
        """)
    def show_drawer(self):
        """在主窗口右侧显示。

        v3.02.01 fix: 用 eventFilter 替代 mask widget，监听主窗口鼠标事件，
        按点击位置精确判断是否需要关闭。
        """
        if self.parent() is None:
            return
        parent = self.parent()
        pw = parent.width()
        ph = parent.height()
        top_offset = self._resolve_top_offset()
        self.setGeometry(pw, top_offset, self.width(), ph - top_offset)
        self.show()
        self.raise_()
        self.refresh()
        # 注册 eventFilter（确保只在可见时拦截）
        if not self._is_installed:
            parent.installEventFilter(self)
            self._is_installed = True
        # 滑入动画（保持引用避免 GC）
        self._show_anim = QPropertyAnimation(self, b"geometry")
        self._show_anim.setDuration(280)
        self._show_anim.setStartValue(self.geometry())
        self._show_anim.setEndValue(
            self.geometry().adjusted(-self.width(), 0, -self.width(), 0)
        )
        self._show_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._show_anim.start()

    def hide_drawer(self):
        """立即关闭。"""
        # 注销 eventFilter
        if getattr(self, "_is_installed", False) and self.parent() is not None:
            self.parent().removeEventFilter(self)
            self._is_installed = False
        if not self.isVisible():
            self.closed.emit()
            return
        self.hide()
        self.closed.emit()

    def _on_hide_finished(self):
        self.hide()
        self.closed.emit()