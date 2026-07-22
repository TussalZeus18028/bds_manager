# -*- coding: utf-8 -*-
"""
关于页面 —— 版本信息、相关链接。
"""
import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
)
from qfluentwidgets import (
    CardWidget, SubtitleLabel, BodyLabel, HyperlinkButton,
    FluentIcon, setTheme, setThemeColor, Theme,
)

from pages.dashboard import wrap_scrollable


class AboutPage(QWidget):
    """关于 BDS Manager"""

    def __init__(self, parent=None):
        super().__init__(parent)
        inner, layout = wrap_scrollable(self, spacing=16)

        # ── 标题 ──
        import main
        title_card = CardWidget(inner)
        tl = QVBoxLayout(title_card)
        tl.setContentsMargins(24, 20, 24, 24)
        tl.setSpacing(8)

        ver = SubtitleLabel(f"BDS Manager v{main.__version__}", title_card)
        ver.setStyleSheet("font-size: 24px; font-weight: bold; color: #4CAF50;")
        tl.addWidget(ver)

        desc = BodyLabel(
            "Minecraft Bedrock 版服务器全功能管理器。\n"
            "一键启停、实时监控、世界管理、版本升级、隧道穿透、资源包管理。\n"
            "基于 PySide6 + QFluentWidgets Fluent Design 构建。\n\n"
            "v3.1 更新：资源曲线、级别过滤、命令补全、备份预览、\n"
            "配置预设、原子写、命令面板（Ctrl+K）、系统主题跟随。",
            title_card,
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #aaa; font-size: 13px; line-height: 1.6;")
        tl.addWidget(desc)
        layout.addWidget(title_card)

        # ── 链接 ──
        links_card = CardWidget(inner)
        ll = QVBoxLayout(links_card)
        ll.setContentsMargins(16, 12, 16, 16)
        ll.setSpacing(4)
        ll.addWidget(SubtitleLabel("相关链接", links_card))

        links = [
            ("GitHub 仓库", "https://github.com/TussalZeus18028/bds_manager", FluentIcon.GITHUB),
            ("BDS 官网下载", "https://www.minecraft.net/zh-hans/download/server/bedrock", FluentIcon.DOWNLOAD),
            ("ChmlFrp 隧道", "https://www.chmlfrp.net/", FluentIcon.LINK),
            ("版本数据库", "https://github.com/TussalZeus18028/bds_version_list", FluentIcon.LIBRARY),
        ]
        for text, url, icon in links:
            link = HyperlinkButton(url, text, links_card, icon)
            link.setStyleSheet("text-align: left;")
            ll.addWidget(link)

        layout.addWidget(links_card)
        layout.addStretch()
