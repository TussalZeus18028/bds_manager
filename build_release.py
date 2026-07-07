#!/usr/bin/env python3
"""BDS Manager 发布构建脚本
自动打包 → 计算 SHA256 → 写入 version.json → 输出到 release/ 目录
"""
import os
import sys
import json
import shutil
import hashlib
import zipfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 从 version.json 读取版本号
with open(os.path.join(SCRIPT_DIR, "version.json"), "r", encoding="utf-8") as f:
    meta = json.load(f)

VERSION = meta.get("version", "0.0.0.0")
print(f"[BUILD] 构建版本: v{VERSION}")

RELEASE_DIR = os.path.join(SCRIPT_DIR, "release")
os.makedirs(RELEASE_DIR, exist_ok=True)

ZIP_NAME = f"bds_manager_v{VERSION}.zip"
ZIP_PATH = os.path.join(RELEASE_DIR, ZIP_NAME)

# 需要打包的文件
INCLUDE_PATTERNS = [".py", ".txt", ".md", ".json", ".bat"]
EXCLUDE_FILES = {
    "bds_manager_config.json",
    "bds_version_cache.json",
    "build_release.py",
    "publish.py",
}
EXCLUDE_DIRS = {"logs", "backups", "Server", "Earlier version", "release", ".git", "__pycache__", "web_ui",
                ".workbuddy"}

# --- 1. 打包 ---
print(f"[BUILD] 打包 → {ZIP_NAME}")
file_count = 0
with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk(SCRIPT_DIR):
        # 跳过排除的目录
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith(".")]
        for f in files:
            if f in EXCLUDE_FILES:
                continue
            if not any(f.endswith(ext) for ext in INCLUDE_PATTERNS):
                continue
            full = os.path.join(root, f)
            arcname = os.path.relpath(full, SCRIPT_DIR)
            zf.write(full, arcname)
            file_count += 1

print(f"  → {file_count} 个文件已打包")

# --- 2. 计算 SHA256 ---
print("[BUILD] 计算 SHA256...")
h = hashlib.sha256()
with open(ZIP_PATH, "rb") as f:
    for chunk in iter(lambda: f.read(65536), b""):
        h.update(chunk)
sha256_hex = h.hexdigest()
file_size = os.path.getsize(ZIP_PATH)

print(f"  SHA256: {sha256_hex}")
print(f"  大小:   {file_size:,} bytes ({file_size/1024:.1f} KB)")

# --- 3. 更新 version.json (release 目录内副本) ---
meta["sha256"] = sha256_hex
meta["file_size"] = file_size
meta["download_url"] = f"https://github.com/TussalZeus18028/bds_manager/releases/download/v{VERSION}/{ZIP_NAME}"

release_json = os.path.join(RELEASE_DIR, "version.json")
with open(release_json, "w", encoding="utf-8") as f:
    json.dump(meta, f, indent=4, ensure_ascii=False)
print(f"[BUILD] {os.path.basename(release_json)} 已更新（含 SHA256）")

# 同时更新项目根目录的 version.json
root_json = os.path.join(SCRIPT_DIR, "version.json")
with open(root_json, "w", encoding="utf-8") as f:
    json.dump(meta, f, indent=4, ensure_ascii=False)
print(f"[BUILD] {os.path.basename(root_json)} 已同步")

# --- 4. 完成 ---
print(f"\n[DONE] 发布文件就绪:")
for item in os.listdir(RELEASE_DIR):
    full = os.path.join(RELEASE_DIR, item)
    size = os.path.getsize(full)
    print(f"  release/{item}  ({size:,} bytes)")
