# -*- coding: utf-8 -*-
"""
服务器生命周期管理 —— 启停 / 崩溃自愈 / RTT 延迟 / 资源监控回调。

v3.03.01 从 main.py 拆分：作为 BDSFluentWindow 的方法，通过 self.xxx 访问 UI。
"""

import os
import time
import re
from datetime import datetime

from PySide6.QtCore import QTimer

from shared.config import config_mgr, get_context, LOG_DIR
from backend.server import ServerProcess
from backend.monitor import SystemStatsSnapshot
from backend.webhook import send_webhook
from backend.notifications import notify


# ── 以下方法直接导入到 BDSFluentWindow 中 ──

def start_server(window):
    """启动 BDS 服务器。"""
    if window._server and window._server.is_running:
        return "服务器已在运行中"

    ctx = get_context()
    exe_path = os.path.join(ctx.server_dir, config_mgr.get("server_exe", "bedrock_server.exe"))
    if not os.path.exists(exe_path):
        err = f"未找到服务器可执行文件: {exe_path}"
        notify("error", "server", "服务器启动失败", err, "page:dashboard")
        return err

    if window._server is not None:
        try:
            window._server.output_received.disconnect()
            window._server.process_stopped.disconnect()
            window._server.error_occurred.disconnect()
            window._server.status_changed.disconnect()
            window._server.proc_stats.disconnect()
        except (TypeError, RuntimeError):
            pass
    window._server = ServerProcess(exe_path, ctx.server_dir)
    window._server.output_received.connect(
        lambda t: _on_server_output(window, t))
    window._server.process_stopped.connect(
        lambda rc: _on_server_stopped(window, rc))
    window._server.error_occurred.connect(
        lambda msg: (
            window.console_page._append_output(f"[ERROR] {msg}", "#ff5555"),
            notify("error", "server", "服务器错误", msg, "page:console"),
        )
    )
    window._server.status_changed.connect(
        lambda r: _on_status_changed(window, r))
    if config_mgr.get("enable_bds_process_monitor", True):
        window._server.proc_stats.connect(window.dashboard_page.update_proc_stats)
    window._server.start()

    window.dashboard_page._on_server_started()
    window.console_page._on_server_started()
    notify("success", "server", "服务器已启动", os.path.basename(exe_path), "page:dashboard")

    if not hasattr(window, "_lag_timer") or not window._lag_timer:
        window._lag_timer = QTimer(window)
        window._lag_timer.timeout.connect(lambda: _lag_ping(window))
    window._lag_timer.start(30000)
    return None


def stop_server(window):
    """停止 BDS 服务器。"""
    if window._server and window._server.is_running:
        window.console_page._append_output("[系统] 正在停止服务器...", "#E65100")
        window._server.stop_server(graceful=False)
    window._restart_count = 0
    if hasattr(window, "_lag_timer") and window._lag_timer:
        window._lag_timer.stop()


def _on_server_output(window, text: str):
    window.console_page._append_output(text)
    window.dashboard_page.on_output()


def _on_server_stopped(window, retcode: int):
    window.dashboard_page._on_server_stopped()
    window.console_page._on_server_stopped()

    if retcode == 0:
        window.console_page._append_output("[系统] 服务器已正常退出", "#555")
        window._restart_count = 0
        if hasattr(window, "_lag_timer") and window._lag_timer:
            window._lag_timer.stop()
        return

    if retcode == -1:
        window.console_page._append_output("[系统] 服务器启动失败", "#ff5555")
        notify("error", "server", "服务器启动失败", "", "page:console")
        return

    send_webhook("crash", "服务器崩溃", f"BDS 异常退出，返回码: {retcode}")
    notify("warning", "server", "服务器已停止", f"退出码 {retcode}", "page:console")
    max_retries = config_mgr.get("max_restart_retries", 5)
    if max_retries > 0 and window._restart_count < max_retries:
        window._restart_count += 1
        msg = f"服务器崩溃，5秒后自动重启（第 {window._restart_count}/{max_retries} 次）"
        window.console_page._append_output(f"[系统] {msg}", "#E65100")
        window.console_page.mark_crash(window._restart_count, max_retries)
        from shared.toast import toast_warning
        toast_warning("自动重启", f"第 {window._restart_count} 次尝试", window)
        QTimer.singleShot(5000, lambda: start_server(window))
    else:
        if window._restart_count >= max_retries and max_retries > 0:
            log_text = window.console_page._log.toPlainText()
            if log_text:
                try:
                    crash_path = os.path.join(LOG_DIR, f"crash_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
                    with open(crash_path, "w", encoding="utf-8") as f:
                        f.write(log_text[-8000:])
                    window.console_page._append_output(f"[系统] 崩溃日志已保存: {crash_path}", "#555")
                except OSError:
                    pass
        window._restart_count = 0
        if hasattr(window, "_lag_timer") and window._lag_timer:
            window._lag_timer.stop()


def _on_status_changed(window, running: bool):
    window.dashboard_page._on_status_changed(running)
    window.console_page._on_status_changed(running)


# ── RTT 延迟探测 ──

def _lag_ping(window):
    if not window._server or not window._server.is_running:
        return
    window._lag_ping_sent = time.time()
    window._lag_ping_pending = True
    window._server.send_command("list")


def check_lag_response(window, text: str):
    if window._lag_ping_pending and re.search(r"players online", text, re.I):
        rtt = (time.time() - window._lag_ping_sent) * 1000.0
        if 0 < rtt < 60000:
            window._lag_samples.append(rtt)
            if len(window._lag_samples) > 10:
                window._lag_samples.pop(0)
        window._lag_ping_pending = False
        if window._lag_samples:
            s = sorted(window._lag_samples)
            med = s[len(s) // 2]
            color = "#4CAF50" if med < 80 else ("#E65100" if med < 200 else "#ff5555")
            window.dashboard_page.status_card.update_rtt(med, color)


# ── 资源监控回调 ──

def on_stats_updated(window, snap: SystemStatsSnapshot):
    window.dashboard_page.status_card.update_server_stats(snap)
    if not hasattr(window, "_last_mem_warn"):
        window._last_mem_warn = 0.0
    threshold = config_mgr.get("mem_warn_threshold", 80) or 80
    if snap.mem_percent >= threshold and time.time() - window._last_mem_warn > 30:
        window._last_mem_warn = time.time()
        msg = f"内存使用率 {snap.mem_percent:.1f}%（阈值: {threshold}%）"
        send_webhook("memory", "内存告警", msg)
        from shared.toast import toast_warning
        toast_warning("内存告警", msg, window, duration=8000)
