# BDS Manager Fluent

Minecraft Bedrock Dedicated Server 全功能管理器 —— 基于 **PySide6 + QFluentWidgets Fluent Design**。

[![Version](https://img.shields.io/badge/version-3.03.04-blue)](https://github.com/TussalZeus18028/bds_manager/releases)
[![Python](https://img.shields.io/badge/python-3.10+-green)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-orange)](LICENSE)

---

## 功能

| 页面 | 功能 |
|------|------|
| 🏠 仪表盘 | CPU/内存/磁盘实时监控、服务器启停、RTT 延迟检测、崩溃自愈重启、备份倒计时 |
| ⌨️ 控制台 | 彩色日志、命令交互（20+ 基岩版命令补全）、玩家进出追踪、右键菜单、搜索/导出 |
| 💾 世界 | 备份列表、手动/自动备份、一键还原（失败回滚）、备份删除、存档大小计算 |
| 📁 资源包 | 资源包/行为包分 Tab 管理，manifest.json 扫描、注册到世界 JSON、详情对话框 |
| ✏️ 配置 | server.properties 可视化编辑（28 项属性）、属性预设、白名单/权限管理 |
| 🔄 升级 | GitHub 版本列表 + HEAD 扫描、分支颜色标识（稳定版 🟢 / 预览版 🟠）、文件大小获取 |
| 🔗 隧道 | frpc 启动/停止/日志，frpc.ini 编辑锁定、模板加载 |
| ℹ️ 关于 | 版本信息 + 相关链接 |
| ⚙️ 设置 | 深色/浅色主题、自定义主色、Toast 通知样式、Webhook 集成、快捷键录制、窗口透明度 |

## 快速开始

### 方式一：一键启动

```bash
python bds_manager.py
```
自动安装依赖 → 检查更新 → 启动。**零配置**。

### 方式二：手动安装

```bash
pip install -r requirements.txt
python main.py
```

或双击 `run.bat`。

### 依赖

- Python 3.10+
- PySide6 ≥ 6.5
- qfluentwidgets ≥ 1.5
- psutil

## 项目结构

```
Manager_Fluent/
├── main.py              # 入口（FluentWindow + 托盘 + 主题 + 自更新）
├── bds_manager.py       # 智能更新引导（自动装依赖 + 检查更新 + 启动）
├── run.bat              # 启动脚本
├── release.py           # 发布打包脚本
├── archive.py           # 代码快照脚本
├── requirements.txt
├── version.json         # 在线更新版本信息
├── constants.py
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
│   └── errors.py        # 全局异常处理
├── components/
│   ├── notification_panel.py # 通知抽屉 + 铃铛按钮
│   ├── splash.py         # 启动闪屏（圆角·半透明·动画）
│   └── key_capture.py   # 键位录制控件
└── shared/
    ├── config.py        # 配置管理（JSON + 迁移 + 备份恢复）
    ├── workers.py       # 线程基类
    ├── toast.py         # 双模式 Toast 通知
    └── retry.py         # 重试装饰器
```

## 近期更新 (v3.03.04)

### 新功能
- 配置 JSON 文件原生编辑器（白名单/权限）：无边框 Fluent Design + 深浅色 + 半透明
- 高 DPI 缩放适配（设置页开关，重启生效）
- `bds_manager.py` 一键启动自动装依赖

### Bug 修复
- Win11 暗色标题栏 / 切换主题最小化 / SSL 证书 / 预设崩溃 / 保存刷屏 / 滚动跳回顶部

### 代码质量
- 全项目 30+ 处异常类型窄化 / main.py 拆分至 1054 行 / Toast 统一 / 配置持久化修复 9 处

## License

MIT
