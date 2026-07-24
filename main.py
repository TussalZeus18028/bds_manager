# -*- coding: utf-8 -*-
"""
BDS Manager Fluent -- 主入口

v3.1 改进：
- 注入 monitor 到 dashboard（绘制资源曲线）
- 监听 WorldPage backup_completed → 更新 Dashboard 最近备份时间
- 监听 ServerProcess.proc_stats → 更新 Dashboard BDS 进程卡
- 监听 ConsolePage._append_output → 通知 Dashboard 假死检测
- 使用 GzipRotatingFileHandler 替代 basicConfig
- 注册 Ctrl+K 命令面板
- 全局异常钩子
- 系统主题变化监听（Qt 6.5+）
- 优雅停服（graceful_shutdown）
"""

import sys
import os
import time
import logging
from datetime import datetime

# ---------- 屏蔽 QFluentWidgets 的 ANSI 彩色 Tips ----------
_real_stdout = sys.stdout
sys.stdout = open(os.devnull, "w", encoding="utf-8")
import qfluentwidgets  # noqa: E402
sys.stdout.close()
sys.stdout = _real_stdout
# ----------------------------------------------------------

from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QSplashScreen
from PySide6.QtGui import QColor, QIcon, QAction, QShortcut, QKeySequence
from PySide6.QtCore import Qt, QTimer, QByteArray
from qfluentwidgets import (
    FluentWindow, FluentIcon, setTheme, setThemeColor, Theme, SystemTrayMenu,
)

from shared.config import config_mgr, init_context, SCRIPT_DIR, LOG_DIR, get_context
from shared.errors import set_error_handler, install_excepthook
from shared.toast import toast_error, toast_success, toast_warning
from shared.errors import handle_errors
from backend.server import ServerProcess
from backend.monitor import SystemResourceMonitor, SystemStatsSnapshot
from backend.webhook import send_webhook
from backend.self_update import CheckUpdateWorker, DownloadUpdateWorker, InstallUpdateWorker, verify_sha256, is_valid_zip, restart_app
from backend.notifications import notify  # v3.02.00 通知中心
from backend.notifications import get_bus as _notify_bus, get_unread_count as _notify_unread
from components.notification_panel import BellButton, NotificationDrawer
from backend.log_handler import make_rotating_file_handler
from pages.dashboard import DashboardPage
from pages.console import ConsolePage
from pages.settings import SettingsPage
from pages.world import WorldPage
from pages.config import ConfigPage
from pages.packs import PacksPage
from pages.upgrade import UpgradePage
from pages.tunnel import TunnelPage
from pages.about import AboutPage
from pages.command_palette import CommandPaletteDialog, build_default_commands

# ---------- 日志（按大小轮转 + gzip 压缩） ----------
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        make_rotating_file_handler(
            os.path.join(LOG_DIR, "bds_manager.log"),
            max_bytes=5 * 1024 * 1024,
            backups=5,
        ),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("bds_manager")

__version__ = "3.02.02"
# ⚠️ 工具版本固定写在这里，不在 bds_manager_config.json / bds_version_cache.json 等任何配置文件中。
# 如果需要做配置兼容性检查，读取远端 version.json（自更新流程用）即可。
# 格式规范：x.xx.xx —— Major 1 位、Minor 2 位（补零）、Patch 2 位（补零）
# 例：3.1.0 → 3.01.00；3.10.5 → 3.10.05
# 注意：旧项目（v2.x，Manager/）版本格式是 x.xx.xx.xx (4段)，compare_versions 已兼容任意段数。
__version_info__ = (3, 2, 2)
__release_date__ = "2026-07-24"


def format_version(major: int, minor: int, patch: int) -> str:
    """把 (major, minor, patch) 元组格式化为 x.xx.xx 字符串。"""
    return f"{major}.{minor:02d}.{patch:02d}"


def get_version() -> str:
    """返回当前工具版本字符串（x.xx.xx 格式）。"""
    return __version__


def get_version_info() -> tuple:
    """返回当前工具版本元组（语义比较用，不补零）。"""
    return __version_info__


# ---------- 错误处理桥接 ----------
def _toast_error_handler(title: str, msg: str, level: str):
    """把 shared/errors 的报告桥接到 toast 通知。"""
    if level == "ERROR":
        toast_error(title, msg, _MAIN_WINDOW_REF[0])
    elif level == "WARNING":
        toast_warning(title, msg, _MAIN_WINDOW_REF[0])
    else:
        toast_success(title, msg, _MAIN_WINDOW_REF[0])

_MAIN_WINDOW_REF: list = [None]


class BDSFluentWindow(FluentWindow):
    """BDS Manager 主窗口 - Fluent Design。"""

    def __init__(self):
        super().__init__()
        self._server: ServerProcess | None = None
        self._monitor: SystemResourceMonitor | None = None
        self._tray = None
        self._bell = None
        self._notif_drawer = None
        self._restart_count = 0
        self._lag_samples: list[float] = []
        self._current_color = config_mgr.get("theme_color", "#0DC5D4")
        self._setup_window()
        self._init_pages()
        self._setup_notification_panel()  # v3.02.00 通知中心
        # v3.02.01: _restore_window_state 移到了 showEvent（等 window system 就绪）
        self._geom_restored = False
        self._init_shortcuts()
        # 把窗口引用暴露给 errors handler
        _MAIN_WINDOW_REF[0] = self
        # 延迟初始化重组件（启动加速）。
        # 启动 Toast / 升级列表 / 自更新检查 都在 _init_services → _startup_toasts 中调度，
        # 不要在这里重复注册（否则 toast 和网络请求都会触发两次）。
        QTimer.singleShot(300, self._setup_tray)        # 系统托盘：Win 创建慢
        QTimer.singleShot(500, self._init_services)     # 资源监控 + 启动 Toast + 升级 + 自更新

    def showEvent(self, event):
        """v3.02.01：首次 show 时恢复窗口状态。

        restoreGeometry 在 window.show() 前调用不生效——window system 还没 attach。
        移到 showEvent 确保在 QMainWindow 完成所有初始化后恢复状态。
        """
        super().showEvent(event)
        if not self._geom_restored:
            self._geom_restored = True
            self._restore_window_state()

    # ---------- 窗口 ----------
    def _setup_window(self):
        self.setWindowTitle(f"BDS Manager Fluent v{__version__}")
        self.setMinimumSize(960, 620)
        self.navigationInterface.setExpandWidth(280)

    def _save_geometry(self):
        """v3.02.01：保存窗口几何，同时存 width/height 做可靠 fallback。

        用 QMainWindow.saveGeometry() 保存 base64 格式（含 maximized/normal 状态），
        同时存 width/height 确保即使 restoreGeometry 在启动时机不工作也有降级方案。
        """
        try:
            geom_b64 = bytes(self.saveGeometry().toBase64()).decode("ascii")
            config_mgr.set("window_geometry", geom_b64)
            # 冗余保存 width/height，让 _restore_window_state 的 fallback 总能生效
            config_mgr.set("window_width", self.width())
            config_mgr.set("window_height", self.height())
        except Exception:
            pass

    def _restore_window_state(self):
        """v3.02.01：恢复窗口状态。

        分两层：
        1. restoreGeometry(base64) — 优先，能还原 maximized/fullscreen + 位置
        2. resize(width, height) — 降级，简单但可靠（永远生效）
        """
        geom_b64 = config_mgr.get("window_geometry", "")
        if geom_b64:
            try:
                ba = QByteArray.fromBase64(geom_b64.encode("ascii"))
                if not ba.isEmpty() and self.restoreGeometry(ba):
                    return
            except Exception:
                pass
        w = config_mgr.get("window_width", 1200)
        h = config_mgr.get("window_height", 800)
        self.resize(w, h)
        # fallback：旧 config 或无配置 → 用默认尺寸
        w = config_mgr.get("window_width", 1200)
        h = config_mgr.get("window_height", 800)
        self.resize(w, h)

    def _setup_tray(self):
        self._tray = QSystemTrayIcon(self)
        self._tray.setToolTip("BDS Manager")
        from qfluentwidgets import FluentIcon as _FI
        self._tray.setIcon(_FI.HOME.icon())
        self._tray.activated.connect(self._on_tray_activated)

        menu = QMenu()
        show_action = menu.addAction("显示窗口")
        show_action.triggered.connect(self._show_from_tray)
        menu.addSeparator()
        cmd_palette_action = menu.addAction("命令面板 (Ctrl+K)")
        cmd_palette_action.triggered.connect(self._open_command_palette)
        menu.addSeparator()
        quit_action = menu.addAction("退出")
        quit_action.triggered.connect(self.close)
        self._tray.setContextMenu(menu)
        self._tray.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self._show_from_tray()

    def _show_from_tray(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def _init_pages(self):
        from qfluentwidgets import NavigationItemPosition

        self.dashboard_page = DashboardPage(self)
        self.dashboard_page.setObjectName("dashboard")
        self.addSubInterface(self.dashboard_page, FluentIcon.HOME, "仪表盘")

        self.console_page = ConsolePage(self)
        self.console_page.setObjectName("console")
        self.addSubInterface(self.console_page, FluentIcon.COMMAND_PROMPT, "控制台")

        self.world_page = WorldPage(self)
        self.world_page.setObjectName("world")
        # 监听备份完成 → 更新 Dashboard 最近备份时间
        self.world_page.backup_completed.connect(self._on_backup_completed)
        self.addSubInterface(self.world_page, FluentIcon.SAVE, "世界")

        self.packs_page = PacksPage(self)
        self.packs_page.setObjectName("packs")
        self.addSubInterface(self.packs_page, FluentIcon.FOLDER, "资源包")

        self.config_page = ConfigPage(self)
        self.config_page.setObjectName("config")
        self.addSubInterface(self.config_page, FluentIcon.EDIT, "配置")

        self.upgrade_page = UpgradePage(self)
        self.upgrade_page.setObjectName("upgrade")
        self.addSubInterface(self.upgrade_page, FluentIcon.SYNC, "升级")

        self.tunnel_page = TunnelPage(self)
        self.tunnel_page.setObjectName("tunnel")
        self.addSubInterface(self.tunnel_page, FluentIcon.LINK, "隧道")

        self.about_page = AboutPage(self)
        self.about_page.setObjectName("about")
        self.addSubInterface(
            self.about_page, FluentIcon.INFO, "关于",
            position=NavigationItemPosition.BOTTOM,
        )

        self.settings_page = SettingsPage(self)
        self.settings_page._main_window = self
        self.settings_page.setObjectName("settings")
        self.addSubInterface(
            self.settings_page, FluentIcon.SETTING, "设置",
            position=NavigationItemPosition.BOTTOM,
        )

    def _setup_notification_panel(self):
        """v3.02.00 通知中心：顶部铃铛 + 右侧抽屉。

        v3.02.01：bell 不再放在 self.width()-56（会与 titleBar 右上角的最小化/最大化/关闭按钮重叠），
        而是塞进 titleBar.buttonLayout，排在 minBtn 之前。这样：
        - bell 永远在 titleBar 内，不会与 stackedWidget 内容重叠
        - 与系统按钮有间距（buttonLayout 自动处理）
        - 窗口缩放时 bell 自动跟随
        """
        self._bell = BellButton(self.titleBar)
        # 插入到 buttonLayout 的最前面（在 minBtn/maxBtn/closeBtn 之前）
        self.titleBar.buttonLayout.insertWidget(0, self._bell)
        # 让 buttonLayout 排版生效
        self.titleBar.buttonLayout.insertSpacing(1, 8)
        self._bell.clicked.connect(self._toggle_notification_drawer)
        # 初始未读数
        self._bell.set_unread(_notify_unread())
        # 监听未读数变化
        _notify_bus().unread_count_changed.connect(self._bell.set_unread)
        # 抽屉
        self._notif_drawer = NotificationDrawer(self)
        self._notif_drawer.hide()
        self._notif_drawer.navigate_requested.connect(self._on_notif_navigate)
        # 首启气泡（v3.02.00 起开始提示，可关闭）
        if config_mgr.get("show_command_palette_tip", True):
            QTimer.singleShot(2000, self._show_command_palette_tip)

    def _toggle_notification_drawer(self):
        if self._notif_drawer and self._notif_drawer.isVisible():
            self._notif_drawer.hide_drawer()
        else:
            self._notif_drawer and self._notif_drawer.show_drawer()

    def _on_notif_navigate(self, page_name: str, params: dict):
        """通知点击跳转：切到对应页 + 高亮目标（参数由 page 自己解析）。"""
        # 找到对应的 subInterface
        target = getattr(self, f"{page_name}_page", None)
        if target is None:
            return
        self.switchTo(target)
        # 高亮目标（params 由各页处理）
        if params and hasattr(target, "highlight_target"):
            try:
                target.highlight_target(params)
            except Exception as e:
                logger.debug("通知高亮失败: %s", e)

    def _show_command_palette_tip(self):
        """首次启动提示气泡：按 Ctrl+K 试试命令面板。"""
        if not self._bell:
            return
        # qfluentwidgets 的 TeachingTip 需要 FlyoutView 作为内容承载
        from qfluentwidgets import TeachingTip, FlyoutView, FluentIcon
        view = FlyoutView(
            title="试试命令面板",
            content="随时按 Ctrl+K 打开命令面板，搜索任何动作（重启、备份、跳转页面…）",
            icon=FluentIcon.HEART,
            isClosable=True,
        )
        tip = TeachingTip(
            view=view,
            target=self._bell,
            parent=self,
            duration=8000,
        )
        # v3.02.01 fix: TeachingTip 没有 closed 信号，只有 destroyed（widget 销毁时触发）
        # isDeleteOnClose=True 时，duration 到期或用户关闭都会 deleteLater → destroyed 触发
        tip.destroyed.connect(lambda: config_mgr.set("show_command_palette_tip", False))

    def resizeEvent(self, event):
        """窗口尺寸变化 —— bell 已放进 titleBar.buttonLayout，无需手动定位。"""
        super().resizeEvent(event)

    # ---------- 服务初始化（资源监控 + 启动 toast + 自更新） ----------
    def _init_services(self):
        self._monitor = SystemResourceMonitor(self)
        self._monitor.stats_updated.connect(self._on_stats_updated)
        self._monitor.stats_updated.connect(self.dashboard_page.resource_card.update_stats)
        # 把 monitor 注入 dashboard 用于绘制曲线
        self.dashboard_page.set_monitor(self._monitor)
        self._monitor.start(config_mgr.get("monitor_interval", 2000))

        if config_mgr.get("show_startup_toasts", True):
            QTimer.singleShot(800, self._startup_toasts)

        # 监听系统主题变化
        if config_mgr.get("follow_system_theme", False):
            try:
                app = QApplication.instance()
                if app and hasattr(app, "styleHints"):
                    app.styleHints().colorSchemeChanged.connect(self._on_system_theme_changed)
            except Exception:
                pass

    def _on_system_theme_changed(self, scheme):
        """系统主题切换时自动应用（仅当 follow_system_theme=True）。"""
        try:
            if not config_mgr.get("follow_system_theme", False):
                return
            from PySide6.QtCore import Qt as _Qt
            is_dark = (scheme == _Qt.ColorScheme.Dark)
            theme = "dark" if is_dark else "light"
            self.apply_theme(theme, self._current_color)
            config_mgr.set("theme", theme)
            logger.info("系统主题切换 → %s", theme)
        except Exception as e:
            logger.debug("系统主题切换异常: %s", e)

    def _on_backup_completed(self):
        """WorldPage 备份完成时刷新 Dashboard 的最近备份时间。"""
        try:
            ctx = get_context()
            from backend.backup import get_backup_files
            files = get_backup_files(ctx.backup_dir)
            if files:
                latest = files[0]  # 已经按 mtime 倒序
                import time as _t
                mtime = os.path.getmtime(os.path.join(ctx.backup_dir, latest))
                delta = int(_t.time() - mtime)
                if delta < 60: text = f"{delta} 秒前"
                elif delta < 3600: text = f"{delta // 60} 分钟前"
                elif delta < 86400: text = f"{delta // 3600} 小时前"
                else: text = f"{delta // 86400} 天前"
                self.dashboard_page.set_backup_time(text)
                notify("success", "backup", "备份完成", latest,
                       f"page:world?backup={latest}")
        except Exception as e:
            logger.debug("更新最近备份时间失败: %s", e)

    def _startup_toasts(self):
        # 防御：防止重复触发（_startup_toasts 一次会话只跑一次）
        if getattr(self, "_toasted", False):
            return
        self._toasted = True
        import psutil
        from shared.toast import toast_success, toast_error, toast_warning, toast_info

        ctx = get_context()
        server_dir = ctx.server_dir

        if os.path.isdir(server_dir):
            toast_success(f"服务器: {os.path.basename(server_dir)}", "目录就绪", self)
        else:
            toast_error("服务器目录不存在", server_dir, self, duration=8000)

        exe_name = config_mgr.get("server_exe", "bedrock_server.exe")
        exe_path = os.path.join(server_dir, exe_name)
        if os.path.exists(exe_path):
            toast_info(f"服务端: {exe_name}", "可执行文件就绪", self)
        else:
            toast_warning(f"服务端: {exe_name}", "未找到，请先安装 BDS", self, duration=6000)

        try:
            cpu = psutil.cpu_percent()
            mem = psutil.virtual_memory().percent
            toast_info("系统资源", f"CPU {cpu:.0f}%  内存 {mem:.0f}%", self)
        except Exception:
            pass

        if os.path.exists(ctx.backup_dir):
            backups = [f for f in os.listdir(ctx.backup_dir) if f.endswith(".zip")]
            if backups:
                latest = max(backups, key=lambda f: os.path.getmtime(os.path.join(ctx.backup_dir, f)))
                toast_info("备份状态", f"最近: {latest[:50]}（共 {len(backups)} 个）", self)
            else:
                toast_info("备份状态", "暂无备份", self)
        else:
            toast_info("备份状态", "备份目录尚未创建", self)

        toast_info(f"BDS Manager v{__version__}", "就绪，等待操作（Ctrl+K 打开命令面板）", self)

        QTimer.singleShot(5000, self.upgrade_page._fetch)

        if config_mgr.get("auto_check_update", True):
            QTimer.singleShot(5000, self._check_self_update)

    def _restore_window_state(self):
        w = config_mgr.get("window_width", 1200)
        h = config_mgr.get("window_height", 800)
        self.resize(w, h)

    def resizeEvent(self, event):
        """v3.02.01：实时保存窗口几何（含 maximized 状态）。
        
        之前保存 width/height，最大化时存的是最大化后的尺寸（错），下次启动恢复成大窗口
        而不是最大化。改用 saveGeometry 始终保存 normalGeometry + windowState flag。
        """
        super().resizeEvent(event)
        self._save_geometry()

    def closeEvent(self, event):
        if self._tray and self._tray.isVisible() and config_mgr.get("close_to_tray", True):
            event.ignore()
            self.hide()
            return
        self.stop_server()
        if self._monitor:
            self._monitor.stop()
        if hasattr(self, "world_page"):
            self.world_page.cleanup()
        if hasattr(self, "tunnel_page"):
            self.tunnel_page.cleanup()
        if hasattr(self, "upgrade_page"):
            self.upgrade_page._stop_scan()
        self._tray.hide()
        # v3.02.01：正常关闭时显式保存几何（resizeEvent 已实时保存，这里再保证一次）
        self._save_geometry()
        config_mgr.save()
        super().closeEvent(event)

    # ---------- 快捷键 ----------
    def _init_shortcuts(self):
        """v3.02.00：通过 ShortcutManager 注册所有快捷键，支持用户自定义。"""
        from backend.shortcuts import ShortcutManager, DEFAULT_SHORTCUTS

        mgr = ShortcutManager.get_instance()
        mgr.set_main_window(self)

        # 注册默认快捷键（12 个）
        for action_id, label, scope, default_key in DEFAULT_SHORTCUTS:
            mgr.register(
                action_id=action_id,
                label=label,
                scope=scope,
                default_key=default_key,
                callback=self._get_shortcut_callback(action_id),
            )

        # 应用用户自定义（如果 config 里有覆盖）
        mgr.apply_user_overrides()

        # Ctrl+1..7 切页（特殊处理：保持原有行为，不进 ShortcutManager）
        # v3.02.01 fix: navigationInterface.setCurrentItem 只亮导航不切页面（qfluentwidgets bug），
        # 改用 switchTo(page) — 同时更新导航高亮和 stackedWidget
        for i, key in enumerate(["dashboard", "console", "world", "packs",
                                  "config", "upgrade", "tunnel"]):
            page = getattr(self, f"{key}_page", None)
            if page is not None:
                QShortcut(QKeySequence(f"Ctrl+{i+1}"), self,
                          activated=lambda p=page: self.switchTo(p))

        # 监听页面切换 → 更新快捷键作用域
        try:
            self.stackedWidget.currentChanged.connect(self._on_page_changed_for_shortcuts)
            # 初始作用域
            self._on_page_changed_for_shortcuts(0)
        except Exception:
            pass

        # v3.02.00 fix: 刷新设置页的快捷键列表（init 时 ShortcutManager 才有内容）
        if hasattr(self, "settings_page") and hasattr(self.settings_page, "refresh_shortcut_card"):
            self.settings_page.refresh_shortcut_card()

    def _get_shortcut_callback(self, action_id: str):
        """返回 action_id 对应的回调函数。"""
        from backend.shortcuts import ShortcutManager
        cb_map = {
            "command_palette":   self._open_command_palette,
            "restart_tool":      self._restart_app,
            "restart_server":    self._shortcut_restart_server,
            "manual_backup":     self._shortcut_manual_backup,
            "save_world":        self._shortcut_save_world,
            "stop_server":       self._shortcut_stop_server,
            "open_settings":     self._shortcut_open_settings,
            "toggle_theme":      self._shortcut_toggle_theme,
            "open_world":        self._shortcut_open_world,
            "clear_console":     self._shortcut_clear_console,
            "search_console":    self._shortcut_search_console,
            "refresh_dashboard": self._shortcut_refresh_dashboard,
        }
        return cb_map.get(action_id, lambda: None)

    # ---------- 快捷键回调 ----------
    def _shortcut_restart_server(self):
        if self.is_server_running():
            self.stop_server()
            QTimer.singleShot(3000, self.start_server)
        else:
            self.start_server()

    def _shortcut_manual_backup(self):
        if hasattr(self, "world_page") and self.world_page:
            self.world_page.do_backup_now()

    def _shortcut_save_world(self):
        if self.is_server_running():
            self._server and self._server.send_save_all()
            from shared.toast import toast_success
            toast_success("已发送", "save-all + save-on", self)

    def _shortcut_stop_server(self):
        if self.is_server_running():
            self.stop_server()

    def _shortcut_open_settings(self):
        if hasattr(self, "settings_page"):
            self.switchTo(self.settings_page)

    def _shortcut_toggle_theme(self):
        cur = config_mgr.get("theme", "dark")
        new = "light" if cur == "dark" else "dark"
        config_mgr.set("theme", new)
        self.apply_theme(new, self._current_color)

    def _shortcut_open_world(self):
        if hasattr(self, "world_page"):
            self.switchTo(self.world_page)

    def _shortcut_clear_console(self):
        if hasattr(self, "console_page"):
            self.console_page.clear_output()

    def _shortcut_search_console(self):
        if hasattr(self, "console_page"):
            self.switchTo(self.console_page)
            if hasattr(self.console_page, "_search_edit"):
                self.console_page._search_edit.setFocus()

    def _shortcut_refresh_dashboard(self):
        # 仪表盘自带 QTimer 自动刷新，这里强制刷新一次状态
        if hasattr(self, "dashboard_page"):
            try:
                self.dashboard_page.status_card.refresh_status()
            except Exception:
                pass

    def _on_page_changed_for_shortcuts(self, idx):
        """主窗口 stackedWidget 切页时通知 ShortcutManager 更新作用域。"""
        from backend.shortcuts import ShortcutManager
        # idx → page name
        widget = self.stackedWidget.widget(idx) if hasattr(self, "stackedWidget") else None
        scope = "global"
        if widget is not None:
            scope = widget.objectName() or "global"
        ShortcutManager.get_instance().set_scope(scope)

    def _open_command_palette(self):
        cmds = build_default_commands(self)
        dlg = CommandPaletteDialog(cmds, self)
        dlg.exec()

    def keyPressEvent(self, event):
        if event.modifiers() == (Qt.ControlModifier | Qt.ShiftModifier) and event.key() == Qt.Key_R:
            self._restart_app()
            return
        super().keyPressEvent(event)

    def _restart_app(self):
        from shared.toast import toast_info
        toast_info("工具即将重启", "将在 1 秒后自动重启", self)
        QTimer.singleShot(1000, lambda: restart_app("main.py"))

    # ---------- 主题 ----------
    def apply_theme(self, theme: str = "dark", accent_color: str = "#0DC5D4"):
        self._current_color = accent_color
        theme_map = {"dark": Theme.DARK, "light": Theme.LIGHT, "auto": Theme.AUTO}
        setTheme(theme_map.get(theme, Theme.DARK))
        try:
            setThemeColor(QColor(accent_color))
        except Exception:
            setThemeColor(QColor("#0DC5D4"))

        # v3.02.01 fix：主题切换后通知抽屉刷新（背景色 + chip 样式）
        # 抽屉在 _build_ui 时一次性读取 isDarkTheme()，主题切换后不会自动更新。
        # 这里手动调用 refresh()，使其按当前主题重建 chip 和 list 样式。
        try:
            if hasattr(self, "_notif_drawer") and self._notif_drawer is not None:
                self._notif_drawer.refresh_theme()
        except Exception:
            pass

        # v3.02.01：同步刷新各页面里主题感知的硬编码颜色（status_badge/bds_card/tasks_card 等）
        for page_attr in ("dashboard_page", "packs_page", "settings_page",
                          "console_page", "world_page", "config_page",
                          "upgrade_page", "tunnel_page", "about_page"):
            page = getattr(self, page_attr, None)
            if page is not None and hasattr(page, "refresh_theme"):
                try:
                    page.refresh_theme()
                except Exception:
                    pass

        is_dark = theme_map.get(theme, Theme.DARK) != Theme.LIGHT
        handle = "#555" if is_dark else "#bbb"
        handle_hover = "#777" if is_dark else "#999"
        track = "transparent"
        self.setStyleSheet(f"""
            QScrollBar:vertical {{
                width: 6px;
                background: {track};
                border: none;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {handle};
                border-radius: 3px;
                min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {handle_hover};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0; border: none;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
            QScrollBar:horizontal {{
                height: 6px;
                background: {track};
                border: none;
                margin: 0;
            }}
            QScrollBar::handle:horizontal {{
                background: {handle};
                border-radius: 3px;
                min-width: 30px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background: {handle_hover};
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0; border: none;
            }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
                background: none;
            }}
        """)
        logger.info("主题: %s, 主色: %s", theme, accent_color)

    # ---------- 服务器管理 ----------
    @property
    def server(self) -> ServerProcess | None:
        return self._server

    @property
    def is_server_running(self) -> bool:
        return self._server is not None and self._server.is_running

    def start_server(self):
        if self._server and self._server.is_running:
            return "服务器已在运行中"

        ctx = get_context()
        exe_path = os.path.join(ctx.server_dir, config_mgr.get("server_exe", "bedrock_server.exe"))
        if not os.path.exists(exe_path):
            err = f"未找到服务器可执行文件: {exe_path}"
            notify("error", "server", "服务器启动失败", err, "page:dashboard")
            return err

        self._server = ServerProcess(exe_path, ctx.server_dir)
        self._server.output_received.connect(self._on_server_output)
        self._server.process_stopped.connect(self._on_server_stopped)
        self._server.error_occurred.connect(
            lambda msg: (
                self.console_page._append_output(f"[ERROR] {msg}", "#ff5555"),
                notify("error", "server", "服务器错误", msg, "page:console"),
            )
        )
        self._server.status_changed.connect(self._on_status_changed)
        # 进程级资源（如果启用）
        if config_mgr.get("enable_bds_process_monitor", True):
            self._server.proc_stats.connect(self.dashboard_page.update_proc_stats)
        self._server.start()

        self.dashboard_page._on_server_started()
        self.console_page._on_server_started()
        notify("success", "server", "服务器已启动", os.path.basename(exe_path), "page:dashboard")

        if not hasattr(self, "_lag_timer") or not self._lag_timer:
            self._lag_timer = QTimer(self)
            self._lag_timer.timeout.connect(self._lag_ping)
        self._lag_timer.start(30000)
        return None

    def stop_server(self):
        if self._server and self._server.is_running:
            self.console_page._append_output("[系统] 正在停止服务器...", "#ffaa00")
            # v3.02.01: 直接 stop，不经过 save-all + 10s 等待
            self._server.stop_server(graceful=False)
        self._restart_count = 0  # 用户手动停服时重置自动重启计数
        if hasattr(self, "_lag_timer") and self._lag_timer:
            self._lag_timer.stop()

    def _on_server_output(self, text: str):
        """服务器输出同时推送给控制台 + Dashboard 假死检测。"""
        self.console_page._append_output(text)
        self.dashboard_page.on_output()

    def _on_server_stopped(self, retcode: int):
        send_webhook("crash", "服务器停止", "BDS 服务器进程已退出")
        self.dashboard_page._on_server_stopped()
        self.console_page._on_server_stopped()

        # v3.02.01 fix: 只有异常退出 (retcode != 0) 且非用户手动停止才自动重启
        # retcode=0 表示 BDS 正常退出 (Quit correctly)，不应触发重启
        if retcode == 0:
            self.console_page._append_output("[系统] 服务器已正常退出", "#888")
            self._restart_count = 0
            if hasattr(self, "_lag_timer") and self._lag_timer:
                self._lag_timer.stop()
            return

        notify("warning", "server", "服务器已停止", f"退出码 {retcode}", "page:console")
        max_retries = config_mgr.get("max_restart_retries", 5)
        if max_retries > 0 and self._restart_count < max_retries:
            self._restart_count += 1
            msg = f"服务器崩溃，5秒后自动重启（第 {self._restart_count}/{max_retries} 次）"
            self.console_page._append_output(f"[系统] {msg}", "#ffaa00")
            self.console_page.mark_crash(self._restart_count, max_retries)
            from shared.toast import toast_warning
            toast_warning("自动重启", f"第 {self._restart_count} 次尝试", self)
            QTimer.singleShot(5000, self.start_server)
        else:
            if self._restart_count >= max_retries and max_retries > 0:
                log_text = self.console_page._log.toPlainText()
                if log_text:
                    try:
                        crash_path = os.path.join(LOG_DIR, f"crash_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
                        with open(crash_path, "w", encoding="utf-8") as f:
                            f.write(log_text[-8000:])
                        self.console_page._append_output(f"[系统] 崩溃日志已保存: {crash_path}", "#888")
                    except Exception:
                        pass
            self._restart_count = 0
            if hasattr(self, "_lag_timer") and self._lag_timer:
                self._lag_timer.stop()

    def _on_status_changed(self, running: bool):
        self.dashboard_page._on_status_changed(running)
        self.console_page._on_status_changed(running)

    # ── RTT 延迟探测 ──
    _lag_ping_sent = 0.0
    _lag_ping_pending = False

    def _lag_ping(self):
        if not self._server or not self._server.is_running:
            return
        import time
        self._lag_ping_sent = time.time()
        self._lag_ping_pending = True
        self._server.send_command("list")

    def check_lag_response(self, text: str):
        import time, re
        if self._lag_ping_pending and re.search(r"players online", text, re.I):
            rtt = (time.time() - self._lag_ping_sent) * 1000.0
            if 0 < rtt < 60000:
                self._lag_samples.append(rtt)
                if len(self._lag_samples) > 10:
                    self._lag_samples.pop(0)
            self._lag_ping_pending = False
            if self._lag_samples:
                s = sorted(self._lag_samples)
                med = s[len(s) // 2]
                color = "#4CAF50" if med < 80 else ("#ffaa00" if med < 200 else "#ff5555")
                self.dashboard_page.status_card.update_rtt(med, color)

    # ---------- 资源监控 ----------
    def _on_stats_updated(self, snap: SystemStatsSnapshot):
        self.dashboard_page.status_card.update_server_stats(snap)
        if not hasattr(self, "_last_mem_warn"):
            self._last_mem_warn = 0.0
        import time as _t
        threshold = config_mgr.get("mem_warn_threshold", 80) or 80
        if snap.mem_percent >= threshold and _t.time() - self._last_mem_warn > 30:
            self._last_mem_warn = _t.time()
            msg = f"内存使用率 {snap.mem_percent:.1f}%（阈值: {threshold}%）"
            send_webhook("memory", "内存告警", msg)
            from shared.toast import toast_warning
            toast_warning("内存告警", msg, self, duration=8000)

    # ── 工具自更新 ──
    def _check_self_update(self):
        # 防御：自更新检查一次会话只跑一次（避免重复网络请求和 toast）
        if getattr(self, "_update_checked", False):
            return
        self._update_checked = True
        self._update_checker = CheckUpdateWorker(self)
        self._update_checker.result.connect(self._on_self_update_found)
        self._update_checker.start()

    def _on_self_update_found(self, status, remote_ver, dl_url, sha256, msg=""):
        from shared.toast import toast_success, toast_error, toast_warning, toast_info
        if status == "error":
            toast_error("版本检查失败", remote_ver or "网络错误", self, duration=5000)
            notify("warning", "update", "版本检查失败", remote_ver or "网络错误")
            return
        if status == "latest":
            toast_success("已是最新版本", f"v{__version__}（远程: v{remote_ver}）", self)
            return
        if status == "too_old":
            # 跨主版本升级（如 v1.x / 早期 v2.x → v3.x）：不直接拒绝，
            # 而是弹引导框让用户选择「打开下载页」或「继续自动升级」。
            self._prompt_cross_version_upgrade(remote_ver, dl_url, sha256, msg)
            return
        if not dl_url:
            toast_warning("更新源缺失", "version.json 未提供下载链接", self, duration=6000)
            return
        toast_info("发现新版本", f"v{__version__} → v{remote_ver}，正在后台下载...", self)
        notify("info", "update", "发现新版本", f"v{__version__} → v{remote_ver}", "page:upgrade")
        self._dl_updater = DownloadUpdateWorker(dl_url, remote_ver, self)
        self._dl_updater.finished.connect(lambda s, m, p: self._on_update_downloaded(s, m, p, sha256))
        self._dl_updater.start()

    def _prompt_cross_version_upgrade(self, remote_ver, dl_url, sha256, msg):
        """跨主版本升级引导：弹 MessageBox 让用户选择「打开下载页」或「继续自动升级」。"""
        from PySide6.QtWidgets import QMessageBox
        from shared.toast import toast_info
        from backend.self_update import GITHUB_REPO_OWNER, GITHUB_REPO_NAME
        import webbrowser

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("发现新版本（建议手动下载）")
        body = (
            f"检测到新版本 v{remote_ver}（当前 v{__version__}）。\n\n"
            f"您的版本与新版差异较大，{msg or '自动升级可能需要手动调整'}。\n\n"
            f"建议手动下载完整包升级（更稳妥）：\n"
            f"1. 点击「打开下载页」前往 GitHub Releases\n"
            f"2. 下载 bds_manager_v{remote_ver}.zip\n"
            f"3. 解压覆盖到当前目录（自动迁移旧版特征文件）\n"
            f"4. 重启程序\n\n"
            f"如果您想继续体验一键自动升级，也可选择「继续自动升级」。"
        )
        box.setText(body)
        box.setTextFormat(0)  # PlainText 让换行符生效
        btn_manual = box.addButton("打开下载页（推荐）", QMessageBox.AcceptRole)
        btn_auto = box.addButton("继续自动升级", QMessageBox.ActionRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(btn_manual)
        box.exec()
        clicked = box.clickedButton()
        if clicked is btn_manual:
            url = f"https://github.com/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/releases/tag/v{remote_ver}"
            webbrowser.open(url)
            toast_info("已打开下载页", f"请手动下载 v{remote_ver} 并解压到工具目录", self, duration=5000)
            return
        if clicked is btn_auto:
            if not dl_url:
                toast_warning("无法自动升级", "version.json 未提供下载链接", self, duration=5000)
                return
            toast_info("开始下载升级包", f"v{__version__} → v{remote_ver}", self)
            self._dl_updater = DownloadUpdateWorker(dl_url, remote_ver, self)
            self._dl_updater.finished.connect(lambda s, m, p: self._on_update_downloaded(s, m, p, sha256))
            self._dl_updater.start()
            return
        # 取消：什么都不做

    def _on_update_downloaded(self, success, msg, path, sha256):
        from shared.toast import toast_success, toast_error
        if not success:
            toast_error("下载失败", msg, self, duration=5000)
            notify("error", "update", "更新下载失败", msg, "page:upgrade")
            return
        if not is_valid_zip(path):
            toast_error("下载无效", "Release 资产未上传？请用 release_gui.py 发布", self)
            notify("error", "update", "下载文件无效", "Release 资产缺失或上传失败", "page:upgrade")
            try:
                os.remove(path)
            except OSError:
                pass
            return
        ok, sha_msg = verify_sha256(path, sha256)
        if not ok:
            toast_error("SHA256 校验失败", sha_msg, self)
            notify("error", "update", "SHA256 校验失败", sha_msg, "page:upgrade")
            try:
                os.remove(path)
            except OSError:
                pass
            return
        toast_success("更新包就绪", "正在安装...", self)
        self._installer = InstallUpdateWorker(path, self)
        self._installer.finished.connect(self._on_update_installed)
        self._installer.start()

    def _on_update_installed(self, success, msg):
        from PySide6.QtWidgets import QMessageBox
        from shared.toast import toast_error
        if success:
            notify("success", "update", "工具已更新", f"即将自动重启到新版本", "page:upgrade")
            QMessageBox.information(self, "更新完成",
                "BDS Manager 已更新！\n旧文件已备份到 backups/upgrade_backup_*/\n程序即将自动重启。")
            restart_app("main.py")
        else:
            toast_error("安装失败", msg, self, duration=6000)
            notify("error", "update", "安装失败", msg, "page:upgrade")


# ---------- 启动闪屏（可动画进度条）----------
class AnimatedSplashScreen(QSplashScreen):
    """带动画进度条的启动闪屏：进度条平滑推进，100% 时主窗口登场。"""

    def __init__(self, version: str):
        from PySide6.QtGui import QPixmap, QColor
        pix = QPixmap(420, 240)
        pix.fill(QColor("#1e1e1e"))
        super().__init__(pix, Qt.WindowStaysOnTopHint)
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self._progress = 0
        self._status = "正在启动..."
        self._version = version

    def set_progress(self, percent: int, status: str = ""):
        """0-100，更新进度条；status 非空时同步更新状态文本。"""
        self._progress = max(0, min(100, percent))
        if status:
            self._status = status
        self.repaint()

    def set_status(self, status: str):
        """仅更新状态文本。"""
        self._status = status
        self.repaint()

    def drawContents(self, painter):
        from PySide6.QtGui import QColor, QFont
        rect = self.rect()
        # 标题
        painter.setPen(QColor("#0DC5D4"))
        f = QFont("Microsoft YaHei", 18)
        f.setBold(True)
        painter.setFont(f)
        painter.drawText(rect.adjusted(0, 55, 0, 0), Qt.AlignHCenter, "BDS Manager")
        # 副标题
        painter.setPen(QColor("#aaa"))
        f2 = QFont("Microsoft YaHei", 10)
        painter.setFont(f2)
        painter.drawText(rect.adjusted(0, 90, 0, 0), Qt.AlignHCenter,
                         f"v{self._version} — 正在加载…")
        # 进度条（背景轨道 + 前景填充）
        bar_x, bar_y, bar_w, bar_h = 60, 165, 300, 6
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#2a2a2a"))
        painter.drawRoundedRect(bar_x, bar_y, bar_w, bar_h, 3, 3)
        if self._progress > 0:
            fg_w = int(bar_w * self._progress / 100)
            painter.setBrush(QColor("#0DC5D4"))
            painter.drawRoundedRect(bar_x, bar_y, fg_w, bar_h, 3, 3)
        # 状态文本
        painter.setPen(QColor("#ccc"))
        f3 = QFont("Microsoft YaHei", 9)
        painter.setFont(f3)
        painter.drawText(rect.adjusted(0, 190, 0, 0), Qt.AlignHCenter, self._status)
        # 百分比
        painter.setPen(QColor("#666"))
        f4 = QFont("Microsoft YaHei", 8)
        painter.setFont(f4)
        painter.drawText(rect.adjusted(0, 212, 0, 0), Qt.AlignHCenter,
                         f"{self._progress}%")


def _animate_progress(splash: AnimatedSplashScreen, app: QApplication,
                      target: int, duration_ms: int = 250):
    """从当前进度平滑过渡到 target（ease-out 曲线）。

    v3.02.01 优化：sleep 从 16ms 减到 5ms，动画更快。
    """
    start = splash._progress
    steps = max(1, duration_ms // 16)  # ~60fps
    for i in range(1, steps + 1):
        ratio = i / steps
        eased = 1 - (1 - ratio) ** 3  # ease-out cubic
        pct = int(start + (target - start) * eased)
        splash.set_progress(pct)
        app.processEvents()
        time.sleep(0.008)  # v3.02.01: 从 0.016 → 0.008，动画仍平滑但快一倍


# ---------- 入口 ----------
def main():
    # 1. QApplication（必须先于任何 QWidget）
    app = QApplication(sys.argv)
    app.setApplicationName("BDS Manager")
    app.setApplicationVersion(__version__)

    # 2. 闪屏（立即显示，进度条 0%）
    splash = AnimatedSplashScreen(__version__)
    splash.show()
    app.processEvents()

    # 3. 全局错误处理
    set_error_handler(_toast_error_handler)
    install_excepthook()
    _animate_progress(splash, app, 10, 60)

    # 4. 加载配置
    config_mgr.load()
    init_context(config_mgr.get("server_dir"))
    splash.set_status("配置已加载")
    _animate_progress(splash, app, 25, 60)

    # 5. 字体
    font_size = config_mgr.get("font_size", 12)
    f = app.font()
    f.setPointSize(font_size)
    app.setFont(f)
    splash.set_status("字体已设置")
    _animate_progress(splash, app, 35, 50)

    # v3.02.01: 构造页面之前先设主题，否则 isDarkTheme() 在页面 __init__ 中返回 False，
    # 导致 QPlainTextEdit/QTableWidget 等控件的硬编码样式走浅色分支。
    theme_raw = config_mgr.get("theme", "dark")
    theme_map = {"dark": Theme.DARK, "light": Theme.LIGHT, "auto": Theme.AUTO}
    setTheme(theme_map.get(theme_raw, Theme.DARK))

    # 6. 主窗口（最耗时的一步，1.5+ 秒）
    splash.set_status("正在构造主窗口...")
    _animate_progress(splash, app, 45, 50)
    window = BDSFluentWindow()
    _animate_progress(splash, app, 80, 100)

    # 7. 主题
    splash.set_status("正在应用主题...")
    window.apply_theme(
        config_mgr.get("theme", "dark"),
        config_mgr.get("theme_color", "#0DC5D4"),
    )
    _animate_progress(splash, app, 95, 60)

    # 8. 进度条到达 100% 时主窗口登场
    splash.set_status("准备就绪")
    _animate_progress(splash, app, 100, 60)
    window.show()
    splash.finish(window)
    app.processEvents()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
