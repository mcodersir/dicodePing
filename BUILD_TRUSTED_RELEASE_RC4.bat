@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"

if not defined DICODEPING_SIGN_PFX if not defined DICODEPING_SIGN_SHA1 if not defined DICODEPING_SIGN_SUBJECT (
  echo No trusted Authenticode certificate is configured.
  echo.
  echo Configure one of these before running this file:
  echo   DICODEPING_SIGN_PFX      and DICODEPING_SIGN_PASSWORD
  echo   DICODEPING_SIGN_SHA1
  echo   DICODEPING_SIGN_SUBJECT
  echo.
  echo A self-signed certificate does not solve Smart App Control reputation.
  pause
  exit /b 1
)

set "PYTHON_EXE="
set "PYTHON_ARG="
python --version >nul 2>nul && set "PYTHON_EXE=python"
if not defined PYTHON_EXE (
  py -3 --version >nul 2>nul && set "PYTHON_EXE=py" && set "PYTHON_ARG=-3"
)
if not defined PYTHON_EXE goto no_python

call :run -m pip install -r requirements-build.txt
if errorlevel 1 goto failed
call :run tools\verify_version.py --tag v1.9.0-rc.4
if errorlevel 1 goto failed
call :run -m pytest -q
if errorlevel 1 goto failed
call :run tools\quality_gate.py
if errorlevel 1 goto failed
call :run tools\build_windows.py --skip-install --require-signing
if errorlevel 1 goto failed

echo.
echo Trusted signed RC4 package created in the release folder.
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
pause
exit /b 1

:failed
echo.
echo Trusted release build failed. Read the first error above.
pause
exit /b 1
