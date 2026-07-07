@echo off
setlocal enabledelayedexpansion

REM 切换到项目根目录
cd /d "%~dp0.."

REM 从 version.json 读取版本号
for /f "tokens=2 delims=:," %%a in ('findstr "\"version\"" version.json') do (
    set "VER=%%~a"
    goto :got_ver
)
:got_ver
set "VER=%VER:"=%"
set "VER=%VER: =%"

if "%VER%"=="" (
    echo 错误：无法从 version.json 读取版本号！
    pause
    exit /b 1
)

echo ============================
echo  BDS Manager 发布脚本
echo  版本: v%VER%
echo ============================
echo.

echo [1/3] 推送到 GitHub...
git push origin main
if errorlevel 1 (
    echo 推送失败！请检查网络和 Git 配置
    pause
    exit /b 1
)
echo   √ 推送成功

echo.
echo [2/3] 检查 GitHub CLI...
where gh >nul 2>&1
if errorlevel 1 set "GH=C:\Program Files\GitHub CLI\gh.exe" & goto :gh_found
set "GH=gh"
:gh_found

"%GH%" auth status >nul 2>&1
if errorlevel 1 (
    echo 需要登录 GitHub CLI，打开浏览器...
    "%GH%" auth login --web --hostname github.com
    if errorlevel 1 (
        echo 登录失败，请手动 gh auth login
        pause
        exit /b 1
    )
)

echo.
echo [3/3] 创建 GitHub Release v%VER%...
set "ZIP=release\bds_manager_v%VER%.zip"
if not exist "%ZIP%" (
    echo 错误：找不到 %ZIP%
    echo 请先运行 python build_release.py 打包
    pause
    exit /b 1
)

"%GH%" release create v%VER% "%ZIP%" ^
  --title "v%VER%" ^
  --notes-file release\version.json

if errorlevel 1 (
    echo Release 创建失败！
    pause
    exit /b 1
)

echo.
echo ============================
echo  发布完成 v%VER%
echo  https://github.com/TussalZeus18028/bds_manager/releases/tag/v%VER%
echo ============================
start "" https://github.com/TussalZeus18028/bds_manager/releases/tag/v%VER%
pause