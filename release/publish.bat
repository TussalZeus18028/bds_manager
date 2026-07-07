@echo off
setlocal enabledelayedexpansion
echo === BDS Manager 发布脚本 v2.1.0.10 ===

REM 切换到项目根目录（脚本在 release/ 子目录）
cd /d "%~dp0.."

echo [1/3] 推送到 GitHub...
git push origin main
if errorlevel 1 (
    echo 推送失败！请检查网络和 Git 配置
    pause
    exit /b 1
)

echo [2/3] 检查 GitHub CLI 登录状态...
"C:\Program Files\GitHub CLI\gh.exe" auth status >nul 2>&1
if errorlevel 1 (
    echo 需要先登录 GitHub CLI，将打开浏览器...
    "C:\Program Files\GitHub CLI\gh.exe" auth login --web --hostname github.com
    if errorlevel 1 (
        echo 登录取消或失败，请手动运行 gh auth login 后再试
        pause
        exit /b 1
    )
)

echo [3/3] 创建 GitHub Release...
"C:\Program Files\GitHub CLI\gh.exe" release create v2.1.0.10 release\bds_manager_v2.1.0.10.zip --title "v2.1.0.10" --notes-file release\version.json
if errorlevel 1 (
    echo Release 创建失败！
    pause
    exit /b 1
)

echo.
echo === 发布完成 ===
echo https://github.com/TussalZeus18028/bds_manager/releases/tag/v2.1.0.10
start "" https://github.com/TussalZeus18028/bds_manager/releases/tag/v2.1.0.10
pause