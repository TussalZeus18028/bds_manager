@echo off
chcp 65001 >nul
if "%1"=="-v" (
    type version.json 2>nul | python -c "import sys,json; d=json.load(sys.stdin); print(f'BDS Manager v{d[\"version\"]} ({d.get(\"codename\",\"\")})')"
    exit /b
)
python main.py
pause
