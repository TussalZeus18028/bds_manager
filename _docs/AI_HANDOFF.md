# AI 交接文档 — BDS Manager Fluent

> 写给下一个 AI：这份文档告诉你项目结构、工具位置、坑和惯例。读完就能上手。
> 最后同步: 2026-08-25（v3.05.00 + 08-14 补丁）。

---

## 项目概要

**Minecraft Bedrock Dedicated Server 全功能桌面管理器**，Windows 为主，已做 Linux 基础兼容。

| 项 | 值 |
|---|-----|
| 语言 | Python 3.10+（开发用 3.12） |
| GUI | PySide6 + QFluentWidgets (Fluent Design) |
| 入口 | `main.py` (双击 `run.bat`) |
| 配置 | `bds_manager_config.json` |
| 当前版本 | 3.05.00 |

---

## 目录结构

```
Manager_Fluent/
├── main.py              # QFluentWindow 主窗口，导航，主题，启动流程，快捷键
├── run.bat / run.sh     # 启动脚本
├── release.py           # 发布脚本（打包 + git push + GitHub Release）
├── archive.py           # 本地归档（存 zip 到 archives/，内容哈希智能跳过）
├── bds_manager.py       # 旧版入口伪装 + 智能更新 shim（可独立运行，无 PySide6 依赖）
├── requirements.txt
├── version.json         # 自更新的版本信息文件
├── pages/               # UI 页面
│   ├── dashboard.py     # 仪表盘（资源曲线/状态卡/BDS进程卡/快捷操作）
│   ├── console.py       # 控制台（ANSI解析/玩家追踪/命令历史）
│   ├── console_search.py# 控制台搜索工具栏
│   ├── command_palette.py # 命令面板 (Ctrl+K)
│   ├── world.py         # 世界管理（备份/还原）
│   ├── packs.py         # 资源包
│   ├── config.py        # 配置编辑
│   ├── upgrade.py       # 版本升级 + lip 部署
│   ├── tunnel.py        # 内网穿透 (frpc)
│   ├── settings.py      # 设置
│   └── about.py         # 关于
├── backend/             # 后端逻辑（纯 QThread，无 Widget 依赖）
│   ├── server.py        # ServerProcess: 子进程/输出/进程监控/优雅停服
│   ├── server_lifecycle.py # 启停/崩溃自愈/RTT/资源告警（ServerHost 协议）
│   ├── backup.py        # 备份/还原（在线 save-hold、失败回滚）
│   ├── monitor.py       # 系统资源监控
│   ├── self_update.py / self_update_ui.py  # 工具自更新
│   ├── upgrade_workers.py # BDS 版本嗅探/下载/安装 Worker
│   ├── lip_utils.py     # lip 检测/镜像/部署
│   ├── webhook.py       # Webhook 通知（队列化）
│   ├── notifications.py # 通知中心（notify 单写）
│   ├── shortcuts.py     # 快捷键管理
│   ├── log_handler.py   # gzip 轮转日志
│   └── network.py       # 端口检测
├── components/          # 可复用组件
│   ├── notification_panel.py # 铃铛 + 通知抽屉
│   ├── splash.py        # 启动闪屏
│   ├── key_capture.py   # 快捷键捕获
│   └── widgets.py       # 通用控件
├── shared/              # 共享基础设施（无 Qt 依赖）
│   ├── config.py        # 配置管理（ConfigManager + ServerContext）
│   ├── version.py       # 唯一版本号源（改版本只改这里）
│   ├── theme.py         # ThemePalette + scrollbar_style()
│   ├── toast.py         # Toast 通知
│   ├── errors.py        # 错误处理桥接
│   ├── retry.py         # 重试工具
│   ├── utils.py         # bds_exe()/ll_exe()/is_linux()
│   └── workers.py       # BaseWorker(QThread)
├── tests/test_core.py   # 单元测试（25 用例）
├── _docs/               # 交接文档 + 对话框样式规范
├── bds_manager_config.json  # 用户配置文件（不入库）
└── bds_version_cache.json   # BDS 版本列表缓存 (48h)
```

---

## 工具清单

### 1. 代码质量审计工具 - fuck-u-code

**位置：** `C:\Users\SudoKernel\.workbuddy\binaries\node\versions\22.22.2\fuck-u-code.cmd`

**用法：**
```bash
"C:\Users\SudoKernel\.workbuddy\binaries\node\versions\22.22.2\fuck-u-code.cmd" analyze "E:/Launcher/服务器/Bedrock/Manager_Fluent" --top 20 --locale zh --format txt
```

**说明：** 自动化代码复杂度/错误处理/命名/重复度分析。跑一次约 2-3 秒。输出 0-100 分和一个「最屎代码排行榜」。

### 2. 系统 Git（完整版，支持 HTTPS）

**位置：** `C:\Program Files\Git\bin\git.exe`

**说明：** WorkBuddy 自带的 MinGW Git 缺少 `remote-https` helper，push 必须用这个。所有 git 操作加 `"C:\Program Files\Git\bin\git.exe"` 前缀。

```bash
# 示例
"C:\Program Files\Git\bin\git.exe" status
"C:\Program Files\Git\bin\git.exe" push
```

### 3. 系统 Python（用于 pip/脚本）

**位置：** `C:\Users\SudoKernel\AppData\Local\Programs\Python\Python312\python.exe`

**说明：** 用户的系统 Python，不要用 WorkBuddy 管理的沙箱 venv。`pip install` 走这个。

### 4. GitHub CLI

**位置：** `C:\Program Files\GitHub CLI\gh`（在 Git Bash PATH 中可用 `gh`）

**用法：**
```bash
GH_TOKEN="ghp_<你的_GitHub_Token>" gh release create v3.05.00 dist/xxx.zip --title "..." --notes "..."
GH_TOKEN="ghp_<你的_GitHub_Token>" gh release delete v3.03.04 --yes
```

**注意：** GitHub Token 在对话中可用 `ghp_<你的_GitHub_Token>`，用户不介意。

---

## 核心架构速览

### 配置系统 (`shared/config.py`)

- `DEFAULT_CONFIG` — 所有默认值；`SCHEMA` — 数值范围校验；`BOOL_FIELDS` — 布尔白名单；`STR_CHOICES` — 枚举白名单
- **白名单自动推导**（v3.04.01 起）：`save()` 遍历 `DEFAULT_CONFIG` keys + `self.values` 中的扩展键，新增配置项只需加 `DEFAULT_CONFIG` + 相应校验集合，**不再需要手写 keys 白名单**
- `ConfigManager.set()` 防抖 0.5s 自动落盘（v3.05.00）；`save()` 原子写（tmp+fsync+replace）+ RLock 防并发；快照回滚保留 5 份到 `backups/config/`；损坏自动从快照恢复
- `ServerContext._active_dir()` — 根据 `server_type` 返回 BDS 或 LL 目录

**常见坑：** `config_mgr.get("key")` 返回 `None` 时不会触发默认值（key 存在只是值为 None）。防御写法：`config_mgr.get("key") or default_value`

**历史事故：** `__test_temp_key__` 曾泄漏进真实配置 —— 测试里 `set()` 创建的 0.5s 延迟保存 timer 在 patch 上下文退出后触发，把临时键写进 `bds_manager_config.json`。修复：测试直接赋值 `manager.values[...]` 不触发 timer。**新写测试时注意：涉及 ConfigManager 的测试要么不用 set()，要么保证 cancel_pending_save()。**

### 版本号源

- `shared/version.py` 是**唯一版本号源**（VERSION / VERSION_INFO / CONFIG_VERSION / RELEASE_DATE）
- 发版流程：改 `shared/version.py` → `python release.py`

### 双服务器 (`server_type`)

- `server_type = "bds"` → 纯 BDS，目录 `Server/`，exe `bedrock_server.exe`
- `server_type = "ll"` → BDS + LeviLamina，目录 `LLServer/`，exe `bedrock_server_mod.exe`
- `_active_dir()` 和 `get_context()` 的 all properties 都会自动根据 `server_type` 切换目录
- `shared/utils.py` 提供 `bds_exe()` / `ll_exe()` / `is_linux()` 跨平台工具

### 跨平台

- Windows: `sys.platform == "win32"`
- Linux: `sys.platform == "linux"` → 升级页不显示版本表格，隧道不可用
- `server.py` 在 Linux 下自动设 `LD_LIBRARY_PATH=`
- `shared/utils.py` 的 `bds_exe()` 返回 `bedrock_server.exe`(Win) / `bedrock_server`(Linux)

### Toast 通知 (`shared/toast.py`)

```python
toast_success("标题", "详情", parent_widget)
toast_error("标题", "详情", parent_widget)
toast_warning("标题", "详情", parent_widget)
toast_info("标题", "详情", parent_widget)
```

所有 toast 自动写入 `notifications` 到通知中心。

### 通知中心 (`backend/notifications.py`)

- `notify(level, category, title, body, target)` 是唯一写入入口（单写，v3.04.01 修复双写）
- 抽屉在 `components/notification_panel.py`，数据存 `bds_manager_notifications.json`

---

## 开发流程

### 归档（改代码前必做）

```bash
cd "E:/Launcher/服务器/Bedrock/Manager_Fluent"
$env:PYTHONIOENCODING="utf-8"  # Windows 控制台必需，否则 emoji 报 GBK 编码错
"C:\Users\SudoKernel\AppData\Local\Programs\Python\Python312\python.exe" archive.py --force --label <标签>
```

**规则：** 改代码前先归档。`--force` 强制创建；内容哈希相同会跳过。

### 编译检查

```bash
"C:\Users\SudoKernel\AppData\Local\Programs\Python\Python312\python.exe" -m py_compile main.py pages/*.py backend/*.py shared/*.py components/*.py bds_manager.py archive.py release.py
```

### 运行测试

```bash
cd "E:/Launcher/服务器/Bedrock/Manager_Fluent"
"C:\Users\SudoKernel\AppData\Local\Programs\Python\Python312\python.exe" tests/test_core.py
```

当前 25 个用例：备份/配置快照/SHA256/Webhook/生命周期/世界选择/主题/ANSI解析/配置白名单/ZipSlip/重启取消/下载清理。

### 发布

```bash
# release.py 会: 打包 → 更新 version.json → git push → 推 tag → GitHub Release + 上传 zip
"C:\Users\SudoKernel\AppData\Local\Programs\Python\Python312\python.exe" release.py
```

**注意：** 用户规则是**推送/发布前必须确认**，不要自动推送。push 若失败（缺 SSH helper），手动：
```bash
"C:\Program Files\Git\bin\git.exe" push "https://TussalZeus18028:ghp_<你的_GitHub_Token>@github.com/TussalZeus18028/bds_manager.git"
```

---

## 已知问题 & 惯例

### QFluentWidgets 踩坑记录

1. **`FluentIcon` 属性** — 用之前 `dir(FluentIcon)` 查，`UNDO`/`REFRESH`/`BELL` 等不存在
2. **QThread worker** — 必须存为 `self._xxx` 实例属性，局部变量会被 GC 回收导致进程静默崩溃（「加速源」按钮 crash 就是这个原因）
3. **`MessageBox` 不解析 HTML** — `<b>`/`<i>` 标签会原样显示，用纯文本
4. **`TeachingTip` API** — 本机 1.11.2 版本不支持 `title/content/icon` 参数
5. **Qt 控件类名选择器不可靠** — 用 `QWidget#objectName { ... }` + `setObjectName()`
6. **硬编码颜色** — 必须用 `theme_palette()`（ThemePalette），禁止手写 `isDarkTheme()` 三元

### 修复历史（最近版本）

| 问题 | 根因 / 修复 |
|------|------------|
| `first_launch_done` 不落盘 | save() 白名单缺失 + int 1/0 被 BOOL_FIELDS 拒绝（v3.04.00） |
| 自更新 + 服务器运行死锁 | restart_app 不先停服（v3.04.00） |
| 配置防抖 timer 泄漏测试键 | 测试直接赋值 values，不走 set() 的 timer（v3.05.01 补丁） |
| 测试污染真实配置 | 测试加 save_now + cancel_pending_save 双保险（08-14 commit 465a642） |
| 任意退出路径丢配置 | `app.aboutToQuit.connect(config_mgr.save_now)`（08-14 commit 4a3cf43） |
| 全局 SSL 绕过 | main.py v3.04.03 移除；**bds_manager.py shim 于 v3.05.01 移除** |
| ZipSlip 边界绕过 | `startswith()` → `commonpath()`（v3.04.03） |
| save() 并发写入冲突 | RLock 保护（v3.05.00） |
| 端口检测卡 GUI | 异步化（v3.04.03） |
| 崩溃倒计时期间点停止 | 可追踪 QTimer 供 stop_server 取消（v3.04.03） |
