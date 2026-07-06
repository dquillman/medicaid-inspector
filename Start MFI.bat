@echo off
REM Double-click this to launch the whole Medicaid Inspector stack
REM (backend + frontend + the HAL assistant) and open it in your browser.
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0start-mfi.ps1"
