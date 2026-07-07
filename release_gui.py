#!/usr/bin/env python3
"""BDS Manager 发布工具 — PyQt5 图形界面"""
import sys
import os
import json
import subprocess
import threading
from pathlib import Path
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QLabel, QGroupBox, QProgressBar, QMessageBox
)
from PyQt5.QtCore import Qt, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QTextCursor, QColor

SCRIPT_DIR = Path(__file__).resolve().parent
RELEASE_PY = SCRIPT_DIR / "release.py"
VERSION_JSON = SCRIPT_DIR / "version.json"
PYTHON = sys.executable


class ReleaseWorker(QObject):
    """后台执行 release.py 子命令（subprocess 直接读取输出）"""
    output = pyqtSignal(str)
    finished = pyqtSignal(int)

    def __init__(self, cmd: str):
        super().__init__()
        self.cmd = cmd

    def run(self):
        import subprocess
        proc = subprocess.Popen(
            [PYTHON, str(RELEASE_PY), self.cmd],
            cwd=str(SCRIPT_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in proc.stdout:
            if line:
                self.output.emit(line)
        proc.wait()
        self.finished.emit(proc.returncode)


class ReleaseGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BDS Manager — 发布工具")
        self.setMinimumSize(640, 520)
        self.setStyleSheet(self._theme())

        cw = QWidget()
        self.setCentralWidget(cw)
        lay = QVBoxLayout(cw)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(10)

        # --- 版本信息 ---
        ver_group = QGroupBox("版本信息")
        ver_h = QHBoxLayout()
        self.ver_label = QLabel("版本: --")
        self.ver_label.setStyleSheet("font-size:15px; font-weight:bold; color:#4fc3f7;")
        ver_h.addWidget(self.ver_label)
        ver_h.addStretch()
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color:#888;")
        ver_h.addWidget(self.status_label)
        ver_group.setLayout(ver_h)
        lay.addWidget(ver_group)

        # --- 按钮 ---
        btn_group = QGroupBox("操作")
        btn_h = QHBoxLayout()
        btn_h.setSpacing(10)

        self.btn_build = self._btn("📦 打包 (Build)", "#ff9800")
        self.btn_build.clicked.connect(lambda: self._run("build"))
        btn_h.addWidget(self.btn_build)

        self.btn_publish = self._btn("🚀 发布 (Publish)", "#4caf50")
        self.btn_publish.clicked.connect(lambda: self._run("publish"))
        btn_h.addWidget(self.btn_publish)

        self.btn_all = self._btn("⚡ 一键发布 (All)", "#2196f3")
        self.btn_all.clicked.connect(lambda: self._run("all"))
        btn_h.addWidget(self.btn_all)

        btn_group.setLayout(btn_h)
        lay.addWidget(btn_group)

        # --- 进度 ---
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.setTextVisible(False)
        lay.addWidget(self.progress)

        # --- 输出 ---
        out_group = QGroupBox("输出日志")
        out_lay = QVBoxLayout()
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(QFont("Consolas", 10))
        self.output.setStyleSheet(
            "QTextEdit { background:#121212; color:#e0e0e0; border:1px solid #333;"
            "border-radius:4px; padding:8px; }"
        )
        out_lay.addWidget(self.output)
        out_group.setLayout(out_lay)
        lay.addWidget(out_group)

        self._load_version()
        self._thread = None
        self._worker = None

    def _theme(self):
        return """
        QMainWindow { background:#1e1e1e; }
        QGroupBox { color:#aaa; border:1px solid #333; border-radius:6px;
                    margin-top:12px; padding-top:14px; font-weight:bold; }
        QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 6px; }
        QProgressBar { background:#333; border:none; border-radius:3px; }
        QProgressBar::chunk { background:#4fc3f7; border-radius:3px; }
        """

    def _btn(self, text, color):
        b = QPushButton(text)
        b.setStyleSheet(
            f"QPushButton {{ background:{color}; color:#fff; border:none; "
            f"border-radius:6px; padding:10px 20px; font-size:13px; font-weight:bold; }}"
            f"QPushButton:hover {{ opacity:0.85; }}"
            f"QPushButton:disabled {{ background:#444; color:#888; }}"
        )
        b.setCursor(Qt.PointingHandCursor)
        return b

    def _load_version(self):
        try:
            with open(VERSION_JSON, encoding="utf-8") as f:
                ver = json.load(f).get("version", "?")
            self.ver_label.setText(f"版本: v{ver}")
        except Exception:
            self.ver_label.setText("版本: 读取失败")

    def _run(self, cmd: str):
        label = {"build": "打包", "publish": "发布", "all": "一键发布"}[cmd]
        if cmd == "publish":
            reply = QMessageBox.question(
                self, "确认发布",
                f"即将推送代码 + 创建 GitHub Release，确认？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply != QMessageBox.No:
                self._start_task(cmd)
        elif cmd == "all":
            reply = QMessageBox.question(
                self, "确认一键发布",
                "将执行: 打包 → 推送 → 创建 Release，确认？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply != QMessageBox.No:
                self._start_task(cmd)
        else:
            self._start_task(cmd)

    def _start_task(self, cmd: str):
        self._set_buttons(False)
        self.progress.setVisible(True)
        self.output.clear()
        self.status_label.setText("执行中...")
        self.status_label.setStyleSheet("color:#4fc3f7;")

        label = {"build": "打包", "publish": "发布", "all": "一键"}[cmd]
        self.output.append(f"<span style='color:#4fc3f7;'>=== 开始{label} ===</span>")

        self._worker = ReleaseWorker(cmd)
        self._worker.output.connect(self._on_output)
        self._worker.finished.connect(self._on_finished)
        self._thread = threading.Thread(target=self._worker.run, daemon=True)
        self._thread.start()

    def _on_output(self, text):
        # 去掉 ANSI 颜色码再显示
        import re
        clean = re.sub(r'\033\[[0-9;]*m', '', text)
        for line in clean.splitlines():
            l = line.strip()
            if not l:
                continue
            if '[ERR' in l or 'ERR ' in l or '失败' in l:
                color = '#f44336'
            elif '[ OK' in l or 'OK ' in l or '成功' in l or 'DONE' in l:
                color = '#4caf50'
            elif '[WARN' in l:
                color = '#ff9800'
            else:
                color = '#aaa'
            self.output.append(f"<span style='color:{color};'>{l}</span>")
        # 滚动到底
        cursor = self.output.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.output.setTextCursor(cursor)

    def _on_finished(self, exit_code):
        self._set_buttons(True)
        self.progress.setVisible(False)
        if exit_code == 0:
            self.status_label.setText("完成")
            self.status_label.setStyleSheet("color:#4caf50;")
            self.output.append("<span style='color:#4caf50;'>=== 完成 ===</span>")
        else:
            self.status_label.setText("失败")
            self.status_label.setStyleSheet("color:#f44336;")
            self.output.append("<span style='color:#f44336;'>=== 失败 ===</span>")
        self._load_version()

    def _set_buttons(self, enabled: bool):
        for b in [self.btn_build, self.btn_publish, self.btn_all]:
            b.setEnabled(enabled)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    gui = ReleaseGUI()
    gui.show()
    sys.exit(app.exec_())
