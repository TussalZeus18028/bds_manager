# -*- coding: utf-8 -*-
"""
世界备份与还原（PySide6 版）。

从旧 PyQt5 版本提取并改写：pyqtSignal → Signal，保持相同逻辑。
"""

import os
import time
import zipfile
import shutil
import tempfile
import logging
from datetime import datetime
from PySide6.QtCore import Signal

from shared.workers import BaseWorker

logger = logging.getLogger("bds_manager")


class BackupWorker(BaseWorker):
    """世界备份后台线程。"""

    def __init__(self, level_name: str, world_path: str, backup_dir: str, parent=None, prefix: str = ""):
        super().__init__(parent)
        self.level_name = level_name
        self.world_path = world_path
        self.backup_dir = backup_dir
        self.prefix = prefix

    def run(self):
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"{self.prefix}{self.level_name}_{timestamp}.zip"
            backup_path = os.path.join(self.backup_dir, backup_name)
            self.progress.emit(f"正在备份 {self.level_name} 到 {backup_name} ...")

            with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                total_files = 0
                for root, dirs, files in os.walk(self.world_path):
                    for file in files:
                        if self._cancel:
                            self.finished.emit(False, "备份已取消")
                            return
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, os.path.dirname(self.world_path))
                        zipf.write(file_path, arcname)
                        total_files += 1
                        if total_files % 100 == 0:
                            self.progress.emit(f"已打包 {total_files} 个文件...")

            self.progress.emit(f"备份完成: {backup_name}")
            self.finished.emit(True, f"备份成功: {backup_name}")
        except Exception as e:
            logger.error("备份失败: %s", e)
            self.finished.emit(False, f"备份失败: {e}")


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

            # 解压备份
            self.progress.emit("正在解压备份...")
            with zipfile.ZipFile(self.backup_path, "r") as zipf:
                zipf.extractall(os.path.dirname(self.world_path))

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


def get_backup_files(backup_dir: str) -> list[str]:
    """返回备份目录下的 zip 文件列表（按修改时间降序）。"""
    if not os.path.exists(backup_dir):
        return []
    files = [f for f in os.listdir(backup_dir) if f.endswith(".zip")]
    files.sort(key=lambda f: os.path.getmtime(os.path.join(backup_dir, f)), reverse=True)
    return files


def get_backup_info(backup_dir: str, filename: str) -> dict | None:
    """获取单个备份文件的元信息。"""
    fp = os.path.join(backup_dir, filename)
    if not os.path.exists(fp):
        return None
    stat = os.stat(fp)
    return {
        "name": filename,
        "path": fp,
        "size_mb": stat.st_size / (1024 * 1024),
        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
    }
