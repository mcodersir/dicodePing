@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
rem PREPARE_V3_RUNTIME.bat invokes tools\package_complete_v3.py after runtime verification.
call PREPARE_V3_RUNTIME.bat
exit /b %errorlevel%
