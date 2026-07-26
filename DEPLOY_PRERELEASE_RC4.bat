@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title dicodePing v1.9.0 RC4 - Git Deploy and Pre-Release
cd /d "%~dp0"

set "REPO=mcodersir/dicodePing"
set "REPO_URL=https://github.com/%REPO%.git"
set "BRANCH=main"
set "TAG=v1.9.0-rc.4"
set "WORKFLOW=v1.9.0-rc.4-release.yml"
set "COMMIT_MESSAGE=release: deploy v1.9.0-rc.4 prerelease"
set "SOURCE_DIR=%CD%"
set "STAGE_DIR=%TEMP%\dicodePing-deploy-v190-rc4-%RANDOM%%RANDOM%"
set "WAIT_SCRIPT=%SOURCE_DIR%\tools\wait_for_github_release.ps1"
set "HEAD_SHA="
set "GIT_USER="

rem Never reuse stale GitHub CLI/API tokens. Git Credential Manager handles HTTPS auth.
set "GH_TOKEN="
set "GITHUB_TOKEN="
set "DICODEPING_GITHUB_TOKEN="
set "GH_PROMPT_DISABLED="
set "GCM_INTERACTIVE=always"
set "GIT_TERMINAL_PROMPT=1"

cls
echo ================================================================
echo       dicodePing v1.9.0 RC4 - Git Deploy and Pre-Release
echo ================================================================
echo.
echo This script uses Git for every repository operation.
echo It does not validate or store a GitHub token and does not require gh CLI.
echo.
echo Steps:
echo   1. Clone the latest main branch with Git Credential Manager.
echo   2. Copy this RC4 source into a clean repository clone.
echo   3. Commit and push the source to main.
echo   4. Create and push tag %TAG%.
echo   5. GitHub Actions builds Windows, Android, Linux and macOS.
echo   6. The workflow creates the GitHub pre-release automatically.
echo.
echo Repository: %REPO%
echo Tag:        %TAG%
echo.

call :require_command git "Git for Windows"
if errorlevel 1 goto :failed
call :require_command robocopy "Windows Robocopy"
if errorlevel 1 goto :failed
call :require_command powershell "Windows PowerShell"
if errorlevel 1 goto :failed

if not exist ".github\workflows\%WORKFLOW%" (
    echo [ERROR] Required workflow was not found:
    echo         .github\workflows\%WORKFLOW%
    goto :failed
)
if not exist "docs\releases\v1.9.0-rc.4.md" (
    echo [ERROR] Release notes were not found:
    echo         docs\releases\v1.9.0-rc.4.md
    goto :failed
)
if not exist "%WAIT_SCRIPT%" (
    echo [ERROR] Release wait helper was not found:
    echo         %WAIT_SCRIPT%
    goto :failed
)

for /f "delims=" %%V in ('git --version') do echo [1/7] %%V detected.
echo Git will use your existing Windows Git credentials.
echo If authentication is not cached, a browser sign-in window may open.
echo.

set "CLONE_OK="
call :clone_repository
if not errorlevel 1 set "CLONE_OK=1"

if not defined CLONE_OK (
    echo.
    echo [INFO] Initial Git clone failed. Trying Git Credential Manager login...
    git credential-manager --version >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Git Credential Manager is unavailable.
        echo Reinstall Git for Windows with Credential Manager enabled, or authenticate Git first.
        goto :failed
    )

    git credential-manager github login
    if errorlevel 1 (
        echo [ERROR] GitHub sign-in through Git Credential Manager failed.
        goto :failed
    )

    if exist "%STAGE_DIR%" rmdir /s /q "%STAGE_DIR%" >nul 2>&1
    call :clone_repository
    if errorlevel 1 (
        echo [ERROR] Git still could not clone %REPO_URL% after login.
        goto :failed
    )
)

pushd "%STAGE_DIR%"
if errorlevel 1 goto :failed

echo [2/7] Checking the release tag...
git ls-remote --exit-code --tags origin "refs/tags/%TAG%" >nul 2>&1
if not errorlevel 1 (
    popd
    echo [ERROR] Tag %TAG% already exists on GitHub.
    echo This script will not overwrite an existing release tag.
    start "" "https://github.com/%REPO%/releases/tag/%TAG%"
    goto :failed
)
popd

echo [3/7] Copying the RC4 source into the clean repository clone...
robocopy "%SOURCE_DIR%" "%STAGE_DIR%" /MIR /R:2 /W:1 /NFL /NDL /NJH /NJS /NP ^
 /XD ".git" ".venv" "venv" "build" "dist" "release" ".pytest_cache" "__pycache__" ".gradle" ".idea" ".kotlin" ".cxx" ".externalNativeBuild" ^
 /XF "*.jks" "*.keystore" "*.p12" "*.pfx" "*.pem" "*.key" "*.apk" "*.aab" "*.aar" "local.properties" "*.log"
set "ROBOCOPY_CODE=!ERRORLEVEL!"
if !ROBOCOPY_CODE! GEQ 8 (
    echo [ERROR] Robocopy failed with exit code !ROBOCOPY_CODE!.
    goto :failed
)

pushd "%STAGE_DIR%"
if errorlevel 1 goto :failed

echo [4/7] Preparing the Git commit...
for /f "delims=" %%U in ('git config --get user.name 2^>nul') do set "GIT_USER=%%U"
if not defined GIT_USER git config user.name "mcodersir"
git config --get user.email >nul 2>&1
if errorlevel 1 git config user.email "mcodersir@users.noreply.github.com"

git add -A
git diff --cached --quiet
if errorlevel 1 (
    git commit -m "%COMMIT_MESSAGE%"
    if errorlevel 1 (
        popd
        goto :failed
    )
) else (
    echo No source changes were detected. The latest main commit will be tagged.
)

for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD_SHA=%%H"
if not defined HEAD_SHA (
    popd
    echo [ERROR] Could not resolve the commit SHA.
    goto :failed
)

echo [5/7] Pushing commit %HEAD_SHA% to %BRANCH%...
git push origin "HEAD:%BRANCH%"
if errorlevel 1 (
    popd
    echo [ERROR] Git could not push the commit to main.
    echo Check the browser sign-in prompt or Windows Credential Manager.
    goto :failed
)

echo [6/7] Creating and pushing %TAG%...
git tag -a "%TAG%" -m "dicodePing %TAG% pre-release"
if errorlevel 1 (
    popd
    goto :failed
)
git push origin "%TAG%"
if errorlevel 1 (
    git tag -d "%TAG%" >nul 2>&1
    popd
    echo [ERROR] Git could not push the release tag.
    goto :failed
)
popd

echo.
echo GitHub Actions was triggered by the tag push.
echo Actions: https://github.com/%REPO%/actions/workflows/%WORKFLOW%
start "" "https://github.com/%REPO%/actions/workflows/%WORKFLOW%"
echo.
echo [7/7] Waiting for the pre-release page to become available...
echo The multi-platform build can take 15 to 45 minutes.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%WAIT_SCRIPT%" -Repository "%REPO%" -Tag "%TAG%" -TimeoutMinutes 90
set "WAIT_CODE=%ERRORLEVEL%"

if "%WAIT_CODE%"=="0" (
    echo.
    echo ================================================================
    echo                    PRE-RELEASE CREATED
    echo ================================================================
    echo Tag:     %TAG%
    echo Commit:  %HEAD_SHA%
    echo Release: https://github.com/%REPO%/releases/tag/%TAG%
    echo.
    start "" "https://github.com/%REPO%/releases/tag/%TAG%"
    goto :success
)

if "%WAIT_CODE%"=="2" (
    echo.
    echo [WARNING] The tag was pushed successfully, but the release was not
    echo found before the local wait timeout expired.
    echo The GitHub Actions build may still be running. No deployment data was lost.
    start "" "https://github.com/%REPO%/actions/workflows/%WORKFLOW%"
    goto :success
)

if "%WAIT_CODE%"=="3" (
    echo.
    echo [ERROR] GitHub Actions finished unsuccessfully.
    echo Open the Actions page to view the failed job logs.
    start "" "https://github.com/%REPO%/actions/workflows/%WORKFLOW%"
    goto :failed
)

echo [ERROR] The release status check failed unexpectedly.
start "" "https://github.com/%REPO%/actions/workflows/%WORKFLOW%"
goto :failed

:clone_repository
echo [INFO] Cloning %REPO_URL%...
if exist "%STAGE_DIR%" rmdir /s /q "%STAGE_DIR%" >nul 2>&1
git -c credential.interactive=always clone --branch "%BRANCH%" --single-branch "%REPO_URL%" "%STAGE_DIR%"
exit /b %ERRORLEVEL%

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
echo Deployment completed successfully.
pause
exit /b 0
