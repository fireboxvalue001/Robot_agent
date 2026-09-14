@echo off
setlocal
cd /d "%~dp0"
set "BASE_PY=%~dp0..\..\..\agent\.venv\Scripts\python.exe"
if not exist "%BASE_PY%" (
  set "BASE_PY="
  where py >nul 2>&1
  if not errorlevel 1 set "BASE_PY=py"
)
if not defined BASE_PY (
  where python >nul 2>&1
  if not errorlevel 1 set "BASE_PY=python"
)
if not defined BASE_PY (
  echo Python launcher was not found. Install Python 3.10 or newer first.
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  "%BASE_PY%" -m venv .venv
)
".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt
if errorlevel 1 exit /b 1
echo.
echo ASR environment is ready.
echo Configure backend\.env, then run start-demo.bat.
