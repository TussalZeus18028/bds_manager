# -*- coding: utf-8 -*-
"""
日志轮转处理器：按天/按大小切割 + 旧文件 gzip 压缩。

使用：
    from backend.log_handler import setup_rotating_logger, make_rotating_file_handler

    setup_rotating_logger("bds_manager", "logs/bds_manager.log", max_bytes=5*1024*1024, backups=5)
"""

import os
import gzip
import logging
import shutil
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler


class GzipRotatingFileHandler(RotatingFileHandler):
    """按大小轮转，轮转文件自动 gzip 压缩。

    v3.05.02 重构（修复压缩链断裂）：
    - 旧实现：父类轮转 `.1/.2` 中间态后再压缩成 `.gz`，父类从此"看不见"这些文件，
      导致 `.2.gz~.5.gz` 永远停留在首次到达该编号的旧内容，backupCount 形同虚设。
    - 新实现：namer 让所有轮转名直接带 `.gz`（父类以 `.gz` 后缀管理整条链：
      超龄清理、`.1.gz → .2.gz` 移动均由父类完成），rotator 在 rotate 时直接 gzip。
    """

    def __init__(self, filename, mode="a", maxBytes=0, backupCount=0,
                 encoding=None, delay=False, errors=None):
        super().__init__(filename, mode, maxBytes, backupCount, encoding, delay, errors)
        # namer：轮转目标名统一加 .gz
        self.namer = lambda name: name + ".gz"
        # rotator：父类 rotate(source, dest) 时 gzip 压缩 source 到 dest
        self.rotator = self._gzip_rotate

    @staticmethod
    def _gzip_rotate(source, dest):
        try:
            with open(source, "rb") as f_in:
                with gzip.open(dest, "wb", compresslevel=6) as f_out:
                    shutil.copyfileobj(f_in, f_out)
            os.remove(source)
        except OSError:
            # 压缩失败不应阻断日志（保留未压缩源文件，下次轮转父类会再处理）
            pass


def make_rotating_file_handler(
    log_path: str,
    max_bytes: int = 5 * 1024 * 1024,  # 5 MB
    backups: int = 5,
    encoding: str = "utf-8",
) -> logging.Handler:
    """构造按大小轮转 + gzip 压缩的 FileHandler。"""
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    return GzipRotatingFileHandler(
        log_path, maxBytes=max_bytes, backupCount=backups, encoding=encoding,
    )


def make_daily_file_handler(
    log_path: str,
    when: str = "midnight",
    backup_count: int = 14,  # 保留 14 天
    encoding: str = "utf-8",
) -> logging.Handler:
    """构造按天轮转的 FileHandler。"""
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    return TimedRotatingFileHandler(
        log_path, when=when, backupCount=backup_count, encoding=encoding, utc=False,
    )


def setup_rotating_logger(
    name: str,
    log_path: str,
    max_bytes: int = 5 * 1024 * 1024,
    backups: int = 5,
    level: int = logging.INFO,
    fmt: str = "[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt: str = "%Y-%m-%d %H:%M:%S",
) -> logging.Logger:
    """一键配置：rotating file + console stream 双 handler。"""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    # 清掉已有 handler 避免重复
    for h in list(logger.handlers):
        logger.removeHandler(h)
    # Rotating file
    fh = make_rotating_file_handler(log_path, max_bytes=max_bytes, backups=backups)
    fh.setFormatter(logging.Formatter(fmt, datefmt))
    logger.addHandler(fh)
    # Console
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter(fmt, datefmt))
    logger.addHandler(ch)
    return logger
