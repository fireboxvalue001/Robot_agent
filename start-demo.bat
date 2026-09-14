@echo off
cd /d "%~dp0"
set "PROJECT_PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PROJECT_PY%" (
  echo ASR virtual environment not found.
  echo Run setup-asr.bat first.
  pause
  exit /b 1
)
"%PROJECT_PY%" -c "import socket,sys; s=socket.socket(); r=s.connect_ex(('127.0.0.1',8877)); s.close(); sys.exit(0 if r == 0 else 1)"
if not errorlevel 1 (
  echo Port 8877 is already in use. The demo may already be running.
  echo Open http://127.0.0.1:8877 in your browser.
  exit /b 0
)
"%PROJECT_PY%" -m uvicorn backend.server:app --host 127.0.0.1 --port 8877
