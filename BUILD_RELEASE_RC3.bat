@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"

set "PYTHON_EXE="
set "PYTHON_ARG="
python --version >nul 2>nul && set "PYTHON_EXE=python"
if not defined PYTHON_EXE (
  py -3 --version >nul 2>nul && set "PYTHON_EXE=py" && set "PYTHON_ARG=-3"
)
if not defined PYTHON_EXE goto no_python

call :run -m pip install --upgrade pip
if errorlevel 1 goto failed
call :run -m pip install -r requirements-build.txt
if errorlevel 1 goto failed
call :run tools\verify_version.py --tag v1.9.0-rc.3
if errorlevel 1 goto failed
call :run -m pytest -q
if errorlevel 1 goto failed
call :run tools\quality_gate.py
if errorlevel 1 goto failed
call :run tools\build_windows.py --skip-install
if errorlevel 1 goto failed

echo.
echo ===============================================
echo Release build completed successfully.
echo Output: release\dicodePing-v1.9.0-rc.3-windows-x64.exe
echo ===============================================
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
echo Python 3.10 or newer was not found.
echo Install Python and enable "Add Python to PATH".
pause
exit /b 1

:failed
echo.
echo Release build failed. Read the first error above.
pause
exit /b 1
