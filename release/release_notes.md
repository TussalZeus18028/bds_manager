## v2.1.1.05

## v2.1.1.05

### 🐛 资源包解析修复
- get_full_pack_info 兼容 _parse_json 返回元组的情况
- 添加 is dict 类型检查，遇到错误 manifest 跳过而非崩溃
- 资源包信息读取不再抛 AttributeError
