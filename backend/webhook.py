# -*- coding: utf-8 -*-
"""
Webhook 通知 —— Discord / 企业微信 / 自定义 URL 推送。
"""

import json
import logging
import requests

from shared.config import config_mgr

logger = logging.getLogger("bds_manager")


def send_webhook(event: str, title: str, message: str):
    """向配置的 Webhook URL 发送通知。

    仅当 webhook_url 非空且 event 在 webhook_events 列表中时发送。
    失败静默忽略，不影响主流程。
    """
    url = (config_mgr.get("webhook_url") or "").strip()
    if not url:
        return
    events = config_mgr.get("webhook_events", [])
    if event not in events:
        return
    try:
        payload = {
            "content": f"**[{title}]** {message}",
            "text": f"[{title}] {message}",
            "username": "BDS Manager",
        }
        resp = requests.post(url, json=payload, timeout=8)
        if resp.status_code >= 400:
            logger.warning("Webhook 通知失败 (%s): HTTP %d", event, resp.status_code)
    except Exception as e:
        logger.warning("Webhook 通知异常 (%s): %s", event, e)
