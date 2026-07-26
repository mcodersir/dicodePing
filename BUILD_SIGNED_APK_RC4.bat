@echo off
setlocal EnableExtensions
cd /d "%~dp0"
call dicodePing_android\build_apk.bat
exit /b %ERRORLEVEL%
