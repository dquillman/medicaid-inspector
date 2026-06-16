@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Check For New Data - Medicaid Inspector

REM Quick, safe check: is there newer government data than what's live?
REM Downloads nothing, changes nothing.

if not defined HF_TOKEN if exist "hf_token.txt" set /p HF_TOKEN=<hf_token.txt

echo.
echo  Checking the government source for a newer release...
echo.
powershell -ExecutionPolicy Bypass -NoProfile -File "refresh-data.ps1" -CheckSource
echo.
echo  ------------------------------------------------------------
echo  If it says NEW AVAILABLE, double-click "Update App Data" next.
echo  If it says UP TO DATE, you're all set - nothing to do.
echo  ------------------------------------------------------------
echo.
echo  Press any key to close this window...
pause >nul
