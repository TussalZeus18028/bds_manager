# -*- coding: utf-8 -*-
"""
自更新 UI 辅助函数（v3.04.01 从 main.py 提取）。

处理跨版本升级引导弹窗和下载确认对话框，减少 main.py BDSFluentWindow 的 UI 逻辑。
"""

from __future__ import annotations

import os
import webbrowser
import logging
from typing import Protocol

from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QWidget
from PySide6.QtCore import Qt
from qfluentwidgets import PushButton, PrimaryPushButton, isDarkTheme, MessageBox

from shared.config import config_mgr
from shared.toast import toast_info, toast_success, toast_error, toast_warning
from shared.version import VERSION as __version__
from backend.self_update import GITHUB_REPO_OWNER, GITHUB_REPO_NAME
from backend.notifications import notify

logger = logging.getLogger("bds_manager")


# ── 协议：自更新 UI 需要的最小窗口接口 ──
class UpdateUIHost(Protocol):
    """主窗口必须提供的自更新回调。"""

    def _start_self_update_download(self, dl_url: str, remote_ver: str, sha256: str = "") -> None: ...
    def apply_theme(self, theme: str, accent_color: str) -> None: ...


def show_cross_version_dialog(
    parent: QWidget,
    remote_ver: str,
    dl_url: str,
    sha256: str,
    msg: str,
    on_auto_upgrade: object,  # callable(dl_url, remote_ver, sha256)
) -> None:
    """跨主版本升级引导弹窗：引导用户选择「打开下载页」或「继续自动升级」。

    从 main.py: BDSFluentWindow._prompt_cross_version_upgrade() 提取。
    """
    bg = "#1e1e1e" if isDarkTheme() else "#fafafa"
    fg = "#ccc" if isDarkTheme() else "#1a1a1a"

    dlg = QDialog(parent)
    dlg.setWindowTitle("发现新版本（建议手动下载）")
    dlg.resize(520, 380)
    dlg.setStyleSheet(f"QDialog {{ background: {bg}; }} QLabel {{ color: {fg}; }}")
    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(20, 16, 20, 16)
    layout.setSpacing(12)

    title = QLabel("发现新版本（建议手动下载）")
    title.setStyleSheet(f"font-size: 15px; font-weight: bold; color: {fg};")
    layout.addWidget(title)

    body_text = (
        f"检测到新版本 v{remote_ver}（当前 v{__version__}）。\n\n"
        f"您的版本与新版差异较大，{msg or '自动升级可能需要手动调整'}。\n\n"
        f"建议手动下载完整包升级（更稳妥）：\n"
        f"1. 点击「打开下载页」前往 GitHub Releases\n"
        f"2. 下载 bds_manager_v{remote_ver}.zip\n"
        f"3. 解压覆盖到当前目录（自动迁移旧版特征文件）\n"
        f"4. 重启程序\n\n"
        f"如果您想继续体验一键自动升级，也可选择「继续自动升级」。"
    )
    body_label = QLabel(body_text)
    body_label.setWordWrap(True)
    layout.addWidget(body_label)

    btn_row = QHBoxLayout()
    btn_manual = PrimaryPushButton("打开下载页（推荐）", dlg)
    btn_auto = PushButton("继续自动升级", dlg)
    btn_cancel = PushButton("取消", dlg)

    def _on_manual():
        webbrowser.open(
            f"https://github.com/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/releases/tag/v{remote_ver}"
        )
        dlg.accept()

    def _on_auto():
        if callable(on_auto_upgrade):
            on_auto_upgrade(dl_url, remote_ver, sha256)
        dlg.accept()

    btn_manual.clicked.connect(_on_manual)
    btn_auto.clicked.connect(_on_auto)
    btn_cancel.clicked.connect(dlg.reject)
    btn_row.addStretch()
    btn_row.addWidget(btn_cancel)
    btn_row.addWidget(btn_auto)
    btn_row.addWidget(btn_manual)
    layout.addLayout(btn_row)
    dlg.exec()


def show_update_prompt(
    parent: QWidget,
    remote_ver: str,
    dl_url: str,
    sha256: str,
    on_download: object,  # callable(dl_url, remote_ver, sha256)
) -> MessageBox:
    """确认更新弹窗：询问用户是否下载新版本。

    从 main.py: BDSFluentWindow._on_self_update_found() 提取。

    Returns:
        MessageBox 实例。调用方必须将其存储为实例属性，
        避免 Python 端引用被 GC 导致 PySide6 报
        "Skipping callback call because the callback object is being destructed"。
    """
    mb = MessageBox(
        "发现新版本",
        f"当前: v{__version__}\n最新: v{remote_ver}\n\n是否立即下载更新？",
        parent,
    )
    mb.yesButton.setText("立即更新")
    mb.cancelButton.setText("稍后")
    # v3.04.01 fix: 使用嵌套函数代替 lambda，避免 MessageBox 关闭时
    # lambda 回调对象被析构导致的 RuntimeWarning。
    def _on_yes():
        if callable(on_download):
            on_download(dl_url, remote_ver, sha256)
    mb.yesSignal.connect(_on_yes)
    mb.show()
    return mb
