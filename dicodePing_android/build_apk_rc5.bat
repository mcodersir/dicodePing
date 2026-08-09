@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"

set "CORE=%CD%\local-maven\ir\dicode\local\libv2ray\26.7.11\libv2ray-26.7.11.aar"
if not exist "%CORE%" (
  echo Missing verified Android core: %CORE%
  echo Run prepare_core.bat after downloading the pinned upstream AAR.
  pause
  exit /b 1
)

for %%V in (ANDROID_KEYSTORE_PATH ANDROID_KEYSTORE_PASSWORD ANDROID_KEY_ALIAS ANDROID_KEY_PASSWORD) do (
  if not defined %%V (
    echo Missing APK signing variable: %%V
    echo See ..\docs\ANDROID_SECURITY_DISTRIBUTION.md
    pause
    exit /b 1
  )
)

call gradlew.bat --no-daemon clean :app:lintStandardRelease :app:testStandardReleaseUnitTest :app:assembleStandardRelease
if errorlevel 1 goto :fail

if not exist "release" mkdir "release"
copy /y "app\build\outputs\apk\standard\release\app-standard-release.apk" "release\dicodePing-v1.9.0-rc.5-android.apk" >nul
if errorlevel 1 goto :fail

set "APKSIGNER="
for /f "delims=" %%F in ('where apksigner.bat 2^>nul') do if not defined APKSIGNER set "APKSIGNER=%%F"
if defined APKSIGNER (
  call "%APKSIGNER%" verify --verbose --print-certs "release\dicodePing-v1.9.0-rc.5-android.apk"
  if errorlevel 1 goto :fail
) else (
  echo Warning: apksigner was not found in PATH; Gradle signing completed but external verification was skipped.
)

certutil -hashfile "release\dicodePing-v1.9.0-rc.5-android.apk" SHA256 > "release\dicodePing-v1.9.0-rc.5-android.apk.sha256.txt"

echo.
echo Signed APK created:
echo   release\dicodePing-v1.9.0-rc.5-android.apk
echo No AAB or signed desktop package was generated.
pause
exit /b 0

:fail
echo.
echo Android signed APK build failed. Read the first error above.
pause
exit /b 1
