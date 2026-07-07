#!/usr/bin/env python3
"""
BDS Manager 自动发布脚本
- 从 version.json 读取版本号
- 推送代码到 GitHub
- 检查并登录 GitHub CLI
- 创建 GitHub Release 并上传 ZIP 包
"""

import os
import sys
import json
import subprocess
import shutil
import webbrowser
from pathlib import Path

# ---------- 配置 ----------
SCRIPT_DIR = Path(__file__).resolve().parent
VERSION_JSON = SCRIPT_DIR / "version.json"
RELEASE_DIR = SCRIPT_DIR / "release"
GH_EXE = shutil.which("gh") or r"C:\Program Files\GitHub CLI\gh.exe"

# ---------- 颜色输出 ----------
class Colors:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    RESET = "\033[0m"

def log_info(msg):
    print(f"{Colors.BLUE}[INFO]{Colors.RESET} {msg}")

def log_ok(msg):
    print(f"{Colors.GREEN}[ OK ]{Colors.RESET} {msg}")

def log_warn(msg):
    print(f"{Colors.YELLOW}[WARN]{Colors.RESET} {msg}")

def log_error(msg):
    print(f"{Colors.RED}[ERR ]{Colors.RESET} {msg}")

# ---------- 核心功能 ----------
def get_version():
    """从 version.json 读取版本号"""
    if not VERSION_JSON.exists():
        log_error(f"找不到 version.json: {VERSION_JSON}")
        sys.exit(1)
    try:
        with open(VERSION_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        ver = data.get("version")
        if not ver:
            log_error("version.json 中缺少 'version' 字段")
            sys.exit(1)
        return ver
    except (json.JSONDecodeError, OSError) as e:
        log_error(f"读取 version.json 失败: {e}")
        sys.exit(1)

def run_cmd(cmd, check=True, capture=False):
    """执行命令，返回 (returncode, stdout, stderr)"""
    log_info(f"执行: {' '.join(cmd)}")
    try:
        if capture:
            result = subprocess.run(
                cmd, check=check, capture_output=True, text=True, cwd=str(SCRIPT_DIR)
            )
            return result.returncode, result.stdout.strip(), result.stderr.strip()
        else:
            result = subprocess.run(cmd, check=check, cwd=str(SCRIPT_DIR))
            return result.returncode, "", ""
    except subprocess.CalledProcessError as e:
        log_error(f"命令执行失败 (返回码 {e.returncode})")
        if e.stdout:
            print(e.stdout)
        if e.stderr:
            print(e.stderr)
        if check:
            sys.exit(e.returncode)
        return e.returncode, "", ""

def check_gh_exists():
    """检查 gh 是否可用"""
    if os.path.isfile(GH_EXE):
        log_ok(f"找到 gh: {GH_EXE}")
        return GH_EXE
    log_error(f"未找到 GitHub CLI ({GH_EXE})，请安装并添加到 PATH")
    log_info("下载: https://cli.github.com/")
    sys.exit(1)

def git_push():
    """推送当前分支到 origin"""
    log_info("推送代码到 GitHub...")
    ret, branch, _ = run_cmd(["git", "branch", "--show-current"], capture=True, check=False)
    if ret != 0:
        log_error("无法获取当前 Git 分支，请确保在 Git 仓库中")
        sys.exit(1)
    branch = branch.strip()
    log_info(f"当前分支: {branch}")
    ret, _, err = run_cmd(["git", "push", "origin", branch], capture=True, check=False)
    if ret != 0:
        log_error(f"推送失败: {err}")
        sys.exit(1)
    log_ok("推送成功")

def gh_auth_status(gh_path):
    """检查 gh 认证状态"""
    ret, out, _ = run_cmd([gh_path, "auth", "status"], capture=True, check=False)
    if ret == 0:
        log_ok(f"已登录 GitHub: {out}")
        return True
    log_warn("未登录 GitHub CLI，需要登录")
    return False

def gh_login(gh_path):
    """执行 gh auth login"""
    log_info("启动 GitHub CLI 登录流程...")
    ret = run_cmd([gh_path, "auth", "login", "--web", "--hostname", "github.com"], check=False)[0]
    if ret != 0:
        log_error("登录失败，请手动运行 'gh auth login' 后重试")
        sys.exit(1)
    log_ok("登录成功")

def check_zip_exists(version):
    """检查 ZIP 包是否存在"""
    zip_name = f"bds_manager_v{version}.zip"
    zip_path = RELEASE_DIR / zip_name
    if not zip_path.exists():
        log_error(f"找不到 ZIP 包: {zip_path}")
        log_info("请先运行 python build_release.py 打包")
        sys.exit(1)
    log_ok(f"找到 ZIP 包: {zip_path}")
    return zip_path

def create_release(gh_path, version, zip_path):
    """创建 GitHub Release"""
    tag = f"v{version}"
    title = f"v{version}"
    notes_file = RELEASE_DIR / "version.json"
    notes_arg = ["--notes-file", str(notes_file)] if notes_file.exists() else []

    cmd = [
        gh_path, "release", "create", tag,
        str(zip_path),
        "--title", title,
        *notes_arg
    ]
    log_info(f"创建 Release: {tag}")
    ret = run_cmd(cmd, check=False)[0]
    if ret != 0:
        log_error("Release 创建失败，请检查输出")
        sys.exit(1)
    log_ok(f"Release {tag} 创建成功")

def open_release_page(version):
    """在浏览器中打开 Release 页面"""
    url = f"https://github.com/TussalZeus18028/bds_manager/releases/tag/v{version}"
    log_info(f"打开: {url}")
    webbrowser.open(url)

def main():
    print("=" * 40)
    print("  BDS Manager 发布脚本")
    print("=" * 40)
    print()

    # 1. 获取版本号
    version = get_version()
    log_ok(f"版本号: v{version}")

    # 2. 检查 gh 是否存在
    gh_path = check_gh_exists()

    # 3. 推送代码
    git_push()

    # 4. 检查认证
    if not gh_auth_status(gh_path):
        gh_login(gh_path)

    # 5. 检查 ZIP 包
    zip_path = check_zip_exists(version)

    # 6. 创建 Release
    create_release(gh_path, version, zip_path)

    # 7. 打开 Release 页面
    open_release_page(version)

    print()
    log_ok("发布流程完成！")
    print(f"访问: https://github.com/TussalZeus18028/bds_manager/releases/tag/v{version}")

if __name__ == "__main__":
    main()
