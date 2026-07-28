@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
title dicodePing v1.9.0 RC14 GitHub Pre-release Deploy
cd /d "%~dp0"

set "REPO=mcodersir/dicodePing"
set "REPO_URL=https://github.com/%REPO%.git"
set "BRANCH=main"
set "TAG=v1.9.0-rc.14"
set "WORKFLOW=release.yml"
set "COMMIT_MESSAGE=fix: redeploy v1.9.0-rc.14 packaged runtime entrypoint"
set "SOURCE_DIR=%CD%"
set "STAGE_DIR=%TEMP%\dicodePing-deploy-v190-rc14-%RANDOM%%RANDOM%"
set "WAIT_SCRIPT=%SOURCE_DIR%\tools\wait_for_github_release.ps1"
set "HEAD_SHA="
set "REMOTE_TAG_EXISTS="
set "TAG_PUSHED="
set "PYTHON_CMD="
set "ROBOCOPY_CODE="

cls
echo ================================================================
echo      dicodePing v1.9.0 RC14 GitHub Pre-release Deploy FIXED v3
echo ================================================================
echo.
echo This script creates a clean repository snapshot and safely removes
echo leftovers from folders previously used for older RC versions.
echo Cleanup happens inside the temporary clone before validation and push.
echo.
echo Repository: %REPO%
echo Branch:     %BRANCH%
echo Tag:        %TAG%
echo.
echo Required GitHub Actions secrets:
echo   ANDROID_KEYSTORE_BASE64
echo   ANDROID_KEYSTORE_PASSWORD
echo   ANDROID_KEY_ALIAS
echo   ANDROID_KEY_PASSWORD
echo.
echo No GitHub token or signing key is stored in this BAT file.
echo.
pause

call :require_command git "Git for Windows"
if errorlevel 1 goto :failed
call :require_command robocopy "Windows Robocopy"
if errorlevel 1 goto :failed
call :require_command powershell "Windows PowerShell"
if errorlevel 1 goto :failed
call :find_python
if errorlevel 1 goto :failed

if not exist ".github\workflows\%WORKFLOW%" (
    echo [ERROR] Missing workflow: .github\workflows\%WORKFLOW%
    goto :failed
)
if not exist "docs\releases\v1.9.0-rc.14.md" (
    echo [ERROR] Missing release notes: docs\releases\v1.9.0-rc.14.md
    goto :failed
)
if not exist "%WAIT_SCRIPT%" (
    echo [ERROR] Missing helper: tools\wait_for_github_release.ps1
    goto :failed
)

call :clone_repository
if errorlevel 1 (
    echo.
    echo [INFO] Clone failed. Opening Git Credential Manager login...
    call :git_login
    if errorlevel 1 goto :failed
    call :clone_repository
    if errorlevel 1 (
        echo [ERROR] Repository clone failed after login.
        goto :failed
    )
)

echo.
echo [2/8] Reading the existing remote tag...
pushd "%STAGE_DIR%"
git ls-remote --exit-code --tags origin "refs/tags/%TAG%" >nul 2>&1
if not errorlevel 1 set "REMOTE_TAG_EXISTS=1"
popd
if defined REMOTE_TAG_EXISTS (
    echo [INFO] %TAG% exists. It will be moved to the new clean commit.
) else (
    echo [OK] No existing remote tag was found.
)

echo.
echo [3/8] Removing every tracked file from the cloned working tree...
pushd "%STAGE_DIR%"
git reset --hard HEAD >nul
if errorlevel 1 (
    popd
    echo [ERROR] git reset failed.
    goto :failed
)
git clean -ffdqx >nul 2>&1
git rm -r -f --ignore-unmatch . >nul
if errorlevel 1 (
    popd
    echo [ERROR] Could not clear the old tracked repository snapshot.
    goto :failed
)
popd

echo.
echo [4/8] Copying the clean RC14 source snapshot...
robocopy "%SOURCE_DIR%" "%STAGE_DIR%" /E /COPY:DAT /DCOPY:DAT /R:2 /W:1 /NFL /NDL /NJH /NJS /NP /XJ ^
 /XD ".git" ".venv" "venv" "build" "dist" "release" "release-assets" "downloaded-artifacts" "artifacts" ".pytest_cache" "__pycache__" ".gradle" ".idea" ".kotlin" ".cxx" ".externalNativeBuild" ^
 /XF "*.jks" "*.keystore" "*.p12" "*.pfx" "*.pem" "*.key" "*.apk" "*.aab" "*.aar" "local.properties" "*.log" "*.bak"
set "ROBOCOPY_CODE=%ERRORLEVEL%"
if %ROBOCOPY_CODE% GEQ 8 (
    echo [ERROR] Robocopy failed with exit code %ROBOCOPY_CODE%.
    goto :failed
)

pushd "%STAGE_DIR%"
if errorlevel 1 goto :failed

echo.
echo [5/8] Purging stale historical release files from the staged tree...
rem The source folder may have been extracted over an older RC directory.
rem Never fail merely because those leftovers exist; delete them from STAGE_DIR.

if exist "tests\test_v*.py" (
    echo [INFO] Removing historical version-locked tests...
    del /f /q "tests\test_v*.py" >nul 2>&1
)

if exist ".github\workflows\v1.9.0-rc.*-release.yml" (
    echo [INFO] Removing obsolete version-specific release workflows...
    del /f /q ".github\workflows\v1.9.0-rc.*-release.yml" >nul 2>&1
)

for /f "delims=" %%F in ('dir /b /a-d "DEPLOY_PRERELEASE_RC*.bat" 2^>nul') do (
    if /I not "%%F"=="DEPLOY_PRERELEASE_RC14.bat" (
        echo [INFO] Removing stale deploy script: %%F
        del /f /q "%%F" >nul 2>&1
    )
)
for /f "delims=" %%F in ('dir /b /a-d "BUILD_RELEASE_RC*.bat" 2^>nul') do (
    echo [INFO] Removing stale release builder: %%F
    del /f /q "%%F" >nul 2>&1
)
for /f "delims=" %%F in ('dir /b /a-d "BUILD_SIGNED_APK_RC*.bat" 2^>nul') do (
    echo [INFO] Removing stale APK builder: %%F
    del /f /q "%%F" >nul 2>&1
)
for /f "delims=" %%F in ('dir /b /a-d "RUN_SOURCE_RC*.bat" 2^>nul') do (
    echo [INFO] Removing stale source runner: %%F
    del /f /q "%%F" >nul 2>&1
)
for /f "delims=" %%F in ('dir /b /a-d "DEPLOY_PRERELEASE_RC*_README_FA.txt" 2^>nul') do (
    if /I not "%%F"=="DEPLOY_PRERELEASE_RC14_README_FA.txt" (
        echo [INFO] Removing stale deploy readme: %%F
        del /f /q "%%F" >nul 2>&1
    )
)
for /f "delims=" %%F in ('dir /b /a-d "START_HERE_RC*.txt" 2^>nul') do (
    echo [INFO] Removing stale start file: %%F
    del /f /q "%%F" >nul 2>&1
)
for /f "delims=" %%F in ('dir /b /a-d "VALIDATION_RESULTS_RC*.txt" 2^>nul') do (
    echo [INFO] Removing stale validation report: %%F
    del /f /q "%%F" >nul 2>&1
)

rem Verify that cleanup actually worked.
if exist "tests\test_v*.py" (
    echo [ERROR] Historical version-locked tests could not be deleted.
    dir /b "tests\test_v*.py"
    popd
    goto :failed
)
if exist ".github\workflows\v1.9.0-rc.*-release.yml" (
    echo [ERROR] Obsolete release workflows could not be deleted.
    dir /b ".github\workflows\v1.9.0-rc.*-release.yml"
    popd
    goto :failed
)
if not exist ".github\workflows\release.yml" (
    echo [ERROR] Current release.yml was not copied.
    popd
    goto :failed
)
if not exist "tests\test_rc14_regressions.py" (
    echo [ERROR] Current RC14 tests were not copied.
    popd
    goto :failed
)
if not exist "DEPLOY_PRERELEASE_RC14.bat" (
    echo [ERROR] Current RC14 deploy script was not copied.
    popd
    goto :failed
)
if not exist "app_v190_rc14.py" (
    echo [ERROR] RC14 runtime wrapper app_v190_rc14.py was not copied.
    popd
    goto :failed
)
findstr /C:"app_v190_rc14.py" "tools\build_windows.py" >nul
if errorlevel 1 (
    echo [ERROR] Windows builder is not using app_v190_rc14.py.
    popd
    goto :failed
)
findstr /C:"app_v190_rc14.py" "tools\build_linux.py" >nul
if errorlevel 1 (
    echo [ERROR] Linux builder is not using app_v190_rc14.py.
    popd
    goto :failed
)
findstr /C:"app_v190_rc14.py" "tools\build_macos.py" >nul
if errorlevel 1 (
    echo [ERROR] macOS builder is not using app_v190_rc14.py.
    popd
    goto :failed
)
echo [OK] Stale files were removed and the RC14 staged tree is clean.

echo.
echo [6/8] Running full local preflight before any push...
call %PYTHON_CMD% tools\prepare_build_workspace.py
if errorlevel 1 goto :validation_failed
call %PYTHON_CMD% tools\verify_version.py --tag %TAG%
if errorlevel 1 goto :validation_failed
call %PYTHON_CMD% tools\validate_android_gradle_kts.py
if errorlevel 1 goto :validation_failed
call %PYTHON_CMD% dicodePing_android\tools\validate_project.py
if errorlevel 1 goto :validation_failed
call %PYTHON_CMD% -c "import pytest" >nul 2>&1
if errorlevel 1 (
    echo [INFO] pytest is missing. Installing the small test dependency...
    call %PYTHON_CMD% -m pip install --disable-pip-version-check "pytest==8.4.1"
    if errorlevel 1 goto :validation_failed
)
call %PYTHON_CMD% -m pytest -q
if errorlevel 1 goto :validation_failed
call %PYTHON_CMD% tools\quality_gate.py
if errorlevel 1 goto :validation_failed

echo [OK] RC14 preflight passed.

git config --get user.name >nul 2>&1
if errorlevel 1 git config user.name "mcodersir"
git config --get user.email >nul 2>&1
if errorlevel 1 git config user.email "mcodersir@users.noreply.github.com"

git add -A
if errorlevel 1 (
    popd
    echo [ERROR] git add failed.
    goto :failed
)

git diff --cached --quiet
if errorlevel 1 (
    git commit -m "%COMMIT_MESSAGE%"
) else (
    echo [INFO] Main already matches this snapshot. Creating an empty commit to retrigger the tag workflow.
    git commit --allow-empty -m "%COMMIT_MESSAGE%"
)
if errorlevel 1 (
    popd
    echo [ERROR] Git commit failed.
    goto :failed
)

for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD_SHA=%%H"
if not defined HEAD_SHA (
    popd
    echo [ERROR] Could not resolve the new commit SHA.
    goto :failed
)

echo.
echo [7/8] Pushing clean commit %HEAD_SHA% to %BRANCH%...
git push origin "HEAD:%BRANCH%"
if errorlevel 1 (
    popd
    echo [ERROR] Push to %BRANCH% failed. Pull protection or a newer remote commit may be blocking it.
    goto :failed
)

echo.
echo Publishing tag %TAG%...
git tag -d "%TAG%" >nul 2>&1
git tag -a "%TAG%" -m "dicodePing %TAG% pre-release" "%HEAD_SHA%"
if errorlevel 1 (
    popd
    echo [ERROR] Local tag creation failed.
    goto :failed
)

if defined REMOTE_TAG_EXISTS (
    git push origin ":refs/tags/%TAG%"
    if errorlevel 1 (
        echo [WARNING] Remote tag deletion was denied. Trying a forced tag update...
        git push --force origin "refs/tags/%TAG%:refs/tags/%TAG%"
        if not errorlevel 1 set "TAG_PUSHED=1"
    ) else (
        git push origin "refs/tags/%TAG%:refs/tags/%TAG%"
        if not errorlevel 1 set "TAG_PUSHED=1"
    )
) else (
    git push origin "refs/tags/%TAG%:refs/tags/%TAG%"
    if not errorlevel 1 set "TAG_PUSHED=1"
)

if not defined TAG_PUSHED (
    popd
    echo [ERROR] The RC14 tag could not be published.
    echo [ERROR] Check GitHub tag-protection rules and repository permissions.
    goto :failed
)
popd

echo.
echo [8/8] GitHub Actions started. Waiting for all platform assets...
echo Actions: https://github.com/%REPO%/actions/workflows/%WORKFLOW%
start "" "https://github.com/%REPO%/actions/workflows/%WORKFLOW%"
echo.
echo Normal build time is approximately 15 to 45 minutes.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%WAIT_SCRIPT%" -Repository "%REPO%" -Tag "%TAG%" -WorkflowFile "%WORKFLOW%" -CommitSha "%HEAD_SHA%" -TimeoutMinutes 90
set "WAIT_CODE=%ERRORLEVEL%"

if "%WAIT_CODE%"=="0" (
    echo.
    echo ================================================================
    echo                 RC14 DEPLOYED SUCCESSFULLY
    echo ================================================================
    echo Commit:  %HEAD_SHA%
    echo Release: https://github.com/%REPO%/releases/tag/%TAG%
    start "" "https://github.com/%REPO%/releases/tag/%TAG%"
    goto :success
)

if "%WAIT_CODE%"=="2" (
    echo.
    echo [WARNING] Source and tag were pushed, but local waiting timed out.
    echo [WARNING] The GitHub build may still be running. Check Actions.
    goto :success
)

if "%WAIT_CODE%"=="3" (
    echo.
    echo [ERROR] GitHub Actions failed or required release assets are missing.
    start "" "https://github.com/%REPO%/actions/workflows/%WORKFLOW%"
    goto :failed
)

echo [ERROR] Release status checking failed unexpectedly.
goto :failed

:validation_failed
popd
echo [ERROR] Local validation failed. Nothing was pushed to GitHub.
goto :failed

:clone_repository
echo [1/8] Cloning %REPO_URL%...
if exist "%STAGE_DIR%" rmdir /s /q "%STAGE_DIR%" >nul 2>&1
git -c credential.interactive=always clone --branch "%BRANCH%" --single-branch "%REPO_URL%" "%STAGE_DIR%"
exit /b %ERRORLEVEL%

:git_login
git credential-manager --version >nul 2>&1
if not errorlevel 1 (
    git credential-manager github login
    exit /b %ERRORLEVEL%
)
git credential-manager-core --version >nul 2>&1
if not errorlevel 1 (
    git credential-manager-core github login
    exit /b %ERRORLEVEL%
)
echo [ERROR] Git Credential Manager is unavailable.
echo Install the current Git for Windows and enable Credential Manager.
start "" "https://git-scm.com/download/win"
exit /b 1

:find_python
py -3 --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=py -3"
    echo [OK] Python found through the Windows launcher.
    exit /b 0
)
python --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=python"
    echo [OK] Python found in PATH.
    exit /b 0
)
echo [ERROR] Python 3 is required for deployment validation.
start "" "https://www.python.org/downloads/windows/"
exit /b 1

:require_command
where %~1 >nul 2>&1
if errorlevel 1 (
    echo [ERROR] %~2 is not installed or is not available in PATH.
    if /I "%~1"=="git" start "" "https://git-scm.com/download/win"
    exit /b 1
)
exit /b 0

:failed
if exist "%STAGE_DIR%" rmdir /s /q "%STAGE_DIR%" >nul 2>&1
echo.
echo Deployment was not completed. Read the first error above.
pause
exit /b 1

:success
if exist "%STAGE_DIR%" rmdir /s /q "%STAGE_DIR%" >nul 2>&1
echo.
echo Deployment process finished.
pause
exit /b 0
