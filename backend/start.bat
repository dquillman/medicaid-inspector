@echo off
cd /d "%~dp0"
pip install -r requirements.txt
python -m uvicorn main:app --port 8001
