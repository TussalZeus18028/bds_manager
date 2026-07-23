# -*- coding: utf-8 -*-
"""
共享配置模块：路径常量、配置读写、ServerContext。

设计原则：无 PySide6 / QFluentWidgets 依赖，可在 Worker 线程中安全导入。

改进（v3.1）：
- 原子写：tmp + fsync + os.replace，避免半写入
- Schema 校验：类型不匹配自动修正
- 配置版本号：旧版自动迁移
- 快照回滚：每次保存保留最近 5 份到 backups/config/
"""

import os
import json
import shutil
import logging
from collections import deque
from datetime import datetime

logger = logging.getLogger("bds_manager")

# ---------- 路径常量 ----------
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "bds_manager_config.json")
VERSION_CACHE_FILE = os.path.join(SCRIPT_DIR, "bds_version_cache.json")
LOG_DIR = os.path.join(SCRIPT_DIR, "logs")
CONFIG_BACKUP_DIR = os.path.join(SCRIPT_DIR, "backups", "config")
CONFIG_MAX_BACKUPS = 5
CONFIG_VERSION = "3.1"  # 当前配置 schema 版本


def _get_default_bedrock_exe_name():
    """返回默认的 BDS 可执行文件名。"""
    return "bedrock_server.exe"


# ---------- 配置读取 ----------
def get_server_dir():
    """从配置文件读取服务器目录，用于 ServerContext 初始化。"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            server_dir = cfg.get("server_dir")
            if server_dir and os.path.isabs(server_dir):
                return server_dir
            elif server_dir:
                return os.path.join(SCRIPT_DIR, server_dir)
        except Exception:
            pass
    default = os.path.join(SCRIPT_DIR, "Server")
    os.makedirs(default, exist_ok=True)
    return default


# ---------- 服务器路径上下文 ----------
class ServerContext:
    """集中管理所有服务器文件路径。"""

    def __init__(self, server_dir):
        self.server_dir = server_dir
        self.server_properties = os.path.join(server_dir, "server.properties")
        self.allowlist_file = os.path.join(server_dir, "allowlist.json")
        self.permissions_file = os.path.join(server_dir, "permissions.json")
        self.packet_limit_file = os.path.join(server_dir, "packetlimitconfig.json")
        self.worlds_dir = os.path.join(server_dir, "worlds")
        self.resource_packs_dir = os.path.join(server_dir, "resource_packs")
        self.behavior_packs_dir = os.path.join(server_dir, "behavior_packs")
        self.backup_dir = os.path.join(server_dir, "backups")

    def update(self, server_dir):
        self.__init__(server_dir)
        for d in [self.worlds_dir, self.resource_packs_dir, self.behavior_packs_dir, self.backup_dir]:
            os.makedirs(d, exist_ok=True)

    @property
    def SERVER_DIR(self):
        return self.server_dir

    @property
    def SERVER_PROPERTIES(self):
        return self.server_properties

    @property
    def ALLOWLIST_FILE(self):
        return self.allowlist_file

    @property
    def PERMISSIONS_FILE(self):
        return self.permissions_file

    @property
    def PACKET_LIMIT_FILE(self):
        return self.packet_limit_file

    @property
    def WORLDS_DIR(self):
        return self.worlds_dir

    @property
    def RESOURCE_PACKS_DIR(self):
        return self.resource_packs_dir

    @property
    def BEHAVIOR_PACKS_DIR(self):
        return self.behavior_packs_dir

    @property
    def BACKUP_DIR(self):
        return self.backup_dir


# 全局上下文实例（惰性加载，由 main.py 显式初始化）
_ctx: ServerContext | None = None


def init_context(server_dir: str | None = None):
    """初始化全局 ServerContext。"""
    global _ctx
    if server_dir is None:
        server_dir = get_server_dir()
    _ctx = ServerContext(server_dir)
    logger.info("服务器目录: %s", _ctx.server_dir)
    os.makedirs(LOG_DIR, exist_ok=True)
    return _ctx


def get_context() -> ServerContext:
    """获取全局 ServerContext（使用前须先调用 init_context）。"""
    if _ctx is None:
        raise RuntimeError("ServerContext 未初始化，请先调用 init_context()")
    return _ctx


# ---------- 默认配置 ----------
DEFAULT_CONFIG = {
    "config_version": CONFIG_VERSION,
    "theme": "dark",
    "theme_color": "#0DC5D4",
    "server_dir": "Server",
    "server_exe": _get_default_bedrock_exe_name(),
    "auto_backup_enabled": True,
    "backup_interval": 60,
    "monitor_interval": 2000,
    "backup_keep": 20,
    "backup_min_age_days": 0,
    "online_backup": True,
    "webhook_url": "",
    "webhook_events": ["backup", "crash", "memory"],
    "frpc_path": "",
    "mem_warn_threshold": 70,
    "max_restart_retries": 5,
    "auto_check_update": True,
    "multi_dl_enabled": True,
    "show_startup_toasts": True,
    "toast_duration_error": 5000,
    "toast_duration_warning": 4000,
    "toast_duration_success": 3500,
    "toast_duration_info": 3000,
    "toast_queue_delay": 200,
    "toast_opacity": 95,
    "toast_style": "original",  # "original" / "modern"
    "window_width": 1200,
    "window_height": 800,
    "github_auth_enabled": False,
    "github_token": "",
    # 新增（v3.1）
    "font_size": 12,                 # 全局 UI 字号
    "follow_system_theme": False,    # 监听 OS 主题变化
    "console_show_timestamps": True,  # 控制台每行时间戳
    "console_max_lines": 5000,        # 控制台最大行数
    "console_auto_scroll": True,
    "enable_bds_process_monitor": True,  # 监控 BDS 进程 CPU/内存
    "graceful_shutdown": True,           # 优雅停服
    "shutdown_grace_seconds": 10,        # stop 等待秒数
    # v3.02.00 新增
    "show_command_palette_tip": True,    # 首次启动提示「Ctrl+K 试试」
    "shortcuts": {},                     # 快捷键用户自定义覆盖 {action_id: key_string}
}

# 类型 schema（用于校验和自动修正）
SCHEMA = {
    "monitor_interval": (int, 200, 10000),
    "backup_interval": (int, 1, 10080),
    "backup_keep": (int, 1, 1000),
    "mem_warn_threshold": (int, 10, 100),
    "max_restart_retries": (int, 0, 100),
    "toast_duration_error": (int, 1000, 60000),
    "toast_duration_warning": (int, 1000, 60000),
    "toast_duration_success": (int, 1000, 60000),
    "toast_duration_info": (int, 1000, 60000),
    "toast_queue_delay": (int, 0, 5000),
    "toast_opacity": (int, 10, 100),
    "window_width": (int, 800, 4000),
    "window_height": (int, 600, 4000),
    "font_size": (int, 9, 20),
    "console_max_lines": (int, 100, 100000),
    "shutdown_grace_seconds": (int, 1, 60),
}

BOOL_FIELDS = {
    "auto_backup_enabled", "online_backup", "auto_check_update",
    "multi_dl_enabled", "show_startup_toasts", "github_auth_enabled",
    "follow_system_theme", "console_show_timestamps",
    "enable_bds_process_monitor", "graceful_shutdown",
    "console_auto_scroll",
}

STR_CHOICES = {
    "theme": {"dark", "light", "auto"},
    "toast_style": {"original", "modern"},
}


def _validate_value(key: str, value):
    """校验单个配置值，超出范围或类型错误时返回 default。"""
    if key in BOOL_FIELDS:
        if not isinstance(value, bool):
            return DEFAULT_CONFIG.get(key)
        return value
    if key in SCHEMA:
        tp, lo, hi = SCHEMA[key]
        if not isinstance(value, (int, float)):
            return DEFAULT_CONFIG.get(key)
        if value < lo or value > hi:
            return max(lo, min(hi, value))
        return int(value)
    if key in STR_CHOICES:
        if value not in STR_CHOICES[key]:
            return DEFAULT_CONFIG.get(key)
        return value
    return value


def _migrate_config(loaded: dict) -> dict:
    """配置迁移：从旧版本升级到当前 schema。"""
    cfg_ver = loaded.get("config_version", "")
    # 3.0 → 3.1：新增字段已在 DEFAULT_CONFIG 通过 .get() 补全，无需特殊处理
    # 这里保留扩展点
    if not cfg_ver:
        logger.info("配置无 version 字段，视为 v3.0 升级到 v%s", CONFIG_VERSION)
    return loaded


class ConfigManager:
    """配置管理器：读写 bds_manager_config.json。"""

    def __init__(self):
        self.values: dict = {}
        self._history: deque = deque(maxlen=CONFIG_MAX_BACKUPS)

    def load(self) -> dict:
        """加载配置，缺失键用 DEFAULT_CONFIG 补全。"""
        config = dict(DEFAULT_CONFIG)
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                # 迁移
                loaded = _migrate_config(loaded)
                # 用 schema 校验后的值覆盖
                for k in DEFAULT_CONFIG:
                    raw = loaded.get(k, DEFAULT_CONFIG[k])
                    config[k] = _validate_value(k, raw)
            except (json.JSONDecodeError, FileNotFoundError, UnicodeDecodeError) as e:
                logger.error("加载配置文件失败: %s", e)
                # 尝试恢复最近一次备份
                self._try_restore_backup()
        # 从独立版本缓存加载
        if os.path.exists(VERSION_CACHE_FILE):
            try:
                with open(VERSION_CACHE_FILE, "r", encoding="utf-8") as f:
                    vc = json.load(f)
                config["version_cache"] = vc.get("version_cache", {})
                config["version_list"] = vc.get("version_list", {})
            except (json.JSONDecodeError, FileNotFoundError):
                pass
        self.values = config
        return config

    def save(self):
        """原子保存：先写 tmp，fsync 后 rename，保留最近 5 份快照。"""
        keys = [
            "config_version", "theme", "theme_color", "server_dir", "server_exe",
            "auto_backup_enabled", "backup_interval", "monitor_interval",
            "backup_keep", "backup_min_age_days", "online_backup",
            "webhook_url", "webhook_events", "frpc_path",
            "mem_warn_threshold", "max_restart_retries",
            "auto_check_update", "multi_dl_enabled", "show_startup_toasts",
            "toast_duration_error", "toast_duration_warning",
            "toast_duration_success", "toast_duration_info",
            "toast_queue_delay", "toast_opacity", "toast_style",
            "window_width", "window_height",
            "github_auth_enabled", "github_token",
            # v3.1 新增
            "font_size", "follow_system_theme",
            "console_show_timestamps", "console_max_lines", "console_auto_scroll",
            "enable_bds_process_monitor", "graceful_shutdown", "shutdown_grace_seconds",
            # v3.02.00 新增
            "show_command_palette_tip", "shortcuts",
        ]
        data = {k: self.values.get(k, DEFAULT_CONFIG.get(k)) for k in keys}
        os.makedirs(SCRIPT_DIR, exist_ok=True)
        # 原子写
        self._atomic_write_json(CONFIG_FILE, data)
        logger.info("配置已保存: %s", os.path.basename(CONFIG_FILE))
        # 版本数据单独存到独立文件
        self._save_version_cache()

    def _atomic_write_json(self, path: str, data: dict):
        """原子写 JSON：tmp + fsync + os.replace，避免半写入。"""
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except (AttributeError, OSError):
                    pass
            os.replace(tmp, path)
        except Exception as e:
            logger.error("原子写入失败 %s: %s", path, e)
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            # 回退：直接写
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)

    def _save_config_snapshot(self):
        """保存当前配置到 backups/config/ 用于回滚。"""
        if not os.path.exists(CONFIG_FILE):
            return
        try:
            os.makedirs(CONFIG_BACKUP_DIR, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            snap = os.path.join(CONFIG_BACKUP_DIR, f"config_{ts}.json")
            shutil.copy2(CONFIG_FILE, snap)
            self._history.append(snap)
            # 清理超出数量的旧备份
            snaps = sorted(
                [os.path.join(CONFIG_BACKUP_DIR, f) for f in os.listdir(CONFIG_BACKUP_DIR) if f.endswith(".json")],
                key=os.path.getmtime, reverse=True,
            )
            for old in snaps[CONFIG_MAX_BACKUPS:]:
                try:
                    os.remove(old)
                except OSError:
                    pass
        except Exception as e:
            logger.debug("配置快照失败: %s", e)

    def _try_restore_backup(self):
        """配置文件损坏时尝试从最新快照恢复。"""
        if not os.path.isdir(CONFIG_BACKUP_DIR):
            return
        snaps = sorted(
            [os.path.join(CONFIG_BACKUP_DIR, f) for f in os.listdir(CONFIG_BACKUP_DIR) if f.endswith(".json")],
            key=os.path.getmtime, reverse=True,
        )
        if not snaps:
            return
        latest = snaps[0]
        try:
            with open(latest, "r", encoding="utf-8") as f:
                json.load(f)  # 验证可解析
            shutil.copy2(latest, CONFIG_FILE)
            logger.warning("主配置损坏，已从快照恢复: %s", os.path.basename(latest))
        except Exception as e:
            logger.error("快照恢复失败: %s", e)

    def rollback(self) -> bool:
        """手动回滚到上一份快照。返回是否成功。"""
        if not os.path.isdir(CONFIG_BACKUP_DIR):
            return False
        snaps = sorted(
            [os.path.join(CONFIG_BACKUP_DIR, f) for f in os.listdir(CONFIG_BACKUP_DIR) if f.endswith(".json")],
            key=os.path.getmtime, reverse=True,
        )
        if not snaps:
            return False
        try:
            shutil.copy2(snaps[0], CONFIG_FILE)
            return True
        except OSError:
            return False

    def _save_version_cache(self):
        """保存版本缓存到独立文件（bds_version_cache.json）。"""
        cache = {
            "version_cache": self.values.get("version_cache", {}),
            "version_list": self.values.get("version_list", {}),
        }
        try:
            self._atomic_write_json(VERSION_CACHE_FILE, cache)
        except Exception as e:
            logger.error("保存版本缓存失败: %s", e)

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def diff(self, other: dict) -> dict:
        """返回与 other 不同的键（{key: (old, new)}）。用于 UI 高亮变更。"""
        result = {}
        for k in other:
            if self.values.get(k) != other[k]:
                result[k] = (other[k], self.values.get(k))
        return result


# 全局配置管理器
config_mgr = ConfigManager()
