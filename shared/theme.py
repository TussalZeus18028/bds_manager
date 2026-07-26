# -*- coding: utf-8 -*-
"""
shared/theme.py — 统一样式表和工具函数。

解决主题颜色、QPlainTextEdit/QTableWidget 样式表在 8+ 文件中重复定义的问题。
"""
from qfluentwidgets import isDarkTheme


# ── 通用颜色 ──
def hint_color() -> str:
    """浅灰提示文字颜色（暗色 vs 浅色）。"""
    return "#888" if isDarkTheme() else "#666"


# ── QPlainTextEdit 主题样式 ──
def plaintext_style(font_family: str = "Consolas, monospace",
                     font_size: int = 12, padding: int = 6) -> str:
    """QPlainTextEdit 深浅色主题样式表。"""
    if isDarkTheme():
        return f"""
            QPlainTextEdit {{
                background: #1e1e1e; color: #ccc;
                border: 1px solid #3a3a3a; border-radius: 6px;
                padding: {padding}px; font-family: {font_family}; font-size: {font_size}px;
            }}
        """
    return f"""
        QPlainTextEdit {{
            background: #fafafa; color: #1a1a1a;
            border: 1px solid #d0d0d0; border-radius: 6px;
            padding: {padding}px; font-family: {font_family}; font-size: {font_size}px;
        }}
    """


# ── QTableWidget 主题样式 ──
def table_style() -> str:
    """QTableWidget 深浅色主题样式表。"""
    if isDarkTheme():
        return """
            QTableWidget {
                background: #1e1e1e; color: #ccc; border: 1px solid #3a3a3a;
                gridline-color: #333; border-radius: 6px;
            }
            QTableWidget::item { padding: 6px 8px; }
            QTableWidget::item:selected { background: #264f78; color: #fff; }
            QHeaderView::section {
                background: #2a2a2a; color: #aaa; border: none;
                padding: 6px 8px; font-weight: bold;
            }
        """
    return """
        QTableWidget {
            background: #fafafa; color: #1a1a1a; border: 1px solid #d0d0d0;
            gridline-color: #e0e0e0; border-radius: 6px;
        }
        QTableWidget::item { padding: 6px 8px; }
        QTableWidget::item:selected { background: #cce5ff; color: #1a1a1a; }
        QHeaderView::section {
            background: #f0f0f0; color: #555; border: none;
            padding: 6px 8px; font-weight: bold;
        }
    """
