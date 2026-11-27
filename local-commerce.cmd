@echo off
setlocal
set "PYTHONUTF8=1"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Project environment missing. See COMMERCE-README.md to install dependencies.
  exit /b 2
)
if "%~1"=="" (
  echo Usage: local-commerce.cmd deploy ^| start ^| status ^| verify ^| stop ^| logs
  exit /b 2
)
cd /d "%~dp0"
"%PY%" scripts\commerce_local.py %*
exit /b %errorlevel%
