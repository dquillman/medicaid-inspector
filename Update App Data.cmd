@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title Update App Data - Medicaid Inspector

REM ============================================================
REM  ONE-BUTTON DATA UPDATE (smart)
REM  Double-click anytime. It checks first: if nothing is new it
REM  says "already up to date" and stops; if there's new government
REM  data it downloads it, rebuilds everything, and publishes live.
REM  First run walks you through the free one-time key setup.
REM ============================================================

REM Load the saved key, if there is one.
if not defined HF_TOKEN if exist "hf_token.txt" set /p HF_TOKEN=<hf_token.txt
if not defined HF_TOKEN goto :setup

:run
echo.
echo  Checking what needs updating...
echo  (If new data is found this can take 30-60 minutes. Leave the window open.)
echo.
powershell -ExecutionPolicy Bypass -NoProfile -File "refresh-data.ps1" -Smart
set "RC=!ERRORLEVEL!"
echo.
echo  ============================================================
if "!RC!"=="0" (
  echo   DONE - new data was downloaded, rebuilt, and published live.
) else if "!RC!"=="10" (
  echo   ALREADY UP TO DATE - nothing needed doing. You're all set.
) else if "!RC!"=="2" (
  echo   Your key is missing or expired - let's set it up again.
  echo  ============================================================
  goto :setup
) else (
  echo   STOPPED - something needs attention. Read the messages
  echo   above and send them to Claude. Nothing was broken.
)
echo  ============================================================
echo.
echo  Press any key to close this window...
pause >nul
exit /b !RC!

:setup
echo.
echo  ============================================================
echo   ONE-TIME SETUP - get your free key (about a minute)
echo  ============================================================
echo.
echo   Two web pages will open:
echo     1. KEY page: make a free account if asked, then click
echo        "New token" / "Create new token", choose "Read",
echo        create it, and COPY the key (starts with hf_).
echo     2. DATA page: if it shows an "Agree" button, click it.
echo.
start "" "https://huggingface.co/settings/tokens"
start "" "https://huggingface.co/datasets/HHS-Official/medicaid-provider-spending"
echo   Then come back here, paste the key below (right-click pastes),
echo   and press Enter. Or just close this window to finish later.
echo.
set /p "TOK=Paste your key here: "
if "!TOK!"=="" (
  echo.
  echo  No key entered - no problem. Double-click this button again
  echo  whenever you're ready.
  echo.
  echo  Press any key to close...
  pause >nul
  exit /b 1
)
> hf_token.txt echo !TOK!
set "HF_TOKEN=!TOK!"
echo.
echo  Saved. Starting the update now...
goto :run
