@echo off
setlocal
cd /d "%~dp0"
set "PERIODS="
set /p "PERIODS=请输入多个期数，用空格隔开，例如187 188 189: "
if "%PERIODS%"=="" (
  echo 未输入期数。
  pause
  exit /b 1
)
set "PY_CMD="
py -3 --version >nul 2>nul
if not errorlevel 1 set "PY_CMD=py -3"
if not defined PY_CMD (
  python --version >nul 2>nul
  if not errorlevel 1 set "PY_CMD=python"
)
if not defined PY_CMD (
  echo Cannot find Python. Please install Python and add it to PATH.
  pause
  exit /b 1
)
chcp 65001 >nul
title banbo decoupled multi-period crawler
%PY_CMD% -m banbo.multi_cli --periods %PERIODS%
set "EXIT_CODE=%ERRORLEVEL%"
echo.
echo 多期完成。未更新 recent_10_cache.json。
pause
exit /b %EXIT_CODE%
