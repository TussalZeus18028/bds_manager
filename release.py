#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BDS Manager Fluent — 发布脚本

用法:
    python release.py --notes "..."                  # 命令行 changelog
    python release.py --notes-file CHANGES.md        # 从文件读
    python release.py                                # 交互（多行 Ctrl+D 结束）
    echo "更新说明" | python release.py              # 从 stdin 读（支持多行）
    python release.py --dry-run                      # 真正 dry（只打包，不写盘）
    python release.py --skip-build                   # 用已有 zip 重传
    python release.py --skip-push                    # 不 git push（只创建 Release）
    python release.py --no-upload                    # 只创建/更新 release（不传 zip）
    python release.py --no-confirm                   # 跳过交互确认

流程:
    1. 校验：git 干净、tag 未冲突
    2. 打包（除非 --skip-build）
    3. 写 version.json（除非 --dry-run）
    4. 提交 + git push
    5. git push tag
    6. 创建/更新 GitHub Release（API）
    7. 上传 zip asset

v3.01.01 改进:
    - 改 argparse 替代 sys.argv 解析
    - 多行 changelog 支持（--notes / --notes-file / stdin.read() / 交互多行）
    - --dry-run 真正不写任何文件（之前也会 commit+push）
    - 用 git push origin <tag> 代替 API 创建 tag（更可靠）
    - 自动检测 release 是否已存在，存在则 PATCH 更新
    - 上传 asset 前先删同名旧 asset
    - 校验更严：tag 冲突、main 同步
    - 从 main.py 读版本（不 import 整个 main 模块，避免 PySide6 依赖）
"""
import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
os.chdir(SCRIPT_DIR)

# ── 版本（从 main.py 顶部正则提取，不 import 整个模块避免 PySide6 依赖） ──
def get_version() -> str:
    main_py = SCRIPT_DIR / "main.py"
    if not main_py.exists():
        return "unknown"
    text = main_py.read_text(encoding="utf-8")
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    return m.group(1) if m else "unknown"

VERSION = get_version()

# ── GitHub 仓库 ──
OWNER = "TussalZeus18028"
REPO = "bds_manager"
TAG = f"v{VERSION}"

# ── 打包排除 ──
SKIP_DIRS = {"__pycache__", ".git", "logs", "backups", ".workbuddy", "archives", "dist"}
SKIP_FILES = {
    "bds_manager_config.json", "bds_version_cache.json",
    ".gitignore", "release.py", "version.json",
}
SKIP_SUFFIX = (".pyc", ".zip", ".bak_")

# ── 终端输出辅助 ──
def info(msg):  print(f"  {msg}")
def ok(msg):    print(f"  ✅ {msg}")
def warn(msg):  print(f"  ⚠️  {msg}")
def err(msg):   print(f"  ❌ {msg}")
def step(msg):  print(f"\n▶ {msg}")


# ── 工具 ──
def run(cmd, **kw):
    """subprocess.run 包装。"""
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


# ── 校验 ──
def check_clean_workspace() -> bool:
    """检查工作区干净（无未提交改动）。"""
    r = run(["git", "status", "--porcelain"])
    if r.stdout.strip():
        err("工作区不干净，请先提交所有更改:")
        print(r.stdout)
        return False
    return True


def check_tag_not_exists() -> bool:
    """检查远端没有同名 tag。"""
    r = run(["git", "ls-remote", "--tags", "origin", TAG])
    if r.stdout.strip():
        err(f"Tag {TAG} 已在远端存在，请勿重复发布")
        info("如需重新发布相同版本，请先删除远端 tag:")
        info(f"  git push origin :refs/tags/{TAG}")
        return False
    return True


def check_main_up_to_date() -> bool:
    """检查本地 main 与 origin/main 同步。"""
    run(["git", "fetch", "origin", "main"])
    r = run(["git", "rev-list", "--count", "HEAD..origin/main"])
    behind = r.stdout.strip()
    if behind and behind != "0":
        warn(f"本地 main 落后 origin/main {behind} 个 commit，建议先 git pull")
        return False
    return True


# ── 打包 ──
def build_zip(output_path: Path) -> tuple[Path, str, int, list]:
    """打包项目到 output_path，返回 (path, sha256, size, file_list)。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    files = []
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, fs in os.walk("."):
            # 排序 + 过滤目录
            dirs[:] = sorted(d for d in dirs
                            if d not in SKIP_DIRS and not d.startswith("."))
            for fn in fs:
                if fn in SKIP_FILES or fn.startswith("."):
                    continue
                if any(fn.endswith(s) for s in SKIP_SUFFIX):
                    continue
                if fn.endswith(".zip"):
                    continue
                fp = Path(root) / fn
                arc = fp.as_posix().lstrip("./")
                zf.write(fp, arc)
                files.append(arc)

    sha = hashlib.sha256()
    with open(output_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha.update(chunk)
    size = output_path.stat().st_size
    return output_path, sha.hexdigest(), size, files


def calc_zip_hash(zip_path: Path) -> tuple[str, int]:
    """从已有 zip 文件计算 SHA256 + size。"""
    sha = hashlib.sha256()
    with open(zip_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest(), zip_path.stat().st_size


# ── version.json ──
def write_version_json(sha256: str, size: int, changelog: str):
    """覆盖写入 version.json。"""
    data = {
        "version": VERSION,
        "release_date": time.strftime("%Y-%m-%d"),
        "download_url": f"https://github.com/{OWNER}/{REPO}/releases/download/{TAG}/bds_manager_v{VERSION}.zip",
        "sha256": sha256,
        "file_size": size,
        "min_compatible_version": VERSION,
        "changelog": changelog,
    }
    with open("version.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


# ── Git ──
def git_commit_and_push(message: str, files: list[str]):
    """提交指定文件 + 推送。"""
    run(["git", "add"] + files, check=True)
    # 检查是否有 staged 内容
    r = run(["git", "diff", "--cached", "--stat"])
    if not r.stdout.strip():
        info(f"无 {files} 变更，跳过 commit")
    else:
        run(["git", "commit", "-m", message], check=True)
    run(["git", "push", "origin", "main"], check=True)


def git_push_tag():
    """推送 tag 到远端。"""
    r = run(["git", "push", "origin", TAG])
    if r.returncode != 0:
        # tag 已存在不算错（幂等）
        stderr = r.stderr or ""
        if "already exists" in stderr or "already up-to-date" in stderr:
            info(f"Tag {TAG} 已存在或已是最新")
            return
        err(f"推送 tag 失败: {stderr}")
        raise RuntimeError("git push tag failed")


# ── GitHub API ──
def get_github_token() -> str | None:
    """从 bds_manager_config.json 读 obfuscated token 并解码。"""
    cfg = SCRIPT_DIR / "bds_manager_config.json"
    if not cfg.exists():
        return None
    try:
        c = json.loads(cfg.read_text(encoding="utf-8"))
        obf = c.get("github_token", "")
        if not obf:
            return None
        data = base64.urlsafe_b64decode(obf.encode())
        KEY = b"bds_manager_2026_token_obfuscation_key"
        key = (KEY * (len(data) // len(KEY) + 1))[:len(data)]
        return bytes(a ^ b for a, b in zip(data, key)).decode("utf-8")
    except Exception as e:
        warn(f"解码 token 失败: {e}")
        return None


def gh_headers(token: str) -> dict:
    return {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}


def gh_api(method: str, path: str, token: str, **kw):
    import requests
    api = f"https://api.github.com/repos/{OWNER}/{REPO}{path}"
    return requests.request(method, api, headers=gh_headers(token), timeout=30, **kw)


def find_release_by_tag(token: str) -> dict | None:
    """用 tag 找 release（不依赖 /releases/tags 端点）。"""
    r = gh_api("GET", "/releases?per_page=100", token)
    if r.status_code != 200:
        warn(f"获取 release 列表失败: {r.status_code}")
        return None
    for rel in r.json():
        if rel["tag_name"] == TAG:
            return rel
    return None


def create_or_update_release(token: str, changelog: str) -> dict:
    """创建或更新 GitHub Release。"""
    existing = find_release_by_tag(token)
    payload = {
        "name": f"BDS Manager Fluent v{VERSION}",
        "body": changelog,
        "draft": False,
        "prerelease": False,
    }
    if existing:
        info(f"Release 已存在 (id={existing['id']})，PATCH 更新")
        r = gh_api("PATCH", f"/releases/{existing['id']}", token, json=payload)
        if r.status_code != 200:
            err(f"更新 release 失败 ({r.status_code}): {r.text[:200]}")
            raise RuntimeError("release update failed")
        ok(f"Release 已更新 (id={r.json()['id']})")
        return r.json()
    else:
        payload["tag_name"] = TAG
        r = gh_api("POST", "/releases", token, json=payload)
        if r.status_code != 201:
            err(f"创建 release 失败 ({r.status_code}): {r.text[:200]}")
            raise RuntimeError("release create failed")
        ok(f"Release 已创建 (id={r.json()['id']})")
        return r.json()


def upload_asset(token: str, release: dict, zip_path: Path):
    """上传 zip 到 release（同名旧 asset 先删）。"""
    asset_name = zip_path.name
    # 删同名旧 asset
    for asset in release.get("assets", []):
        if asset["name"] == asset_name:
            r = gh_api("DELETE", f"/releases/assets/{asset['id']}", token)
            if r.status_code in (204, 404):
                info(f"已删除旧 asset: {asset_name}")
            else:
                warn(f"删旧 asset 失败 ({r.status_code})，继续上传")

    upload_url = release["upload_url"].split("{")[0]
    with open(zip_path, "rb") as f:
        r = requests.post(
            f"{upload_url}?name={asset_name}",
            headers={**gh_headers(token), "Content-Type": "application/zip"},
            data=f,
            timeout=120,
        )
    if r.status_code == 201:
        ok(f"上传成功: {r.json()['browser_download_url']}")
    else:
        err(f"上传失败 ({r.status_code}): {r.text[:200]}")
        raise RuntimeError("asset upload failed")


# ── 主流程 ──
def main() -> int:
    parser = argparse.ArgumentParser(
        description="BDS Manager Fluent 发布脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--notes", help="changelog 文本（命令行直接传）")
    g.add_argument("--notes-file", help="changelog 文件路径（从文件读）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打包，不修改任何文件（不写 version.json / 不 commit / 不 push / 不创建 release）")
    parser.add_argument("--no-confirm", action="store_true",
                        help="跳过所有交互确认（CI/自动化用）")
    parser.add_argument("--skip-build", action="store_true",
                        help="跳过打包，使用 dist/ 已有 zip（重传场景）")
    parser.add_argument("--skip-push", action="store_true",
                        help="不 git push（只创建 GitHub Release）")
    parser.add_argument("--no-upload", action="store_true",
                        help="不重新上传 zip（只创建/更新 release metadata）")
    args = parser.parse_args()

    print("╔══════════════════════════════════╗")
    print("║  BDS Manager Fluent  发布脚本     ║")
    print(f"║  版本: v{VERSION:<25} ║")
    print("╚══════════════════════════════════╝")

    # 1. 获取 changelog
    changelog = ""
    if args.notes:
        changelog = args.notes.strip()
    elif args.notes_file:
        nf = Path(args.notes_file)
        if not nf.exists():
            err(f"找不到 notes 文件: {nf}")
            return 1
        changelog = nf.read_text(encoding="utf-8").strip()
    elif not sys.stdin.isatty():
        # 非交互模式：从 stdin 读多行（支持 heredoc / pipe）
        try:
            changelog = sys.stdin.read().strip()
        except (EOFError, KeyboardInterrupt):
            pass
    else:
        # 交互模式：提示用户多行输入
        print("\n📝 输入更新说明（多行，Ctrl+D 或 Ctrl+Z 结束）:")
        try:
            changelog = sys.stdin.read().strip()
        except (EOFError, KeyboardInterrupt):
            changelog = ""
    if not changelog:
        changelog = f"BDS Manager Fluent v{VERSION}"
    preview = changelog.splitlines()[0] if changelog else "(empty)"
    info(f"Changelog ({len(changelog)} chars): {preview[:60]}{'...' if len(preview) > 60 else ''}")

    # 2. 校验
    step("校验环境...")
    if args.dry_run:
        ok("dry-run 模式：跳过所有写操作")
    else:
        if not check_clean_workspace():
            return 1
        if not check_tag_not_exists():
            return 1

    # 3. 打包
    zip_path = SCRIPT_DIR / f"dist/bds_manager_v{VERSION}.zip"
    if args.skip_build and zip_path.exists():
        step(f"使用已有 zip...")
        sha, size = calc_zip_hash(zip_path)
        info(f"路径: {zip_path}")
        info(f"大小: {size:,} 字节")
        info(f"SHA256: {sha}")
    else:
        step("打包项目...")
        zip_path, sha, size, files = build_zip(zip_path)
        ok(f"打包完成: {len(files)} 个文件，{size:,} 字节")
        info(f"SHA256: {sha}")
        info(f"路径: {zip_path}")

    if args.dry_run:
        ok(f"\n🎯 dry-run 完成（无任何写操作）")
        info(f"zip 预览: {zip_path}")
        return 0

    # 4. 写 version.json
    step("更新 version.json...")
    write_version_json(sha, size, changelog)
    ok("version.json 已写入")

    # 5. 提交 + git push
    if not args.skip_push:
        step("提交并 git push...")
        msg = f"发布 v{VERSION}: {changelog.splitlines()[0][:60]}"
        git_commit_and_push(msg, ["version.json"])
        ok("main 已推送")
    else:
        warn("跳过 git push（--skip-push）")

    # 6. 推送 tag
    step("推送 tag...")
    git_push_tag()
    ok(f"tag {TAG} 已推送")

    # 7. 创建/更新 Release
    step("创建/更新 GitHub Release...")
    token = get_github_token()
    if not token:
        err("未找到 GitHub Token，请先在 bds_manager_config.json 配置 github_token")
        info("或安装 gh CLI 并运行 gh auth login")
        return 1
    rel = create_or_update_release(token, changelog)
    info(f"Release URL: {rel['html_url']}")

    # 8. 上传 zip
    if not args.no_upload:
        step("上传 zip asset...")
        upload_asset(token, rel, zip_path)
    else:
        warn("跳过 asset 上传（--no-upload）")

    print("\n🎉 发布完成！")
    print(f"  Release: {rel['html_url']}")
    print(f"  Tag:     {TAG}")
    print(f"  Zip:     {zip_path}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n⚠️  已取消")
        sys.exit(1)
    except Exception as e:
        err(f"发布失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
