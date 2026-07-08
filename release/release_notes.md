## v2.1.1.04

## v2.1.1.04 安全加固 & 资源管理

### 🐛 Bug 修复
- DownloadUpdateWorker 改用 progress 信号（基类对齐，运行不再崩溃）
- requests 资源使用 finally 关闭，杜绝连接泄漏
- _apply_tool_update 解压失败保留 ZIP（防数据丢失）

### 🛡️ 安全加固
- _extract_update_zip 增加 Zip Slip 防护
  - 拒绝空名/`.`/`..`/含路径分隔符
  - 校验 realpath 在 SCRIPT_DIR 内

### 🧹 资源管理
- 重复下载自动取消旧 QThread
- fallback 下载流不再被误判为 .zip

### 🔄 Toast 同步终端
- error / warn / ok / info 全部 print 到 stdout
- 便于通过终端日志对照代码定位问题

### 📘 文档
- README 更新 v2.1.1+ 自更新机制、发布流程说明
