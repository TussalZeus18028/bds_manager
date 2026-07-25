# -*- coding: utf-8 -*-
"""
启动闪屏组件 —— 圆角 · 半透明 · 动画进度条 · 深浅色适配。

v3.03.01 从 main.py 拆分，保持完全独立。
"""

import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QColor, QBitmap, QPainter, QFont, QPen
from PySide6.QtWidgets import QApplication, QSplashScreen


class AnimatedSplashScreen(QSplashScreen):
    """v3.03.00 重设计：圆角窗口 + 半透明背景 + 动画进度条 + 深浅色适配。

    QSplashScreen 基于 QPixmap 渲染，不支持 QSS。圆角通过 QBitmap setMask 实现，
    半透明通过 setWindowOpacity，绘制内容在 drawContents 手动处理。
    """

    W, H = 480, 300

    def __init__(self, version: str, is_dark: bool = False):
        self._is_dark = is_dark

        pix = QPixmap(self.W, self.H)
        bg = "#1a1c20" if is_dark else "#f5f5f5"
        pix.fill(QColor(bg))
        super().__init__(pix, Qt.WindowStaysOnTopHint)
        self.setWindowFlag(Qt.FramelessWindowHint, True)

        bitmap = QBitmap(self.W, self.H)
        bitmap.fill(Qt.color0)
        mp = QPainter(bitmap)
        mp.setBrush(Qt.color1)
        mp.setPen(Qt.NoPen)
        mp.setRenderHint(QPainter.Antialiasing)
        mp.drawRoundedRect(0, 0, self.W, self.H, 14, 14)
        mp.end()
        self.setMask(bitmap)

        self.setWindowOpacity(0.94)
        self._progress = 0
        self._status = "正在启动..."
        self._version = version

    def set_progress(self, percent: int, status: str = ""):
        self._progress = max(0, min(100, percent))
        if status:
            self._status = status
        self.repaint()

    def set_status(self, status: str):
        self._status = status
        self.repaint()

    def drawContents(self, painter):
        rect = self.rect()
        is_dark = self._is_dark

        accent = QColor("#0DC5D4")
        title_color = QColor("#0DC5D4") if is_dark else QColor("#0078D4")
        sub_color = QColor("#78909c") if is_dark else QColor("#6b7b8d")
        line_color = QColor("#2a2e33") if is_dark else QColor("#d0d4d8")
        track_color = QColor("#252830") if is_dark else QColor("#e0e3e6")
        status_color = QColor("#b0b8c0") if is_dark else QColor("#5a6268")
        pct_color = QColor("#5a6268") if is_dark else QColor("#8a9098")
        hint_color = QColor("#3a4048") if is_dark else QColor("#a0a4a8")

        painter.setPen(title_color)
        title_font = QFont("Microsoft YaHei", 20)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.drawText(rect.adjusted(0, 54, 0, 0), Qt.AlignHCenter, "BDS Manager")

        painter.setPen(sub_color)
        sub_font = QFont("Microsoft YaHei", 10)
        painter.setFont(sub_font)
        painter.drawText(rect.adjusted(0, 94, 0, 0), Qt.AlignHCenter,
                         f"v{self._version}  —  服务器管理工具")

        line_y = 140
        painter.setPen(QPen(line_color, 1))
        painter.drawLine(60, line_y, self.W - 60, line_y)

        bar_x, bar_y, bar_w, bar_h = 60, 175, self.W - 120, 5
        painter.setPen(Qt.NoPen)
        painter.setBrush(track_color)
        painter.drawRoundedRect(bar_x, bar_y, bar_w, bar_h, 3, 3)
        if self._progress > 0:
            fg_w = int(bar_w * self._progress / 100)
            painter.setBrush(accent)
            painter.drawRoundedRect(bar_x, bar_y, fg_w, bar_h, 3, 3)

        painter.setPen(status_color)
        status_font = QFont("Microsoft YaHei", 10)
        painter.setFont(status_font)
        painter.drawText(rect.adjusted(0, 200, 0, 0), Qt.AlignHCenter, self._status)

        painter.setPen(pct_color)
        pct_font = QFont("Microsoft YaHei", 9)
        painter.setFont(pct_font)
        painter.drawText(rect.adjusted(0, 232, 0, 0), Qt.AlignHCenter,
                         f"加载 {self._progress}%")

        painter.setPen(hint_color)
        hint_font = QFont("Microsoft YaHei", 8)
        painter.setFont(hint_font)
        painter.drawText(rect.adjusted(0, 272, 0, 0), Qt.AlignHCenter,
                         "Bedrock Dedicated Server 管理工具")


def animate_progress(splash: AnimatedSplashScreen, app: QApplication,
                     target: int, duration_ms: int = 250):
    """从当前进度平滑过渡到 target（ease-out cubic，~60fps）。"""
    start = splash._progress
    steps = max(1, duration_ms // 16)
    for i in range(1, steps + 1):
        ratio = i / steps
        eased = 1 - (1 - ratio) ** 3
        pct = int(start + (target - start) * eased)
        splash.set_progress(pct)
        app.processEvents()
        time.sleep(0.008)
