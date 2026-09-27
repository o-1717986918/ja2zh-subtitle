@echo off
setlocal
cd /d "%~dp0"
if exist "D:\miniconda\envs\ja2zh-subtitle\python.exe" (
  "D:\miniconda\envs\ja2zh-subtitle\python.exe" webui.py
) else (
  python webui.py
)
endlocal
