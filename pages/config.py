# -*- coding: utf-8 -*-
"""
配置页面 —— server.properties 可视化编辑、白名单/权限管理。

v3.1 改进：
- 每个属性右侧加说明 CaptionLabel
- 端口范围校验（IPv4/IPv6）
- 保存时显示 diff（变更项红色高亮）
- "保存并应用"按钮：写完配置提示重启服务器
- 4 个预设方案按钮（生存/创造/小游戏/PvP）
- diff 弹窗预览
"""

import os
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QFileDialog, QMessageBox, QLabel,
)
from qfluentwidgets import (
    CardWidget, SubtitleLabel, StrongBodyLabel, BodyLabel, CaptionLabel,
    PrimaryPushButton, PushButton, LineEdit, ComboBox,
    FluentIcon, ToggleButton, InfoBar, MessageBox,
)

from shared.config import get_context
from shared.toast import toast_success, toast_error, toast_info, toast_warning
from components.widgets import NoScrollSpinBox  # v3.02.01: 滚轮防护

# 默认 server.properties 模板
_DEFAULT_PROPERTIES = """#server.properties
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
from pages.dashboard import wrap_scrollable

# --- server.properties 完整属性定义 ---
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
    "server-port": "IPv4 端口 (UDP, 1024-65535)",
    "server-portv6": "IPv6 端口 (UDP, 1024-65535)",
    "view-distance": "视野距离（区块数，5-32）",
    "tick-distance": "tick 加载距离（区块数，4-12）",
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

# 数值范围限制（int 类型）
_INT_RANGES = {
    "max-players": (1, 40),
    "server-port": (1024, 65535),
    "server-portv6": (1024, 65535),
    "view-distance": (5, 32),
    "tick-distance": (4, 12),
    "player-idle-timeout": (0, 120),
    "max-threads": (1, 32),
    "compression-threshold": (0, 65535),
}

# 预设方案：key -> (类型, 值)
_PRESETS = {
    "生存": {
        "gamemode": ("combo", "survival"),
        "difficulty": ("combo", "normal"),
        "force-gamemode": ("bool", True),
        "allow-cheats": ("bool", False),
        "max-players": ("int", 10),
        "pvp": "real",
    },
    "创造": {
        "gamemode": ("combo", "creative"),
        "difficulty": ("combo", "peaceful"),
        "force-gamemode": ("bool", True),
        "allow-cheats": ("bool", True),
        "max-players": ("int", 20),
    },
    "小游戏": {
        "gamemode": ("combo", "adventure"),
        "difficulty": ("combo", "easy"),
        "force-gamemode": ("bool", True),
        "allow-cheats": ("bool", True),
        "max-players": ("int", 16),
    },
    "PvP": {
        "gamemode": ("combo", "survival"),
        "difficulty": ("combo", "hard"),
        "force-gamemode": ("bool", False),
        "allow-cheats": ("bool", False),
        "max-players": ("int", 30),
    },
}


class ConfigPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        inner, layout = wrap_scrollable(self, spacing=12)

        # ── 预设方案 ──
        preset_card = CardWidget(inner)
        pc = QVBoxLayout(preset_card)
        pc.setContentsMargins(16, 12, 16, 16); pc.setSpacing(8)
        pc.addWidget(SubtitleLabel("预设方案", preset_card))
        pc.addWidget(CaptionLabel("点击预设按钮可一键应用以下配置（不会自动保存）", preset_card))
        preset_row = QHBoxLayout()
        for name in _PRESETS.keys():
            btn = PushButton(name, preset_card)
            btn.clicked.connect(lambda checked, n=name: self._apply_preset(n))
            preset_row.addWidget(btn)
        preset_row.addStretch()
        pc.addLayout(preset_row)
        layout.addWidget(preset_card)

        # ── server.properties ──
        prop_card = CardWidget(inner)
        prop_layout = QVBoxLayout(prop_card)
        prop_layout.setContentsMargins(16, 12, 16, 16)
        prop_layout.setSpacing(6)
        prop_layout.addWidget(SubtitleLabel("server.properties（28 项）", prop_card))

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
                w = NoScrollSpinBox(prop_card)
                lo, hi = _INT_RANGES.get(key, (0, 65535))
                w.setRange(lo, hi)
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

            # 说明
            hint_lbl = CaptionLabel(_HINTS.get(key, ""), prop_card)
            hint_lbl.setStyleSheet("color: #888; font-size: 11px;")
            hint_lbl.setMaximumWidth(280)
            hint_lbl.setWordWrap(True)
            row.addWidget(hint_lbl)

            prop_layout.addLayout(row)

        # 错误提示
        self._error_label = CaptionLabel("", prop_card)
        self._error_label.setStyleSheet("color: #ff5555; font-weight: bold;")
        prop_layout.addWidget(self._error_label)

        # 按钮行
        save_row = QHBoxLayout()
        self._diff_btn = PushButton("查看变更 (Diff)", prop_card, FluentIcon.DOCUMENT)
        self._diff_btn.clicked.connect(self._show_diff)
        save_row.addWidget(self._diff_btn)
        save_row.addStretch()
        save_btn = PrimaryPushButton("保存", prop_card, FluentIcon.SAVE)
        save_btn.clicked.connect(lambda: self._save(apply=False))
        apply_btn = PrimaryPushButton("保存并应用", prop_card, FluentIcon.SEND)
        apply_btn.clicked.connect(lambda: self._save(apply=True))
        save_row.addWidget(save_btn)
        save_row.addWidget(apply_btn)
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

        btn_allowlist.clicked.connect(lambda: self._open_file("allowlist.json"))
        btn_perms.clicked.connect(lambda: self._open_file("permissions.json"))
        btn_packet.clicked.connect(lambda: self._open_file("packetlimitconfig.json"))
        btn_port.clicked.connect(self._check_ports)

        layout.addWidget(mgmt_card)
        layout.addStretch()

        self._load_properties()

    # ---------- 预设 ----------
    def _apply_preset(self, name: str):
        if name not in _PRESETS:
            return
        preset = _PRESETS[name]
        for key, value in preset.items():
            if key == "pvp":
                continue
            if key not in self._editors:
                continue
            typ, w = self._editors[key]
            typ2, val = value
            if typ != typ2:
                continue
            if typ == "int":
                w.setValue(val)
            elif typ == "bool":
                w.setChecked(val)
                w.setText("启用" if val else "禁用")
            elif typ == "combo":
                idx = w.findText(val)
                if idx >= 0:
                    w.setCurrentIndex(idx)
        toast_info("已应用预设", f"方案: {name}，请检查后保存", self.window())

    # ---------- 加载 ----------
    def _load_properties(self):
        ctx = get_context()
        fp = ctx.server_properties
        if not os.path.exists(fp):
            reply = QMessageBox.question(
                self, "配置文件不存在",
                f"server.properties 不存在：\n{fp}\n\n是否创建默认配置文件？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
            )
            if reply == QMessageBox.Yes:
                self._create_default_properties()
                self._load_properties()
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

    def _create_default_properties(self):
        ctx = get_context()
        fp = ctx.server_properties
        try:
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            with open(fp, "w", encoding="utf-8") as f:
                f.write(_DEFAULT_PROPERTIES)
            toast_success("配置文件已创建", "已生成默认 server.properties", self.window())
        except Exception as e:
            toast_error("创建失败", str(e), self.window())

    # ---------- 校验 ----------
    def _validate(self) -> tuple[bool, str]:
        """返回 (是否通过, 错误信息)。"""
        for key, (typ, w) in self._editors.items():
            if typ == "int":
                lo, hi = _INT_RANGES.get(key, (0, 65535))
                val = w.value()
                if val < lo or val > hi:
                    return False, f"{key} = {val} 超出范围 [{lo}, {hi}]"
        # 端口冲突
        v4 = self._editors["server-port"][1].value()
        v6 = self._editors["server-portv6"][1].value()
        if v4 == v6:
            return False, f"IPv4 端口 {v4} 与 IPv6 端口 {v6} 冲突"
        return True, ""

    def _get_values(self) -> dict:
        """返回当前所有 key -> 字符串值。"""
        out = {}
        for key, (typ, w) in self._editors.items():
            if typ == "text":
                out[key] = w.text()
            elif typ == "int":
                out[key] = str(w.value())
            elif typ == "bool":
                out[key] = "true" if w.isChecked() else "false"
            elif typ == "combo":
                out[key] = w.currentText()
        return out

    def _read_existing(self) -> dict:
        """读取磁盘上当前 server.properties 的所有 key -> 值。"""
        ctx = get_context()
        out = {}
        if not os.path.exists(ctx.server_properties):
            return out
        try:
            with open(ctx.server_properties, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    out[k] = v
        except Exception:
            pass
        return out

    # ---------- Diff ----------
    def _show_diff(self):
        new_vals = self._get_values()
        old_vals = self._read_existing()
        diffs = []
        for k, v in new_vals.items():
            if old_vals.get(k) != v:
                diffs.append((k, old_vals.get(k, "(无)"), v))
        if not diffs:
            toast_info("无变更", "当前设置与磁盘一致", self.window())
            return
        text = "\n".join([f"  {k}: {old}  →  <b>{new}</b>" for k, old, new in diffs])
        # 用 MessageBox 显示
        mb = MessageBox("配置变更预览", f"以下 {len(diffs)} 项将被修改：\n\n{text}",
                        self.window())
        mb.exec()

    # ---------- 保存 ----------
    def _save(self, apply: bool = False):
        ok, err = self._validate()
        if not ok:
            self._error_label.setText(f"❌ {err}")
            toast_error("配置校验失败", err, self.window())
            return
        self._error_label.setText("")

        ctx = get_context()
        values = self._get_values()
        # 按 _KNOWN_PROPS 顺序写
        lines = []
        for key in _KNOWN_PROPS:
            if key in values:
                lines.append(f"{key}={values[key]}")
        try:
            with open(ctx.server_properties, "w", encoding="utf-8") as f:
                f.write("# server.properties\n" + "\n".join(lines) + "\n")
        except Exception as e:
            toast_error("保存失败", str(e), self.window())
            return

        if apply:
            # 提示用户重启
            win = self.window()
            if win and getattr(win, "is_server_running", False):
                mb = MessageBox(
                    "已保存",
                    "配置已写入 server.properties。\n\n服务器正在运行中，需要重启才能生效。\n\n是否立即重启？",
                    self.window(),
                )
                if mb.exec():
                    win.stop_server()
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(3000, win.start_server)
            else:
                toast_success("保存成功", "新配置将在下次启动时生效", self.window())
        else:
            toast_success("保存成功", "server.properties 已更新，重启服务器后生效", self.window())

    def _open_file(self, filename: str):
        ctx = get_context()
        fp = os.path.join(ctx.server_dir, filename)
        if not os.path.exists(fp):
            toast_error("文件不存在", fp, self.window())
            return
        try:
            os.startfile(fp)
        except AttributeError:
            import subprocess, sys
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.Popen([opener, fp])

    def _check_ports(self):
        import socket
        ctx = get_context()
        ipv4 = self._editors["server-port"][1].value()
        ipv6 = self._editors["server-portv6"][1].value()

        msgs = []
        for label, port in [("IPv4", ipv4), ("IPv6", ipv6)]:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.bind(("0.0.0.0", port))
                sock.close()
                msgs.append(f"✅ {label} {port}: 可用")
            except OSError:
                free = None
                for offset in range(1, 200):
                    p = port + offset
                    try:
                        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                        s.bind(("0.0.0.0", p))
                        s.close()
                        free = p
                        break
                    except OSError:
                        pass
                if free:
                    msgs.append(f"❌ {label} {port}: 已占用 → 推荐 {free}")
                else:
                    msgs.append(f"❌ {label} {port}: 已占用（附近无空闲端口）")

        mb = MessageBox("端口检测", "\n".join(msgs), self.window())
        mb.exec()
