#!/bin/bash
set -e
cd "$(dirname "$0")"

# 检查 Python 3
if ! command -v python3 &>/dev/null; then
    echo "请先安装 Python 3.10+ : sudo apt install python3 python3-pip python3-venv"
    exit 1
fi

# 自动安装缺失依赖
if ! python3 -c "import PySide6" 2>/dev/null; then
    echo "安装运行依赖..."
    python3 -m pip install --user PySide6 qfluentwidgets psutil requests
fi

echo "启动 BDS Manager..."
python3 main.py
