@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Virtual environment not found.
  echo Run: python -m venv .venv
  pause
  exit /b 1
)
echo Starting DeadlineSOS...
start "DeadlineSOS Server" cmd /k ".venv\Scripts\python.exe app.py"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:5000/login"
echo DeadlineSOS opened at http://127.0.0.1:5000/login
exit /b 0
