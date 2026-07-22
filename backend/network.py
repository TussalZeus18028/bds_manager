# -*- coding: utf-8 -*-
"""
网络错误友好提示（对齐旧版）。返回中文 + 英文双语文案。
"""

import urllib.request, urllib.error
import socket, ssl


def network_error_text(exc) -> tuple[str, str, str]:
    """返回 (zh, en, combined)。combined = '中文\n(English)'。"""
    if exc is None:
        return "未知网络错误", "Unknown network error", "未知网络错误\n(Unknown network error)"
    try:
        msg = str(exc)
    except Exception:
        msg = repr(exc)
    lower = msg.lower()
    zh, en = "", ""

    if isinstance(exc, urllib.error.HTTPError):
        code = getattr(exc, "code", "?")
        reason = getattr(exc, "reason", "")
        zh, en = f"服务器返回 HTTP {code} 错误", f"Server returned HTTP {code} ({reason})"
    elif isinstance(exc, urllib.error.URLError):
        r = str(getattr(exc, "reason", exc)).lower()
        if "timed out" in r or "timeout" in r:
            zh, en = "连接超时，请检查网络或稍后重试", "Connection timed out."
        elif "getaddrinfo" in r or "name or service" in r or "nodename" in r:
            zh, en = "无法解析服务器地址（DNS 失败）", "Could not resolve host (DNS failure)."
        elif "refused" in r:
            zh, en = "连接被拒绝", "Connection refused."
        elif "unreachable" in r:
            zh, en = "网络不可达", "Network is unreachable."
        elif "aborted" in r or "reset" in r:
            zh, en = "连接被中断", "Connection was reset."
        else:
            zh, en = f"网络连接失败：{msg}", f"Network error: {msg}"
    elif isinstance(exc, socket.timeout):
        zh, en = "连接超时，请检查网络或稍后重试", "Connection timed out."
    elif isinstance(exc, ssl.SSLError):
        zh, en = "SSL/TLS 安全连接失败", "SSL/TLS secure connection failed."
    else:
        zh, en = f"网络错误：{msg}", f"Network error: {msg}"

    return zh, en, f"{zh}\n({en})"
