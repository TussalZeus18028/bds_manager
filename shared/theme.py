# -*- coding: utf-8 -*-
"""
shared/theme.py — 统一样式表和主题颜色工厂（v3.04.01 增强）。

解决主题颜色、QPlainTextEdit/QTableWidget 样式表在 8+ 文件中重复定义的问题。
新增 ThemePalette 集中管理所有硬编码色值，消除 isDarkTheme() 三元重复。
"""

from qfluentwidgets import isDarkTheme


# ════════════════════════════════════════════════════════════
#  ThemePalette: 集中管理所有主题颜色对
# ════════════════════════════════════════════════════════════

class ThemePalette:
    """主题色板：一个入口获取所有深浅色适配的颜色。

    用法：
        p = theme_palette()
        bg = p.surface       # 暗色: #1e1e1e, 浅色: #fafafa
        fg = p.text          # 暗色: #ccc,     浅色: #1a1a1a
    """

    # ── 基础色 ──
    @property
    def surface(self) -> str:
        """页面/卡片主背景。"""
        return "#1e1e1e" if isDarkTheme() else "#fafafa"

    @property
    def text(self) -> str:
        """主文字颜色。"""
        return "#ccc" if isDarkTheme() else "#1a1a1a"

    @property
    def text_secondary(self) -> str:
        """次要文字（提示/说明）。"""
        return "#888" if isDarkTheme() else "#666"

    @property
    def border(self) -> str:
        """边框/分隔线颜色。"""
        return "#3a3a3a" if isDarkTheme() else "#d0d0d0"

    # ── 控件专用 ──
    @property
    def card_bg(self) -> str:
        """卡片/面板背景（比 surface 略深/浅）。"""
        return "#2a2a2a" if isDarkTheme() else "#f0f0f0"

    @property
    def card_hover(self) -> str:
        """卡片 hover 态。"""
        return "#353535" if isDarkTheme() else "#e6e6e6"

    @property
    def scrollbar_handle(self) -> str:
        """滚动条滑块颜色。"""
        return "#555" if isDarkTheme() else "#bbb"

    @property
    def scrollbar_handle_hover(self) -> str:
        """滚动条滑块 hover 颜色。"""
        return "#777" if isDarkTheme() else "#999"

    @property
    def chip_bg(self) -> str:
        """Chip/标签未选中背景。"""
        return "#2a2a2a" if isDarkTheme() else "#e8e8e8"

    @property
    def chip_hover(self) -> str:
        """Chip/标签 hover。"""
        return "#353535" if isDarkTheme() else "#d8d8d8"

    @property
    def chip_fg(self) -> str:
        """Chip/标签未选中文字。"""
        return "#aabbcc" if isDarkTheme() else "#444"

    @property
    def grid_line(self) -> str:
        """图表/网格线颜色。"""
        return "#2a2a2a" if isDarkTheme() else "#e0e0e0"

    @property
    def header_bg(self) -> str:
        """列表/表格表头背景。"""
        return "#2a2a2a" if isDarkTheme() else "#f0f0f0"

    @property
    def header_fg(self) -> str:
        """列表/表格表头文字。"""
        return "#aaa" if isDarkTheme() else "#555"

    def level_accent(self, level: str) -> str:
        """通知等级强调色（色条/标题用）。返回 hex。"""
        colors = {
            "error":   ("#ff7777", "#c03030"),
            "warning": ("#ffcc66", "#b86a00"),
            "success": ("#66dd88", "#2a8a4a"),
            "info":    ("#77aaff", "#1c66c0"),
        }
        idx = 0 if isDarkTheme() else 1
        return colors.get(level, colors["info"])[idx]

    def level_bg(self, level: str) -> str:
        """通知等级背景色。"""
        colors = {
            "error":   ("#2a181a", "#fdecec"),
            "warning": ("#2a2218", "#fdf3e3"),
            "success": ("#182a1e", "#e6f5ec"),
            "info":    ("#181e2a", "#e6f0fa"),
        }
        idx = 0 if isDarkTheme() else 1
        return colors.get(level, colors["info"])[idx]

    def toast_msg_color(self) -> str:
        """Toast 消息文字颜色。"""
        return "#ccddee" if isDarkTheme() else "#333333"

    def rtt_color(self, median_ms: float) -> str:
        """RTT 延迟颜色（绿 < 80ms，橙 < 200ms，红 >= 200ms）。"""
        if median_ms < 80:
            return "#4CAF50"
        if median_ms < 200:
            return "#E65100"
        return "#ff5555"


# ── 模块级单例 ──
_PALETTE: ThemePalette | None = None


def theme_palette() -> ThemePalette:
    """获获取主题调色板（惰性单例）。"""
    global _PALETTE
    if _PALETTE is None:
        _PALETTE = ThemePalette()
    return _PALETTE


# ── 便捷别名（兼容旧 API）──
def hint_color() -> str:
    """浅灰提示文字颜色。"""
    return theme_palette().text_secondary


# ── QPlainTextEdit 主题样式 ──
def plaintext_style(font_family: str = "Consolas, monospace",
                     font_size: int = 12, padding: int = 6) -> str:
    """QPlainTextEdit 深浅色主题样式表。"""
    p = theme_palette()
    return f"""
        QPlainTextEdit {{
            background: {p.surface}; color: {p.text};
            border: 1px solid {p.border}; border-radius: 6px;
            padding: {padding}px; font-family: {font_family}; font-size: {font_size}px;
        }}
    """


# ── QTableWidget 主题样式 ──
def table_style() -> str:
    """QTableWidget 深浅色主题样式表。"""
    p = theme_palette()
    if isDarkTheme():
        return f"""
            QTableWidget {{
                background: {p.surface}; color: {p.text};
                border: 1px solid {p.border}; gridline-color: #333;
                border-radius: 6px;
            }}
            QTableWidget::item {{ padding: 6px 8px; }}
            QTableWidget::item:selected {{ background: #264f78; color: #fff; }}
            QHeaderView::section {{
                background: {p.header_bg}; color: {p.header_fg};
                border: none; padding: 6px 8px; font-weight: bold;
            }}
        """
    return f"""
        QTableWidget {{
            background: {p.surface}; color: {p.text};
            border: 1px solid {p.border}; gridline-color: #e0e0e0;
            border-radius: 6px;
        }}
        QTableWidget::item {{ padding: 6px 8px; }}
        QTableWidget::item:selected {{ background: #cce5ff; color: {p.text}; }}
        QHeaderView::section {{
            background: {p.header_bg}; color: {p.header_fg};
            border: none; padding: 6px 8px; font-weight: bold;
        }}
    """


# ── 滚动条统一样式 ──
def scrollbar_style() -> str:
    """全局 6px 细滚动条样式表（主题感知）。"""
    p = theme_palette()
    return f"""
        QScrollBar:vertical {{
            width: 6px; background: transparent; border: none; margin: 0;
        }}
        QScrollBar::handle:vertical {{
            background: {p.scrollbar_handle}; border-radius: 3px; min-height: 30px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {p.scrollbar_handle_hover};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0; border: none;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: none;
        }}
        QScrollBar:horizontal {{
            height: 6px; background: transparent; border: none; margin: 0;
        }}
        QScrollBar::handle:horizontal {{
            background: {p.scrollbar_handle}; border-radius: 3px; min-width: 30px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: {p.scrollbar_handle_hover};
        }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            width: 0; border: none;
        }}
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
            background: none;
        }}
    """
