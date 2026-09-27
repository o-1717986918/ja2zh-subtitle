@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" (
  echo Usage: drag a Japanese video file onto run_japanese_windows.bat.
  exit /b 2
)
.venv\Scripts\python.exe main.py %* --ja-only
