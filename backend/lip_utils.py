# -*- coding: utf-8 -*-
"""
backend/lip_utils.py — lip 包管理器工具函数与工作线程。

供 upgrade.py 的 lip 一键部署区使用。
不依赖 PySide6（QThread 除外），可独立测试。
"""
import os
import shutil
import subprocess
import glob as _g
import time

from PySide6.QtCore import QThread, Signal


# ── 检测 ──
_LIP_PATHS = [
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\lip.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\futrime.lip_*\lip.exe"),
    os.path.expanduser("~/.local/bin/lip"),
    "/usr/local/bin/lip",
    "/usr/bin/lip",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\lip\lip.exe"),
    os.path.expandvars(r"%PROGRAMFILES%\lip\lip.exe"),
]


def lip_installed() -> bool:
    if shutil.which("lip"):
        return True
    for pat in _LIP_PATHS:
        for p in _g.glob(pat):
            if os.path.isfile(p):
                return True
    return False


def find_lip_exe() -> str:
    f = shutil.which("lip")
    if f:
        return f
    for pat in _LIP_PATHS:
        for p in _g.glob(pat):
            if os.path.isfile(p):
                return p
    return ""


def lip_version() -> str:
    """获取 lip 版本号。

    v3.05.07 注意：lip **没有** `version` 子命令（会报 Unknown command），
    正确用法是全局选项 `lip -v` / `lip --version`。
    """
    exe = find_lip_exe()
    if not exe:
        return ""
    try:
        r = subprocess.run([exe, "-v"], capture_output=True, timeout=8)
        if r.returncode != 0:
            return ""
        # lip 输出是 GBK（CP936）不是 UTF-8
        out = r.stdout.decode("gbk", errors="replace").strip()
        return out.splitlines()[0].strip() if out else ""
    except (OSError, subprocess.SubprocessError):
        return ""


# ── 镜像源命令 ──
# v3.05.07: 抽成常量，upgrade.py 的「加速源」按钮复用，避免两处各写一份
MIRROR_CMDS = [
    ("github_proxy", "https://github.bibk.top"),
    ("go_module_proxy", "https://goproxy.cn"),
]


# ── 工作线程 ──
class LipCmdWorker(QThread):
    """后台执行命令，实时流式输出 stdout/stderr。"""
    output = Signal(str, str)
    finished = Signal(int)

    def __init__(self, args: list[str], cwd: str = "", parent=None):
        super().__init__(parent)
        self._args = args
        self._cwd = cwd or os.getcwd()

    def run(self):
        try:
            p = subprocess.Popen(
                self._args, cwd=self._cwd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            for raw_line in p.stdout:
                # lip 输出是 GBK(CP936)；先试 UTF-8，失败用 GBK 兜底
                try:
                    line = raw_line.decode("utf-8")
                except UnicodeDecodeError:
                    line = raw_line.decode("gbk", errors="replace")
                # v3.05.07: 同时去掉 CR —— lip 在 Windows 下输出 CRLF
                line = line.rstrip("\r\n")
                if line:
                    self.output.emit(line, "")
            p.wait()
            self.finished.emit(p.returncode)
        except FileNotFoundError:
            self.output.emit("", "未找到命令行工具")
            self.finished.emit(-1)
        except Exception as e:
            self.output.emit("", str(e))
            self.finished.emit(-1)


class InstallLipWorker(QThread):
    """winget 安装 lip。"""
    line = Signal(str)
    done = Signal(bool)

    # v3.05.07: winget 安装可能因 EULA 交互而挂起，这里设硬超时
    INSTALL_TIMEOUT = 240

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        self.line.emit("lip 未安装，使用 winget 自动安装...")
        if lip_installed():
            self.line.emit("检测到 lip 已存在")
            self.done.emit(True)
            return
        try:
            # v3.05.07: 补全 winget 参数 —— 缺 --accept-package-agreements /
            # --disable-interactivity 时 winget 可能弹交互界面卡住不返回
            p = subprocess.Popen(
                ["winget", "install", "futrime.lip",
                 "--accept-source-agreements",
                 "--accept-package-agreements",
                 "--disable-interactivity"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            deadline = time.time() + self.INSTALL_TIMEOUT
            for raw in p.stdout:
                if self._cancel:
                    p.terminate()
                    self.line.emit("已取消安装")
                    self.done.emit(False)
                    return
                # winget 输出同样是 GBK
                try:
                    ln = raw.decode("utf-8").rstrip()
                except UnicodeDecodeError:
                    ln = raw.decode("gbk", errors="replace").rstrip()
                if ln:
                    self.line.emit(ln)
                if time.time() > deadline:
                    p.kill()
                    self.line.emit(f"安装超时（>{self.INSTALL_TIMEOUT}s）")
                    self.done.emit(False)
                    return
            p.wait()
            ok = lip_installed()
            self.line.emit("lip 就绪" if ok else f"winget 退出码 {p.returncode}")
            self.done.emit(ok)
        except FileNotFoundError:
            self.line.emit("未找到 winget（需 Windows 10 1709+）")
            self.done.emit(False)
        except OSError as e:
            self.line.emit(f"安装出错: {e}")
            self.done.emit(False)
