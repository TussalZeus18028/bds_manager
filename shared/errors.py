# -*- coding: utf-8 -*-
"""
统一错误处理：业务异常基类 + 全局捕获装饰器。

设计：
- BDSError 携带 hint（用户应该怎么做）字段
- handle_errors 装饰器统一处理：业务异常→带 hint 的 Toast；未预期异常→记录堆栈 + Toast
- 线程安全的信号方式上报到 UI（emit through Qt Signal if available）

使用：
    from shared.errors import BDSError, handle_errors

    raise BDSError("配置文件不存在", hint="请在 设置 页选择 server_dir")

    @handle_errors(default_return=False)
    def risky_operation():
        ...
"""

import logging
import functools
import traceback
from typing import Any, Callable

logger = logging.getLogger("bds_manager")


class BDSError(Exception):
    """BDS Manager 业务异常基类。"""

    def __init__(self, msg: str, hint: str = "", code: str = ""):
        super().__init__(msg)
        self.msg = msg
        self.hint = hint
        self.code = code  # 可选错误码

    def __str__(self):
        if self.hint:
            return f"{self.msg}（建议：{self.hint}）"
        return self.msg


class ServerNotRunningError(BDSError):
    """服务器未运行时就尝试发送命令等。"""
    def __init__(self, action: str = "此操作"):
        super().__init__(
            f"{action}需要服务器在运行中",
            hint="先在 仪表盘 或 控制台 页点击 启动服务器",
            code="E_NOT_RUNNING",
        )


class FileMissingError(BDSError):
    """关键文件缺失。"""
    def __init__(self, path: str, hint: str = ""):
        super().__init__(
            f"文件不存在: {path}",
            hint=hint or "请先在 设置 页配置正确的路径",
            code="E_FILE_MISSING",
        )


class NetworkError(BDSError):
    """网络相关错误（封装 network.py 的友好文案）。"""
    def __init__(self, zh: str, en: str = "", code: str = "E_NETWORK"):
        super().__init__(
            f"{zh}\n({en})" if en else zh,
            hint="请检查网络连接或代理设置",
            code=code,
        )


# 全局错误回调（由 main.py 在启动时注入为 toast 弹窗）
_error_handler: Callable[[str, str, str], None] | None = None


def set_error_handler(handler: Callable[[str, str, str], None]):
    """注入全局错误处理回调：handler(title, msg, level)。"""
    global _error_handler
    _error_handler = handler


def _report_error(title: str, msg: str, level: str = "ERROR"):
    """内部使用：调用注入的 handler 或记录日志。"""
    if _error_handler is not None:
        try:
            _error_handler(title, msg, level)
            return
        except Exception as e:
            logger.warning("错误处理器异常: %s", e)
    # 兜底：仅记录日志
    logger.error("[%s] %s: %s", level, title, msg)


def handle_errors(default_return: Any = None, title: str = "操作失败", silent: bool = False):
    """统一异常捕获装饰器。

    用法：
        @handle_errors()
        def foo(): ...

        @handle_errors(default_return=[], title="加载列表失败")
        def load_list(): ...
    """
    def deco(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except BDSError as e:
                logger.warning("业务异常: %s (hint=%s)", e.msg, e.hint)
                if not silent:
                    _report_error(title, str(e), "ERROR")
                return default_return
            except Exception as e:
                tb = traceback.format_exc()
                logger.error("未预期错误: %s\n%s", e, tb)
                if not silent:
                    _report_error(
                        title,
                        f"{e}\n\n💡 如持续出现请查看 logs/bds_manager.log",
                        "ERROR",
                    )
                return default_return
        return wrapper
    return deco


def install_excepthook():
    """安装全局未捕获异常钩子（用于 GUI 主循环外的异常）。

    用法：在 main.py 启动时调用 install_excepthook()。
    """
    def _hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logger.critical("未捕获异常:\n%s", msg)
        _report_error(
            "程序遇到未预期错误",
            f"{exc_value}\n\n请查看 logs/bds_manager.log 获取详细信息。",
            "ERROR",
        )
    import sys
    sys.excepthook = _hook
