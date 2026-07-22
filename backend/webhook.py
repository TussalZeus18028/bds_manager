# -*- coding: utf-8 -*-
"""
Webhook 通知 —— Discord / 企业微信 / 自定义 URL 推送。

v3.1 改进：
- 扩展事件类型：player_join/player_leave/command_executed/server_started
- 失败重试 3 次（指数退避）
- 支持事件模板（按 event 自定义标题前缀、颜色等）
"""

import json
import logging
import socket
import urllib.request
import urllib.error
import time
from shared.config import config_mgr
from shared.retry import retry
from shared.errors import NetworkError

logger = logging.getLogger("bds_manager")

# 支持的事件类型
SUPPORTED_EVENTS = [
    "backup",           # 备份完成
    "crash",            # 服务器崩溃/停止
    "memory",           # 内存告警
    "player_join",      # 玩家加入
    "player_leave",     # 玩家离开
    "command_executed", # 执行了命令
    "server_started",   # 服务器启动
    "update_available", # 工具更新可用
]

# 事件标题前缀（用于 Discord/企业微信的可读性）
EVENT_PREFIX = {
    "backup": "[备份]",
    "crash": "[崩溃]",
    "memory": "[内存]",
    "player_join": "[加入]",
    "player_leave": "[离开]",
    "command_executed": "[命令]",
    "server_started": "[启动]",
    "update_available": "[更新]",
}

# 事件颜色（仅 Discord 使用）
EVENT_COLOR = {
    "backup": 0x4CAF50,
    "crash": 0xFF5555,
    "memory": 0xFFAA00,
    "player_join": 0x44CC66,
    "player_leave": 0x888888,
    "command_executed": 0x4488FF,
    "server_started": 0x0DC5D4,
    "update_available": 0xFFD700,
}


# 网络重试白名单
_RETRY_EXC = (
    urllib.error.URLError,
    socket.timeout,
    ConnectionError,
    TimeoutError,
)


@retry(max_attempts=3, backoff=2.0, initial_delay=1.0, retry_on=_RETRY_EXC)
def _post_webhook(url: str, payload: dict, timeout: int = 8):
    """实际发送 POST 请求，带重试。"""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "BDS-Manager/3.1"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status >= 400:
            raise NetworkError(f"Webhook HTTP {resp.status}", code="E_WEBHOOK_HTTP")


def send_webhook(event: str, title: str, message: str, extra: dict | None = None):
    """向配置的 Webhook URL 发送通知。

    仅当 webhook_url 非空且 event 在 webhook_events 列表中时发送。
    失败静默记录日志，不影响主流程。
    """
    url = (config_mgr.get("webhook_url") or "").strip()
    if not url:
        return
    events = config_mgr.get("webhook_events", [])
    if event not in events:
        return

    prefix = EVENT_PREFIX.get(event, "[事件]")
    full_title = f"{prefix} {title}"
    payload = {
        "content": f"**{full_title}** {message}",
        "text": f"{full_title} {message}",
        "username": "BDS Manager",
        "title": full_title,
        "message": message,
        "event": event,
    }
    # Discord embed 颜色
    if event in EVENT_COLOR:
        payload["embeds"] = [{
            "title": full_title,
            "description": message,
            "color": EVENT_COLOR[event],
        }]
    # 额外字段
    if extra:
        payload["extra"] = extra

    try:
        _post_webhook(url, payload)
    except Exception as e:
        logger.warning("Webhook 通知失败 (%s): %s", event, e)
