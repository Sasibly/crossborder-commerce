@echo off
setlocal
set "PYTHONUTF8=1"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Project environment missing. See COMMERCE-README.md.
  exit /b 2
)
cd /d "%~dp0"
"%PY%" scripts\accept_local.py %*
exit /b %errorlevel%
