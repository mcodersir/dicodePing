@echo off
setlocal
cd /d "%~dp0"
call gradlew.bat --no-daemon clean assembleStandardRelease
if errorlevel 1 exit /b %errorlevel%
if not exist release mkdir release
copy /y "app\build\outputs\apk\standard\release\app-standard-release.apk" "release\dicodePing-v1.9.0-rc.14-android.apk" >nul
echo Built release\dicodePing-v1.9.0-rc.14-android.apk
endlocal
