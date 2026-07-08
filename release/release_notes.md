## v2.1.1.01

## v2.1.1.01

### 🔄 版本检查升级
- version.json 从 GitHub API 获取，绕开 raw CDN 缓存
- 新增 _fetch_remote_version_json() 辅助函数

### 🔘 安装体验优化
- 进入升级页自动扫描本地更新包
- 安装按钮始终可见（禁用/启用态）

### 🐛 修复
- base64 导入缺失
- subprocess GBK 编码错误
- 版本号不同步问题
