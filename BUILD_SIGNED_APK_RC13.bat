@echo off
setlocal EnableExtensions
cd /d "%~dp0"
call dicodePing_android\build_apk_rc13.bat
exit /b %ERRORLEVEL%
