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
import time
import threading
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

from shared.version import CONFIG_VERSION  # noqa: E402 (after dir setup)


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
            server_dir = cfg.get("server_dir", "")
            if server_dir and os.path.isabs(server_dir):
                return server_dir
            elif server_dir:
                return os.path.join(SCRIPT_DIR, server_dir)
        except (KeyError, TypeError, AttributeError):
            pass  # 用户目录键缺失，降级到默认
    default = os.path.join(SCRIPT_DIR, "Server")
    os.makedirs(default, exist_ok=True)
    return default


# ---------- 服务器路径上下文 ----------
class ServerContext:
    """集中管理所有服务器文件路径，根据 server_type 动态切换 BDS / LL 目录。"""

    def __init__(self, bds_dir: str, ll_dir: str = ""):
        self._bds_dir = bds_dir
        self._ll_dir = ll_dir or bds_dir  # 未配置 LL 则回退到 BDS 目录

    def _active_dir(self) -> str:
        stype = config_mgr.get("server_type", "bds")  # 运行时读取，保证切换即时生效
        return self._ll_dir if stype == "ll" else self._bds_dir

    @property
    def server_dir(self) -> str:
        return self._active_dir()

    @property
    def server_properties(self) -> str:
        return os.path.join(self._active_dir(), "server.properties")

    @property
    def allowlist_file(self) -> str:
        return os.path.join(self._active_dir(), "allowlist.json")

    @property
    def permissions_file(self) -> str:
        return os.path.join(self._active_dir(), "permissions.json")

    @property
    def packet_limit_file(self) -> str:
        return os.path.join(self._active_dir(), "packetlimitconfig.json")

    @property
    def worlds_dir(self) -> str:
        return os.path.join(self._active_dir(), "worlds")

    @property
    def resource_packs_dir(self) -> str:
        return os.path.join(self._active_dir(), "resource_packs")

    @property
    def behavior_packs_dir(self) -> str:
        return os.path.join(self._active_dir(), "behavior_packs")

    @property
    def backup_dir(self) -> str:
        return os.path.join(self._active_dir(), "backups")

    # ── 原始目录访问（脱离 server_type 判断时使用）──
    @property
    def bds_dir(self) -> str:
        return self._bds_dir

    @property
    def ll_dir(self) -> str:
        return self._ll_dir


# 全局上下文实例（惰性加载，由 main.py 显式初始化）
_ctx: ServerContext | None = None


def _resolve_ll_dir(ll_dir: str) -> str:
    """将相对/绝对 LL 目录解析为绝对路径。"""
    if not ll_dir:
        return ""
    if os.path.isabs(ll_dir):
        return ll_dir
    return os.path.join(SCRIPT_DIR, ll_dir)


def init_context(server_dir: str | None = None, ll_dir: str | None = None):
    """初始化全局 ServerContext（支持 BDS + LL 双目录）。"""
    global _ctx
    if server_dir is None:
        server_dir = get_server_dir()
    if ll_dir is None:
        ll_dir = config_mgr.get("ll_server_dir", "")
    ll_abs = _resolve_ll_dir(ll_dir)
    _ctx = ServerContext(server_dir, ll_abs)
    stype = config_mgr.get("server_type", "bds")
    if ll_abs and stype == "ll":
        logger.info("服务器目录: %s (LL: %s)", _ctx._bds_dir, ll_abs)
    else:
        logger.info("服务器目录: %s (%s)", _ctx._bds_dir, "BDS+LL" if stype == "ll" else "BDS")
    os.makedirs(LOG_DIR, exist_ok=True)
    return _ctx


def refresh_context_from_config():
    """根据当前配置重新初始化 ServerContext（用于 server_type 切换后刷新路径）。"""
    bds = get_server_dir()
    ll = config_mgr.get("ll_server_dir", "")
    init_context(bds, ll)


def get_context() -> ServerContext:
    """获取全局 ServerContext（使用前须先调用 init_context）。"""
    if _ctx is None:
        raise RuntimeError("ServerContext 未初始化，请先调用 init_context()")
    return _ctx


# ---------- 默认配置 ----------
DEFAULT_CONFIG = {
    "config_version": CONFIG_VERSION,
    "theme": "light",
    "theme_color": "#0DC5D4",
    "window_background_opacity": 100,  # 窗口透明度 20-100，100=不透明
    "server_dir": "Server",
    "server_exe": _get_default_bedrock_exe_name(),
    "auto_backup_enabled": True,
    "backup_interval": 60,
    "monitor_interval": 2000,
    "backup_keep": 20,
    "backup_min_age_days": 0,
    "online_backup": True,
    "webhook_enabled": True,
    "webhook_url": "",
    "webhook_events": ["backup", "crash", "memory"],
    "frpc_path": "",
    "mem_warn_threshold": 70,
    "max_restart_retries": 5,
    "first_launch_done": False,         # 首次启动引导
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
    "server_root_dir": "",            # lip/BDS 一键部署目标目录
    "ll_server_dir": "",              # LeviLamina 服务器目录（含 bedrock_server_mod.exe）
    "server_type": "bds",             # 服务器类型: "bds" 或 "ll"
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
    "close_to_tray": True,               # 关闭窗口时最小化到托盘
    "high_dpi": False,                  # 高 DPI 缩放适配（125/150/175% 清晰），重启生效
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
    "console_auto_scroll", "close_to_tray", "first_launch_done", "webhook_enabled",
}
# 注意：server_root_dir / ll_server_dir / server_type 是字符串，不是 bool

STR_CHOICES = {
    "theme": {"dark", "light", "auto"},
    "toast_style": {"original", "modern"},
    "server_type": {"bds", "ll"},
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
    if not cfg_ver or cfg_ver != CONFIG_VERSION:
        logger.info("配置迁移: %s → %s", cfg_ver or "未知", CONFIG_VERSION)
        loaded["config_version"] = CONFIG_VERSION  # v3.02.02: 标记已迁移
        # 清理废弃键
        for dead_key in ("window_background",):
            loaded.pop(dead_key, None)
        # 补齐缺失字段
        loaded.setdefault("window_background_opacity", 100)
        loaded.setdefault("close_to_tray", True)
    return loaded


def _merge_loaded_config(loaded: dict) -> dict:
    """迁移、校验并合并一份已解析的配置。"""
    loaded = _migrate_config(dict(loaded))
    config = dict(DEFAULT_CONFIG)
    for key in DEFAULT_CONFIG:
        raw = loaded.get(key, DEFAULT_CONFIG[key])
        config[key] = _validate_value(key, raw)
    # 保留 window_geometry 等不在默认 schema 中、但仍需持久化的扩展字段。
    for key, value in loaded.items():
        if key not in config:
            config[key] = value
    return config


class ConfigManager:
    """配置管理器：读写 bds_manager_config.json。"""

    def __init__(self):
        self.values: dict = {}
        self._history: deque = deque(maxlen=CONFIG_MAX_BACKUPS)
        self._save_timer: threading.Timer | None = None
        self._save_lock = threading.RLock()  # v3.05.00: 保护 save() + timer 并发

    def _schedule_save(self, delay: float = 0.5):
        """延迟保存（防抖）：多次 set 只触发一次落盘。"""
        with self._save_lock:
            if self._save_timer:
                self._save_timer.cancel()
            self._save_timer = threading.Timer(delay, self.save)
            self._save_timer.daemon = True
            self._save_timer.start()

    def save_now(self):
        """立即落盘（关键路径如关闭前）。"""
        with self._save_lock:
            if self._save_timer:
                self._save_timer.cancel()
                self._save_timer = None
        self.save()

    def load(self) -> dict:
        """加载配置，缺失键用 DEFAULT_CONFIG 补全。

        v3.02.01：DEFAULT_CONFIG 迭代后，也把不在白名单中的非标准键（如 window_geometry）
        合并到 config 中，否则 save 能写但 load 读不到。
        """
        config = dict(DEFAULT_CONFIG)
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                config = _merge_loaded_config(loaded)
            except (json.JSONDecodeError, FileNotFoundError, UnicodeDecodeError) as e:
                logger.error("加载配置文件失败: %s", e)
                # 尝试恢复最近一次备份
                restored = self._try_restore_backup()
                if restored is not None:
                    config = _merge_loaded_config(restored)
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
        """原子保存（v3.05.00: RLock 防并发）。"""
        with self._save_lock:
            self._save_inner()

    def _save_inner(self):
        """内部实现：原子写 + 快照 + 版本缓存。"""
        keys = list(DEFAULT_CONFIG.keys())
        for key in self.values:
            if key not in DEFAULT_CONFIG and key not in ("version_cache", "version_list"):
                keys.append(key)
        data = {k: self.values.get(k, DEFAULT_CONFIG.get(k)) for k in keys}
        os.makedirs(SCRIPT_DIR, exist_ok=True)
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    previous = json.load(f)
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                previous = None
            if previous != data:
                self._save_config_snapshot()
        self._atomic_write_json(CONFIG_FILE, data)
        now = time.time()
        if not hasattr(self, "_last_log") or now - self._last_log > 2.0:
            logger.info("配置已保存: %s", os.path.basename(CONFIG_FILE))
            self._last_log = now
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
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
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

    def _try_restore_backup(self) -> dict | None:
        """配置文件损坏时尝试从最新快照恢复，并返回快照内容。"""
        if not os.path.isdir(CONFIG_BACKUP_DIR):
            return None
        snaps = sorted(
            [os.path.join(CONFIG_BACKUP_DIR, f) for f in os.listdir(CONFIG_BACKUP_DIR) if f.endswith(".json")],
            key=os.path.getmtime, reverse=True,
        )
        if not snaps:
            return None
        latest = snaps[0]
        try:
            with open(latest, "r", encoding="utf-8") as f:
                restored = json.load(f)
            if not isinstance(restored, dict):
                raise ValueError("配置快照根节点不是对象")
            shutil.copy2(latest, CONFIG_FILE)
            logger.warning("主配置损坏，已从快照恢复: %s", os.path.basename(latest))
            return restored
        except Exception as e:
            logger.error("快照恢复失败: %s", e)
            return None

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
        """设置配置值并自动延迟落盘（v3.04.03: 防抖保存）。"""
        self.values[key] = value
        self._schedule_save()

    def diff(self, other: dict) -> dict:
        """返回与 other 不同的键（{key: (old, new)}）。用于 UI 高亮变更。"""
        result = {}
        for k in other:
            if self.values.get(k) != other[k]:
                result[k] = (other[k], self.values.get(k))
        return result


# 全局配置管理器
config_mgr = ConfigManager()
