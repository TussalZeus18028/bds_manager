"""bds_manager.py 基础单元测试。

覆盖纯函数与少量无需完整 UI 的实例方法：
- compare_versions        : 点分版本号比较（修复 R9 的统一实现）
- _decode_server_line     : 服务器输出字节解码（R3 中文乱码修复）
- network_error_text      : 网络异常友好提示（中文 + 英文）
- send_webhook            : Webhook 通知发送（#69）
- UpgradeTab._common_top_dir   : 更新 ZIP 公共顶层目录探测（B3 修复）

说明：UpgradeTab._common_top_dir 方法体不依赖实例状态（不访问 self.* 属性），
因此以 None 作为 self 直接以未绑定方法形式调用，避免实例化 QWidget。
"""

import json
import os
import sys
import tempfile

import pytest

# 将项目根目录加入 import 路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import bds_manager as m


# ---------------------------------------------------------------------------
# compare_versions
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("a,b,expected", [
    ("2.1.1.12", "2.1.1.11", 1),
    ("1.0.0", "1.0.0.1", -1),
    ("2.1.1.12", "2.1.1.12", 0),
    ("1.2", "1.2.0", 0),          # 短版本号补零后相等
    ("1.10", "1.9", 1),
    ("not.a.version", "2.0", 0),   # 非法输入返回 0
    ("", "2.0", 0),
])
def test_compare_versions(a, b, expected):
    assert m.compare_versions(a, b) == expected


# ---------------------------------------------------------------------------
# _decode_server_line
# ---------------------------------------------------------------------------
def test_decode_returns_str_as_is():
    assert m._decode_server_line("纯文本行") == "纯文本行"


def test_decode_utf8_bytes():
    raw = "服务器已启动".encode("utf-8")
    assert m._decode_server_line(raw) == "服务器已启动"


def test_decode_gbk_bytes():
    # 模拟中文 Windows 控制台以 GBK 输出的字节
    raw = "中文乱码测试".encode("gbk")
    assert m._decode_server_line(raw) == "中文乱码测试"


def test_decode_invalid_falls_back_without_raising():
    # 无法用任何编码干净解码的字节不应抛异常
    raw = b"\xff\xfe\x00\x80\x99"
    out = m._decode_server_line(raw)
    assert isinstance(out, str)


# ---------------------------------------------------------------------------
# network_error_text
# ---------------------------------------------------------------------------
def test_network_error_none():
    zh, en, combined = m.network_error_text(None)
    assert "未知" in zh and "Unknown" in en
    assert "English" not in combined  # combined 用括号包裹英文
    assert "(Unknown" in combined


def test_network_error_timeout():
    import urllib.error
    exc = urllib.error.URLError("Connection timed out")
    zh, en, _ = m.network_error_text(exc)
    assert "超时" in zh and "timed out" in en


def test_network_error_dns():
    import urllib.error
    exc = urllib.error.URLError("getaddrinfo failed")
    zh, en, _ = m.network_error_text(exc)
    assert "DNS" in zh


def test_network_error_http():
    import urllib.error
    exc = urllib.error.HTTPError("http://x", 404, "Not Found", None, None)
    zh, en, _ = m.network_error_text(exc)
    assert "404" in zh


# ---------------------------------------------------------------------------
# send_webhook
# ---------------------------------------------------------------------------
def _fake_parent(webhook_url="", events=None):
    class Cfg:
        config = {
            "webhook_url": webhook_url,
            "webhook_events": events if events is not None else ["backup", "crash", "memory"],
        }
    return Cfg()


def test_send_webhook_skips_when_url_empty(monkeypatch):
    called = {"n": 0}

    def fake_post(*args, **kwargs):
        called["n"] += 1
        raise AssertionError("不应被调用")

    monkeypatch.setattr(m.requests, "post", fake_post)
    m._toast_parent = _fake_parent(webhook_url="")
    m.send_webhook("backup", "标题", "消息")
    assert called["n"] == 0


def test_send_webhook_skips_when_event_not_enabled(monkeypatch):
    called = {"n": 0}

    def fake_post(*args, **kwargs):
        called["n"] += 1

    monkeypatch.setattr(m.requests, "post", fake_post)
    m._toast_parent = _fake_parent(webhook_url="https://example.com/hook", events=["crash"])
    m.send_webhook("backup", "标题", "消息")
    assert called["n"] == 0


def test_send_webhook_posts_when_enabled(monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return type("R", (), {"status_code": 200})()

    monkeypatch.setattr(m.requests, "post", fake_post)
    m._toast_parent = _fake_parent(webhook_url="https://example.com/hook", events=["backup"])
    m.send_webhook("backup", "备份完成", "成功")
    assert captured["url"] == "https://example.com/hook"
    assert "备份完成" in captured["json"]["content"]
    assert captured["json"]["username"] == "BDS Manager"
    assert captured["timeout"] == 8


def test_send_webhook_silent_on_request_error(monkeypatch):
    def fake_post(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(m.requests, "post", fake_post)
    m._toast_parent = _fake_parent(webhook_url="https://example.com/hook", events=["backup"])
    # 不应抛异常
    m.send_webhook("backup", "t", "m")


# ---------------------------------------------------------------------------
# UpgradeTab._common_top_dir  (未绑定调用，self 为 None)
# ---------------------------------------------------------------------------
def test_common_top_dir_single_top():
    names = ["bedrock-server-1.20/bedrock_server.exe",
             "bedrock-server-1.20/config/foo.json"]
    assert m.UpgradeTab._common_top_dir(None, names) == "bedrock-server-1.20/"


def test_common_top_dir_multiple_tops():
    names = ["a/file.txt", "b/file.txt"]
    assert m.UpgradeTab._common_top_dir(None, names) == ""


def test_common_top_dir_top_level_file():
    names = ["readme.txt", "sub/file.txt"]
    assert m.UpgradeTab._common_top_dir(None, names) == ""


def test_common_top_dir_backslash():
    names = ["server\\bedrock_server.exe"]
    assert m.UpgradeTab._common_top_dir(None, names) == "server/"


def test_common_top_dir_skips_dir_entries():
    names = ["bedrock-server-1.20/", "bedrock-server-1.20/bedrock_server.exe"]
    assert m.UpgradeTab._common_top_dir(None, names) == "bedrock-server-1.20/"
