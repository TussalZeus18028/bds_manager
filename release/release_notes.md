## v2.1.1.00

## v2.1.0.10 架构重构 & 质量收尾

### 🏗️ 架构重构
- 彻底消除全局路径变量，60处引用统一为 _ctx 单例
- _BrowseWorker/UpgradeWorker 硬编码改为 constants 常量引用
- 拆分 _start_head_worker 消除重复
- ServerContext 集中路径管理

### 🛡️ 健壮性
- 0 个 bare except 残留
- HEAD 扫描：3次重试+指数退避+4UA轮换
- Token XOR+Base64 加密存储
- 强制备份：服务器运行时暂停→备份→恢复

### 🧹 清理
- requirements.txt 移除 fastapi/uvicorn/websockets
- Toast 位置随窗口自适应
