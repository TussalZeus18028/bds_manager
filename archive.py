# -*- coding: utf-8 -*-
"""
项目归档工具 —— 把当前源代码快照到 archives/ 目录。

用法：
    python archive.py                  # 自动检测版本号 + 内容未变则跳过
    python archive.py --label mywork   # 自定义后缀
    python archive.py --force          # 强制重新归档（即使内容未变）
    python archive.py --list           # 列出已有归档
    python archive.py --keep 10        # 归档后只保留最近 N 份（默认 20）

智能跳过：
    - 计算所有源文件（路径+mtime+size）的 SHA256
    - 与 archives/.last_archive_hash 比对
    - 一致则跳过（避免每次都创建相同内容的 zip）
    - 用 --force 可强制覆盖

归档目录约定：
    - dist/        —— 正式发布包（release.py 产出，用于 GitHub Release）
    - archives/    —— 代码快照（archive.py 产出，用于本地版本对比/回滚）

排除项：
    __pycache__/  .git/  .workbuddy/  dist/  archives/
    logs/  backups/  *.pyc  *.bak_  .DS_Store  Thumbs.db
"""
import argparse
import hashlib
import os
import re
import sys
import time
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ARCHIVES_DIR = SCRIPT_DIR / "archives"
HASH_FILE = ARCHIVES_DIR / ".last_archive_hash"

SKIP_DIRS = {
    "__pycache__", ".git", ".workbuddy", "dist", "archives",
    "logs", "backups", "release", ".vscode", ".idea",
}
SKIP_FILES = {".gitignore", ".DS_Store", "Thumbs.db"}
SKIP_SUFFIX = (".pyc", ".bak_", ".tmp")


def get_version() -> str:
    """从 main.py 顶部读取 __version__ 字符串。"""
    main_py = SCRIPT_DIR / "main.py"
    if not main_py.exists():
        return "unknown"
    text = main_py.read_text(encoding="utf-8")
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    return m.group(1) if m else "unknown"


def iter_source_files():
    """遍历要打包的源文件（按相对路径排序，保证 hash 稳定）。"""
    files = []
    for root, dirs, fs in os.walk(SCRIPT_DIR):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in fs:
            if fn in SKIP_FILES or fn.startswith("."):
                continue
            if any(fn.endswith(s) for s in SKIP_SUFFIX):
                continue
            if fn.endswith(".zip"):
                continue
            fp = Path(root) / fn
            files.append(fp)
    files.sort(key=lambda p: p.relative_to(SCRIPT_DIR).as_posix())
    return files


def compute_source_hash() -> str:
    """对所有源文件计算 SHA256（路径 + mtime + size）。"""
    h = hashlib.sha256()
    for fp in iter_source_files():
        rel = fp.relative_to(SCRIPT_DIR).as_posix()
        st = fp.stat()
        h.update(rel.encode("utf-8"))
        h.update(str(st.st_mtime_ns).encode("utf-8"))
        h.update(str(st.st_size).encode("utf-8"))
    return h.hexdigest()


def read_last_hash() -> str | None:
    if not HASH_FILE.exists():
        return None
    try:
        return HASH_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def write_last_hash(h: str):
    ARCHIVES_DIR.mkdir(parents=True, exist_ok=True)
    HASH_FILE.write_text(h, encoding="utf-8")


def build_zip(version: str, label: str = "") -> tuple[Path, list]:
    """打包项目到 archives/，返回 (zip_path, files_list)。"""
    ARCHIVES_DIR.mkdir(parents=True, exist_ok=True)

    ts = time.strftime("%Y%m%d_%H%M%S")
    tag = f"v{version}_{label}" if label else f"v{version}"
    out = ARCHIVES_DIR / f"bds_manager_{tag}_{ts}.zip"

    files = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for fp in iter_source_files():
            arc = fp.relative_to(SCRIPT_DIR).as_posix()
            zf.write(fp, arc)
            files.append(arc)

    return out, files


def list_archives() -> list[Path]:
    """列出 archives/ 下的所有归档，按修改时间倒序。"""
    if not ARCHIVES_DIR.exists():
        return []
    return sorted(ARCHIVES_DIR.glob("bds_manager_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)


def keep_recent(n: int):
    """列出将被清理的旧归档（仅打印，不删除 —— 由用户手动决定）。"""
    archives = list_archives()
    to_remove = archives[n:]
    if not to_remove:
        return
    print(f"\n  ⚠️  超过保留上限 {n} 份，以下 {len(to_remove)} 份较旧归档建议清理：")
    for old in to_remove:
        size_kb = old.stat().st_size / 1024
        mt = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(old.stat().st_mtime))
        print(f"     · {old.name}  ({size_kb:.1f} KB, {mt})")
    print(f"\n  💡 如需自动清理，请手动执行（沙箱策略禁止脚本直接删除文件）：")
    quoted = " ".join(f'"{p}"' for p in to_remove)
    print(f"     rm {quoted}")


def main():
    parser = argparse.ArgumentParser(
        description="把当前项目快照打包到 archives/ 目录",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--label", default="", help="归档标签（如 bugfix/optimized/refactor）")
    parser.add_argument("--force", action="store_true", help="强制归档，忽略内容是否变化")
    parser.add_argument("--list", action="store_true", help="只列出已有归档，不打包")
    parser.add_argument("--keep", type=int, default=20, help="归档后保留最近 N 份（默认 20，0=不删除）")
    args = parser.parse_args()

    # 列出模式
    if args.list:
        archives = list_archives()
        if not archives:
            print("archives/ 目录为空")
            return 0
        print(f"\n📦 archives/ 下有 {len(archives)} 份归档（最新在前）：\n")
        for p in archives:
            size_kb = p.stat().st_size / 1024
            mt = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p.stat().st_mtime))
            print(f"  {p.name:55s}  {size_kb:7.1f} KB  {mt}")
        return 0

    # 打包模式
    version = get_version()
    print(f"📦 归档项目: BDS Manager v{version}")
    print(f"   目标: archives/")
    if args.label:
        print(f"   标签: {args.label}")

    # 智能跳过：内容未变则不创建新归档
    current_hash = compute_source_hash()
    last_hash = read_last_hash()
    if not args.force and last_hash == current_hash:
        archives = list_archives()
        latest = archives[0] if archives else None
        if latest:
            size_kb = latest.stat().st_size / 1024
            mt = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(latest.stat().st_mtime))
            print(f"\n⏭️  源代码未变更，跳过归档")
            print(f"   最近一份: {latest.name}  ({size_kb:.1f} KB, {mt})")
            print(f"   内容 hash: {current_hash[:16]}...")
            print(f"\n   💡 强制归档: python archive.py --force")
            if args.label:
                print(f"   或带标签: python archive.py --label {args.label} --force")
            return 0

    out, files = build_zip(version, args.label)
    size = out.stat().st_size

    # 把当前 hash 写入 sidecar
    write_last_hash(current_hash)

    print(f"\n✅ 归档完成: {out.name}")
    print(f"   文件数: {len(files)}")
    print(f"   大小:   {size:,} 字节 ({size/1024:.1f} KB)")
    print(f"   内容 hash: {current_hash[:16]}...")
    print(f"   路径:   {out.relative_to(SCRIPT_DIR)}")

    # 保留最近 N 份
    if args.keep > 0:
        keep_recent(args.keep)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n⚠️  已取消")
        sys.exit(1)
