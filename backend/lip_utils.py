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

from PySide6.QtCore import QThread, Signal


# ── 检测 ──
_LIP_PATHS = [
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\futrime.lip_*\lip.exe"),
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


# ── 镜像源命令 ──
MIRROR_CMDS = [
    ("github_proxy", "https://github.bibk.top"),
    ("go_module_proxy", "https://goproxy.cn"),
]


def setup_mirrors(lip_exe: str) -> bool:
    """配置 lip 加速源，成功返回 True。"""
    ok = True
    for key, val in MIRROR_CMDS:
        r = subprocess.run([lip_exe, "config", "set", key, val],
                           capture_output=True, text=True, timeout=15)
        if r.returncode != 0:
            ok = False
    return ok


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
                encoding="utf-8", errors="replace", bufsize=1,
            )
            for line in p.stdout:
                line = line.rstrip("\n")
                if line:
                    self.output.emit(line, "")
            p.wait()
            self.finished.emit(p.returncode)
        except FileNotFoundError:
            self.output.emit("", "未找到命令行工具")
            self.finished.emit(-1)
        except OSError as e:
            self.output.emit("", str(e))
            self.finished.emit(-1)


class InstallLipWorker(QThread):
    """winget 安装 lip。"""
    line = Signal(str)
    done = Signal(bool)

    def run(self):
        self.line.emit("lip 未安装，使用 winget 自动安装...")
        if lip_installed():
            self.line.emit("检测到 lip 已存在")
            self.done.emit(True)
            return
        try:
            p = subprocess.Popen(
                ["winget", "install", "futrime.lip", "--accept-source-agreements"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, encoding="utf-8", errors="replace",
            )
            for raw in p.stdout:
                ln = raw.rstrip()
                if ln:
                    self.line.emit(ln)
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
