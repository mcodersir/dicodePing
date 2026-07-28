@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

set "VERSION=1.9.0-rc.19"
set "CORE_VERSION=26.7.11"
set "CORE_SHA256=0c79bb52dc4329aaa266601e56ce4f0cc756b43f97a43dccd08d4a4bfc9aa352"
set "CORE_AAR=local-maven\ir\dicode\local\libv2ray\%CORE_VERSION%\libv2ray-%CORE_VERSION%.aar"
set "CORE_URL=https://github.com/2dust/AndroidLibXrayLite/releases/download/v%CORE_VERSION%/libv2ray.aar"

where py >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python launcher was not found.
  exit /b 1
)
where curl >nul 2>&1
if errorlevel 1 (
  echo [ERROR] curl was not found.
  exit /b 1
)

rem Remove stale files left when this ZIP was extracted over an older RC.
py -3 ..\tools\prepare_build_workspace.py --keep-outputs
if errorlevel 1 exit /b 1
py -3 ..\tools\validate_android_source_references.py
if errorlevel 1 exit /b 1

rem Core preparation is part of the build, so Aether/Usque cannot be forgotten.
py -3 tools\prepare_bundled_cores.py
if errorlevel 1 exit /b 1

for %%D in ("%CORE_AAR%") do if not exist "%%~dpD" mkdir "%%~dpD"
if not exist "%CORE_AAR%" goto :download_core
for /f "tokens=1" %%H in ('certutil -hashfile "%CORE_AAR%" SHA256 ^| findstr /R /V "hash CertUtil"') do set "ACTUAL_SHA=%%H"
if /I not "%ACTUAL_SHA%"=="%CORE_SHA256%" goto :download_core
goto :build

:download_core
if exist "%CORE_AAR%" del /f /q "%CORE_AAR%"
curl.exe -fL --retry 4 --retry-delay 2 -o "%CORE_AAR%" "%CORE_URL%"
if errorlevel 1 exit /b 1
for /f "tokens=1" %%H in ('certutil -hashfile "%CORE_AAR%" SHA256 ^| findstr /R /V "hash CertUtil"') do set "ACTUAL_SHA=%%H"
if /I not "%ACTUAL_SHA%"=="%CORE_SHA256%" (
  echo [ERROR] libv2ray SHA-256 mismatch.
  exit /b 1
)

:build
call gradlew.bat --no-daemon clean testStandardDebugUnitTest assembleStandardRelease
if errorlevel 1 exit /b 1
if not exist release mkdir release
copy /y "app\build\outputs\apk\standard\release\app-standard-release.apk" "release\dicodePing-v%VERSION%-android.apk" >nul
if errorlevel 1 exit /b 1
py -3 tools\verify_apk_cores.py "release\dicodePing-v%VERSION%-android.apk"
if errorlevel 1 exit /b 1
echo Built release\dicodePing-v%VERSION%-android.apk
exit /b 0
