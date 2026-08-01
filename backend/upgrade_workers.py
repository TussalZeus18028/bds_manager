# -*- coding: utf-8 -*-
"""
升级模块 — 后台工作线程。
从 pages/upgrade.py 抽离（v3.05.00），降低单文件复杂度。
"""
import os, re, time, json, random, socket, urllib.request, urllib.error, logging
import html as _html_lip

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger("bds_manager")

# ══════════════════════════════════════════
#  常量
# ══════════════════════════════════════════

VERSION_LIST_URL = (
    "https://raw.githubusercontent.com/TussalZeus18028/bds_version_list/main/bds_versions.json"
)
_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
]

_ANSI_RE = re.compile(r'\x1b\[([0-9;]*)m')
_ANSI_COLORS = {
    "30": "#000", "31": "#f55", "32": "#5f5", "33": "#ff5",
    "34": "#55f", "35": "#f5f", "36": "#5ff", "37": "#ccc",
    "90": "#888", "91": "#f88", "92": "#8f8", "93": "#ff8",
    "94": "#88f", "95": "#f8f", "96": "#8ff", "97": "#fff",
}

# ══════════════════════════════════════════
#  GitHub 版本列表抓取
# ══════════════════════════════════════════

def scrape_github_versions() -> list | None:
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
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError,
            socket.timeout, OSError) as e:
        logger.debug("抓取 GitHub 版本列表失败: %s", e)
        return None


# ══════════════════════════════════════════
#  ANSI → HTML（lip 终端着色）
# ══════════════════════════════════════════

def ansi_to_html(text: str) -> str:
    parts, stack, last = [], [], 0
    for m in _ANSI_RE.finditer(text):
        if m.start() > last:
            parts.append(_html_lip.escape(text[last:m.start()]))
        codes = m.group(1).split(";") if m.group(1) else ["0"]
        style = ""
        i = 0
        while i < len(codes):
            c = codes[i]
            if c == "0": stack = []
            elif c == "1": style += "font-weight:bold;"
            elif c == "38" and i+2 < len(codes) and codes[i+1] == "2":
                r = codes[i+2]; g = codes[i+3] if i+3 < len(codes) else "0"; b = codes[i+4] if i+4 < len(codes) else "0"
                style += f"color:rgb({r},{g},{b});"; i += 4
            elif c == "48" and i+2 < len(codes) and codes[i+1] == "2":
                r = codes[i+2]; g = codes[i+3] if i+3 < len(codes) else "0"; b = codes[i+4] if i+4 < len(codes) else "0"
                style += f"background:rgb({r},{g},{b});"; i += 4
            elif c in _ANSI_COLORS:
                style += f"color:{_ANSI_COLORS[c]};"
            elif c == "39": style += "color:inherit;"
            i += 1
        if style:
            stack.append(style); parts.append(f'<span style="{style}">')
        else:
            for _ in stack: parts.append("</span>")
            stack = []
        last = m.end()
    if last < len(text): parts.append(_html_lip.escape(text[last:]))
    for _ in stack: parts.append("</span>")
    return "".join(parts)


# ══════════════════════════════════════════
#  Worker 线程
# ══════════════════════════════════════════

class GithubFetcher(QThread):
    result = Signal(bool, list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        r = scrape_github_versions()
        if self._cancel:
            self.result.emit(False, [])
            return
        self.result.emit(r is not None, r if r else [])


class HeadScanWorker(QThread):
    progress = Signal(str, int)
    found = Signal(str, str, str)
    finished = Signal()

    def __init__(self, base_version: str, patch_range=40, build_range=30,
                 append_mode=False, parent=None):
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
        while len(parts) < 4: parts.append(0)
        urls = self._generate_urls(parts)
        total, checked = len(urls), 0
        for ver, url, branch in urls:
            if self._cancel: break
            self._probe_head(ver, url, branch)
            checked += 1
            self.progress.emit(ver, int(checked * 100 / total))
        self.finished.emit()

    def _generate_urls(self, parts: list[int]) -> list[tuple[str, str, str]]:
        if self._append_mode:
            stable = [(f"{parts[0]}.{parts[1]}.{p}.{b}",
                       f"https://www.minecraft.net/bedrockdedicatedserver/bin-win/bedrock-server-{parts[0]}.{parts[1]}.{p}.{b}.zip",
                       "stable")
                      for p in range(0, self._patch_range) for b in range(0, self._build_range)]
            preview = [(f"{parts[0]}.{parts[1]}.{p}.{b}",
                        f"https://www.minecraft.net/bedrockdedicatedserver/bin-win-preview/bedrock-server-{parts[0]}.{parts[1]}.{p}.{b}.zip",
                        "preview")
                       for p in range(0, self._patch_range) for b in range(0, self._build_range)]
            return stable + preview
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
        return urls

    def _probe_head(self, ver: str, url: str, branch: str):
        for attempt in range(3):
            if self._cancel: break
            try:
                req = urllib.request.Request(url, method="HEAD",
                    headers={"User-Agent": random.choice(_UA_POOL)})
                resp = urllib.request.urlopen(req, timeout=6)
                if resp.getcode() == 200:
                    self.found.emit(ver, branch, url)
                break
            except urllib.error.HTTPError as e:
                if e.code == 429: time.sleep(min(2 ** attempt, 8))
                else: break
            except (urllib.error.URLError, socket.timeout):
                if attempt < 2: time.sleep(0.5 * (attempt + 1))
                else: break


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
        import requests  # lazy import（非公共库）
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
        import zipfile, shutil
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
                        except OSError:
                            self.log.emit(f"  跳过: {d}（无法读取）")
                for fn in ["server.properties", "allowlist.json", "permissions.json"]:
                    src = os.path.join(self.server_dir, fn)
                    if os.path.exists(src):
                        shutil.copy2(src, os.path.join(self.backup_dir, fn))

            self.log.emit("正在解压更新包...")
            is_upgrade = self.do_backup and os.path.exists(
                os.path.join(self.server_dir, "bedrock_server.exe"))
            skip = ({"worlds/", "resource_packs/", "behavior_packs/",
                     "config/", "server.properties", "allowlist.json",
                     "permissions.json", "backups/"} if is_upgrade else set())
            server_real = os.path.realpath(self.server_dir)
            with zipfile.ZipFile(self.zip_path) as zf:
                names = [n.replace("\\", "/") for n in zf.namelist()]
                top = set(p.split("/")[0] for p in names if "/" in p and p.split("/")[0])
                has_prefix = len(top) == 1 and all("/" in n for n in names)
                for orig, norm in zip(zf.namelist(), names):
                    parts = [p for p in norm.split("/") if p not in ("", ".", "..")]
                    if not parts: continue
                    rel = "/".join(parts[1:] if has_prefix and len(parts) > 1 else parts)
                    if not rel or norm.endswith("/"): continue
                    if any(rel.lower().startswith(s) for s in skip): continue
                    target = os.path.join(self.server_dir, rel)
                    tr = os.path.realpath(target)
                    if tr != server_real and not tr.startswith(server_real + os.sep): continue
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with open(target, "wb") as dst:
                        dst.write(zf.read(orig))

            if self.target_version and self.backup_dir:
                _record_upgrade(self.target_version, self.from_version, self.backup_dir)

            self.log.emit("安装完成")
            self.finished.emit(True, "安装完成")
        except Exception as e:
            self.log.emit(f"安装失败: {e}")
            self.finished.emit(False, str(e))


class HeadSizeWorker(QThread):
    result = Signal(int, str)

    def __init__(self, items: list[tuple[int, str]], parent=None):
        super().__init__(parent)
        self._items = items
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        for row, url in self._items:
            if self._cancel: break
            try:
                req = urllib.request.Request(url, method="HEAD",
                    headers={"User-Agent": "Mozilla/5.0"})
                resp = urllib.request.urlopen(req, timeout=4)
                size = int(resp.headers.get("content-length", 0))
                size_text = f"{size/1024/1024:.1f} MB"
            except (urllib.error.URLError, socket.timeout, ValueError, OSError):
                size_text = "—"
            self.result.emit(row, size_text)
