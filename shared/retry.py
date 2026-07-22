# -*- coding: utf-8 -*-
"""
重试装饰器：指数退避 + 可重试异常白名单。

使用：
    from shared.retry import retry

    @retry(max_attempts=3, backoff=2.0, retry_on=(requests.ConnectionError, socket.timeout))
    def fetch_remote_version():
        ...
"""

import time
import logging
import functools
from typing import Type, Tuple, Iterable, Callable

logger = logging.getLogger("bds_manager")


def retry(
    max_attempts: int = 3,
    backoff: float = 2.0,
    initial_delay: float = 1.0,
    max_delay: float = 30.0,
    retry_on: Tuple[Type[Exception], ...] | Type[Exception] | None = Exception,
    on_retry: Callable[[int, Exception, float], None] | None = None,
):
    """指数退避重试装饰器。

    参数：
        max_attempts  总尝试次数（含首次）
        backoff       退避倍率（每轮等待时间 *= backoff）
        initial_delay 首次重试前的等待秒数
        max_delay     单次等待最大秒数
        retry_on      可重试的异常类型元组，默认全部 Exception
        on_retry      回调函数 (attempt_idx, exc, next_delay)
    """
    if isinstance(retry_on, type):
        retry_on = (retry_on,)

    def deco(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exc = e
                    if retry_on and not isinstance(e, retry_on):
                        raise
                    if attempt >= max_attempts:
                        logger.warning(
                            "%s 第 %d/%d 次尝试仍失败，放弃: %s",
                            func.__name__, attempt, max_attempts, e,
                        )
                        raise
                    logger.info(
                        "%s 第 %d/%d 次失败，%ss 后重试: %s",
                        func.__name__, attempt, max_attempts, delay, e,
                    )
                    if on_retry:
                        try:
                            on_retry(attempt, e, delay)
                        except Exception:
                            pass
                    time.sleep(delay)
                    delay = min(delay * backoff, max_delay)
            # 理论上不会到这里
            if last_exc:
                raise last_exc
        return wrapper
    return deco
