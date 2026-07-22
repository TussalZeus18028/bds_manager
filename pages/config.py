# -*- coding: utf-8 -*-
"""
配置页面 —— server.properties 可视化编辑、白名单/权限管理。
"""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QFileDialog,
)
from qfluentwidgets import (
    CardWidget, SubtitleLabel, StrongBodyLabel, BodyLabel,
    PrimaryPushButton, PushButton, LineEdit, ComboBox,
    FluentIcon, ToggleButton, SpinBox, InfoBar,
)

from shared.config import get_context
from shared.toast import toast_success, toast_error
from pages.dashboard import wrap_scrollable

# --- server.properties 完整属性定义（来自旧版 ConfigTab）---
_KNOWN_PROPS = {
    "server-name":    ("text",  "Dedicated Server"),
    "gamemode":       ("combo", ["survival", "creative", "adventure"]),
    "force-gamemode": ("bool",  False),
    "difficulty":     ("combo", ["peaceful", "easy", "normal", "hard"]),
    "allow-cheats":   ("bool",  False),
    "max-players":    ("int",   10),
    "online-mode":    ("bool",  True),
    "allow-list":     ("bool",  False),
    "server-port":    ("int",   19132),
    "server-portv6":  ("int",   19133),
    "view-distance":  ("int",   32),
    "tick-distance":  ("int",   4),
    "player-idle-timeout": ("int", 30),
    "max-threads":    ("int",   8),
    "level-name":     ("text",  "Bedrock level"),
    "level-seed":     ("text",  ""),
    "default-player-permission-level": ("combo", ["visitor", "member", "operator"]),
    "texturepack-required": ("bool", False),
    "content-log-file-enabled": ("bool", False),
    "compression-threshold": ("int", 1),
    "compression-algorithm": ("combo", ["zlib", "snappy"]),
    "op-permission-level": ("combo", ["1", "2", "3", "4"]),
    "server-authoritative-movement": ("combo", ["client-auth", "server-auth", "server-auth-with-rewind"]),
    "server-authoritative-block-breaking": ("bool", False),
    "chat-restriction": ("combo", ["None", "Disabled", "Muted", "Limited"]),
    "disable-player-interaction": ("bool", False),
    "emit-server-telemetry": ("bool", True),
    "correct-player-movement": ("bool", False),
}

_HINTS = {
    "server-name": "服务器名称，显示在外部服务器列表",
    "gamemode": "默认游戏模式",
    "force-gamemode": "强制玩家使用默认游戏模式",
    "difficulty": "游戏难度",
    "allow-cheats": "是否允许使用命令（开启后可使用 /op 等）",
    "max-players": "最大玩家数量 (1-40)",
    "online-mode": "正版验证（false 为离线模式）",
    "allow-list": "是否启用白名单",
    "server-port": "IPv4 端口 (UDP)",
    "server-portv6": "IPv6 端口 (UDP)",
    "view-distance": "视野距离（区块数）",
    "tick-distance": "tick 加载距离（区块数）",
    "player-idle-timeout": "玩家空闲踢出时间（分钟，0为禁用）",
    "max-threads": "最大线程数（建议不超过CPU核心数）",
    "level-name": "世界文件夹名称（位于 worlds/ 下）",
    "level-seed": "世界种子（留空则随机生成）",
    "default-player-permission-level": "新玩家默认权限等级",
    "texturepack-required": "是否强制玩家使用服务器资源包",
    "compression-threshold": "压缩阈值 (0-65535)",
    "compression-algorithm": "压缩算法（zlib 兼容性更好）",
    "op-permission-level": "OP 权限等级 (1-4)",
    "server-authoritative-movement": "移动权威模式",
    "server-authoritative-block-breaking": "服务端权威方块破坏",
    "chat-restriction": "聊天限制级别",
    "correct-player-movement": "服务端纠正玩家移动",
}


class ConfigPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        inner, layout = wrap_scrollable(self, spacing=12)

        # ── server.properties ──
        prop_card = CardWidget(inner)
        prop_layout = QVBoxLayout(prop_card)
        prop_layout.setContentsMargins(16, 12, 16, 16)
        prop_layout.setSpacing(6)
        prop_layout.addWidget(SubtitleLabel("server.properties", prop_card))

        self._editors = {}
        for key, (typ, default) in _KNOWN_PROPS.items():
            row = QHBoxLayout()
            row.setSpacing(8)
            lbl = BodyLabel(key, prop_card)
            lbl.setMinimumWidth(140)
            lbl.setMaximumWidth(200)
            lbl.setWordWrap(True)
            lbl.setToolTip(_HINTS.get(key, ""))
            row.addWidget(lbl)

            if typ == "text":
                w = LineEdit(prop_card)
                w.setText(str(default))
            elif typ == "int":
                w = SpinBox(prop_card)
                w.setRange(0, 65535)
                w.setValue(int(default))
            elif typ == "bool":
                w = ToggleButton("启用" if default else "禁用", prop_card)
                w.setChecked(bool(default))
                w.toggled.connect(lambda chk, btn=w: btn.setText("启用" if chk else "禁用"))
            elif typ == "combo":
                w = ComboBox(prop_card)
                w.addItems(default)
            self._editors[key] = (typ, w)
            row.addWidget(w, 1)
            prop_layout.addLayout(row)

        save_row = QHBoxLayout()
        save_row.addStretch()
        save_btn = PrimaryPushButton("保存配置", prop_card, FluentIcon.SAVE)
        save_btn.clicked.connect(self._save)
        save_row.addWidget(save_btn)
        prop_layout.addLayout(save_row)
        layout.addWidget(prop_card)

        # ── 配置管理 ──
        mgmt_card = CardWidget(inner)
        mgmt_layout = QVBoxLayout(mgmt_card)
        mgmt_layout.setContentsMargins(16, 12, 16, 16)
        mgmt_layout.setSpacing(8)
        mgmt_layout.addWidget(SubtitleLabel("配置文件管理", mgmt_card))

        row1 = QHBoxLayout()
        btn_allowlist = PushButton("编辑白名单", mgmt_card, FluentIcon.PEOPLE)
        btn_perms = PushButton("编辑权限", mgmt_card, FluentIcon.EDIT)
        btn_packet = PushButton("包限制", mgmt_card, FluentIcon.FOLDER)
        btn_port = PushButton("端口检测", mgmt_card, FluentIcon.WIFI)
        row1.addWidget(btn_allowlist)
        row1.addWidget(btn_perms)
        row1.addWidget(btn_packet)
        row1.addWidget(btn_port)
        row1.addStretch()
        mgmt_layout.addLayout(row1)

        # 打开文件
        btn_allowlist.clicked.connect(lambda: self._open_file("allowlist.json"))
        btn_perms.clicked.connect(lambda: self._open_file("permissions.json"))
        btn_packet.clicked.connect(lambda: self._open_file("packetlimitconfig.json"))
        btn_port.clicked.connect(self._check_ports)

        layout.addWidget(mgmt_card)
        layout.addStretch()

        self._load_properties()

    def _load_properties(self):
        ctx = get_context()
        fp = ctx.server_properties
        if not os.path.exists(fp):
            return
        try:
            with open(fp, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    if key in self._editors:
                        typ, w = self._editors[key]
                        if typ == "text":
                            w.setText(value)
                        elif typ == "int":
                            try: w.setValue(int(value))
                            except: pass
                        elif typ == "bool":
                            val = value.lower() == "true"
                            w.setChecked(val)
                            w.setText("启用" if val else "禁用")
                        elif typ == "combo":
                            idx = w.findText(value)
                            if idx >= 0: w.setCurrentIndex(idx)
        except Exception as e:
            toast_error("加载失败", str(e), self.window())

    def _save(self):
        ctx = get_context()
        lines = []
        for key, (typ, w) in self._editors.items():
            if typ == "text":
                val = w.text()
            elif typ == "int":
                val = str(w.value())
            elif typ == "bool":
                val = "true" if w.isChecked() else "false"
            elif typ == "combo":
                val = w.currentText()
            lines.append(f"{key}={val}")
        try:
            with open(ctx.server_properties, "w", encoding="utf-8") as f:
                f.write("# server.properties\n" + "\n".join(lines) + "\n")
            toast_success("保存成功", "server.properties 已更新", self.window())
        except Exception as e:
            toast_error("保存失败", str(e), self.window())

    def _open_file(self, filename: str):
        ctx = get_context()
        fp = os.path.join(ctx.server_dir, filename)
        if not os.path.exists(fp):
            toast_error("文件不存在", fp, self.window())
            return
        os.startfile(fp)

    def _check_ports(self):
        """检测 UDP 端口占用并推荐可用端口。"""
        import socket
        ctx = get_context()
        # 读取当前端口
        ipv4, ipv6 = 19132, 19133
        if os.path.exists(ctx.server_properties):
            try:
                with open(ctx.server_properties, encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("server-port="):
                            ipv4 = int(line.split("=")[1].strip())
                        elif line.startswith("server-portv6="):
                            ipv6 = int(line.split("=")[1].strip())
            except Exception:
                pass

        from shared.toast import toast_warning, toast_info
        msgs = []
        for label, port in [("IPv4", ipv4), ("IPv6", ipv6)]:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.bind(("0.0.0.0", port))
                sock.close()
                msgs.append(f"{label} {port}: 可用")
            except OSError:
                # 找空闲端口
                free = None
                for offset in range(100):
                    p = port + offset
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                        s.bind(("0.0.0.0", p))
                        s.close()
                        free = p
                        break
                    except OSError:
                        pass
                msgs.append(f"{label} {port}: 已占用 → 推荐 {free}" if free else f"{label} {port}: 已占用")

        toast_info("端口检测", "\n".join(msgs), self.window(), duration=6000)
