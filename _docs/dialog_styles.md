# QFluentWidgets 对话框样式参考

## MessageBox（推荐，首选）

自带主题背景、亚克力半透明模糊、圆角、无 Windows 原生白框标题栏。

```python
from qfluentwidgets import MessageBox

# 询问对话框（有确认/取消两个按钮）
if MessageBox("标题", "内容文字", self).exec():
    # 用户点了"确认"
    do_something()

# 示例：停止服务器确认
if MessageBox("确认停止", "确定要停止服务器吗？", win).exec():
    win.stop_server()
```

**项目中使用位置：**
- `components/notification_panel.py` — 清空通知确认
- `pages/console.py` — 停止服务器确认

---

## 自定义 QDialog（次选，需要精细控制时用）

如果 MessageBox 的默认按钮文字（确认/取消）不合适，或需要自定义布局，用原生 QDialog + qf 控件：

```python
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel
from PySide6.QtCore import Qt
from qfluentwidgets import PushButton, PrimaryPushButton, isDarkTheme

bg = "#1e1e1e" if isDarkTheme() else "#fafafa"
fg = "#ccc" if isDarkTheme() else "#1a1a1a"

dlg = QDialog(parent)
dlg.setWindowTitle("标题")
dlg.setFixedSize(340, 160)
dlg.setStyleSheet(
    f"QDialog {{ background: {bg}; border-radius: 8px; }}"
    f"QLabel {{ color: {fg}; font-size: 14px; }}"
)
dlg.setWindowFlags(dlg.windowFlags() | Qt.FramelessWindowHint)
dlg.setAttribute(Qt.WA_TranslucentBackground)

layout = QVBoxLayout(dlg)
layout.setContentsMargins(24, 20, 24, 16)
layout.addWidget(QLabel("提示文字"))

btn_row = QHBoxLayout()
btn_row.addStretch()
btn_row.addWidget(PushButton("取消", dlg))
btn_row.addWidget(PrimaryPushButton("确定", dlg))
layout.addLayout(btn_row)

if dlg.exec() == QDialog.Accepted:
    ...
```

**注意事项：**
- `isDarkTheme()` 判断深/浅色调，手工适配 `bg` `fg`
- qf 控件（PushButton / PrimaryPushButton）自动跟随主题，原生控件（QLabel）需手工设样式
- `Qt.FramelessWindowHint` + `WA_TranslucentBackground` 去掉 Windows 原生白框，才能有圆角

**项目中使用位置：**
- `main.py` — 跨主版本升级引导弹窗

---

## 禁止项

```python
# ❌ 永远不要这样写——Windows 原生对话框白底蓝边，不跟随主题，无圆角
from PySide6.QtWidgets import QMessageBox
QMessageBox.question(parent, "标题", "消息", QMessageBox.Yes | QMessageBox.No)
```
