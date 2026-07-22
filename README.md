# BDS Manager Fluent

Minecraft Bedrock 版服务器全功能管理器 —— 基于 **PySide6 + QFluentWidgets Fluent Design**。

---

## 功能

| 页面 | 功能 |
|------|------|
| 🏠 仪表盘 | 实时系统资源监控、服务器启停、RTT 延迟、崩溃自愈重启 |
| ⌨️ 控制台 | 彩色日志输出、命令交互、玩家进出追踪、搜索/导出、命令历史 |
| 💾 世界 | 备份列表、手动/自动备份、一键还原（失败回滚）、备份删除 |
| 📁 资源包 | 资源包/行为包分 Tab 管理，扫描 manifest.json 显示详情 |
| ✏️ 配置 | server.properties 可视化编辑（28 项属性）、白名单/权限/包限制 |
| 🔄 升级 | GitHub 版本列表 + HEAD 扫描，下载进度条，ZipSlip 安全解压 |
| 🔗 隧道 | frpc 启动/停止/日志，frpc.ini 编辑锁定/模板 |
| ℹ️ 关于 | 版本信息 + 相关链接 |
| ⚙️ 设置 | 主题/主色切换、Toast 双模式、Webhook、GitHub Token、关闭行为 |

## 安装

```bash
pip install -r requirements.txt
python main.py
```

或双击 `run.bat`。

### 依赖

- Python 3.11+
- PySide6 ≥ 6.5
- PySide6-Fluent-Widgets ≥ 1.5
- requests, psutil

## 项目结构

```
Manager_Fluent/
├── main.py              # 入口（FluentWindow + 托盘 + 自更新）
├── run.bat              # 启动脚本
├── release.py           # 发布打包脚本
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
│   ├── settings.py      # 设置
│   └── about.py         # 关于
├── backend/
│   ├── server.py        # 服务器进程管理
│   ├── backup.py        # 备份/还原
│   ├── monitor.py       # 系统资源监控
│   ├── self_update.py   # 工具自更新
│   ├── webhook.py       # Webhook 通知
│   └── network.py       # 网络工具（端口检测/错误提示）
└── shared/
    ├── config.py        # 配置管理
    ├── workers.py       # 线程基类
    └── toast.py         # 双模式 Toast 通知
```

## 构建与发布

```bash
python release.py
```

自动打包 → 计算 SHA256 → 更新 version.json → 推送到 GitHub Release。

## License

MIT
