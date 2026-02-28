@echo off
title Medicaid Inspector
echo ============================================
echo   Medicaid Inspector - Starting Services
echo ============================================
echo.

:: Start backend
echo Starting backend server (port 8000)...
cd /d "%~dp0backend"
start "MI Backend" cmd /k "uvicorn main:app --reload --port 8000"

:: Start frontend
echo Starting frontend server (port 5200)...
cd /d "%~dp0frontend"
start "MI Frontend" cmd /k "npx vite --host"

:: Wait for frontend to be ready, then open browser
echo Waiting for servers to start...
timeout /t 5 /nobreak >nul
start http://localhost:5200

echo.
echo Servers are running:
echo   Backend:  http://localhost:8000
echo   Frontend: http://localhost:5200
echo.
echo Close this window or press any key to exit.
pause >nul
