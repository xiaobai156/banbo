@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_banbo_v2.ps1"
set "exit_code=%ERRORLEVEL%"
echo.
echo Done. Press any key to continue . . .
pause >nul
exit /b %exit_code%
