# -*- coding: utf-8 -*-
"""
共享控件 —— 跨页面复用的自定义 widget。

v3.02.01: SpinBox 默认鼠标滚轮划过就改值，极容易误触。
NoScrollSpinBox 修复：完全禁用滚轮修改（键盘 / 按钮仍可正常改值）。
"""

from PySide6.QtCore import QEvent
from qfluentwidgets import SpinBox


class NoScrollSpinBox(SpinBox):
    """SpinBox 子类：完全禁用滚轮修改。

    用法：直接替换 SpinBox(...) → NoScrollSpinBox(...)，其他 API 完全一致。
    
    设计决策：即使 SpinBox 获得焦点也不响应滚轮。
    用户想改值可以用键盘方向键、数字键、或点击上下按钮——
    滚轮在页面上下穿梭时最容易误触，所以一刀切禁用。
    """
    def event(self, event: QEvent) -> bool:
        # 拦截滚轮事件（在 wheelEvent 之前分发），完全吞掉
        if event.type() == QEvent.Type.Wheel:
            event.ignore()
            return True
        return super().event(event)
