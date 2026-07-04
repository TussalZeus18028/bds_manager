# 🧊 BDS Manager – Minecraft Bedrock 专用服务器管理工具

**一个功能强大、界面美观、开箱即用的 Minecraft Bedrock Dedicated Server 管理终端。**

![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![PyQt5](https://img.shields.io/badge/PyQt5-5.15-green)
![License](https://img.shields.io/badge/License-Apache_2.0-orange)
![Version](https://img.shields.io/badge/Version-2.0.5-brightgreen)

---

## 📌 简介

BDS Manager 是一个使用 PyQt5 构建的图形化管理工具，专为 **Minecraft Bedrock 专用服务器（BDS）** 设计。v2.0 带来了仪表盘、自动版本升级、工具自更新等大量新功能。无论你是新手服主还是资深管理员，都能高效地运维你的基岩版服务器。

---

## ✨ 主要特性

### 🏠 仪表盘（NEW v2.0）
- 实时状态总览：服务器状态、在线玩家数、运行时长、最近备份
- 在线玩家列表，右键踢出/封禁/设OP/取消OP
- CPU/内存/网络/TPS 实时监控
- 崩溃自动重启（最多5次，5秒延迟）

### 🖥️ 控制台
- 一键启动/停止服务器，实时彩色日志输出（13种颜色规则自动高亮）
- 玩家事件追踪（连接/生成/断开自动解析）
- 命令历史（上下箭头翻页，最近100条）
- 日志持久化（脚本目录 `logs/` 下按日期保存）

### 📦 资源包 / 行为包管理
- 图形化添加/移除资源包和行为包
- 自动读取 `manifest.json`，显示 UUID、版本、依赖等信息
- 手动激活/注销包到当前世界
- 文件监控自动刷新界面

### ⚙️ 可视化配置编辑
- 表单编辑 `server.properties`（28个配置项，中文提示）
- 内置端口检测与更换工具
- 白名单/权限/封包限制 JSON 编辑器
- 保存时保留原有注释

### 🌍 世界管理
- 查看当前世界名称、种子、难度
- 一键备份/还原（还原前验证 zip 完整性，旧世界可回滚）
- 自动定时备份 + 备份轮转（保留最近20个）

### 📊 系统资源监视
- 实时 CPU、内存、网络使用率
- CPU/内存历史折线图（最近60个点）

### 🚇 隧道（内网穿透）
- 集成 ChmlFrp，管理 `frpc.exe` 和 `frpc.ini`
- 一键启动/停止隧道，实时输出日志
- 配置模板按钮（含官网链接 https://www.chmlfrp.net/）

### 🔄 版本升级
- 自动检测官方稳定版/预览版最新版本（HEAD 并发探测）
- 支持手动指定版本号直接下载
- 一键升级：自动备份 → 解压 → 恢复关键数据
- 探测结果缓存 1 小时

### 🔧 工具自更新
- 版本升级标签页内检查 `bds_manager.py` 自身更新
- 自动下载新版、替换、重启（旧版备份 .bak）

### ⚙️ 设置
- 主题切换（深色/浅色/自定义颜色）
- 服务器路径、备份间隔、监视频率可配
- 窗口大小自动记忆

---

## 🚀 快速开始

### 环境要求
- Python 3.8+
- Windows

### 安装
```bash
pip install -r requirements.txt
```

### 运行
```bash
python bds_manager.py
```

首次启动会自动创建 `Server` 文件夹。将 BDS 文件放入后，在设置标签页指定路径即可。

---

## 📂 目录结构
```
bds_manager/
├── bds_manager.py          # 主程序
├── bds_manager_config.json # 配置文件（自动生成）
├── version.json            # 版本信息（用于自更新）
├── requirements.txt        # Python 依赖
├── logs/                   # 日志目录
│   ├── console_*.log
│   └── tunnel_*.log
└── Server/                 # 服务器目录（可自定义）
```

---

## 📄 许可证

Apache License 2.0
