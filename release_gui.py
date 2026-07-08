#!/usr/bin/env python3
"""BDS Manager 发布工具 — PyQt5 图形界面（内建打包+发布逻辑）"""
import sys
import os
import json
import hashlib
import zipfile
import subprocess
import shutil
import webbrowser
import threading
from pathlib import Path
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QLabel, QGroupBox, QProgressBar, QMessageBox
)
from PyQt5.QtCore import Qt, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QTextCursor

SCRIPT_DIR = Path(__file__).resolve().parent
VERSION_JSON = SCRIPT_DIR / "version.json"
RELEASE_DIR = SCRIPT_DIR / "release"
GH_EXE = shutil.which("gh") or r"C:\Program Files\GitHub CLI\gh.exe"
GITHUB_REPO = "TussalZeus18028/bds_manager"

EXCLUDE_FILES = {"bds_manager_config.json", "bds_version_cache.json",
                 "release.py", "release_gui.py", "run.bat", "README.md"}
EXCLUDE_DIRS = {"logs", "backups", "Server", "Earlier version", "release",
                ".git", "__pycache__", "web_ui", ".workbuddy"}


class BuildWorker(QObject):
    log = pyqtSignal(str, str)    # level, text
    done = pyqtSignal(bool, str)  # ok, msg

    def __init__(self):
        super().__init__()
        self._log = lambda lv, t: self.log.emit(lv, t)

    def run(self):
        self._log("info", "===== 打包构建 =====")
        meta = json.loads(VERSION_JSON.read_text(encoding="utf-8"))
        ver = meta.get("version", "0.0.0.0")
        self._log("info", f"版本: v{ver}")
        RELEASE_DIR.mkdir(exist_ok=True)
        zip_name = f"bds_manager_v{ver}.zip"
        zip_path = RELEASE_DIR / zip_name

        # 打包
        self._log("info", f"打包 → {zip_name}")
        count = 0
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(SCRIPT_DIR):
                dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith(".")]
                for f in files:
                    if f in EXCLUDE_FILES or not f.endswith((".py", ".txt", ".json")):
                        continue
                    zf.write(os.path.join(root, f), os.path.relpath(os.path.join(root, f), SCRIPT_DIR))
                    count += 1
        self._log("ok", f"{count} 个文件已打包")

        # SHA256
        self._log("info", "计算 SHA256...")
        h = hashlib.sha256()
        with open(zip_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        sha = h.hexdigest()
        size = os.path.getsize(zip_path)
        self._log("ok", f"SHA256: {sha}")
        self._log("ok", f"大小: {size:,} bytes ({size/1024:.1f} KB)")

        meta["sha256"] = sha
        meta["file_size"] = size
        meta["download_url"] = f"https://github.com/{GITHUB_REPO}/releases/download/v{ver}/{zip_name}"
        for tgt in [VERSION_JSON, RELEASE_DIR / "version.json"]:
            tgt.write_text(json.dumps(meta, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
        # 生成 Markdown 发布说明，避免直接把 JSON 当 release notes
        notes_md = RELEASE_DIR / "release_notes.md"
        changelog = meta.get("changelog", "")
        notes_md.write_text(f"## v{ver}\n\n{changelog}\n", encoding="utf-8")
        self._log("ok", f"{notes_md.name} 已生成")
        self.done.emit(True, "打包完成")


class PublishWorker(QObject):
    log = pyqtSignal(str, str)
    done = pyqtSignal(bool, str)

    def __init__(self):
        super().__init__()
        self._log = lambda lv, t: self.log.emit(lv, t)

    def _run(self, cmd):
        self._log("info", f"$ {' '.join(cmd)}")
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(SCRIPT_DIR))
        out = (r.stdout or "").strip()
        err = (r.stderr or "").strip()
        if err:
            self._log("err", err)
        return r.returncode, out

    def run(self):
        self._log("info", "===== 发布到 GitHub =====")
        meta = json.loads(VERSION_JSON.read_text(encoding="utf-8"))
        ver = meta["version"]
        self._log("ok", f"版本: v{ver}")

        # 检查 gh
        if not os.path.isfile(GH_EXE):
            self._log("err", f"未找到 gh ({GH_EXE})")
            self.done.emit(False, "gh 未安装")
            return

        # 检查 ZIP
        zip_path = RELEASE_DIR / f"bds_manager_v{ver}.zip"
        if not zip_path.exists():
            self._log("err", f"找不到 {zip_path}")
            self._log("err", "请先打包")
            self.done.emit(False, "ZIP 不存在")
            return

        # 推送
        rc, branch = self._run(["git", "branch", "--show-current"])
        if rc != 0:
            self.done.emit(False, "不在 Git 仓库"); return
        self._log("info", f"分支: {branch}")
        rc, _ = self._run(["git", "push", "origin", branch])
        if rc != 0:
            self._log("err", "推送失败")
            self.done.emit(False, "推送失败"); return
        self._log("ok", "推送成功")

        # gh 登录
        rc, _ = self._run([GH_EXE, "auth", "status"])
        if rc != 0:
            self._log("warn", "gh 未登录，尝试自动登录...")
            rc2, _ = self._run([GH_EXE, "auth", "login", "--git-protocol", "https",
                                "--hostname", "github.com", "--with-token"])
            if rc2 != 0:
                self._log("warn", "登录失败，请手动: gh auth login --web")
                self._log("info", "（仅完成推送，跳过 Release）")
                self.done.emit(True, "推送成功（需手动登录 gh）"); return

        # 创建 Release
        tag = f"v{ver}"
        notes = RELEASE_DIR / "release_notes.md"
        cmd = [GH_EXE, "release", "create", tag, str(zip_path), "--title", tag]
        if notes.exists():
            cmd += ["--notes-file", str(notes)]
        rc, _ = self._run(cmd)
        if rc != 0:
            self._log("err", "Release 创建失败")
            self.done.emit(False, "Release 创建失败"); return
        self._log("ok", f"Release {tag} 创建成功")
        webbrowser.open(f"https://github.com/{GITHUB_REPO}/releases/tag/{tag}")
        self.done.emit(True, "发布完成")


class ReleaseGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BDS Manager — 发布工具")
        self.setMinimumSize(680, 560)
        self.setStyleSheet(self._theme())

        cw = QWidget()
        self.setCentralWidget(cw)
        lay = QVBoxLayout(cw)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(10)

        # 版本信息
        ver_g = QGroupBox("版本信息")
        ver_h = QHBoxLayout()
        self.ver_lbl = QLabel("版本: --")
        self.ver_lbl.setStyleSheet("font-size:15px; font-weight:bold; color:#4fc3f7;")
        ver_h.addWidget(self.ver_lbl)
        ver_h.addStretch()
        self.sts_lbl = QLabel("就绪")
        self.sts_lbl.setStyleSheet("color:#888;")
        ver_h.addWidget(self.sts_lbl)
        ver_g.setLayout(ver_h)
        lay.addWidget(ver_g)

        # 按钮
        btn_g = QGroupBox("操作")
        btn_h = QHBoxLayout()
        btn_h.setSpacing(10)
        self.btn_b = self._btn("📦 打包", "#ff9800")
        self.btn_p = self._btn("🚀 发布", "#4caf50")
        self.btn_a = self._btn("⚡ 一键", "#2196f3")
        self.btn_b.clicked.connect(lambda: self._start("build"))
        self.btn_p.clicked.connect(lambda: self._start("publish"))
        self.btn_a.clicked.connect(lambda: self._start("all"))
        btn_h.addWidget(self.btn_b)
        btn_h.addWidget(self.btn_p)
        btn_h.addWidget(self.btn_a)
        btn_g.setLayout(btn_h)
        lay.addWidget(btn_g)

        # 进度条
        self.pb = QProgressBar()
        self.pb.setRange(0, 0); self.pb.setVisible(False)
        self.pb.setFixedHeight(6); self.pb.setTextVisible(False)
        lay.addWidget(self.pb)

        # 输出
        out_g = QGroupBox("输出日志")
        out_l = QVBoxLayout()
        self.out = QTextEdit()
        self.out.setReadOnly(True)
        self.out.setFont(QFont("Consolas", 10))
        self.out.setStyleSheet(
            "QTextEdit { background:#121212; color:#e0e0e0; border:1px solid #333;"
            "border-radius:4px; padding:8px; }")
        out_l.addWidget(self.out)
        out_g.setLayout(out_l)
        lay.addWidget(out_g)

        self._load_ver()

    def _theme(self):
        return """
        QMainWindow{background:#1e1e1e} QGroupBox{color:#aaa;border:1px solid #333;
        border-radius:6px;margin-top:12px;padding-top:14px;font-weight:bold}
        QGroupBox::title{subcontrol-origin:margin;left:12px;padding:0 6px}
        QProgressBar{background:#333;border:none;border-radius:3px}
        QProgressBar::chunk{background:#4fc3f7;border-radius:3px}
        """

    def _btn(self, text, color):
        b = QPushButton(text)
        b.setStyleSheet(f"QPushButton{{background:{color};color:#fff;border:none;"
                        f"border-radius:6px;padding:10px 20px;font-size:13px;font-weight:bold}}"
                        f"QPushButton:hover{{opacity:.85}}"
                        f"QPushButton:disabled{{background:#444;color:#888}}")
        b.setCursor(Qt.PointingHandCursor)
        return b

    def _load_ver(self):
        try:
            v = json.loads(VERSION_JSON.read_text(encoding="utf-8"))["version"]
            self.ver_lbl.setText(f"版本: v{v}")
        except Exception:
            self.ver_lbl.setText("版本: 读取失败")

    def _start(self, mode: str):
        labels = {"build": "打包", "publish": "发布", "all": "一键发布"}
        if mode in ("publish", "all"):
            reply = QMessageBox.question(
                self, f"确认{labels[mode]}",
                f"即将执行: {labels[mode]}，确认？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No:
                return

        for b in [self.btn_b, self.btn_p, self.btn_a]:
            b.setEnabled(False)
        self.pb.setVisible(True)
        self.out.clear()
        self.sts_lbl.setText("执行中...")
        self.sts_lbl.setStyleSheet("color:#4fc3f7;")
        self.out.append(f"<span style='color:#4fc3f7;'>=== 开始{labels[mode]} ===</span>")

        if mode == "build":
            self._run_build()
        elif mode == "publish":
            self._run_publish()
        else:
            self._run_all()

    def _run_build(self):
        self._w = BuildWorker()
        self._w.log.connect(self._on_log)
        self._w.done.connect(self._on_build_done)
        threading.Thread(target=self._w.run, daemon=True).start()

    def _run_publish(self):
        self._w = PublishWorker()
        self._w.log.connect(self._on_log)
        self._w.done.connect(self._on_done)
        threading.Thread(target=self._w.run, daemon=True).start()

    def _run_all(self):
        self._mode = "all"
        self._w = BuildWorker()
        self._w.log.connect(self._on_log)
        self._w.done.connect(self._on_build_done)
        threading.Thread(target=self._w.run, daemon=True).start()

    def _on_build_done(self, ok, msg):
        if self._mode == "all" and ok:
            self._run_publish()
        else:
            self._on_done(ok, msg)
        self._mode = ""

    def _on_log(self, level, text):
        colors = {"err": "#f44336", "ok": "#4caf50", "warn": "#ff9800",
                  "info": "#4fc3f7"}
        c = colors.get(level, "#aaa")
        # 过滤无意义的空行
        for line in text.splitlines():
            l = line.strip()
            if l:
                self.out.append(f"<span style='color:{c};'>  {l}</span>")
        cursor = self.out.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.out.setTextCursor(cursor)

    def _on_done(self, ok, msg):
        for b in [self.btn_b, self.btn_p, self.btn_a]:
            b.setEnabled(True)
        self.pb.setVisible(False)
        if ok:
            self.sts_lbl.setText("完成"); self.sts_lbl.setStyleSheet("color:#4caf50;")
            self.out.append("<span style='color:#4caf50;'>=== 完成 ===</span>")
        else:
            self.sts_lbl.setText("失败"); self.sts_lbl.setStyleSheet("color:#f44336;")
            self.out.append("<span style='color:#f44336;'>=== 失败 ===</span>")
        self._load_ver()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    gui = ReleaseGUI()
    gui.show()
    sys.exit(app.exec_())
