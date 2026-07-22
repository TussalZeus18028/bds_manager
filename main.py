# -*- coding: utf-8 -*-
"""
BDS Manager Fluent -- 主入口

基于 PySide6 + QFluentWidgets 的 Minecraft Bedrock 服务器管理工具。
支持暗色/亮色主题切换、自定义主题色、侧边栏导航。
"""

import sys
import os
import logging
from datetime import datetime

# ---------- 屏蔽 QFluentWidgets 的 ANSI 彩色 Tips ----------
_real_stdout = sys.stdout
sys.stdout = open(os.devnull, "w", encoding="utf-8")
import qfluentwidgets  # noqa: E402
sys.stdout.close()
sys.stdout = _real_stdout
# ----------------------------------------------------------

from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PySide6.QtGui import QColor, QIcon, QAction
from PySide6.QtCore import Qt, QTimer
from qfluentwidgets import (
    FluentWindow, FluentIcon, setTheme, setThemeColor, Theme, SystemTrayMenu,
)

from shared.config import config_mgr, init_context, SCRIPT_DIR, LOG_DIR, get_context
from backend.server import ServerProcess
from backend.monitor import SystemResourceMonitor, SystemStatsSnapshot
from backend.webhook import send_webhook
from backend.self_update import CheckUpdateWorker, DownloadUpdateWorker, InstallUpdateWorker, verify_sha256, is_valid_zip, restart_app
from pages.dashboard import DashboardPage
from pages.console import ConsolePage
from pages.settings import SettingsPage
from pages.world import WorldPage
from pages.config import ConfigPage
from pages.packs import PacksPage
from pages.upgrade import UpgradePage
from pages.tunnel import TunnelPage
from pages.about import AboutPage

# ---------- 日志 ----------
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "bds_manager.log"), encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("bds_manager")

__version__ = "3.0.1"


class BDSFluentWindow(FluentWindow):
    """BDS Manager 主窗口 - Fluent Design。持有共享的服务器进程和资源监控。"""

    def __init__(self):
        super().__init__()
        self._server: ServerProcess | None = None
        self._monitor: SystemResourceMonitor | None = None
        self._tray = None
        self._setup_window()
        self._setup_tray()
        self._init_pages()
        self._init_services()
        self._restore_window_state()

    # ---------- 窗口 ----------
    def _setup_window(self):
        self.setWindowTitle(f"BDS Manager Fluent v{__version__}")
        self.resize(
            config_mgr.get("window_width", 1200),
            config_mgr.get("window_height", 800),
        )
        self.setMinimumSize(960, 620)
        self.navigationInterface.setExpandWidth(280)

    def _setup_tray(self):
        """系统托盘：双击恢复，右键菜单退出。"""
        self._tray = QSystemTrayIcon(self)
        self._tray.setToolTip("BDS Manager")
        # 用 QFluentWidgets 内置图标作为托盘图标
        from qfluentwidgets import FluentIcon as _FI
        self._tray.setIcon(_FI.HOME.icon())
        self._tray.activated.connect(self._on_tray_activated)

        menu = QMenu()
        show_action = menu.addAction("显示窗口")
        show_action.triggered.connect(self._show_from_tray)
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

    def _init_services(self):
        """启动后台服务 + 自检 Toast。"""
        self._monitor = SystemResourceMonitor(self)
        self._monitor.stats_updated.connect(self._on_stats_updated)
        self._monitor.stats_updated.connect(self.dashboard_page.resource_card.update_stats)
        self._monitor.start(config_mgr.get("monitor_interval", 2000))

        # 启动自检 Toast（对齐旧版 _show_startup_toasts）
        if config_mgr.get("show_startup_toasts", True):
            QTimer.singleShot(800, self._startup_toasts)

    def _startup_toasts(self):
        import psutil
        from shared.toast import toast_success, toast_error, toast_warning, toast_info

        ctx = get_context()
        server_dir = ctx.server_dir

        # 服务器目录
        if os.path.isdir(server_dir):
            toast_success(f"服务器: {os.path.basename(server_dir)}", "目录就绪", self)
        else:
            toast_error("服务器目录不存在", server_dir, self, duration=8000)

        # 服务端可执行文件
        exe_name = config_mgr.get("server_exe", "bedrock_server.exe")
        exe_path = os.path.join(server_dir, exe_name)
        if os.path.exists(exe_path):
            toast_info(f"服务端: {exe_name}", "可执行文件就绪", self)
        else:
            toast_warning(f"服务端: {exe_name}", "未找到，请先安装 BDS", self, duration=6000)

        # 系统资源
        try:
            cpu = psutil.cpu_percent()
            mem = psutil.virtual_memory().percent
            toast_info("系统资源", f"CPU {cpu:.0f}%  内存 {mem:.0f}%", self)
        except Exception:
            pass

        # 备份状态
        if os.path.exists(ctx.backup_dir):
            backups = [f for f in os.listdir(ctx.backup_dir) if f.endswith(".zip")]
            if backups:
                latest = max(backups, key=lambda f: os.path.getmtime(os.path.join(ctx.backup_dir, f)))
                toast_info("备份状态", f"最近: {latest[:50]}（共 {len(backups)} 个）", self)
            else:
                toast_info("备份状态", "暂无备份", self)
        else:
            toast_info("备份状态", "备份目录尚未创建", self)

        # 版本就绪
        toast_info(f"BDS Manager v{__version__}", "就绪，等待操作", self)

        # 后台自动扫描 BDS 版本（5 秒延迟，不阻塞启动）
        QTimer.singleShot(5000, self.upgrade_page._fetch)

        # 工具自更新检查（5 秒延迟）
        if config_mgr.get("auto_check_update", True):
            QTimer.singleShot(5000, self._check_self_update)

    def _restore_window_state(self):
        w = config_mgr.get("window_width", 1200)
        h = config_mgr.get("window_height", 800)
        self.resize(w, h)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        config_mgr.set("window_width", self.width())
        config_mgr.set("window_height", self.height())

    def closeEvent(self, event):
        """关闭行为：按用户设置选择最小化到托盘或直接退出。"""
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
        config_mgr.save()
        super().closeEvent(event)

    def keyPressEvent(self, event):
        """快捷键。"""
        # Ctrl+Shift+R: 重启工具
        if event.modifiers() == (Qt.ControlModifier | Qt.ShiftModifier) and event.key() == Qt.Key_R:
            from backend.self_update import restart_app
            from shared.toast import toast_info
            toast_info("工具即将重启", "将在 1 秒后自动重启", self)
            QTimer.singleShot(1000, lambda: restart_app("main.py"))
            return
        super().keyPressEvent(event)

    # ---------- 主题 ----------
    def apply_theme(self, theme: str = "dark", accent_color: str = "#0DC5D4"):
        theme_map = {"dark": Theme.DARK, "light": Theme.LIGHT, "auto": Theme.AUTO}
        setTheme(theme_map.get(theme, Theme.DARK))
        try:
            setThemeColor(QColor(accent_color))
        except Exception:
            setThemeColor(QColor("#0DC5D4"))

        # 现代化细滚动条（全局）
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

    # ---------- 服务器管理（共享）----------
    @property
    def server(self) -> ServerProcess | None:
        return self._server

    @property
    def is_server_running(self) -> bool:
        return self._server is not None and self._server.is_running

    def start_server(self):
        """启动 BDS 服务器进程。"""
        if self._server and self._server.is_running:
            return "服务器已在运行中"

        ctx = get_context()
        exe_path = os.path.join(ctx.server_dir, config_mgr.get("server_exe", "bedrock_server.exe"))
        if not os.path.exists(exe_path):
            return f"未找到服务器可执行文件: {exe_path}"

        self._server = ServerProcess(exe_path, ctx.server_dir)
        self._server.output_received.connect(self.console_page._append_output)
        self._server.process_stopped.connect(self._on_server_stopped)
        self._server.error_occurred.connect(
            lambda msg: self.console_page._append_output(f"[ERROR] {msg}", "#ff5555")
        )
        self._server.status_changed.connect(self._on_status_changed)
        self._server.start()

        self.dashboard_page._on_server_started()
        self.console_page._on_server_started()

        # RTT 延迟探测 + 玩家列表刷新（每 30 秒）
        self._restart_count = 0
        self._lag_samples: list[float] = []
        if not hasattr(self, "_lag_timer") or not self._lag_timer:
            self._lag_timer = QTimer(self)
            self._lag_timer.timeout.connect(self._lag_ping)
        self._lag_timer.start(30000)
        return None  # 成功

    def stop_server(self):
        """停止 BDS 服务器。"""
        if self._server and self._server.is_running:
            self.console_page._append_output("[系统] 正在发送 stop 命令...", "#ffaa00")
            self._server.stop_server()
        if hasattr(self, "_lag_timer"):
            self._lag_timer.stop()

    def _on_server_stopped(self):
        send_webhook("crash", "服务器停止", "BDS 服务器进程已退出")
        self.dashboard_page._on_server_stopped()
        self.console_page._on_server_stopped()

        # 崩溃自愈：自动重启（已在 start_server 重置 _restart_count）
        max_retries = config_mgr.get("max_restart_retries", 5)
        if max_retries > 0 and self._restart_count < max_retries:
            self._restart_count += 1
            msg = f"服务器崩溃，{5}秒后自动重启（第 {self._restart_count}/{max_retries} 次）"
            self.console_page._append_output(f"[系统] {msg}", "#ffaa00")
            from shared.toast import toast_warning
            toast_warning("自动重启", f"第 {self._restart_count} 次尝试", self)
            QTimer.singleShot(5000, self.start_server)
        else:
            # 超出重试上限：保存崩溃日志
            if self._restart_count >= max_retries and max_retries > 0:
                log_text = self.console_page._log.toPlainText()
                if log_text:
                    try:
                        crash_path = os.path.join(LOG_DIR, f"crash_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
                        with open(crash_path, "w", encoding="utf-8") as f:
                            f.write(log_text[-8000:])  # 末尾 8000 字符
                        self.console_page._append_output(f"[系统] 崩溃日志已保存: {crash_path}", "#888")
                    except Exception:
                        pass
            self._restart_count = 0
            if hasattr(self, "_lag_timer"):
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
        """供 console_page 在收到输出时调用，检测 list 响应计算 RTT。"""
        import time, re
        if self._lag_ping_pending and re.search(r"players online", text, re.I):
            rtt = (time.time() - self._lag_ping_sent) * 1000.0
            if 0 < rtt < 60000:
                self._lag_samples.append(rtt)
                if len(self._lag_samples) > 10:
                    self._lag_samples.pop(0)
            self._lag_ping_pending = False
            # 更新仪表盘 RTT
            if self._lag_samples:
                s = sorted(self._lag_samples)
                med = s[len(s) // 2]
                color = "#4CAF50" if med < 80 else ("#ffaa00" if med < 200 else "#ff5555")
                self.dashboard_page.status_card.update_rtt(med, color)

    # ---------- 资源监控（共享）----------
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
        self._update_checker = CheckUpdateWorker(self)
        self._update_checker.result.connect(self._on_self_update_found)
        self._update_checker.start()

    def _on_self_update_found(self, status, remote_ver, dl_url, sha256):
        from shared.toast import toast_success, toast_error, toast_warning, toast_info
        if status == "error":
            toast_error("版本检查失败", remote_ver or "网络错误", self, duration=5000)
            return
        if status == "latest":
            toast_success("已是最新版本", f"v{__version__}（远程: v{remote_ver}）", self)
            return
        if not dl_url:
            toast_warning("更新源缺失", "version.json 未提供下载链接", self, duration=6000)
            return
        toast_info("发现新版本", f"v{__version__} → v{remote_ver}，正在后台下载...", self)
        self._dl_updater = DownloadUpdateWorker(dl_url, remote_ver, self)
        self._dl_updater.finished.connect(lambda s, m, p: self._on_update_downloaded(s, m, p, sha256))
        self._dl_updater.start()

    def _on_update_downloaded(self, success, msg, path, sha256):
        from shared.toast import toast_success, toast_error
        if not success:
            toast_error("下载失败", msg, self, duration=5000); return
        if not is_valid_zip(path):
            toast_error("下载无效", "Release 资产未上传？请用 release_gui.py 发布", self)
            try:
                os.remove(path)
            except OSError:
                pass
            return
        ok, sha_msg = verify_sha256(path, sha256)
        if not ok:
            toast_error("SHA256 校验失败", sha_msg, self)
            try:
                os.remove(path)
            except OSError:
                pass
            return
        toast_success("更新包就绪", f"正在安装...", self)
        self._installer = InstallUpdateWorker(path, self)
        self._installer.finished.connect(self._on_update_installed)
        self._installer.start()

    def _on_update_installed(self, success, msg):
        from PySide6.QtWidgets import QMessageBox
        from shared.toast import toast_error
        if success:
            QMessageBox.information(self, "更新完成",
                "BDS Manager 已更新！\n旧文件已备份到 backups/upgrade_backup_*/\n程序即将自动重启。")
            restart_app("main.py")
        else:
            toast_error("安装失败", msg, self, duration=6000)


# ---------- 入口 ----------
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("BDS Manager")
    app.setApplicationVersion(__version__)

    config_mgr.load()
    init_context(config_mgr.get("server_dir"))

    window = BDSFluentWindow()
    window.apply_theme(
        config_mgr.get("theme", "dark"),
        config_mgr.get("theme_color", "#0DC5D4"),
    )
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
