@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

where py >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python 3 is required.
  echo Install Python 3 or make sure the "py" launcher is in PATH.
  exit /b 1
)

echo dicodePing 3.0.0-pre.2 - Runtime repair/download
echo.
py -3 tools\fetch_runtime_assets.py
if errorlevel 1 (
  echo.
  echo [ERROR] Runtime repair did not complete.
  echo.
  echo Diagnostics:
  py -3 tools\fetch_runtime_assets.py --diagnose
  echo.
  echo Offline source folder is also supported:
  echo   set DICODEPING_RUNTIME_SOURCE_DIR=D:\path\to\runtime-files
  echo   REPAIR_V3_RUNTIME.bat
  echo.
  exit /b 1
)

echo.
echo Version 3 runtime assets are ready and checksum-verified.
exit /b 0
