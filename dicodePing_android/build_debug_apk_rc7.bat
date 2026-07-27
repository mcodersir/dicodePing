@echo off
setlocal EnableExtensions
cd /d "%~dp0"
call gradlew.bat --no-daemon :app:assembleStandardDebug
if errorlevel 1 goto :fail
if not exist "release" mkdir "release"
copy /y "app\build\outputs\apk\standard\debug\app-standard-debug.apk" "release\dicodePing-v1.9.0-rc.7-android-standard-debug-test.apk" >nul
if errorlevel 1 goto :fail
echo.
echo Android debug/test APK created with the standard Android debug key:
echo   release\dicodePing-v1.9.0-rc.7-android-standard-debug-test.apk
pause
exit /b 0
:fail
echo Android debug APK build failed.
pause
exit /b 1
