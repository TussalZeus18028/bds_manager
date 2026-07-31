# BDS Manager Fluent

Minecraft Bedrock Dedicated Server 全功能管理器 —— 基于 **PySide6 + QFluentWidgets Fluent Design**。

[![Version](https://img.shields.io/badge/version-3.04.02-blue)](https://github.com/TussalZeus18028/bds_manager/releases)
[![Python](https://img.shields.io/badge/python-3.10+-green)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-orange)](LICENSE)

---

## 功能

| 页面 | 功能 |
|------|------|
| 仪表盘 | CPU/内存/磁盘实时监控、服务器启停、RTT 延迟检测、崩溃自愈重启 |
| 控制台 | 彩色日志、命令交互（Tab 补全）、命令预设下拉、命令历史持久化、过滤计数 |
| 世界 | 备份列表、手动/自动备份、一键还原（失败回滚）、备份删除、存档大小计算 |
| 资源包 | 资源包/行为包分 Tab 管理，manifest.json 扫描、注册到世界 JSON、详情对话框 |
| 配置 | server.properties 可视化编辑（28 项）、属��预设、白名单/权限管理、重载/重置、端口检测 |
| 升级 | BDS 版本列表 + HEAD 扫描、分支颜色标识、下载/安装分离、lip 一键 LL 部署 |
| 隧道 | frpc 启动/停止/日志，frpc.ini 编辑、状态指示、模板加载 |
| 设置 | 深浅主题/自定义主色、Toast 通知、Webhook、快捷键自定义、高 DPI、双服务器路径 |
| 关于 | 版本信息 + 相关链接 |

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

## 近期更新 (v3.04.02)

- 代码质量：修复通知双写、新增 ThemePalette 统一主题颜色、ConfigManager 白名单自动推导
- 稳定性：修复 lambda 析构警告、ANSI 解析器拆分、自更新 UI 提取
- 测试覆盖从 12 个用例提升至 20 个

## License

MIT
