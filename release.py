#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BDS Manager Fluent — 发布脚本

用法:
    python release.py              # 交互式发布
    python release.py --dry-run    # 仅打包，不上传

功能:
    1. 打包项目为 zip（自动排除配置文件/日志/临时文件）
    2. 计算 SHA256 + 文件大小
    3. 更新 version.json
    4. 通过 GitHub API（或 gh CLI）创建 Release 并上传 zip
"""

import os, sys, json, hashlib, zipfile, subprocess, time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(SCRIPT_DIR)

# ── 版本 ──
import main  # noqa: E402
VERSION = main.__version__

# ── GitHub 仓库信息 ──
OWNER = "TussalZeus18028"
REPO = "bds_manager"
TAG = f"v{VERSION}"

# ── 打包排除 ──
SKIP_DIRS = {"__pycache__", ".git", "logs", "backups"}
SKIP_FILES = {"bds_manager_config.json", "bds_version_cache.json", ".gitignore", "release.py"}
SKIP_SUFFIX = (".pyc", ".zip", ".bak_")


def build_zip() -> tuple[str, str, int]:
    """打包项目，返回 (zip_path, sha256, size)。"""
    output = f"dist/bds_manager_v{VERSION}.zip"
    os.makedirs("dist", exist_ok=True)

    files = []
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, fs in os.walk("."):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            for fn in fs:
                if fn in SKIP_FILES or fn.startswith(".") or any(fn.endswith(s) for s in SKIP_SUFFIX):
                    continue
                fp = os.path.join(root, fn)
                arc = fp.replace("\\", "/").lstrip("./")
                zf.write(fp, arc)
                files.append(arc)

    sha = hashlib.sha256()
    with open(output, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha.update(chunk)
    size = os.path.getsize(output)

    print(f"  📦 打包完成: {output}")
    print(f"  📏 文件数: {len(files)}")
    print(f"  📊 大小: {size:,} 字节")
    print(f"  🔑 SHA256: {sha.hexdigest()}")
    return output, sha.hexdigest(), size


def update_version_json(sha256: str, size: int, changelog: str = ""):
    """更新 version.json。"""
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
    print(f"  📋 version.json 已更新")


def create_release_gh_cli(zip_path: str, changelog: str):
    """通过 gh CLI 创建 Release。"""
    # 如果没有安装 gh，回退到 API
    if subprocess.run(["where", "gh"], capture_output=True).returncode != 0:
        return create_release_api(zip_path, changelog)

    print("  🚀 使用 gh CLI 创建 Release...")
    subprocess.run(["gh", "release", "create", TAG, zip_path,
                     "--title", f"BDS Manager Fluent v{VERSION}",
                     "--notes", changelog,
                     "--repo", f"{OWNER}/{REPO}"], check=True)
    print(f"  ✅ Release {TAG} 已发布")


def create_release_api(zip_path: str, changelog: str):
    """通过 GitHub API 创建 Release。"""
    import base64, requests

    # 读取 token
    cfg_path = "bds_manager_config.json"
    token = None
    if os.path.exists(cfg_path):
        with open(cfg_path) as f:
            cfg = json.load(f)
        obf = cfg.get("github_token", "")
        if obf:
            try:
                data = base64.urlsafe_b64decode(obf.encode())
                KEY = b"bds_manager_2026_token_obfuscation_key"
                key = (KEY * (len(data) // len(KEY) + 1))[:len(data)]
                token = bytes(a ^ b for a, b in zip(data, key)).decode("utf-8")
            except Exception:
                pass

    if not token:
        print("  ❌ 未找到 GitHub Token，请手动创建 Release 或运行 gh auth login")
        return

    H = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
    api = f"https://api.github.com/repos/{OWNER}/{REPO}"

    print("  🚀 通过 GitHub API 创建 Release...")

    # 创建 tag
    try:
        r = requests.get(f"{api}/git/refs/heads/main", headers=H, timeout=10)
        sha = r.json()["object"]["sha"]
    except Exception:
        print("  ❌ 无法获取 main 分支 SHA，请先推送代码")
        return

    r = requests.post(f"{api}/git/refs", headers=H, json={"ref": f"refs/tags/{TAG}", "sha": sha})
    if r.status_code not in (201, 422):
        print(f"  ❌ Tag 创建失败: {r.text[:200]}")
        return
    print(f"  🏷 Tag {TAG} OK")

    # 创建 release
    r = requests.post(f"{api}/releases", headers=H, json={
        "tag_name": TAG, "name": f"BDS Manager Fluent v{VERSION}",
        "body": changelog, "draft": False, "prerelease": False,
    })
    if r.status_code != 201:
        print(f"  ❌ Release 创建失败: {r.text[:200]}")
        return
    rel = r.json()
    print(f"  📦 Release id={rel['id']}")

    # 上传 zip
    upload_url = rel["upload_url"].split("{")[0]
    with open(zip_path, "rb") as f:
        r = requests.post(f"{upload_url}?name={os.path.basename(zip_path)}",
                          headers={**H, "Content-Type": "application/zip"}, data=f)
    if r.status_code == 201:
        print(f"  ✅ 上传成功: {r.json()['browser_download_url']}")
    else:
        print(f"  ❌ 上传失败: {r.text[:200]}")


# ── 主流程 ──
def main():
    dry_run = "--dry-run" in sys.argv

    print(f"╔══════════════════════════════════╗")
    print(f"║  BDS Manager Fluent  发布脚本     ║")
    print(f"║  版本: v{VERSION:<25} ║")
    print(f"╚══════════════════════════════════╝")

    # 1. 确认工作区干净
    result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
    if result.stdout.strip():
        print("\n⚠️  工作区不干净，请先提交所有更改:")
        print(result.stdout)
        if not dry_run:
            return

    # 2. 打包
    print("\n[1/3] 打包项目...")
    zip_path, sha256, size = build_zip()

    # 3. 更新 version.json
    changelog = input("\n📝 更新说明 (可选): ").strip() or f"BDS Manager Fluent v{VERSION}"
    update_version_json(sha256, size, changelog)

    # 4. 提交 + 推送
    subprocess.run(["git", "add", "version.json"], check=True)
    subprocess.run(["git", "commit", "-m", f"发布 v{VERSION}: {changelog[:60]}"], check=True)
    subprocess.run(["git", "push"], check=True)
    print("  ✅ 已推送")

    if dry_run:
        print(f"\n✅ 干跑完成。zip 保存在: {zip_path}")
        return

    # 5. 发布
    print(f"\n[2/3] 创建 Release {TAG}...")
    create_release_gh_cli(zip_path, changelog)

    print(f"\n[3/3] ✅ 发布完成！")
    print(f"  Release: https://github.com/{OWNER}/{REPO}/releases/tag/{TAG}")
    print(f"  Zip 已保存: {zip_path}")


if __name__ == "__main__":
    main()
