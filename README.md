# BDS Manager Fluent

Minecraft Bedrock Dedicated Server 全功能管理器 —— 基于 **PySide6 + QFluentWidgets Fluent Design**。

[![Version](https://img.shields.io/badge/version-3.03.04-blue)](https://github.com/TussalZeus18028/bds_manager/releases)
[![Python](https://img.shields.io/badge/python-3.10+-green)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-orange)](LICENSE)

---

## 功能

| 页面 | 功能 |
|------|------|
| 仪表盘 | CPU/内存/磁盘实时监控、服务器启停、RTT 延迟检测、崩溃自愈重启 |
| 控制台 | 彩色日志、命令交互（Tab 补全）、命令预设下拉、命令历史持久化、过滤计数、停服后 start 启动 |
| 世界 | 备份列表、手动/自动备份、一键还原（失败回滚）、备份删除、存档大小计算 |
| 资源包 | 资源包/行为包分 Tab 管理，manifest.json 扫描、注��到世界 JSON、详情对话框 |
| 配置 | server.properties 可视化编辑（28 项）、属性预设、白名单/权限管理、重载/重置、端口检测 |
| 升级 | BDS 版本列表 + HEAD 扫描、分支颜色标识（稳定版/预览版）、下载/安装分离、lip 一键 LL 部署 |
| 隧道 | frpc 启动/停止/日志，frpc.ini 编辑、状态指示、模板加载 |
| 关于 | 版本信息 + 相关链接 |
| 设置 | 深浅主题/自定义主色、Toast 通知、Webhook、快捷键自定义、高 DPI、崩溃重启次数、双服务器路径 |

## 快速开始

### 方式一：双击 run.bat

直接双击 `run.bat`，无需任何命令。

### 方式二：命令行启动

```bash
python main.py
```

首次运行会自动安装缺失依赖（PySide6 / qfluentwidgets / psutil）。

### 方式三：从旧版升级

旧版 Manager/ 执行升级后会自动调用 `bds_manager.py`——它会拉取最新 zip 解压覆盖，然后启动新版 main.py。

### 依赖

- Python 3.10+
- PySide6 ≥ 6.5
- qfluentwidgets ≥ 1.5
- psutil

## 项目结构

```
Manager_Fluent/
├── main.py              # 入口（FluentWindow + 托盘 + 主题 + 自更新）
├── bds_manager.py       # 旧版升级桥接（自动下载解压 + 启动 main.py）
├── run.bat              # 启动脚本（双击即用）
├── release.py           # 发布打包脚本
├── archive.py           # 代码快照脚本
├── requirements.txt
├── version.json         # 在线更新版本信息
├── pages/
│   ├── dashboard.py     # 仪表盘
│   ├── console.py       # 控制台
│   ├── console_search.py # 日志搜索/导出
│   ├── world.py         # 世界管理
│   ├── config.py        # 配置编辑
│   ├── packs.py         # 资源包
│   ├── upgrade.py       # 版本升级
│   ├── tunnel.py        # 内网穿透
│   ├── settings.py      # 设置（含快捷键录制）
│   ├── command_palette.py # 命令面板（Ctrl+K）
│   └── about.py         # 关于
├── backend/
│   ├── server.py        # 服务器进程管理（基岩版 save hold/resume）
│   ├── server_lifecycle.py # 服务器生命周期（启停·崩溃自愈·RTT）
│   ├── backup.py        # 备份/还原
│   ├── monitor.py       # 系统资源监控
│   ├── self_update.py   # 工具自更新
│   ├── webhook.py       # Webhook 通知
│   ├── notifications.py # 通知中心
│   ├── network.py       # 网络工具
│   ├── shortcuts.py     # 快捷键管理
│   ├── log_handler.py   # 日志轮转
├── components/
│   ├── notification_panel.py # 通知抽屉 + 铃铛按钮
│   ├── splash.py         # 启动闪屏（圆角·半透明·动画）
│   ├── widgets.py        # 通用组件（NoScrollSpinBox 等）
│   └── key_capture.py   # 键位录制控件
└── shared/
    ├── version.py         # 唯一版本号源
    ├── config.py        # 配置管理（JSON + 迁移 + 备份恢复）
    ├── theme.py          # 主题样式表统一管理
    ├── utils.py          # 通用工具函数
    ├── workers.py       # 线程基类
    ├── toast.py         # 双模式 Toast 通知
    ├── retry.py         # 重试装饰器
    └── errors.py        # 全局异常处理
```

## 近期更新 (v3.03.04)

### 新功能
- 配置 JSON 原生编辑器（白名单/权限）：无边框 Fluent Design + 深浅色 + 半透明
- 高 DPI 缩放适配（设置页开关）
- main.py 启动自动安装缺失依赖

### Bug 修复
- 深色模式持久化 (9处) / 主题最小化 / SSL 证书 / 预设崩溃 / 停止确认 / 滚跳 / 标签截断 / frpc编辑按钮

### 代码质量
- 版本号集中到 shared/version.py / 样式统一到 shared/theme.py / 30+ 异常窄化 / PEP 8 清理

## License

MIT
