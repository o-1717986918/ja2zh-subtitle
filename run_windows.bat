@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
  echo Usage: drag a video file onto run_windows.bat, or pass a video path.
  exit /b 2
)
.venv\Scripts\python.exe main.py %*

