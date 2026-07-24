@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "CORE=%CD%\local-maven\ir\dicode\local\libv2ray\26.6.2\libv2ray-26.6.2.aar"

if not exist "%CORE%" (
  echo Missing Android core.
  echo Download:
  echo https://github.com/2dust/AndroidLibXrayLite/releases/download/v26.6.2/libv2ray.aar
  echo Rename it to libv2ray-26.6.2.aar and place it at:
  echo %CORE%
  echo.
  echo You can also download it to Downloads and run prepare_core.bat.
  pause
  exit /b 1
)

call gradlew.bat --no-daemon clean :app:assembleDebug
if errorlevel 1 goto :fail
if not exist "release" mkdir "release"
copy /y "app\build\outputs\apk\debug\app-debug.apk" "release\dicodePing-v0.1.2-android-debug.apk" >nul
if errorlevel 1 goto :fail

echo.
echo APK: release\dicodePing-v0.1.2-android-debug.apk
pause
exit /b 0

:fail
echo.
echo Android build failed. Review the message above.
pause
exit /b 1
