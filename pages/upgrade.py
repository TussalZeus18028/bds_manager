# -*- coding: utf-8 -*-
"""
升级 / 安装页面 —— BDS 版本管理（对齐旧 PyQt5 版完整逻辑）。

v3.1 改进：
- 升级历史（.upgrade_history.json）
- "回滚到上一版本"按钮（用 pre_upgrade_ 备份）
- 选中两行对比 Changelog
- metadata 显示在表格（bds_version + 文件大小）
- HEAD 扫描 memoize（已存在）
"""

import os, re, time, json, shutil, tempfile, random, socket, ssl, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QPlainTextEdit,
)
from PySide6.QtGui import QTextCursor
from qfluentwidgets import (
    CardWidget, SubtitleLabel, StrongBodyLabel, BodyLabel, CaptionLabel,
    PrimaryPushButton, PushButton, LineEdit, FluentIcon,
    ProgressBar, MessageBox,
)

from shared.config import config_mgr, get_context, SCRIPT_DIR
from shared.toast import toast_success, toast_error, toast_info
from pages.dashboard import wrap_scrollable
from components.widgets import NoScrollSpinBox  # v3.02.01: 滚轮防护

import requests

# ── 升级历史 ──
UPGRADE_HISTORY_FILE = os.path.join(SCRIPT_DIR, ".upgrade_history.json")


def _load_upgrade_history() -> list[dict]:
    if not os.path.exists(UPGRADE_HISTORY_FILE):
        return []
    try:
        with open(UPGRADE_HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_upgrade_history(history: list[dict]):
    try:
        with open(UPGRADE_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history[-50:], f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _record_upgrade(version: str, from_ver: str, backup_dir: str | None):
    history = _load_upgrade_history()
    history.append({
        "version": version,
        "from_version": from_ver,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "backup_dir": backup_dir,
    })
    _save_upgrade_history(history)


# ── 扫描范围常量 ──
VERSION_LIST_URL = "https://raw.githubusercontent.com/TussalZeus18028/bds_version_list/main/bds_versions.json"
_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
]


# ── GitHub 版本列表抓取 ──
def _scrape_github_versions() -> list | None:
    try:
        req = urllib.request.Request(VERSION_LIST_URL, headers={
            "User-Agent": "BDS-Manager/3.1",
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


class GithubFetcher(QThread):
    result = Signal(bool, list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        r = _scrape_github_versions()
        if self._cancel:
            self.result.emit(False, [])
            return
        self.result.emit(r is not None, r if r else [])


class HeadScanWorker(QThread):
    progress = Signal(str, int)
    found = Signal(str, str, str)
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


class InstallWorker(QThread):
    log = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, zip_path: str, server_dir: str, do_backup: bool,
                 target_version: str = "", from_version: str = "", parent=None):
        super().__init__(parent)
        self.zip_path = zip_path
        self.server_dir = server_dir
        self.do_backup = do_backup
        self.target_version = target_version
        self.from_version = from_version
        self.backup_dir: str | None = None

    def run(self):
        import zipfile
        try:
            if self.do_backup:
                ts = time.strftime("%Y%m%d_%H%M%S")
                self.backup_dir = os.path.join(self.server_dir, "backups", f"pre_upgrade_{ts}")
                os.makedirs(self.backup_dir, exist_ok=True)
                self.log.emit("正在备份关键文件...")
                for d in ["worlds", "resource_packs", "behavior_packs", "config"]:
                    src = os.path.join(self.server_dir, d)
                    if os.path.exists(src):
                        try:
                            shutil.copytree(src, os.path.join(self.backup_dir, d))
                            self.log.emit(f"  已备份: {d}")
                        except Exception:
                            pass
                for fn in ["server.properties", "allowlist.json", "permissions.json"]:
                    src = os.path.join(self.server_dir, fn)
                    if os.path.exists(src):
                        shutil.copy2(src, os.path.join(self.backup_dir, fn))

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

            # 记录升级历史
            if self.target_version and self.backup_dir:
                _record_upgrade(self.target_version, self.from_version, self.backup_dir)

            self.log.emit("✅ 安装完成")
            self.finished.emit(True, "安装完成")
        except Exception as e:
            self.log.emit(f"❌ 安装失败: {e}")
            self.finished.emit(False, str(e))


class HeadSizeWorker(QThread):
    """后台 HEAD 请求批量获取版本 zip 大小，避免阻塞 UI。"""
    result = Signal(int, str)  # (row_index, size_text)

    def __init__(self, items: list[tuple[int, str]], parent=None):
        """items: [(row_index, url), ...]"""
        super().__init__(parent)
        self._items = items
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        for row, url in self._items:
            if self._cancel:
                break
            try:
                req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
                resp = urllib.request.urlopen(req, timeout=4)
                size = int(resp.headers.get("content-length", 0))
                size_text = f"{size/1024/1024:.1f} MB"
            except Exception:
                size_text = "—"
            self.result.emit(row, size_text)


class UpgradePage(QWidget):
    # GitHub 重试配置：失败时先重试 N 次，最后才提示用户启用 HEAD 嗅探（最后手段）
    GITHUB_MAX_RETRIES = 3
    GITHUB_BACKOFF_BASE = 2  # 秒（指数退避：1s, 2s, 4s）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._results: list[tuple] = []
        self._size_worker: HeadSizeWorker | None = None
        self._head_worker: HeadScanWorker | None = None
        self._github_worker: GithubFetcher | None = None
        # 重试 & 嗅探 fallback 状态
        self._github_attempt = 0          # 当前是第几次尝试
        self._github_silent = False       # True = 后台静默（不弹窗）
        self._pending_head_scan = False   # GitHub 全部失败后，等待用户点「启用 HEAD 嗅探」
        inner, layout = wrap_scrollable(self, spacing=12)

        cached = config_mgr.get("version_list", {})
        if isinstance(cached, dict) and cached.get("data"):
            self._results = cached["data"]

        # 当前信息
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

        # 版本列表
        ver_card = CardWidget(inner)
        vl = QVBoxLayout(ver_card)
        vl.setContentsMargins(16, 12, 16, 16); vl.setSpacing(8)

        hdr = QHBoxLayout()
        hdr.addWidget(SubtitleLabel("可用版本", ver_card))
        hdr.addStretch()
        self._fetch_btn = PrimaryPushButton("浏览可用版本", ver_card, FluentIcon.SYNC)
        self._stop_btn = PushButton("停止", ver_card, FluentIcon.CANCEL)
        self._stop_btn.setEnabled(False)
        self._patch_spin = NoScrollSpinBox(ver_card)
        self._patch_spin.setRange(10, 200); self._patch_spin.setValue(40)
        self._build_spin = NoScrollSpinBox(ver_card)
        self._build_spin.setRange(5, 60); self._build_spin.setValue(30)
        hdr.addWidget(self._fetch_btn)
        hdr.addWidget(self._stop_btn)
        hdr.addWidget(CaptionLabel("Patch:", ver_card))
        hdr.addWidget(self._patch_spin)
        hdr.addWidget(CaptionLabel("Build:", ver_card))
        hdr.addWidget(self._build_spin)
        vl.addLayout(hdr)

        self._ver_table = QTableWidget(0, 4, ver_card)
        self._ver_table.setHorizontalHeaderLabels(["版本", "分支", "大小", "操作"])
        self._ver_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for col, w in [(1, 80), (2, 90), (3, 110)]:
            self._ver_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.Fixed)
            self._ver_table.setColumnWidth(col, w)
        self._ver_table.verticalHeader().setVisible(False)
        self._ver_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._ver_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._ver_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._ver_table.setMinimumHeight(320)
        self._ver_table.setStyleSheet("""
            QTableWidget { background:#1e1e1e;color:#ccc;border:1px solid #3a3a3a;border-radius:6px;gridline-color:#3a3a3a; }
            QTableWidget::item { padding: 2px 8px; }
            QTableWidget::item:selected { background: rgba(13, 197, 212, 0.25); }
            QHeaderView::section { background:#2a2a2a;color:#aaa;border:none;padding:6px 8px;font-weight:bold; }
        """)
        vl.addWidget(self._ver_table)

        # 工具行
        tools_row = QHBoxLayout()
        self._size_btn = PushButton("获取文件大小", ver_card, FluentIcon.SEND)
        self._size_btn.clicked.connect(self._fetch_sizes)
        self._compare_btn = PushButton("对比选中", ver_card, FluentIcon.SEND)
        self._compare_btn.clicked.connect(self._on_compare_versions)
        self._rollback_btn = PushButton("回滚到上一版本", ver_card, FluentIcon.CANCEL)
        self._rollback_btn.clicked.connect(self._on_rollback)
        tools_row.addWidget(self._size_btn)
        tools_row.addWidget(self._compare_btn)
        tools_row.addWidget(self._rollback_btn)
        tools_row.addStretch()
        vl.addLayout(tools_row)

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

        # 升级历史
        history_card = CardWidget(inner)
        hl = QVBoxLayout(history_card)
        hl.setContentsMargins(16, 12, 16, 16); hl.setSpacing(6)
        hl.addWidget(SubtitleLabel("升级历史", history_card))
        self._history_table = QTableWidget(0, 3, history_card)
        self._history_table.setHorizontalHeaderLabels(["时间", "版本", "回滚"])
        self._history_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._history_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self._history_table.setColumnWidth(2, 80)
        self._history_table.verticalHeader().setVisible(False)
        self._history_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._history_table.setStyleSheet("""
            QTableWidget { background:#1e1e1e;color:#ccc;border:1px solid #3a3a3a;border-radius:6px;gridline-color:#3a3a3a; }
            QTableWidget::item { padding: 4px 8px; }
            QHeaderView::section { background:#2a2a2a;color:#aaa;border:none;padding:6px 8px;font-weight:bold; }
        """)
        hl.addWidget(self._history_table)
        layout.addWidget(history_card)

        # 进度
        prog_card = CardWidget(inner)
        pl = QVBoxLayout(prog_card)
        pl.setContentsMargins(16, 12, 16, 16); pl.setSpacing(6)
        self._dl_bar = ProgressBar(prog_card); self._dl_bar.setVisible(False)
        pl.addWidget(self._dl_bar)
        self._dl_status = CaptionLabel("", prog_card)
        pl.addWidget(self._dl_status)
        layout.addWidget(prog_card)

        # 日志
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

        # 工具自更新
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

        if self._results:
            self._populate_table()
            cached_ts = cached.get("timestamp", 0) if isinstance(cached, dict) else 0
            age = int(time.time() - cached_ts) if cached_ts else 0
            if age < 60:
                age_text = f"{age} 秒前"
            elif age < 3600:
                age_text = f"{age // 60} 分钟前"
            elif age < 86400:
                age_text = f"{age // 3600} 小时前"
            else:
                age_text = f"{age // 86400} 天前"
            self._scan_status.setText(f"📦 缓存 {len(self._results)} 个版本（{age_text}），后台静默检查中...")

        self._refresh_history()
        self._auto_refreshed = False  # 首次 showEvent 触发后台刷新

    def showEvent(self, event):
        """首次显示页面时，如果缓存过期则后台静默刷新（不打断用户）。"""
        super().showEvent(event)
        if self._auto_refreshed:
            return
        self._auto_refreshed = True
        cached = config_mgr.get("version_list", {})
        ts = cached.get("timestamp", 0) if isinstance(cached, dict) else 0
        # 缓存 5 分钟内不算过期，不触发后台请求
        if time.time() - ts < 300:
            return
        # 延迟 800ms 启动后台刷新，避免影响 UI 渲染
        QTimer.singleShot(800, self._auto_refresh)

    def _auto_refresh(self):
        """静默后台拉取 GitHub 版本列表（不打断用户操作）。"""
        # 已经有用户在主动获取就跳过
        if hasattr(self, "_github_worker") and self._github_worker and self._github_worker.isRunning():
            return
        if hasattr(self, "_head_worker") and self._head_worker and self._head_worker.isRunning():
            return
        self._start_github_fetch(silent=True)

    def _refresh_history(self):
        history = _load_upgrade_history()
        self._history_table.setRowCount(len(history))
        for i, h in enumerate(reversed(history)):
            self._history_table.setItem(i, 0, QTableWidgetItem(h.get("timestamp", "")))
            ver_text = f"{h.get('from_version', '?')} → {h.get('version', '?')}"
            self._history_table.setItem(i, 1, QTableWidgetItem(ver_text))
            backup = h.get("backup_dir")
            if backup and os.path.exists(backup):
                btn = PushButton("回滚", self._history_table)
                btn.clicked.connect(lambda checked, b=backup: self._do_rollback(b))
                self._history_table.setCellWidget(i, 2, btn)
            else:
                item = QTableWidgetItem("—")
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                self._history_table.setItem(i, 2, item)

    def _on_compare_versions(self):
        """对比选中的两个版本（Changelog 链接）。"""
        sel = self._ver_table.selectionModel().selectedRows()
        if len(sel) != 2:
            toast_info("提示", "请先在表格中按住 Ctrl 选中 2 个版本", self.window())
            return
        v1 = self._ver_table.item(sel[0].row(), 0).text()
        v2 = self._ver_table.item(sel[1].row(), 0).text()
        # Mojang 官方 Changelog 页
        url = f"https://feedback.minecraft.net/hc/en-us/articles/4410058574989-Minecraft-Bedrock-Changelog"
        mb = MessageBox(
            "版本对比",
            f"已选: <b>{v1}</b> vs <b>{v2}</b>\n\n"
            f"请访问 Mojang 官方 Changelog 页面查看详细变更：\n{url}\n\n"
            f"（本工具暂未集成自动 Changelog 抓取）",
            self.window(),
        )
        mb.exec()

    def _on_rollback(self):
        history = _load_upgrade_history()
        if not history:
            toast_info("无历史", "尚无升级记录可回滚", self.window())
            return
        last = history[-1]
        backup = last.get("backup_dir")
        if not backup or not os.path.exists(backup):
            toast_error("不可用", f"上次的备份已不存在: {backup}", self.window())
            return
        confirm = MessageBox(
            "回滚确认",
            f"将回滚到 <b>{last.get('from_version', '?')}</b> 版本。\n\n"
            f"备份位置: {backup}\n\n是否继续？",
            self.window(),
        )
        if confirm.exec():
            self._do_rollback(backup)

    def _do_rollback(self, backup_dir: str):
        """从备份目录恢复 server.properties / worlds / packs / config。"""
        ctx = get_context()
        server_dir = ctx.server_dir
        restored = []
        try:
            for d in ["worlds", "resource_packs", "behavior_packs", "config"]:
                src = os.path.join(backup_dir, d)
                dst = os.path.join(server_dir, d)
                if os.path.exists(src):
                    if os.path.exists(dst):
                        shutil.rmtree(dst, ignore_errors=True)
                    shutil.copytree(src, dst)
                    restored.append(d)
            for fn in ["server.properties", "allowlist.json", "permissions.json"]:
                src = os.path.join(backup_dir, fn)
                dst = os.path.join(server_dir, fn)
                if os.path.exists(src):
                    shutil.copy2(src, dst)
                    restored.append(fn)
            toast_success("回滚完成", f"已恢复: {', '.join(restored) or '(无)'}", self.window())
        except Exception as e:
            toast_error("回滚失败", str(e), self.window())

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
        from backend.self_update import InstallUpdateWorker, restart_app
        self._tool_status.setText("正在安装更新...")
        self._tool_install_btn.setEnabled(False)
        self.__installer = InstallUpdateWorker(self._tool_zip, self)
        self.__installer.finished.connect(lambda s, _: (
            MessageBox.information(self, "更新完成", "BDS Manager 已更新！即将自动重启。") if s else None,
            restart_app("main.py") if s else None
        ))
        self.__installer.start()

    def _log_line(self, msg: str):
        self._log.appendPlainText(msg)
        self._log.moveCursor(QTextCursor.End)

    def _fetch(self):
        """用户点「浏览可用版本」：清旧表 → GitHub 重试 → 失败后提示用户启用 HEAD 嗅探。"""
        self._ver_table.setRowCount(0)
        self._results.clear()
        self._fetch_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._stop_btn.setText("停止")
        self._pending_head_scan = False
        self._log_line("🔄 正在从 GitHub 仓库拉取版本列表...")
        self._start_github_fetch(silent=False)

    def _start_github_fetch(self, silent: bool, attempt: int = 1):
        """单次 GitHub 拉取；失败由 _on_github_done 决定是否重试。"""
        self._github_attempt = attempt
        self._github_silent = silent
        self._scan_status.setText(
            f"🔄 拉取 GitHub 仓库版本列表...（尝试 {attempt}/{self.GITHUB_MAX_RETRIES}）"
        )
        if not silent:
            self._log_line(f"🔄 GitHub 拉取（尝试 {attempt}/{self.GITHUB_MAX_RETRIES}）")
        self._github_worker = GithubFetcher(self)
        # 用默认参数绑定 attempt，避免 lambda 闭包陷阱
        self._github_worker.result.connect(
            lambda ok, r, a=attempt, s=silent: self._on_github_done(ok, r, a, s)
        )
        self._github_worker.start()

    def _on_github_done(self, ok: bool, results: list, attempt: int, silent: bool):
        """单次拉取完成：成功 → 写缓存；失败 → 重试或 fallback。"""
        if ok and results:
            self._on_github_success(results, silent)
            return
        # 失败：还有重试次数？
        if attempt < self.GITHUB_MAX_RETRIES:
            delay = self.GITHUB_BACKOFF_BASE ** (attempt - 1)  # 1, 2, 4 秒
            self._scan_status.setText(
                f"⚠️ GitHub 拉取失败，{delay}s 后重试（{attempt+1}/{self.GITHUB_MAX_RETRIES}）"
            )
            if not silent:
                self._log_line(f"⚠️ GitHub 失败，{delay}s 后重试（{attempt+1}/{self.GITHUB_MAX_RETRIES}）")
            QTimer.singleShot(delay * 1000, lambda: self._start_github_fetch(silent, attempt + 1))
            return
        # 全部失败
        if silent:
            # 后台静默：直接放弃，保留缓存
            self._scan_status.setText(f"❌ 后台静默检查失败（尝试 {attempt} 次），保留缓存")
            return
        # 用户主动：把停止按钮变成"启用 HEAD 嗅探"，让用户决定
        self._on_github_exhausted()

    def _on_github_success(self, results: list, silent: bool):
        """GitHub 拉取成功：写缓存 + 填表。"""
        cached = config_mgr.get("version_list", {}).get("data", [])
        if (len(results) == len(cached)
            and results and cached and results[0] == cached[0]):
            self._save_cache()
            self._populate_table()
            self._scan_status.setText(f"✅ {len(results)} 个版本（无变化）")
            return
        self._results = results
        self._save_cache()
        self._populate_table()
        msg = f"✅ GitHub: {len(results)} 个版本（之前 {len(cached)}）"
        self._scan_status.setText(msg)
        if not silent:
            self._log_line(msg)

    def _on_github_exhausted(self):
        """GitHub 全部失败：把停止按钮改为「启用 HEAD 嗅探」让用户决定（最后手段）。"""
        self._pending_head_scan = True
        self._fetch_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._stop_btn.setText("启用 HEAD 嗅探")
        self._scan_status.setText(
            f"❌ GitHub 失败 {self.GITHUB_MAX_RETRIES} 次 — 可点停止按钮启用 HEAD 嗅探（最后手段，65+ 请求）"
        )
        self._log_line(
            f"❌ GitHub 失败 {self.GITHUB_MAX_RETRIES} 次，嗅探作为最后手段"
        )

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
        config_mgr.set("version_list", {
            "data": self._results,
            "timestamp": int(time.time()),
        })
        config_mgr.save()

    def _stop_scan(self):
        """根据当前状态执行不同动作：
        1. GitHub 拉取中 → 取消
        2. HEAD 扫描中 → 取消
        3. GitHub 全部失败等待用户决定 → 启动 HEAD 嗅探（最后手段）
        """
        # 状态 3：用户点"启用 HEAD 嗅探"
        if self._pending_head_scan:
            self._pending_head_scan = False
            self._stop_btn.setText("停止")
            self._log_line("⚠️ 启用 HEAD 嗅探（最后手段，会发 65+ 个请求）...")
            self._start_head_scan("1.20.0.0", append_mode=False)
            return
        # 状态 1 & 2：中止正在运行的任务
        if self._github_worker and self._github_worker.isRunning():
            self._github_worker.cancel()
            self._github_worker.wait(800)
        if self._head_worker and self._head_worker.isRunning():
            self._head_worker.cancel()
            self._head_worker.wait(500)
        if self._size_worker and self._size_worker.isRunning():
            self._size_worker.cancel()
            self._size_worker.wait(500)
        self._fetch_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._stop_btn.setText("停止")
        if hasattr(self, "_size_btn"):
            self._size_btn.setEnabled(True)
            self._size_btn.setText("获取文件大小")
        self._scan_status.setText("⏹ 已中止")

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
        # 默认占位 "—"，文件大小需要用户点「获取文件大小」按钮才请求（启动加速）
        for i, (ver, branch, url) in enumerate(deduped):
            self._ver_table.setItem(i, 0, QTableWidgetItem(ver))
            branch_text = "稳定版" if branch == "stable" else "预览版"
            item = QTableWidgetItem(branch_text)
            self._ver_table.setItem(i, 1, item)
            self._ver_table.setItem(i, 2, QTableWidgetItem("—"))
            btn = PushButton("下载安装", self._ver_table)
            btn.clicked.connect(lambda checked, u=url, v=ver: self._install(u, v))
            self._ver_table.setCellWidget(i, 3, btn)
        # 恢复 size button
        if hasattr(self, "_size_btn"):
            self._size_btn.setEnabled(True)
            self._size_btn.setText("获取文件大小")

    def _fetch_sizes(self):
        """用户点「获取文件大小」时启动后台 HEAD 请求。"""
        items_for_size: list[tuple[int, str]] = []
        for i, (_v, _b, url) in enumerate(self._results[:self._ver_table.rowCount()]):
            items_for_size.append((i, url))
        if not items_for_size:
            return
        if self._size_worker and self._size_worker.isRunning():
            self._size_worker.cancel()
            self._size_worker.wait(500)
        self._size_worker = HeadSizeWorker(items_for_size, self)
        self._size_worker.result.connect(self._on_size_ready)
        self._size_worker.start()
        self._size_btn.setEnabled(False)
        self._size_btn.setText("正在获取...")

    def _on_size_ready(self, row: int, size_text: str):
        if row < self._ver_table.rowCount():
            self._ver_table.setItem(row, 2, QTableWidgetItem(size_text))

    def _download_manual(self):
        ver = self._manual_input.text().strip()
        if not ver:
            return
        url = f"https://www.minecraft.net/bedrockdedicatedserver/bin-win/bedrock-server-{ver}.zip"
        self._install(url, ver)

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
        # 检测当前版本
        from_version = ""
        try:
            ver_path = os.path.join(ctx.server_dir, "valid_known_packs.json")
            # 用文件存在性粗略判断
            if os.path.exists(os.path.join(ctx.server_dir, "bedrock_server.exe")):
                from_version = "current"
        except Exception:
            pass
        self._install_worker = InstallWorker(
            zip_path, ctx.server_dir, True, version, from_version, self
        )
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
            self._refresh_history()
        else:
            toast_error("安装失败", msg, self.window())
