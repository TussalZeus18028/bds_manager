# BDS Manager Fluent

Minecraft Bedrock Dedicated Server 全功能管理器 —— 基于 **PySide6 + QFluentWidgets Fluent Design**。

[![Version](https://img.shields.io/badge/version-3.05.07-blue)](https://github.com/TussalZeus18028/bds_manager/releases)
[![Python](https://img.shields.io/badge/python-3.10+-green)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-orange)](LICENSE)

---

## 功能

| 页面 | 功能 |
|------|------|
| 仪表盘 | CPU/内存/磁盘/**网络速度**实时监控与曲线、服务器启停、RTT 延迟检测、崩溃自愈重启、后台任务卡 |
| 控制台 | 彩色日志、命令交互（Tab 补全）、命令预设下拉、命令历史持久化、过滤计数 |
| 世界 | 备份列表、手动/自动备份（**全局定时**）、一键还原（失败回滚）、备份删除、存档大小计算 |
| 资源包 | 资源包/行为包分 Tab 管理，manifest.json 扫描、注册到世界 JSON、详情对话框 |
| 配置 | server.properties 可视化编辑（28 项，**保留注释**）、属性预设、白名单/权限管理、重载/重置、端口检测 |
| 升级 | BDS 版本列表 + HEAD 扫描、分支颜色标识、下载/安装分离、lip 一键 LL 部署 |
| 隧道 | frpc 启动/停止/日志，frpc.ini 编辑、状态指示、模板加载 |
| 设置 | 深浅主题/自定义主色、Toast 通知、Webhook、快捷键自定义、高 DPI、双服务器路径 |
| 关于 | 版本信息 + 相关链接 |
| 通知中心 | 铃铛 + 抽屉，**单条删除/未读筛选/时间分组**，点击跳转，已读同步 |
| 命令面板 | Ctrl+K 全局动作搜索 |

## 快速开始

### 双击启动

双击 `run.bat`，自动安装依赖并启动程序。

### 命令行

```bash
python main.py
```

### 依赖

- Python 3.10+
- PySide6 ≥ 6.5
- qfluentwidgets ≥ 1.5
- psutil
- requests

```bash
pip install -r requirements.txt
```

## 项目结构

```
Manager_Fluent/
├── main.py                  # 入口（主窗口 + 系统托盘 + 主题 + 自更新）
├── run.bat / run.sh         # 启动脚本
├── requirements.txt
├── version.json             # 在线更新版本信息
├── pages/                   # UI 页面
│   ├── dashboard.py         # 仪表盘
│   ├── console.py           # 控制台
│   ├── world.py             # 世界管理
│   ├── packs.py             # 资源包
│   ├── config.py            # 配置编辑
│   ├── upgrade.py           # 版本升级
│   ├── tunnel.py            # 内网穿透
│   ├── settings.py          # 设置
│   └── about.py             # 关于
├── backend/                 # 后端逻辑
│   ├── server.py            # 服务器进程管理
│   ├── server_lifecycle.py  # 生命周期（启停·崩溃自愈·RTT）
│   ├── backup.py            # 备份/还原
│   ├── monitor.py           # 系统资源监控
│   ├── self_update.py       # 工具自更新
│   ├── webhook.py           # Webhook 通知
│   ├── notifications.py     # 通知中心
│   └── shortcuts.py         # 快捷键管理
├── components/              # 可复用组件
│   ├── notification_panel.py # 通知抽屉
│   ├── splash.py             # 启动闪屏
│   └── widgets.py            # 通用控件
└── shared/                  # 共享基础设施
    ├── config.py            # 配置管理
    ├── theme.py             # 主题样式
    ├── toast.py             # Toast 通知
    ├── errors.py            # 错误处理
    └── utils.py             # 工具函数
```

## v3.05.07 (2026-11-25)

### Bug 修复
- **自更新重启崩溃**：`threading.Timer` 的签名是 `(interval, function, args, kwargs)`，**没有 `daemon` 参数**（那是 `Thread` 的）→ v3.05.06 的 `restart_app` 每次自更新都抛 `TypeError`，`os._exit` 兜底从未生效，且弹"程序遇到未预期错误"
- **自更新失败无法自救**：新进程若启动即崩溃（旧代码本身有 bug），旧进程会被无条件强杀 → 用户彻底打不开程序。现在改为检测子进程状态并**从备份自动回滚**（`backups/upgrade_backup_*`）
- **winget 安装 lip 可能永久卡死**：缺 `--accept-package-agreements` / `--disable-interactivity`，winget 会停在 EULA 交互界面 → 补全非交互参数 + 240 秒超时 + 可取消
- **版本列表拉取无降级**：`raw.githubusercontent.com` 偶发超时/502 时静默失败 → 增加 GitHub Contents API 备用源，失败日志从 debug 提升到 warning

### 新增
- 设置页 / 升级页显示 **lip 版本号**（`lip -v`）
- lip 镜像地址统一为 `MIRROR_CMDS` 常量，移除重复定义

### 改进
- **BDS 版本嗅探支持跨 minor**：旧逻辑只探同一 minor，官方发大版本时 patch 号会跳到 60+/70+（如 `1.26.43.1` → `1.26.70.x`），探测范围完全够不着 → 现在依次探测同 patch 大 build、更高 patch、以及下一个 minor 的开头
- 版本列表数据已更新至 **373 个版本**（含 stable / preview 双通道）

## v3.05.06 (2026-11-25)

### Bug 修复
- **自更新重启残留双窗口**：更新安装完成后改为**强制停服**（`force_stop_for_update`，不等待优雅关停）+ `restart_app` 增加 2.5 秒 `os._exit(0)` 兜底——`QApplication.quit()` 在极端情况未生效时强制结束旧进程，杜绝新旧窗口并存

## v3.05.05 (2026-11-25)

### Bug 修复
- **自更新下载失败**：`DownloadUpdateWorker` 用 requests（certifi CA）在代理/自签根证书环境报 `SSL: CERTIFICATE_VERIFY_FAILED` → 改用 **urllib（系统证书库）** 下载（与 BDS 版本下载一致），已实测真实下载 + SHA256 校验通过

### 新增
- 设置页 → 其他 → **"立即检查更新"按钮**（强制重新检查，绕过会话内一次性检查；检查中禁用，完成后恢复）

## v3.05.04 (2026-11-25)

### Bug 修复
- **自更新崩溃**：点击更新确认后 `_start_self_update_download` 抛 `NameError: toast_info`（main.py 未导入）→ 更新中断并弹"程序遇到未预期错误"
- lip 安装输出跨线程直接操作 UI（lambda 无 QObject 接收者）→ 改为方法槽（QueuedConnection）

## v3.05.03 (2026-11-25)

### Bug 修复
- 升级页下载确认框"一次性跳过"后永不恢复（误触风险）
- 控制台搜索"上一个"按钮导航错乱（QTextDocument.find 只支持向前）
- 备份元数据 `bds_version` 误存工具版本 → 改为从控制台日志解析真实 BDS 版本；`tool_version` 改用真实版本号
- frpc.ini 启动时重复保存两次
- frpc 主动停止后迟到退出信号误弹"意外退出"提示
- frpc 路径为空时 frpc.ini 写到当前工作目录
- lip 升级命令错误：`lip install --upgrade`（不存在）→ `lip update <pkg>`
- lip 安装 winget 输出被丢弃 → 接入终端日志
- LL 部署目录存成 `../..` 相对路径 → 绝对路径
- 快捷键录制态/命令面板边框硬编码主色 → 跟随 theme_color

### 增强
- **自更新备份增强**：升级前递归备份 `pages/backend/shared/components` 子目录代码（此前只备份根目录，升级后无法回滚子目录）
- 新增通用文本编辑器组件 `components/text_editor_dialog.py`（无边框圆角/半透明/主题感知/Ctrl+S），白名单编辑器改用该组件
- 新增 `_docs/UI_STYLE.md` UI 风格规范（主题/控件选型/弹窗/布局/图标/自检清单）

### 清理
- 删除根目录冗余 allowlist.json（代码零引用）、旧 dist 包与旧日志

## v3.05.02 (2026-08-25)

### 修复
- 通知中心单条"已读"永久失效（存储键不匹配）+ 已读蓝点残留
- 备份页"服务器正在停止"时按钮卡死、进度条空转
- 还原中提示一闪而过
- **自动备份依赖世界页显示**：从不打开"世界"页则永不备份 → 全局定时启动
- 仪表盘备份倒计时与实际定时器不同步
- 磁盘监控显示程序盘而非服务器所在盘
- 配置保存丢弃 server.properties 全部注释 → 行级保留
- 日志 gzip 轮转链断裂（backupCount 失效，旧 .gz 永不轮换）
- 服务器未运行时的命令误入历史
- 版本列表"稳定版/预览版"列宽不足被截断
- 移除 `bds_manager.py` shim 的全局 SSL 验证绕过（安全）

### 增强
- 仪表盘新增**网络速度双线曲线**（上行/下行）
- 通知中心：**单条删除**（hover ✕）、**未读/已读筛选**、**时间分组**（今日/昨日/本周/更早）
- 备份间隔修改**即时生效**（无需重启）
- 闪屏跟随主题主色 + auto 主题按系统判断
- 全项目 emoji 替换为 **QFluentWidgets 矢量图标**（FluentIcon）

### 其他
- 测试防抖 timer 泄漏修复 + 清理已污染配置
- 归档脚本等 CLI 输出改为纯文本标记（修复 Windows GBK 控制台编码错误）

## v3.05.01 (2026-08-25)

### 安全
- 移除 `bds_manager.py`（旧版入口/智能更新 shim）的全局 SSL 验证绕过，与 main.py v3.04.03 安全基线对齐

### Bug 修复
- 修复测试防抖保存 timer 泄漏临时键到真实配置（`__test_temp_key__`），并清理已污染的配置
- 测试改为直接赋值 values，杜绝 timer 在测试上下文外触发写盘

### 文档
- PROJECT_SUMMARY.md 同步至 v3.05.00+ 实际架构（补全 backend/upgrade_workers、lip_utils、notifications、shortcuts 等）
- _docs/AI_HANDOFF.md 更新版本/结构/测试数（25 用例）/踩坑记录

## v3.05.00 (2026-08-01)

### 安全
- 移除全局 SSL 验证绕过
- ZipSlip 防护改用 `commonpath()` 消除边界绕过

### Bug 修复
- 崩溃倒计时期间点停止正确取消重启
- `send_save_all()` 不再阻塞 GUI 线程
- frpc 进程孤儿兜底 kill + 意外退出 UI 同步
- 端口检测异步化（不再卡死 GUI + 对话框不响应）
- stdout 重定向 try/finally 保护
- 下载失败清理半成品文件

### 体验
- **全页面触控适配** — QScroller 惯性滚动（10 页面 + 通知抽屉 + 资源包表格）
- 命令面板全新设计：可拖动、深色适配、半透明、plaintext_style 搜索框
- 本地回环免除命令 (`CheckNetIsolation LoopbackExempt`)
- 控制台过滤器按钮布局修复
- X 按钮退出确认框

### 架构
- `config_mgr.set()` 防抖自动落盘 — 任何设置变更 0.5s 后自动持久化
- 关闭逻辑还原旧版 — `QApplication.quit()` 绕过 closeEvent 避免托盘冲突
- 测试 20 → 25 用例

## License

MIT
