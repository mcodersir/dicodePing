@echo off
setlocal EnableExtensions
cd /d "%~dp0"
python app_v190_rc13.py
if errorlevel 1 py -3 app_v190_rc13.py
pause
