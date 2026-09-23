@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Crush Chat Analyzer

echo ==============================================
echo   Crush Chat Analyzer
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
    echo.
    echo 请先安装 Python 3.10 或更高版本：
    echo https://www.python.org/downloads/
    echo.
    echo 安装时务必勾选 “Add Python to PATH”。
    echo.
    start "" "https://www.python.org/downloads/"
    pause
    exit /b 1
)

echo 使用 Python 命令：%PY_CMD%
%PY_CMD% -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 (
    echo.
    echo [错误] Python 版本过低，需要 3.10 或更高版本。
    echo 当前版本：
    %PY_CMD% --version
    echo.
    pause
    exit /b 1
)

echo 正在启动 Crush Chat Analyzer...
echo.
%PY_CMD% main.py
set "EXIT_CODE=%errorlevel%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo [提示] 程序异常退出，错误码：%EXIT_CODE%
    echo 可以查看 logs\error.log。
    echo.
    pause
)

endlocal & exit /b %EXIT_CODE%
