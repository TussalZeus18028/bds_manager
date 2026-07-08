## v2.1.1.00

## v2.1.1.00 自更新机制 & 发布工具

### 📦 ZIP 全量更新
- 自更新改为 ZIP 包下载，覆盖附属文件
- 下载后 SHA256 校验 + ZIP 头检测防伪
- 启动更新异步化，不阻塞 GUI
- version.json 缓存穿透（时间戳参数）

### 🔘 安装按钮
- 升级页新增「安装更新并重启」按钮
- 进入页面自动扫描本地更新包，一键启用
- 备份 → 解压 → 重启 全自动

### 🛠 发布工具
- release_gui.py 图形界面（内建打包+发布）
- build_release.py / publish.py / release.py 已合并删除
- 自动生成 release_notes.md
- publish.bat 已替换为 Python 脚本

### 🐛 修复
- DownloadUpdateWorker 信号参数对齐
- 下载进度 status_signal → progress
- subprocess GBK 编码错误
