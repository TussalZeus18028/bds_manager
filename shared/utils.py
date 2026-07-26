# -*- coding: utf-8 -*-
"""
shared/utils.py — 通用工具函数。
"""


def format_time_ago(seconds: float) -> str:
    """将秒数转为 "X 秒前/分钟前/小时前/天前" 格式。"""
    if seconds < 60:
        return f"{int(seconds)} 秒前"
    mins = int(seconds / 60)
    if mins < 60:
        return f"{mins} 分钟前"
    hours = int(mins / 60)
    if hours < 24:
        return f"{hours} 小时前"
    days = int(hours / 24)
    return f"{days} 天前"
