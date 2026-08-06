@echo off
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
title banbo decoupled duplicate detector
cd /d "%~dp0"
echo Starting decoupled duplicate check...
%PY_CMD% -m banbo.duplicate_cli
echo.
echo Done. Check generated txt file.
pause
