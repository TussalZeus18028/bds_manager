# -*- coding: utf-8 -*-
"""
shared/utils.py — 通用工具函数。
"""

import sys


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



def bds_exe() -> str:
    '''跨平台 BDS 可执行文件名。'''
    return "bedrock_server.exe" if sys.platform == "win32" else "bedrock_server"

def ll_exe() -> str:
    '''跨平台 LL 可执行文件名。'''
    return "bedrock_server_mod.exe" if sys.platform == "win32" else "bedrock_server_mod"

def is_windows() -> bool:
    return sys.platform == "win32"

def is_linux() -> bool:
    return sys.platform == "linux"
