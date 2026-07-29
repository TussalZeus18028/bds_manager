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

# script dir = project root (Manager_Fluent/)
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── 以下方法直接导入到 BDSFluentWindow 中 ──

_DEFAULT_PROPERTIES = [
    "server-name=Dedicated Server", "gamemode=survival", "difficulty=easy",
    "allow-cheats=false", "max-players=10", "online-mode=true",
    "allow-list=false", "view-distance=32", "tick-distance=4",
    "player-idle-timeout=30", "max-threads=8", "level-name=Bedrock level",
    "default-player-permission-level=member", "texturepack-required=false",
    "content-log-file-enabled=false", "content-log-console-output-enabled=false",
    "compression-threshold=1", "server-authoritative-movement=server-auth",
    "player-movement-score-threshold=20",
    "player-movement-action-direction-threshold=0.85",
    "player-movement-distance-threshold=0.3",
    "player-movement-duration-threshold-in-ms=500",
    "correct-player-movement=false", "server-authoritative-block-breaking=false",
]

_LL_EXE_CANDIDATES = [
    lambda: os.path.dirname(SCRIPT_DIR),
    lambda: os.path.join(os.path.dirname(SCRIPT_DIR), "LLServer"),
    lambda: os.path.join(os.path.dirname(SCRIPT_DIR), "Server"),
    lambda: SCRIPT_DIR,
    lambda: os.path.join(SCRIPT_DIR, "LLServer"),
]


def _ensure_default_properties(srv_dir: str) -> None:
    """BDS 首次启动前自动生成默认配置和必要文件。"""
    props = os.path.join(srv_dir, "server.properties")
    allowlist = os.path.join(srv_dir, "allowlist.json")
    if os.path.exists(props) and os.path.exists(allowlist):
        return
    try:
        if not os.path.exists(props):
            with open(props, "w", encoding="utf-8") as f:
                f.write("\n".join(_DEFAULT_PROPERTIES) + "\n")
        if not os.path.exists(allowlist):
            with open(allowlist, "w", encoding="utf-8") as f:
                f.write("[]\n")
        notify("info", "server", "配置就绪",
               f"已自动生成 server.properties + allowlist.json 到 {srv_dir}", "page:dashboard")
    except OSError:
        logger.warning("无法创建配置文件 (%s)", srv_dir)


def _try_find_ll_exe(srv_dir: str, exe_path: str) -> tuple[str, str] | None:
    """搜索 LL 服务器可执行文件，返回 (srv_dir, exe_path) 或 None。"""
    for candidate_fn in _LL_EXE_CANDIDATES:
        d = candidate_fn()
        candidate = os.path.join(d, "bedrock_server_mod.exe")
        if d and os.path.isfile(candidate):
            config_mgr.set("ll_server_dir", d)
            config_mgr.save()
            return (d, candidate)
    return None


def start_server(window):
    """启动 BDS 服务器（支持纯 BDS 或 LeviLamina）。"""
    if window._server and window._server.is_running:
        return "服务器已在运行中"

    ctx = get_context()
    stype = config_mgr.get("server_type", "bds")

    if stype == "ll":
        ll_dir = config_mgr.get("ll_server_dir", "")
        srv_dir = ll_dir if (ll_dir and os.path.isabs(ll_dir)) else (
            os.path.join(SCRIPT_DIR, ll_dir) if ll_dir else ctx.server_dir)
        exe_name = "bedrock_server_mod.exe"
    else:
        srv_dir = ctx.server_dir
        exe_name = config_mgr.get("server_exe", "bedrock_server.exe")

    exe_path = os.path.join(srv_dir, exe_name)
    _ensure_default_properties(srv_dir)

    # LL 服务器自动检测
    if not os.path.exists(exe_path) and stype == "ll":
        found = _try_find_ll_exe(srv_dir, exe_path)
        if found:
            srv_dir, exe_path = found

    # BDS 不存在时尝试回退到 LL
    if not os.path.exists(exe_path) and stype == "bds":
        alt = os.path.join(srv_dir, "bedrock_server_mod.exe")
        if os.path.exists(alt):
            config_mgr.set("server_type", "ll")
            config_mgr.set("ll_server_dir", config_mgr.get("server_dir", "Server"))
            config_mgr.save()
            srv_dir, exe_path, exe_name = srv_dir, alt, "bedrock_server_mod.exe"

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
    window._server = ServerProcess(exe_path, srv_dir)
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
        window._intentional_stop = True
        window.console_page._append_output("[系统] 正在停止服务器...", "#E65100")
        graceful = config_mgr.get("graceful_shutdown", True)
        grace_seconds = config_mgr.get("shutdown_grace_seconds", 10)
        window._server.stop_server(graceful=graceful, grace_seconds=grace_seconds)
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

    if getattr(window, "_intentional_stop", False):
        window._intentional_stop = False
        window.console_page._append_output("[系统] 服务器已停止（用户操作）", "#888")
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
