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

if defined PYTHON_ARG (
  "%PYTHON_EXE%" %PYTHON_ARG% -m pip install -r requirements.txt
  if errorlevel 1 goto failed
  "%PYTHON_EXE%" %PYTHON_ARG% app_v190_rc2.py
) else (
  "%PYTHON_EXE%" -m pip install -r requirements.txt
  if errorlevel 1 goto failed
  "%PYTHON_EXE%" app_v190_rc2.py
)
exit /b %ERRORLEVEL%

:no_python
echo Python 3.10 or newer was not found.
pause
exit /b 1

:failed
echo Dependency installation failed.
pause
exit /b 1
