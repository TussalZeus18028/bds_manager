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
    """按大小轮转，旧文件自动 gzip 压缩。"""

    def __init__(self, filename, mode="a", maxBytes=0, backupCount=0,
                 encoding=None, delay=False, errors=None):
        super().__init__(filename, mode, maxBytes, backupCount, encoding, delay, errors)
        self._namer_gzip = None  # 标记是否已重命名

    def doRollover(self):
        """重写：先调用父类轮转，再把轮出的 .1 .2 文件 gzip 压缩。"""
        super().doRollover()
        try:
            base_path = self.baseFilename
            # 把 backups/bds_manager.log.X 压缩为 backups/bds_manager.log.X.gz
            for i in range(1, self.backupCount + 1):
                s = f"{base_path}.{i}"
                if os.path.exists(s) and not s.endswith(".gz"):
                    gz = s + ".gz"
                    with open(s, "rb") as f_in, gzip.open(gz, "wb", compresslevel=6) as f_out:
                        shutil.copyfileobj(f_in, f_out)
                    try:
                        os.remove(s)
                    except OSError:
                        pass
        except Exception as e:
            # 压缩失败不应阻断日志
            logging.getLogger("bds_manager").debug("日志压缩失败: %s", e)


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
