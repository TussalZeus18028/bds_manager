# -*- coding: utf-8 -*-
"""
共享配置模块：路径常量、配置读写、ServerContext。

设计原则：无 PySide6 / QFluentWidgets 依赖，可在 Worker 线程中安全导入。
"""

import os
import json
import logging

logger = logging.getLogger("bds_manager")

# ---------- 路径常量 ----------
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "bds_manager_config.json")
VERSION_CACHE_FILE = os.path.join(SCRIPT_DIR, "bds_version_cache.json")
LOG_DIR = os.path.join(SCRIPT_DIR, "logs")


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
}


class ConfigManager:
    """配置管理器：读写 bds_manager_config.json。"""

    def __init__(self):
        self.values: dict = {}

    def load(self) -> dict:
        """加载配置，缺失键用 DEFAULT_CONFIG 补全。"""
        config = dict(DEFAULT_CONFIG)
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                for k in DEFAULT_CONFIG:
                    config[k] = loaded.get(k, DEFAULT_CONFIG[k])
            except (json.JSONDecodeError, FileNotFoundError, UnicodeDecodeError) as e:
                logger.error("加载配置文件失败: %s", e)
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
        """保存当前配置（排除版本缓存，其另有独立文件）。"""
        keys = [
            "theme", "theme_color", "server_dir", "server_exe",
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
        ]
        data = {k: self.values.get(k, DEFAULT_CONFIG.get(k)) for k in keys}
        os.makedirs(SCRIPT_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        logger.info("配置已保存: %s", os.path.basename(CONFIG_FILE))
        # 版本数据单独存到独立文件
        self._save_version_cache()

    def _save_version_cache(self):
        """保存版本缓存到独立文件（bds_version_cache.json）。"""
        cache = {
            "version_cache": self.values.get("version_cache", {}),
            "version_list": self.values.get("version_list", {}),
        }
        try:
            with open(VERSION_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error("保存版本缓存失败: %s", e)

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


# 全局配置管理器
config_mgr = ConfigManager()
