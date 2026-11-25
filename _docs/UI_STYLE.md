# BDS Manager Fluent — UI 风格规范

> 新功能/新页面开发时**先读本规范**，保证全项目视觉一致。
> 配套文档：`_docs/dialog_styles.md`（对话框弹窗规范）。
> 最后同步：2026-08-25（v3.05.02）

---

## 1. 主题系统

| 项 | 约定 |
|---|---|
| 主题模式 | `theme` 配置：`dark` / `light` / `auto`（auto 跟随系统 `styleHints().colorScheme`） |
| 主色 | `theme_color` 配置（默认 `#0DC5D4` 青），`apply_theme(theme, accent)` 全局应用 |
| 切换 | 设置页改主色即时生效；主题切换后各页面调用 `refresh_theme()` 重设硬编码样式 |

**硬编码主色规则**：新代码一律 `config_mgr.get("theme_color", "#0DC5D4")`。遗留的写死 `#0DC5D4` 属历史债务（已逐步清理）。

## 2. 颜色系统（ThemePalette，强制使用）

`shared/theme.py` 的 `theme_palette()` 是**唯一**颜色入口，禁止手写 `isDarkTheme()` 三元。

| 属性 | 用途 | dark / light |
|---|---|---|
| `p.surface` | 页面/卡片主背景 | `#1e1e1e` / `#fafafa` |
| `p.text` | 主文字 | `#ccc` / `#1a1a1a` |
| `p.text_secondary` | 次要文字/提示 | `#888` / `#666` |
| `p.border` | 边框/分隔线 | `#3a3a3a` / `#d0d0d0` |
| `p.card_bg` | 卡片背景 | `#2a2a2a` / `#f0f0f0` |
| `p.card_hover` | 卡片 hover | `#353535` / `#e6e6e6` |
| `p.scrollbar_handle(_hover)` | 滚动条 | `#555`/`#777` / `#bbb`/`#999` |
| `p.chip_bg/hover/fg` | Chip 标签 | 见 theme.py |
| `p.grid_line` | 图表网格线 | `#2a2a2a` / `#e0e0e0` |
| `p.header_bg/fg` | 表格表头 | `#2a2a2a`/`#aaa` / `#f0f0f0`/`#555` |
| `p.level_accent(level)` | 通知等级色（error/warning/success/info） | 见 theme.py |
| `p.level_bg(level)` | 通知等级背景 | 见 theme.py |
| `p.toast_msg_color()` | Toast 文字 | `#ccddee` / `#333` |
| `p.rtt_color(ms)` | RTT 三色（<80 绿 / <200 橙 / ≥200 红） | — |

**工厂函数**：
- `theme_palette()` — 取色板
- `plaintext_style(font_family, font_size, padding)` — QPlainTextEdit 主题样式
- `table_style()` — QTableWidget 主题样式
- `scrollbar_style()` — 全局 6px 细滚动条（main.py 的 apply_theme 里统一应用）

## 3. 控件选型（什么场景用什么）

| 场景 | 控件 | 说明 |
|---|---|---|
| 主操作按钮 | `PrimaryPushButton` | 启动/保存/应用等 |
| 次要按钮 | `PushButton` | 常规动作，可带 `FluentIcon` |
| 开关 | `ToggleButton` | **设置 `setMinimumWidth`（≥100），否则文字被 check indicator 挤压截断**（踩坑：显示"自动滚"） |
| 复选 | `CheckBox` | 注意文字颜色主题感知 |
| 输入框 | `LineEdit` | qf 控件，主题感知 |
| 下拉 | `ComboBox` | qf 控件 |
| 卡片容器 | `CardWidget` | 页面分区，**margins(16,12,16,16) + spacing 8** 惯例 |
| 标题/正文/说明 | `SubtitleLabel` / `StrongBodyLabel` / `BodyLabel` / `CaptionLabel` | 层级递减，均主题感知 |
| 进度 | `ProgressBar` | 下载/备份进度 |
| 数字输入 | `NoScrollSpinBox`（components/widgets.py） | 禁用滚轮误触，必须用它 |
| 滑块 | qf `Slider`（如存在）或 `SpinBox` | 少用滑块，多用数字框 |
| 图标按钮 | `QToolButton` + `FluentIcon` | 铃铛等 |

## 4. 文本编辑器（用户最看重的样式）

**外部文件编辑** → **`FileEditDialog`**（`components/text_editor_dialog.py`，v3.05.02 提取）：
- 无边框 + 半透明(0.96) + 圆角容器(12px) + 深/浅色主题
- Consolas 等宽 13px + tabstop 20 + 内边距 12
- 标题栏 ✕ 关闭（hover 变红 `#e81123`）+ 保存/取消按钮行
- `Ctrl+S` 保存、`Esc` 关闭、`saved` 信号
- 用法：`FileEditDialog(path, parent).exec()`（读取失败自动不弹窗）
- 适用：allowlist.json / permissions.json / packetlimitconfig.json

**页内嵌编辑器**（frpc.ini 等需要常驻的场景）→ `QPlainTextEdit` + `plaintext_style("Consolas, monospace", 12, 6)`（shared/theme.py），只读锁定模式参考 `pages/tunnel.py`（"点击编辑" toggle）。

## 5. 信息弹窗 / Toast

| 场景 | 用 | 说明 |
|---|---|---|
| 确认/询问 | `MessageBox("标题","内容",win).exec()` | **不解析 HTML**，用纯文本；按钮文字可 `yesButton.setText()` |
| 全屏 toast（原版模式） | `toast_success/error/warning/info(title, msg, parent)` | 圆角滑入排队，自动进通知中心 |
| 全屏 toast（现代模式） | 同上（`toast_style="modern"` 时内部转 InfoBar 顶部居中） | 主题感知 |
| 长时进度提示 | `toast_info(..., duration=None)` | **不要传负数 duration**（-1 是 truthy 立即消失，v3.05.02 踩坑） |
| 系统通知 | `notify(level, category, title, body, action_target)` | 持久化 + 铃铛抽屉，action_target 格式 `page:world?backup=xxx` |
| 错误详情 | `MessageBox` 或 toast，附 `logs/bds_manager.log` 提示 | 见 shared/errors.py |

**禁止**：`QMessageBox`（原生白框不跟随主题，dialog_styles.md 明令禁止）。

## 6. 页面布局

```python
# 每个页面统一入口（pages/dashboard.py 的 wrap_scrollable）
inner, layout, _scroll = wrap_scrollable(self, spacing=12)
# 自动获得：ScrollArea + QScroller 惯性滚动 + margins(24,16,24,16)
```

- 页面 = ScrollArea 包裹，内容 = CardWidget 分区
- 卡片内统一 `setContentsMargins(16,12,16,16)`、`setSpacing(8)`
- 重组件延迟到 `showEvent` 初始化（启动加速惯例）
- 触控适配：所有可滚动区 `QScroller.grabGesture(widget, QScroller.LeftMouseButtonGesture)`

## 7. 表格 / 列表

- `QTableWidget` + `table_style()`（theme.py）
- 表头 `setSectionResizeMode`：自适应列用 `Stretch`，固定列用 `Fixed` + `setColumnWidth`
- **列宽必须量好**（教训：分支列 80px 截断"稳定版"→ 120px；按钮/文字列加 20-30px buffer）
- 行高 `verticalHeader().setDefaultSectionSize(40)`（容纳按钮）
- 触控：表格也加 QScroller

## 8. 图标（FluentIcon，无 emoji）

- 一律用 `FluentIcon.XXX` 矢量图标，**全项目禁用 emoji**（v3.05.02 已全量清理）
- 常用成员：HOME / COMMAND_PROMPT / SAVE / FOLDER / EDIT / SYNC / LINK / INFO / SETTING / PLAY / CANCEL / DELETE / SEARCH / SEND / DOWNLOAD / UPDATE / MESSAGE / PEOPLE / CONNECT / ACCEPT / MEGAPHONE / DOCUMENT / CLOSE 等（共 174 个成员）
- **用前 `dir(FluentIcon)` 确认**（UNDO / REFRESH / BELL / ERROR / WARNING 等不存在）
- 绘制到 widget 用 `icon.icon().pixmap(size, size)` → `QLabel.setPixmap` / `p.drawPixmap` / `QTreeWidgetItem.setIcon`
- 按钮带图标：`PushButton("文字", parent, FluentIcon.XXX)`

## 9. 对话框弹窗（引用 dialog_styles.md）

- 首选 `MessageBox`
- 自定义 QDialog：`FramelessWindowHint` + `WA_TranslucentBackground` + 圆角 + qf 控件
- 完整文件编辑器 → `FileEditDialog`（见上）

## 10. 主窗口 / 全局

- `FluentWindow`，`setMinimumSize(960, 620)`，导航展开宽 280
- 窗口圆角：Win11 DWM 优先，降级 QBitmap mask（12px）
- 透明度：`window_background_opacity`（100=不透明）
- 滚动条：`scrollbar_style()` 全局 6px
- 快捷键：`ShortcutManager`（backend/shortcuts.py）注册，不用裸 QShortcut 散落各处

## 11. 新 UI 自检清单

- [ ] 颜色全部走 `theme_palette()`，无 `isDarkTheme()` 三元、无硬编码色值
- [ ] 主色用 `config_mgr.get("theme_color", "#0DC5D4")`（不是写死 #0DC5D4）
- [ ] 无 emoji，图标用 FluentIcon（已 dir() 确认存在）
- [ ] 按钮/开关设了最小宽度（防截断）
- [ ] 页面走 `wrap_scrollable`，卡片 margins(16,12,16,16)
- [ ] 可滚动区加了 QScroller
- [ ] Toast 用 `toast_*` 系列，duration 不传负数
- [ ] 数字输入用 `NoScrollSpinBox`
- [ ] 文件编辑用 `FileEditDialog`（不是新写一个）
- [ ] `refresh_theme()` 已实现（主题切换时恢复硬编码样式）
