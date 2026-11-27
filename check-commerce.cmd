@echo off
setlocal
set "PYTHONUTF8=1"
set "RUN_MODE=mock"
set "EMBEDDING_PROVIDER=hash"
set "AUTH_REQUIRED=false"
cd /d "%~dp0"
.venv\Scripts\python.exe -m pytest -ra
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe scripts\commerce_demo.py
