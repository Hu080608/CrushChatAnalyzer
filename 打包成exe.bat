@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Crush Chat Analyzer - 打包成 exe

echo ==============================================
echo   Crush Chat Analyzer - 打包成 exe
echo   制作者：胡胜杰
echo ==============================================
echo.

set "PY_CMD="
where py >nul 2>nul
if %errorlevel%==0 set "PY_CMD=py -3"

if not defined PY_CMD (
    where python >nul 2>nul
    if not errorlevel 1 set "PY_CMD=python"
)

if not defined PY_CMD (
    echo [错误] 没有检测到 Python。
    pause
    exit /b 1
)

echo [1/2] 检查 PyInstaller...
%PY_CMD% -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
    echo 正在安装 PyInstaller...
    %PY_CMD% -m pip install pyinstaller
    if errorlevel 1 (
        echo PyInstaller 安装失败，请检查网络。
        pause
        exit /b 1
    )
)

echo [2/2] 开始打包（版本会自动 +1）...
%PY_CMD% build_exe.py
if errorlevel 1 (
    echo.
    echo 打包失败，请查看上面的错误信息。
    pause
    exit /b 1
)

echo.
echo 打包完成，文件在 dist 目录。
pause
endlocal
