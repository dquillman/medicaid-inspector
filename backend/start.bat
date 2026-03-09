@echo off
cd /d "%~dp0"
G:\Python311\python.exe -m pip install -r requirements.txt
G:\Python311\python.exe -m uvicorn main:app --port 8001
