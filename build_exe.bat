@echo off
setlocal
cd /d "%~dp0"
call BUILD_RELEASE_RC4.bat
exit /b %ERRORLEVEL%
