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
import ssl as _ssl

# v3.04.03 安全修复: 移除全局 SSL 验证绕过。
# 之前 _ssl._create_default_https_context = _ssl._create_unverified_context
# 会禁用整个应用的 HTTPS 证书验证（自更新下载/Webhook/版本检查全部裸奔）。
# 如果 GitHub API 遇到 SSL 错误，应修复系统 CA 证书而非绕过验证。

import time
import logging
from datetime import datetime

# ---------- 屏蔽 QFluentWidgets 的 ANSI 彩色 Tips ----------
# v3.04.03 健壮性修复: try/finally 保护，确保 import 失败时 stdout 也能恢复
_real_stdout = sys.stdout
sys.stdout = open(os.devnull, "w", encoding="utf-8")
try:
    import qfluentwidgets  # noqa: E402
finally:
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
from backend.self_update_ui import show_cross_version_dialog, show_update_prompt  # v3.04.01
from backend.notifications import notify  # v3.02.00 通知中心
from backend.notifications import get_bus as _notify_bus, get_unread_count as _notify_unread
from components.notification_panel import BellButton, NotificationDrawer
from components.splash import AnimatedSplashScreen, animate_progress
from backend import server_lifecycle as _slc
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

from shared.version import VERSION as __version__, VERSION_INFO as __version_info__, RELEASE_DATE as __release_date__
from shared.utils import bds_exe, ll_exe, is_linux



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
        # v3.02.02: 窗口圆角
        self._rounded_mask_active = False
        self._apply_rounded_corners()
        # v3.02.02: 窗口背景效果（毛玻璃 / 半透明）
        self._apply_window_background()

    def _apply_window_background(self):
        """根据 window_background_opacity 设置透明度（100=不透明）。"""
        opacity = config_mgr.get("window_background_opacity", 100)
        if opacity < 100:
            self.setWindowOpacity(opacity / 100.0)

    def _apply_rounded_corners(self):
        """窗口四个角圆角：优先 Win11 DWM API，降级到 QRegion mask。"""
        if sys.platform != "win32":
            return
        # 1) 尝试 Win 11 DWM 原生圆角（Build 22000+）
        try:
            import ctypes
            hwnd = int(self.winId())
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 33,  # DWMWA_WINDOW_CORNER_PREFERENCE
                ctypes.byref(ctypes.c_int(3)), ctypes.sizeof(ctypes.c_int),
            )
            if result == 0:  # S_OK
                return
        except OSError:
            pass  # DWM 不可用，降级 QRegion
        # 2) 降级：QRegion mask 模拟圆角（Win 10 / Win 8）
        self._rounded_mask_active = True
        self._update_rounded_mask()

    def _update_rounded_mask(self):
        """用 QBitmap 反锯齿圆角 mask（比 QRegion 多边形近似平滑得多）。"""
        from PySide6.QtGui import QBitmap, QPainter
        r = self.rect()
        if r.width() <= 0 or r.height() <= 0:
            return
        bitmap = QBitmap(r.size())
        bitmap.fill(Qt.color0)
        p = QPainter(bitmap)
        p.setBrush(Qt.color1)
        p.setPen(Qt.NoPen)
        p.setRenderHint(QPainter.Antialiasing)
        p.drawRoundedRect(r, 12, 12)
        p.end()
        self.setMask(bitmap)

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
            config_mgr.save()
        except (UnicodeDecodeError, AttributeError, OSError):
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
            except (RuntimeError, AttributeError, ValueError):
                pass
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
        quit_action.triggered.connect(lambda: (setattr(self, "_skip_close_confirm", True), QApplication.quit()))
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
        self.addSubInterface(self.dashboard_page, FluentIcon.HOME, "仪表盘 (Ctrl+1)")

        self.console_page = ConsolePage(self)
        self.console_page.setObjectName("console")
        self.addSubInterface(self.console_page, FluentIcon.COMMAND_PROMPT, "控制台 (Ctrl+2)")

        self.world_page = WorldPage(self)
        self.world_page.setObjectName("world")
        # 监听备份完成 → 更新 Dashboard 最近备份时间
        self.world_page.backup_completed.connect(self._on_backup_completed)
        self.addSubInterface(self.world_page, FluentIcon.SAVE, "世界 (Ctrl+3)")

        self.packs_page = PacksPage(self)
        self.packs_page.setObjectName("packs")
        self.addSubInterface(self.packs_page, FluentIcon.FOLDER, "资源包 (Ctrl+4)")

        self.config_page = ConfigPage(self)
        self.config_page.setObjectName("config")
        self.addSubInterface(self.config_page, FluentIcon.EDIT, "配置 (Ctrl+5)")

        self.upgrade_page = UpgradePage(self)
        self.upgrade_page.setObjectName("upgrade")
        self.addSubInterface(self.upgrade_page, FluentIcon.SYNC, "升级 (Ctrl+6)")

        if not is_linux():
            self.tunnel_page = TunnelPage(self)
            self.tunnel_page.setObjectName("tunnel")
            self.addSubInterface(self.tunnel_page, FluentIcon.LINK, "隧道 (Ctrl+7)")

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
        # v3.02.02: 通知入队时同步弹出视觉 toast（GUI 线程安全）
        _notify_bus().notification_added.connect(self._on_notif_to_toast)
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

    def _on_notif_to_toast(self, n):
        """v3.02.02: 通知入队 → 同时弹出视觉 toast。"""
        if n is None:
            return
        # toast 来源的通知已经弹过视觉 toast，不重复弹
        if getattr(n, "category", "") == "toast":
            return
        from shared.toast import toast_info, toast_success, toast_warning, toast_error
        fn_map = {"error": toast_error, "warning": toast_warning,
                  "success": toast_success, "info": toast_info}
        fn = fn_map.get(n.level, toast_info)
        fn(n.title, n.body, self)

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
        tip.destroyed.connect(lambda: (config_mgr.set("show_command_palette_tip", False), config_mgr.save()))

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

        # 首次启动引导
        if not config_mgr.get("first_launch_done", True):
            QTimer.singleShot(2000, self._show_onboarding)

        # 监听系统主题变化
        if config_mgr.get("follow_system_theme", False):
            try:
                app = QApplication.instance()
                if app and hasattr(app, "styleHints"):
                    app.styleHints().colorSchemeChanged.connect(self._on_system_theme_changed)
            except (RuntimeError, AttributeError, ValueError):
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
            config_mgr.save()
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

    def _show_onboarding(self):
        """首次启动引导：检查服务器状态，指引用户安装。"""
        from qfluentwidgets import MessageBox
        ctx = get_context()
        has_bds = os.path.isfile(os.path.join(ctx.bds_dir, bds_exe()))
        has_ll = bool(config_mgr.get("ll_server_dir", "")) and                  os.path.isfile(os.path.join(ctx.ll_dir, ll_exe()))

        target_page = "console"
        if not has_bds and not has_ll:
            steps = [
                "1. 切换到「升级」页面",
                "2. 点「浏览可用版本」查看 BDS 列表",
                "3. 选择一个版本点「下载」",
                "4. 下载完成后选择安装目录并点「开始安装」",
                "5. 回到「控制台」点「启动服务器」",
            ]
            target_page = "upgrade"
        elif has_bds and not has_ll:
            steps = [
                "BDS 已安装，可正常使用。",
                "如需 LeviLamina：切换到「升级」页 → lip 卡片一键部署。",
                "回到「控制台」即可启动服务器。",
            ]
        else:
            steps = ["服务器已就绪，直接去「控制台」启动吧！"]

        w = MessageBox(
            "欢迎使用 BDS Manager",
            "这是你第一次运行。\n\n" + "\n".join(steps) + "\n\n完成后点「开始使用」",
            self,
        )
        w.yesButton.setText("开始使用")
        w.cancelButton.hide()
        _tp = target_page
        w.yesSignal.connect(lambda: (
            config_mgr.set("first_launch_done", True),
            config_mgr.save(),
            self._navigate_to(_tp),
            w.close(),
        ))
        w.show()

    def _navigate_to(self, page_name: str):
        """切换到指定页面。"""
        _map = {
            "dashboard": self.dashboard_page,
            "console": self.console_page,
            "upgrade": self.upgrade_page,
            "settings": self.settings_page,
        }
        target = _map.get(page_name)
        if target:
            self.stackedWidget.setCurrentWidget(target)

    def _startup_toasts(self):
        # 防御：防止重复触发（_startup_toasts 一次会话只跑一次）
        if getattr(self, "_toasted", False):
            return
        self._toasted = True
        import psutil
        from shared.toast import toast_success, toast_error, toast_warning, toast_info

        ctx = get_context()
        stype = config_mgr.get("server_type", "bds")
        server_dir = ctx.server_dir  # ServerContext.server_dir 已根据 server_type 动态返回

        if os.path.isdir(server_dir):
            label = "LL 服务器" if stype == "ll" else "BDS 服务器"
            toast_success(f"{label}: {os.path.basename(server_dir)}", "目录就绪", self)
        else:
            toast_error("服务器目录不存在", server_dir, self, duration=8000)

        if stype == "ll":
            exe_name = "bedrock_server_mod.exe"
        else:
            exe_name = config_mgr.get("server_exe", "bedrock_server.exe")
        exe_path = os.path.join(server_dir, exe_name)
        if os.path.exists(exe_path):
            toast_info(f"服务端: {exe_name}", "可执行文件就绪", self)
        else:
            hint = "请先用 lip 部署或手动安装" if stype == "ll" else "请先安装 BDS"
            toast_warning(f"服务端: {exe_name}", f"未找到，{hint}", self, duration=6000)

        try:
            cpu = psutil.cpu_percent()
            mem = psutil.virtual_memory().percent
            toast_info("系统资源", f"CPU {cpu:.0f}%  内存 {mem:.0f}%", self)
        except (AttributeError, OSError):
            pass  # 监控未就绪或 psutil 不可用

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

    def resizeEvent(self, event):
        """v3.02.01：实时保存窗口几何（含 maximized 状态）。v3.03.00: 300ms debounce。"""
        super().resizeEvent(event)
        if getattr(self, "_rounded_mask_active", False):
            self._update_rounded_mask()
        # v3.03.00: debounce 300ms，避免拖拽窗口时高频写 config_mgr
        if hasattr(self, '_resize_timer'):
            self._resize_timer.start(300)
        else:
            from PySide6.QtCore import QTimer
            self._resize_timer = QTimer(self)
            self._resize_timer.setSingleShot(True)
            self._resize_timer.timeout.connect(self._save_geometry)
            self._resize_timer.start(300)

    def closeEvent(self, event):
        # 服务器在运行 → 先安全关闭
        if self._server is not None and self._server.is_running:
            self._do_safe_shutdown()
            event.ignore()
            return
        # close_to_tray → 隐藏到托盘
        if self._tray and self._tray.isVisible() and config_mgr.get("close_to_tray", True):
            event.ignore()
            self._save_geometry()
            config_mgr.save()
            self.hide()
            return
        # 快捷键/程序化退出跳过确认
        if getattr(self, "_skip_close_confirm", False):
            self._skip_close_confirm = False
        else:
            # X 按钮 → 确认后退出
            from qfluentwidgets import MessageBox
            mb = MessageBox("确认退出", "确定要退出 BDS Manager 吗？", self)
            mb.yesButton.setText("退出")
            mb.cancelButton.setText("取消")
            if not mb.exec():
                event.ignore()
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
        if self._tray is not None:
            self._tray.hide()
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
        except (RuntimeError, AttributeError):
            pass  # stackedWidget 未就绪

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
            "safe_shutdown":     self._shortcut_safe_shutdown,
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
            toast_success("已发送", "save hold + save resume（基岩版存档）", self)

    def _shortcut_stop_server(self):
        if self.is_server_running():
            self.stop_server()

    def _shortcut_open_settings(self):
        if hasattr(self, "settings_page"):
            self.switchTo(self.settings_page)

    def _shortcut_toggle_theme(self):
        cur = config_mgr.get("theme", "light")
        new = "light" if cur == "dark" else "dark"
        config_mgr.set("theme", new)
        config_mgr.save()
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
            except (RuntimeError, AttributeError, ValueError):
                pass

    def _shortcut_safe_shutdown(self):
        """v3.02.02: Ctrl+Shift+D 安全关闭。"""
        if not hasattr(self, "_server") or not hasattr(self, "console_page"):
            return
        if getattr(self, "_shutting_down", False):
            return
        self._shutting_down = True
        try:
            self._do_safe_shutdown()
        finally:
            self._shutting_down = False

    def _do_safe_shutdown(self):
        """停止所有服务后退出（QApplication.quit() 不走 closeEvent 确认）。"""
        self._skip_close_confirm = True
        from backend.notifications import notify
        stopped_any = False

        # 1. 停服务器
        if self._server is not None and self._server.is_running:
            self.stop_server()
            stopped_any = True
            self.console_page._append_output("[系统] Ctrl+Shift+D 安全关闭：正在停止服务器...", "#E65100")

        # 2. 停隧道
        if hasattr(self, "tunnel_page") and self.tunnel_page:
            try:
                self.tunnel_page.cleanup()
                stopped_any = True
                self.console_page._append_output("[系统] 安全关闭：隧道已停止", "#E65100")
            except Exception:
                pass

        # 3. 停监控
        if self._monitor:
            self._monitor.stop()
            stopped_any = True

        # 4. 退出
        if stopped_any:
            notify("warning", "system", "安全关闭", "服务器 / 隧道 / 监控已全部停止，1 秒后退出")
            from shared.toast import toast_warning
            toast_warning("安全关闭", "正在安全退出...", self, duration=3000)
            QTimer.singleShot(1000, QApplication.quit)
        else:
            notify("info", "system", "安全关闭", "当前没有运行中的进程，退出")
            from shared.toast import toast_info
            toast_info("安全关闭", "正在退出...", self, duration=2000)
            QTimer.singleShot(500, QApplication.quit)

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
        config_mgr.save()
        self._skip_close_confirm = True
        toast_info("工具即将重启", "将在 1 秒后自动重启", self)
        QTimer.singleShot(1000, lambda: restart_app("main.py"))

    # ---------- 主题 ----------
    def apply_theme(self, theme: str = "light", accent_color: str = "#0DC5D4"):
        self._current_color = accent_color
        theme_map = {"dark": Theme.DARK, "light": Theme.LIGHT, "auto": Theme.AUTO}
        setTheme(theme_map.get(theme, Theme.DARK))
        try:
            setThemeColor(QColor(accent_color))
        except (AttributeError, ValueError):
            setThemeColor(QColor("#0DC5D4"))

        # ── Windows 11 原生暗色标题栏 ──
        # QFluentWidgets setTheme 只管控件样式，不管 Windows 标题栏。
        # Win10 1809+ / Win11 需要通过 DWMWA_USE_IMMERSIVE_DARK_MODE (20)
        # 显式切换标题栏深/浅色，否则暗色模式下标题栏仍是白色。
        if sys.platform == "win32":
            try:
                import ctypes
                hwnd = int(self.winId())
                dark = 1 if theme_map.get(theme, Theme.DARK) == Theme.DARK else 0
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, 20,  # DWMWA_USE_IMMERSIVE_DARK_MODE
                    ctypes.byref(ctypes.c_int(dark)), ctypes.sizeof(ctypes.c_int),
                )
            except (OSError, AttributeError):
                pass

        # 通知铃铛图标跟随主题切换（FluentIcon.MESSAGE 有深/浅两套 SVG）
        if hasattr(self, "_bell") and self._bell is not None:
            self._bell.setIcon(FluentIcon.MESSAGE.icon(theme=theme_map.get(theme, Theme.DARK)))

        # v3.02.01 fix：主题切换后通知抽屉刷新（背景色 + chip 样式）
        # 抽屉在 _build_ui 时一次性读取 isDarkTheme()，主题切换后不会自动更新。
        # 这里手动调用 refresh()，使其按当前主题重建 chip 和 list 样式。
        try:
            if hasattr(self, "_notif_drawer") and self._notif_drawer is not None:
                self._notif_drawer.refresh_theme()
        except (AttributeError, RuntimeError):
            pass

        # v3.02.01：同步刷新各页面里主题感知的硬编码颜色（status_badge/bds_card/tasks_card 等）
        for page_attr in ("dashboard_page", "packs_page", "settings_page",
                          "console_page", "world_page", "config_page",
                          "upgrade_page", "tunnel_page", "about_page"):
            page = getattr(self, page_attr, None)
            if page is not None and hasattr(page, "refresh_theme"):
                try:
                    page.refresh_theme()
                except (AttributeError, RuntimeError):
                    pass

        # v3.04.01: 滚动条样式统一到 shared/theme.scrollbar_style()
        from shared.theme import scrollbar_style as _scrollbar_style
        self.setStyleSheet(_scrollbar_style())
        logger.info("主题: %s, 主色: %s", theme, accent_color)

    # ---------- 服务器管理 ----------
    @property
    def server(self) -> ServerProcess | None:
        return self._server

    @property
    def is_server_running(self) -> bool:
        return self._server is not None and self._server.is_running

    def start_server(self):
        return _slc.start_server(self)

    def stop_server(self):
        _slc.stop_server(self)

    def _on_server_output(self, text: str):
        _slc._on_server_output(self, text)

    def _on_server_stopped(self, retcode: int):
        _slc._on_server_stopped(self, retcode)

    def _on_status_changed(self, running: bool):
        _slc._on_status_changed(self, running)

    # ── RTT 延迟探测 → backend/server_lifecycle ──
    _lag_ping_sent = 0.0
    _lag_ping_pending = False

    def _lag_ping(self):
        _slc._lag_ping(self)

    def check_lag_response(self, text: str):
        _slc.check_lag_response(self, text)

    # ── 资源监控 → backend/server_lifecycle ──
    def _on_stats_updated(self, snap: SystemStatsSnapshot):
        _slc.on_stats_updated(self, snap)

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
        # v3.04.01: 委托到 backend/self_update_ui.py
        # 必须保存返回值到 self._update_mb，否则 MessageBox.show() 非阻塞返回后
        # Python 端引用被 GC，导致 yesSignal 回调对象析构 → RuntimeWarning
        self._update_mb = show_update_prompt(
            parent=self,
            remote_ver=remote_ver,
            dl_url=dl_url,
            sha256=sha256,
            on_download=lambda u, v, s: self._start_self_update_download(u, v, s),
        )

    def _start_self_update_download(self, dl_url, remote_ver, sha256=""):
        """确认后开始下载自更新包。"""
        toast_info("正在下载", f"v{remote_ver} 下载中...", self)
        self._dl_updater = DownloadUpdateWorker(dl_url, remote_ver, self)
        self._dl_updater.finished.connect(lambda s, m, p: self._on_update_downloaded(s, m, p, sha256))
        self._dl_updater.start()

    def _prompt_cross_version_upgrade(self, remote_ver, dl_url, sha256, msg):
        """跨主版本升级引导（v3.04.01: 委托到 backend/self_update_ui.py）。"""
        show_cross_version_dialog(
            parent=self,
            remote_ver=remote_ver,
            dl_url=dl_url,
            sha256=sha256,
            msg=msg,
            on_auto_upgrade=lambda u, v, s: self._start_self_update_download(u, v, s),
        )

    def _show_update_complete(self):
        """更新完成提示。"""
        toast_success("更新完成", "程序已更新，重启后自动生效", self, duration=6000)

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
        from shared.toast import toast_error, toast_success
        if success:
            toast_success("更新完成", "BDS Manager 已更新，旧文件已备份，即将自动重启", self, duration=6000)
            QTimer.singleShot(1500, lambda: restart_app("main.py"))
        else:
            toast_error("安装失败", msg, self, duration=6000)
            notify("error", "update", "安装失败", msg, "page:upgrade")


# ---------- 入口 ----------
def main():
    # 0. 先加载配置（高 DPI 必须在 QApplication 之前决策）
    config_mgr.load()
    init_context(config_mgr.get("server_dir"))

    # 0a. 高 DPI 适配（必须在 QApplication 创建之前）
    #     Qt6 默认启用 AA_EnableHighDpiScaling，用户可选更精确的缩放策略：
    #     PassThrough → 允许非整数倍缩放（125%/150%/175%），文字不模糊
    if config_mgr.get("high_dpi", False):
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )

    # 1. QApplication（必须先于任何 QWidget）
    app = QApplication(sys.argv)
    app.setApplicationName("BDS Manager")
    app.setApplicationVersion(__version__)

    # 2. 闪屏（根据配置主题选择深/浅色）
    theme_raw = config_mgr.get("theme", "light")
    splash = AnimatedSplashScreen(__version__, is_dark=(theme_raw == "dark"))
    splash.show()
    app.processEvents()

    # 4. 全局错误处理
    set_error_handler(_toast_error_handler)
    install_excepthook()
    animate_progress(splash, app, 10, 60)
    splash.set_status("配置已加载")
    animate_progress(splash, app, 25, 60)

    # 5. 字体
    font_size = config_mgr.get("font_size", 12)
    f = app.font()
    f.setPointSize(font_size)
    app.setFont(f)
    splash.set_status("字体已设置")
    animate_progress(splash, app, 35, 50)

    # v3.02.01: 构造页面之前先设主题，否则 isDarkTheme() 在页面 __init__ 中返回 False，
    # 导致 QPlainTextEdit/QTableWidget 等控件的硬编码样式走浅色分支。
    theme_map = {"dark": Theme.DARK, "light": Theme.LIGHT, "auto": Theme.AUTO}
    setTheme(theme_map.get(theme_raw, Theme.LIGHT))

    # 6. 主窗口（最耗时的一步，1.5+ 秒）
    splash.set_status("正在构造主窗口...")
    animate_progress(splash, app, 45, 50)
    window = BDSFluentWindow()
    animate_progress(splash, app, 80, 100)

    # 7. 主题
    splash.set_status("正在应用主题...")
    window.apply_theme(
        config_mgr.get("theme", "light"),
        config_mgr.get("theme_color", "#0DC5D4"),
    )
    animate_progress(splash, app, 95, 60)

    # 8. 进度条到达 100% 时主窗口登场
    splash.set_status("准备就绪")
    animate_progress(splash, app, 100, 60)
    window.show()
    splash.finish(window)
    app.processEvents()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
