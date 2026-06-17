@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Update App Data - Medicaid Inspector

REM ============================================================
REM  ONE-BUTTON DATA UPDATE (smart)
REM  Double-click anytime. It checks first: if nothing is new it
REM  says "already up to date" and stops; if there's new government
REM  data it downloads it, rebuilds everything, and publishes live.
REM ============================================================

REM Load the saved Hugging Face token (paste it once into hf_token.txt).
if not defined HF_TOKEN if exist "hf_token.txt" set /p HF_TOKEN=<hf_token.txt

if not defined HF_TOKEN goto :needtoken

echo.
echo  Checking what needs updating...
echo  (If new data is found this can take 30-60 minutes. Leave the window open.)
echo.
powershell -ExecutionPolicy Bypass -NoProfile -File "refresh-data.ps1" -Smart
set "RC=%ERRORLEVEL%"
echo.
echo  ============================================================
if "%RC%"=="0" (
  echo   DONE - new data was downloaded, rebuilt, and published live.
) else if "%RC%"=="10" (
  echo   ALREADY UP TO DATE - nothing needed doing. You're all set.
) else if "%RC%"=="2" (
  echo   SETUP NEEDED - your Hugging Face key is missing or expired.
  echo   Opening the setup pages...
  echo  ============================================================
  goto :needtoken
) else (
  echo   STOPPED - something needs attention. Read the messages
  echo   above and send them to Claude. Nothing was broken.
)
echo  ============================================================
echo.
echo  Press any key to close this window...
pause >nul
exit /b %RC%

:needtoken
echo.
echo  ============================================================
echo   FIRST-TIME SETUP (only needed once)
echo  ============================================================
echo.
echo   The government data lives on a site called Hugging Face.
echo   You need a free "key" so this button can download it.
echo.
echo   Two web pages will open now:
echo     1. Token page - sign in (or make a free account),
echo        create a token (choose "Read"), and copy it.
echo     2. Dataset page - if it asks you to agree to terms, click agree.
echo.
echo   Then: paste your copied token into the file named
echo         hf_token.txt   in this same folder, and save.
echo.
echo   After that, just double-click this button again.
echo.
start "" "https://huggingface.co/settings/tokens"
start "" "https://huggingface.co/datasets/HHS-Official/medicaid-provider-spending"
echo  Press any key to close this window...
pause >nul
exit /b 1
