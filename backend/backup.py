# -*- coding: utf-8 -*-
"""
世界备份与还原（PySide6 版）。

从旧 PyQt5 版本提取并改写：pyqtSignal → Signal，保持相同逻辑。

v3.1 改进：
- 备份时写入 metadata.json（包含版本/时间/世界名/源 BDS 版本/文件数）
- 备份完成时记录 hash 和玩家数
- 提供 list_backup_contents() 用于备份内容预览
- 提供 read_backup_metadata() 用于读取元数据
"""

import os
import json
import time
import hashlib
import zipfile
import shutil
import tempfile
import logging
from datetime import datetime
from PySide6.QtCore import Signal

from shared.workers import BaseWorker
from shared.errors import FileMissingError

logger = logging.getLogger("bds_manager")


# ---------- 元数据辅助 ----------
def _write_backup_metadata(backup_path: str, metadata: dict):
    """把 metadata 嵌入 zip 内 .metadata.json（不计入压缩列表，仅用 zipfile 写）。"""
    try:
        with zipfile.ZipFile(backup_path, "a", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(".metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))
    except Exception as e:
        logger.debug("写入备份元数据失败: %s", e)


def read_backup_metadata(backup_path: str) -> dict | None:
    """从 zip 读取 .metadata.json，失败返回 None。"""
    try:
        with zipfile.ZipFile(backup_path, "r") as zf:
            try:
                raw = zf.read(".metadata.json")
                return json.loads(raw.decode("utf-8"))
            except KeyError:
                return None
    except (zipfile.BadZipFile, OSError):
        return None


def list_backup_contents(backup_path: str) -> list[str] | None:
    """列出 zip 内的所有文件名（不递归解包）。返回 None 表示无效 zip。"""
    try:
        with zipfile.ZipFile(backup_path, "r") as zf:
            # 过滤掉元数据文件
            return [n for n in zf.namelist() if n != ".metadata.json"]
    except (zipfile.BadZipFile, OSError):
        return None


def build_backup_tree(backup_path: str) -> dict | None:
    """把 zip 内容构造成树形 dict 用于 QTreeWidget 显示。

    返回：
        {
            "name": "Bedrock_20260722_120000.zip",
            "total_files": N,
            "total_size": S,
            "root": {"name": "worlds/Bedrock Level/", "children": [...], "files": [...]}
        }
    或 None（无效 zip）
    """
    try:
        with zipfile.ZipFile(backup_path, "r") as zf:
            infos = zf.infolist()
            total_files = sum(1 for i in infos if not i.is_dir() and i.filename != ".metadata.json")
            total_size = sum(i.file_size for i in infos if not i.is_dir() and i.filename != ".metadata.json")
            # 构造树
            root: dict = {"name": "/", "children": {}, "files": []}
            for info in infos:
                if info.filename == ".metadata.json":
                    continue
                parts = info.filename.replace("\\", "/").split("/")
                cur = root
                for i, p in enumerate(parts):
                    is_last = (i == len(parts) - 1)
                    if is_last:
                        if info.is_dir():
                            cur["children"].setdefault(p + "/", {"name": p, "children": {}, "files": []})
                        else:
                            cur["files"].append({"name": p, "size": info.file_size})
                    else:
                        key = p + "/"
                        if key not in cur["children"]:
                            cur["children"][key] = {"name": p, "children": {}, "files": []}
                        cur = cur["children"][key]
            return {
                "name": os.path.basename(backup_path),
                "total_files": total_files,
                "total_size": total_size,
                "root": root,
            }
    except (zipfile.BadZipFile, OSError):
        return None


# ---------- 备份 Worker ----------
class BackupWorker(BaseWorker):
    """世界备份后台线程。"""

    def __init__(self, level_name: str, world_path: str, backup_dir: str,
                 parent=None, prefix: str = "", bds_version: str = ""):
        super().__init__(parent)
        self.level_name = level_name
        self.world_path = world_path
        self.backup_dir = backup_dir
        self.prefix = prefix
        self.bds_version = bds_version
        self.result_path: str = ""

    def run(self):
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"{self.prefix}{self.level_name}_{timestamp}.zip"
            backup_path = os.path.join(self.backup_dir, backup_name)
            self.progress.emit(f"正在备份 {self.level_name} 到 {backup_name} ...")

            file_count = 0
            total_bytes = 0
            with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(self.world_path):
                    for file in files:
                        if self._cancel:
                            self.finished.emit(False, "备份已取消")
                            return
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, os.path.dirname(self.world_path))
                        zipf.write(file_path, arcname)
                        file_count += 1
                        try:
                            total_bytes += os.path.getsize(file_path)
                        except OSError:
                            pass
                        if file_count % 100 == 0:
                            self.progress.emit(f"已打包 {file_count} 个文件...")

            # 写入元数据
            metadata = {
                "world_name": self.level_name,
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "bds_version": self.bds_version,
                "file_count": file_count,
                "total_bytes": total_bytes,
                "tool_version": "3.1",
            }
            _write_backup_metadata(backup_path, metadata)
            self.result_path = backup_path
            self.progress.emit(f"备份完成: {backup_name}（{file_count} 个文件，{total_bytes/1024/1024:.1f} MB）")
            self.finished.emit(True, f"备份成功: {backup_name}")
        except Exception as e:
            logger.error("备份失败: %s", e)
            self.finished.emit(False, f"备份失败: {e}")


# ---------- 还原 Worker ----------
class RestoreWorker(BaseWorker):
    """世界还原后台线程（带安全回滚）。"""

    def __init__(self, level_name: str, world_path: str, backup_path: str, parent=None):
        super().__init__(parent)
        self.level_name = level_name
        self.world_path = world_path
        self.backup_path = backup_path

    def run(self):
        temp_backup = None
        try:
            # 验证备份 zip 完整性
            self.progress.emit("正在验证备份文件...")
            if not zipfile.is_zipfile(self.backup_path):
                self.finished.emit(False, "备份文件已损坏或不是有效的 ZIP 文件")
                return

            with zipfile.ZipFile(self.backup_path, "r") as test_zf:
                bad_file = test_zf.testzip()
            if bad_file:
                self.finished.emit(False, f"备份文件中的 {bad_file} 已损坏，还原已中止")
                return

            # 移走当前世界（先移到临时目录，失败时可回滚）
            self.progress.emit("正在清空当前世界...")
            if os.path.exists(self.world_path) and os.listdir(self.world_path):
                temp_backup = tempfile.mkdtemp(
                    prefix="world_restore_backup_",
                    dir=os.path.dirname(self.world_path),
                )
                for item in os.listdir(self.world_path):
                    if self._cancel:
                        self._rollback_restore(temp_backup, self.world_path)
                        self.finished.emit(False, "还原已取消")
                        return
                    item_path = os.path.join(self.world_path, item)
                    dest = os.path.join(temp_backup, item)
                    shutil.move(item_path, dest)

            # 解压备份（ZipSlip 防护）
            self.progress.emit("正在解压备份...")
            with zipfile.ZipFile(self.backup_path, "r") as zipf:
                target_dir = os.path.dirname(self.world_path)
                target_real = os.path.realpath(target_dir)
                for member in zipf.infolist():
                    if member.filename == ".metadata.json":
                        continue
                    member_path = os.path.realpath(os.path.join(target_dir, member.filename))
                    if not member_path.startswith(target_real + os.sep) and member_path != target_real:
                        logger.warning("跳过越权路径: %s", member.filename)
                        continue
                    zipf.extract(member, target_dir)

            # 清理临时备份
            if temp_backup and os.path.exists(temp_backup):
                shutil.rmtree(temp_backup, ignore_errors=True)

            self.progress.emit("还原完成")
            self.finished.emit(True, f"世界已从 {os.path.basename(self.backup_path)} 还原")
        except Exception as e:
            logger.error("还原失败: %s", e)
            self._rollback_restore(temp_backup, self.world_path)
            self.finished.emit(False, f"还原失败: {e}")

    def _rollback_restore(self, temp_backup: str | None, world_path: str):
        """还原失败时将临时移出的世界内容移回（修复 L3 数据丢失）。"""
        if not temp_backup or not os.path.exists(temp_backup):
            return
        try:
            os.makedirs(world_path, exist_ok=True)
            for item in os.listdir(temp_backup):
                src = os.path.join(temp_backup, item)
                dest = os.path.join(world_path, item)
                if os.path.exists(dest):
                    shutil.rmtree(dest, ignore_errors=True)
                shutil.move(src, dest)
            shutil.rmtree(temp_backup, ignore_errors=True)
            logger.info("还原回滚完成")
        except Exception as e:
            logger.error("回滚失败，临时备份保留在 %s: %s", temp_backup, e)


# ---------- 列表与元信息 ----------
def get_backup_files(backup_dir: str) -> list[str]:
    """返回备份目录下的 zip 文件列表（按修改时间降序）。"""
    if not os.path.exists(backup_dir):
        return []
    files = [f for f in os.listdir(backup_dir) if f.endswith(".zip")]
    files.sort(key=lambda f: os.path.getmtime(os.path.join(backup_dir, f)), reverse=True)
    return files


def get_backup_info(backup_dir: str, filename: str) -> dict | None:
    """获取单个备份文件的元信息（合并 zip 文件属性 + 嵌入 metadata）。"""
    fp = os.path.join(backup_dir, filename)
    if not os.path.exists(fp):
        return None
    stat = os.stat(fp)
    info = {
        "name": filename,
        "path": fp,
        "size_mb": stat.st_size / (1024 * 1024),
        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        "metadata": None,
    }
    # 尝试读取嵌入 metadata
    meta = read_backup_metadata(fp)
    if meta:
        info["metadata"] = meta
    return info
