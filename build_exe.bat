@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"

set "PYTHON_EXE="
set "PYTHON_ARG="

python --version >nul 2>nul
if not errorlevel 1 goto use_python

py -3 --version >nul 2>nul
if not errorlevel 1 goto use_launcher

goto no_python

:use_python
set "PYTHON_EXE=python"
goto run_build

:use_launcher
set "PYTHON_EXE=py"
set "PYTHON_ARG=-3"
goto run_build

:run_build
if defined PYTHON_ARG goto run_with_launcher
"%PYTHON_EXE%" tools\build_windows.py
goto build_finished

:run_with_launcher
"%PYTHON_EXE%" %PYTHON_ARG% tools\build_windows.py

:build_finished
set "BUILD_EXIT=%ERRORLEVEL%"
if not "%BUILD_EXIT%"=="0" goto build_failed

echo.
echo Build completed successfully.
echo Output: release\dicodePing-v0.1.2-windows.exe
pause
exit /b 0

:no_python
echo Python 3.10 or newer was not found.
echo Install Python and enable the Add Python to PATH option.
pause
exit /b 1

:build_failed
echo.
echo Build failed. Review the error shown above.
pause
exit /b %BUILD_EXIT%
