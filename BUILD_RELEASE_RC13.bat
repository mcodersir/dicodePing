@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"

set "PYTHON_EXE="
set "PYTHON_ARG="
py -3.12 --version >nul 2>nul && set "PYTHON_EXE=py" && set "PYTHON_ARG=-3.12"
if not defined PYTHON_EXE (
  python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>nul && set "PYTHON_EXE=python"
)
if not defined PYTHON_EXE goto no_python

echo [0/7] Cleaning stale files from older extracted versions...
call :run tools\prepare_build_workspace.py
if errorlevel 1 goto failed

echo [1/7] Installing build requirements...
call :run -m pip install --upgrade pip
if errorlevel 1 goto failed
call :run -m pip install -r requirements-build.txt
if errorlevel 1 goto failed

echo [2/7] Checking version metadata...
call :run tools\verify_version.py --tag v1.9.0-rc.13
if errorlevel 1 goto failed

echo [3/7] Running tests...
call :run -m pytest -q
if errorlevel 1 goto failed

echo [4/7] Running quality checks...
call :run tools\quality_gate.py
if errorlevel 1 goto failed

echo [5/7] Validating Android project...
call :run dicodePing_android\tools\validate_project.py
if errorlevel 1 goto failed

echo [6/7] Building legacy-style portable Windows EXE...
call :run tools\build_windows.py --skip-install
if errorlevel 1 goto failed

echo.
echo ==============================================================
echo RC13 legacy-style Windows build completed:
echo   release\dicodePing-v1.9.0-rc.13-windows-x64.exe
echo.
echo Android signed APK:
echo   BUILD_SIGNED_APK_RC13.bat
echo.
echo Windows + Linux + macOS + Android release assets:
echo   Run workflow: .github\workflows\v1.9.0-rc.13-release.yml
echo ==============================================================
pause
exit /b 0

:run
if defined PYTHON_ARG (
  "%PYTHON_EXE%" %PYTHON_ARG% %*
) else (
  "%PYTHON_EXE%" %*
)
exit /b %ERRORLEVEL%

:no_python
echo Python 3.12 was not found.
echo Install Python 3.12 x64 and enable the Python launcher.
pause
exit /b 1

:failed
echo.
echo RC13 legacy-style build failed. Read the first error above.
pause
exit /b 1
