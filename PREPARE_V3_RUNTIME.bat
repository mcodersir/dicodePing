@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

where py >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python 3 is required for runtime verification and packaging.
  echo Install Python 3 or make sure the "py" launcher is in PATH.
  exit /b 1
)

echo dicodePing 3.0.0-pre.1 - Offline runtime verification and complete package builder
echo.
py -3 tools\fetch_runtime_assets.py --verify-only
if errorlevel 1 (
  echo.
  echo [ERROR] One or more pinned runtime files are missing or invalid.
  echo This script never downloads anything.
  echo Run REPAIR_V3_RUNTIME.bat once to restore the exact pinned runtime set,
  echo then run PREPARE_V3_RUNTIME.bat again.
  exit /b 1
)

echo.
echo Runtime set is checksum-verified. Building complete offline package...
py -3 -m tools.package_complete_v3 --verify-output
if errorlevel 1 (
  echo.
  echo [ERROR] Runtime verification succeeded, but complete ZIP packaging failed.
  echo Review the error above. No partial package should be used.
  exit /b 1
)

echo.
echo [OK] Complete Version 3 package is ready:
echo      dist\dicodePing-3.0.0-pre.1-complete.zip
echo.
echo This ZIP includes all pinned Xray, sing-box, Wintun and Android runtime files.
echo No network access was used while packaging.
exit /b 0
