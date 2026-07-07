@echo off
echo === BDS Manager 发布脚本 v2.1.0.10 ===
cd /d "%~dp0"

echo [1/3] 推送到 GitHub...
git push origin main
if %errorlevel% neq 0 (
    echo 推送失败！请检查网络和 Git 配置
    pause
    exit /b 1
)

echo [2/3] 创建 GitHub Release...
"C:\Program Files\GitHub CLI\gh.exe" release create v2.1.0.10 release\bds_manager_v2.1.0.10.zip ^
  --title "v2.1.0.10 架构重构 & ZIP全量更新" ^
  --notes-file release\version.json
if %errorlevel% neq 0 (
    echo Release 创建失败！请先运行 gh auth login 登录
    pause
    exit /b 1
)

echo [3/3] 完成！
echo.
echo Release 地址: https://github.com/TussalZeus18028/bds_manager/releases/tag/v2.1.0.10
start "" https://github.com/TussalZeus18028/bds_manager/releases/tag/v2.1.0.10
pause