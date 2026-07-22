# -*- coding: utf-8 -*-
"""
升级 / 安装页面 —— BDS 版本管理（对齐旧 PyQt5 版完整逻辑）。
"""

import os, re, time, json, shutil, tempfile, random, socket, ssl, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QPlainTextEdit,
)
from PySide6.QtGui import QTextCursor
from qfluentwidgets import (
    CardWidget, SubtitleLabel, StrongBodyLabel, BodyLabel, CaptionLabel,
    PrimaryPushButton, PushButton, LineEdit, FluentIcon,
    ProgressBar, SpinBox,
)

from shared.config import config_mgr, get_context
from shared.toast import toast_success, toast_error, toast_info
from pages.dashboard import wrap_scrollable

import requests

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 常量（对齐旧版）──
VERSION_LIST_URL = "https://raw.githubusercontent.com/TussalZeus18028/bds_version_list/main/bds_versions.json"
_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
]


# ── GitHub 版本列表抓取 ──
def _scrape_github_versions() -> list | None:
    """从 BDS 版本列表仓库获取版本数据。"""
    try:
        req = urllib.request.Request(VERSION_LIST_URL, headers={
            "User-Agent": "BDS-Manager/3.0",
            "Accept": "application/vnd.github.v3+json",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        results = []
        for entry in data.get("versions", []):
            ver = entry.get("version", "")
            branch = entry.get("branch", "stable")
            url = entry.get("url", "")
            if ver and url:
                results.append((ver, branch, url))
        return results if results else None
    except Exception:
        return None


# ── GitHub 抓取 Worker ──
class GithubFetcher(QThread):
    result = Signal(bool, list)

    def run(self):
        r = _scrape_github_versions()
        self.result.emit(r is not None, r if r else [])


# ── HEAD 扫描 Worker（对齐旧 _BrowseWorker）──
class HeadScanWorker(QThread):
    progress = Signal(str, int)
    found = Signal(str, str, str)  # ver, branch, url
    finished = Signal()

    def __init__(self, base_version: str, patch_range=40, build_range=30, append_mode=False, parent=None):
        super().__init__(parent)
        self._base = base_version
        self._patch_range = patch_range
        self._build_range = build_range
        self._append_mode = append_mode
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        parts = [int(x) for x in self._base.split(".")]
        while len(parts) < 4:
            parts.append(0)

        if self._append_mode:
            stable = [(f"{parts[0]}.{parts[1]}.{p}.{b}",
                       f"https://www.minecraft.net/bedrockdedicatedserver/bin-win/bedrock-server-{parts[0]}.{parts[1]}.{p}.{b}.zip",
                       "stable")
                      for p in range(0, self._patch_range) for b in range(0, self._build_range)]
            preview = [(f"{parts[0]}.{parts[1]}.{p}.{b}",
                        f"https://www.minecraft.net/bedrockdedicatedserver/bin-win-preview/bedrock-server-{parts[0]}.{parts[1]}.{p}.{b}.zip",
                        "preview")
                       for p in range(0, self._patch_range) for b in range(0, self._build_range)]
            urls = stable + preview
        else:
            urls = []
            for major in range(1, parts[0] + 1):
                sm = 18 if major == 1 else 0
                em = parts[1] + 1 if major == parts[0] else 40
                for minor in range(sm, em):
                    ep = parts[2] + 1 if (major == parts[0] and minor == parts[1]) else 140
                    for patch in range(0, ep):
                        for build in range(0, 35):
                            v = f"{major}.{minor}.{patch}.{build}"
                            urls.append((v, f"https://www.minecraft.net/bedrockdedicatedserver/bin-win/bedrock-server-{v}.zip", "stable"))
                            urls.append((v, f"https://www.minecraft.net/bedrockdedicatedserver/bin-win-preview/bedrock-server-{v}.zip", "preview"))

        total = len(urls)
        checked = 0
        for ver, url, branch in urls:
            if self._cancel:
                break
            for attempt in range(3):
                if self._cancel:
                    break
                try:
                    req = urllib.request.Request(url, method="HEAD",
                        headers={"User-Agent": random.choice(_UA_POOL)})
                    resp = urllib.request.urlopen(req, timeout=6)
                    if resp.getcode() == 200:
                        self.found.emit(ver, branch, url)
                    break
                except urllib.error.HTTPError as e:
                    if e.code == 429:
                        time.sleep(min(2 ** attempt, 8))
                    else:
                        break
                except (urllib.error.URLError, socket.timeout):
                    if attempt < 2:
                        time.sleep(0.5 * (attempt + 1))
                    else:
                        break
            checked += 1
            self.progress.emit(ver, int(checked * 100 / total))
        self.finished.emit()


# ── 下载 Worker（支持多线程分段）──
class DownloadWorker(QThread):
    progress = Signal(int)
    status = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, url: str, save_path: str, parent=None):
        super().__init__(parent)
        self.url = url
        self.save_path = save_path
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            hdr = {"User-Agent": "Mozilla/5.0"}
            resp = requests.get(self.url, stream=True, headers=hdr, timeout=600)
            total = int(resp.headers.get("content-length", 0))
            done = 0
            with open(self.save_path, "wb") as f:
                for chunk in resp.iter_content(8192):
                    if self._cancel:
                        self.finished.emit(False, "已取消")
                        return
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        pct = int(done * 100 / total)
                        self.progress.emit(pct)
                        self.status.emit(f"{done/1024/1024:.1f}/{total/1024/1024:.1f} MB ({pct}%)")
            self.finished.emit(True, "下载完成")
        except Exception as e:
            self.finished.emit(False, str(e))


# ── 安装 Worker ──
class InstallWorker(QThread):
    log = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, zip_path: str, server_dir: str, do_backup: bool, parent=None):
        super().__init__(parent)
        self.zip_path = zip_path
        self.server_dir = server_dir
        self.do_backup = do_backup

    def run(self):
        import zipfile
        try:
            # 预备份
            backup_dir = None
            if self.do_backup:
                ts = time.strftime("%Y%m%d_%H%M%S")
                backup_dir = os.path.join(self.server_dir, "backups", f"pre_upgrade_{ts}")
                os.makedirs(backup_dir, exist_ok=True)
                self.log.emit("正在备份关键文件...")
                for d in ["worlds", "resource_packs", "behavior_packs", "config"]:
                    src = os.path.join(self.server_dir, d)
                    if os.path.exists(src):
                        try:
                            shutil.copytree(src, os.path.join(backup_dir, d))
                            self.log.emit(f"  已备份: {d}")
                        except Exception:
                            pass
                for fn in ["server.properties", "allowlist.json", "permissions.json"]:
                    src = os.path.join(self.server_dir, fn)
                    if os.path.exists(src):
                        shutil.copy2(src, os.path.join(backup_dir, fn))

            # 解压（带 ZipSlip 防护 + 跳过 worlds/config 等）
            self.log.emit("正在解压更新包...")
            skip = {"worlds/", "resource_packs/", "behavior_packs/",
                    "config/", "server.properties", "allowlist.json",
                    "permissions.json", "backups/"}
            server_real = os.path.realpath(self.server_dir)
            with zipfile.ZipFile(self.zip_path) as zf:
                names = [n.replace("\\", "/") for n in zf.namelist()]
                top = set(p.split("/")[0] for p in names if "/" in p and p.split("/")[0])
                has_prefix = len(top) == 1 and all("/" in n for n in names)

                for orig, norm in zip(zf.namelist(), names):
                    parts = [p for p in norm.split("/") if p not in ("", ".", "..")]
                    if not parts:
                        continue
                    rel = "/".join(parts[1:] if has_prefix and len(parts) > 1 else parts)
                    if not rel or norm.endswith("/"):
                        continue
                    if any(rel.lower().startswith(s) for s in skip):
                        continue
                    target = os.path.join(self.server_dir, rel)
                    tr = os.path.realpath(target)
                    if tr != server_real and not tr.startswith(server_real + os.sep):
                        continue
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with open(target, "wb") as dst:
                        dst.write(zf.read(orig))

            self.log.emit("✅ 安装完成")
            self.finished.emit(True, "安装完成")
        except Exception as e:
            self.log.emit(f"❌ 安装失败: {e}")
            self.finished.emit(False, str(e))


# ── 升级页面 ──
class UpgradePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._results: list[tuple] = []  # [(ver, branch, url), ...]
        inner, layout = wrap_scrollable(self, spacing=12)

        # ── 加载缓存版本 ──
        cached = config_mgr.get("version_list", {})
        if isinstance(cached, dict) and cached.get("data"):
            self._results = cached["data"]

        # ── 当前信息 ──
        info_card = CardWidget(inner)
        il = QVBoxLayout(info_card)
        il.setContentsMargins(16, 12, 16, 16); il.setSpacing(6)
        il.addWidget(SubtitleLabel("当前状态", info_card))
        ctx = get_context()
        exe_name = config_mgr.get("server_exe", "bedrock_server.exe")
        self._server_exe_path = os.path.join(ctx.server_dir, exe_name)
        self._server_installed = os.path.exists(self._server_exe_path)

        if self._server_installed:
            self._info = BodyLabel(f"✅ BDS 已安装 — {ctx.server_dir}", info_card)
            il.addWidget(self._info)
        else:
            self._info = BodyLabel(f"❌ 未检测到 BDS — 请先安装服务器", info_card)
            self._info.setStyleSheet("color: #ffaa00;")
            il.addWidget(self._info)
            il.addWidget(CaptionLabel(f"预期路径: {self._server_exe_path}", info_card))
        layout.addWidget(info_card)

        # ── 版本列表 ──
        ver_card = CardWidget(inner)
        vl = QVBoxLayout(ver_card)
        vl.setContentsMargins(16, 12, 16, 16); vl.setSpacing(8)

        hdr = QHBoxLayout()
        hdr.addWidget(SubtitleLabel("可用版本", ver_card))
        hdr.addStretch()
        self._fetch_btn = PrimaryPushButton("浏览可用版本", ver_card, FluentIcon.SYNC)
        self._stop_btn = PushButton("停止", ver_card, FluentIcon.CANCEL)
        self._stop_btn.setEnabled(False)
        self._patch_spin = SpinBox(ver_card)
        self._patch_spin.setRange(10, 200); self._patch_spin.setValue(40)
        self._build_spin = SpinBox(ver_card)
        self._build_spin.setRange(5, 60); self._build_spin.setValue(30)
        hdr.addWidget(self._fetch_btn)
        hdr.addWidget(self._stop_btn)
        hdr.addWidget(CaptionLabel("Patch:", ver_card))
        hdr.addWidget(self._patch_spin)
        hdr.addWidget(CaptionLabel("Build:", ver_card))
        hdr.addWidget(self._build_spin)
        vl.addLayout(hdr)

        self._ver_table = QTableWidget(0, 3, ver_card)
        self._ver_table.setHorizontalHeaderLabels(["版本", "分支", "操作"])
        self._ver_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._ver_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._ver_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._ver_table.verticalHeader().setVisible(False)
        self._ver_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._ver_table.setStyleSheet("""
            QTableWidget { background:#1e1e1e;color:#ccc;border:1px solid #3a3a3a;border-radius:6px;gridline-color:#3a3a3a; }
            QHeaderView::section { background:#2a2a2a;color:#aaa;border:none;padding:6px 8px;font-weight:bold; }
        """)
        vl.addWidget(self._ver_table)

        self._scan_status = CaptionLabel("", ver_card)
        self._scan_status.setStyleSheet("color:#888;")
        vl.addWidget(self._scan_status)

        # 手动输入
        man_row = QHBoxLayout()
        man_row.addWidget(CaptionLabel("手动版本:", ver_card))
        self._manual_input = LineEdit(ver_card)
        self._manual_input.setPlaceholderText("1.21.0.2")
        self._manual_input.setMaximumWidth(110)
        self._manual_dl = PushButton("下载", ver_card, FluentIcon.DOWNLOAD)
        self._manual_dl.clicked.connect(self._download_manual)
        man_row.addWidget(self._manual_input)
        man_row.addWidget(self._manual_dl)
        man_row.addStretch()
        vl.addLayout(man_row)

        layout.addWidget(ver_card)

        # ── 进度 ──
        prog_card = CardWidget(inner)
        pl = QVBoxLayout(prog_card)
        pl.setContentsMargins(16, 12, 16, 16); pl.setSpacing(6)
        self._dl_bar = ProgressBar(prog_card); self._dl_bar.setVisible(False)
        pl.addWidget(self._dl_bar)
        self._dl_status = CaptionLabel("", prog_card)
        pl.addWidget(self._dl_status)
        layout.addWidget(prog_card)

        # ── 日志 ──
        log_card = CardWidget(inner)
        ll = QVBoxLayout(log_card)
        ll.setContentsMargins(12, 10, 12, 12)
        ll.addWidget(CaptionLabel("操作日志", log_card))
        self._log = QPlainTextEdit(log_card)
        self._log.setReadOnly(True); self._log.setMaximumBlockCount(2000)
        self._log.setMinimumHeight(100)
        self._log.setStyleSheet("QPlainTextEdit{background:#1e1e1e;color:#ccc;border:1px solid #3a3a3a;border-radius:6px;padding:6px;font-family:Consolas,monospace;font-size:12px;}")
        ll.addWidget(self._log)
        layout.addWidget(log_card)

        # ── 工具自更新 ──
        tool_card = CardWidget(inner)
        tl = QVBoxLayout(tool_card)
        tl.setContentsMargins(16, 12, 16, 16); tl.setSpacing(8)
        hdr = QHBoxLayout()
        hdr.addWidget(SubtitleLabel("BDS Manager 自身更新", tool_card))
        hdr.addStretch()
        import main
        self._tool_ver_label = CaptionLabel(f"当前 v{main.__version__}", tool_card)
        hdr.addWidget(self._tool_ver_label)
        tl.addLayout(hdr)

        btn_row = QHBoxLayout()
        self._tool_check_btn = PushButton("检查工具更新", tool_card, FluentIcon.SYNC)
        self._tool_check_btn.clicked.connect(self._check_tool_update)
        self._tool_install_btn = PushButton("安装更新并重启", tool_card, FluentIcon.UPDATE)
        self._tool_install_btn.setEnabled(False)
        self._tool_install_btn.clicked.connect(self._install_tool_update)
        btn_row.addWidget(self._tool_check_btn)
        btn_row.addWidget(self._tool_install_btn)
        btn_row.addStretch()
        tl.addLayout(btn_row)

        self._tool_bar = ProgressBar(tool_card)
        self._tool_bar.setVisible(False)
        tl.addWidget(self._tool_bar)
        self._tool_status = CaptionLabel("", tool_card)
        tl.addWidget(self._tool_status)

        layout.addWidget(tool_card)
        layout.addStretch()

        self._fetch_btn.clicked.connect(self._fetch)
        self._stop_btn.clicked.connect(self._stop_scan)

        # 首次展示缓存版本
        if self._results:
            self._populate_table()
            self._scan_status.setText(f"已加载 {len(self._results)} 个缓存版本（点击浏览刷新）")

    # ── 工具自更新 ──
    def _check_tool_update(self):
        from backend.self_update import CheckUpdateWorker, DownloadUpdateWorker, verify_sha256, is_valid_zip

        self._tool_check_btn.setEnabled(False)
        self._tool_status.setText("正在检查更新...")

        self.__checker = CheckUpdateWorker(self)
        self.__checker.result.connect(lambda s, v, u, sh: self._on_tool_check_done(s, v, u, sh))
        self.__checker.start()

    def _on_tool_check_done(self, status, remote_ver, dl_url, sha256):
        self._tool_check_btn.setEnabled(True)
        import main
        if status == "error":
            self._tool_status.setText(f"检查失败: {remote_ver}")
            return
        if status == "latest":
            self._tool_status.setText(f"✅ 已是最新 v{main.__version__}")
            return
        if not dl_url:
            self._tool_status.setText("❌ 未找到下载链接")
            return

        self._tool_status.setText(f"发现 v{remote_ver}，正在下载...")
        self._tool_bar.setVisible(True)
        self._tool_bar.setRange(0, 100)
        self._tool_bar.setValue(0)

        from backend.self_update import DownloadUpdateWorker
        self.__dl = DownloadUpdateWorker(dl_url, remote_ver, self)
        self.__dl.progress.connect(self._tool_bar.setValue)
        self.__dl.finished.connect(lambda s, m, p: self._on_tool_dl_done(s, m, p, sha256))
        self.__dl.start()

    def _on_tool_dl_done(self, success, msg, path, sha256):
        self._tool_bar.setVisible(False)
        if not success:
            self._tool_status.setText(f"❌ 下载失败: {msg}")
            return
        from backend.self_update import verify_sha256, is_valid_zip
        if not is_valid_zip(path):
            self._tool_status.setText("❌ 下载文件无效")
            try: os.remove(path)
            except OSError: pass
            return
        ok, sha_msg = verify_sha256(path, sha256)
        if not ok:
            self._tool_status.setText(f"❌ SHA256 校验失败: {sha_msg}")
            try: os.remove(path)
            except OSError: pass
            return
        self._tool_zip = path
        self._tool_status.setText(f"✅ 就绪: {os.path.basename(path)} | {sha_msg}")
        self._tool_install_btn.setEnabled(True)

    def _install_tool_update(self):
        if not hasattr(self, "_tool_zip") or not os.path.exists(self._tool_zip):
            self._tool_status.setText("❌ 找不到更新包")
            return
        from PySide6.QtWidgets import QMessageBox
        from backend.self_update import InstallUpdateWorker, restart_app
        self._tool_status.setText("正在安装更新...")
        self._tool_install_btn.setEnabled(False)
        self.__installer = InstallUpdateWorker(self._tool_zip, self)
        self.__installer.finished.connect(lambda s, _: (
            QMessageBox.information(self, "更新完成", "BDS Manager 已更新！即将自动重启。") if s else None,
            restart_app("main.py") if s else None
        ))
        self.__installer.start()

    # ── 日志 ──
    def _log_line(self, msg: str):
        self._log.appendPlainText(msg)
        self._log.moveCursor(QTextCursor.End)

    # ── 版本抓取 ──
    def _fetch(self):
        self._ver_table.setRowCount(0)
        self._results.clear()
        self._fetch_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._scan_status.setText("正在从 GitHub 获取版本列表...")
        self._log_line("正在从 GitHub 获取版本列表...")

        self._github_worker = GithubFetcher(self)
        self._github_worker.result.connect(self._on_github_done)
        self._github_worker.start()

    def _on_github_done(self, ok: bool, results: list):
        self._fetch_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        if results:
            self._results = results
            self._save_cache()
            self._populate_table()
            self._scan_status.setText(f"GitHub: {len(results)} 个版本可用")
            self._log_line(f"GitHub 获取到 {len(results)} 个版本，完成")
        else:
            self._scan_status.setText("GitHub 失败，回退 HEAD 全量扫描...")
            self._log_line("GitHub 获取失败，开始 HEAD 全量扫描...")
            ctx = get_context()
            base = "1.20.0.0"
            self._start_head_scan(base, append_mode=False)

    def _start_head_scan(self, base_ver: str, append_mode: bool):
        self._head_worker = HeadScanWorker(
            base_ver, self._patch_spin.value(), self._build_spin.value(),
            append_mode, self,
        )
        self._head_worker.progress.connect(lambda v, p: self._scan_status.setText(f"探测 {v} ({p}%)"))
        self._head_worker.found.connect(self._on_head_found)
        self._head_worker.finished.connect(self._on_scan_done)
        self._head_worker.start()

    def _on_head_found(self, ver: str, branch: str, url: str):
        if not any(v == ver and b == branch for v, b, u in self._results):
            self._results.append((ver, branch, url))
            self._populate_table()

    def _on_scan_done(self):
        self._fetch_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._save_cache()
        self._populate_table()
        self._scan_status.setText(f"共 {len(self._results)} 个版本可用")

    def _save_cache(self):
        """将当前版本列表缓存到配置（持久化到 bds_version_cache.json）。"""
        config_mgr.set("version_list", {
            "data": self._results,
            "timestamp": int(time.time()),
        })
        config_mgr.save()

    def _stop_scan(self):
        if hasattr(self, "_head_worker") and self._head_worker.isRunning():
            self._head_worker.cancel()
        self._fetch_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)

    def _populate_table(self):
        seen = set()
        deduped = []
        for v, b, u in self._results:
            if (v, b) not in seen:
                seen.add((v, b))
                deduped.append((v, b, u))
        self._results = deduped
        try:
            deduped.sort(key=lambda x: [int(i) for i in x[0].split(".")], reverse=True)
        except Exception:
            pass

        self._ver_table.setRowCount(len(deduped))
        for i, (ver, branch, url) in enumerate(deduped):
            self._ver_table.setItem(i, 0, QTableWidgetItem(ver))
            color = "#4CAF50" if branch == "stable" else "#ff9800"
            item = QTableWidgetItem("稳定版" if branch == "stable" else "预览版")
            self._ver_table.setItem(i, 1, item)
            btn = PushButton("下载安装", self._ver_table)
            btn.clicked.connect(lambda checked, u=url, v=ver: self._install(u, v))
            self._ver_table.setCellWidget(i, 2, btn)

    # ── 手动下载 ──
    def _download_manual(self):
        ver = self._manual_input.text().strip()
        if not ver:
            return
        url = f"https://www.minecraft.net/bedrockdedicatedserver/bin-win/bedrock-server-{ver}.zip"
        self._install(url, ver)

    # ── 下载 + 安装 ──
    def _install(self, url: str, version: str):
        ctx = get_context()
        self._dl_bar.setVisible(True)
        self._dl_bar.setRange(0, 100)
        self._dl_bar.setValue(0)
        self._log_line(f"准备安装 BDS {version}")

        dl_path = os.path.join(SCRIPT_DIR, f"_update_v{version}.zip")
        self._dl_worker = DownloadWorker(url, dl_path, self)
        self._dl_worker.progress.connect(self._dl_bar.setValue)
        self._dl_worker.status.connect(self._dl_status.setText)
        self._dl_worker.finished.connect(lambda ok, msg: self._on_dl_done(ok, msg, dl_path, version))
        self._dl_worker.start()

    def _on_dl_done(self, ok: bool, msg: str, zip_path: str, version: str):
        if not ok:
            self._dl_bar.setVisible(False)
            toast_error("下载失败", msg, self.window())
            self._log_line(f"❌ 下载失败: {msg}")
            return
        self._log_line("下载完成，开始安装...")
        ctx = get_context()
        self._install_worker = InstallWorker(zip_path, ctx.server_dir, True, self)
        self._install_worker.log.connect(self._log_line)
        self._install_worker.finished.connect(lambda s, m: self._on_install_done(s, m, zip_path))
        self._install_worker.start()

    def _on_install_done(self, success: bool, msg: str, zip_path: str):
        self._dl_bar.setVisible(False)
        try:
            if os.path.exists(zip_path):
                os.remove(zip_path)
        except Exception:
            pass
        if success:
            toast_success("安装完成", "BDS 已更新，请重新启动服务器", self.window())
        else:
            toast_error("安装失败", msg, self.window())
