@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set "VERSION=3.0.0-pre.3"
where py >nul 2>&1 || (echo [ERROR] Python launcher was not found.& exit /b 1)
py -3 ..\tools\prepare_build_workspace.py --keep-outputs || exit /b 1
py -3 ..\tools\validate_android_source_references.py || exit /b 1
py -3 ..\tools\validate_android_release.py || exit /b 1
py -3 ..\tools\prepare_vazirmatn.py --android || exit /b 1
py -3 ..\tools\fetch_runtime_assets.py --android || exit /b 1
call gradlew.bat --no-daemon --warning-mode=fail clean testStandardDebugUnitTest lintStandardRelease assembleStandardRelease || exit /b 1
if not exist release mkdir release
copy /y "app\build\outputs\apk\standard\release\app-standard-release.apk" "release\dicodePing-v%VERSION%-android.apk" >nul || exit /b 1
py -3 tools\verify_apk_cores.py "release\dicodePing-v%VERSION%-android.apk" || exit /b 1
py -3 tools\verify_apk_fonts.py "release\dicodePing-v%VERSION%-android.apk" || exit /b 1
echo Built release\dicodePing-v%VERSION%-android.apk
exit /b 0
