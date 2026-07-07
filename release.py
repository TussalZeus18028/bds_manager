#!/usr/bin/env python3
"""
BDS Manager 发布工具（二合一）
用法:
  python release.py build    打包 → SHA256 → 写入 version.json
  python release.py publish  推送 → 创建 GitHub Release
  python release.py all      一键: build + publish
  python release.py          显示此帮助
"""

import os
import sys
import json
import hashlib
import zipfile
import subprocess
import shutil
import webbrowser
from pathlib import Path

# ---------- 配置 ----------
SCRIPT_DIR = Path(__file__).resolve().parent
VERSION_JSON = SCRIPT_DIR / "version.json"
RELEASE_DIR = SCRIPT_DIR / "release"
GH_EXE = shutil.which("gh") or r"C:\Program Files\GitHub CLI\gh.exe"

# 打包排除
INCLUDE_PATTERNS = [".py", ".txt", ".md", ".json", ".bat"]
EXCLUDE_FILES = {"bds_manager_config.json", "bds_version_cache.json", "release.py", "run.bat", "README.md", "release_gui.py"}
EXCLUDE_DIRS = {"logs", "backups", "Server", "Earlier version", "release",
                ".git", "__pycache__", "web_ui", ".workbuddy"}

GITHUB_REPO = "TussalZeus18028/bds_manager"

# ---------- 输出 ----------
class C:
    GREEN = "\033[92m"; YELLOW = "\033[93m"; RED = "\033[91m"
    BLUE = "\033[94m"; RESET = "\033[0m"

def _log(c, tag, msg): print(f"{c}[{tag}]{C.RESET} {msg}")
def log_info(msg): _log(C.BLUE, "INFO", msg)
def log_ok(msg):   _log(C.GREEN, " OK ", msg)
def log_warn(msg): _log(C.YELLOW, "WARN", msg)
def log_err(msg):  _log(C.RED, "ERR ", msg)

def _banner(title):
    print(f"\n{C.BLUE}{'='*40}{C.RESET}")
    print(f"  {title}")
    print(f"{C.BLUE}{'='*40}{C.RESET}\n")

# ---------- 版本号 ----------
def get_version():
    if not VERSION_JSON.exists():
        log_err(f"找不到 {VERSION_JSON}"); sys.exit(1)
    with open(VERSION_JSON, "r", encoding="utf-8") as f:
        return json.load(f)["version"]

# ---------- 子命令: build ----------
def cmd_build():
    _banner("步骤: 打包构建")
    meta = json.loads(VERSION_JSON.read_text(encoding="utf-8"))
    ver = meta.get("version", "0.0.0.0")
    log_info(f"版本: v{ver}")

    RELEASE_DIR.mkdir(exist_ok=True)
    zip_name = f"bds_manager_v{ver}.zip"
    zip_path = RELEASE_DIR / zip_name

    # 打包
    log_info(f"打包 → {zip_name}")
    count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(SCRIPT_DIR):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith(".")]
            for f in files:
                if f in EXCLUDE_FILES:
                    continue
                if not any(f.endswith(ext) for ext in INCLUDE_PATTERNS):
                    continue
                full = os.path.join(root, f)
                arc = os.path.relpath(full, SCRIPT_DIR)
                zf.write(full, arc)
                count += 1
    log_ok(f"{count} 个文件已打包")

    # SHA256
    log_info("计算 SHA256...")
    h = hashlib.sha256()
    with open(zip_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    sha = h.hexdigest()
    size = os.path.getsize(zip_path)
    log_ok(f"SHA256: {sha}")
    log_ok(f"大小:   {size:,} bytes ({size/1024:.1f} KB)")

    # 写入 version.json
    meta["sha256"] = sha
    meta["file_size"] = size
    meta["download_url"] = f"https://github.com/{GITHUB_REPO}/releases/download/v{ver}/{zip_name}"

    for target in [VERSION_JSON, RELEASE_DIR / "version.json"]:
        target.write_text(json.dumps(meta, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
        log_ok(f"{target.name} 已更新")

    # 清单
    print(f"\n{C.GREEN}[DONE]{C.RESET} release/ 目录:")
    for item in sorted(RELEASE_DIR.iterdir()):
        print(f"  {item.name}  ({item.stat().st_size:,} bytes)")

# ---------- 子命令: publish ----------
def _run(cmd, capture=False):
    log_info(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=capture, text=True, cwd=str(SCRIPT_DIR))
    rc = result.returncode
    if capture and rc != 0 and result.stderr:
        log_err(result.stderr.strip())
    return rc, result.stdout.strip(), result.stderr.strip()

def cmd_publish():
    _banner("步骤: 发布到 GitHub")
    ver = get_version()
    log_ok(f"版本: v{ver}")

    # 1. 检查 gh
    if not os.path.isfile(GH_EXE):
        log_err(f"未找到 gh ({GH_EXE})"); log_info("安装: winget install GitHub.cli"); sys.exit(1)
    log_ok(f"gh: {GH_EXE}")

    # 2. 检查 ZIP
    zip_path = RELEASE_DIR / f"bds_manager_v{ver}.zip"
    if not zip_path.exists():
        log_err(f"找不到 {zip_path}"); log_info("请先运行: python release.py build"); sys.exit(1)
    log_ok(f"ZIP: {zip_path.name}")

    # 3. 推送
    log_info("推送代码...")
    rc, branch, _ = _run(["git", "branch", "--show-current"], capture=True)
    if rc != 0:
        log_err("不在 Git 仓库中"); sys.exit(1)
    log_info(f"分支: {branch}")
    rc, _, _ = _run(["git", "push", "origin", branch], capture=True)
    if rc != 0:
        log_err("推送失败"); sys.exit(1)
    log_ok("推送成功")

    # 4. gh 认证（仅检查，不阻塞——Git 凭据已够用）
    rc, out, _ = _run([GH_EXE, "auth", "status"], capture=True)
    if rc != 0:
        log_warn("gh 未登录，将使用 git 凭据直接创建 Release（若失败请手动 gh auth login）")

    # 5. 创建 Release
    tag = f"v{ver}"
    notes = RELEASE_DIR / "version.json"
    cmd = [GH_EXE, "release", "create", tag, str(zip_path), "--title", tag]
    if notes.exists():
        cmd += ["--notes-file", str(notes)]
    rc, _, _ = _run(cmd)
    if rc != 0:
        log_err("Release 创建失败"); sys.exit(1)
    log_ok(f"Release {tag} 创建成功")

    # 6. 打开页面
    url = f"https://github.com/{GITHUB_REPO}/releases/tag/{tag}"
    log_info(url)
    webbrowser.open(url)

    _banner("发布完成")

# ---------- 入口 ----------
def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "build":
        cmd_build()
    elif cmd == "publish":
        cmd_publish()
    elif cmd == "all":
        cmd_build()
        cmd_publish()
    else:
        print(__doc__)
        print("当前子命令: build | publish | all")

if __name__ == "__main__":
    main()
