#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bds_manager.py — 伪装为旧版入口名的智能更新 + 启动脚本

⚠️ 重要：这不是 Manager_Fluent 项目的主入口。
   - 主入口是 main.py（run.bat 调用）
   - 这个文件叫 bds_manager.py 是为了「伪装」

用途说明
========

旧版 Manager/ 的 _restart_app 写死：

    subprocess.Popen([sys.executable, os.path.join(SCRIPT_DIR, "bds_manager.py")])

也就是说，当旧版启动「自动升级」后，subprocess.Popen 启动的总是 bds_manager.py。
如果 zip 包里有 bds_manager.py，就会被解压覆盖——那么旧版重启后调用的就是
**新版的 bds_manager.py**（也就是本文件）。

本脚本做了三件事：
  1. 调用 GitHub API 检查 version.json，比较本地与远端版本
  2. 如果有更新：下载 zip → 校验 SHA256 → 解压覆盖（跳过用户配置）
  3. 启动真正的 BDS Manager Fluent 主程序 main.py

这样旧版本"自动升级"后，无论它启动的是什么进程，最终都跑到新版 UI。
本文件可独立运行（不需要 PySide6），因此即使主程序缺失也能下载/解压。

压缩包规则
==========
- release.py 在打包时应包含本文件（命名为 bds_manager.py）
- 不要在压缩包里再放一个 main.py stub
- bds_manager.py 应在压缩包顶层（不是 pages/ 或 backend/ 子目录）
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile

# ── 常量 ──────────────────────────────────────────────────────────────
GITHUB_REPO_OWNER = "TussalZeus18028"
GITHUB_REPO_NAME = "bds_manager"
GITHUB_REPO_BRANCH = "main"
USER_AGENT = "BDS-Manager-AutoUpdater/3.0"

# 跳过用户配置和已知会冲突的目录
SKIP_FILES = {
    "bds_manager.py",  # 自身（避免嵌套重写）
    "bds_manager_config.json",
    "bds_version_cache.json",
    "run.bat",         # 旧版 run.bat 是「python bds_manager.py」，避免被覆盖回来
}
SKIP_DIRS = {
    "logs", "backups", "Server", "Earlier version", ".git", "__pycache__",
    "web_ui", "tests",  # 旧版子目录，丢弃
    "release",  # 旧版 release 工具目录
    ".workbuddy",
}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


# ── 工具函数 ──────────────────────────────────────────────────────────
def log(msg: str) -> None:
    """带前缀的日志（输出到 stderr，避免被子进程捕获为 stdout）。"""
    print(f"[bds_manager-stub {time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def parse_version_tuple(v: str) -> tuple:
    """版本号字符串 → tuple（用于比较），空段补 0。"""
    parts = []
    for p in v.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def get_local_version() -> tuple:
    """从 main.py 读 __version__，main.py 不存在则返回 (0,)。"""
    main_py = os.path.join(SCRIPT_DIR, "main.py")
    if not os.path.exists(main_py):
        return (0,)
    try:
        import re
        text = open(main_py, encoding="utf-8").read()
        m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
        if not m:
            return (0,)
        return parse_version_tuple(m.group(1))
    except OSError:
        return (0,)


# ── GitHub API ────────────────────────────────────────────────────────
def fetch_remote_version_json(max_attempts: int = 3) -> dict | None:
    """从 GitHub API 拉 version.json（重试 + 指数退避）。"""
    url = (
        f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}"
        f"/contents/version.json?ref={GITHUB_REPO_BRANCH}"
    )
    delay = 1.0
    for attempt in range(1, max_attempts + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=10) as resp:
                api_data = json.loads(resp.read().decode("utf-8"))
                return json.loads(base64.b64decode(api_data["content"]).decode("utf-8"))
        except Exception as e:
            log(f"  GitHub 拉取失败（{attempt}/{max_attempts}）: {e}")
            if attempt < max_attempts:
                time.sleep(delay)
                delay *= 2
    return None


# ── 下载 + 校验 ───────────────────────────────────────────────────────
def download_zip(remote_ver: str, dl_url: str, expected_sha: str) -> str | None:
    """下载 zip 到 _update_v<ver>.zip，校验 SHA256，返回路径或 None。"""
    zip_path = os.path.join(SCRIPT_DIR, f"_update_v{remote_ver}.zip")
    try:
        log(f"⬇️  下载: {dl_url[:80]}...")
        req = urllib.request.Request(dl_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as resp:
            with open(zip_path, "wb") as f:
                shutil.copyfileobj(resp, f)
        # SHA256 校验
        if expected_sha:
            h = hashlib.sha256()
            with open(zip_path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            actual = h.hexdigest()
            if actual.lower() != expected_sha.lower():
                log(f"  ❌ SHA256 不匹配（期望 {expected_sha[:16]}... 实际 {actual[:16]}...）")
                try:
                    os.remove(zip_path)
                except OSError:
                    pass
                return None
            log(f"  ✅ SHA256 校验通过")
        return zip_path
    except Exception as e:
        log(f"  ❌ 下载失败: {e}")
        try:
            os.remove(zip_path)
        except OSError:
            pass
        return None


# ── 解压 ──────────────────────────────────────────────────────────────
def common_top_dir(names: list[str]) -> str:
    """探测 zip 是否有公共顶层目录。"""
    tops = set()
    for n in names:
        parts = n.replace("\\", "/").split("/")
        if len(parts) > 1 and parts[0]:
            tops.add(parts[0])
    return list(tops)[0] + "/" if len(tops) == 1 else ""


def extract_zip(zip_path: str) -> bool:
    """解压 zip 到 SCRIPT_DIR，跳过用户配置和冲突目录。"""
    try:
        log(f"📦 解压: {os.path.basename(zip_path)}")
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            top = common_top_dir(names)
            for name in names:
                if name.endswith("/") or name.endswith("\\"):
                    continue
                rel = name[len(top):] if top and name.startswith(top) else name
                rel = rel.lstrip("/\\")
                if not rel:
                    continue
                parts = rel.replace("\\", "/").split("/")
                if not parts or parts[-1] in ("", ".", "..") or ".." in parts:
                    continue
                if parts[-1] in SKIP_FILES:
                    continue
                if parts[0] in SKIP_DIRS:
                    continue
                target = os.path.join(SCRIPT_DIR, *parts)
                real = os.path.realpath(target)
                # ZipSlip 防护
                if not real.startswith(os.path.realpath(SCRIPT_DIR)):
                    log(f"  跳过越权路径: {name}")
                    continue
                os.makedirs(os.path.dirname(target) or SCRIPT_DIR, exist_ok=True)
                with zf.open(name) as src, open(target, "wb") as dst:
                    dst.write(src.read())
        try:
            os.remove(zip_path)
        except OSError:
            pass
        log("  ✅ 解压完成")
        return True
    except Exception as e:
        log(f"  ❌ 解压失败: {e}")
        return False


# ── 启动主程序 ────────────────────────────────────────────────────────
def launch_main_py() -> None:
    """detached 启动 main.py（让 bds_manager.py 退出不影响 main.py）。"""
    main_py = os.path.join(SCRIPT_DIR, "main.py")
    if not os.path.exists(main_py):
        log(f"  ❌ main.py 不存在: {main_py}")
        log(f"  请手动从 https://github.com/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/releases 下载完整 zip 解压")
        sys.exit(1)
    log(f"🚀 启动主程序: main.py")
    if sys.platform == "win32":
        # DETACHED_PROCESS = 0x00000008，让 main.py 完全独立（关闭 bds_manager.py 也不退出）
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        subprocess.Popen(
            [sys.executable, main_py],
            cwd=SCRIPT_DIR,
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
    else:
        subprocess.Popen(
            [sys.executable, main_py],
            cwd=SCRIPT_DIR,
            start_new_session=True,
            close_fds=True,
        )


# ── 主流程 ────────────────────────────────────────────────────────────
def auto_update_then_launch() -> int:
    """1) 自动检查更新  2) 启动 main.py。返回 main.py 进程退出码。"""
    local = get_local_version()
    log(f"本地版本: {'.'.join(map(str, local)) or '(无 main.py)'}")

    # 1. 检查更新
    try:
        data = fetch_remote_version_json()
        if not data:
            log("⚠️ 无法获取远端版本，跳过更新（直接启动主程序）")
        else:
            remote_ver = data.get("version", "")
            remote = parse_version_tuple(remote_ver)
            if not remote_ver or remote <= local:
                log(f"✅ 已是最新（远端 {'.'.join(map(str, remote)) or remote_ver}）")
            else:
                log(f"📥 发现新版本: {'.'.join(map(str, remote))}（当前 {'.'.join(map(str, local))}）")
                dl_url = data.get("download_url", "")
                sha256 = data.get("sha256", "")
                if not dl_url:
                    log("  ⚠️ version.json 缺少 download_url，跳过")
                else:
                    zip_path = download_zip(remote_ver, dl_url, sha256)
                    if zip_path and extract_zip(zip_path):
                        log("🎉 自动更新完成")
    except Exception as e:
        log(f"⚠️ 更新检查出错（不影响启动）: {e}")

    # 2. 启动主程序
    launch_main_py()
    return 0


if __name__ == "__main__":
    sys.exit(auto_update_then_launch())
