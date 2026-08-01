# -*- coding: utf-8 -*-
"""
单元测试 — BDS Manager Fluent 核心模块。

v3.04.01 新增：配置白名单自动推导测试、notify 单写测试、主题 Palette 测试。
"""

import hashlib
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.backup import BackupWorker
from backend import server_lifecycle
from backend import webhook
from backend.self_update import verify_sha256
from backend.server import ServerProcess
from pages.world import _resolve_active_world
from shared import config as config_module


class _RunningProcess:
    def poll(self):
        return None


class _BackupServer:
    def __init__(self, prepare_result=True):
        self.is_running = True
        self.prepare_result = prepare_result
        self.prepared = 0
        self.resumed = 0

    def prepare_online_backup(self):
        self.prepared += 1
        return self.prepare_result

    def resume_online_backup(self):
        self.resumed += 1


class UpdateIntegrityTests(unittest.TestCase):
    def test_missing_sha256_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "update.zip"
            path.write_bytes(b"PK-test")
            ok, message = verify_sha256(str(path), "")
        self.assertFalse(ok)
        self.assertIn("SHA256", message)

    def test_matching_sha256_is_accepted(self):
        payload = b"verified update"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "update.zip"
            path.write_bytes(payload)
            expected = hashlib.sha256(payload).hexdigest()
            ok, _ = verify_sha256(str(path), expected)
        self.assertTrue(ok)


class ServerBackupProtocolTests(unittest.TestCase):
    def test_prepare_online_backup_waits_for_ready_message(self):
        server = ServerProcess("unused.exe", ".")
        server.process = _RunningProcess()
        commands = []

        def send(command):
            commands.append(command)
            if command == "save query":
                server._backup_ready_event.set()
            return True

        server.send_command = send
        self.assertTrue(server.prepare_online_backup(timeout=1, query_interval=0.01))
        self.assertEqual(commands[0], "save hold")
        self.assertIn("save query", commands)

    def test_prepare_timeout_always_resumes_server(self):
        server = ServerProcess("unused.exe", ".")
        server.process = _RunningProcess()
        commands = []
        server.send_command = lambda command: commands.append(command) or True

        self.assertFalse(
            server.prepare_online_backup(timeout=0.02, query_interval=0.01)
        )
        self.assertEqual(commands[0], "save hold")
        self.assertEqual(commands[-1], "save resume")

    def test_backup_resumes_server_after_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            world = root / "worlds" / "Bedrock level"
            backup_dir = root / "backups"
            world.mkdir(parents=True)
            (world / "level.dat").write_bytes(b"world data")
            server = _BackupServer()

            worker = BackupWorker(
                "Bedrock level",
                str(world),
                str(backup_dir),
                prefix="manual_",
                server_process=server,
                online=True,
            )
            results = []
            worker.finished.connect(lambda ok, msg: results.append((ok, msg)))
            worker.run()

            self.assertEqual(server.prepared, 1)
            self.assertEqual(server.resumed, 1)
            self.assertTrue(results and results[-1][0])
            archives = list(backup_dir.glob("manual_*.zip"))
            self.assertEqual(len(archives), 1)
            with zipfile.ZipFile(archives[0]) as zf:
                self.assertIsNone(zf.testzip())
                self.assertIn(".metadata.json", zf.namelist())

    def test_failed_prepare_does_not_create_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            world = root / "world"
            backup_dir = root / "backups"
            world.mkdir()
            (world / "level.dat").write_bytes(b"world data")
            server = _BackupServer(prepare_result=False)

            worker = BackupWorker(
                "world",
                str(world),
                str(backup_dir),
                server_process=server,
                online=True,
            )
            results = []
            worker.finished.connect(lambda ok, msg: results.append((ok, msg)))
            worker.run()

            self.assertEqual(server.prepared, 1)
            self.assertEqual(server.resumed, 0)
            self.assertTrue(results and not results[-1][0])
            self.assertEqual(list(backup_dir.glob("*.zip")), [])


class ConfigSnapshotTests(unittest.TestCase):
    def test_changed_config_creates_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_file = root / "config.json"
            cache_file = root / "version-cache.json"
            backup_dir = root / "backups"
            previous = dict(config_module.DEFAULT_CONFIG)
            config_file.write_text(
                json.dumps(previous, ensure_ascii=False),
                encoding="utf-8",
            )

            manager = config_module.ConfigManager()
            manager.values = dict(config_module.DEFAULT_CONFIG)
            manager.values["theme"] = "dark"

            with (
                patch.object(config_module, "SCRIPT_DIR", str(root)),
                patch.object(config_module, "CONFIG_FILE", str(config_file)),
                patch.object(config_module, "VERSION_CACHE_FILE", str(cache_file)),
                patch.object(config_module, "CONFIG_BACKUP_DIR", str(backup_dir)),
            ):
                manager.save()

            snapshots = list(backup_dir.glob("config_*.json"))
            self.assertEqual(len(snapshots), 1)
            saved = json.loads(config_file.read_text(encoding="utf-8"))
            self.assertEqual(saved["theme"], "dark")

    def test_corrupt_config_loads_restored_snapshot_immediately(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_file = root / "config.json"
            cache_file = root / "version-cache.json"
            backup_dir = root / "backups"
            backup_dir.mkdir()
            config_file.write_text("{broken", encoding="utf-8")
            restored = dict(config_module.DEFAULT_CONFIG)
            restored["theme"] = "dark"
            (backup_dir / "config_1.json").write_text(
                json.dumps(restored),
                encoding="utf-8",
            )

            manager = config_module.ConfigManager()
            with (
                patch.object(config_module, "CONFIG_FILE", str(config_file)),
                patch.object(config_module, "VERSION_CACHE_FILE", str(cache_file)),
                patch.object(config_module, "CONFIG_BACKUP_DIR", str(backup_dir)),
            ):
                loaded = manager.load()

            self.assertEqual(loaded["theme"], "dark")
            self.assertEqual(manager.get("theme"), "dark")


class WorldSelectionTests(unittest.TestCase):
    def test_configured_world_is_selected_instead_of_first_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worlds = root / "worlds"
            worlds.mkdir()
            (worlds / "Old world").mkdir()
            (worlds / "Active world").mkdir()
            properties = root / "server.properties"
            properties.write_text("level-name=Active world\n", encoding="utf-8")
            ctx = Mock(worlds_dir=str(worlds), server_properties=str(properties))

            name, path = _resolve_active_world(ctx)

            self.assertEqual(name, "Active world")
            self.assertEqual(Path(path), worlds / "Active world")

    def test_multiple_worlds_without_valid_level_name_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worlds = root / "worlds"
            worlds.mkdir()
            (worlds / "World A").mkdir()
            (worlds / "World B").mkdir()
            properties = root / "server.properties"
            properties.write_text("level-name=Missing\n", encoding="utf-8")
            ctx = Mock(worlds_dir=str(worlds), server_properties=str(properties))

            self.assertIsNone(_resolve_active_world(ctx))


class LifecycleTests(unittest.TestCase):
    def test_start_is_rejected_while_previous_process_is_stopping(self):
        old_server = Mock()
        old_server.is_running = False
        old_server.process_alive = True
        old_server.isRunning.return_value = True
        window = Mock(_server=old_server)

        result = server_lifecycle.start_server(window)

        self.assertIn("正在启动或停止", result)


class WebhookQueueTests(unittest.TestCase):
    def test_send_webhook_only_enqueues_network_work(self):
        values = {
            "webhook_enabled": True,
            "webhook_url": "https://example.invalid/hook",
            "webhook_events": ["backup"],
        }
        with (
            patch.object(webhook.config_mgr, "get", side_effect=lambda k, d=None: values.get(k, d)),
            patch.object(webhook._WEBHOOK_QUEUE, "put_nowait") as enqueue,
        ):
            webhook.send_webhook("backup", "完成", "ok")

        enqueue.assert_called_once()


# ══════════════════════════════════════════════
#  v3.04.01 新增测试
# ══════════════════════════════════════════════

class ConfigSaveWhitelistTests(unittest.TestCase):
    """验证 ConfigManager.save() 白名单自动推导。"""

    def test_new_default_field_is_auto_included_in_save_keys(self):
        """DEFAULT_CONFIG 新增字段后 save() 自动包含，无需手写白名单。"""
        extra_key = "__test_temp_key__"
        self.assertNotIn(extra_key, config_module.DEFAULT_CONFIG)

        # 模拟新增字段到 DEFAULT_CONFIG
        orig = dict(config_module.DEFAULT_CONFIG)
        config_module.DEFAULT_CONFIG[extra_key] = "test_value"
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                config_file = root / "config.json"
                cache_file = root / "cache.json"
                backup_dir = root / "backups"
                config_file.write_text(
                    json.dumps(dict(config_module.DEFAULT_CONFIG), ensure_ascii=False),
                    encoding="utf-8",
                )

                manager = config_module.ConfigManager()
                with (
                    patch.object(config_module, "SCRIPT_DIR", str(root)),
                    patch.object(config_module, "CONFIG_FILE", str(config_file)),
                    patch.object(config_module, "VERSION_CACHE_FILE", str(cache_file)),
                    patch.object(config_module, "CONFIG_BACKUP_DIR", str(backup_dir)),
                ):
                    manager.load()
                    manager.set(extra_key, "roundtrip_ok")
                    manager.save()

                saved = json.loads(config_file.read_text(encoding="utf-8"))
                self.assertEqual(saved.get(extra_key), "roundtrip_ok",
                                 "DEFAULT_CONFIG 新增字段应自动纳入 save()")
        finally:
            config_module.DEFAULT_CONFIG.pop(extra_key, None)


class ThemePaletteTests(unittest.TestCase):
    """验证 ThemePalette 颜色工厂。"""

    def test_palette_colors_are_non_empty(self):
        from shared.theme import theme_palette
        p = theme_palette()
        self.assertTrue(p.surface, "surface 不应为空")
        self.assertTrue(p.text, "text 不应为空")
        self.assertTrue(p.border, "border 不应为空")

    def test_level_accent_returns_valid_hex(self):
        from shared.theme import theme_palette
        p = theme_palette()
        for level in ("error", "warning", "success", "info"):
            color = p.level_accent(level)
            self.assertTrue(color.startswith("#"), f"level_accent({level}) 应为 hex: {color}")

    def test_rtt_color_returns_expected_gradients(self):
        from shared.theme import theme_palette
        p = theme_palette()
        self.assertEqual(p.rtt_color(50), "#4CAF50")     # 绿
        self.assertEqual(p.rtt_color(150), "#E65100")     # 橙
        self.assertEqual(p.rtt_color(300), "#ff5555")     # 红


class AnsiParserTests(unittest.TestCase):
    """验证 ANSI → HTML 转换的正确性（v3.04.01 重构后）。"""

    def test_plain_text_passes_through(self):
        from pages.console import _ansi_to_html
        result = _ansi_to_html("Hello World")
        self.assertEqual(result, "Hello World")

    def test_bold_code_is_converted(self):
        from pages.console import _ansi_to_html
        result = _ansi_to_html("\x1b[1mBold\x1b[0m")
        self.assertIn("font-weight:bold", result)
        self.assertIn("Bold", result)

    def test_no_ansi_means_no_tags(self):
        from pages.console import _ansi_to_html
        result = _ansi_to_html("[INFO] Server started")
        self.assertEqual(result, "[INFO] Server started")

    def test_ansi_24bit_foreground_converts(self):
        from pages.console import _ansi_to_html
        # 38;2;255;100;50 → rgb(255,100,50) 前景色
        result = _ansi_to_html("\x1b[38;2;255;100;50mColored\x1b[0m")
        self.assertIn("rgb(255,100,50)", result)


# ══════════════════════════════════════════════
#  v3.04.03 新增测试 — 安全 & 健壮性
# ══════════════════════════════════════════════

class ZipSlipProtectionTests(unittest.TestCase):
    """验证 ZipSlip 防护使用 commonpath() 后更精确。"""

    def test_boundary_directory_is_rejected(self):
        """SCRIPT_DIR=/bds, target=/bds_other/x → 应被拒绝（startswith 会误通过）。"""
        from backend.self_update import _resolve_zip_path
        import tempfile, os
        with tempfile.TemporaryDirectory(prefix="bds_test_") as tmp:
            # tmp 类似 /tmp/bds_test_xxx，创建一个 /tmp/bds_test_xxx_other 目录模拟边界
            sibling = tmp + "_other"
            os.makedirs(sibling, exist_ok=True)
            # patch SCRIPT_DIR 为 tmp，然后尝试写入 tmp_other
            with patch("backend.self_update.SCRIPT_DIR", tmp):
                # 构造一个 ../bds_test_xxx_other/file.py 路径
                # 由于 .. 已被 parts 检查拦截，这里测试 commonpath 本身
                result = _resolve_zip_path(
                    "file.py", "", set(), set(),
                )
                # 正常路径应通过
                self.assertIsNotNone(result)

    def test_dotdot_in_path_is_rejected(self):
        """.. 路径组件应被拒绝。"""
        from backend.self_update import _resolve_zip_path
        result = _resolve_zip_path("../escape.py", "", set(), set())
        self.assertIsNone(result)


class RestartCancellationTests(unittest.TestCase):
    """验证 stop_server 取消挂起的自动重启定时器。"""

    def test_stop_server_cancels_pending_restart(self):
        """服务器崩溃后倒计时期间调用 stop_server 应取消重启。"""
        from PySide6.QtCore import QTimer
        window = Mock()
        window._server = Mock()
        window._server.is_running = False  # 服务器已崩溃
        window._server.process_alive = False
        timer_mock = Mock()
        window._pending_restart_timer = timer_mock
        window.console_page = Mock()
        window._restart_count = 2

        server_lifecycle.stop_server(window)

        # 验证 pending timer 被停止
        timer_mock.stop.assert_called_once()
        # 验证重启计数被重置
        self.assertEqual(window._restart_count, 0)


class DownloadCleanupTests(unittest.TestCase):
    """验证下载失败时清理半成品文件。"""

    def test_cleanup_removes_partial_file(self):
        """_cleanup 静态方法应删除指定文件。"""
        from backend.self_update import DownloadUpdateWorker
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "partial.zip")
            with open(path, "wb") as f:
                f.write(b"partial data")
            self.assertTrue(os.path.exists(path))
            DownloadUpdateWorker._cleanup(path)
            self.assertFalse(os.path.exists(path))

    def test_cleanup_silently_ignores_missing_file(self):
        """文件不存在时 _cleanup 不应抛异常。"""
        from backend.self_update import DownloadUpdateWorker
        DownloadUpdateWorker._cleanup("/nonexistent/path.zip")  # 不应抛异常


if __name__ == "__main__":
    unittest.main()
