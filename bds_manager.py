#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Minecraft Bedrock Dedicated Server 管理工具
功能：
  - 启动/停止服务器，实时显示控制台输出（自动着色）
  - 向服务器发送命令
  - 资源包/行为包管理（添加、移除、自动注册到世界）
  - 可视化编辑 server.properties（带中文提示）
  - 白名单(allowlist.json) 和权限(permissions.json) 表格管理
  - 世界备份与还原（自动备份定时器可动态调整）
  - 服务器端口、最大玩家等快速设置
  - 深色/浅色/自定义主题切换
  - 配置保存与自动加载
  - 支持脚本与服务器文件夹分离
  - 文件系统监控，外部修改自动刷新（防抖）
  - 添加包时自动重试读取 manifest.json（解决文件系统延迟）
  - 资源包/行为包详细信息查看（双击或右键菜单 -> 详情）
  - 手动激活/注销资源包到当前世界（右键菜单，需服务器未运行）
  - 端口检测与更换功能（检测 UDP 端口占用，自动推荐可用端口）
  - 系统资源监视（CPU、内存、网络、磁盘），支持设置更新频率
  - 增强控制台日志（时间戳 + 彩色输出）
  - 系统托盘图标，支持最小化隐藏
  - 实时 CPU 与内存使用率折线图（历史 60 点，高度增加，中文显示）
  - 增强：更完善的错误处理，所有关键操作均有详细日志和用户提示
  - 新增：隧道标签页（ChmlFrp 内网穿透），支持 frpc.exe 路径设置、
    frpc.ini 编辑、启动/停止隧道及实时输出
  - 多线程优化：所有耗时操作移至后台线程，避免阻塞主界面
"""

__version__ = "2.0.9"

import sys
import os
import json
import shutil
import zipfile
import subprocess
import threading
import time
import re
try:
    import json5
    _HAS_JSON5 = True
except ImportError:
    _HAS_JSON5 = False
    json5 = None

def _parse_json(text):
    """兼容解析 JSON 或 JSON5（含注释/尾逗号）"""
    if _HAS_JSON5:
        try:
            return json5.loads(text), True
        except Exception:
            pass
    return json.loads(text), False
import socket
import psutil
import ctypes
import urllib.request
import urllib.error
import tempfile
from datetime import datetime
from pathlib import Path
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed

# 尝试导入 matplotlib，如果失败则提示安装
try:
    import matplotlib
    matplotlib.use('Qt5Agg')
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
    # ---------- 解决中文显示问题 ----------
    try:
        plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
        plt.rcParams['axes.unicode_minus'] = False
    except Exception as e:
        print(f"[WARN] 中文字体设置失败: {e}")
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print("[WARN] matplotlib 未安装，折线图功能将不可用。请执行: pip install matplotlib")

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QTabWidget, QTextEdit, QLineEdit, QPushButton, QLabel, QMessageBox,
    QFileDialog, QTableWidget, QTableWidgetItem, QHeaderView, QDialog,
    QFormLayout, QGroupBox, QSpinBox, QCheckBox, QComboBox, QColorDialog,
    QSplitter, QProgressBar, QListWidget, QListWidgetItem, QAbstractItemView,
    QInputDialog, QScrollArea, QMenu, QDialogButtonBox,
    QTabWidget as QTabWidget2, QSystemTrayIcon, QAction, QStyle,
    QPlainTextEdit
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread, QFileSystemWatcher, QEvent, QObject, QPropertyAnimation, QParallelAnimationGroup, QEasingCurve, QRect, QPoint
from PyQt5.QtGui import QFont, QColor, QTextCursor, QIcon, QPainter, QPen

# ---------- Toast 通知组件 ----------
class ToastNotification(QWidget):
    """现代化右上角弹窗通知"""
    _instances = []

    def __init__(self, parent, title, message, level="info", duration=4000):
        super().__init__(None)
        self._window = parent

        # 使用纯色背景 + 圆角遮罩（避免 Windows UpdateLayeredWindow 错误）
        colors = {
            "error": ("#ff4444", "#2a181a"),
            "warning": ("#ffaa33", "#2a2218"),
            "success": ("#44cc66", "#182a1e"),
            "info": ("#4488ff", "#181e2a"),
        }
        accent_hex, bg_hex = colors.get(level, colors["info"])
        self._bg = QColor(bg_hex)
        self._accent = QColor(accent_hex)
        self._radius = 12

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.ToolTip)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedWidth(320)

        icon = {"error": "❌", "warning": "⚠️", "success": "✅", "info": "ℹ️"}.get(level, "ℹ️")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        icon_label = QLabel(icon)
        icon_label.setStyleSheet("font-size:18px; background:transparent;")
        layout.addWidget(icon_label, 0, Qt.AlignTop)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        title_label = QLabel(title)
        title_label.setStyleSheet(f"font-weight:bold; font-size:12px; color:{accent_hex}; background:transparent;")
        msg_label = QLabel(message)
        msg_label.setWordWrap(True)
        msg_label.setStyleSheet("font-size:11px; color:#ccddee; background:transparent;")
        text_layout.addWidget(title_label)
        text_layout.addWidget(msg_label)
        layout.addLayout(text_layout, 1)

        self.setStyleSheet(f"ToastNotification {{ background-color: {bg_hex}; }}")

        self.adjustSize()
        self.setFixedWidth(320)
        h = max(60, self.sizeHint().height() + 10)
        self.setFixedHeight(h)
        self._apply_mask()

        self._calc_position()
        self._start_slide_in()
        self.show()
        self._clicked = False
        self.mousePressEvent = lambda e: self._dismiss()
        QTimer.singleShot(duration, self._dismiss)
        ToastNotification._instances.append(self)

    def _apply_mask(self):
        """圆角遮罩"""
        from PyQt5.QtGui import QBitmap, QPainter as QP2
        mask = QBitmap(self.size())
        mask.fill(Qt.color0)
        p = QP2(mask)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(Qt.color1)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(self.rect(), self._radius, self._radius)
        p.end()
        self.setMask(mask)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(self._bg)
        p.setPen(QPen(self._accent, 2))
        r = self.rect().adjusted(1, 1, -1, -1)
        p.drawRoundedRect(r, self._radius, self._radius)

    def _calc_position(self):
        """计算在窗口右上角的绝对坐标"""
        w = self._window
        offset = 12
        for inst in ToastNotification._instances:
            offset += inst.height() + 8
        # 相对于主窗口右上角
        x = w.mapToGlobal(QPoint(w.width() - self.width() - 12, offset)).x()
        y = w.mapToGlobal(QPoint(0, offset)).y()
        self.move(x, y)

    def _start_slide_in(self):
        # 从窗口右边缘滑入
        w = self._window
        right_edge = w.mapToGlobal(QPoint(w.width(), 0)).x()
        self._anim_in = QPropertyAnimation(self, b"pos")
        self._anim_in.setDuration(300)
        self._anim_in.setStartValue(QPoint(right_edge, self.y()))
        self._anim_in.setEndValue(self.pos())
        self._anim_in.setEasingCurve(QEasingCurve.OutCubic)
        self._anim_in.start()

    def _dismiss(self):
        if self._clicked: return
        self._clicked = True
        # 位置 + 透明度 同时动画
        self._anim_out = QPropertyAnimation(self, b"pos")
        self._anim_out.setDuration(250)
        self._anim_out.setStartValue(self.pos())
        end_x = self._window.mapToGlobal(QPoint(self._window.width(), 0)).x()
        self._anim_out.setEndValue(QPoint(end_x, self.y()))
        self._anim_out.setEasingCurve(QEasingCurve.InCubic)
        self._anim_out.finished.connect(self._cleanup)
        self._anim_out.start()

    def _cleanup(self):
        if self in ToastNotification._instances:
            ToastNotification._instances.remove(self)
        self.deleteLater()
        for inst in ToastNotification._instances:
            inst._calc_position()

# ---------- 启用 Windows 控制台 ANSI 颜色 ----------
if sys.platform == "win32":
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass

# ---------- 增强的颜色控制台日志（带时间戳）----------
COLOR_RESET = "\033[0m"
COLOR_INFO = "\033[92m"
COLOR_WARNING = "\033[93m"
COLOR_ERROR = "\033[91m"
COLOR_SUCCESS = "\033[96m"
COLOR_CMD = "\033[94m"
COLOR_GRAY = "\033[90m"
COLOR_DEBUG = "\033[95m"

def _timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

def log_info(msg):
    print(f"{COLOR_INFO}[{_timestamp()}] [INFO] {msg}{COLOR_RESET}")

def log_warning(msg):
    print(f"{COLOR_WARNING}[{_timestamp()}] [WARN] {msg}{COLOR_RESET}")

def log_error(msg):
    print(f"{COLOR_ERROR}[{_timestamp()}] [ERROR] {msg}{COLOR_RESET}")

def log_success(msg):
    print(f"{COLOR_SUCCESS}[{_timestamp()}] [SUCCESS] {msg}{COLOR_RESET}")

def log_cmd(msg):
    print(f"{COLOR_CMD}[{_timestamp()}] [CMD] {msg}{COLOR_RESET}")

def log_step(msg):
    print(f"{COLOR_GRAY}[{_timestamp()}] [STEP] {msg}{COLOR_RESET}")

def log_debug(msg):
    print(f"{COLOR_DEBUG}[{_timestamp()}] [DEBUG] {msg}{COLOR_RESET}")

# ---------- Toast 便捷函数 ----------
_toast_parent = None

def set_toast_parent(parent):
    global _toast_parent
    _toast_parent = parent

def toast_error(title, msg=""):
    if _toast_parent: ToastNotification(_toast_parent, title, msg, "error", 5000)

def toast_warning(title, msg=""):
    if _toast_parent: ToastNotification(_toast_parent, title, msg, "warning", 4000)

def toast_success(title, msg=""):
    if _toast_parent: ToastNotification(_toast_parent, title, msg, "success", 3500)

def toast_info(title, msg=""):
    if _toast_parent: ToastNotification(_toast_parent, title, msg, "info", 3000)

# ---------- 全局配置：支持脚本与服务器文件夹分离 ----------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "bds_manager_config.json")

def get_server_dir():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
                server_dir = config.get("server_dir")
                if server_dir and os.path.isabs(server_dir):
                    return server_dir
                elif server_dir:
                    return os.path.join(SCRIPT_DIR, server_dir)
        except Exception as e:
            log_error(f"读取配置文件失败: {e}")
    default = os.path.join(SCRIPT_DIR, "Server")
    os.makedirs(default, exist_ok=True)
    return default

SERVER_DIR = get_server_dir()
log_info(f"服务器目录: {SERVER_DIR}")

SERVER_PROPERTIES = os.path.join(SERVER_DIR, "server.properties")
ALLOWLIST_FILE = os.path.join(SERVER_DIR, "allowlist.json")
PERMISSIONS_FILE = os.path.join(SERVER_DIR, "permissions.json")
PACKET_LIMIT_FILE = os.path.join(SERVER_DIR, "packetlimitconfig.json")
WORLDS_DIR = os.path.join(SERVER_DIR, "worlds")
RESOURCE_PACKS_DIR = os.path.join(SERVER_DIR, "resource_packs")
BEHAVIOR_PACKS_DIR = os.path.join(SERVER_DIR, "behavior_packs")
BACKUP_DIR = os.path.join(SERVER_DIR, "backups")

for d in [WORLDS_DIR, RESOURCE_PACKS_DIR, BEHAVIOR_PACKS_DIR, BACKUP_DIR]:
    os.makedirs(d, exist_ok=True)

# ---------- 端口检测辅助函数 ----------
def is_port_udp_in_use(port):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('0.0.0.0', port))
        sock.close()
        return False
    except OSError as e:
        log_debug(f"端口 {port} 检测被占用: {e}")
        return True

def find_free_udp_port(start_port, max_attempts=100):
    for offset in range(max_attempts):
        port = start_port + offset
        if not is_port_udp_in_use(port):
            return port
    return None

# ---------- 端口检测/更换对话框 ----------
class PortCheckerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setWindowTitle("端口检测与更换")
        self.setModal(True)
        self.resize(500, 400)
        self.init_ui()
        self.load_current_ports()

    def init_ui(self):
        layout = QVBoxLayout(self)
        info_label = QLabel("此工具可检测 server-port 和 server-portv6 是否被占用，并自动推荐可用端口。\n"
                           "注意：基岩版服务器使用 UDP 协议，端口需高于 1024（推荐 19132 及以上）。")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        self.ports_group = QGroupBox("当前端口配置")
        ports_layout = QFormLayout()
        self.ipv4_port_label = QLabel()
        self.ipv4_status_label = QLabel()
        self.ipv6_port_label = QLabel()
        self.ipv6_status_label = QLabel()
        ports_layout.addRow("IPv4 端口 (server-port):", self.ipv4_port_label)
        ports_layout.addRow("状态:", self.ipv4_status_label)
        ports_layout.addRow("IPv6 端口 (server-portv6):", self.ipv6_port_label)
        ports_layout.addRow("状态:", self.ipv6_status_label)
        self.ports_group.setLayout(ports_layout)
        layout.addWidget(self.ports_group)

        self.recommend_group = QGroupBox("推荐端口")
        recommend_layout = QFormLayout()
        self.recommend_ipv4_edit = QLineEdit()
        self.recommend_ipv6_edit = QLineEdit()
        self.recommend_ipv4_edit.setPlaceholderText("自动推荐")
        self.recommend_ipv6_edit.setPlaceholderText("自动推荐")
        recommend_layout.addRow("推荐 IPv4 端口:", self.recommend_ipv4_edit)
        recommend_layout.addRow("推荐 IPv6 端口:", self.recommend_ipv6_edit)
        self.recommend_group.setLayout(recommend_layout)
        layout.addWidget(self.recommend_group)

        btn_layout = QHBoxLayout()
        self.detect_btn = QPushButton("重新检测")
        self.detect_btn.clicked.connect(self.detect_ports)
        self.apply_btn = QPushButton("应用推荐端口")
        self.apply_btn.clicked.connect(self.apply_recommended_ports)
        self.manual_btn = QPushButton("手动设置端口")
        self.manual_btn.clicked.connect(self.manual_set_ports)
        btn_layout.addWidget(self.detect_btn)
        btn_layout.addWidget(self.apply_btn)
        btn_layout.addWidget(self.manual_btn)
        layout.addLayout(btn_layout)

        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def load_current_ports(self):
        self.current_ipv4 = 19132
        self.current_ipv6 = 19133
        if os.path.exists(SERVER_PROPERTIES):
            try:
                with open(SERVER_PROPERTIES, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("server-port="):
                            try:
                                self.current_ipv4 = int(line.split("=", 1)[1])
                            except (ValueError, IndexError):
                                pass
                        elif line.startswith("server-portv6="):
                            try:
                                self.current_ipv6 = int(line.split("=", 1)[1])
                            except (ValueError, IndexError):
                                pass
            except Exception as e:
                log_error(f"读取 server.properties 失败: {e}")
        self.ipv4_port_label.setText(str(self.current_ipv4))
        self.ipv6_port_label.setText(str(self.current_ipv6))
        self.detect_ports()

    def detect_ports(self):
        try:
            ipv4_in_use = is_port_udp_in_use(self.current_ipv4)
            ipv6_in_use = is_port_udp_in_use(self.current_ipv6)
            self.ipv4_status_label.setText("被占用 ❌" if ipv4_in_use else "空闲 ✅")
            self.ipv6_status_label.setText("被占用 ❌" if ipv6_in_use else "空闲 ✅")
            new_ipv4 = self.current_ipv4
            new_ipv6 = self.current_ipv6
            if ipv4_in_use:
                new_ipv4 = find_free_udp_port(max(self.current_ipv4 + 1, 19132))
                if new_ipv4 is None:
                    new_ipv4 = "未找到可用端口"
            if ipv6_in_use:
                base = max(self.current_ipv6 + 1, 19133)
                new_ipv6 = find_free_udp_port(base)
                if new_ipv6 is None:
                    new_ipv6 = "未找到可用端口"
                if isinstance(new_ipv6, int) and isinstance(new_ipv4, int) and new_ipv6 == new_ipv4:
                    new_ipv6 = find_free_udp_port(new_ipv6 + 1)
            self.recommend_ipv4_edit.setText(str(new_ipv4) if new_ipv4 is not None else "错误")
            self.recommend_ipv6_edit.setText(str(new_ipv6) if new_ipv6 is not None else "错误")
        except Exception as e:
            log_error(f"端口检测异常: {e}")
            toast_error("端口检测失败", str(e))

    def apply_recommended_ports(self):
        new_ipv4_text = self.recommend_ipv4_edit.text().strip()
        new_ipv6_text = self.recommend_ipv6_edit.text().strip()
        try:
            new_ipv4 = int(new_ipv4_text)
            new_ipv6 = int(new_ipv6_text)
        except ValueError:
            toast_error("格式无效", "推荐的端口格式无效，请重新检测或手动输入。")
            return
        if not os.path.exists(SERVER_PROPERTIES):
            toast_error("文件不存在", "server.properties 文件不存在")
            return
        try:
            with open(SERVER_PROPERTIES, "r", encoding="utf-8") as f:
                lines = f.readlines()
            updated = False
            with open(SERVER_PROPERTIES, "w", encoding="utf-8") as f:
                for line in lines:
                    if line.startswith("server-port="):
                        f.write(f"server-port={new_ipv4}\n")
                        updated = True
                    elif line.startswith("server-portv6="):
                        f.write(f"server-portv6={new_ipv6}\n")
                        updated = True
                    else:
                        f.write(line)
                if not updated:
                    f.write(f"server-port={new_ipv4}\n")
                    f.write(f"server-portv6={new_ipv6}\n")
            log_success(f"端口已更新: IPv4={new_ipv4}, IPv6={new_ipv6}")
            toast_success("端口已更新", f"{new_ipv4} / {new_ipv6}")
            self.load_current_ports()
            if hasattr(self.parent, 'load_server_properties'):
                self.parent.load_server_properties()
        except Exception as e:
            log_error(f"应用端口失败: {e}")
            QMessageBox.critical(self, "错误", f"保存端口配置失败: {e}")

    def manual_set_ports(self):
        ipv4, ok1 = QInputDialog.getInt(self, "手动设置 IPv4 端口", "请输入 IPv4 端口 (1024-65535):",
                                         self.current_ipv4, 1024, 65535)
        ipv6, ok2 = QInputDialog.getInt(self, "手动设置 IPv6 端口", "请输入 IPv6 端口 (1024-65535):",
                                         self.current_ipv6, 1024, 65535)
        if ok1 and ok2:
            self.recommend_ipv4_edit.setText(str(ipv4))
            self.recommend_ipv6_edit.setText(str(ipv6))
            self.apply_recommended_ports()

# ---------- 辅助函数 ----------
def format_file_size(size_bytes):
    for unit in ['B', 'KiB', 'MiB', 'GiB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}" if unit != 'B' else f"{size_bytes} B"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} GiB"

def get_world_path(level_name):
    return os.path.join(WORLDS_DIR, level_name)

def get_pack_manifest(pack_folder, retry=5, delay=0.4):
    manifest_path = os.path.join(pack_folder, "manifest.json")
    for attempt in range(retry):
        if not os.path.exists(manifest_path):
            if attempt < retry - 1:
                log_warning(f"manifest.json 尚未就绪 (尝试 {attempt+1}/{retry})，等待 {delay} 秒...")
                time.sleep(delay)
                continue
            else:
                log_error(f"在 {pack_folder} 中未找到 manifest.json")
                break
        try:
            with open(manifest_path, "r", encoding="utf-8-sig") as f:
                content = f.read()
        except Exception as e:
            log_warning(f"读取文件失败 (尝试 {attempt+1}/{retry}): {e}")
            time.sleep(delay)
            continue
        try:
            data, _ = _parse_json(content)
            header = data.get("header", {})
            uuid = header.get("uuid")
            version = header.get("version")
            if isinstance(version, list):
                version = ".".join(map(str, version))
            return uuid, version
        except Exception as e:
            log_warning(f"使用 json5 解析 manifest.json 失败 (尝试 {attempt+1}/{retry}): {e}")
            if attempt == retry - 1:
                log_error(f"文件开头预览 (前300字符):\n{content[:300]}")
            time.sleep(delay)
            continue
    return None, None

def get_full_pack_info(pack_folder):
    manifest_path = os.path.join(pack_folder, "manifest.json")
    if not os.path.exists(manifest_path):
        return None
    try:
        with open(manifest_path, "r", encoding="utf-8-sig") as f:
            content = f.read()
        data = json5.loads(content)
        header = data.get("header", {})
        modules = data.get("modules", [])
        dependencies = data.get("dependencies", [])
        metadata = data.get("metadata", {})
        info = {
            "name": header.get("name", "未知名称"),
            "description": header.get("description", "无描述"),
            "uuid": header.get("uuid", "未知"),
            "version": header.get("version", "未知"),
            "min_engine_version": header.get("min_engine_version", []),
            "modules": modules,
            "dependencies": dependencies,
            "authors": metadata.get("authors", []),
            "license": metadata.get("license", "未知"),
            "url": metadata.get("url", ""),
            "raw_data": data
        }
        if isinstance(info["version"], list):
            info["version"] = ".".join(map(str, info["version"]))
        if info["min_engine_version"] and isinstance(info["min_engine_version"], list):
            info["min_engine_version"] = ".".join(map(str, info["min_engine_version"]))
        return info
    except Exception as e:
        log_error(f"读取完整包信息失败 {pack_folder}: {e}")
        return None

def get_folder_size(folder_path):
    total = 0
    if not os.path.exists(folder_path):
        return 0
    try:
        for dirpath, dirnames, filenames in os.walk(folder_path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if os.path.exists(fp):
                    total += os.path.getsize(fp)
    except Exception as e:
        log_error(f"计算文件夹大小失败: {e}")
    return total

def register_pack_to_world(world_path, pack_type, pack_name, pack_uuid, pack_version):
    if pack_type == "resource":
        json_path = os.path.join(world_path, "world_resource_packs.json")
    else:
        json_path = os.path.join(world_path, "world_behavior_packs.json")
    if not os.path.exists(json_path):
        data = []
    else:
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            log_error(f"读取世界包注册文件失败: {e}")
            return False
    for entry in data:
        if entry.get("pack_id") == pack_uuid:
            return False
    data.append({
        "pack_id": pack_uuid,
        "version": pack_version
    })
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
        return True
    except Exception as e:
        log_error(f"写入世界包注册文件失败: {e}")
        return False

def unregister_pack_from_world(world_path, pack_type, pack_uuid):
    if pack_type == "resource":
        json_path = os.path.join(world_path, "world_resource_packs.json")
    else:
        json_path = os.path.join(world_path, "world_behavior_packs.json")
    if not os.path.exists(json_path):
        return False
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        new_data = [entry for entry in data if entry.get("pack_id") != pack_uuid]
        if len(new_data) == len(data):
            return False
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(new_data, f, indent=4)
        return True
    except Exception as e:
        log_error(f"从世界注销包失败: {e}")
        return False

# ---------- 包详细信息对话框（已改进表格）----------
class PackInfoDialog(QDialog):
    def __init__(self, pack_folder, pack_type, is_active, parent=None):
        super().__init__(parent)
        self.pack_folder = pack_folder
        self.pack_type = pack_type
        self.is_active = is_active
        self.setWindowTitle(f"包详细信息 - {os.path.basename(pack_folder)}")
        self.setMinimumSize(600, 500)
        self.init_ui()
        self.load_info()

    def init_ui(self):
        layout = QVBoxLayout(self)
        self.tab_widget = QTabWidget2()

        self.basic_widget = QWidget()
        self.basic_layout = QFormLayout(self.basic_widget)
        self.basic_layout.setSpacing(8)

        self.modules_widget = QWidget()
        self.modules_layout = QVBoxLayout(self.modules_widget)
        self.modules_table = QTableWidget()
        self.modules_table.setColumnCount(3)
        self.modules_table.setHorizontalHeaderLabels(["类型", "版本", "入口点/说明"])
        self.modules_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.modules_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.modules_layout.addWidget(self.modules_table)

        self.deps_widget = QWidget()
        self.deps_layout = QVBoxLayout(self.deps_widget)
        self.deps_table = QTableWidget()
        self.deps_table.setColumnCount(2)
        self.deps_table.setHorizontalHeaderLabels(["UUID", "版本"])
        self.deps_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.deps_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.deps_layout.addWidget(self.deps_table)

        self.tab_widget.addTab(self.basic_widget, "基本信息")
        self.tab_widget.addTab(self.modules_widget, "模块")
        self.tab_widget.addTab(self.deps_widget, "依赖")
        layout.addWidget(self.tab_widget)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        button_box.accepted.connect(self.accept)
        layout.addWidget(button_box)

    def load_info(self):
        self.modules_table.setRowCount(0)
        self.deps_table.setRowCount(0)

        pack_info = get_full_pack_info(self.pack_folder)
        folder_name = os.path.basename(self.pack_folder)
        if pack_info:
            name = pack_info.get("name", "未知")
            desc = pack_info.get("description", "无描述")
            uuid = pack_info.get("uuid", "未知")
            version = pack_info.get("version", "未知")
            min_engine = pack_info.get("min_engine_version", "未指定")
            authors = ", ".join(pack_info.get("authors", [])) if pack_info.get("authors") else "无"
            license_info = pack_info.get("license", "未知")
            url = pack_info.get("url", "")
        else:
            name = "读取失败"
            desc = "无法解析 manifest.json"
            uuid = "未知"
            version = "未知"
            min_engine = "未知"
            authors = "未知"
            license_info = "未知"
            url = ""
        size_bytes = get_folder_size(self.pack_folder)
        size_str = format_file_size(size_bytes)
        active_status = "已激活" if self.is_active else "未激活"
        self.basic_layout.addRow("📦 包名称:", QLabel(f"<b>{name}</b>"))
        self.basic_layout.addRow("📄 描述:", QLabel(desc))
        self.basic_layout.addRow("🆔 UUID:", QLabel(uuid))
        self.basic_layout.addRow("🔢 版本:", QLabel(version))
        self.basic_layout.addRow("📁 文件夹:", QLabel(folder_name))
        self.basic_layout.addRow("🎨 类型:", QLabel("资源包" if self.pack_type == "resource" else "行为包"))
        self.basic_layout.addRow("✅ 激活状态:", QLabel(active_status))
        self.basic_layout.addRow("💾 大小:", QLabel(size_str))
        self.basic_layout.addRow("⚙️ 最低引擎版本:", QLabel(str(min_engine)))
        self.basic_layout.addRow("👥 作者:", QLabel(authors))
        self.basic_layout.addRow("📜 许可证:", QLabel(license_info))
        if url:
            self.basic_layout.addRow("🔗 网址:", QLabel(f'<a href="{url}">{url}</a>'))

        if pack_info and pack_info.get("modules"):
            modules = pack_info["modules"]
            self.modules_table.setRowCount(len(modules))
            for i, mod in enumerate(modules):
                mod_type = mod.get("type", "未知")
                mod_version = mod.get("version", [])
                if isinstance(mod_version, list):
                    mod_version = ".".join(map(str, mod_version))
                entry = mod.get("entry", "") or mod.get("script", "") or "—"
                item_type = QTableWidgetItem(mod_type)
                item_type.setTextAlignment(Qt.AlignCenter)
                item_version = QTableWidgetItem(str(mod_version))
                item_version.setTextAlignment(Qt.AlignCenter)
                item_entry = QTableWidgetItem(str(entry))
                item_entry.setTextAlignment(Qt.AlignCenter)
                self.modules_table.setItem(i, 0, item_type)
                self.modules_table.setItem(i, 1, item_version)
                self.modules_table.setItem(i, 2, item_entry)
        else:
            self.modules_table.setRowCount(1)
            item = QTableWidgetItem("无模块信息")
            item.setTextAlignment(Qt.AlignCenter)
            self.modules_table.setItem(0, 0, item)
            self.modules_table.setSpan(0, 0, 1, 3)

        if pack_info and pack_info.get("dependencies"):
            deps = pack_info["dependencies"]
            self.deps_table.setRowCount(len(deps))
            for i, dep in enumerate(deps):
                dep_uuid = dep.get("uuid", "未知")
                dep_version = dep.get("version", [])
                if isinstance(dep_version, list):
                    dep_version = ".".join(map(str, dep_version))
                item_uuid = QTableWidgetItem(dep_uuid)
                item_uuid.setTextAlignment(Qt.AlignCenter)
                item_ver = QTableWidgetItem(str(dep_version))
                item_ver.setTextAlignment(Qt.AlignCenter)
                self.deps_table.setItem(i, 0, item_uuid)
                self.deps_table.setItem(i, 1, item_ver)
        else:
            self.deps_table.setRowCount(1)
            item = QTableWidgetItem("无依赖")
            item.setTextAlignment(Qt.AlignCenter)
            self.deps_table.setItem(0, 0, item)
            self.deps_table.setSpan(0, 0, 1, 2)

# ---------- 服务器进程线程 ----------
class ServerProcess(QThread):
    output_received = pyqtSignal(str)
    process_stopped = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(self, server_exe, work_dir):
        super().__init__()
        self.server_exe = server_exe
        self.work_dir = work_dir
        self.process = None
        self._stop_event = threading.Event()

    def run(self):
        self._stop_event.clear()
        try:
            self.process = subprocess.Popen(
                [self.server_exe],
                cwd=self.work_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        except Exception as e:
            log_error(f"启动服务器进程失败: {e}")
            self.error_occurred.emit(f"启动失败: {e}")
            self.process_stopped.emit()
            return

        for line in iter(self.process.stdout.readline, ""):
            if self._stop_event.is_set():
                break
            self.output_received.emit(line.rstrip())
        self.process.stdout.close()
        retcode = self.process.wait()
        if retcode != 0 and not self._stop_event.is_set():
            log_error(f"服务器异常退出，返回码: {retcode}")
            self.error_occurred.emit(f"服务器异常退出，返回码: {retcode}")
        self.process_stopped.emit()

    def send_command(self, command):
        if self.process and self.process.stdin and not self._stop_event.is_set():
            try:
                self.process.stdin.write(command + "\n")
                self.process.stdin.flush()
            except Exception as e:
                log_error(f"发送命令失败: {e}")

    def stop_server(self):
        if self.process:
            try:
                self.send_command("stop")
            except Exception:
                pass
            self._stop_event.set()
            for _ in range(50):
                if self.process.poll() is not None:
                    break
                time.sleep(0.1)
            if self.process.poll() is None:
                log_warning("服务器未响应stop命令，强制终止")
                self.process.terminate()
                time.sleep(1)
                if self.process.poll() is None:
                    self.process.kill()
        self._stop_event.set()

# ---------- 系统资源监视器（带折线图）----------
class SystemMonitor(QGroupBox):
    def __init__(self, parent=None, interval=2000, history_length=60):
        super().__init__("📊 系统资源监视", parent)
        self.interval = interval
        self.history_length = history_length
        self.cpu_history = deque(maxlen=history_length)
        self.mem_history = deque(maxlen=history_length)
        self.last_net_io = None
        self.last_update_time = time.time()
        self.init_ui()
        self.setup_monitoring(interval)

    def init_ui(self):
        main_layout = QVBoxLayout(self)

        stats_widget = QWidget()
        stats_layout = QGridLayout(stats_widget)

        self.cpu_label = QLabel("CPU:")
        self.cpu_value = QLabel("--%")
        self.cpu_progress = QProgressBar()
        self.cpu_progress.setRange(0, 100)

        self.memory_label = QLabel("内存:")
        self.memory_value = QLabel("--/-- GB (--%)")
        self.memory_progress = QProgressBar()
        self.memory_progress.setRange(0, 100)

        self.network_label = QLabel("网络:")
        self.network_value = QLabel("↑ -- KB/s ↓ -- KB/s")

        self.disk_label = QLabel("磁盘:")
        self.disk_value = QLabel("--/-- GB (--%)")
        self.disk_progress = QProgressBar()
        self.disk_progress.setRange(0, 100)

        stats_layout.addWidget(self.cpu_label, 0, 0)
        stats_layout.addWidget(self.cpu_value, 0, 1)
        stats_layout.addWidget(self.cpu_progress, 0, 2)
        stats_layout.addWidget(self.memory_label, 1, 0)
        stats_layout.addWidget(self.memory_value, 1, 1)
        stats_layout.addWidget(self.memory_progress, 1, 2)
        stats_layout.addWidget(self.network_label, 2, 0)
        stats_layout.addWidget(self.network_value, 2, 1, 1, 2)
        stats_layout.addWidget(self.disk_label, 3, 0)
        stats_layout.addWidget(self.disk_value, 3, 1)
        stats_layout.addWidget(self.disk_progress, 3, 2)
        stats_layout.setColumnStretch(2, 1)

        main_layout.addWidget(stats_widget)

        if MATPLOTLIB_AVAILABLE:
            bg_color = '#2b2b2b' if self.palette().window().color().name() == '#2b2b2b' else '#f5f5f5'
            self.figure = Figure(figsize=(5, 4), dpi=100, facecolor=bg_color)
            self.canvas = FigureCanvas(self.figure)
            self.ax_cpu = self.figure.add_subplot(211)
            self.ax_mem = self.figure.add_subplot(212)
            self.ax_cpu.set_ylabel('CPU %')
            self.ax_mem.set_ylabel('内存 %')
            self.ax_cpu.set_xlim(0, self.history_length)
            self.ax_mem.set_xlim(0, self.history_length)
            self.ax_cpu.set_ylim(0, 100)
            self.ax_mem.set_ylim(0, 100)
            self.ax_cpu.set_title('CPU 使用率历史')
            self.ax_mem.set_title('内存使用率历史')
            for ax in [self.ax_cpu, self.ax_mem]:
                ax.tick_params(colors='white' if bg_color == '#2b2b2b' else 'black')
                ax.title.set_color('white' if bg_color == '#2b2b2b' else 'black')
                ax.xaxis.label.set_color('white' if bg_color == '#2b2b2b' else 'black')
                ax.yaxis.label.set_color('white' if bg_color == '#2b2b2b' else 'black')
                ax.set_facecolor(bg_color)
            self.figure.tight_layout(pad=1.5)
            for _ in range(self.history_length):
                self.cpu_history.append(0)
                self.mem_history.append(0)
            self.line_cpu, = self.ax_cpu.plot(range(self.history_length), list(self.cpu_history), color='#4CAF50', linewidth=1.5)
            self.line_mem, = self.ax_mem.plot(range(self.history_length), list(self.mem_history), color='#2196F3', linewidth=1.5)
            main_layout.addWidget(self.canvas)
        else:
            no_chart_label = QLabel("折线图不可用：请安装 matplotlib (pip install matplotlib)")
            no_chart_label.setWordWrap(True)
            no_chart_label.setStyleSheet("color: #ffaa55; padding: 10px;")
            main_layout.addWidget(no_chart_label)

    def setup_monitoring(self, interval=2000):
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_system_info)
        self.timer.start(interval)

    def update_interval(self, interval):
        self.interval = interval
        if hasattr(self, 'timer') and self.timer.isActive():
            self.timer.stop()
            self.timer.start(interval)

    def stop_monitoring(self):
        """停止资源监视定时器"""
        if hasattr(self, 'timer') and self.timer.isActive():
            self.timer.stop()

    def update_system_info(self):
        try:
            cpu_percent = psutil.cpu_percent(interval=None)
            self.cpu_value.setText(f"{cpu_percent:.1f}%")
            self.cpu_progress.setValue(int(cpu_percent))
            self.cpu_history.append(cpu_percent)

            memory = psutil.virtual_memory()
            memory_used_gb = memory.used / (1024**3)
            memory_total_gb = memory.total / (1024**3)
            memory_percent = memory.percent
            self.memory_value.setText(f"{memory_used_gb:.1f}/{memory_total_gb:.1f} GB ({memory_percent:.1f}%)")
            self.memory_progress.setValue(int(memory_percent))
            self.mem_history.append(memory_percent)

            current_time = time.time()
            net_io = psutil.net_io_counters()
            if self.last_net_io is not None:
                time_diff = current_time - self.last_update_time
                if time_diff > 0:
                    upload_speed = (net_io.bytes_sent - self.last_net_io.bytes_sent) / time_diff / 1024
                    download_speed = (net_io.bytes_recv - self.last_net_io.bytes_recv) / time_diff / 1024
                    self.network_value.setText(f"↑ {upload_speed:.1f} KB/s ↓ {download_speed:.1f} KB/s")
            self.last_net_io = net_io
            self.last_update_time = current_time

            disk = psutil.disk_usage('/')
            disk_used_gb = disk.used / (1024**3)
            disk_total_gb = disk.total / (1024**3)
            disk_percent = disk.percent
            self.disk_value.setText(f"{disk_used_gb:.1f}/{disk_total_gb:.1f} GB ({disk_percent:.1f}%)")
            self.disk_progress.setValue(int(disk_percent))

            if MATPLOTLIB_AVAILABLE:
                self.line_cpu.set_ydata(list(self.cpu_history))
                self.line_mem.set_ydata(list(self.mem_history))
                current_len = len(self.cpu_history)
                if current_len == self.history_length:
                    self.ax_cpu.set_xlim(0, self.history_length)
                    self.ax_mem.set_xlim(0, self.history_length)
                else:
                    self.ax_cpu.set_xlim(0, current_len)
                    self.ax_mem.set_xlim(0, current_len)
                self.figure.canvas.draw_idle()
        except Exception as e:
            log_debug(f"系统资源更新失败: {e}")

# ---------- 主题管理器 ----------
class ThemeManager:
    def __init__(self):
        self.themes = {
            "dark": self.get_dark_theme(),
            "light": self.get_light_theme(),
            "custom": self.get_dark_theme()
        }

    def get_dark_theme(self):
        return """
            QMainWindow, QWidget {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #555;
                border-radius: 8px;
                margin-top: 1ex;
                padding-top: 10px;
                background-color: #363636;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px;
                color: #4CAF50;
            }
            QPushButton {
                background-color: #4CAF50;
                border: none;
                color: white;
                padding: 6px 12px;
                border-radius: 4px;
                font-weight: bold;
                min-width: 70px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #666;
                color: #999;
            }
            QPushButton.danger {
                background-color: #f44336;
            }
            QPushButton.danger:hover {
                background-color: #da190b;
            }
            QLineEdit, QComboBox, QTextEdit, QListWidget, QTableWidget {
                padding: 8px;
                border: 2px solid #555;
                border-radius: 4px;
                background-color: #404040;
                color: #ffffff;
                font-size: 12px;
            }
            QLineEdit:focus, QComboBox:focus {
                border-color: #4CAF50;
            }
            QTableWidget::item {
                padding: 6px;
            }
            QCheckBox {
                spacing: 8px;
                color: #ccc;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
            }
            QCheckBox::indicator:unchecked {
                border: 2px solid #555;
                background-color: #404040;
                border-radius: 3px;
            }
            QCheckBox::indicator:checked {
                border: 2px solid #4CAF50;
                background-color: #4CAF50;
                border-radius: 3px;
            }
            QTabWidget::pane {
                border: 1px solid #555;
                background-color: #363636;
            }
            QTabBar::tab {
                background-color: #404040;
                color: white;
                padding: 8px 16px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background-color: #4CAF50;
                color: white;
            }
            QTabBar::tab:hover:!selected {
                background-color: #555;
            }
            QHeaderView::section {
                background-color: #2d4a2d;
                padding: 6px;
                border: none;
                font-weight: bold;
                color: #4CAF50;
            }
            QScrollBar:vertical {
                background-color: #2b2b2b;
                width: 15px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background-color: #555;
                border-radius: 7px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #777;
            }
            QProgressBar {
                border: 2px solid #555;
                border-radius: 5px;
                text-align: center;
                color: white;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                width: 20px;
            }
        """

    def get_light_theme(self):
        return """
            QMainWindow, QWidget {
                background-color: #f5f5f5;
                color: #333333;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #cccccc;
                border-radius: 8px;
                margin-top: 1ex;
                padding-top: 10px;
                background-color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px;
                color: #2e7d32;
            }
            QPushButton {
                background-color: #4CAF50;
                border: none;
                color: white;
                padding: 6px 12px;
                border-radius: 4px;
                font-weight: bold;
                min-width: 70px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #999999;
            }
            QPushButton.danger {
                background-color: #f44336;
            }
            QPushButton.danger:hover {
                background-color: #da190b;
            }
            QLineEdit, QComboBox, QTextEdit, QListWidget, QTableWidget {
                padding: 8px;
                border: 2px solid #cccccc;
                border-radius: 4px;
                background-color: #ffffff;
                color: #333333;
                font-size: 12px;
            }
            QLineEdit:focus, QComboBox:focus {
                border-color: #4CAF50;
            }
            QTableWidget::item {
                padding: 6px;
            }
            QCheckBox {
                spacing: 8px;
                color: #333333;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
            }
            QCheckBox::indicator:unchecked {
                border: 2px solid #cccccc;
                background-color: #ffffff;
                border-radius: 3px;
            }
            QCheckBox::indicator:checked {
                border: 2px solid #4CAF50;
                background-color: #4CAF50;
                border-radius: 3px;
            }
            QTabWidget::pane {
                border: 1px solid #cccccc;
                background-color: #ffffff;
            }
            QTabBar::tab {
                background-color: #f0f0f0;
                color: #333333;
                padding: 8px 16px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background-color: #4CAF50;
                color: white;
            }
            QTabBar::tab:hover:!selected {
                background-color: #e0e0e0;
            }
            QHeaderView::section {
                background-color: #e0e0e0;
                padding: 6px;
                border: none;
                font-weight: bold;
                color: #2e7d32;
            }
            QScrollBar:vertical {
                background-color: #f5f5f5;
                width: 15px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background-color: #cccccc;
                border-radius: 7px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #aaaaaa;
            }
            QProgressBar {
                border: 2px solid #cccccc;
                border-radius: 5px;
                text-align: center;
                color: #333333;
                font-weight: bold;
                background-color: #ffffff;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                width: 20px;
            }
        """

    def get_custom_theme(self, colors):
        bg = colors.get("background", "#2b2b2b")
        text = colors.get("text", "#ffffff")
        accent = colors.get("accent", "#4CAF50")
        border = colors.get("border", "#555555")
        group_bg = colors.get("group_bg", "#363636")
        input_bg = colors.get("input_bg", "#404040")
        button_bg = colors.get("button_bg", "#4CAF50")
        button_hover = colors.get("button_hover", "#45a049")
        return f"""
            QMainWindow, QWidget {{
                background-color: {bg};
                color: {text};
            }}
            QGroupBox {{
                font-weight: bold;
                border: 2px solid {border};
                border-radius: 8px;
                margin-top: 1ex;
                padding-top: 10px;
                background-color: {group_bg};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 8px;
                color: {accent};
            }}
            QPushButton {{
                background-color: {button_bg};
                border: none;
                color: white;
                padding: 6px 12px;
                border-radius: 4px;
                font-weight: bold;
                min-width: 70px;
            }}
            QPushButton:hover {{
                background-color: {button_hover};
            }}
            QPushButton:disabled {{
                background-color: #666;
                color: #999;
            }}
            QPushButton.danger {{
                background-color: #f44336;
            }}
            QPushButton.danger:hover {{
                background-color: #da190b;
            }}
            QLineEdit, QComboBox, QTextEdit, QListWidget, QTableWidget {{
                padding: 8px;
                border: 2px solid {border};
                border-radius: 4px;
                background-color: {input_bg};
                color: {text};
                font-size: 12px;
            }}
            QLineEdit:focus, QComboBox:focus {{
                border-color: {accent};
            }}
            QTableWidget::item {{
                padding: 6px;
            }}
            QCheckBox {{
                spacing: 8px;
                color: {text};
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
            }}
            QCheckBox::indicator:unchecked {{
                border: 2px solid {border};
                background-color: {input_bg};
                border-radius: 3px;
            }}
            QCheckBox::indicator:checked {{
                border: 2px solid {accent};
                background-color: {accent};
                border-radius: 3px;
            }}
            QTabWidget::pane {{
                border: 1px solid {border};
                background-color: {group_bg};
            }}
            QTabBar::tab {{
                background-color: {input_bg};
                color: {text};
                padding: 8px 16px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }}
            QTabBar::tab:selected {{
                background-color: {accent};
                color: white;
            }}
            QTabBar::tab:hover:!selected {{
                background-color: {border};
            }}
            QHeaderView::section {{
                background-color: {input_bg};
                padding: 6px;
                border: none;
                font-weight: bold;
                color: {accent};
            }}
            QScrollBar:vertical {{
                background-color: {bg};
                width: 15px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {border};
                border-radius: 7px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {accent};
            }}
            QProgressBar {{
                border: 2px solid {border};
                border-radius: 5px;
                text-align: center;
                color: {text};
                font-weight: bold;
            }}
            QProgressBar::chunk {{
                background-color: {accent};
                width: 20px;
            }}
        """

    def set_custom_colors(self, colors):
        self.themes["custom"] = self.get_custom_theme(colors)

    def get_theme(self, name):
        return self.themes.get(name, self.themes["dark"])

# ---------- 设置标签页 ----------
class SettingsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.init_ui()

    def init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # --- 主题 ---
        theme_group = QGroupBox("🎨 主题")
        theme_layout = QHBoxLayout()
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["auto", "dark", "light", "custom"])
        self.theme_combo.currentTextChanged.connect(self.parent.on_theme_changed)
        theme_layout.addWidget(QLabel("选择主题:"))
        theme_layout.addWidget(self.theme_combo)
        theme_layout.addStretch()
        theme_group.setLayout(theme_layout)
        layout.addWidget(theme_group)

        # --- 自定义颜色 ---
        self.custom_group = QGroupBox("🎨 自定义颜色")
        custom_layout = QGridLayout()
        self.color_buttons = {}
        colors_def = [
            ("background", "背景色"), ("text", "文字色"), ("accent", "强调色"),
            ("border", "边框色"), ("group_bg", "组背景"), ("input_bg", "输入框背景"),
            ("button_bg", "按钮背景"), ("button_hover", "按钮悬停")
        ]
        for i, (key, label) in enumerate(colors_def):
            btn = QPushButton()
            btn.setFixedSize(60, 30)
            btn.clicked.connect(lambda _, k=key: self.parent.choose_custom_color(k))
            self.color_buttons[key] = btn
            custom_layout.addWidget(QLabel(label), i // 4, (i % 4) * 2)
            custom_layout.addWidget(btn, i // 4, (i % 4) * 2 + 1)
        self.apply_custom_btn = QPushButton("应用自定义颜色")
        self.apply_custom_btn.clicked.connect(self.parent.apply_custom_theme)
        custom_layout.addWidget(self.apply_custom_btn, 2, 0, 1, 8)
        self.custom_group.setLayout(custom_layout)
        # 切换主题时显示/隐藏自定义颜色
        self.theme_combo.currentTextChanged.connect(
            lambda t: self.custom_group.setVisible(t == "custom"))
        layout.addWidget(self.custom_group)

        # --- 服务器路径 ---
        server_group = QGroupBox("📂 服务器路径")
        server_layout = QHBoxLayout()
        self.server_dir_edit = QLineEdit()
        browse_dir_btn = QPushButton("浏览")
        browse_dir_btn.clicked.connect(self.browse_server_dir)
        server_layout.addWidget(QLabel("服务器文件夹:"))
        server_layout.addWidget(self.server_dir_edit)
        server_layout.addWidget(browse_dir_btn)
        server_group.setLayout(server_layout)
        layout.addWidget(server_group)

        # --- 服务端程序 ---
        exe_group = QGroupBox("⚙️ 服务端程序")
        exe_layout = QHBoxLayout()
        self.server_exe_edit = QLineEdit()
        browse_exe_btn = QPushButton("浏览")
        browse_exe_btn.clicked.connect(self.browse_server_exe)
        exe_layout.addWidget(QLabel("可执行文件:"))
        exe_layout.addWidget(self.server_exe_edit)
        exe_layout.addWidget(browse_exe_btn)
        exe_group.setLayout(exe_layout)
        layout.addWidget(exe_group)

        # --- 自动备份 ---
        backup_group = QGroupBox("💾 自动备份")
        backup_layout = QHBoxLayout()
        self.backup_interval = QSpinBox()
        self.backup_interval.setRange(0, 1440)
        self.backup_interval.setSuffix(" 分钟")
        self.backup_interval.setToolTip("0 = 禁用自动备份")
        backup_layout.addWidget(QLabel("备份间隔:"))
        backup_layout.addWidget(self.backup_interval)
        backup_layout.addStretch()
        backup_group.setLayout(backup_layout)
        layout.addWidget(backup_group)

        # --- 系统监视 ---
        monitor_group = QGroupBox("📊 系统资源监视")
        monitor_layout = QHBoxLayout()
        self.monitor_interval = QSpinBox()
        self.monitor_interval.setRange(500, 10000)
        self.monitor_interval.setSuffix(" 毫秒")
        self.monitor_interval.setToolTip("系统资源监视器更新频率")
        monitor_layout.addWidget(QLabel("更新间隔:"))
        monitor_layout.addWidget(self.monitor_interval)
        monitor_layout.addStretch()
        monitor_group.setLayout(monitor_layout)
        layout.addWidget(monitor_group)

        # --- 内存告警 ---
        mem_group = QGroupBox("⚠️ 内存告警")
        mem_layout = QHBoxLayout()
        self.mem_warn = QSpinBox()
        self.mem_warn.setRange(50, 99)
        self.mem_warn.setSuffix(" %")
        self.mem_warn.setToolTip("内存使用率超过此阈值时弹出告警")
        mem_layout.addWidget(QLabel("告警阈值:"))
        mem_layout.addWidget(self.mem_warn)
        mem_layout.addStretch()
        mem_group.setLayout(mem_layout)
        layout.addWidget(mem_group)

        # --- 高分屏 ---
        dpi_group = QGroupBox("🖥️ 高分屏适配")
        dpi_layout = QHBoxLayout()
        self.hidpi_cb = QCheckBox("启用高分屏缩放（需重启程序生效）")
        dpi_layout.addWidget(self.hidpi_cb)
        dpi_group.setLayout(dpi_layout)
        layout.addWidget(dpi_group)

        # --- 保存按钮 ---
        save_row = QHBoxLayout()
        save_row.addStretch()
        btn_save = QPushButton("💾 保存设置")
        btn_save.setStyleSheet("font-weight: bold; min-height: 32px; padding: 6px 24px;")
        btn_save.clicked.connect(self.save_settings)
        save_row.addWidget(btn_save)
        save_row.addStretch()
        layout.addLayout(save_row)

        layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll)

        self.load_config()

    def browse_server_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择服务器文件夹", SCRIPT_DIR)
        if path:
            self.server_dir_edit.setText(os.path.relpath(path, SCRIPT_DIR) if path.startswith(SCRIPT_DIR) else path)

    def browse_server_exe(self):
        base_dir = self.parent.get_absolute_server_dir()
        path, _ = QFileDialog.getOpenFileName(self, "选择服务端程序", base_dir, "Executable (*.exe);;All Files (*)")
        if path:
            rel = os.path.relpath(path, base_dir)
            self.server_exe_edit.setText(rel)

    def load_config(self):
        self.theme_combo.setCurrentText(self.parent.config.get("theme", "auto"))
        self.server_dir_edit.setText(self.parent.config.get("server_dir", "Server"))
        self.server_exe_edit.setText(self.parent.config.get("server_exe", "bedrock_server.exe"))
        self.backup_interval.setValue(self.parent.config.get("backup_interval", 60))
        self.monitor_interval.setValue(self.parent.config.get("monitor_interval", 2000))
        self.mem_warn.setValue(self.parent.config.get("mem_warn_threshold", 80))
        self.hidpi_cb.setChecked(self.parent.config.get("hidpi_enabled", True))
        self.custom_group.setVisible(self.theme_combo.currentText() == "custom")
        for key, btn in self.color_buttons.items():
            color = self.parent.custom_colors.get(key, "#2b2b2b")
            btn.setStyleSheet(f"background-color: {color}; border: 1px solid #888;")

    def save_settings(self):
        new_dir = self.server_dir_edit.text().strip()
        new_exe = self.server_exe_edit.text().strip()
        abs_dir = os.path.join(SCRIPT_DIR, new_dir) if not os.path.isabs(new_dir) else new_dir
        if not os.path.isdir(abs_dir):
            toast_error("路径无效", f"服务器目录不存在")
            return
        exe_path = os.path.join(abs_dir, new_exe)
        if not os.path.isfile(exe_path):
            reply = QMessageBox.question(
                self, "文件不存在",
                f"指定的服务器程序不存在：\n{exe_path}\n\n仍要保存设置吗？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return

        self.parent.config["theme"] = self.theme_combo.currentText()
        self.parent.config["server_dir"] = new_dir
        self.parent.config["server_exe"] = new_exe
        self.parent.config["backup_interval"] = self.backup_interval.value()
        self.parent.config["monitor_interval"] = self.monitor_interval.value()
        self.parent.config["mem_warn_threshold"] = self.mem_warn.value()
        self.parent.config["hidpi_enabled"] = self.hidpi_cb.isChecked()
        self.parent.save_config()
        self.parent.apply_theme(self.parent.config["theme"])
        self.parent.apply_monitor_interval(self.parent.config["monitor_interval"])
        self.parent.init_watcher()
        self.parent.update_backup_timer()
        toast_success("设置已保存", "新设置已生效")

# ---------- 后台工作线程（用于耗时操作）----------
class BaseWorker(QThread):
    """通用后台工作者基类，带进度和完成信号"""
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)  # success, message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel = False

    def cancel(self):
        self._cancel = True

class BackupWorker(BaseWorker):
    def __init__(self, level_name, world_path, backup_dir, parent=None):
        super().__init__(parent)
        self.level_name = level_name
        self.world_path = world_path
        self.backup_dir = backup_dir

    def run(self):
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"{self.level_name}_{timestamp}.zip"
            backup_path = os.path.join(self.backup_dir, backup_name)
            self.progress.emit(f"正在备份 {self.level_name} 到 {backup_name} ...")
            # 使用shutil.make_archive更快，但这里用zipfile保持与原逻辑一致
            with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                total_files = 0
                for root, dirs, files in os.walk(self.world_path):
                    for file in files:
                        if self._cancel:
                            self.finished.emit(False, "备份已取消")
                            return
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, os.path.dirname(self.world_path))
                        zipf.write(file_path, arcname)
                        total_files += 1
                        if total_files % 100 == 0:
                            self.progress.emit(f"已打包 {total_files} 个文件...")
            self.progress.emit(f"备份完成: {backup_name}")
            toast_success("备份完成", backup_name)
            self.finished.emit(True, f"备份成功: {backup_name}")
        except Exception as e:
            log_error(f"备份失败: {e}")
            toast_error("备份失败", str(e))
            self.finished.emit(False, f"备份失败: {e}")

class RestoreWorker(BaseWorker):
    def __init__(self, level_name, world_path, backup_path, parent=None):
        super().__init__(parent)
        self.level_name = level_name
        self.world_path = world_path
        self.backup_path = backup_path

    def run(self):
        try:
            # 先验证备份 zip 完整性
            self.progress.emit("正在验证备份文件...")
            if not zipfile.is_zipfile(self.backup_path):
                self.finished.emit(False, "备份文件已损坏或不是有效的 ZIP 文件")
                return

            # 测试 zip 完整性
            bad_file = None
            try:
                with zipfile.ZipFile(self.backup_path, 'r') as test_zf:
                    bad_file = test_zf.testzip()
            except zipfile.BadZipFile:
                self.finished.emit(False, "备份文件已损坏，无法读取")
                return

            if bad_file:
                self.finished.emit(False, f"备份文件中的 {bad_file} 已损坏，还原已中止")
                return

            # 验证通过，开始还原
            self.progress.emit("正在清空当前世界...")
            # 先移到临时目录而非直接删除（安全回滚）
            temp_backup = None
            if os.path.exists(self.world_path) and os.listdir(self.world_path):
                import tempfile
                temp_backup = tempfile.mkdtemp(prefix="world_restore_backup_",
                                               dir=os.path.dirname(self.world_path))
                for item in os.listdir(self.world_path):
                    if self._cancel:
                        self.finished.emit(False, "还原已取消")
                        return
                    item_path = os.path.join(self.world_path, item)
                    dest = os.path.join(temp_backup, item)
                    shutil.move(item_path, dest)

            self.progress.emit("正在解压备份...")
            with zipfile.ZipFile(self.backup_path, 'r') as zipf:
                zipf.extractall(os.path.dirname(self.world_path))

            # 清理临时备份
            if temp_backup and os.path.exists(temp_backup):
                shutil.rmtree(temp_backup, ignore_errors=True)

            self.progress.emit("还原完成")
            self.finished.emit(True, f"世界已从 {os.path.basename(self.backup_path)} 还原")
        except Exception as e:
            log_error(f"还原失败: {e}")
            self.finished.emit(False, f"还原失败: {e}")

class CopyPackWorker(BaseWorker):
    def __init__(self, src_path, dest_path, pack_type, world_path, parent=None):
        super().__init__(parent)
        self.src_path = src_path
        self.dest_path = dest_path
        self.pack_type = pack_type
        self.world_path = world_path

    def run(self):
        try:
            self.progress.emit(f"正在复制包到服务器...")
            shutil.copytree(self.src_path, self.dest_path)
            self.progress.emit("复制完成，正在读取 manifest...")
            # 尝试读取manifest
            uuid, version = get_pack_manifest(self.dest_path, retry=10, delay=0.2)
            if not uuid:
                self.finished.emit(False, "无法读取 manifest.json，包未自动激活。")
                return
            # 自动激活
            if self.world_path and os.path.exists(self.world_path):
                success = register_pack_to_world(self.world_path, self.pack_type, os.path.basename(self.dest_path), uuid, version)
                if success:
                    self.progress.emit("包已激活到当前世界")
                else:
                    self.progress.emit("包已在激活列表中")
            self.finished.emit(True, f"包 {os.path.basename(self.dest_path)} 添加成功")
        except Exception as e:
            log_error(f"复制包失败: {e}")
            self.finished.emit(False, f"复制包失败: {e}")

class RemovePackWorker(BaseWorker):
    def __init__(self, pack_path, pack_type, world_path, pack_uuid, parent=None):
        super().__init__(parent)
        self.pack_path = pack_path
        self.pack_type = pack_type
        self.world_path = world_path
        self.pack_uuid = pack_uuid

    def run(self):
        try:
            if self.pack_uuid and self.world_path and os.path.exists(self.world_path):
                self.progress.emit("正在从世界注销包...")
                unregister_pack_from_world(self.world_path, self.pack_type, self.pack_uuid)
            self.progress.emit("正在删除包文件夹...")
            shutil.rmtree(self.pack_path, ignore_errors=True)
            self.progress.emit("删除完成")
            self.finished.emit(True, f"包 {os.path.basename(self.pack_path)} 已删除")
        except Exception as e:
            log_error(f"删除包失败: {e}")
            self.finished.emit(False, f"删除包失败: {e}")

# ---------- 服务器控制台标签页 ----------
class ConsoleTab(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.server_process = None
        self._auto_restart = False
        self._restart_count = 0
        self._restart_timer = QTimer()
        self._restart_timer.setSingleShot(True)
        self._restart_timer.timeout.connect(self._do_auto_restart)
        self._log_file = None
        self._init_log_file()
        # 命令历史
        self._cmd_history = []
        self._cmd_history_idx = -1
        # 玩家列表和 TPS
        self._players = {}     # {name: {"xuid": xuid, "joined": timestamp}}
        self._server_start_time = None
        self._bds_version = ""
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("▶ 启动服务器")
        self.start_btn.clicked.connect(self.start_server)
        self.stop_btn = QPushButton("⏹ 停止服务器")
        self.stop_btn.clicked.connect(self.stop_server)
        self.stop_btn.setEnabled(False)
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        btn_layout.addStretch()
        self.auto_restart_cb = QCheckBox("崩溃自动重启（最多5次）")
        self.auto_restart_cb.setToolTip("服务器异常退出后自动重新启动")
        self.auto_restart_cb.toggled.connect(lambda v: setattr(self, '_auto_restart', v))
        btn_layout.addWidget(self.auto_restart_cb)
        layout.addLayout(btn_layout)

        self.output_area = QTextEdit()
        self.output_area.setReadOnly(True)
        self.output_area.setFont(QFont("Consolas", 10))
        layout.addWidget(QLabel("服务器输出:"))
        layout.addWidget(self.output_area)

        cmd_layout = QHBoxLayout()
        self.cmd_input = QLineEdit()
        self.cmd_input.setPlaceholderText("输入命令 (如 stop, list, op <玩家名>) 并按回车发送")
        self.cmd_input.returnPressed.connect(self.send_command)
        # 命令历史：上下箭头翻页
        self.cmd_input.installEventFilter(self)
        self.cmd_input._console_tab = self
        cmd_layout.addWidget(self.cmd_input)
        layout.addLayout(cmd_layout)

    def eventFilter(self, obj, event):
        """命令输入框的按键历史"""
        if obj is self.cmd_input and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Up:
                if self._cmd_history and self._cmd_history_idx < len(self._cmd_history) - 1:
                    self._cmd_history_idx += 1
                    idx = len(self._cmd_history) - 1 - self._cmd_history_idx
                    self.cmd_input.setText(self._cmd_history[idx])
                return True
            elif event.key() == Qt.Key_Down:
                if self._cmd_history_idx > 0:
                    self._cmd_history_idx -= 1
                    idx = len(self._cmd_history) - 1 - self._cmd_history_idx
                    self.cmd_input.setText(self._cmd_history[idx])
                elif self._cmd_history_idx == 0:
                    self._cmd_history_idx = -1
                    self.cmd_input.clear()
                return True
        return super().eventFilter(obj, event)

    def append_output(self, text):
        # 1. 定义颜色规则（按优先级从高到低匹配）
        rules = [
            # 严重错误（最高优先级）
            (re.compile(r'(?:ERROR|FATAL|Exception|Traceback|失败|崩溃|crash)', re.I), '#ff3333', True),
            # 警告
            (re.compile(r'(?:WARN|WARNING|警告|deprecated)', re.I), '#ffaa33', True),
            # 成功/启动/加载完成
            (re.compile(r'(?:Server started|Done|Started|Loaded|成功|完成|✅)', re.I), '#55ff55', True),
            # 玩家连接/生成
            (re.compile(r'Player (?:connected|Spawned):', re.I), '#66ccff', True),
            # 玩家断开
            (re.compile(r'Player disconnected:', re.I), '#ff66aa', True),
            # OP/Deop/权限变更
            (re.compile(r'(?:Opped|De-opped|Permission)', re.I), '#ffdd44', True),
            # 命令执行（行首 >）
            (re.compile(r'^>\s', re.M), '#ffaa00', False),
            # 世界保存
            (re.compile(r'(?:Saving|Saved|save complete)', re.I), '#aaddff', True),
            # 自动保存 / 备份
            (re.compile(r'(?:Autosave|backup|Backup)', re.I), '#88cc88', True),
            # 服务器版本/核心信息
            (re.compile(r'(?:Version|v\d+\.\d+\.\d+|Bedrock)', re.I), '#88ddff', True),
            # 玩家列表/数量
            (re.compile(r'(?:There are \d+ of|players online|\d+ players)', re.I), '#aaffaa', True),
            # 网络/端口绑定
            (re.compile(r'(?:port|bind|listening|UDP|IPv[46])', re.I), '#dd88ff', True),
            # 世界加载/区块
            (re.compile(r'(?:Loading|level|chunk|dimension|world)', re.I), '#ccddff', True),
            # 遥测
            (re.compile(r'(?:TELEMETRY|telemetry)', re.I), '#888888', True),
        ]

        # 2. 依次匹配规则
        matched = False
        for pattern, color, full_match in rules:
            if full_match:
                if pattern.search(text):
                    self.output_area.append(f'<span style="color:{color};">{text}</span>')
                    matched = True
                    break
            else:
                if pattern.match(text):  # 行首匹配
                    self.output_area.append(f'<span style="color:{color};">{text}</span>')
                    matched = True
                    break

        # 3. 无匹配时，保留默认灰色，但可区分是否为错误输出的 stderr
        if not matched:
            # 可选：如果文本包含数字或方括号时间戳，给点淡紫色，增加可读性
            if re.search(r'\[\d{1,2}:\d{2}:\d{2}\]', text):
                self.output_area.append(f'<span style="color:#aaaaaa;">{text}</span>')  # 稍亮灰
            else:
                self.output_area.append(f'<span style="color:#888888;">{text}</span>')  # 普通灰

        # 自动滚动到底部
        scrollbar = self.output_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

        # 写入日志文件
        if self._log_file:
            try:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._log_file.write(f"[{ts}] {text}\n")
                self._log_file.flush()
            except Exception:
                pass

        # 同步输出到 cmd 窗口
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] [BDS] {text}", flush=True)

        # 解析玩家加入/离开事件
        self._parse_player_event(text)
        # 解析 BDS 版本
        m = re.search(r'Version:\s+(\d+\.\d+\.\d+\.\d+)', text)
        if m and not self._bds_version:
            self._bds_version = m.group(1)

    def _parse_player_event(self, text):
        """解析 BDS 玩家连接/生成/断开事件"""
        # "Player connected: Name, xuid: ..."
        m = re.search(r'Player connected:\s+([A-Za-z0-9_]+)', text, re.I)
        if m:
            name = m.group(1)
            self._players[name] = {"joined": time.time()}
            self.parent.server_stats["players"] = list(self._players.keys())
            toast_info("玩家加入", name)
            return
        # "Player Spawned: Name xuid: ..."  （没有逗号！）
        m = re.search(r'Player (?:S|s)pawned:\s+([A-Za-z0-9_]+)', text, re.I)
        if m:
            name = m.group(1)
            if name not in self._players:
                self._players[name] = {"joined": time.time()}
            self.parent.server_stats["players"] = list(self._players.keys())
            return
        # "Player disconnected: Name, xuid: ..."
        m = re.search(r'Player disconnected:\s+([A-Za-z0-9_]+)', text, re.I)
        if m:
            name = m.group(1)
            self._players.pop(name, None)
            self.parent.server_stats["players"] = list(self._players.keys())
            toast_info("玩家离开", name)

    def get_server_stats(self):
        """返回当前服务器状态汇总"""
        uptime = int(time.time() - self._server_start_time) if self._server_start_time else 0
        return {
            "running": self.is_server_running(),
            "uptime_seconds": uptime,
            "players": list(self._players.keys()),
            "player_count": len(self._players),
            "auto_restart": self._auto_restart,
            "bds_version": self._bds_version or _detect_current_version(get_server_dir()),
        }

    def _init_log_file(self):
        """初始化日志文件，按日期命名（脚本目录/logs/）"""
        try:
            log_dir = os.path.join(SCRIPT_DIR, "logs")
            os.makedirs(log_dir, exist_ok=True)
            date_str = datetime.now().strftime("%Y-%m-%d")
            log_path = os.path.join(log_dir, f"console_{date_str}.log")
            self._log_file = open(log_path, "a", encoding="utf-8")
            self._log_file.write(f"\n--- 会话开始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        except Exception:
            self._log_file = None

    def start_server(self):
        server_exe = self.parent.get_server_exe_path()
        if not os.path.exists(server_exe):
            toast_error("启动失败", f"找不到: {os.path.basename(server_exe)}")
            QMessageBox.critical(self, "错误", f"找不到服务器程序: {server_exe}\n请在设置中指定正确路径。")
            log_error(f"服务器程序不存在: {server_exe}")
            return
        self.server_process = ServerProcess(server_exe, self.parent.get_absolute_server_dir())
        self.server_process.output_received.connect(self.append_output)
        self.server_process.process_stopped.connect(self.on_server_stopped)
        self.server_process.error_occurred.connect(self.on_server_error)
        self.server_process.start()
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._server_start_time = time.time()
        self._players.clear()
        self._restart_count = 0
        log_success("服务器启动中...")
        self.append_output(">>> 服务器启动中... <<<")
        toast_info("服务器启动", "BDS 正在启动...")

    def stop_server(self):
        if self.server_process:
            log_info("正在停止服务器...")
            self.append_output(">>> 正在停止服务器... <<<")
            self.server_process.stop_server()

    def on_server_stopped(self):
        if self.start_btn.isEnabled():
            return  # 防重复
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        log_success("服务器已停止")
        toast_info("服务器已停止", "BDS 进程已退出")
        self.append_output(">>> 服务器已停止 <<<")
        self.server_process = None

    def on_server_error(self, error_msg):
        self.append_output(f">>> 错误: {error_msg} <<<")
        toast_error("服务器崩溃", error_msg)
        if self._auto_restart and self._restart_count < 5:
            self._restart_count += 1
            self.append_output(f">>> {5}秒后自动重启（第 {self._restart_count} 次）... <<<")
            self._restart_timer.start(5000)
        else:
            QMessageBox.critical(self, "服务器错误", error_msg)
        self.on_server_stopped()

    def send_command(self):
        cmd = self.cmd_input.text().strip()
        if not cmd:
            return
        self.cmd_input.clear()
        # 添加到历史（去重）
        if cmd not in self._cmd_history:
            self._cmd_history.append(cmd)
        if len(self._cmd_history) > 100:
            self._cmd_history.pop(0)
        self._cmd_history_idx = -1
        if self.server_process and self.server_process.isRunning():
            self.server_process.send_command(cmd)
            log_cmd(f"发送命令: {cmd}")
            self.append_output(f"> {cmd}")
        else:
            log_warning("服务器未运行，无法发送命令")
            self.append_output("服务器未运行，无法发送命令。")

    def is_server_running(self):
        return self.server_process is not None and self.server_process.isRunning()

    def _do_auto_restart(self):
        """崩溃后自动重启服务器"""
        if self.parent.is_server_running():
            self.append_output(">>> 服务器仍在运行，跳过自动重启 <<<")
            return
        toast_warning("自动重启", f"第 {self._restart_count} 次尝试")
        self.append_output(">>> 自动重启服务器... <<<")
        self.start_server()

# ---------- 资源包管理标签页 ----------
class PacksTab(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.init_ui()
        self.refresh_lists()

    def init_ui(self):
        layout = QHBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)

        resource_widget = QWidget()
        resource_layout = QVBoxLayout(resource_widget)
        resource_layout.addWidget(QLabel("📦 资源包 (Resource Packs)"))
        self.resource_list = QListWidget()
        self.resource_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.resource_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.resource_list.customContextMenuRequested.connect(lambda pos: self.show_context_menu(pos, "resource"))
        self.resource_list.itemDoubleClicked.connect(self.on_item_double_clicked)
        resource_layout.addWidget(self.resource_list)

        btn_resource_add = QPushButton("添加资源包")
        btn_resource_add.clicked.connect(lambda: self.add_pack("resource"))
        btn_resource_remove = QPushButton("移除选中")
        btn_resource_remove.clicked.connect(lambda: self.remove_pack("resource"))
        btn_resource_detail = QPushButton("查看详情")
        btn_resource_detail.clicked.connect(lambda: self.show_detail_for_selected("resource"))
        btn_layout_res = QHBoxLayout()
        btn_layout_res.addWidget(btn_resource_add)
        btn_layout_res.addWidget(btn_resource_remove)
        btn_layout_res.addWidget(btn_resource_detail)
        resource_layout.addLayout(btn_layout_res)
        splitter.addWidget(resource_widget)

        behavior_widget = QWidget()
        behavior_layout = QVBoxLayout(behavior_widget)
        behavior_layout.addWidget(QLabel("⚙️ 行为包 (Behavior Packs)"))
        self.behavior_list = QListWidget()
        self.behavior_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.behavior_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.behavior_list.customContextMenuRequested.connect(lambda pos: self.show_context_menu(pos, "behavior"))
        self.behavior_list.itemDoubleClicked.connect(self.on_item_double_clicked)
        behavior_layout.addWidget(self.behavior_list)

        btn_behavior_add = QPushButton("添加行为包")
        btn_behavior_add.clicked.connect(lambda: self.add_pack("behavior"))
        btn_behavior_remove = QPushButton("移除选中")
        btn_behavior_remove.clicked.connect(lambda: self.remove_pack("behavior"))
        btn_behavior_detail = QPushButton("查看详情")
        btn_behavior_detail.clicked.connect(lambda: self.show_detail_for_selected("behavior"))
        btn_layout_beh = QHBoxLayout()
        btn_layout_beh.addWidget(btn_behavior_add)
        btn_layout_beh.addWidget(btn_behavior_remove)
        btn_layout_beh.addWidget(btn_behavior_detail)
        behavior_layout.addLayout(btn_layout_beh)
        splitter.addWidget(behavior_widget)

        layout.addWidget(splitter)

    def show_context_menu(self, pos, pack_type):
        list_widget = self.resource_list if pack_type == "resource" else self.behavior_list
        item = list_widget.itemAt(pos)
        if item:
            menu = QMenu()
            detail_action = menu.addAction("查看详细信息")
            detail_action.triggered.connect(lambda: self.show_pack_info(item))
            server_running = self.parent.is_server_running()
            if not server_running:
                data = item.data(Qt.UserRole)
                if data:
                    folder_name, ptype, uuid = data
                    level_name = self.parent.get_level_name()
                    world_path = get_world_path(level_name)
                    is_active = False
                    if world_path and uuid:
                        reg_file = os.path.join(world_path, "world_resource_packs.json" if pack_type == "resource" else "world_behavior_packs.json")
                        if os.path.exists(reg_file):
                            try:
                                with open(reg_file, "r") as f:
                                    data_json = json.load(f)
                                if any(e.get("pack_id") == uuid for e in data_json):
                                    is_active = True
                            except Exception:
                                pass
                    if is_active:
                        deactivate_action = menu.addAction("从当前世界注销")
                        deactivate_action.triggered.connect(lambda: self.deactivate_pack(item))
                    else:
                        activate_action = menu.addAction("激活到当前世界")
                        activate_action.triggered.connect(lambda: self.activate_pack(item))
            else:
                action = menu.addAction("激活/注销 (服务器运行时不可用)")
                action.setEnabled(False)
            menu.exec_(list_widget.mapToGlobal(pos))

    def on_item_double_clicked(self, item):
        self.show_pack_info(item)

    def show_detail_for_selected(self, pack_type):
        list_widget = self.resource_list if pack_type == "resource" else self.behavior_list
        selected = list_widget.selectedItems()
        if selected:
            self.show_pack_info(selected[0])

    def show_pack_info(self, item):
        data = item.data(Qt.UserRole)
        if not data:
            toast_error("错误", "无法获取包信息")
            return
        folder_name, pack_type, uuid = data
        base_dir = RESOURCE_PACKS_DIR if pack_type == "resource" else BEHAVIOR_PACKS_DIR
        pack_folder = os.path.join(base_dir, folder_name)
        if not os.path.exists(pack_folder):
            toast_error("包不存在", f"文件夹不存在: {pack_folder}")
            return
        is_active = False
        level_name = self.parent.get_level_name()
        world_path = get_world_path(level_name)
        if world_path and uuid:
            reg_file = os.path.join(world_path, "world_resource_packs.json" if pack_type == "resource" else "world_behavior_packs.json")
            if os.path.exists(reg_file):
                try:
                    with open(reg_file, "r") as f:
                        data_json = json.load(f)
                    if any(e.get("pack_id") == uuid for e in data_json):
                        is_active = True
                except Exception:
                    pass
        dialog = PackInfoDialog(pack_folder, pack_type, is_active, self)
        dialog.exec_()

    def activate_pack(self, item):
        data = item.data(Qt.UserRole)
        if not data:
            return
        folder_name, pack_type, uuid = data
        if self.parent.is_server_running():
            toast_warning("操作被阻止", "请先停止服务器再修改包状态")
            return
        level_name = self.parent.get_level_name()
        world_path = get_world_path(level_name)
        if not os.path.exists(world_path):
            toast_error("世界不存在", "请先启动一次服务器生成世界")
            return
        base_dir = RESOURCE_PACKS_DIR if pack_type == "resource" else BEHAVIOR_PACKS_DIR
        pack_folder = os.path.join(base_dir, folder_name)
        uuid, version = get_pack_manifest(pack_folder, retry=3)
        if not uuid:
            toast_error("缺少 UUID", f"无法读取 {folder_name} 的 manifest.json")
            return
        success = register_pack_to_world(world_path, pack_type, folder_name, uuid, version)
        if success:
            log_success(f"手动激活 {folder_name} 到世界 {level_name}")
            toast_success("激活成功", f"{folder_name} 已激活")
        else:
            toast_info("已激活", f"{folder_name} 已在激活列表中")
        self.refresh_lists()
        self.parent.on_external_change()

    def deactivate_pack(self, item):
        data = item.data(Qt.UserRole)
        if not data:
            return
        folder_name, pack_type, uuid = data
        if self.parent.is_server_running():
            toast_warning("操作被阻止", "请先停止服务器")
            return
        level_name = self.parent.get_level_name()
        world_path = get_world_path(level_name)
        if not os.path.exists(world_path):
            toast_error("世界不存在", f"世界文件夹不存在")
            return
        if not uuid:
            toast_error("缺少 UUID", "包缺少 UUID，无法注销")
            return
        success = unregister_pack_from_world(world_path, pack_type, uuid)
        if success:
            log_success(f"从世界注销 {folder_name}")
            toast_success("注销成功", f"{folder_name} 已注销")
        else:
            toast_info("未激活", f"{folder_name} 未在激活列表中")
        self.refresh_lists()
        self.parent.on_external_change()

    def refresh_lists(self):
        self.resource_list.clear()
        self.behavior_list.clear()
        level_name = self.parent.get_level_name()
        world_path = get_world_path(level_name)
        try:
            for folder in os.listdir(RESOURCE_PACKS_DIR):
                folder_path = os.path.join(RESOURCE_PACKS_DIR, folder)
                if os.path.isdir(folder_path):
                    uuid, _ = get_pack_manifest(folder_path, retry=1)
                    status = ""
                    if world_path and uuid:
                        reg_file = os.path.join(world_path, "world_resource_packs.json")
                        if os.path.exists(reg_file):
                            try:
                                with open(reg_file, "r") as f:
                                    data = json.load(f)
                                if any(e.get("pack_id") == uuid for e in data):
                                    status = " ✓已激活"
                            except Exception:
                                pass
                    item = QListWidgetItem(f"{folder}{status}")
                    item.setData(Qt.UserRole, (folder, "resource", uuid))
                    self.resource_list.addItem(item)
            QApplication.processEvents()
            for folder in os.listdir(BEHAVIOR_PACKS_DIR):
                folder_path = os.path.join(BEHAVIOR_PACKS_DIR, folder)
                if os.path.isdir(folder_path):
                    uuid, _ = get_pack_manifest(folder_path, retry=1)
                    status = ""
                    if world_path and uuid:
                        reg_file = os.path.join(world_path, "world_behavior_packs.json")
                        if os.path.exists(reg_file):
                            try:
                                with open(reg_file, "r") as f:
                                    data = json.load(f)
                                if any(e.get("pack_id") == uuid for e in data):
                                    status = " ✓已激活"
                            except Exception:
                                pass
                    item = QListWidgetItem(f"{folder}{status}")
                    item.setData(Qt.UserRole, (folder, "behavior", uuid))
                    self.behavior_list.addItem(item)
            # 防止大量包导致 UI 卡顿
            QApplication.processEvents()
        except Exception as e:
            log_error(f"刷新包列表失败: {e}")
            toast_error("刷新失败", str(e))

    def add_pack(self, pack_type):
        path = QFileDialog.getExistingDirectory(self, f"选择{pack_type}包文件夹", SCRIPT_DIR)
        if not path:
            return
        folder_name = os.path.basename(path)
        dest_dir = RESOURCE_PACKS_DIR if pack_type == "resource" else BEHAVIOR_PACKS_DIR
        dest_path = os.path.join(dest_dir, folder_name)
        if os.path.exists(dest_path):
            toast_warning("已存在", f"{folder_name} 已存在")
            log_warning(f"添加失败，{folder_name} 已存在")
            return
        level_name = self.parent.get_level_name()
        world_path = get_world_path(level_name)
        # 启动后台复制线程
        self.worker = CopyPackWorker(path, dest_path, pack_type, world_path if os.path.exists(world_path) else None, self)
        self.worker.progress.connect(lambda msg: self.parent.status_label.setText(msg))
        self.worker.finished.connect(self.on_add_pack_finished)
        self.worker.start()
        # 禁用按钮（可选）
        self.setEnabled(False)
        self.parent.status_label.setText(f"正在添加 {folder_name} ...")

    def on_add_pack_finished(self, success, message):
        self.setEnabled(True)
        self.parent.status_label.setText("就绪")
        if success:
            toast_success("添加成功", message)
            log_success(message)
        else:
            toast_warning("警告", message)
            log_warning(message)
        self.refresh_lists()
        self.parent.on_external_change()
        self.worker = None

    def remove_pack(self, pack_type):
        list_widget = self.resource_list if pack_type == "resource" else self.behavior_list
        selected = list_widget.selectedItems()
        if not selected:
            return
        if QMessageBox.question(self, "确认", "删除包将同时从磁盘移除文件和从世界注销，是否继续？",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        for item in selected:
            data = item.data(Qt.UserRole)
            if not data:
                continue
            folder_name, ptype, uuid = data
            if ptype != pack_type:
                continue
            level_name = self.parent.get_level_name()
            world_path = get_world_path(level_name)
            target_dir = RESOURCE_PACKS_DIR if pack_type == "resource" else BEHAVIOR_PACKS_DIR
            pack_path = os.path.join(target_dir, folder_name)
            # 启动后台删除线程
            self.worker = RemovePackWorker(pack_path, pack_type, world_path if os.path.exists(world_path) else None, uuid, self)
            self.worker.progress.connect(lambda msg: self.parent.status_label.setText(msg))
            self.worker.finished.connect(self.on_remove_pack_finished)
            self.worker.start()
            self.setEnabled(False)
            self.parent.status_label.setText(f"正在删除 {folder_name} ...")
            break  # 一次只处理一个，避免冲突

    def on_remove_pack_finished(self, success, message):
        self.setEnabled(True)
        self.parent.status_label.setText("就绪")
        if success:
            toast_success("移除成功", message)
            log_success(message)
        else:
            toast_error("错误", message)
            log_error(message)
        self.refresh_lists()
        self.parent.on_external_change()
        self.worker = None

# ---------- 配置文件标签页 ----------
class WheelEventFilter(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel:
            return True
        return super().eventFilter(obj, event)

class ConfigTab(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.init_ui()
        self.load_server_properties()

    def init_ui(self):
        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)

        prop_group = QGroupBox("server.properties")
        prop_layout = QFormLayout()
        self.prop_edits = {}
        props = [
            ("server-name", "text", "Dedicated Server", "服务器名称，显示在外部服务器列表"),
            ("gamemode", "combo", ["survival", "creative", "adventure"], "默认游戏模式"),
            ("force-gamemode", "bool", False, "强制玩家使用默认游戏模式"),
            ("difficulty", "combo", ["peaceful", "easy", "normal", "hard"], "游戏难度"),
            ("allow-cheats", "bool", False, "是否允许使用命令（开启后可使用 /op 等）"),
            ("max-players", "int", 10, "最大玩家数量 (1-40)"),
            ("online-mode", "bool", True, "正版验证（false 为离线模式）"),
            ("allow-list", "bool", False, "是否启用白名单（需手动配置 allowlist.json）"),
            ("server-port", "int", 19132, "IPv4 端口 (UDP)"),
            ("server-portv6", "int", 19133, "IPv6 端口 (UDP)"),
            ("enable-lan-visibility", "bool", True, "是否在局域网中广播"),
            ("view-distance", "int", 32, "视野距离（区块数）"),
            ("tick-distance", "int", 4, "tick 加载距离（区块数）"),
            ("player-idle-timeout", "int", 30, "玩家空闲踢出时间（分钟，0为禁用）"),
            ("max-threads", "int", 8, "最大线程数（建议不超过CPU核心数）"),
            ("level-name", "text", "Bedrock level", "世界文件夹名称（位于 worlds/ 下）"),
            ("level-seed", "text", "", "世界种子（留空则随机生成）"),
            ("default-player-permission-level", "combo", ["visitor", "member", "operator"], "新玩家默认权限等级"),
            ("texturepack-required", "bool", False, "是否强制玩家使用服务器资源包"),
            ("content-log-file-enabled", "bool", False, "是否启用内容日志文件"),
            ("compression-threshold", "int", 1, "压缩阈值 (0-65535, 1=全部压缩)"),
            ("compression-algorithm", "combo", ["zlib", "snappy"], "压缩算法（zlib 兼容性更好）"),
            ("op-permission-level", "combo", ["1", "2", "3", "4"], "OP 权限等级 (1-4)"),
            ("server-authoritative-movement", "combo", ["client-auth", "server-auth", "server-auth-with-rewind"], "移动权威模式"),
            ("server-authoritative-block-breaking", "bool", False, "服务端权威方块破坏"),
            ("chat-restriction", "combo", ["None", "Disabled", "Muted", "Limited"], "聊天限制级别"),
            ("disable-player-interaction", "bool", False, "禁用玩家交互"),
            ("emit-server-telemetry", "bool", True, "发送服务器遥测数据"),
            ("correct-player-movement", "bool", False, "服务端纠正玩家移动"),
        ]
        for item in props:
            key = item[0]
            typ = item[1]
            default = item[2]
            tooltip = item[3] if len(item) > 3 else ""
            if typ == "text":
                widget = QLineEdit()
            elif typ == "int":
                widget = QSpinBox()
                widget.setRange(0, 65535)
            elif typ == "bool":
                widget = QCheckBox()
            elif typ == "combo":
                widget = QComboBox()
                widget.addItems(default)
                default = default[0]
            widget.setToolTip(tooltip)
            self.prop_edits[key] = widget
            prop_layout.addRow(QLabel(key), widget)
        prop_group.setLayout(prop_layout)
        scroll_layout.addWidget(prop_group)

        wheel_filter = WheelEventFilter(self)
        for widget in self.prop_edits.values():
            if isinstance(widget, (QSpinBox, QComboBox)):
                widget.installEventFilter(wheel_filter)

        port_group = QGroupBox("端口检测与更换")
        port_layout = QHBoxLayout()
        self.port_check_btn = QPushButton("端口检测与更换")
        self.port_check_btn.clicked.connect(self.open_port_checker)
        port_layout.addWidget(self.port_check_btn)
        port_layout.addStretch()
        port_group.setLayout(port_layout)
        scroll_layout.addWidget(port_group)

        btn_save = QPushButton("保存 server.properties")
        btn_save.clicked.connect(self.save_server_properties)
        scroll_layout.addWidget(btn_save)

        other_group = QGroupBox("其他管理")
        other_layout = QVBoxLayout()
        btn_allowlist = QPushButton("编辑白名单 (allowlist.json)")
        btn_allowlist.clicked.connect(self.edit_allowlist)
        btn_permissions = QPushButton("编辑权限 (permissions.json)")
        btn_permissions.clicked.connect(self.edit_permissions)
        btn_packetlimit = QPushButton("编辑包限制 (packetlimitconfig.json)")
        btn_packetlimit.clicked.connect(self.edit_packet_limit)
        other_layout.addWidget(btn_allowlist)
        other_layout.addWidget(btn_permissions)
        other_layout.addWidget(btn_packetlimit)
        other_group.setLayout(other_layout)
        scroll_layout.addWidget(other_group)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

    def open_port_checker(self):
        dialog = PortCheckerDialog(self)
        dialog.exec_()
        self.load_server_properties()

    def load_server_properties(self):
        if not os.path.exists(SERVER_PROPERTIES):
            log_warning("server.properties 不存在，将创建默认配置")
            self.create_default_properties()
        try:
            with open(SERVER_PROPERTIES, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    if key in self.prop_edits:
                        widget = self.prop_edits[key]
                        if isinstance(widget, QLineEdit):
                            widget.setText(value)
                        elif isinstance(widget, QSpinBox):
                            try:
                                widget.setValue(int(value))
                            except Exception:
                                pass
                        elif isinstance(widget, QCheckBox):
                            widget.setChecked(value.lower() == "true")
                        elif isinstance(widget, QComboBox):
                            idx = widget.findText(value)
                            if idx >= 0:
                                widget.setCurrentIndex(idx)
        except Exception as e:
            log_error(f"加载 server.properties 失败: {e}")
            toast_error("加载配置失败", str(e))

    def create_default_properties(self):
        default_content = """#server.properties
server-name=Dedicated Server
gamemode=survival
force-gamemode=false
difficulty=easy
allow-cheats=false
max-players=10
online-mode=true
allow-list=false
server-port=19132
server-portv6=19133
enable-lan-visibility=true
view-distance=32
tick-distance=4
player-idle-timeout=30
max-threads=8
level-name=Bedrock level
level-seed=
default-player-permission-level=member
texturepack-required=false
content-log-file-enabled=false
compression-threshold=1
compression-algorithm=zlib
op-permission-level=4
server-authoritative-movement=server-auth
server-authoritative-block-breaking=false
chat-restriction=None
disable-player-interaction=false
emit-server-telemetry=true
correct-player-movement=false
"""
        try:
            with open(SERVER_PROPERTIES, "w", encoding="utf-8") as f:
                f.write(default_content)
            log_success("已创建默认 server.properties")
        except Exception as e:
            log_error(f"创建默认 server.properties 失败: {e}")

    def save_server_properties(self):
        lines = []
        if os.path.exists(SERVER_PROPERTIES):
            try:
                with open(SERVER_PROPERTIES, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            except Exception as e:
                log_error(f"读取 server.properties 失败: {e}")
        new_lines = []
        updated_keys = set()
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.split("=", 1)[0]
                if key in self.prop_edits:
                    widget = self.prop_edits[key]
                    if isinstance(widget, QLineEdit):
                        value = widget.text()
                    elif isinstance(widget, QSpinBox):
                        value = str(widget.value())
                    elif isinstance(widget, QCheckBox):
                        value = "true" if widget.isChecked() else "false"
                    elif isinstance(widget, QComboBox):
                        value = widget.currentText()
                    # 保留原行的注释部分
                    comment = ""
                    if "#" in stripped:
                        idx = stripped.index("#")
                        comment = " " + stripped[idx:]
                    new_lines.append(f"{key}={value}{comment}\n")
                    updated_keys.add(key)
                    continue
            new_lines.append(line)
        for key, widget in self.prop_edits.items():
            if key not in updated_keys:
                if isinstance(widget, QLineEdit):
                    value = widget.text()
                elif isinstance(widget, QSpinBox):
                    value = str(widget.value())
                elif isinstance(widget, QCheckBox):
                    value = "true" if widget.isChecked() else "false"
                elif isinstance(widget, QComboBox):
                    value = widget.currentText()
                new_lines.append(f"{key}={value}\n")
        try:
            with open(SERVER_PROPERTIES, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            log_success("server.properties 已保存")
            toast_success("配置已保存", "重启服务器后生效")
        except Exception as e:
            log_error(f"保存 server.properties 失败: {e}")
            QMessageBox.critical(self, "错误", f"保存失败: {e}")

    def edit_allowlist(self):
        self.edit_json_file(ALLOWLIST_FILE, "白名单")

    def edit_permissions(self):
        self.edit_json_file(PERMISSIONS_FILE, "权限")

    def edit_packet_limit(self):
        self.edit_json_file(PACKET_LIMIT_FILE, "包限制配置")

    def edit_json_file(self, filepath, title):
        if not os.path.exists(filepath):
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump([], f, indent=4)
            except Exception as e:
                log_error(f"创建 {title} 文件失败: {e}")
                QMessageBox.critical(self, "错误", f"创建文件失败: {e}")
                return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"编辑 {title}")
        dialog.resize(600, 500)
        layout = QVBoxLayout(dialog)
        text_edit = QTextEdit()
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                text_edit.setText(f.read())
        except Exception as e:
            log_error(f"读取 {title} 文件失败: {e}")
            QMessageBox.critical(self, "错误", f"读取文件失败: {e}")
            return
        layout.addWidget(text_edit)
        btn_save = QPushButton("保存")
        def save():
            try:
                json.loads(text_edit.toPlainText())
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(text_edit.toPlainText())
                log_success(f"{title} 已保存")
                toast_success("已保存", "JSON 已保存")
                dialog.accept()
            except Exception as e:
                log_error(f"保存 {title} 失败: {e}")
                toast_error("JSON 格式错误", str(e))
        btn_save.clicked.connect(save)
        layout.addWidget(btn_save)
        dialog.exec_()

# ---------- 世界管理标签页 ----------
class WorldTab(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        info_group = QGroupBox("当前世界")
        info_layout = QFormLayout()
        self.level_name_label = QLabel()
        self.level_seed_label = QLabel()
        self.difficulty_label = QLabel()
        self.world_size_label = QLabel()
        info_layout.addRow("世界名称:", self.level_name_label)
        info_layout.addRow("种子:", self.level_seed_label)
        info_layout.addRow("难度:", self.difficulty_label)
        info_layout.addRow("世界大小:", self.world_size_label)
        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        backup_group = QGroupBox("备份与还原")
        backup_layout = QHBoxLayout()
        self.backup_btn = QPushButton("立即备份当前世界")
        self.backup_btn.clicked.connect(self.backup_world)
        self.restore_btn = QPushButton("还原备份")
        self.restore_btn.clicked.connect(self.restore_backup)
        backup_layout.addWidget(self.backup_btn)
        backup_layout.addWidget(self.restore_btn)
        backup_layout.addStretch()
        backup_group.setLayout(backup_layout)
        layout.addWidget(backup_group)

        self.backup_list = QListWidget()
        self.backup_list.setMaximumHeight(200)
        layout.addWidget(QLabel("已有备份:"))
        layout.addWidget(self.backup_list)
        del_btn = QPushButton("🗑 删除选中备份")
        del_btn.setStyleSheet("color: #f44336; font-weight: bold;")
        del_btn.clicked.connect(self.delete_backup)
        layout.addWidget(del_btn)
        self.refresh_backup_list()

        quick_group = QGroupBox("世界设置快捷修改 (会修改 server.properties)")
        quick_layout = QFormLayout()
        self.new_difficulty = QComboBox()
        self.new_difficulty.addItems(["peaceful", "easy", "normal", "hard"])
        self.apply_difficulty_btn = QPushButton("应用")
        self.apply_difficulty_btn.clicked.connect(self.set_difficulty)
        quick_layout.addRow("难度:", self.new_difficulty)
        quick_layout.addRow("", self.apply_difficulty_btn)
        quick_group.setLayout(quick_layout)
        layout.addWidget(quick_group)

        layout.addStretch()
        self.refresh_info()

    def refresh_info(self):
        if os.path.exists(SERVER_PROPERTIES):
            try:
                with open(SERVER_PROPERTIES, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("level-name="):
                            self.level_name_label.setText(line.split("=", 1)[1].strip())
                        elif line.startswith("level-seed="):
                            self.level_seed_label.setText(line.split("=", 1)[1].strip() or "随机")
                        elif line.startswith("difficulty="):
                            self.difficulty_label.setText(line.split("=", 1)[1].strip())
            except Exception as e:
                log_error(f"读取世界信息失败: {e}")
        else:
            self.level_name_label.setText("未找到")

        # 计算世界大小
        level_name = self.level_name_label.text()
        wp = get_world_path(level_name)
        if os.path.exists(wp):
            try:
                total = sum(os.path.getsize(os.path.join(root, f))
                            for root, _, files in os.walk(wp) for f in files)
                if total < 1048576:
                    self.world_size_label.setText(f"{total/1024:.1f} KB")
                elif total < 1073741824:
                    self.world_size_label.setText(f"{total/1048576:.1f} MB")
                else:
                    self.world_size_label.setText(f"{total/1073741824:.2f} GB")
            except Exception:
                self.world_size_label.setText("计算失败")
        else:
            self.world_size_label.setText("不存在")

    def refresh_backup_list(self):
        self.backup_list.clear()
        try:
            backups = sorted([f for f in os.listdir(BACKUP_DIR) if f.endswith(".zip")], reverse=True)
            for b in backups:
                self.backup_list.addItem(b)
        except Exception as e:
            log_error(f"刷新备份列表失败: {e}")

    def delete_backup(self):
        """删除选中的备份文件"""
        item = self.backup_list.currentItem()
        if not item:
            toast_warning("未选择", "请先选择要删除的备份")
            return
        filename = item.text()
        filepath = os.path.join(BACKUP_DIR, filename)
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除备份文件吗？\n\n{filename}\n\n此操作不可恢复！",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        try:
            os.remove(filepath)
            toast_success("已删除", filename)
            self.refresh_backup_list()
        except Exception as e:
            toast_error("删除失败", str(e))

    def backup_world(self):
        if self.parent.is_server_running():
            reply = QMessageBox.question(self, "警告", "服务器正在运行，备份可能损坏世界文件。是否继续？",
                                        QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
        level_name = self.level_name_label.text()
        world_path = get_world_path(level_name)
        if not os.path.exists(world_path):
            toast_error("世界不存在", f"世界文件夹不存在")
            log_error(f"世界备份失败：{world_path} 不存在")
            return
        # 启动备份线程
        toast_info("开始备份", f"正在备份世界 {level_name}...")
        self.worker = BackupWorker(level_name, world_path, BACKUP_DIR, self)
        self.worker.progress.connect(lambda msg: self.parent.status_label.setText(msg))
        self.worker.finished.connect(self.on_backup_finished)
        self.worker.start()
        self.backup_btn.setEnabled(False)
        self.parent.status_label.setText("正在备份...")

    def on_backup_finished(self, success, message):
        self.backup_btn.setEnabled(True)
        self.parent.status_label.setText("就绪")
        if success:
            toast_success("备份完成", message)
            log_success(message)
        else:
            toast_error("备份失败", message)
            QMessageBox.critical(self, "备份失败", message)
            log_error(message)
        self.refresh_backup_list()
        self.worker = None

    def restore_backup(self):
        selected = self.backup_list.currentItem()
        if not selected:
            toast_warning("请选择备份", "请先选择一个备份文件")
            return
        backup_name = selected.text()
        backup_path = os.path.join(BACKUP_DIR, backup_name)
        level_name = self.level_name_label.text()
        world_path = get_world_path(level_name)
        if not os.path.exists(world_path):
            os.makedirs(world_path, exist_ok=True)
        if self.parent.is_server_running():
            toast_warning("服务器运行中", "还原前请先停止服务器")
            return
        reply = QMessageBox.question(self, "确认还原", f"还原将覆盖当前世界 {level_name}，是否继续？",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        # 启动还原线程
        self.worker = RestoreWorker(level_name, world_path, backup_path, self)
        self.worker.progress.connect(lambda msg: self.parent.status_label.setText(msg))
        self.worker.finished.connect(self.on_restore_finished)
        self.worker.start()
        self.restore_btn.setEnabled(False)
        self.parent.status_label.setText("正在还原...")

    def on_restore_finished(self, success, message):
        self.restore_btn.setEnabled(True)
        self.parent.status_label.setText("就绪")
        if success:
            toast_success("还原成功", message)
            log_success(message)
        else:
            QMessageBox.critical(self, "还原失败", message)
            log_error(message)
        self.refresh_backup_list()
        self.worker = None

    def set_difficulty(self):
        difficulty = self.new_difficulty.currentText()
        if os.path.exists(SERVER_PROPERTIES):
            try:
                with open(SERVER_PROPERTIES, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                with open(SERVER_PROPERTIES, "w", encoding="utf-8") as f:
                    for line in lines:
                        if line.startswith("difficulty="):
                            f.write(f"difficulty={difficulty}\n")
                        else:
                            f.write(line)
                log_success(f"难度已修改为 {difficulty}，需重启服务器生效")
                toast_success("难度已修改", "需重启服务器生效")
                self.refresh_info()
            except Exception as e:
                log_error(f"修改难度失败: {e}")
                QMessageBox.critical(self, "错误", f"修改失败: {e}")
        else:
            log_error("server.properties 不存在")
            toast_error("错误", "server.properties 不存在")

# ==================== 隧道标签页 (ChmlFrp) ====================
class TunnelTab(QWidget):
    """ChmlFrp 内网穿透管理标签页"""
    tunnel_line_signal = pyqtSignal(str, bool)  # 跨线程安全输出

    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.tunnel_process = None
        self._read_thread = None
        self._tunnel_log = None
        self._init_tunnel_log()
        self.init_ui()
        self.load_settings()
        self.tunnel_line_signal.connect(self._on_tunnel_line)

    def init_ui(self):
        layout = QVBoxLayout(self)

        # frpc.exe 路径
        exe_group = QGroupBox("frpc 客户端")
        exe_layout = QHBoxLayout()
        self.frpc_path_edit = QLineEdit()
        self.frpc_path_edit.setPlaceholderText("请选择 frpc.exe 的完整路径")
        browse_exe_btn = QPushButton("浏览")
        browse_exe_btn.clicked.connect(self.browse_frpc_exe)
        exe_layout.addWidget(QLabel("frpc.exe:"))
        exe_layout.addWidget(self.frpc_path_edit)
        exe_layout.addWidget(browse_exe_btn)
        exe_group.setLayout(exe_layout)
        layout.addWidget(exe_group)

        # 控制按钮
        ctrl_group = QGroupBox("隧道控制")
        ctrl_layout = QHBoxLayout()
        self.start_tunnel_btn = QPushButton("▶ 启动隧道")
        self.start_tunnel_btn.clicked.connect(self.start_tunnel)
        self.stop_tunnel_btn = QPushButton("⏹ 停止隧道")
        self.stop_tunnel_btn.clicked.connect(self.stop_tunnel)
        self.stop_tunnel_btn.setEnabled(False)
        self.tunnel_status_label = QLabel("⏹ 已停止")
        self.tunnel_status_label.setStyleSheet("font-weight: bold;")
        ctrl_layout.addWidget(self.start_tunnel_btn)
        ctrl_layout.addWidget(self.stop_tunnel_btn)
        ctrl_layout.addStretch()
        ctrl_layout.addWidget(QLabel("状态:"))
        ctrl_layout.addWidget(self.tunnel_status_label)
        ctrl_group.setLayout(ctrl_layout)
        layout.addWidget(ctrl_group)

        # frpc.ini 编辑区
        ini_group = QGroupBox("frpc.ini 配置文件")
        ini_layout = QVBoxLayout()
        self.ini_editor = QPlainTextEdit()
        self.ini_editor.setFont(QFont("Consolas", 10))
        self.ini_editor.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1a1a22;
                color: #c8d6e5;
                border: 1px solid #444;
                border-radius: 6px;
                padding: 8px;
                selection-background-color: #3a3a5a;
            }
        """)
        self.ini_editor.setPlaceholderText(
            "在此粘贴从 ChmlFrp 官网获取的 frpc.ini 配置内容...\n"
            "获取方式：登录 panel.chmlfrp.cn → 隧道管理 → 配置文件 → 选择节点 → 生成配置文件"
        )
        self.ini_editor.setReadOnly(True)  # 默认锁定防误触
        ini_layout.addWidget(self.ini_editor)

        ini_btn_layout = QHBoxLayout()
        self.edit_toggle_btn = QPushButton("🔒 点击编辑")
        self.edit_toggle_btn.setToolTip("点击解锁后才能修改配置内容")
        self.edit_toggle_btn.setCheckable(True)
        self.edit_toggle_btn.toggled.connect(self._toggle_ini_edit)
        ini_btn_layout.addWidget(self.edit_toggle_btn)
        save_ini_btn = QPushButton("💾 保存 frpc.ini")
        save_ini_btn.clicked.connect(self.save_ini_file)
        load_ini_btn = QPushButton("📂 加载 frpc.ini")
        load_ini_btn.clicked.connect(self.load_ini_file)
        open_ini_dir_btn = QPushButton("📁 打开 frpc 目录")
        open_ini_dir_btn.clicked.connect(self.open_frpc_dir)
        template_btn = QPushButton("📋 配置模板")
        template_btn.clicked.connect(self._load_template)
        template_btn.setToolTip("填入 frpc.ini 模板，含 ChmlFrp 官网链接")
        ini_btn_layout.addWidget(save_ini_btn)
        ini_btn_layout.addWidget(load_ini_btn)
        ini_btn_layout.addWidget(open_ini_dir_btn)
        ini_btn_layout.addWidget(template_btn)
        ini_btn_layout.addStretch()
        ini_layout.addLayout(ini_btn_layout)
        ini_group.setLayout(ini_layout)
        layout.addWidget(ini_group)

        # 隧道输出终端
        output_group = QGroupBox("隧道输出")
        output_layout = QVBoxLayout()
        self.tunnel_output = QTextEdit()
        self.tunnel_output.setReadOnly(True)
        self.tunnel_output.setFont(QFont("Consolas", 10))
        output_layout.addWidget(self.tunnel_output)
        clear_output_btn = QPushButton("清空输出")
        clear_output_btn.clicked.connect(lambda: self.tunnel_output.clear())
        output_layout.addWidget(clear_output_btn, alignment=Qt.AlignRight)
        output_group.setLayout(output_layout)
        layout.addWidget(output_group)

    # ---------- 辅助方法 ----------
    def get_frpc_dir(self):
        path = self.frpc_path_edit.text().strip()
        if path:
            return os.path.dirname(path)
        return ""

    def get_frpc_exe(self):
        return self.frpc_path_edit.text().strip()

    def get_ini_path(self):
        exe_path = self.get_frpc_exe()
        if exe_path:
            return os.path.join(os.path.dirname(exe_path), "frpc.ini")
        return ""

    def load_settings(self):
        config = self.parent.config
        self.frpc_path_edit.setText(config.get("frpc_path", ""))
        ini_path = self.get_ini_path()
        if ini_path and os.path.exists(ini_path):
            try:
                with open(ini_path, "r", encoding="utf-8") as f:
                    self.ini_editor.setPlainText(f.read())
                    self._deselect_editor()
            except Exception as e:
                log_error(f"加载 frpc.ini 失败: {e}")

    def save_settings(self):
        self.parent.config["frpc_path"] = self.frpc_path_edit.text().strip()
        self.parent.save_config()

    # ---------- frpc.exe 路径浏览 ----------
    def browse_frpc_exe(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 frpc.exe", "",
            "Executable (*.exe);;All Files (*)"
        )
        if path:
            self.frpc_path_edit.setText(path)
            self.save_settings()
            ini_path = self.get_ini_path()
            if os.path.exists(ini_path):
                try:
                    with open(ini_path, "r", encoding="utf-8") as f:
                        self.ini_editor.setPlainText(f.read())
                        self._deselect_editor()
                    self.append_output(f"📂 已自动加载 {ini_path}")
                except Exception as e:
                    log_error(f"自动加载 frpc.ini 失败: {e}")

    # ---------- frpc.ini 文件操作 ----------
    def save_ini_file(self):
        ini_path = self.get_ini_path()
        if not ini_path:
            toast_error("未设置 frpc", "请先设置 frpc.exe 路径")
            return
        try:
            os.makedirs(os.path.dirname(ini_path), exist_ok=True)
            with open(ini_path, "w", encoding="utf-8") as f:
                f.write(self.ini_editor.toPlainText())
            log_success(f"frpc.ini 已保存到 {ini_path}")
            self.append_output(f"✅ frpc.ini 已保存: {ini_path}")
            toast_success("frpc.ini 已保存", "配置已保存")
        except Exception as e:
            log_error(f"保存 frpc.ini 失败: {e}")
            QMessageBox.critical(self, "错误", f"保存失败: {e}")

    def load_ini_file(self):
        ini_path = self.get_ini_path()
        if not ini_path:
            toast_error("未设置 frpc", "请先设置 frpc.exe 路径")
            return
        if not os.path.exists(ini_path):
            toast_warning("文件不存在", f"frpc.ini 不存在")
            return
        try:
            with open(ini_path, "r", encoding="utf-8") as f:
                self.ini_editor.setPlainText(f.read())
                self._deselect_editor()
            self.append_output(f"📂 已加载: {ini_path}")
            log_success(f"加载 frpc.ini: {ini_path}")
        except Exception as e:
            log_error(f"加载 frpc.ini 失败: {e}")
            QMessageBox.critical(self, "错误", f"加载失败: {e}")

    def open_frpc_dir(self):
        dir_path = self.get_frpc_dir()
        if not dir_path or not os.path.exists(dir_path):
            toast_warning("目录不存在", "请先设置正确的 frpc.exe 路径")
            return
        try:
            if sys.platform == "win32":
                os.startfile(dir_path)
            else:
                subprocess.Popen(["explorer", dir_path])
        except Exception as e:
            log_error(f"打开目录失败: {e}")
            QMessageBox.critical(self, "错误", f"打开目录失败: {e}")

    def _load_template(self):
        """加载 frpc.ini 模板"""
        template = (
            "# frpc.ini 配置模板\n"
            "# 请访问 ChmlFrp 官网获取隧道信息：https://www.chmlfrp.net/\n"
            "# 在官网创建隧道后，复制生成的配置到下方\n"
            "#\n"
            "# 示例配置:\n"
            "# [common]\n"
            "# server_addr = 你的服务器地址\n"
            "# server_port = 7000\n"
            "# token = 你的token\n"
            "#\n"
            "# [你的隧道名称]\n"
            "# type = tcp\n"
            "# local_ip = 127.0.0.1\n"
            "# local_port = 19132\n"
            "# remote_port = 外网端口\n"
        )
        reply = QMessageBox.question(
            self, "加载模板",
            "将用模板替换当前编辑内容，是否继续？\n\n"
            "提示：请前往 https://www.chmlfrp.net/ 创建隧道。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.ini_editor.setPlainText(template)
            self._deselect_editor()

    def _toggle_ini_edit(self, checked):
        """锁定/解锁编辑器"""
        self.ini_editor.setReadOnly(not checked)
        if checked:
            self.edit_toggle_btn.setText("✏️ 编辑中（点击锁定）")
            self.edit_toggle_btn.setStyleSheet("color: #ffaa33; font-weight: bold;")
        else:
            self.edit_toggle_btn.setText("🔒 点击编辑")
            self.edit_toggle_btn.setStyleSheet("")

    def _deselect_editor(self):
        """取消全选，光标移到末尾"""
        c = self.ini_editor.textCursor()
        c.clearSelection()
        self.ini_editor.setTextCursor(c)
        self.ini_editor.moveCursor(QTextCursor.End)

    # ---------- 隧道输出 ----------
    def _init_tunnel_log(self):
        """初始化隧道日志文件（脚本目录/logs/）"""
        try:
            log_dir = os.path.join(SCRIPT_DIR, "logs")
            os.makedirs(log_dir, exist_ok=True)
            date_str = datetime.now().strftime("%Y-%m-%d")
            log_path = os.path.join(log_dir, f"tunnel_{date_str}.log")
            self._tunnel_log = open(log_path, "a", encoding="utf-8")
            self._tunnel_log.write(f"\n--- 会话: {datetime.now()} ---\n")
        except Exception:
            self._tunnel_log = None

    def _on_tunnel_line(self, text, is_error):
        """信号槽：安全地从工作线程传递到主线程"""
        # GUI 输出
        self.append_output(text, is_error)
        # 写入日志文件
        if self._tunnel_log:
            try:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._tunnel_log.write(f"[{ts}] {text}\n")
                self._tunnel_log.flush()
            except Exception:
                pass
        # 输出到 cmd 窗口
        if is_error:
            log_warning(f"[隧道] {text}")
        else:
            log_info(f"[隧道] {text}")

    def append_output(self, text, is_error=False):
        timestamp = datetime.now().strftime("%H:%M:%S")
        if is_error:
            formatted = f'<span style="color:#ff5555;">[{timestamp}] {text}</span>'
        else:
            formatted = f'<span style="color:#dddddd;">[{timestamp}] {text}</span>'
        self.tunnel_output.append(formatted)
        scrollbar = self.tunnel_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    # ---------- 隧道启动/停止 ----------
    def start_tunnel(self):
        exe_path = self.get_frpc_exe()
        if not exe_path:
            toast_error("未设置 frpc", "请先设置 frpc.exe 路径")
            return
        if not os.path.exists(exe_path):
            QMessageBox.critical(self, "错误", f"找不到 frpc.exe:\n{exe_path}")
            return

        ini_path = self.get_ini_path()
        if not os.path.exists(ini_path):
            reply = QMessageBox.question(
                self, "配置文件缺失",
                f"frpc.ini 不存在于:\n{ini_path}\n\n是否先保存当前编辑内容？",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
            )
            if reply == QMessageBox.Yes:
                self.save_ini_file()
                if not os.path.exists(ini_path):
                    return
            elif reply == QMessageBox.Cancel:
                return

        if self.tunnel_process and self.tunnel_process.poll() is None:
            self.append_output("⚠️ 隧道已在运行中", is_error=True)
            return

        self.append_output(f"🚀 正在启动隧道: {exe_path}")
        log_info(f"启动隧道: {exe_path}")

        try:
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            self.tunnel_process = subprocess.Popen(
                [exe_path, "-c", "frpc.ini"],
                cwd=os.path.dirname(exe_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                encoding='utf-8',
                errors='replace',
                bufsize=1,
                creationflags=creationflags
            )
        except Exception as e:
            log_error(f"启动隧道失败: {e}")
            self.append_output(f"❌ 启动失败: {e}", is_error=True)
            QMessageBox.critical(self, "错误", f"启动隧道失败:\n{e}")
            return

        self._read_thread = threading.Thread(target=self._read_tunnel_output, daemon=True)
        self._read_thread.start()

        self.start_tunnel_btn.setEnabled(False)
        self.stop_tunnel_btn.setEnabled(True)
        self.tunnel_status_label.setText("▶ 运行中")
        self.tunnel_status_label.setStyleSheet("font-weight: bold; color: #4CAF50;")
        toast_success("隧道已启动", "frpc 正在运行")
        self.append_output("✅ 隧道已启动，等待连接...")

    def _read_tunnel_output(self):
        if not self.tunnel_process:
            return
        try:
            for line in iter(self.tunnel_process.stdout.readline, ""):
                if not line:
                    break
                if "启动成功" in line or "login to server" in line.lower():
                    self.tunnel_line_signal.emit(f"✅ {line.strip()}", False)
                elif "error" in line.lower() or "fail" in line.lower():
                    self.tunnel_line_signal.emit(f"❌ {line.strip()}", True)
                else:
                    self.tunnel_line_signal.emit(line.strip(), False)
            retcode = self.tunnel_process.poll()
            if retcode is not None and retcode != 0:
                self.tunnel_line_signal.emit(f"⚠️ 隧道异常退出，返回码: {retcode}", True)
        except Exception as e:
            log_error(f"读取隧道输出异常: {e}")
        finally:
            QTimer.singleShot(0, self._on_tunnel_stopped)

    def _on_tunnel_stopped(self):
        if self.start_tunnel_btn.isEnabled():
            return  # 已处理过，防重复
        self.start_tunnel_btn.setEnabled(True)
        self.stop_tunnel_btn.setEnabled(False)
        toast_info("隧道已停止", "frpc 已退出")
        self.tunnel_status_label.setText("⏹ 已停止")
        self.tunnel_status_label.setStyleSheet("font-weight: bold; color: #ff5555;")
        if self.tunnel_process:
            self.tunnel_process = None
        self.append_output("⏹ 隧道已停止")

    def stop_tunnel(self):
        if not self.tunnel_process or self.tunnel_process.poll() is not None:
            self.append_output("⚠️ 隧道未在运行", is_error=True)
            return

        self.append_output("⏹ 正在停止隧道...")
        log_info("正在停止隧道...")

        try:
            self.tunnel_process.terminate()
            for _ in range(30):
                if self.tunnel_process.poll() is not None:
                    break
                time.sleep(0.1)
            if self.tunnel_process.poll() is None:
                self.tunnel_process.kill()
                self.append_output("⚠️ 强制终止隧道进程", is_error=True)
        except Exception as e:
            log_error(f"停止隧道异常: {e}")
            self.append_output(f"❌ 停止异常: {e}", is_error=True)

        self._on_tunnel_stopped()

    def is_tunnel_running(self):
        return self.tunnel_process is not None and self.tunnel_process.poll() is None

    def cleanup(self):
        if self.is_tunnel_running():
            self.stop_tunnel()

# ---------- 版本升级辅助 ----------
def _detect_current_version(server_dir):
    """从服务器目录检测当前 BDS 版本"""
    server_dir = Path(server_dir)
    # 方案1: 查找 bedrock-server-*.zip 文件
    for pattern in ["bedrock-server-*.zip", "bedrock-server-*.mcworld"]:
        matches = sorted(server_dir.glob(pattern))
        if matches:
            fname = matches[-1].name
            m = re.search(r'bedrock-server-(\d+\.\d+\.\d+\.\d+)', fname)
            if m:
                return m.group(1)
    # 方案2: 从 exe 文件版本读取
    exe_path = server_dir / "bedrock_server.exe"
    if exe_path.exists():
        try:
            import struct
            with open(exe_path, "rb") as f:
                # 读取 PE 头部，查找版本信息（简化方法）
                f.seek(60)
                pe_offset = struct.unpack("<I", f.read(4))[0]
                f.seek(pe_offset + 4)
                magic = struct.unpack("<H", f.read(2))[0]
                # PE32+ FileHeader 偏移
                if magic == 0x8664:
                    f.seek(pe_offset + 24)
                    characteristics = struct.unpack("<H", f.read(2))[0]
                # 粗略版：执行 bedrock_server.exe --version 不可行
                # 作为兜底，尝试读取内嵌字符串
                raw = f.read()
                for m in re.finditer(rb'(\d+)\.(\d+)\.(\d+)\.(\d+)', raw):
                    ver = m.group(0).decode()
                    # 过滤掉明显不是版本号的（如 0.0.0.0, 255.255.255.255）
                    parts = ver.split(".")
                    if all(0 <= int(p) <= 99 for p in parts) and int(parts[0]) >= 1:
                        return ver
        except Exception:
            pass
    return None


def _check_url_exists(url):
    """用 HEAD 请求探测 URL 是否存在，返回 (exists, content_length)"""
    try:
        req = urllib.request.Request(url, method="HEAD", headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=8) as resp:
            return True, resp.headers.get("Content-Length", "0")
    except urllib.error.HTTPError:
        return False, "0"
    except Exception:
        return False, "0"


def _increment_version(ver_str, level=3):
    """递增版本号，level: 0=major, 1=minor, 2=patch, 3=build"""
    parts = [int(x) for x in ver_str.split(".")]
    while len(parts) < 4:
        parts.append(0)
    parts[level] += 1
    for i in range(level + 1, 4):
        parts[i] = 0
    return ".".join(str(p) for p in parts)


def _fetch_latest_version_info(branch="stable", current_version=None,
                               progress_callback=None, cancel_check=None):
    """通过 HEAD 请求并发探测 BDS 下载 URL，找到最新可用版本。

    参数：
        branch: "stable" 或 "preview"
        current_version: 当前服务器版本，用作探测起点
        progress_callback: callable(version, percent) — 进度回调
        cancel_check: callable() -> bool — 返回 True 表示取消

    返回 (version, url, branch_label)"""
    base_pattern = "bin-win-preview" if branch == "preview" else "bin-win"
    label = "预览版" if branch == "preview" else "稳定版"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    # 策略1：尝试抓取页面（少数情况下链接可能直接嵌入 HTML）
    try:
        req = urllib.request.Request(
            "https://www.minecraft.net/en-us/download/server/bedrock",
            headers=headers
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")
            pattern = rf'{base_pattern}/bedrock-server-(\d+\.\d+\.\d+\.\d+)\.zip'
            m = re.search(pattern, html)
            if m:
                version = m.group(1)
                url = f"https://www.minecraft.net/bedrockdedicatedserver/{base_pattern}/bedrock-server-{version}.zip"
                if progress_callback:
                    progress_callback(version, 100)
                return version, url, label
    except Exception:
        pass

    if not current_version:
        current_version = "1.20.0.0"

    parts = [int(x) for x in current_version.split(".")]
    while len(parts) < 4:
        parts.append(0)

    # 策略2：并发 HEAD 请求逐批探测
    # 稳定版 build 号一般 ≤5，预览版可达 30+
    # 稳定版 patch 递增 ≤3，预览版 patch 可能跳 10+
    is_preview = (branch == "preview")
    if is_preview:
        # 预览版：build 号稀疏且高，用跳步探测减少请求
        build_step = 5         # 每隔 5 个 build 探测一次
        max_build = 55
        max_patches = 20
    else:
        build_step = 1         # 稳定版：逐 build 精确探测
        max_build = 8
        max_patches = 10

    candidate_urls = []
    for patch in range(parts[2], parts[2] + max_patches):
        start_build = parts[3] + 1 if patch == parts[2] else 0
        for build in range(start_build, min(max_build, 60), build_step):
            candidate = f"{parts[0]}.{parts[1]}.{patch}.{build}"
            url = (f"https://www.minecraft.net/bedrockdedicatedserver/"
                   f"{base_pattern}/bedrock-server-{candidate}.zip")
            candidate_urls.append((candidate, url))

    if not candidate_urls:
        return None, None, "无候选版本可探测"

    # 评估：每个 patch 的 8 个 build 分批提交
    # 第一批：所有 patch 的第一个 build
    # 如果某 patch 有版本 → 继续探测该 patch 的后续 build
    batch_size = 8  # 每批并发数
    total = len(candidate_urls)
    results = {}             # url → bool
    explored = set()         # 已探测的 url

    # 按 patch 分组探测：逐 patch 提交 build
    patch_candidates = {}
    for ver, url in candidate_urls:
        patch_num = int(ver.split(".")[2])
        if patch_num not in patch_candidates:
            patch_candidates[patch_num] = []
        patch_candidates[patch_num].append((ver, url))

    last_found = None
    last_found_url = None
    consecutive_empty = 0
    checked_count = 0
    total_patches = len(patch_candidates)

    # 并发探测中收集所有找到的版本（避免竞态覆盖）
    all_found = {}  # key: (patch, build), value: (version, url)

    for idx, patch_num in enumerate(sorted(patch_candidates.keys())):
        if cancel_check and cancel_check():
            break

        patch_list = patch_candidates[patch_num]
        found_in_patch = False

        # 分批探测当前 patch 的所有 build
        for i in range(0, len(patch_list), batch_size):
            batch = patch_list[i:i + batch_size]
            if cancel_check and cancel_check():
                break

            with ThreadPoolExecutor(max_workers=min(batch_size, 10)) as executor:
                futures = {executor.submit(_check_url_exists, u): (v, u) for v, u in batch}
                for future in as_completed(futures, timeout=15):
                    v, u = futures[future]
                    try:
                        exists, _ = future.result()
                        if exists:
                            pnum = int(v.split(".")[2])
                            bnum = int(v.split(".")[3])
                            all_found[(pnum, bnum)] = (v, u)
                            found_in_patch = True
                    except Exception:
                        pass

            checked_count += len(batch)

            # 进度回调
            if progress_callback:
                pct = min(checked_count * 100 // total, 99)
                current_checking = batch[-1][0] if batch else ""
                progress_callback(current_checking, pct)

        if not found_in_patch:
            consecutive_empty += 1
            # 稳定版：连续 2 个空 patch 即停止（版本号连续递增）
            # 预览版：不中断，扫完所有候选 patch（版本号不连续，可能跳跃 10+ patch）
            if not is_preview and consecutive_empty >= 2:
                break
        else:
            consecutive_empty = 0

    # 在所有找到的版本中取最高的 (patch, build)
    if all_found:
        max_key = max(all_found.keys())  # (patch, build) 元组自然排序
        last_found, last_found_url = all_found[max_key]

    if progress_callback:
        progress_callback("", 100)

    if last_found is None:
        return None, None, f"未找到高于 {current_version} 的版本"

    # 预览版步进探测后，精确扫描找到的 patch 附近，确保拿到最高 build
    if is_preview and last_found:
        lp = [int(x) for x in last_found.split(".")]
        # 在找到的 build 前后 5 个范围内精确扫描
        fine_tasks = []
        for b in range(max(0, lp[3] - 5), lp[3] + 6):
            if b == lp[3]:
                continue  # 跳过已确认的
            cand = f"{lp[0]}.{lp[1]}.{lp[2]}.{b}"
            u = (f"https://www.minecraft.net/bedrockdedicatedserver/"
                 f"{base_pattern}/bedrock-server-{cand}.zip")
            fine_tasks.append((cand, u))

        if fine_tasks:
            fine_results = {}
            with ThreadPoolExecutor(max_workers=len(fine_tasks)) as executor:
                futures = {executor.submit(_check_url_exists, u): (v, u) for v, u in fine_tasks}
                for future in as_completed(futures, timeout=10):
                    v, u = futures[future]
                    try:
                        exists, _ = future.result()
                        if exists:
                            fine_results[int(v.split(".")[3])] = (v, u)
                    except Exception:
                        pass
            # 取最高 build
            if fine_results:
                max_b = max(fine_results.keys())
                if max_b > lp[3]:
                    last_found, last_found_url = fine_results[max_b]

    return last_found, last_found_url, label


# ---------- 版本升级下载线程 ----------
class UpgradeWorker(BaseWorker):
    progress = pyqtSignal(int)
    status_signal = pyqtSignal(str)

    def __init__(self, url, save_path, parent=None):
        super().__init__(parent)
        self.url = url
        self.save_path = save_path

    def run(self):
        self._cancel = False
        try:
            self.status_signal.emit("正在连接下载服务器...")
            req = urllib.request.Request(self.url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            })
            with urllib.request.urlopen(req, timeout=60) as resp:
                content_length = resp.headers.get("Content-Length")
                total = int(content_length) if content_length else 0
                downloaded = 0
                chunk_size = 8192

                with open(self.save_path, "wb") as f:
                    while True:
                        if self._cancel:
                            self.finished.emit(False, "下载已取消")
                            return
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            pct = int(downloaded * 100 / total)
                            self.progress.emit(pct)
                            mb = downloaded / (1024 * 1024)
                            total_mb = total / (1024 * 1024)
                            self.status_signal.emit(
                                f"下载中... {mb:.1f} MB / {total_mb:.1f} MB ({pct}%)"
                            )
                        else:
                            mb = downloaded / (1024 * 1024)
                            self.status_signal.emit(f"下载中... {mb:.1f} MB (未知总大小)")

            if os.path.getsize(self.save_path) > 0:
                self.status_signal.emit("下载完成！")
                self.finished.emit(True, "下载完成")
            else:
                self.finished.emit(False, "下载的文件为空")

        except urllib.error.HTTPError as e:
            self.finished.emit(False, f"HTTP 错误: {e.code} {e.reason}")
        except urllib.error.URLError as e:
            self.finished.emit(False, f"网络错误: {e.reason}")
        except Exception as e:
            self.finished.emit(False, f"下载失败: {str(e)}")


# ---------- 版本升级标签页 ----------
class UpgradeTab(QWidget):
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        self.latest_stable_version = None
        self.latest_stable_url = None
        self.latest_preview_version = None
        self.latest_preview_url = None
        self.selected_branch = "stable"
        self.downloaded_zip = None
        self.download_worker = None
        self.upgrade_worker = None
        self.check_worker = None
        self._check_cancelled = False
        self.init_ui()
        self.refresh_current_info()

    # ---------- UI 初始化 ----------
    def init_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(8, 8, 8, 8)

        # --- 当前信息 ---
        current_group = QGroupBox("📋 当前信息")
        current_layout = QFormLayout()
        self.current_version_label = QLabel("检测中...")
        self.current_version_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.current_dir_label = QLabel(str(self.parent.get_absolute_server_dir()))
        self.current_dir_label.setWordWrap(True)
        detect_btn = QPushButton("🔄 重新检测")
        detect_btn.setFixedWidth(120)
        detect_btn.clicked.connect(self.refresh_current_info)

        hrow = QHBoxLayout()
        hrow.addWidget(self.current_version_label)
        hrow.addStretch()
        hrow.addWidget(detect_btn)
        current_layout.addRow("当前版本:", hrow)
        current_layout.addRow("服务器目录:", self.current_dir_label)
        current_group.setLayout(current_layout)
        layout.addWidget(current_group)

        # --- 版本检查 ---
        check_group = QGroupBox("🔍 版本检查")
        check_layout = QFormLayout()
        self.stable_version_label = QLabel("未检查")
        self.preview_version_label = QLabel("未检查")
        self.check_status_label = QLabel("")
        check_layout.addRow("最新稳定版:", self.stable_version_label)
        check_layout.addRow("最新预览版:", self.preview_version_label)

        check_btn_layout = QHBoxLayout()
        self.check_stable_btn = QPushButton("🔍 检查稳定版更新")
        self.check_stable_btn.clicked.connect(lambda: self.check_updates("stable"))
        self.check_preview_btn = QPushButton("🔍 检查预览版更新")
        self.check_preview_btn.clicked.connect(lambda: self.check_updates("preview"))
        check_btn_layout.addWidget(self.check_stable_btn)
        check_btn_layout.addWidget(self.check_preview_btn)
        check_btn_layout.addStretch()
        check_layout.addRow(check_btn_layout)

        # 探测进度条 + 取消按钮
        progress_row = QHBoxLayout()
        self.check_progress_bar = QProgressBar()
        self.check_progress_bar.setRange(0, 100)
        self.check_progress_bar.setValue(0)
        self.check_progress_bar.setVisible(False)
        self.check_progress_bar.setMaximumHeight(18)
        progress_row.addWidget(self.check_progress_bar)
        self.cancel_check_btn = QPushButton("取消检查")
        self.cancel_check_btn.clicked.connect(self.cancel_version_check)
        self.cancel_check_btn.setVisible(False)
        self.cancel_check_btn.setEnabled(False)
        self.cancel_check_btn.setMaximumWidth(90)
        progress_row.addWidget(self.cancel_check_btn)
        check_layout.addRow(progress_row)

        self.check_progress_label = QLabel("")
        self.check_progress_label.setVisible(False)
        self.check_progress_label.setStyleSheet("color: #888; font-size: 11px;")
        check_layout.addRow(self.check_progress_label)

        check_layout.addRow(self.check_status_label)
        check_group.setLayout(check_layout)
        layout.addWidget(check_group)

        # --- 手动指定版本 ---
        manual_group = QGroupBox("✏️ 手动指定版本")
        manual_layout = QHBoxLayout()
        manual_layout.addWidget(QLabel("版本号:"))
        self.manual_version_input = QLineEdit()
        self.manual_version_input.setPlaceholderText("例如: 1.26.32.2")
        self.manual_version_input.setMaximumWidth(140)
        manual_layout.addWidget(self.manual_version_input)
        manual_layout.addWidget(QLabel("分支:"))
        self.manual_branch_combo = QComboBox()
        self.manual_branch_combo.addItem("稳定版", "stable")
        self.manual_branch_combo.addItem("预览版", "preview")
        self.manual_branch_combo.setMaximumWidth(90)
        manual_layout.addWidget(self.manual_branch_combo)
        self.manual_download_btn = QPushButton("⬇️ 直接下载")
        self.manual_download_btn.clicked.connect(self.download_manual_version)
        self.manual_download_btn.setMaximumWidth(100)
        manual_layout.addWidget(self.manual_download_btn)
        manual_layout.addStretch()
        manual_group.setLayout(manual_layout)
        layout.addWidget(manual_group)

        # --- 下载 ---
        dl_group = QGroupBox("⬇️ 下载")
        dl_layout = QVBoxLayout()

        dl_row1 = QHBoxLayout()
        dl_row1.addWidget(QLabel("版本选择:"))
        self.branch_combo = QComboBox()
        self.branch_combo.addItem("稳定版 (Stable)", "stable")
        self.branch_combo.addItem("预览版 (Preview)", "preview")
        self.branch_combo.currentIndexChanged.connect(self._on_branch_changed)
        dl_row1.addWidget(self.branch_combo)
        dl_row1.addStretch()
        dl_layout.addLayout(dl_row1)

        dl_row2 = QHBoxLayout()
        self.download_btn = QPushButton("⬇️ 下载最新版本")
        self.download_btn.clicked.connect(self.start_download)
        self.download_btn.setMinimumWidth(160)
        self.cancel_dl_btn = QPushButton("取消下载")
        self.cancel_dl_btn.clicked.connect(self.cancel_download)
        self.cancel_dl_btn.setEnabled(False)
        self.cancel_dl_btn.setMinimumWidth(100)
        dl_row2.addWidget(self.download_btn)
        dl_row2.addWidget(self.cancel_dl_btn)
        dl_row2.addStretch()
        dl_layout.addLayout(dl_row2)

        self.dl_progress = QProgressBar()
        self.dl_progress.setRange(0, 100)
        self.dl_progress.setValue(0)
        self.dl_progress.setVisible(False)
        dl_layout.addWidget(self.dl_progress)

        self.dl_status_label = QLabel("")
        self.dl_status_label.setWordWrap(True)
        dl_layout.addWidget(self.dl_status_label)

        dl_group.setLayout(dl_layout)
        layout.addWidget(dl_group)

        # --- 升级操作 ---
        upgrade_group = QGroupBox("🚀 升级操作")
        upgrade_layout = QVBoxLayout()

        self.backup_check = QCheckBox("升级前自动备份（worlds/配置/白名单/资源包/行为包）")
        self.backup_check.setChecked(True)
        upgrade_layout.addWidget(self.backup_check)

        warn_label = QLabel("⚠️ 升级前请确保服务器已停止！升级将覆盖服务器核心文件。")
        warn_label.setWordWrap(True)
        warn_label.setStyleSheet("color: #ff9800; font-weight: bold;")
        upgrade_layout.addWidget(warn_label)

        upg_btn_row = QHBoxLayout()
        self.upgrade_btn = QPushButton("🚀 开始升级")
        self.upgrade_btn.clicked.connect(self.start_upgrade)
        self.upgrade_btn.setMinimumWidth(160)
        self.upgrade_btn.setEnabled(False)
        self.upgrade_btn.setStyleSheet("font-weight: bold; font-size: 13px; min-height: 36px;")
        upg_btn_row.addWidget(self.upgrade_btn)
        upg_btn_row.addStretch()
        upgrade_layout.addLayout(upg_btn_row)

        upgrade_group.setLayout(upgrade_layout)
        layout.addWidget(upgrade_group)

        # --- 日志 ---
        log_group = QGroupBox("📜 操作日志")
        log_layout = QVBoxLayout()
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(180)
        self.log_output.setFont(QFont("Consolas", 9))
        log_layout.addWidget(self.log_output)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        # --- 工具自更新 ---
        self.tool_update_group = QGroupBox("🔧 BDS Manager 自身更新")
        tool_layout = QVBoxLayout()
        tool_top = QHBoxLayout()
        tool_top.addWidget(QLabel(f"当前版本: v{__version__}"))
        tool_top.addStretch()
        self.check_tool_btn = QPushButton("🔍 检查工具更新")
        self.check_tool_btn.clicked.connect(self._check_tool_update)
        tool_top.addWidget(self.check_tool_btn)
        tool_layout.addLayout(tool_top)
        self.tool_update_status = QLabel("")
        self.tool_update_status.setWordWrap(True)
        tool_layout.addWidget(self.tool_update_status)
        self.tool_update_group.setLayout(tool_layout)
        layout.addWidget(self.tool_update_group)

        layout.addStretch()

        scroll_area.setWidget(content)
        outer_layout.addWidget(scroll_area)

    # ---------- 方法 ----------
    def _log(self, msg, level="INFO"):
        ts = datetime.now().strftime("%H:%M:%S")
        colors = {"INFO": "#4CAF50", "WARN": "#ff9800", "ERROR": "#f44336", "SUCCESS": "#2196F3"}
        color = colors.get(level, "#ffffff")
        self.log_output.append(f'<span style="color:gray">[{ts}]</span> '
                               f'<span style="color:{color}">[{level}]</span> {msg}')
        # 滚动到底部
        sb = self.log_output.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_branch_changed(self, idx):
        self.selected_branch = self.branch_combo.itemData(idx)

    def refresh_current_info(self):
        server_dir = self.parent.get_absolute_server_dir()
        self.current_dir_label.setText(str(server_dir))
        ver = _detect_current_version(server_dir)
        if ver:
            self.current_version_label.setText(f"v{ver}")
            self.current_version_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #4CAF50;")
        else:
            self.current_version_label.setText("未检测到版本")
            self.current_version_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #ff9800;")
        self._log(f"当前版本检测: {'v' + ver if ver else '未检测到'}", "INFO")

    def check_updates(self, branch="stable"):
        """检查版本更新（优先使用缓存）"""
        # 缓存检查
        cache = self.parent.config.get("version_cache", {})
        now = time.time()
        cache_key = f"latest_{branch}"
        if cache_key in cache:
            entry = cache[cache_key]
            cached_time = entry.get("timestamp", 0)
            if now - cached_time < 3600:  # 1 小时内有效
                ver = entry.get("version")
                url = entry.get("url")
                label = entry.get("label", "")
                if ver and url:
                    self._on_check_result(branch, True, ver, url, label)
                    self._log(f"使用缓存结果: {branch} v{ver}（上次检查: {datetime.fromtimestamp(cached_time).strftime('%H:%M:%S')}）", "INFO")
                    return

        if branch == "stable":
            self.check_stable_btn.setEnabled(False)
            self.check_stable_btn.setText("检查中...")
            self.stable_version_label.setText("检查中...")
        else:
            self.check_preview_btn.setEnabled(False)
            self.check_preview_btn.setText("检查中...")
            self.preview_version_label.setText("检查中...")

        self._log(f"正在检查 {branch} 更新...", "INFO")

        # 显示探测进度条和取消按钮
        self.check_progress_bar.setVisible(True)
        self.check_progress_bar.setValue(0)
        self.cancel_check_btn.setVisible(True)
        self.cancel_check_btn.setEnabled(True)
        self.check_progress_label.setVisible(True)
        self.check_progress_label.setText("准备探测...")

        # 获取当前版本作为探测起点
        server_dir = self.parent.get_absolute_server_dir()
        current_ver = _detect_current_version(server_dir)

        self._check_cancelled = False

        class CheckWorker(BaseWorker):
            progress_signal = pyqtSignal(str, int)
            result_signal = pyqtSignal(bool, str, str, str)

            def __init__(self, branch, current_ver, cancel_fn, parent=None):
                super().__init__(parent)
                self.branch = branch
                self.current_ver = current_ver
                self.cancel_fn = cancel_fn

            def run(self):
                def progress_cb(ver, pct):
                    self.progress_signal.emit(ver, pct)

                def cancel_cb():
                    return self.cancel_fn() if self.cancel_fn else False

                ver, url, label = _fetch_latest_version_info(
                    self.branch, self.current_ver, progress_cb, cancel_cb
                )
                self.result_signal.emit(ver is not None, ver or "", url or "", label)

        self.check_worker = CheckWorker(branch, current_ver, lambda: self._check_cancelled, self)
        self.check_worker.progress_signal.connect(self._on_check_progress)
        self.check_worker.result_signal.connect(
            lambda ok, ver, url, label: self._on_check_result(branch, ok, ver, url, label))
        self.check_worker.finished.connect(self._on_check_finished)
        self.check_worker.start()

    def cancel_version_check(self):
        self._check_cancelled = True
        self.check_cancel_btn.setEnabled(False)
        self._log("正在取消版本检查...", "WARN")

    def _on_check_progress(self, ver, pct):
        self.check_progress_bar.setValue(pct)
        if ver:
            self.check_progress_label.setText(f"探测中... {ver} ({pct}%)")
        else:
            self.check_progress_label.setText(f"探测中... ({pct}%)")

    def _on_check_finished(self):
        self.check_progress_bar.setVisible(False)
        self.cancel_check_btn.setVisible(False)
        self.check_progress_label.setVisible(False)

    def download_manual_version(self):
        """手动指定版本号直接下载"""
        ver = self.manual_version_input.text().strip()
        if not ver:
            toast_warning("请输入版本号", "例如: 1.26.32.2")
            return

        # 验证版本号格式
        if not re.match(r'^\d+\.\d+\.\d+\.\d+$', ver):
            toast_warning("格式错误", "版本号格式应为 X.Y.Z.W")
            return

        branch = self.manual_branch_combo.currentData()
        base_pattern = "bin-win-preview" if branch == "preview" else "bin-win"
        url = f"https://www.minecraft.net/bedrockdedicatedserver/{base_pattern}/bedrock-server-{ver}.zip"
        label = "预览版" if branch == "preview" else "稳定版"

        self._log(f"手动指定版本: v{ver} ({label})", "INFO")
        self._log(f"URL: {url}", "INFO")

        # 先验证 URL 是否有效
        self.manual_download_btn.setEnabled(False)
        self.manual_download_btn.setText("验证中...")
        exists, cl = _check_url_exists(url)

        if not exists:
            self.manual_download_btn.setEnabled(True)
            self.manual_download_btn.setText("⬇️ 直接下载")
            toast_error("版本不存在", "请确认版本号正确")
            return
            self._log(f"版本 v{ver} 不存在 (HTTP 404)", "ERROR")
            return

        self.manual_download_btn.setEnabled(True)
        self.manual_download_btn.setText("⬇️ 直接下载")

        # 选择保存路径
        server_dir = self.parent.get_absolute_server_dir()
        default_name = f"bedrock-server-{ver}.zip"
        save_path, _ = QFileDialog.getSaveFileName(
            self, "保存服务器压缩包", os.path.join(server_dir, default_name),
            "ZIP 文件 (*.zip)")
        if not save_path:
            return

        # 设置下载参数并启动
        if branch == "stable":
            self.latest_stable_version = ver
            self.latest_stable_url = url
        else:
            self.latest_preview_version = ver
            self.latest_preview_url = url
        self.branch_combo.setCurrentIndex(0 if branch == "stable" else 1)
        self.downloaded_zip = save_path

        self.download_btn.setEnabled(False)
        self.cancel_dl_btn.setEnabled(True)
        self.dl_progress.setVisible(True)
        self.dl_progress.setValue(0)
        self.dl_status_label.setText("准备下载...")
        self._log(f"开始下载 {label} v{ver}", "INFO")
        self._log(f"保存到: {save_path}", "INFO")

        self.download_worker = UpgradeWorker(url, save_path, self)
        self.download_worker.progress.connect(self._on_download_progress)
        self.download_worker.status_signal.connect(self._on_download_status)
        self.download_worker.finished.connect(self._on_download_finished)
        self.download_worker.start()

    def _on_check_result(self, branch, ok, ver, url, label):
        self._last_check_branch = branch

        # 重置按钮
        if branch == "stable":
            self.check_stable_btn.setEnabled(True)
            self.check_stable_btn.setText("🔍 检查稳定版更新")
        else:
            self.check_preview_btn.setEnabled(True)
            self.check_preview_btn.setText("🔍 检查预览版更新")

        if ok:
            if branch == "stable":
                self.latest_stable_version = ver
                self.latest_stable_url = url
                self.stable_version_label.setText(f"v{ver} ({label})")
                self.stable_version_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            else:
                self.latest_preview_version = ver
                self.latest_preview_url = url
                self.preview_version_label.setText(f"v{ver} ({label})")
                self.preview_version_label.setStyleSheet("color: #4CAF50; font-weight: bold;")

            current = _detect_current_version(self.parent.get_absolute_server_dir())
            if current and current == ver:
                self.check_status_label.setText(f"✅ 当前已是最新版本 (v{current})")
                self.check_status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            else:
                self.check_status_label.setText(f"📢 发现新版本 v{ver}，可下载升级")
                self.check_status_label.setStyleSheet("color: #ff9800; font-weight: bold;")
                self.download_btn.setEnabled(True)
            self._log(f"{branch}最新版本: v{ver}", "SUCCESS")

            # 缓存结果
            if "version_cache" not in self.parent.config:
                self.parent.config["version_cache"] = {}
            self.parent.config["version_cache"][f"latest_{branch}"] = {
                "version": ver, "url": url, "label": label,
                "timestamp": time.time()
            }
            self.parent.save_config()
        else:
            if branch == "stable":
                self.stable_version_label.setText(f"检查失败: {label}")
                self.stable_version_label.setStyleSheet("color: #f44336;")
            else:
                self.preview_version_label.setText(f"检查失败: {label}")
                self.preview_version_label.setStyleSheet("color: #f44336;")
            self.check_status_label.setText(f"❌ 检查失败: {label}")
            self.check_status_label.setStyleSheet("color: #f44336;")
            self._log(f"版本检查失败: {label}", "ERROR")

    def _on_check_finished(self):
        self.check_progress_bar.setVisible(False)
        self.cancel_check_btn.setVisible(False)
        self.check_progress_label.setVisible(False)

    def start_download(self):
        branch = self.selected_branch
        if branch == "stable":
            url = self.latest_stable_url
            ver = self.latest_stable_version
        else:
            url = self.latest_preview_url
            ver = self.latest_preview_version

        if not url:
            toast_warning("未检查更新", "请先点击「检查更新」按钮")
            return

        # 选择保存路径
        server_dir = self.parent.get_absolute_server_dir()
        default_name = f"bedrock-server-{ver}.zip"
        save_path, _ = QFileDialog.getSaveFileName(
            self, "保存服务器压缩包", os.path.join(server_dir, default_name),
            "ZIP 文件 (*.zip)")
        if not save_path:
            return

        self.downloaded_zip = save_path
        self.download_btn.setEnabled(False)
        self.cancel_dl_btn.setEnabled(True)
        self.dl_progress.setVisible(True)
        self.dl_progress.setValue(0)
        self.dl_status_label.setText("准备下载...")
        self._log(f"开始下载 {branch} v{ver}", "INFO")
        self._log(f"保存到: {save_path}", "INFO")

        self.download_worker = UpgradeWorker(url, save_path, self)
        self.download_worker.progress.connect(self._on_download_progress)
        self.download_worker.status_signal.connect(self._on_download_status)
        self.download_worker.finished.connect(self._on_download_finished)
        self.download_worker.start()

    def cancel_download(self):
        if self.download_worker and self.download_worker.isRunning():
            self.download_worker.cancel()
            self._log("用户取消下载", "WARN")
            self._reset_download_ui()

    def _on_download_progress(self, pct):
        self.dl_progress.setValue(pct)

    def _on_download_status(self, msg):
        self.dl_status_label.setText(msg)

    def _on_download_finished(self, success, message):
        self.download_btn.setEnabled(True)
        self.cancel_dl_btn.setEnabled(False)
        if success:
            self.dl_progress.setValue(100)
            self.dl_status_label.setText(f"✅ {message}")
            self.dl_status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            self.upgrade_btn.setEnabled(True)
            self._log(f"下载完成: {self.downloaded_zip}", "SUCCESS")
        else:
            self.dl_progress.setVisible(False)
            self.dl_status_label.setText(f"❌ {message}")
            self.dl_status_label.setStyleSheet("color: #f44336;")
            self.downloaded_zip = None
            toast_error("下载失败", message)
            self._log(f"下载失败: {message}", "ERROR")

    def _reset_download_ui(self):
        self.download_btn.setEnabled(True)
        self.cancel_dl_btn.setEnabled(False)
        self.dl_progress.setVisible(False)
        self.dl_progress.setValue(0)
        self.dl_status_label.setText("")

    def start_upgrade(self):
        if not self.downloaded_zip or not os.path.exists(self.downloaded_zip):
            toast_error("未下载", "请先下载更新包")
            return

        server_dir = self.parent.get_absolute_server_dir()

        # 检查服务器是否运行
        if self.parent.is_server_running():
            reply = QMessageBox.question(
                self, "服务器正在运行",
                "升级前需要停止服务器。是否立即停止服务器并继续升级？",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self._log("正在停止服务器...", "WARN")
                self.parent.console_tab.stop_server()
                for _ in range(30):
                    QApplication.processEvents()
                    if not self.parent.is_server_running():
                        break
                    time.sleep(0.1)
            else:
                self._log("用户取消升级（服务器未停止）", "WARN")
                return

        # 确认升级
        reply = QMessageBox.warning(
            self, "确认升级",
            "即将执行以下操作：\n\n"
            f"1. {'备份 worlds/配置/白名单/资源包/行为包' if self.backup_check.isChecked() else '(不备份，直接覆盖)'}\n"
            "2. 解压新版服务器文件，覆盖核心文件\n"
            f"3. {'恢复备份的文件' if self.backup_check.isChecked() else ''}\n\n"
            f"目标目录: {server_dir}\n\n"
            "此操作不可撤销，是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            self._log("用户取消升级", "WARN")
            return

        # 禁用按钮
        self.upgrade_btn.setEnabled(False)
        self._log("=" * 50, "INFO")
        self._log("开始升级流程...", "INFO")

        class UpgradeExecWorker(BaseWorker):
            status_signal = pyqtSignal(str)
            log_signal = pyqtSignal(str, str)

            def __init__(self, server_dir, zip_path, do_backup, parent=None):
                super().__init__(parent)
                self.server_dir = Path(server_dir)
                self.zip_path = zip_path
                self.do_backup = do_backup

            def _log(self, msg, level="INFO"):
                self.log_signal.emit(msg, level)

            def run(self):
                try:
                    self._backup_dir = None

                    # 1. 备份
                    if self.do_backup:
                        self._log("步骤 1/3: 备份关键文件...", "INFO")
                        self._backup_dir = self._backup_critical_files()
                        self._log(f"备份完成 → {self._backup_dir}", "SUCCESS")
                    else:
                        self._log("步骤 1/3: 跳过备份（用户选择不备份）", "WARN")

                    # 2. 解压
                    self._log("步骤 2/3: 解压新版服务器文件...", "INFO")
                    self._extract_and_merge()
                    self._log("解压完成", "SUCCESS")

                    # 3. 恢复备份
                    if self.do_backup and self._backup_dir:
                        self._log("步骤 3/3: 恢复备份文件...", "INFO")
                        self._restore_backup()
                        self._log("恢复完成", "SUCCESS")
                    else:
                        self._log("步骤 3/3: 跳过恢复（未备份）", "INFO")

                    self._log("✅ 升级完成！", "SUCCESS")
                    toast_success("升级完成", "请重新启动服务器")
                    self.finished.emit(True, "升级成功！")
                except Exception as e:
                    self._log(f"❌ 升级失败: {e}", "ERROR")
                    toast_error("升级失败", str(e))
                    self.finished.emit(False, str(e))

            def _backup_critical_files(self):
                """备份关键文件到临时目录"""
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_root = self.server_dir / "backups" / f"pre_upgrade_{ts}"
                os.makedirs(backup_root, exist_ok=True)

                # 需要备份的目录和文件
                dirs_to_backup = [
                    "worlds", "resource_packs", "behavior_packs",
                    "development_behavior_packs", "development_resource_packs",
                    "development_skin_packs", "config"
                ]
                files_to_backup = [
                    "server.properties", "allowlist.json", "permissions.json",
                    "packetlimitconfig.json", "profanity_filter.wlist"
                ]

                for d in dirs_to_backup:
                    src = self.server_dir / d
                    if src.exists():
                        dst = backup_root / d
                        try:
                            shutil.copytree(src, dst)
                            self._log(f"  已备份目录: {d}", "INFO")
                        except Exception as e:
                            self._log(f"  备份 {d} 失败: {e}", "WARN")

                for f in files_to_backup:
                    src = self.server_dir / f
                    if src.exists():
                        dst = backup_root / f
                        try:
                            shutil.copy2(src, dst)
                            self._log(f"  已备份文件: {f}", "INFO")
                        except Exception as e:
                            self._log(f"  备份 {f} 失败: {e}", "WARN")

                return backup_root

            def _extract_and_merge(self):
                """解压新版服务器并覆盖文件"""
                with zipfile.ZipFile(self.zip_path, "r") as zf:
                    # 检查是否有根目录前缀（如 bedrock_server/）
                    names = zf.namelist()
                    top_dirs = set()
                    for name in names:
                        parts = name.replace("\\\\", "/").split("/")
                        if len(parts) > 1 and parts[0]:
                            top_dirs.add(parts[0])

                    has_prefix = len(top_dirs) == 1 and not any(
                        "/" not in n and "." in n for n in names[:5]
                    )

                    total = len(names)
                    for i, name in enumerate(names):
                        # 计算目标路径
                        if has_prefix:
                            # 去掉第一层目录前缀
                            parts = name.replace("\\\\", "/").split("/")
                            rel_path = "/".join(parts[1:]) if len(parts) > 1 else ""
                            if not rel_path:
                                continue
                        else:
                            rel_path = name.replace("\\\\", "/")

                        # 跳过会覆盖的关键目录/文件（备份由恢复步骤处理）
                        skip_prefixes = [
                            "worlds/", "resource_packs/", "behavior_packs/",
                            "server.properties", "allowlist.json", "permissions.json",
                            "packetlimitconfig.json"
                        ]
                        skip_prefixes_lower = [s.lower() for s in skip_prefixes]
                        if any(rel_path.lower().startswith(s) for s in skip_prefixes_lower):
                            continue

                        target = self.server_dir / rel_path
                        if name.endswith("/") or name.endswith("\\\\"):
                            os.makedirs(target, exist_ok=True)
                        else:
                            os.makedirs(target.parent, exist_ok=True)
                            with zf.open(name) as src_entry:
                                with open(target, "wb") as dst_entry:
                                    dst_entry.write(src_entry.read())

                        if total > 0 and i % 200 == 0:
                            pct = int(i * 100 / total)
                            self.status_signal.emit(f"解压中... {pct}%")

            def _restore_backup(self):
                """恢复备份的关键文件"""
                if not self._backup_dir or not self._backup_dir.exists():
                    return

                dirs_to_restore = [
                    "worlds", "resource_packs", "behavior_packs",
                    "development_behavior_packs", "development_resource_packs",
                    "development_skin_packs", "config"
                ]
                files_to_restore = [
                    "server.properties", "allowlist.json", "permissions.json",
                    "packetlimitconfig.json", "profanity_filter.wlist"
                ]

                for d in dirs_to_restore:
                    src = self._backup_dir / d
                    if src.exists():
                        dst = self.server_dir / d
                        if dst.exists():
                            shutil.rmtree(dst, ignore_errors=True)
                        shutil.copytree(src, dst)
                        self._log(f"  已恢复目录: {d}", "INFO")

                for f in files_to_restore:
                    src = self._backup_dir / f
                    if src.exists():
                        dst = self.server_dir / f
                        shutil.copy2(src, dst)
                        self._log(f"  已恢复文件: {f}", "INFO")

        self.upgrade_worker = UpgradeExecWorker(
            server_dir, self.downloaded_zip, self.backup_check.isChecked(), self
        )
        self.upgrade_worker.log_signal.connect(self._log)
        self.upgrade_worker.status_signal.connect(lambda m: self.dl_status_label.setText(m))
        self.upgrade_worker.finished.connect(self._on_upgrade_finished)
        self.upgrade_worker.start()

    def _on_upgrade_finished(self, success, message):
        self.upgrade_btn.setEnabled(bool(self.downloaded_zip and os.path.exists(self.downloaded_zip)))
        if success:
            toast_success("升级完成", "请重新启动服务器")
            self.refresh_current_info()
            if hasattr(self.parent, 'refresh_all_tabs'):
                self.parent.refresh_all_tabs()
        else:
            QMessageBox.critical(self, "升级失败", f"升级过程中发生错误：\n\n{message}\n\n"
                                                   "备份文件位于 backups/pre_upgrade_* 目录，可手动恢复。")

    # ---------- 工具自更新方法 ----------
    def _check_tool_update(self):
        """检查 BDS Manager 自身是否有新版本"""
        self.check_tool_btn.setEnabled(False)
        self.check_tool_btn.setText("检查中...")
        self.tool_update_status.setText("🔍 正在连接 GitHub...")
        self._log("正在检查 BDS Manager 自身更新...", "INFO")

        class ToolVersionWorker(BaseWorker):
            result_signal = pyqtSignal(bool, str, str, str)

            def run(self):
                try:
                    url = ("https://raw.githubusercontent.com/TussalZeus18028/"
                           "bds_manager/main/version.json")
                    req = urllib.request.Request(url, headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                    })
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                        remote_ver = data.get("version", "")
                        release_date = data.get("release_date", "")
                        changelog = data.get("changelog", "")
                        download_url = data.get("download_url", "")
                        self.result_signal.emit(
                            True, remote_ver, release_date,
                            changelog or ""
                        )
                except urllib.error.HTTPError as e:
                    self.result_signal.emit(False, "", "", f"HTTP {e.code}: {e.reason}")
                except urllib.error.URLError as e:
                    self.result_signal.emit(False, "", "", f"网络错误: {e.reason}")
                except json.JSONDecodeError as e:
                    self.result_signal.emit(False, "", "", f"JSON 解析失败: {e}")
                except Exception as e:
                    self.result_signal.emit(False, "", "", f"未知错误: {e}")

        self._tool_ver_worker = ToolVersionWorker(self)
        self._tool_ver_worker.result_signal.connect(self._on_tool_update_result)
        self._tool_ver_worker.start()

    def _on_tool_update_result(self, ok, remote_ver, release_date, changelog):
        self.check_tool_btn.setEnabled(True)
        self.check_tool_btn.setText("🔍 检查工具更新")

        if not ok:
            self.tool_update_status.setText(f"❌ 检查失败: {changelog}")
            self.tool_update_status.setStyleSheet("color: #f44336; padding: 4px;")
            toast_error("检查更新失败", changelog)
            self._log(f"工具更新检查失败: {changelog}", "ERROR")
            return

        self._log(f"远程版本: v{remote_ver} | 本地: v{__version__}", "INFO")

        def _cmp(v1, v2):
            try:
                a = [int(x) for x in v1.split(".")]
                b = [int(x) for x in v2.split(".")]
                while len(a) < 4: a.append(0)
                while len(b) < 4: b.append(0)
                return (a > b) - (a < b)
            except (ValueError, IndexError):
                return 0

        if _cmp(remote_ver, __version__) > 0:
            info = f"📢 发现新版本 v{remote_ver}！（当前 v{__version__}）\n发布日期: {release_date}"
            if changelog:
                info += f"\n\n更新内容:\n{changelog}"
            self.tool_update_status.setText(info)
            self.tool_update_status.setStyleSheet("color: #ff9800; font-weight: bold; padding: 4px;")
            self._log(f"发现新版本 v{remote_ver}", "SUCCESS")

            reply = QMessageBox.question(
                self, "发现新版本",
                f"BDS Manager 有新版本可用！\n\n"
                f"当前版本: v{__version__}\n"
                f"最新版本: v{remote_ver}\n"
                f"发布日期: {release_date}\n\n"
                f"是否立即下载并更新？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            if reply == QMessageBox.Yes:
                self._download_tool_update(remote_ver)
        else:
            self.tool_update_status.setText(f"✅ 已是最新版本 v{__version__}（远程: v{remote_ver}）")
            self.tool_update_status.setStyleSheet("color: #4CAF50; padding: 4px;")
            self._log("已是最新版本", "SUCCESS")

    def _download_tool_update(self, remote_ver):
        """下载新版 bds_manager.py"""
        self.check_tool_btn.setEnabled(False)
        self.check_tool_btn.setText("下载中...")
        self.tool_update_status.setText(f"⬇️ 正在下载 v{remote_ver}...")
        self._log(f"开始下载 BDS Manager v{remote_ver}...", "INFO")

        class DownloadSelfWorker(BaseWorker):
            def run(self):
                try:
                    url = ("https://raw.githubusercontent.com/TussalZeus18028/"
                           "bds_manager/main/bds_manager.py")
                    req = urllib.request.Request(url, headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                    })
                    with urllib.request.urlopen(req, timeout=60) as resp:
                        new_content = resp.read()

                    if not new_content:
                        self.finished.emit(False, "下载的文件为空")
                        return
                    if len(new_content) < 1000:
                        self.finished.emit(False, f"文件异常（仅 {len(new_content)} 字节）")
                        return

                    self._new_content = new_content
                    self.finished.emit(True, f"下载完成（{len(new_content)/1024:.1f} KB）")
                except urllib.error.HTTPError as e:
                    self.finished.emit(False, f"HTTP {e.code}: {e.reason}")
                except urllib.error.URLError as e:
                    self.finished.emit(False, f"网络错误: {e.reason}")
                except Exception as e:
                    self.finished.emit(False, f"下载失败: {e}")

        self._dl_self_worker = DownloadSelfWorker(self)
        self._dl_self_worker.finished.connect(
            lambda ok, msg: self._on_tool_download_finished(ok, msg))
        self._dl_self_worker.start()

    def _on_tool_download_finished(self, success, message):
        self.check_tool_btn.setEnabled(True)
        self.check_tool_btn.setText("🔍 检查工具更新")

        if not success:
            self.tool_update_status.setText(f"❌ 下载失败: {message}")
            self.tool_update_status.setStyleSheet("color: #f44336; padding: 4px;")
            toast_error("下载失败", message)
            self._log(f"下载失败: {message}", "ERROR")
            return

        new_content = getattr(self._dl_self_worker, "_new_content", None)
        if not new_content:
            self._log("下载内容为空", "ERROR")
            return

        toast_success("下载完成", message)
        self._log(f"下载完成: {message}", "SUCCESS")

        reply = QMessageBox.question(
            self, "下载完成",
            f"新版本已下载完成！（{message}）\n\n"
            "是否立即替换当前文件并重启？\n"
            "⚠️ 替换后程序将自动重启。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )

        if reply == QMessageBox.Yes:
            try:
                current_path = os.path.join(SCRIPT_DIR, "bds_manager.py")
                backup_path = current_path + ".bak"
                shutil.copy2(current_path, backup_path)
                with open(current_path, "wb") as f:
                    f.write(new_content)
                self._log("文件已替换，旧文件备份为 .bak", "SUCCESS")
                QMessageBox.information(
                    self, "更新完成",
                    "BDS Manager 已更新！\n\n"
                    f"旧文件已备份为 bds_manager.py.bak\n\n"
                    "程序即将自动重启。"
                )
                import subprocess
                subprocess.Popen([sys.executable] + sys.argv,
                                 creationflags=subprocess.CREATE_NO_WINDOW
                                 if sys.platform == "win32" else 0)
                QApplication.quit()
            except Exception as e:
                self._log(f"替换文件失败: {e}", "ERROR")
                QMessageBox.critical(self, "更新失败", f"替换文件时出错：{e}")
        else:
            self.tool_update_status.setText("⚠️ 已取消更新。新版本已下载但未安装。")
            self.tool_update_status.setStyleSheet("color: #ff9800; padding: 4px;")
            self._log("用户取消安装更新", "WARN")

# ---------- 仪表盘标签页 ----------
class DashboardTab(QWidget):
    """首页仪表盘：状态概览 + 玩家列表 + 快捷指令"""
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self._refresh)
        self._refresh_timer.start(2000)  # 每 2 秒刷新
        self._tps_samples = []
        self._last_tick_count = 0
        self._last_tick_time = time.time()
        self.init_ui()

    def init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(8)

        # === 第一行：状态卡片 ===
        status_row = QHBoxLayout()
        self._make_status_card(status_row, "🟢 服务器", "server", "停止")
        self._make_status_card(status_row, "👥 在线玩家", "players", "0")
        self._make_status_card(status_row, "⏱ 运行时长", "uptime", "00:00:00")
        self._make_status_card(status_row, "📌 BDS 版本", "bds_ver", "--")
        self._make_status_card(status_row, "📦 备份", "backup", "--")
        layout.addLayout(status_row)

        # === 第二行：玩家列表 + 快捷指令 ===
        row2 = QHBoxLayout()

        # 玩家列表
        players_group = QGroupBox("👥 在线玩家")
        players_layout = QVBoxLayout()
        self.players_list = QListWidget()
        self.players_list.setMaximumHeight(140)
        self.players_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.players_list.customContextMenuRequested.connect(self._player_context_menu)
        players_layout.addWidget(self.players_list)
        players_group.setLayout(players_layout)
        row2.addWidget(players_group, 1)

        # 玩家右键菜单
        self.players_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.players_list.customContextMenuRequested.connect(self._player_context_menu)
        layout.addLayout(row2)

        # === 第三行：性能 + TPS ===
        perf_group = QGroupBox("📊 性能监控")
        perf_layout = QGridLayout()
        self.cpu_label = QLabel("CPU: --%")
        self.mem_label = QLabel("内存: --%")
        self.net_label = QLabel("网络: --")
        self.cpu_pbar = QProgressBar(); self.cpu_pbar.setMaximum(100); self.cpu_pbar.setMaximumHeight(14)
        self.mem_pbar = QProgressBar(); self.mem_pbar.setMaximum(100); self.mem_pbar.setMaximumHeight(14)
        perf_layout.addWidget(QLabel("CPU:"), 0, 0)
        perf_layout.addWidget(self.cpu_pbar, 0, 1)
        perf_layout.addWidget(self.cpu_label, 0, 2)
        perf_layout.addWidget(QLabel("内存:"), 1, 0)
        perf_layout.addWidget(self.mem_pbar, 1, 1)
        perf_layout.addWidget(self.mem_label, 1, 2)
        perf_layout.addWidget(self.net_label, 2, 2)
        self.tps_label = QLabel("TPS: N/A")
        perf_layout.addWidget(QLabel("TPS:"), 2, 0)
        perf_layout.addWidget(self.tps_label, 2, 1)
        perf_group.setLayout(perf_layout)
        layout.addWidget(perf_group)

        layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll)

        # 初始化刷新
        self._refresh()

    def _make_status_card(self, row, title, key, default):
        group = QGroupBox(title)
        group.setStyleSheet("QGroupBox { font-weight: bold; font-size: 13px; }")
        gl = QVBoxLayout()
        gl.setAlignment(Qt.AlignCenter)
        label = QLabel(default)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("font-size: 18px; font-weight: bold; color: #4CAF50;")
        setattr(self, f"card_{key}", label)
        gl.addWidget(label)
        group.setLayout(gl)
        row.addWidget(group)

    def _player_context_menu(self, pos):
        """玩家列表右键菜单"""
        item = self.players_list.itemAt(pos)
        if not item:
            return
        player = item.text()
        menu = QMenu()
        for action_text, cmd in [("踢出", "kick"), ("封禁", "ban"), ("设为OP", "op"), ("取消OP", "deop")]:
            act = menu.addAction(action_text)
            act.triggered.connect(lambda checked, c=cmd, p=player: self._run_player_cmd(c, p))
        menu.exec_(self.players_list.mapToGlobal(pos))

    def _run_player_cmd(self, cmd, player):
        """对选中玩家执行命令"""
        ct = self.parent.console_tab
        ct.cmd_input.setText(f"{cmd} {player}")
        ct.send_command()

    def _refresh(self):
        """定时刷新仪表盘数据"""
        ct = self.parent.console_tab
        stats = ct.get_server_stats()

        # 服务器状态
        if stats["running"]:
            self.card_server.setText("🟢 运行中")
            self.card_server.setStyleSheet("font-size: 18px; font-weight: bold; color: #4CAF50;")
        else:
            self.card_server.setText("⏹ 已停止")
            self.card_server.setStyleSheet("font-size: 18px; font-weight: bold; color: #f44336;")

        # 玩家数
        self.card_players.setText(str(stats["player_count"]))
        self.card_players.setStyleSheet("font-size: 18px; font-weight: bold; color: #66ccff;")

        # 运行时长
        secs = stats["uptime_seconds"]
        if secs > 0:
            h, m, s = secs // 3600, (secs % 3600) // 60, secs % 60
            self.card_uptime.setText(f"{h:02d}:{m:02d}:{s:02d}")
            self.card_uptime.setStyleSheet("font-size: 18px; font-weight: bold; color: #ffaa33;")
        else:
            self.card_uptime.setText("--")
            self.card_uptime.setStyleSheet("font-size: 18px; font-weight: bold; color: #888;")

        # BDS 版本
        ver = stats.get("bds_version", "")
        self.card_bds_ver.setText(ver or "--")
        self.card_bds_ver.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {'#88ddff' if ver else '#888'};")

        # 玩家列表
        self.players_list.clear()
        for p in stats["players"]:
            self.players_list.addItem(p)

        # 备份信息
        backup_dir = self.parent.get_absolute_server_dir() + "/backups"
        if os.path.exists(backup_dir):
            backups = sorted(
                [f for f in os.listdir(backup_dir) if f.endswith(".zip")],
                key=lambda f: os.path.getmtime(os.path.join(backup_dir, f)),
                reverse=True
            )
            if backups:
                last_bk = backups[0]
                bk_time = datetime.fromtimestamp(
                    os.path.getmtime(os.path.join(backup_dir, last_bk))
                ).strftime("%m-%d %H:%M")
                self.card_backup.setText(f"最近: {bk_time}")
                self.card_backup.setStyleSheet("font-size: 14px; color: #4CAF50;")
            else:
                self.card_backup.setText("无备份")
                self.card_backup.setStyleSheet("font-size: 14px; color: #888;")

        # CPU/内存
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory().percent
            net = psutil.net_io_counters()
            self.cpu_pbar.setValue(int(cpu))
            self.mem_pbar.setValue(int(mem))
            self.cpu_label.setText(f"CPU: {cpu:.1f}%")
            self.mem_label.setText(f"内存: {mem:.1f}%")
            sent_kb = net.bytes_sent / 1024
            recv_kb = net.bytes_recv / 1024
            self.net_label.setText(f"上传: {sent_kb/1024:.1f}MB / 下载: {recv_kb/1024:.1f}MB")
        except Exception:
            pass

        # TPS（活动率估算）
        tps = stats.get("tps", 0)
        if tps > 0:
            if tps >= 5:
                self.tps_label.setText(f"TPS: {tps:.1f} 🟢")
                self.tps_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            elif tps >= 1:
                self.tps_label.setText(f"TPS: {tps:.1f} 🟡")
                self.tps_label.setStyleSheet("color: #ffaa33; font-weight: bold;")
            else:
                self.tps_label.setText(f"TPS: {tps:.1f} 🔴")
                self.tps_label.setStyleSheet("color: #f44336; font-weight: bold;")
        else:
            self.tps_label.setText("TPS: --")
            self.tps_label.setStyleSheet("color: #888;")

# ---------- 主窗口 ----------
class BDSManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = self.load_config()
        self.theme_manager = ThemeManager()
        self.custom_colors = self.config.get("custom_colors", {
            "background": "#2b2b2b",
            "text": "#ffffff",
            "accent": "#4CAF50",
            "border": "#555555",
            "group_bg": "#363636",
            "input_bg": "#404040",
            "button_bg": "#4CAF50",
            "button_hover": "#45a049"
        })
        self.theme_manager.set_custom_colors(self.custom_colors)
        # 共享服务器状态（ConsoleTab 写入，DashboardTab 读取）
        self.server_stats = {"players": []}
        # Toast 通知系统
        set_toast_parent(self)
        self.init_ui()
        self.apply_theme(self.config.get("theme", "auto"))
        # 自动备份定时器
        self.backup_timer = QTimer()
        self.backup_timer.timeout.connect(self.auto_backup)
        self.update_backup_timer()
        # 内存告警监视器（每30秒检查）
        self._mem_timer = QTimer()
        self._mem_timer.timeout.connect(self._check_memory)
        self._mem_timer.start(30000)
        self._last_mem_warn = 0  # 上次告警时间，避免频繁弹
        # 文件监控（防抖）
        self.watcher = QFileSystemWatcher()
        self.watcher.directoryChanged.connect(self.on_external_change)
        self.watcher.fileChanged.connect(self.on_external_change)
        self._refresh_timer = QTimer()
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self.refresh_all_tabs)
        self.init_watcher()
        # 系统托盘
        self.create_tray_icon()
        # 启动自检提示
        QTimer.singleShot(500, self._show_startup_toasts)

    def keyPressEvent(self, event):
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_D:
            if self.is_server_running():
                reply = QMessageBox.question(self, "确认退出", "服务器正在运行，退出前是否先停止服务器？",
                                             QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
                if reply == QMessageBox.Yes:
                    self.console_tab.stop_server()
                    # 等待服务器退出（最多 3 秒）
                    for _ in range(30):
                        QApplication.processEvents()
                        if not self.is_server_running():
                            break
                        time.sleep(0.1)
                elif reply == QMessageBox.Cancel:
                    return
            self.quit_app()
        else:
            super().keyPressEvent(event)

    def get_absolute_server_dir(self):
        server_dir_cfg = self.config.get("server_dir", "Server")
        if os.path.isabs(server_dir_cfg):
            return server_dir_cfg
        return os.path.join(SCRIPT_DIR, server_dir_cfg)

    def get_server_exe_path(self):
        exe_rel = self.config.get("server_exe", "bedrock_server.exe")
        server_dir = self.get_absolute_server_dir()
        return os.path.join(server_dir, exe_rel)

    def get_level_name(self):
        if os.path.exists(SERVER_PROPERTIES):
            try:
                with open(SERVER_PROPERTIES, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("level-name="):
                            return line.split("=", 1)[1].strip()
            except Exception as e:
                log_error(f"读取 level-name 失败: {e}")
        return "Bedrock level"

    def is_server_running(self):
        return self.console_tab.is_server_running()

    def load_config(self):
        default = {
            "theme": "dark",
            "server_dir": "Server",
            "server_exe": "bedrock_server.exe",
            "backup_interval": 60,
            "monitor_interval": 2000,
            "custom_colors": {},
            "frpc_path": "",
            "version_cache": {}
        }
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    for k, v in default.items():
                        if k not in loaded:
                            loaded[k] = v
                    return loaded
            except Exception as e:
                log_error(f"加载配置文件失败: {e}")
                return default
        return default

    def save_config(self):
        config = {
            "theme": self.config.get("theme", "dark"),
            "server_dir": self.config.get("server_dir", "Server"),
            "server_exe": self.config.get("server_exe", "bedrock_server.exe"),
            "backup_interval": self.config.get("backup_interval", 60),
            "monitor_interval": self.config.get("monitor_interval", 2000),
            "custom_colors": self.custom_colors,
            "frpc_path": self.config.get("frpc_path", ""),
            "version_cache": self.config.get("version_cache", {}),
            "window_width": self.config.get("window_width", 1200),
            "window_height": self.config.get("window_height", 800),
            "mem_warn_threshold": self.config.get("mem_warn_threshold", 80),
            "hidpi_enabled": self.config.get("hidpi_enabled", True),
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4)
        except Exception as e:
            log_error(f"保存配置文件失败: {e}")
        self.update_global_paths()
        log_info(f"服务器目录已更新: {SERVER_DIR}")
        self.init_watcher()

    def update_global_paths(self):
        global SERVER_DIR, SERVER_PROPERTIES, ALLOWLIST_FILE, PERMISSIONS_FILE
        global PACKET_LIMIT_FILE, WORLDS_DIR, RESOURCE_PACKS_DIR, BEHAVIOR_PACKS_DIR, BACKUP_DIR
        SERVER_DIR = self.get_absolute_server_dir()
        os.makedirs(SERVER_DIR, exist_ok=True)
        SERVER_PROPERTIES = os.path.join(SERVER_DIR, "server.properties")
        ALLOWLIST_FILE = os.path.join(SERVER_DIR, "allowlist.json")
        PERMISSIONS_FILE = os.path.join(SERVER_DIR, "permissions.json")
        PACKET_LIMIT_FILE = os.path.join(SERVER_DIR, "packetlimitconfig.json")
        WORLDS_DIR = os.path.join(SERVER_DIR, "worlds")
        RESOURCE_PACKS_DIR = os.path.join(SERVER_DIR, "resource_packs")
        BEHAVIOR_PACKS_DIR = os.path.join(SERVER_DIR, "behavior_packs")
        BACKUP_DIR = os.path.join(SERVER_DIR, "backups")
        for d in [WORLDS_DIR, RESOURCE_PACKS_DIR, BEHAVIOR_PACKS_DIR, BACKUP_DIR]:
            os.makedirs(d, exist_ok=True)

    def update_backup_timer(self):
        interval = self.config.get("backup_interval", 60)
        self.backup_timer.stop()
        if interval > 0:
            self.backup_timer.start(interval * 60 * 1000)
            log_info(f"自动备份已启用，间隔 {interval} 分钟")
        else:
            log_info("自动备份已禁用")

    def _check_memory(self):
        """检查内存使用率，超过阈值则告警"""
        try:
            import psutil
            mem = psutil.virtual_memory().percent
            threshold = self.config.get("mem_warn_threshold", 80)
            if mem > threshold and time.time() - self._last_mem_warn > 120:
                self._last_mem_warn = time.time()
                toast_warning("内存不足", f"内存使用率 {mem:.1f}%（阈值 {threshold}%）")
        except Exception:
            pass

    def auto_backup(self):
        level_name = self.get_level_name()
        world_path = get_world_path(level_name)
        if os.path.exists(world_path) and not self.is_server_running():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"auto_{level_name}_{timestamp}.zip"
            backup_path = os.path.join(BACKUP_DIR, backup_name)
            try:
                with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for root, dirs, files in os.walk(world_path):
                        for file in files:
                            file_path = os.path.join(root, file)
                            arcname = os.path.relpath(file_path, os.path.dirname(world_path))
                            zipf.write(file_path, arcname)
                log_success(f"自动备份完成: {backup_name}")
                toast_success("自动备份完成", backup_name)
                # 清理旧备份：保留最近 20 个，删除多余的
                self._cleanup_old_backups(keep=20)
            except Exception as e:
                log_error(f"自动备份失败: {e}")
                toast_error("备份失败", str(e))
        else:
            log_debug("自动备份跳过：世界不存在或服务器正在运行")

    def _cleanup_old_backups(self, keep=20):
        """清理旧备份文件，仅保留最近 keep 个"""
        try:
            if not os.path.exists(BACKUP_DIR):
                return
            backups = sorted(
                [f for f in os.listdir(BACKUP_DIR) if f.endswith(".zip")],
                key=lambda f: os.path.getmtime(os.path.join(BACKUP_DIR, f)),
                reverse=True
            )
            for old in backups[keep:]:
                os.remove(os.path.join(BACKUP_DIR, old))
                log_info(f"已删除旧备份: {old}")
        except Exception as e:
            log_warning(f"清理旧备份失败: {e}")

    def init_ui(self):
        self.setWindowTitle("Minecraft Bedrock Server 管理工具 ")
        # 恢复上次窗口大小
        w = self.config.get("window_width", 1200)
        h = self.config.get("window_height", 800)
        self.setGeometry(100, 100, w, h)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        title = QLabel(" 基岩版服务器管理终端 ")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px;")
        layout.addWidget(title)

        self.tab_widget = QTabWidget()
        self.console_tab = ConsoleTab(self)
        self.packs_tab = PacksTab(self)
        self.config_tab = ConfigTab(self)
        self.world_tab = WorldTab(self)

        monitor_tab = QWidget()
        monitor_layout = QVBoxLayout(monitor_tab)
        self.system_monitor = SystemMonitor(interval=self.config.get("monitor_interval", 2000), history_length=60)
        monitor_layout.addWidget(self.system_monitor)
        monitor_layout.addStretch()

        self.tunnel_tab = TunnelTab(self)
        self.upgrade_tab = UpgradeTab(self)
        self.dashboard_tab = DashboardTab(self)
        self.settings_tab = SettingsTab(self)

        self.tab_widget.addTab(self.dashboard_tab, "🏠 仪表盘")
        self.tab_widget.addTab(self.console_tab, "🖥️ 控制台")
        self.tab_widget.addTab(self.packs_tab, "📦 资源包/行为包")
        self.tab_widget.addTab(self.config_tab, "⚙️ 配置")
        self.tab_widget.addTab(self.world_tab, "🌍 世界管理")
        self.tab_widget.addTab(monitor_tab, "📊 系统资源")
        self.tab_widget.addTab(self.tunnel_tab, "🚇 隧道")
        self.tab_widget.addTab(self.upgrade_tab, "🔄 版本升级")
        self.tab_widget.addTab(self.settings_tab, "⚙️ 设置")
        # 标签页切换动画
        from PyQt5.QtWidgets import QGraphicsOpacityEffect
        self._tab_fx = QGraphicsOpacityEffect(self.tab_widget)
        self._tab_fx.setOpacity(1.0)
        self.tab_widget.setGraphicsEffect(self._tab_fx)
        self._tab_anim = QPropertyAnimation(self._tab_fx, b"opacity")
        self._tab_anim.setDuration(150)
        self.tab_widget.currentChanged.connect(self._animate_tab_switch)

        layout.addWidget(self.tab_widget)

        # 状态栏（实时信息）
        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(8, 2, 8, 2)
        self.status_server = QLabel("⏹ 服务器: 已停止")
        self.status_server.setStyleSheet("font-size:11px; color:#888; padding:0 8px;")
        self.status_players = QLabel("👥 0")
        self.status_players.setStyleSheet("font-size:11px; color:#888; padding:0 8px;")
        self.status_mem = QLabel("💾 --")
        self.status_mem.setStyleSheet("font-size:11px; color:#888; padding:0 8px;")
        self.status_ver = QLabel(f"v{__version__}")
        self.status_ver.setStyleSheet("font-size:10px; color:#555; padding:0 8px;")
        self.status_tunnel = QLabel("🚇 --")
        self.status_tunnel.setStyleSheet("font-size:11px; color:#888; padding:0 8px;")
        status_layout.addWidget(self.status_server)
        status_layout.addWidget(self.status_players)
        status_layout.addWidget(self.status_mem)
        status_layout.addStretch()
        status_layout.addWidget(self.status_tunnel)
        status_layout.addWidget(self.status_ver)
        layout.addLayout(status_layout)
        # 兼容旧代码
        self.status_label = self.status_server
        # 状态栏刷新定时器
        self._status_timer = QTimer()
        self._status_timer.timeout.connect(self._refresh_status_bar)
        self._status_timer.start(3000)

    def create_tray_icon(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.style().standardIcon(QStyle.SP_ComputerIcon))
        tray_menu = QMenu()
        show_action = QAction("显示主窗口", self)
        show_action.triggered.connect(self.show_normal)
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self.quit_app)
        tray_menu.addAction(show_action)
        tray_menu.addAction(quit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

    def _show_startup_toasts(self):
        """启动时自检并提示"""
        import psutil
        server_dir = get_server_dir()
        # 服务器目录
        if os.path.isdir(server_dir):
            toast_success("服务器目录", f"✓ {os.path.basename(server_dir)}")
        else:
            toast_error("服务器目录", f"✗ 不存在: {server_dir}")
        # 服务端程序
        exe = os.path.join(server_dir, self.config.get("server_exe", "bedrock_server.exe"))
        if os.path.exists(exe):
            toast_info("服务端程序", f"✓ {os.path.basename(exe)}")
        else:
            toast_warning("服务端程序", f"✗ 未找到 {os.path.basename(exe)}")
        # 系统资源
        cpu = psutil.cpu_percent()
        mem = psutil.virtual_memory().percent
        toast_info("系统资源", f"CPU {cpu:.0f}% | 内存 {mem:.0f}%")
        # 备份状态
        if os.path.exists(BACKUP_DIR):
            pkgs = sorted([f for f in os.listdir(BACKUP_DIR) if f.endswith(".zip")],
                          key=lambda f: os.path.getmtime(os.path.join(BACKUP_DIR, f)), reverse=True)
            if pkgs:
                toast_info("备份状态", f"最近: {pkgs[0][:40]}")
            else:
                toast_info("备份状态", "暂无备份")
        # 版本信息
        toast_info(f"BDS Manager v{__version__}", "就绪，等待操作")

    def show_normal(self):
        self.showNormal()
        self.activateWindow()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_normal()

    def _animate_tab_switch(self, index):
        """标签页切换 150ms 淡入动画"""
        self._tab_anim.stop()
        self._tab_anim.setStartValue(0.7)
        self._tab_anim.setEndValue(1.0)
        self._tab_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._tab_anim.start()

    def _refresh_status_bar(self):
        """更新底部状态栏实时信息"""
        running = self.is_server_running()
        stats = self.console_tab.get_server_stats()
        # 服务器
        if running:
            self.status_server.setText("🟢 服务器: 在线")
            self.status_server.setStyleSheet("font-size:11px; color:#4CAF50; padding:0 8px;")
        else:
            self.status_server.setText("⏹ 服务器: 已停止")
            self.status_server.setStyleSheet("font-size:11px; color:#888; padding:0 8px;")
        # 玩家
        n = stats.get("player_count", 0)
        self.status_players.setText(f"👥 {n}")
        self.status_players.setStyleSheet(f"font-size:11px; color:{'#66ccff' if n else '#888'}; padding:0 8px;")
        # 内存
        try:
            import psutil
            mem = psutil.virtual_memory().percent
            c = "#4CAF50" if mem < 60 else "#ffaa33" if mem < 80 else "#f44336"
            self.status_mem.setText(f"💾 {mem:.0f}%")
            self.status_mem.setStyleSheet(f"font-size:11px; color:{c}; padding:0 8px;")
        except:
            pass
        # 隧道
        t_running = hasattr(self, 'tunnel_tab') and self.tunnel_tab.is_tunnel_running()
        if t_running:
            self.status_tunnel.setText("🚇 隧道在线")
            self.status_tunnel.setStyleSheet("font-size:11px; color:#4CAF50; padding:0 8px;")
        else:
            self.status_tunnel.setText("🚇 --")
            self.status_tunnel.setStyleSheet("font-size:11px; color:#888; padding:0 8px;")

    def quit_app(self):
        """退出应用：先停止服务器和隧道，再清理资源"""
        if self.is_server_running():
            self.console_tab.stop_server()
            QApplication.processEvents()
            time.sleep(1)  # 给服务器时间优雅退出
        if hasattr(self, 'tunnel_tab'):
            self.tunnel_tab.cleanup()
        if hasattr(self, 'system_monitor'):
            self.system_monitor.stop_monitoring()
        self.backup_timer.stop()
        # 保存窗口大小
        self.config["window_width"] = self.width()
        self.config["window_height"] = self.height()
        self.save_config()
        self.tray_icon.hide()
        QApplication.quit()

    def init_watcher(self):
        paths_to_watch = []
        if os.path.exists(RESOURCE_PACKS_DIR):
            paths_to_watch.append(RESOURCE_PACKS_DIR)
        if os.path.exists(BEHAVIOR_PACKS_DIR):
            paths_to_watch.append(BEHAVIOR_PACKS_DIR)
        if os.path.exists(SERVER_PROPERTIES):
            paths_to_watch.append(SERVER_PROPERTIES)
        if os.path.exists(ALLOWLIST_FILE):
            paths_to_watch.append(ALLOWLIST_FILE)
        if os.path.exists(PERMISSIONS_FILE):
            paths_to_watch.append(PERMISSIONS_FILE)
        # 监控世界包注册文件（激活/注销包时修改）
        level_name = self.get_level_name()
        if level_name:
            world_path = get_world_path(level_name)
            for reg_file in ["world_resource_packs.json", "world_behavior_packs.json"]:
                fp = os.path.join(world_path, reg_file)
                if os.path.exists(fp):
                    paths_to_watch.append(fp)
        # 监控世界目录（新增/删除世界时刷新）
        if os.path.exists(WORLDS_DIR):
            paths_to_watch.append(WORLDS_DIR)
        existing = self.watcher.directories() + self.watcher.files()
        for p in existing:
            if p not in paths_to_watch:
                self.watcher.removePath(p)
        for p in paths_to_watch:
            if p not in existing:
                self.watcher.addPath(p)
        log_info("文件监控已启动，资源包或配置变化将自动刷新界面")

    def on_external_change(self, path=""):
        """文件系统变化回调（防抖：500ms 内多次变化只刷新一次）"""
        if not self._refresh_timer.isActive():
            self._refresh_timer.start(500)

    def refresh_all_tabs(self):
        if hasattr(self, 'packs_tab'):
            self.packs_tab.refresh_lists()
        if hasattr(self, 'config_tab'):
            self.config_tab.load_server_properties()
        if hasattr(self, 'world_tab'):
            self.world_tab.refresh_info()
            self.world_tab.refresh_backup_list()
        if hasattr(self, 'upgrade_tab'):
            self.upgrade_tab.refresh_current_info()
        log_info("界面已自动同步外部更改")

    def _detect_system_theme(self):
        """检测 Windows 深浅色模式"""
        if sys.platform != "win32":
            return "dark"
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "light" if val else "dark"
        except Exception:
            return "dark"

    def apply_theme(self, theme_name):
        if theme_name == "auto":
            theme_name = self._detect_system_theme()
        style = self.theme_manager.get_theme(theme_name)
        self.setStyleSheet(style)
        if MATPLOTLIB_AVAILABLE and hasattr(self, 'system_monitor') and hasattr(self.system_monitor, 'figure'):
            bg_color = '#2b2b2b' if theme_name == 'dark' else '#f5f5f5'
            self.system_monitor.figure.patch.set_facecolor(bg_color)
            self.system_monitor.ax_cpu.set_facecolor(bg_color)
            self.system_monitor.ax_mem.set_facecolor(bg_color)
            text_color = 'white' if theme_name == 'dark' else 'black'
            for ax in [self.system_monitor.ax_cpu, self.system_monitor.ax_mem]:
                ax.tick_params(colors=text_color)
                ax.title.set_color(text_color)
                ax.xaxis.label.set_color(text_color)
                ax.yaxis.label.set_color(text_color)
            self.system_monitor.figure.canvas.draw_idle()

    def on_theme_changed(self, theme_name):
        if theme_name == "custom":
            self.apply_custom_theme()
        else:
            self.apply_theme(theme_name)
        self.config["theme"] = theme_name

    def choose_custom_color(self, color_key):
        current = QColor(self.custom_colors.get(color_key, "#2b2b2b"))
        color = QColorDialog.getColor(current, self, f"选择 {color_key}")
        if color.isValid():
            self.custom_colors[color_key] = color.name()
            if hasattr(self, 'settings_tab') and self.settings_tab and self.settings_tab.color_buttons.get(color_key):
                self.settings_tab.color_buttons[color_key].setStyleSheet(f"background-color: {color.name()}; border: 1px solid #888;")

    def apply_custom_theme(self):
        self.theme_manager.set_custom_colors(self.custom_colors)
        self.apply_theme("custom")
        self.config["theme"] = "custom"

    def apply_monitor_interval(self, interval):
        if hasattr(self, 'system_monitor'):
            self.system_monitor.update_interval(interval)

    def closeEvent(self, event):
        if hasattr(self, 'tunnel_tab'):
            self.tunnel_tab.cleanup()
        if hasattr(self, 'system_monitor'):
            self.system_monitor.stop_monitoring()
        self.backup_timer.stop()
        event.ignore()
        self.hide()
        self.tray_icon.showMessage("提示", "程序已最小化到系统托盘，双击图标可恢复。", QSystemTrayIcon.Information, 2000)

    def resizeEvent(self, event):
        """窗口大小变化时自动保存"""
        super().resizeEvent(event)
        if hasattr(self, 'config'):
            self.config["window_width"] = self.width()
            self.config["window_height"] = self.height()

# ---------- 高分屏适配 ----------
def _load_hidpi_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f).get("hidpi_enabled", True)
        except: pass
    return True

if __name__ == "__main__":
    if _load_hidpi_config():
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 9))
    if not QSystemTrayIcon.isSystemTrayAvailable():
        log_warning("系统托盘不可用，将无法最小化到托盘")
    window = BDSManager()
    window.show()
    sys.exit(app.exec_())
