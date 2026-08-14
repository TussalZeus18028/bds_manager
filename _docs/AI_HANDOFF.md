# AI 交接文档 — BDS Manager Fluent

> 写给下一个 AI：这份文档告诉你项目结构、工具位置、坑和惯例。读完就能上手。

---

## 项目概要

**Minecraft Bedrock Dedicated Server 全功能桌面管理器**，Windows 为主，已做 Linux 基础兼容。

| 项 | 值 |
|---|-----|
| 语言 | Python 3.12 |
| GUI | PySide6 + QFluentWidgets (Fluent Design) |
| 入口 | `main.py` (双击 `run.bat`) |
| 配置 | `bds_manager_config.json` |
| 当前版本 | 3.04.00 |

---

## 目录结构

```
Manager_Fluent/
├── main.py              # QFluentWindow 主窗口，导航，主题，启动流程
├── pages/               # 9 个页面：dashboard/console/world/packs/config/upgrade/tunnel/settings/about
├── backend/             # 服务器进程、生命周期、备份、Webhook、自更新、lip 工具
├── shared/              # 配置管理(config_mgr)、版本号(version.py)、Toast、主题工具、跨平台工具(utils.py)
├── components/          # 通知面板、可复用 widget
├── tests/               # 单元测试 test_core.py (12 个用例)
├── bds_manager.py       # 旧版命令行启动器
├── release.py           # 发布脚本（打包 + git push + GitHub Release）
├── archive.py           # 本地归档（存 zip 到 archives/）
├── run.bat / run.sh     # 双击启动
├── version.json         # 自更新的版本信息文件
├── bds_manager_config.json  # 用户配置文件
└── bds_version_cache.json   # BDS 版本列表缓存 (24h)
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
GH_TOKEN="ghp_<你的_GitHub_Token>" gh release create v3.04.00 dist/xxx.zip --title "..." --notes "..."
GH_TOKEN="ghp_<你的_GitHub_Token>" gh release delete v3.03.04 --yes
```

**注意：** GitHub Token 在对话中可用 `ghp_<你的_GitHub_Token>`，用户不介意。

---

## 核心架构速览

### 配置系统 (`shared/config.py`)

- `DEFAULT_CONFIG` — 所有默认值
- `BOOL_FIELDS` — 布尔字段白名单（只有 `True/False` 才能通过 `_validate_value`，int 1/0 会被当成非法值回退默认）
- `DEFAULT_RANGE_FIELDS` — 范围校验字段
- `ConfigManager.save()` 有一个**手写的 keys 白名单**（第 332-357 行），新增配置项必须同时加入这个白名单 + `DEFAULT_CONFIG` + 相应的 `BOOL_FIELDS`/`DEFAULT_RANGE_FIELDS`
- `ServerContext._active_dir()` — 根据 `server_type` 返回 BDS 或 LL 目录

**常见坑：** `config_mgr.get("key")` 返回 `None` 时不会触发默认值（key 存在只是值为 None）。防御写法：`config_mgr.get("key") or default_value`

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

---

## 开发流程

### 归档

```bash
cd "E:/Launcher/服务器/Bedrock/Manager_Fluent"
"C:\Users\SudoKernel\AppData\Local\Programs\Python\Python312\python.exe" archive.py --force
```

**规则：** 改代码前先归档。

### 编译检查

```bash
"C:\Users\SudoKernel\AppData\Local\Programs\Python\Python312\python.exe" -m py_compile main.py pages/*.py backend/*.py shared/*.py components/*.py
```

### 运行测试

```bash
cd "E:/Launcher/服务器/Bedrock/Manager_Fluent"
"C:\Users\SudoKernel\AppData\Local\Programs\Python\Python312\python.exe" tests/test_core.py
```

### 发布

```bash
# release.py 会: 打包 → 更新 version.json → git push → GitHub Release
# 但 push 可能失败（缺 SSH），需要手动：
"C:\Program Files\Git\bin\git.exe" push "https://TussalZeus18028:ghp_<你的_GitHub_Token>@github.com/TussalZeus18028/bds_manager.git"

# 创建 Release:
GH_TOKEN="ghp_<你的_GitHub_Token>" gh release create vX.XX.XX dist/bds_manager_vX.XX.XX.zip --title "BDS Manager vX.XX.XX" --notes "..."
```

**注意：** 用户规则是**推送/发布前必须确认**，不要自动推送。

---

## 已知问题 & 惯例

### QFluentWidgets 踩坑记录

1. **`FluentIcon` 属性** — 用之前 `dir(FluentIcon)` 查，`UNDO`/`REFRESH`/`BELL` 等不存在
2. **QThread worker** — 必须存为 `self._xxx` 实例属性，局部变量会被 GC 回收导致进程静默崩溃（最近的「加速源」按钮 crash 就是这个原因）
3. **`MessageBox` 不解析 HTML** — `<b>`/`<i>` 标签会原样显示，用纯文本
4. **`TeachingTip` API** — 本机 1.11.2 版本不支持 `title/content/icon` 参数
5. **Qt 控件类名选择器不可靠** — 用 `QWidget#objectName { ... }` + `setObjectName()`
6. **硬编码颜色** — 必须用 `isDarkTheme()` 三元判断

### 修复历史（v3.04.00）

最近几天修过的问题，避免重蹈：

| 问题 | 根因 |
|------|------|
| `first_launch_done` 不落盘 | save() 白名单缺失 + int 1/0 被 BOOL_FIELDS 拒绝 |
| `cmd_history` 为 None 崩溃 | `config_mgr.get` 返回 None 不触发默认值 |
| Webhook 开关 | 新增 `webhook_enabled` 配置项 |
| 加速源按钮静默崩溃 | LipCmdWorker 局部变量被 GC |
| 配置文件 `<b>` 标签泄漏 | MessageBox 不渲染 HTML |
| 自更新 + 服务器运行死锁 | restart_app 不先停服 |
| BDS 安装路径不管 server_type | `_on_dl_done` 硬编码 bds_dir |
| 升级页双重拉取 | `_fetch()` 无去重 |
| server_root_dir 不落盘 | save 白名单缺失 |
