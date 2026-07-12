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
goto install_and_run

:use_launcher
set "PYTHON_EXE=py"
set "PYTHON_ARG=-3"
goto install_and_run

:install_and_run
if defined PYTHON_ARG goto install_with_launcher
"%PYTHON_EXE%" -m pip install -r requirements.txt
if errorlevel 1 goto run_failed
"%PYTHON_EXE%" app.py
goto app_finished

:install_with_launcher
"%PYTHON_EXE%" %PYTHON_ARG% -m pip install -r requirements.txt
if errorlevel 1 goto run_failed
"%PYTHON_EXE%" %PYTHON_ARG% app.py

:app_finished
set "APP_EXIT=%ERRORLEVEL%"
exit /b %APP_EXIT%

:no_python
echo Python 3.10 or newer was not found.
echo Install Python and enable the Add Python to PATH option.
pause
exit /b 1

:run_failed
echo.
echo Project startup failed. Review the error shown above.
pause
exit /b 1
