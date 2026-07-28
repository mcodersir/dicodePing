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
set "COMMIT_MESSAGE=release: deploy v1.9.0-rc.14 real Aether and WARP cores"
set "SOURCE_DIR=%CD%"
set "STAGE_DIR=%TEMP%\dicodePing-deploy-v190-rc14-%RANDOM%%RANDOM%"
set "WAIT_SCRIPT=%SOURCE_DIR%\tools\wait_for_github_release.ps1"
set "HEAD_SHA="
set "REMOTE_TAG_EXISTS="
set "TAG_PUSHED="
set "PYTHON_CMD="

cls
echo ================================================================
echo      dicodePing v1.9.0 RC14 GitHub Pre-release Deploy
echo ================================================================
echo.
echo This script will:
echo   1. Clone the latest main branch.
echo   2. Replace old repository clutter with this clean RC14 source.
echo   3. Validate version and Android project files.
echo   4. Commit and push RC14 to main.
echo   5. Create or replace tag %TAG%.
echo   6. Let GitHub Actions build Windows, Linux, macOS and Android.
echo   7. Wait until the pre-release assets are published.
echo.
echo Repository: %REPO%
echo Tag:        %TAG%
echo.
echo IMPORTANT: GitHub repository Actions secrets must already contain:
echo   ANDROID_KEYSTORE_BASE64
echo   ANDROID_KEYSTORE_PASSWORD
echo   ANDROID_KEY_ALIAS
echo   ANDROID_KEY_PASSWORD
echo.
echo No GitHub token or signing key is stored in this file.
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
    echo [ERROR] Missing release wait helper: tools\wait_for_github_release.ps1
    goto :failed
)

call :clone_repository
if errorlevel 1 (
    echo.
    echo [INFO] Clone failed. Trying Git Credential Manager sign-in...
    call :git_login
    if errorlevel 1 goto :failed
    call :clone_repository
    if errorlevel 1 (
        echo [ERROR] Repository clone still failed after sign-in.
        goto :failed
    )
)

echo.
echo [2/7] Checking existing remote tag...
pushd "%STAGE_DIR%"
git ls-remote --exit-code --tags origin "refs/tags/%TAG%" >nul 2>&1
if not errorlevel 1 set "REMOTE_TAG_EXISTS=1"
popd
if defined REMOTE_TAG_EXISTS (
    echo [INFO] %TAG% already exists and will be replaced after the new commit is pushed.
    echo [INFO] The GitHub pre-release will be updated in place by release.yml.
) else (
    echo [OK] %TAG% is not currently present on the remote.
)

echo.
echo [3/7] Synchronizing the clean RC14 source...
robocopy "%SOURCE_DIR%" "%STAGE_DIR%" /MIR /R:2 /W:1 /NFL /NDL /NJH /NJS /NP /XJ ^
 /XD ".git" ".venv" "venv" "build" "dist" "release" "release-assets" "downloaded-artifacts" "artifacts" ".pytest_cache" "__pycache__" ".gradle" ".idea" ".kotlin" ".cxx" ".externalNativeBuild" ^
 /XF "*.jks" "*.keystore" "*.p12" "*.pfx" "*.pem" "*.key" "*.apk" "*.aab" "*.aar" "local.properties" "*.log"
set "ROBOCOPY_CODE=%ERRORLEVEL%"
if %ROBOCOPY_CODE% GEQ 8 (
    echo [ERROR] Robocopy failed with exit code %ROBOCOPY_CODE%.
    goto :failed
)

pushd "%STAGE_DIR%"
if errorlevel 1 goto :failed

echo.
echo [4/7] Running RC14 preflight validation...
call %PYTHON_CMD% tools\verify_version.py --tag %TAG%
if errorlevel 1 (
    popd
    echo [ERROR] Version validation failed.
    goto :failed
)
call %PYTHON_CMD% tools\validate_android_gradle_kts.py
if errorlevel 1 (
    popd
    echo [ERROR] Android Gradle validation failed.
    goto :failed
)
call %PYTHON_CMD% dicodePing_android\tools\validate_project.py
if errorlevel 1 (
    popd
    echo [ERROR] Android source validation failed.
    goto :failed
)

for /f "delims=" %%U in ('git config --get user.name 2^>nul') do set "GIT_USER=%%U"
if not defined GIT_USER git config user.name "mcodersir"
git config --get user.email >nul 2>&1
if errorlevel 1 git config user.email "mcodersir@users.noreply.github.com"

git add -A
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "%COMMIT_MESSAGE%"
) else (
    echo [INFO] Source already matches main. Creating an empty release commit to retrigger RC14.
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
echo [5/7] Pushing commit %HEAD_SHA% to %BRANCH%...
git push origin "HEAD:%BRANCH%"
if errorlevel 1 (
    popd
    echo [ERROR] Push to %BRANCH% failed. The remote branch may have changed.
    goto :failed
)

echo.
echo [6/7] Publishing tag %TAG%...
git tag -d "%TAG%" >nul 2>&1
git tag -a "%TAG%" -m "dicodePing %TAG% pre-release" "%HEAD_SHA%"
if errorlevel 1 (
    popd
    echo [ERROR] Local release tag creation failed.
    goto :failed
)

if defined REMOTE_TAG_EXISTS (
    echo [INFO] Removing the old remote tag so the tag-push workflow runs again...
    git push origin ":refs/tags/%TAG%"
    if errorlevel 1 (
        echo [WARNING] Remote tag deletion was denied. Trying a force update...
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
    echo [ERROR] Check tag protection rules and your repository permission.
    goto :failed
)
popd

echo.
echo GitHub Actions release build has started.
echo Actions: https://github.com/%REPO%/actions/workflows/%WORKFLOW%
start "" "https://github.com/%REPO%/actions/workflows/%WORKFLOW%"
echo.
echo [7/7] Waiting for Windows, Linux, macOS and Android assets...
echo This normally takes 15 to 45 minutes.
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
    echo [WARNING] Source and tag were pushed successfully, but local waiting timed out.
    echo [WARNING] The GitHub build may still be running. Check the Actions page.
    goto :success
)

if "%WAIT_CODE%"=="3" (
    echo.
    echo [ERROR] GitHub Actions failed or the release is missing required assets.
    start "" "https://github.com/%REPO%/actions/workflows/%WORKFLOW%"
    goto :failed
)

echo [ERROR] Release status checking failed unexpectedly.
goto :failed

:clone_repository
echo [1/7] Cloning %REPO_URL%...
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
