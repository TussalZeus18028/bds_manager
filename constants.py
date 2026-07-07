# constants.py — BDS Manager 配置常量集中管理
# pylint: skip-file

# --- 版本扫描范围 ---
DEFAULT_SCAN_PATCH_RANGE = 40   # 稳定版 Patch 序号扫描范围
DEFAULT_SCAN_BUILD_RANGE = 30   # 预览版 Build 序号扫描范围

# --- 下载引擎 ---
DEFAULT_DL_SEGMENTS = 4          # 多线程下载默认分段数
HEAD_SCAN_BATCH_SIZE = 16        # HEAD 并发批次大小
HEAD_SCAN_MAX_WORKERS = 10       # HEAD 扫描最大线程数
HEAD_SCAN_TIMEOUT = 6            # 单个 HEAD 请求超时（秒）

# --- 备份 ---
DEFAULT_BACKUP_INTERVAL = 60     # 自动备份间隔（分钟）
DEFAULT_BACKUP_KEEP = 20         # 保留最近 N 个备份

# --- 监控 ---
DEFAULT_MONITOR_INTERVAL = 2000  # 仪表盘刷新间隔（毫秒）
DEFAULT_MEM_WARN_THRESHOLD = 80  # 内存告警阈值（%）
DASHBOARD_REFRESH_HISTORY = 60   # 资源历史数据点数量

# --- 网络 ---
DEFAULT_REQUEST_TIMEOUT = 30     # HTTP 请求默认超时（秒）
GITHUB_API_TIMEOUT = 15          # GitHub API 请求超时（秒）
TOAST_QUEUE_DELAY_DEFAULT = 200  # Toast 队列间隔（毫秒）

# --- UI ---
DEFAULT_WINDOW_WIDTH = 1200
DEFAULT_WINDOW_HEIGHT = 800
