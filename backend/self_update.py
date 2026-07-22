# -*- coding: utf-8 -*-
"""
工具自更新模块 —— 从 GitHub 获取 version.json，下载、校验、安装、重启。
"""

import os, sys, json, shutil, zipfile, base64, hashlib, subprocess
import urllib.request, urllib.error
import logging

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication

from shared.config import config_mgr, SCRIPT_DIR
from shared.toast import toast_success, toast_error, toast_warning

logger = logging.getLogger("bds_manager")

# GitHub 仓库信息（对齐旧版）
GITHUB_REPO_OWNER = "TussalZeus18028"
GITHUB_REPO_NAME = "bds_manager"
GITHUB_REPO_BRANCH = "main"


# ── Token 辅助 ──
_TOKEN_XOR_KEY = b"bds_manager_2026_token_obfuscation_key"

def _deobfuscate_token(obfuscated: str) -> str:
    try:
        data = base64.urlsafe_b64decode(obfuscated.encode())
        key = (_TOKEN_XOR_KEY * (len(data) // len(_TOKEN_XOR_KEY) + 1))[:len(data)]
        return bytes(a ^ b for a, b in zip(data, key)).decode("utf-8")
    except Exception:
        return ""


def _github_headers():
    headers = {"User-Agent": "BDS-Manager/3.0", "Accept": "application/vnd.github.v3+json"}
    if config_mgr.get("github_auth_enabled"):
        token = config_mgr.get("github_token") or ""
        if token:
            # 配置中存储的是 XOR+base64 混淆后的 token
            real = _deobfuscate_token(token)
            if real:
                headers["Authorization"] = f"token {real}"
    return headers


# ── 版本比较 ──
def compare_versions(a: str, b: str) -> int:
    """返回 >0 若 a > b，<0 若 a < b，0 相等。"""
    try:
        pa = [int(x) for x in a.split(".")]
        pb = [int(x) for x in b.split(".")]
    except (ValueError, AttributeError):
        return 0
    for i in range(max(len(pa), len(pb))):
        va = pa[i] if i < len(pa) else 0
        vb = pb[i] if i < len(pb) else 0
        if va != vb:
            return va - vb
    return 0


# ── 获取远程版本 ──
def fetch_remote_version_json() -> dict:
    """通过 GitHub API 获取 version.json。"""
    url = (f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}"
           f"/contents/version.json?ref={GITHUB_REPO_BRANCH}")
    req = urllib.request.Request(url, headers=_github_headers())
    with urllib.request.urlopen(req, timeout=10) as resp:
        api_data = json.loads(resp.read().decode("utf-8"))
        return json.loads(base64.b64decode(api_data["content"]).decode("utf-8"))


# ── SHA256 校验 ──
def verify_sha256(filepath: str, expected: str) -> tuple[bool, str]:
    if not expected:
        return True, "跳过校验"
    try:
        h = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        actual = h.hexdigest()
        if actual.lower() == expected.lower():
            return True, "SHA256 校验通过"
        return False, f"SHA256 不匹配（期望: {expected[:16]}... 实际: {actual[:16]}...）"
    except OSError as e:
        return False, f"读取文件失败: {e}"


def is_valid_zip(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(2) == b"PK"
    except OSError:
        return False


def common_top_dir(names: list[str]) -> str:
    top = set()
    for n in names:
        parts = n.replace("\\", "/").split("/")
        if len(parts) > 1:
            top.add(parts[0] + "/")
        elif parts and parts[0]:
            return ""  # 混合了根级文件
    return list(top)[0] if len(top) == 1 else ""


# ── 检查 Worker ──
class CheckUpdateWorker(QThread):
    result = Signal(str, str, str, str)  # status, remote_ver, dl_url, sha256

    def run(self):
        try:
            data = fetch_remote_version_json()
            remote = data.get("version", "")
            if not remote:
                self.result.emit("error", "", "", "")
                return
            import main
            if compare_versions(remote, main.__version__) > 0:
                dl = data.get("download_url", "")
                sha = data.get("sha256", "")
                self.result.emit("update", remote, dl, sha)
            else:
                self.result.emit("latest", remote, "", "")
        except Exception as e:
            from backend.network import network_error_text
            _, _, msg = network_error_text(e)
            self.result.emit("error", msg, "", "")


# ── 下载 Worker ──
class DownloadUpdateWorker(QThread):
    progress = Signal(int)
    finished = Signal(bool, str, str)  # success, msg, save_path

    def __init__(self, dl_url: str, remote_ver: str, parent=None):
        super().__init__(parent)
        self._url = dl_url
        self._ver = remote_ver

    def run(self):
        import requests
        path = os.path.join(SCRIPT_DIR, f"bds_manager_v{self._ver}.zip")
        try:
            r = requests.get(self._url, headers=_github_headers(), stream=True, timeout=60)
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            done = 0
            with open(path, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        self.progress.emit(int(done * 100 / total))
            if os.path.getsize(path) < 1000:
                self.finished.emit(False, "下载文件异常", "")
                return
            self.finished.emit(True, "下载完成", path)
        except Exception as e:
            self.finished.emit(False, str(e), "")


# ── 安装 Worker ──
class InstallUpdateWorker(QThread):
    log = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, zip_path: str, parent=None):
        super().__init__(parent)
        self._zip = zip_path

    def run(self):
        try:
            # 备份
            ts = __import__("time").strftime("%Y%m%d_%H%M%S")
            backup_dir = os.path.join(SCRIPT_DIR, "backups", f"upgrade_backup_{ts}")
            os.makedirs(backup_dir, exist_ok=True)
            self.log.emit("正在备份核心文件...")
            for f in os.listdir(SCRIPT_DIR):
                if f.endswith((".py", ".json", ".txt", ".md")) and os.path.isfile(os.path.join(SCRIPT_DIR, f)):
                    shutil.copy2(os.path.join(SCRIPT_DIR, f), os.path.join(backup_dir, f))

            # 解压
            skip_files = {"bds_manager_config.json", "bds_version_cache.json"}
            skip_dirs = {"logs", "backups", "Server", "Earlier version", ".git", "__pycache__"}
            self.log.emit("正在解压更新...")
            with zipfile.ZipFile(self._zip) as zf:
                names = zf.namelist()
                top = common_top_dir(names)
                for name in names:
                    if name.endswith("/") or name.endswith("\\"):
                        continue
                    rel = name
                    if top and name.startswith(top):
                        rel = name[len(top):]
                    rel = rel.lstrip("/\\")
                    parts = rel.replace("\\", "/").split("/")
                    if not rel or not parts:
                        continue
                    if parts[-1] in skip_files or parts[0] in skip_dirs:
                        continue
                    if parts[-1] in ("", ".", "..") or ".." in parts:
                        continue
                    target = os.path.join(SCRIPT_DIR, *parts)
                    tr = os.path.realpath(target)
                    if not tr.startswith(os.path.realpath(SCRIPT_DIR)):
                        self.log.emit(f"跳过越权路径: {name}")
                        continue
                    os.makedirs(os.path.dirname(target) or SCRIPT_DIR, exist_ok=True)
                    with zf.open(name) as src, open(target, "wb") as dst:
                        dst.write(src.read())

            try:
                os.remove(self._zip)
            except OSError:
                pass
            self.log.emit("安装完成，即将重启...")
            self.finished.emit(True, "安装完成")
        except Exception as e:
            self.log.emit(f"安装失败: {e}")
            self.finished.emit(False, str(e))


# ── 重启 ──
def restart_app(script_name: str = "main.py"):
    subprocess.Popen([sys.executable, os.path.join(SCRIPT_DIR, script_name)],
                     cwd=SCRIPT_DIR,
                     creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    QApplication.quit()
