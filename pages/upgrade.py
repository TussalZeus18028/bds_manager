# -*- coding: utf-8 -*-
"""
升级 / 安装页面 —— BDS 版本管理（对齐旧 PyQt5 版完整逻辑）。

v3.1 改进：
- 升级历史（.upgrade_history.json）
- "回滚到上一版本"按钮（用 pre_upgrade_ 备份）
- 选中两行对比 Changelog
- metadata 显示在表格（bds_version + 文件大小）
- HEAD 扫描 memoize（已存在）
"""

import os, re, time, json, shutil, logging
import html as _html_lip

logger = logging.getLogger("bds_manager")

import requests

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QPlainTextEdit,
)
from PySide6.QtGui import QTextCursor, QColor, QFont
from qfluentwidgets import (
    CardWidget, SubtitleLabel, BodyLabel, CaptionLabel,
    PrimaryPushButton, PushButton, LineEdit, FluentIcon,
    ProgressBar, MessageBox, isDarkTheme,
)

from shared.config import config_mgr, get_context, SCRIPT_DIR
from shared.utils import is_linux, bds_exe, ll_exe
from shared.toast import toast_success, toast_error, toast_info
from pages.dashboard import wrap_scrollable
from components.widgets import NoScrollSpinBox

# v3.05.00: Worker 线程抽离到 backend/upgrade_workers.py
from backend.upgrade_workers import (
    scrape_github_versions, ansi_to_html,
    GithubFetcher, HeadScanWorker, DownloadWorker, InstallWorker, HeadSizeWorker,
)


def _table_style() -> str:
    """v3.03.04: 从 shared/theme.py 统一主题样式。"""
    from shared.theme import table_style
    return table_style()


def _plaintext_style() -> str:
    """v3.03.04: 从 shared/theme.py 统一主题样式。"""
    from shared.theme import plaintext_style
    return plaintext_style()

# ── 升级历史 ──
UPGRADE_HISTORY_FILE = os.path.join(SCRIPT_DIR, ".upgrade_history.json")


def _load_upgrade_history() -> list[dict]:
    if not os.path.exists(UPGRADE_HISTORY_FILE):
        return []
    try:
        with open(UPGRADE_HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError, OSError):
        return []


def _save_upgrade_history(history: list[dict]):
    try:
        with open(UPGRADE_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history[-50:], f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def _record_upgrade(version: str, from_ver: str, backup_dir: str | None):
    history = _load_upgrade_history()
    history.append({
        "version": version,
        "from_version": from_ver,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "backup_dir": backup_dir,
    })
    _save_upgrade_history(history)


class UpgradePage(QWidget):
    # GitHub 重试配置：失败时先重试 N 次，最后才提示用户启用 HEAD 嗅探（最后手段）
    GITHUB_MAX_RETRIES = 3
    GITHUB_BACKOFF_BASE = 2  # 秒（指数退避：1s, 2s, 4s）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._results: list[tuple] = []
        self._size_worker: HeadSizeWorker | None = None
        self._head_worker: HeadScanWorker | None = None
        self._github_worker: GithubFetcher | None = None
        # 重试 & 嗅探 fallback 状态
        self._github_attempt = 0          # 当前是第几次尝试
        self._github_silent = False       # True = 后台静默（不弹窗）
        self._pending_head_scan = False   # GitHub 全部失败后，等待用户点「启用 HEAD 嗅探」
        inner, layout, self._scroll = wrap_scrollable(self, spacing=12)

        cached = config_mgr.get("version_list", {})
        if isinstance(cached, dict) and cached.get("data"):
            self._results = cached["data"]

        # 当前信息
        info_card = CardWidget(inner)
        il = QVBoxLayout(info_card)
        il.setContentsMargins(16, 12, 16, 16); il.setSpacing(6)
        il.addWidget(SubtitleLabel("当前状态", info_card))
        ctx = get_context()
        stype = config_mgr.get("server_type", "bds")

        # 检测纯 BDS（始终检查 BDS 目录）
        bds_dir = ctx.bds_dir if hasattr(ctx, "bds_dir") else ctx.server_dir
        bds_exe = os.path.join(bds_dir, config_mgr.get("server_exe", "bedrock_server.exe"))
        bds_ok = os.path.exists(bds_exe)

        # 检测 LL 服务器
        ll_dir = config_mgr.get("ll_server_dir", "")
        if ll_dir:
            ll_abs = os.path.join(SCRIPT_DIR, ll_dir) if not os.path.isabs(ll_dir) else ll_dir
        else:
            ll_abs = ctx.bds_dir if hasattr(ctx, "bds_dir") else ctx.server_dir
        ll_exe = os.path.join(ll_abs, "bedrock_server_mod.exe")
        ll_ok = os.path.exists(ll_exe)

        if bds_ok:
            il.addWidget(BodyLabel(f"已安装 BDS — {bds_dir}", info_card))
            if ll_ok:
                il.addWidget(CaptionLabel(f"已安装 LL — {ll_abs}", info_card))
            else:
                il.addWidget(CaptionLabel("LL 未安装 — 点击上方 lip 卡片部署", info_card))
        elif ll_ok:
            il.addWidget(BodyLabel(f"已安装 LeviLamina — {ll_abs}", info_card))
            il.addWidget(CaptionLabel(f"纯 BDS 未安装（仅 LL 模式）", info_card))
        else:
            self._info = BodyLabel("未安装任何服务器", info_card)
            self._info.setStyleSheet("color: #E65100;")
            il.addWidget(self._info)
            il.addWidget(CaptionLabel(f"BDS 路径: {bds_exe}", info_card))
            il.addWidget(CaptionLabel(f"LL 路径: {ll_exe}", info_card))

        layout.addWidget(info_card)

        # ═══ lip 一键部署 (BDS + LeviLamina) ═══
        self._setup_lip_section(inner, layout)

        if is_linux():
            linux_card = CardWidget(inner)
            lcl = QVBoxLayout(linux_card)
            lcl.setContentsMargins(16, 12, 16, 16); lcl.setSpacing(8)
            lcl.addWidget(SubtitleLabel("Linux 用户", linux_card))
            from qfluentwidgets import HyperlinkButton
            link = HyperlinkButton(
                "https://www.minecraft.net/en-us/download/server/bedrock",
                "打开 Minecraft 官网下载 Ubuntu 版 BDS",
                linux_card, FluentIcon.LINK,
            )
            lcl.addWidget(link)
            lcl.addWidget(BodyLabel(
                "当前运行在 Linux 系统上。BDS Manager 的版本下载功能仅供 Windows 使用。\n"
                "下载 Linux 版 BDS zip，解压后将文件夹路径配置到「设置」页即可开服。\n"
                "启动命令: LD_LIBRARY_PATH=. ./bedrock_server",
                linux_card))
            layout.addWidget(linux_card)
            # Linux 下跳过版本表格，继续渲染后续卡片（历史、日志、工具更新）
        else:
                # 版本列表
            ver_card = CardWidget(inner)
            vl = QVBoxLayout(ver_card)
            vl.setContentsMargins(16, 12, 16, 16); vl.setSpacing(8)

            hdr = QHBoxLayout()
            hdr.addWidget(SubtitleLabel("可用版本", ver_card))
            hdr.addStretch()
            self._fetch_btn = PrimaryPushButton("浏览可用版本", ver_card, FluentIcon.SYNC)
            self._stop_btn = PushButton("停止", ver_card, FluentIcon.CANCEL)
            self._stop_btn.setEnabled(False)
            self._patch_spin = NoScrollSpinBox(ver_card)
            self._patch_spin.setRange(10, 200); self._patch_spin.setValue(40)
            self._build_spin = NoScrollSpinBox(ver_card)
            self._build_spin.setRange(5, 60); self._build_spin.setValue(30)
            hdr.addWidget(self._fetch_btn)
            hdr.addWidget(self._stop_btn)
            hdr.addWidget(CaptionLabel("Patch:", ver_card))
            hdr.addWidget(self._patch_spin)
            hdr.addWidget(CaptionLabel("Build:", ver_card))
            hdr.addWidget(self._build_spin)
            vl.addLayout(hdr)

            self._ver_table = QTableWidget(0, 4, ver_card)
            self._ver_table.setHorizontalHeaderLabels(["版本", "分支", "大小", "操作"])
            self._ver_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            for col, w in [(1, 80), (2, 90), (3, 120)]:
                self._ver_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.Fixed)
                self._ver_table.setColumnWidth(col, w)
            self._ver_table.verticalHeader().setVisible(False)
            self._ver_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self._ver_table.setSelectionBehavior(QAbstractItemView.SelectRows)
            self._ver_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
            self._ver_table.setMinimumHeight(320)
            self._ver_table.verticalHeader().setDefaultSectionSize(40)  # 行高：容纳 PushButton
            self._ver_table.setStyleSheet(_table_style())
            vl.addWidget(self._ver_table)

            # 工具行
            tools_row = QHBoxLayout()
            self._size_btn = PushButton("获取文件大小", ver_card, FluentIcon.SEND)
            self._size_btn.clicked.connect(self._fetch_sizes)
            self._compare_btn = PushButton("对比选中", ver_card, FluentIcon.SEND)
            self._compare_btn.clicked.connect(self._on_compare_versions)
            self._rollback_btn = PushButton("回滚到上一版本", ver_card, FluentIcon.CANCEL)
            self._rollback_btn.clicked.connect(self._on_rollback)
            tools_row.addWidget(self._size_btn)
            tools_row.addWidget(self._compare_btn)
            tools_row.addWidget(self._rollback_btn)
            tools_row.addStretch()
            vl.addLayout(tools_row)

            self._scan_status = CaptionLabel("", ver_card)
            self._scan_status.setStyleSheet(f"color: {'#888' if isDarkTheme() else '#666'};")
            vl.addWidget(self._scan_status)

            # 手动输入
            man_row = QHBoxLayout()
            man_row.addWidget(CaptionLabel("手动版本:", ver_card))
            self._manual_input = LineEdit(ver_card)
            self._manual_input.setPlaceholderText("1.21.0.2")
            self._manual_input.setMaximumWidth(110)
            self._manual_dl = PushButton("下载", ver_card, FluentIcon.DOWNLOAD)
            self._manual_dl.clicked.connect(self._download_manual)
            man_row.addWidget(self._manual_input)
            man_row.addWidget(self._manual_dl)
            man_row.addStretch()
            vl.addLayout(man_row)

            layout.addWidget(ver_card)

        # 升级历史
        history_card = CardWidget(inner)
        hl = QVBoxLayout(history_card)
        hl.setContentsMargins(16, 12, 16, 16); hl.setSpacing(6)
        hl.addWidget(SubtitleLabel("升级历史", history_card))
        self._history_table = QTableWidget(0, 3, history_card)
        self._history_table.setHorizontalHeaderLabels(["时间", "版本", "回滚"])
        self._history_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._history_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self._history_table.setColumnWidth(2, 80)
        self._history_table.verticalHeader().setVisible(False)
        self._history_table.verticalHeader().setDefaultSectionSize(36)
        self._history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._history_table.setMinimumHeight(250)  # v3.04.03: 够显示6-7行
        self._history_table.setStyleSheet(_table_style())
        hl.addWidget(self._history_table)
        layout.addWidget(history_card)

        # ── 安装区 (下载完成后出现) ──
        self._install_card = CardWidget(inner)
        il2 = QVBoxLayout(self._install_card)
        il2.setContentsMargins(16, 12, 16, 16); il2.setSpacing(8)
        il2.addWidget(SubtitleLabel("安装", self._install_card))
        self._install_info = BodyLabel("请先下载一个版本", self._install_card)
        self._install_info.setWordWrap(True)
        il2.addWidget(self._install_info)
        path_row = QHBoxLayout(); path_row.setSpacing(6)
        path_row.addWidget(CaptionLabel("安装到:", self._install_card))
        self._install_dir = LineEdit(self._install_card)
        self._install_dir.setPlaceholderText("选择服务器安装目录...")
        path_row.addWidget(self._install_dir, 1)
        browse2 = PushButton("浏览", self._install_card, FluentIcon.FOLDER)
        browse2.clicked.connect(self._browse_install_dir)
        path_row.addWidget(browse2)
        il2.addLayout(path_row)
        self._install_status = CaptionLabel("", self._install_card)
        il2.addWidget(self._install_status)
        self._install_progress = ProgressBar(self._install_card)
        self._install_progress.setVisible(False)
        il2.addWidget(self._install_progress)
        self._install_btn = PushButton("开始安装", self._install_card, FluentIcon.SAVE)
        self._install_btn.clicked.connect(self._do_install)
        self._install_btn.setEnabled(False)
        il2.addWidget(self._install_btn)
        self._install_card.setVisible(False)
        layout.addWidget(self._install_card)

        # 进度（下载用）
        prog_card = CardWidget(inner)
        pl = QVBoxLayout(prog_card)
        pl.setContentsMargins(16, 12, 16, 16); pl.setSpacing(6)
        self._dl_bar = ProgressBar(prog_card); self._dl_bar.setVisible(False)
        pl.addWidget(self._dl_bar)
        self._dl_status = CaptionLabel("", prog_card)
        pl.addWidget(self._dl_status)
        layout.addWidget(prog_card)

        # 日志
        log_card = CardWidget(inner)
        ll = QVBoxLayout(log_card)
        ll.setContentsMargins(12, 10, 12, 12)
        ll.addWidget(CaptionLabel("操作日志", log_card))
        self._log = QPlainTextEdit(log_card)
        self._log.setReadOnly(True); self._log.setMaximumBlockCount(2000)
        self._log.setMinimumHeight(100)
        self._log.setStyleSheet(_plaintext_style())
        ll.addWidget(self._log)
        layout.addWidget(log_card)

        # 工具自更新
        tool_card = CardWidget(inner)
        tl = QVBoxLayout(tool_card)
        tl.setContentsMargins(16, 12, 16, 16); tl.setSpacing(8)
        hdr = QHBoxLayout()
        hdr.addWidget(SubtitleLabel("BDS Manager 自身更新", tool_card))
        hdr.addStretch()
        import main
        self._tool_ver_label = CaptionLabel(f"当前 v{main.__version__}", tool_card)
        hdr.addWidget(self._tool_ver_label)
        tl.addLayout(hdr)

        btn_row = QHBoxLayout()
        self._tool_check_btn = PushButton("检查工具更新", tool_card, FluentIcon.SYNC)
        self._tool_check_btn.clicked.connect(self._check_tool_update)
        self._tool_install_btn = PushButton("安装更新并重启", tool_card, FluentIcon.UPDATE)
        self._tool_install_btn.setEnabled(False)
        self._tool_install_btn.clicked.connect(self._install_tool_update)
        btn_row.addWidget(self._tool_check_btn)
        btn_row.addWidget(self._tool_install_btn)
        btn_row.addStretch()
        tl.addLayout(btn_row)

        self._tool_bar = ProgressBar(tool_card)
        self._tool_bar.setVisible(False)
        tl.addWidget(self._tool_bar)
        self._tool_status = CaptionLabel("", tool_card)
        tl.addWidget(self._tool_status)

        layout.addWidget(tool_card)
        layout.addStretch()

        self._fetch_btn.clicked.connect(self._fetch)
        self._stop_btn.clicked.connect(self._stop_scan)

        if self._results:
            self._populate_table()
            cached_ts = cached.get("timestamp", 0) if isinstance(cached, dict) else 0
            age = int(time.time() - cached_ts) if cached_ts else 0
            if age < 60:
                age_text = f"{age} 秒前"
            elif age < 3600:
                age_text = f"{age // 60} 分钟前"
            elif age < 86400:
                age_text = f"{age // 3600} 小时前"
            else:
                age_text = f"{age // 86400} 天前"
            self._scan_status.setText(f"📦 缓存 {len(self._results)} 个版本（{age_text}），后台静默检查中...")

        self._refresh_history()
        self._auto_refreshed = False  # 首次 showEvent 触发后台刷新

    # ── lip 一键部署 ──
    def _setup_lip_section(self, inner, layout):
        from backend.lip_utils import lip_installed, find_lip_exe, InstallLipWorker, LipCmdWorker

        # ═══ 部署控制卡 ═══
        ctrl_card = CardWidget(inner)
        cc = QVBoxLayout(ctrl_card)
        cc.setContentsMargins(16, 12, 16, 12)
        cc.setSpacing(6)

        hdr = QHBoxLayout()
        hdr.addWidget(SubtitleLabel("lip  快速部署 (BDS + LeviLamina)", ctrl_card))
        self._lip_status = CaptionLabel("", ctrl_card)
        self._lip_status.setStyleSheet("color: #888;")
        hdr.addWidget(self._lip_status)
        hdr.addStretch()

        self._lip_install_btn = PushButton("安装 lip", ctrl_card, FluentIcon.DOWNLOAD)
        self._lip_install_btn.clicked.connect(self._on_install_lip)
        self._lip_install_btn.setMinimumWidth(88)
        hdr.addWidget(self._lip_install_btn)

        self._mirror_btn = PushButton("加速源", ctrl_card, FluentIcon.SYNC)
        self._mirror_btn.clicked.connect(self._on_lip_mirrors)
        self._mirror_btn.setMinimumWidth(72)
        hdr.addWidget(self._mirror_btn)
        cc.addLayout(hdr)

        deploy_row = QHBoxLayout()
        deploy_row.setSpacing(6)
        self._deploy_dir = LineEdit(ctrl_card)
        deploy_root = config_mgr.get("server_root_dir") or get_context().server_dir
        self._deploy_dir.setText(deploy_root)
        self._deploy_dir.setPlaceholderText("部署目录")
        deploy_row.addWidget(self._deploy_dir, 1)
        btn_browse = PushButton("浏览", ctrl_card, FluentIcon.FOLDER)
        btn_browse.clicked.connect(self._on_lip_browse)
        btn_browse.setMinimumWidth(60)
        deploy_row.addWidget(btn_browse)
        self._ll_ver = LineEdit(ctrl_card)
        self._ll_ver.setPlaceholderText("LL 版本 (可选)")
        self._ll_ver.setFixedWidth(100)
        deploy_row.addWidget(self._ll_ver)
        self._deploy_btn = PrimaryPushButton("安装 BDS + LL", ctrl_card, FluentIcon.PLAY)
        self._deploy_btn.clicked.connect(self._on_lip_deploy)
        self._deploy_btn.setMinimumWidth(130)
        deploy_row.addWidget(self._deploy_btn)
        cc.addLayout(deploy_row)

        self._lip_progress = ProgressBar(ctrl_card)
        self._lip_progress.setVisible(False)
        self._lip_progress.setFixedHeight(4)
        cc.addWidget(self._lip_progress)

        layout.addWidget(ctrl_card)

        # ═══ 终端卡 ═══
        term_card = CardWidget(inner)
        tc = QVBoxLayout(term_card)
        tc.setContentsMargins(12, 8, 12, 8)
        tc.setSpacing(4)

        t_hdr = QHBoxLayout()
        t_hdr.addWidget(BodyLabel("lip 终端", term_card))
        t_hdr.addStretch()
        t_hdr.addWidget(CaptionLabel("输入命令后回车执行", term_card))
        tc.addLayout(t_hdr)

        self._lip_term = QPlainTextEdit(term_card)
        self._lip_term.setReadOnly(True)
        self._lip_term.setFont(QFont("Consolas", 11))
        self._lip_term.setMinimumHeight(200)

        self._lip_cmd = LineEdit(term_card)
        self._lip_cmd.setPlaceholderText("lip install github.com/LiteLDev/LeviLamina")
        self._lip_cmd.returnPressed.connect(self._on_lip_cmd)

        tc.addWidget(self._lip_term)
        tc.addWidget(self._lip_cmd)
        layout.addWidget(term_card)

        # 初始化
        self._lip_worker: LipCmdWorker | None = None
        self._lip_installer: InstallLipWorker | None = None
        self._apply_lip_term_theme()
        self._check_lip_status()

    def _check_lip_status(self):
        from backend.lip_utils import lip_installed
        if lip_installed():
            self._lip_status.setText("已安装")
            self._lip_install_btn.setVisible(False)
            self._deploy_btn.setEnabled(True)
        else:
            self._lip_status.setText("未安装")
            self._lip_install_btn.setVisible(True)
            self._deploy_btn.setEnabled(False)

    def _on_install_lip(self):
        from backend.lip_utils import InstallLipWorker
        self._lip_install_btn.setEnabled(False)
        self._lip_install_btn.setText("安装中...")
        self._lip_progress.setVisible(True)
        self._lip_progress.setRange(0, 0)
        self._lip_installer = InstallLipWorker()
        self._lip_installer.line.connect(lambda t: None)  # 输出重定向至下方日志
        self._lip_installer.done.connect(self._on_lip_installed)
        self._lip_installer.start()

    def _on_lip_installed(self, ok: bool):
        self._lip_install_btn.setEnabled(True)
        self._lip_install_btn.setText("安装 lip")
        self._lip_progress.setVisible(False)
        self._check_lip_status()
        if ok:
            toast_success("lip 就绪", "已安装 lip，可以部署 BDS + LeviLamina", self.window())

    def _on_lip_mirrors(self):
        from backend.lip_utils import lip_installed, find_lip_exe, LipCmdWorker
        try:
            if not lip_installed():
                toast_error("请先安装 lip", "未检测到 lip 命令行工具，请先安装 lip。", self.window())
                return
        except Exception as e:
            toast_error("检测失败", f"无法检测 lip 安装状态: {e}", self.window())
            return

        self._mirror_btn.setEnabled(False)
        self._mirror_btn.setText("配置中...")
        lip = find_lip_exe() or "lip"

        def _done(code):
            try:
                self._mirror_btn.setEnabled(True)
                self._mirror_worker = None
                if code == 0:
                    self._mirror_btn.setText("已加速")
                    toast_success("加速源就绪", "GitHub + Go 代理已配置", self.window())
                else:
                    self._mirror_btn.setText("加速源")
                    toast_error("配置失败", f"lip 退出码 {code}", self.window())
            except Exception as e:
                logger.error("_done 异常: %s", e)

        def _step2(code):
            _done(code)

        def _step1(code):
            try:
                if code == 0:
                    w2 = LipCmdWorker([lip, "config", "set", "go_module_proxy", "https://goproxy.cn"])
                    w2.finished.connect(_step2)
                    self._mirror_worker = w2
                    w2.start()
                else:
                    _done(code)
            except Exception as e:
                logger.error("_step1 异常: %s", e)
                _done(-1)

        try:
            w1 = LipCmdWorker([lip, "config", "set", "github_proxy", "https://github.bibk.top"])
            w1.finished.connect(_step1)
            self._mirror_worker = w1
            w1.start()
        except Exception as e:
            logger.error("启动 mirror worker 失败: %s", e)
            self._mirror_btn.setEnabled(True)
            self._mirror_btn.setText("加速源")

    def _on_lip_browse(self):
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, "选择部署目录")
        if d:
            # 防止选到子目录——向上查找含 bedrock_server_mod.exe 的根
            import os
            bd = os.path.basename(d)
            sub_folders = ("behavior_packs", "resource_packs", "worlds", "config", "plugins", "definitions", "data")
            while bd in sub_folders:
                d = os.path.dirname(d)
                bd = os.path.basename(d)
            self._deploy_dir.setText(d)
            config_mgr.set("server_root_dir", d)
            config_mgr.save()

    def _on_lip_deploy(self):
        if getattr(self, "_install_worker", None) is not None and self._install_worker.isRunning():
            toast_warning("安装进行中", "BDS 正在安装，请等待完成后再部署 LL。", self.window())
            return
        from backend.lip_utils import lip_installed, find_lip_exe, LipCmdWorker
        if not lip_installed():
            toast_error("请先安装 lip", "", self.window())
            return
        deploy_dir = self._deploy_dir.text().strip() or get_context().server_dir
        # 防护：拒绝明显的子目录（如 behavior_packs）
        basename = os.path.basename(deploy_dir)
        if basename in ("behavior_packs", "resource_packs", "worlds", "config", "plugins", "definitions", "data"):
            toast_error("部署目录无效", f"不能部署到 {basename}/ 子目录，请选择服务器根目录", self.window())
            return
        if not os.path.isdir(deploy_dir):
            os.makedirs(deploy_dir, exist_ok=True)
        ver = self._ll_ver.text().strip()
        pkg = "github.com/LiteLDev/LeviLamina"
        # 检测是否已安装——已安装用 update，未安装用 install
        already = os.path.isfile(os.path.join(deploy_dir, "bedrock_server_mod.exe"))
        if already:
            args = ["install", "--upgrade"]
            self._append_lip_term("检测到已安装，升级模式\n", "#ff8c00")
        else:
            args = ["install"]
        if ver:
            args.append(f"{pkg}@{ver}")
        else:
            args.append(pkg)

        self._deploy_btn.setEnabled(False)
        self._deploy_btn.setText("部署中...")
        self._lip_progress.setVisible(True)
        self._lip_progress.setRange(0, 0)

        # 终端输出 + toast
        self._append_lip_term(f"\n═══ 开始部署 BDS + LeviLamina ═══\n", "#0DC5D4")
        self._append_lip_term(f"目录: {deploy_dir}\n", "#888")
        toast_info("lip 部署中", f"正在安装 BDS + LeviLamina 到 {deploy_dir}", self.window())

        lip = find_lip_exe() or "lip"
        self._lip_worker = LipCmdWorker([lip] + args, deploy_dir)
        self._lip_worker.output.connect(self._on_lip_term_output)
        self._lip_worker.finished.connect(self._on_lip_deploy_done)
        self._lip_worker.start()

    def _append_lip_term(self, text: str, color: str = "#ccc"):
        for line in text.split("\n"):
            if "\r" in line:
                line = line.split("\r")[-1]
            if not line:
                continue
            content = ansi_to_html(line) if "\x1b" in line else _html_lip.escape(line)
            self._lip_term.appendHtml(
                f'<span style="color:{color}; white-space:pre-wrap; font-family:Consolas,monospace;">{content}</span>'
            )
        sb = self._lip_term.verticalScrollBar()
        sb.setValue(sb.maximum())
    def _on_lip_deploy_done(self, code: int):
        self._deploy_btn.setEnabled(True)
        self._deploy_btn.setText("安装 BDS + LL")
        self._lip_progress.setVisible(False)
        if code == 0:
            d = self._deploy_dir.text().strip() or get_context().server_dir
            # 自动配置: 更新 LL 目录 + 切换服务器类型
            rel = os.path.relpath(d, SCRIPT_DIR) if os.path.isabs(d) else d
            config_mgr.set("ll_server_dir", rel)
            config_mgr.set("server_type", "ll")
            config_mgr.save()
            self._append_lip_term("✅ 部署完成！已自动切换为 LL 服务器\n", "#4caf50")
            self._append_lip_term(f"> 运行 bedrock_server_mod.exe 启动\n", "#888")
            toast_success("部署完成", f"BDS + LeviLamina 已安装到 {d}\n已自动切换为 LL 服务器", self.window())
        else:
            self._append_lip_term(f"❌ 部署失败 (退出码 {code})\n", "#e81123")
            toast_error("部署失败", f"lip 退出码 {code}，请查看终端输出", self.window())

    def _on_lip_cmd(self):
        cmd = self._lip_cmd.text().strip()
        if not cmd:
            return
        if cmd == "clear":
            self._lip_term.clear()
            self._lip_cmd.clear()
            return
        # 回显
        tc = self._lip_term.textCursor()
        tc.movePosition(QTextCursor.End)
        fmt = tc.charFormat()
        fmt.setForeground(QColor("#0DC5D4"))
        tc.setCharFormat(fmt)
        tc.insertText(f"{self._deploy_dir.text().strip()}> {cmd}\n")
        self._lip_term.setTextCursor(tc)
        self._lip_cmd.clear()

        from backend.lip_utils import LipCmdWorker, find_lip_exe
        cwd = self._deploy_dir.text().strip() or get_context().server_dir
        lip = find_lip_exe()
        if not lip:
            lip = "lip"
        # 用户可能输入 "lip install ..." 或 "install ..."
        parts = cmd.split()
        if parts and parts[0] == "lip":
            parts = parts[1:]
        self._lip_worker = LipCmdWorker([lip] + parts, cwd)
        self._lip_worker.output.connect(self._on_lip_term_output)
        self._lip_worker.start()

    def _on_lip_term_output(self, stdout: str, stderr: str):
        text = stdout or stderr
        if not text:
            return
        for line in text.split("\n"):
            if "\r" in line:
                line = line.split("\r")[-1]
            if not line.strip():
                continue
            content = ansi_to_html(line) if "\x1b" in line else _html_lip.escape(line)
            self._lip_term.appendHtml(
                f'<span style="color:#ccc; white-space:pre-wrap; font-family:Consolas,monospace;">{content}</span>'
            )
        sb = self._lip_term.verticalScrollBar()
        sb.setValue(sb.maximum())
    def _apply_lip_term_theme(self):
        dark = isDarkTheme()
        self._lip_term.setStyleSheet(
            f"QPlainTextEdit {{ background: {'#0d0d0d' if dark else '#fafafa'};"
            f" color: {'#0f0' if dark else '#1a1a1a'};"
            f" border: 1px solid {'#3a3a3a' if dark else '#d0d0d0'}; border-radius: 6px;"
            f" padding: 8px; font-family: Consolas, monospace; font-size: 12px; }}"
        )

    def refresh_theme(self):
        """v3.02.01: 主题切换后重新设置表格/日志/标签样式。"""
        self._ver_table.setStyleSheet(_table_style())
        self._history_table.setStyleSheet(_table_style())
        self._log.setStyleSheet(_plaintext_style())
        self._scan_status.setStyleSheet(f"color: {'#888' if isDarkTheme() else '#666'};")
        if hasattr(self, "_lip_term"):
            self._apply_lip_term_theme()

    def showEvent(self, event):
        """首次显示页面时，如果缓存过期则后台静默刷新（不打断用户）。"""
        super().showEvent(event)
        if self._auto_refreshed:
            return
        self._auto_refreshed = True
        cached = config_mgr.get("version_list", {})
        ts = cached.get("timestamp", 0) if isinstance(cached, dict) else 0
        # 缓存 48 小时内不算过期，减少 GitHub 请求
        if time.time() - ts < 172800:
            return
        # 延迟 800ms 启动后台刷新，避免影响 UI 渲染
        QTimer.singleShot(800, self._auto_refresh)

    def _auto_refresh(self):
        """静默后台拉取 GitHub 版本列表（不打断用户操作）。"""
        # 已经有用户在主动获取就跳过
        if hasattr(self, "_github_worker") and self._github_worker and self._github_worker.isRunning():
            return
        if hasattr(self, "_head_worker") and self._head_worker and self._head_worker.isRunning():
            return
        self._start_github_fetch(silent=True)

    def _refresh_history(self):
        history = _load_upgrade_history()
        self._history_table.setRowCount(len(history))
        for i, h in enumerate(reversed(history)):
            self._history_table.setItem(i, 0, QTableWidgetItem(h.get("timestamp", "")))
            ver_text = f"{h.get('from_version', '?')} → {h.get('version', '?')}"
            self._history_table.setItem(i, 1, QTableWidgetItem(ver_text))
            backup = h.get("backup_dir")
            if backup and os.path.exists(backup):
                btn = PushButton("回滚", self._history_table)
                btn.clicked.connect(lambda checked, b=backup: self._do_rollback(b))
                self._history_table.setCellWidget(i, 2, btn)
            else:
                item = QTableWidgetItem("—")
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                self._history_table.setItem(i, 2, item)

    def _on_compare_versions(self):
        """对比选中的两个版本（Changelog 链接）。"""
        sel = self._ver_table.selectionModel().selectedRows()
        if len(sel) != 2:
            toast_info("提示", "请先在表格中按住 Ctrl 选中 2 个版本", self.window())
            return
        v1 = self._ver_table.item(sel[0].row(), 0).text()
        v2 = self._ver_table.item(sel[1].row(), 0).text()
        # Mojang 官方 Changelog 页
        url = f"https://feedback.minecraft.net/hc/en-us/articles/4410058574989-Minecraft-Bedrock-Changelog"
        mb = MessageBox(
            "版本对比",
            f"已选: {v1} vs {v2}\n\n"
            f"请访问 Mojang 官方 Changelog 页面查看详细变更：\n{url}\n\n"
            f"（本工具暂未集成自动 Changelog 抓取）",
            self.window(),
        )
        mb.exec()

    def _on_rollback(self):
        history = _load_upgrade_history()
        if not history:
            toast_info("无历史", "尚无升级记录可回滚", self.window())
            return
        last = history[-1]
        backup = last.get("backup_dir")
        if not backup or not os.path.exists(backup):
            toast_error("不可用", f"上次的备份已不存在: {backup}", self.window())
            return
        confirm = MessageBox(
            "回滚确认",
            f"将回滚到 {last.get('from_version', '?')} 版本。\n\n"
            f"备份位置: {backup}\n\n是否继续？",
            self.window(),
        )
        if confirm.exec():
            self._do_rollback(backup)

    def _do_rollback(self, backup_dir: str):
        """从备份目录恢复 server.properties / worlds / packs / config。"""
        ctx = get_context()
        server_dir = ctx.server_dir
        restored = []
        try:
            for d in ["worlds", "resource_packs", "behavior_packs", "config"]:
                src = os.path.join(backup_dir, d)
                dst = os.path.join(server_dir, d)
                if os.path.exists(src):
                    if os.path.exists(dst):
                        shutil.rmtree(dst, ignore_errors=True)
                    shutil.copytree(src, dst)
                    restored.append(d)
            for fn in ["server.properties", "allowlist.json", "permissions.json"]:
                src = os.path.join(backup_dir, fn)
                dst = os.path.join(server_dir, fn)
                if os.path.exists(src):
                    shutil.copy2(src, dst)
                    restored.append(fn)
            toast_success("回滚完成", f"已恢复: {', '.join(restored) or '(无)'}", self.window())
        except Exception as e:
            toast_error("回滚失败", str(e), self.window())

    def _check_tool_update(self):
        from backend.self_update import CheckUpdateWorker, DownloadUpdateWorker, verify_sha256, is_valid_zip
        # 保存滚动位置，避免 setText 触发布局刷新后跳回顶部
        vpos = self._scroll.verticalScrollBar().value()
        self._tool_check_btn.setEnabled(False)
        self._tool_status.setText("正在检查更新...")
        self._scroll.verticalScrollBar().setValue(vpos)
        self.__checker = CheckUpdateWorker(self)
        self.__checker.result.connect(lambda s, v, u, sh: self._on_tool_check_done(s, v, u, sh))
        self.__checker.start()

    def _on_tool_check_done(self, status, remote_ver, dl_url, sha256):
        vpos = self._scroll.verticalScrollBar().value()
        self._tool_check_btn.setEnabled(True)
        import main
        if status == "error":
            self._tool_status.setText(f"检查失败: {remote_ver}")
            self._scroll.verticalScrollBar().setValue(vpos)
            return
        if status == "latest":
            self._tool_status.setText(f"已是最新 v{main.__version__}")
            self._scroll.verticalScrollBar().setValue(vpos)
            return
        if not dl_url:
            self._tool_status.setText("未找到下载链接")
            self._scroll.verticalScrollBar().setValue(vpos)
            return
        self._tool_status.setText(f"发现 v{remote_ver}，正在下载...")
        self._tool_bar.setVisible(True)
        self._tool_bar.setRange(0, 100)
        self._tool_bar.setValue(0)
        self._scroll.verticalScrollBar().setValue(vpos)
        from backend.self_update import DownloadUpdateWorker
        self.__dl = DownloadUpdateWorker(dl_url, remote_ver, self)
        self.__dl.progress.connect(self._tool_bar.setValue)
        self.__dl.finished.connect(lambda s, m, p, ver=remote_ver: self._on_tool_dl_done(s, m, p, sha256, ver))
        self.__dl.start()
        toast_info("下载中", f"BDS Manager v{remote_ver} 正在下载...", self.window())

    def _on_tool_dl_done(self, success, msg, path, sha256, remote_ver=""):
        self._tool_bar.setVisible(False)
        if not success:
            self._tool_status.setText(f"下载失败: {msg}")
            toast_error("更新下载失败", msg, self.window())
            return
        self._tool_status.setText(f"✅ 下载完成: v{remote_ver}，准备安装...")
        toast_success("更新就绪", f"BDS Manager v{remote_ver} 下载完成", self.window())
        from backend.self_update import verify_sha256, is_valid_zip
        if not is_valid_zip(path):
            self._tool_status.setText("下载文件无效")
            try: os.remove(path)
            except OSError as e: logger.debug("清理无效 zip 失败: %s", e)
            return
        ok, sha_msg = verify_sha256(path, sha256)
        if not ok:
            self._tool_status.setText(f"❌ SHA256 校验失败: {sha_msg}")
            try: os.remove(path)
            except OSError as e: logger.debug("清理校验失败 zip: %s", e)
            return
        self._tool_zip = path
        self._tool_status.setText(f"✅ 就绪: {os.path.basename(path)} | {sha_msg}")
        self._tool_install_btn.setEnabled(True)

    def _install_tool_update(self):
        if not hasattr(self, "_tool_zip") or not os.path.exists(self._tool_zip):
            self._tool_status.setText("❌ 找不到更新包")
            return
        from backend.self_update import InstallUpdateWorker, restart_app
        self._tool_status.setText("正在安装更新...")
        self._tool_install_btn.setEnabled(False)
        self.__installer = InstallUpdateWorker(self._tool_zip, self)
        self.__installer.finished.connect(lambda s, _: (
            MessageBox.information(self, "更新完成", "BDS Manager 已更新！即将自动重启。") if s else None,
            restart_app("main.py") if s else None
        ))
        self.__installer.start()

    def _log_line(self, msg: str):
        self._log.appendPlainText(msg)
        self._log.moveCursor(QTextCursor.End)

    def _fetch(self):
        """用户点「浏览可用版本」：清旧表 → GitHub 重试 → 失败后提示用户启用 HEAD 嗅探。"""
        if getattr(self, "_fetch_done", False):
            return
        self._fetch_done = True
        self._ver_table.setRowCount(0)
        self._results.clear()
        self._fetch_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._stop_btn.setText("停止")
        self._pending_head_scan = False
        self._log_line("🔄 正在从 GitHub 仓库拉取版本列表...")
        self._start_github_fetch(silent=False)

    def _start_github_fetch(self, silent: bool, attempt: int = 1):
        """单次 GitHub 拉取；失败由 _on_github_done 决定是否重试。"""
        self._github_attempt = attempt
        self._github_silent = silent
        self._scan_status.setText(
            f"🔄 拉取 GitHub 仓库版本列表...（尝试 {attempt}/{self.GITHUB_MAX_RETRIES}）"
        )
        if not silent:
            self._log_line(f"🔄 GitHub 拉取（尝试 {attempt}/{self.GITHUB_MAX_RETRIES}）")
        self._github_worker = GithubFetcher(self)
        # 用默认参数绑定 attempt，避免 lambda 闭包陷阱
        self._github_worker.result.connect(
            lambda ok, r, a=attempt, s=silent: self._on_github_done(ok, r, a, s)
        )
        self._github_worker.start()

    def _on_github_done(self, ok: bool, results: list, attempt: int, silent: bool):
        """单次拉取完成：成功 → 写缓存；失败 → 重试或 fallback。"""
        if ok and results:
            self._on_github_success(results, silent)
            return
        # 失败：还有重试次数？
        if attempt < self.GITHUB_MAX_RETRIES:
            delay = self.GITHUB_BACKOFF_BASE ** (attempt - 1)  # 1, 2, 4 秒
            self._scan_status.setText(
                f"⚠️ GitHub 拉取失败，{delay}s 后重试（{attempt+1}/{self.GITHUB_MAX_RETRIES}）"
            )
            if not silent:
                self._log_line(f"⚠️ GitHub 失败，{delay}s 后重试（{attempt+1}/{self.GITHUB_MAX_RETRIES}）")
            QTimer.singleShot(delay * 1000, lambda: self._start_github_fetch(silent, attempt + 1))
            return
        # 全部失败
        if silent:
            # 后台静默：直接放弃，保留缓存
            self._scan_status.setText(f"❌ 后台静默检查失败（尝试 {attempt} 次），保留缓存")
            return
        # 用户主动：把停止按钮变成"启用 HEAD 嗅探"，让用户决定
        self._on_github_exhausted()

    def _on_github_success(self, results: list, silent: bool):
        """GitHub 拉取成功：写缓存 + 填表。"""
        cached = config_mgr.get("version_list", {}).get("data", [])
        if (len(results) == len(cached)
            and results and cached and results[0] == cached[0]):
            self._save_cache()
            self._populate_table()
            self._scan_status.setText(f"✅ {len(results)} 个版本（无变化）")
            return
        self._results = results
        self._save_cache()
        self._populate_table()
        msg = f"✅ GitHub: {len(results)} 个版本（之前 {len(cached)}）"
        self._scan_status.setText(msg)
        if not silent:
            self._log_line(msg)

    def _on_github_exhausted(self):
        """GitHub 全部失败：把停止按钮改为「启用 HEAD 嗅探」让用户决定（最后手段）。"""
        self._pending_head_scan = True
        self._fetch_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._stop_btn.setText("启用 HEAD 嗅探")
        self._scan_status.setText(
            f"❌ GitHub 失败 {self.GITHUB_MAX_RETRIES} 次 — 可点停止按钮启用 HEAD 嗅探（最后手段，65+ 请求）"
        )
        self._log_line(
            f"❌ GitHub 失败 {self.GITHUB_MAX_RETRIES} 次，嗅探作为最后手段"
        )

    def _start_head_scan(self, base_ver: str, append_mode: bool):
        self._head_worker = HeadScanWorker(
            base_ver, self._patch_spin.value(), self._build_spin.value(),
            append_mode, self,
        )
        self._head_worker.progress.connect(lambda v, p: self._scan_status.setText(f"探测 {v} ({p}%)"))
        self._head_worker.found.connect(self._on_head_found)
        self._head_worker.finished.connect(self._on_scan_done)
        self._head_worker.start()

    def _on_head_found(self, ver: str, branch: str, url: str):
        if not any(v == ver and b == branch for v, b, u in self._results):
            self._results.append((ver, branch, url))
            self._populate_table()

    def _on_scan_done(self):
        self._fetch_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._save_cache()
        self._populate_table()
        self._scan_status.setText(f"共 {len(self._results)} 个版本可用")

    def _save_cache(self):
        # v3.02.02: persist 到磁盘，避免每次重启重新拉 GitHub
        config_mgr.set("version_list", {
            "data": self._results,
            "timestamp": int(time.time()),
        })
        config_mgr.save()

    def _stop_scan(self):
        """根据当前状态执行不同动作：
        1. GitHub 拉取中 → 取消
        2. HEAD 扫描中 → 取消
        3. GitHub 全部失败等待用户决定 → 启动 HEAD 嗅探（最后手段）
        """
        # 状态 3：用户点"启用 HEAD 嗅探"
        if self._pending_head_scan:
            self._pending_head_scan = False
            self._stop_btn.setText("停止")
            self._log_line("⚠️ 启用 HEAD 嗅探（最后手段，会发 65+ 个请求）...")
            self._start_head_scan("1.20.0.0", append_mode=False)
            return
        # 状态 1 & 2：中止正在运行的任务
        if self._github_worker and self._github_worker.isRunning():
            self._github_worker.cancel()
            self._github_worker.wait(800)
        if self._head_worker and self._head_worker.isRunning():
            self._head_worker.cancel()
            self._head_worker.wait(500)
        if self._size_worker and self._size_worker.isRunning():
            self._size_worker.cancel()
            self._size_worker.wait(500)
        self._fetch_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._stop_btn.setText("停止")
        if hasattr(self, "_size_btn"):
            self._size_btn.setEnabled(True)
            self._size_btn.setText("获取文件大小")
        self._scan_status.setText("⏹ 已中止")

    def _populate_table(self):
        seen = set()
        deduped = []
        for v, b, u in self._results:
            if (v, b) not in seen:
                seen.add((v, b))
                deduped.append((v, b, u))
        self._results = deduped
        try:
            deduped.sort(key=lambda x: [int(i) for i in x[0].split(".")], reverse=True)
        except (ValueError, IndexError):
            pass  # 版本号格式异常，保持原顺序

        self._ver_table.setRowCount(len(deduped))
        # 默认占位 "—"，文件大小需要用户点「获取文件大小」按钮才请求（启动加速）
        for i, (ver, branch, url) in enumerate(deduped):
            self._ver_table.setItem(i, 0, QTableWidgetItem(ver))
            # v3.02.02: stable 绿色 / preview 橙色，加 emoji 图标
            is_stable = branch == "stable"
            branch_text = "🟢 稳定版" if is_stable else "🟠 预览版"
            item = QTableWidgetItem(branch_text)
            item.setForeground(QColor("#4CAF50" if is_stable else "#ff9800"))
            self._ver_table.setItem(i, 1, item)
            self._ver_table.setItem(i, 2, QTableWidgetItem("—"))
            btn = PushButton("下载", self._ver_table)
            btn.setMinimumHeight(30)
            btn.setMaximumHeight(34)
            btn.clicked.connect(lambda checked, u=url, v=ver: self._install(u, v))
            self._ver_table.setCellWidget(i, 3, btn)
        # 恢复 size button
        if hasattr(self, "_size_btn"):
            self._size_btn.setEnabled(True)
            self._size_btn.setText("获取文件大小")

    def _fetch_sizes(self):
        """用户点「获取文件大小」时启动后台 HEAD 请求。"""
        items_for_size: list[tuple[int, str]] = []
        for i, (_v, _b, url) in enumerate(self._results[:self._ver_table.rowCount()]):
            items_for_size.append((i, url))
        if not items_for_size:
            return
        if self._size_worker and self._size_worker.isRunning():
            self._size_worker.cancel()
            self._size_worker.wait(500)
        self._size_worker = HeadSizeWorker(items_for_size, self)
        self._size_worker.result.connect(self._on_size_ready)
        self._size_worker.start()
        self._size_btn.setEnabled(False)
        self._size_btn.setText("正在获取...")

    def _on_size_ready(self, row: int, size_text: str):
        if row < self._ver_table.rowCount():
            self._ver_table.setItem(row, 2, QTableWidgetItem(size_text))

    def _download_manual(self):
        ver = self._manual_input.text().strip()
        if not ver:
            return
        url = f"https://www.minecraft.net/bedrockdedicatedserver/bin-win/bedrock-server-{ver}.zip"
        self._install(url, ver)

    def _install(self, url: str, version: str):
        ctx = get_context()
        # 下载确认
        from qfluentwidgets import MessageBox
        if not hasattr(self, "_skip_confirm"):
            w = MessageBox("确认下载", f"即将下载 BDS {version}\n\n当前服务器文件将自动备份。\n是否继续？", self.window())
            w.yesSignal.connect(lambda: self._install_after_confirm(url, version, True))
            w.cancelSignal.connect(w.close)
            w.show()
            return
        self._install_after_confirm(url, version, False)

    def _install_after_confirm(self, url: str, version: str, skip_next: bool):
        if skip_next:
            self._skip_confirm = True
        self._dl_bar.setVisible(True)
        self._dl_bar.setRange(0, 100)
        self._dl_bar.setValue(0)
        self._log_line(f"准备安装 BDS {version}")

        dl_path = os.path.join(SCRIPT_DIR, f"_update_v{version}.zip")
        self._dl_worker = DownloadWorker(url, dl_path, self)
        self._dl_worker.progress.connect(self._dl_bar.setValue)
        self._dl_worker.status.connect(self._dl_status.setText)
        self._dl_worker.finished.connect(lambda ok, msg: self._on_dl_done(ok, msg, dl_path, version))
        self._dl_worker.start()
        # v3.02.02: 下载开始 toast
        toast_info("下载中", f"BDS {version} 正在下载...", self.window())

    def _on_dl_done(self, ok: bool, msg: str, zip_path: str, version: str):
        self._dl_bar.setVisible(False)
        if not ok:
            toast_error("下载失败", msg, self.window())
            self._log_line(f"下载失败: {msg}")
            return
        self._log_line(f"下载完成: {os.path.basename(zip_path)}")
        toast_success("下载完成", f"BDS {version} 下载完成，请选择安装路径", self.window())
        # 保存状态，等待用户选择安装路径
        self._pending_zip = zip_path
        self._pending_version = version
        # 显示安装区，填充当前 BDS 目录
        ctx_dl = get_context()
        stype_dir = config_mgr.get("server_type", "bds")
        if stype_dir == "ll" and ctx_dl.ll_dir:
            self._install_dir.setText(ctx_dl.ll_dir)
        else:
            self._install_dir.setText(ctx_dl.bds_dir if hasattr(ctx_dl, "bds_dir") else ctx_dl.server_dir)
        stype_info = config_mgr.get("server_type", "bds")
        self._install_info.setText(f"已下载 BDS {version}，请选择安装路径后点击 [开始安装]" + (f"\n⚠ 当前服务器模式: {stype_info.upper()}" if stype_info != "bds" else ""))
        self._install_btn.setEnabled(True)
        self._install_card.setVisible(True)
        self._update_install_status()
        # 滚动到安装区
        from PySide6.QtCore import QTimer
        QTimer.singleShot(100, lambda: self._scroll.ensureWidgetVisible(self._install_card))

    def _browse_install_dir(self):
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, "选择 BDS 安装目录", self._install_dir.text() or SCRIPT_DIR)
        if d:
            self._install_dir.setText(d)
            self._update_install_status()

    def _update_install_status(self):
        d = self._install_dir.text()
        if not d or not os.path.isdir(d):
            self._install_status.setText("请选择一个有效的目录")
            return
        has_bds = os.path.isfile(os.path.join(d, bds_exe()))
        has_ll = os.path.isfile(os.path.join(d, ll_exe()))
        stype = config_mgr.get("server_type", "bds")
        if has_bds and has_ll:
            self._install_status.setText("检测到 BDS + LL — 将备份后再升级")
        elif has_bds:
            self._install_status.setText("检测到已有 BDS — 将备份后再升级" + (" (当前: LL 模式)" if stype == "ll" else ""))
        elif has_ll:
            self._install_status.setText("检测到已有 LL — 将备份后再升级" + (" (当前: BDS 模式)" if stype == "bds" else ""))
        else:
            self._install_status.setText("空目录 — 将完整安装")

    def _do_install(self):
        if getattr(self, "_lip_worker", None) is not None and self._lip_worker.isRunning():
            toast_warning("部署进行中", "LL 正在部署，请等待完成后再安装 BDS。", self.window())
            return
        if not hasattr(self, "_pending_zip") or not os.path.exists(self._pending_zip):
            toast_error("安装失败", "未找到已下载的安装包", self.window())
            return
        target = self._install_dir.text()
        if not target or not os.path.isdir(target):
            toast_error("安装失败", "请选择有效的安装目录", self.window())
            return

        version = self._pending_version
        zip_path = self._pending_zip
        is_upgrade = os.path.isfile(os.path.join(target, bds_exe())) or os.path.isfile(os.path.join(target, ll_exe()))

        self._log_line(f"{'升级' if is_upgrade else '新装'} BDS {version} → {target}")
        self._install_btn.setEnabled(False)
        self._install_progress.setVisible(True)
        self._install_progress.setRange(0, 0)  # 不确定进度

        self._install_worker = InstallWorker(
            zip_path, target, is_upgrade, version, "", self
        )
        self._install_worker.log.connect(self._log_line)
        self._install_worker.finished.connect(lambda s, m: self._on_install_done(s, m, zip_path, target, is_upgrade))
        self._install_worker.start()

    def _on_install_done(self, success: bool, msg: str, zip_path: str, target: str = "", is_upgrade: bool = False):
        self._install_progress.setVisible(False)
        self._install_card.setVisible(False)
        try:
            if os.path.exists(zip_path):
                os.remove(zip_path)
        except OSError as e:
            logger.debug("清理安装包失败 (%s): %s", zip_path, e)
        if hasattr(self, "_pending_zip"):
            del self._pending_zip
            del self._pending_version
        self._install_btn.setEnabled(False)
        if success:
            # 安装成功 → 自动更新 server_dir 配置
            ctx = get_context()
            current_dir = ctx.bds_dir if hasattr(ctx, "bds_dir") else ctx.server_dir
            if os.path.abspath(target) != os.path.abspath(current_dir):
                config_mgr.set("server_dir", target)
                config_mgr.save()
                from shared.config import refresh_context_from_config
                refresh_context_from_config()
                toast_success("安装完成", f"BDS 已安装到 {target}\n已自动切换服务器目录", self.window())
            else:
                toast_success("安装完成", f"BDS 已{'更新' if is_upgrade else '安装'}到 {target}\n请重新启动服务器", self.window())
            self._refresh_history()
        else:
            toast_error("安装失败", msg, self.window())
            self._install_btn.setEnabled(True)
