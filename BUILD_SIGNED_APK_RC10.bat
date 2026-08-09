@echo off
setlocal EnableExtensions
cd /d "%~dp0"
call dicodePing_android\build_apk_rc10.bat
exit /b %ERRORLEVEL%
