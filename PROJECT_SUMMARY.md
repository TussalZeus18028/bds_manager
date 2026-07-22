# BDS Manager Fluent —— 项目全貌

> **版本**: v3.0.1 | **日期**: 2026-07-22 | **仓库**: `TussalZeus18028/bds_manager` (main 分支)
>
> 从旧版 PyQt5 单体文件 (~7500 行) 完全重写为 PySide6 + QFluentWidgets 模块化架构。

---

## 项目位置

```
E:\Launcher\服务器\Bedrock\Manager_Fluent\    ← 新 Fluent 版（当前主分支）
E:\Launcher\服务器\Bedrock\Manager\            ← 旧 PyQt5 版（保留作参考）
```

备份: `Manager/backups/pre_refactor_20260722_180356/`（重构前的完整快照） + `bds_manager.py.bak_174752`

---

## 技术栈

| 项 | 选择 |
|----|------|
| GUI 框架 | PySide6 (Qt for Python) |
| UI 组件库 | QFluentWidgets (Fluent Design) |
| 线程 | PySide6.QtCore.QThread + Signal (不卡 GUI) |
| 图标 | FluentIcon (矢量) 替代 emoji |
| 打包 | Python zipfile + GitHub API |
| 运行环境 | Python 3.12 受管 venv (`envs/fluent/`) |
| 依赖 | `requirements.txt` — PySide6, PySide6-Fluent-Widgets, requests, psutil |

---

## 文件结构

```
Manager_Fluent/
├── main.py                  # 入口: FluentWindow + 系统托盘 + 自更新 + 主题
├── run.bat                  # 一键启动
├── release.py               # 发布打包脚本
├── README.md                # GitHub 首页介绍
├── requirements.txt
├── version.json             # 在线更新版本信息
├── constants.py             # 从旧项目拷贝
│
├── pages/                   # UI 页面（每页一个文件）
│   ├── dashboard.py         # 仪表盘: 启停/CPU/内存/磁盘/RTT/快捷跳转
│   ├── console.py           # 控制台: 彩色日志/玩家追踪/命令历史/日志落盘
│   ├── console_search.py    # 控制台搜索/导出/清屏工具栏
│   ├── world.py             # 世界: 备份列表/手动/自动备份/还原/删除/世界详情
│   ├── config.py            # 配置: 28属性可视化编辑/端口检测/默认文件创建
│   ├── packs.py             # 资源包: 行为包/资源包添加移除/manifest扫描
│   ├── upgrade.py           # 升级: GitHub版本列表+HEAD扫描/缓存/下载安装
│   ├── tunnel.py            # 隧道: frpc启停/日志着色/ini编辑锁定/模板
│   ├── settings.py          # 设置: 主题/主色/Toast双模式/Webhook/GitHub/备份参数
│   └── about.py             # 关于: 版本号+4个外部链接
│
├── backend/                 # 后端逻辑（纯 QThread，无 Widget 依赖）
│   ├── server.py            # ServerProcess: 子进程管理/输出/错误/停服
│   ├── backup.py            # BackupWorker + RestoreWorker: 备份/还原/回滚
│   ├── monitor.py           # SystemResourceMonitor: CPU/内存/磁盘采集
│   ├── self_update.py       # CheckUpdate/DownloadUpdate/InstallUpdate Worker
│   ├── webhook.py           # send_webhook: Discord/企业微信/自定义URL
│   └── network.py           # 端口检测 + 网络错误中英双语提示
│
└── shared/                  # 共享基础设施（可被 backend 安全导入）
    ├── config.py            # ConfigManager: load/save/get/set + ServerContext
    ├── workers.py           # BaseWorker(QThread) + SimpleWorker
    └── toast.py             # 双模式 Toast: 原版(圆角滑入排队) / 现代(InfoBar)
```

---

## 完整功能清单

### 页面 (9 个)
| 页面 | 图标 | 核心功能 |
|------|------|---------|
| 仪表盘 | HOME | 启停按钮、CPU/内存/磁盘/RTT 实时显示、快捷跳转 |
| 控制台 | COMMAND_PROMPT | 彩色日志(ERROR红/WARN橙/玩家绿/聊天金/IP蓝/UUID紫)、命令发送、玩家进出追踪、上下箭头命令历史、搜索/导出/清屏、日志自动落盘 |
| 世界 | SAVE | 备份表格(文件名/大小/时间)、手动备份、自动备份定时器、一键还原(失败回滚)、备份删除、世界详情(名称/种子/难度/磁盘大小) |
| 资源包 | FOLDER | 行为包/资源包分Tab、manifest.json扫描、添加/移除 |
| 配置 | EDIT | 28 项 server.properties 可视化编辑(text/int/bool/combo)、端口检测、自动创建默认配置文件 |
| 升级 | UPDATE | GitHub版本列表 + Minecraft CDN HEAD扫描、版本缓存(bds_version_cache.json)、下载进度条、安装(ZipSlip防护) |
| 隧道 | LINK | frpc路径设置、启停、日志着色输出、frpc.ini编辑器(锁定/模板/加载/打开目录) |
| 关于 | INFO | 版本号 + GitHub/BDS/ChmlFrp/版本数据库链接 |
| 设置 | SETTING | 主题(dark/light/auto)+主色调、服务器路径、备份参数、Toast(原版/现代二选一+透明度+时长+排队延迟)、Webhook(URL+备份/崩溃/内存事件)、GitHub Token认证、自动更新/多线程下载/内存告警阈值/崩溃重启次数/关闭行为 |

### 系统功能
- **系统托盘**: 最小化到托盘、双击恢复、右键退出
- **主题定制**: `apply_theme(theme, accent_color)` 全局6px现代细滚动条
- **启动自检**: 5个Toast依次弹出(目录/可执行文件/资源/备份/版本就绪)
- **崩溃自愈**: N次自动重启 + 超限后保存崩溃日志
- **RTT延迟**: 每30秒list命令探测，仪表盘绿色/橙色/红色��示
- **内存告警**: Toast+终端+Webhook三重通知，30秒冷却
- **工具自更新**: GitHub API检查 → 下载 → SHA256校验 → 备份 → 解压覆盖 → 重启
- **Ctrl+Shift+R**: 快速重启应用
- **关闭行为**: 可配置X最小化到托盘或直接退出

### 后端能力
- **ServerProcess**: 子进程管理，输出 Signal 投递到主线程
- **BackupWorker**: 备份世界(在线save hold模式)，zip+testzip校验
- **RestoreWorker**: 还原世界，失败自动回滚
- **SystemResourceMonitor**: QTimer采集CPU/内存/磁盘，Signal推送SystemStatsSnapshot
- **CheckUpdateWorker/DownloadUpdateWorker/InstallUpdateWorker**: 工具自更新三阶段
- **FetchVersionsWorker/InstallWorker**: BDS版本嗅探+安装
- **PortScanner**: UDP端口检测+空闲端口推荐
- **FrpcReader(QThread)**: frpc输出流读取
- **CopyPackWorker(QThread)**: 资源包目录拷贝

---

## 关键设计决策

1. **`setStyleSheet` 只用于暗色控件**，不在亮色主题下覆盖 Fluent 默认亮色样式
2. **backend/ 与 shared/ 无 Widgets 依赖**：ServerContext惰性初始化，Worker线程安全
3. **双模式 Toast**：`toast_style = "original"` → 完全照搬旧版圆角滑入排队动画；`"modern"` → QFluentWidgets InfoBar
4. **版本缓存独立文件**：`bds_version_cache.json`，启动即出列表，后台静默更新
5. **Token 存储**：XOR+base64 混淆存储于配置文件，使用时反混淆
6. **配置文件不入版本库**：`.gitignore` 排除 `bds_manager_config.json`（含Token）
7. **ScrollArea 包裹每个页面**：`wrap_scrollable()` 统一模板，控件多时自动可��

---

## 已修复的关键Bug（v2.1.1.12 旧版审查发现）

所有16项旧版Bug已验证修复落地：
- 子包 pack_id 匹配、列表 json.loads 回写、解压子目录 ZipSlip 防护
- 中文乱码（读写编码双向统一）、自动备份后台化、还原失败回滚
- 控制台批量刷新+HTML转义+5000行上限、玩家列表变更检测、右键菜单去重
- TPS死字段清理、server_stats冗余写入清理、解码死分支修复
- 关闭逻辑（托盘不可用时真正退出）、备份轮转（只清理 auto_ 前缀）
- 隧道日志 HTML 转义+行数上限（对齐控制台修复）
- 版本探测 memoize（不再每2秒扫描）

## 仍然保留的特性

**旧 PyQt5 版**仍在 `Manager/bds_manager.py` 保留，作为参考。新旧两个版本共享同一份 `bds_manager_config.json`。

---

## 发布与版本历史

| 版本 | 日期 | 内容 |
|------|------|------|
| v3.0.0 | 07-22 | Fluent UI 完整重写，8页面侧边栏，双模式Toast，工具自更新 |
| v3.0.1 | 07-22 | 控制台日志落盘+命令历史+搜索导出，世界详情，崩溃自愈+RTT，隧道编辑锁定，配置默认创建，关于页，UI美化，6px细滚动条 |

## 发布方式

```bash
python release.py
```

自动打包 → 计算SHA256 → 更新version.json → 推送到GitHub Release。

---

## 当前状态 & 后续建议

**已完成**: 核心功能全部迁移，9个页面完整可用，GitHub Release v3.0.1 已发布。

**可继续完善** (旧版仍有但新版未实现):
- 在线备份 save hold/resume 流程（当前只有简单备份）
- 控制台日志文件日期轮转（当前一个session一个文件）
- 资源包详情对话框 (PackInfoDialog)
- 配置页"保存并应用"（当前保存后需手动重启服务器）
- 仪表盘"最近备份时间"实时更新
- 更多 FluentIcon 细节图标优化
