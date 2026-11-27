@echo off
setlocal
set "PYTHONUTF8=1"
set "RUN_MODE=mock"
set "EMBEDDING_PROVIDER=hash"
set "AUTH_REQUIRED=false"
set "SHOP_TENANT=local"
set "DB_PATH=data/commerce.sqlite3"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Create the environment first: python -m venv .venv
  echo Then: .venv\Scripts\python.exe -m pip install -r requirements-dev.txt
  exit /b 2
)
cd /d "%~dp0"
"%PY%" scripts\db.py up
if errorlevel 1 exit /b 1
set "PORT=%~1"
if "%PORT%"=="" set "PORT=8027"
echo Open http://127.0.0.1:%PORT%/workbench
"%PY%" -m uvicorn xborder_insight.api:app --app-dir src --host 127.0.0.1 --port %PORT%
