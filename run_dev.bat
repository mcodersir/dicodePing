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
goto validate_and_run

:use_launcher
set "PYTHON_EXE=py"
set "PYTHON_ARG=-3"
goto validate_and_run

:validate_and_run
if defined PYTHON_ARG goto launcher_path
"%PYTHON_EXE%" -m pip install -r requirements.txt || goto run_failed
"%PYTHON_EXE%" tools\validate_v3.py || goto run_failed
"%PYTHON_EXE%" app.py
goto app_finished

:launcher_path
"%PYTHON_EXE%" %PYTHON_ARG% -m pip install -r requirements.txt || goto run_failed
"%PYTHON_EXE%" %PYTHON_ARG% tools\validate_v3.py || goto run_failed
"%PYTHON_EXE%" %PYTHON_ARG% app.py

:app_finished
exit /b %ERRORLEVEL%

:no_python
echo Python 3.12 or newer was not found.
echo Install Python and enable the Add Python to PATH option.
exit /b 1

:run_failed
echo.
echo Version 3 startup validation failed. Review the error shown above.
exit /b 1
