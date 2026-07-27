@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title dicodePing v1.9.0 RC9 Hotfix 3 - Release Recovery Deploy
cd /d "%~dp0"

set "REPO=mcodersir/dicodePing"
set "REPO_URL=https://github.com/%REPO%.git"
set "BRANCH=main"
set "TAG=v1.9.0-rc.9"
set "WORKFLOW=v1.9.0-rc.9-release.yml"
set "TRIGGER_REL=.github\release-triggers\v1.9.0-rc.9.txt"
set "COMMIT_MESSAGE=fix: publish v1.9.0-rc.9 Android CI and scanner hotfix 3"
set "SOURCE_DIR=%CD%"
set "STAGE_DIR=%TEMP%\dicodePing-deploy-v190-rc9-%RANDOM%%RANDOM%"
set "WAIT_SCRIPT=%SOURCE_DIR%\tools\wait_for_github_release_rc9.ps1"
set "HEAD_SHA="
set "GIT_USER="
set "REMOTE_TAG_EXISTS="
set "RELEASE_EXISTS="
set "TAG_UPDATED="

rem Git Credential Manager handles HTTPS authentication. Never reuse shell tokens.
set "GH_TOKEN="
set "GITHUB_TOKEN="
set "DICODEPING_GITHUB_TOKEN="
set "GH_PROMPT_DISABLED="
set "GCM_INTERACTIVE=always"
set "GIT_TERMINAL_PROMPT=1"

cls
echo ================================================================
echo      dicodePing v1.9.0 RC9 Hotfix 3 - Release Recovery Deploy
echo ================================================================
echo.
echo This script uses Git for repository authentication and deployment.
echo An existing partial RC9 release is updated in place after a successful build.
echo.
echo Steps:
echo   1. Clone the latest main branch using Git Credential Manager.
echo   2. Detect an existing tag or partial GitHub release without stopping.
echo   3. Copy and validate the RC9 Hotfix 3 source.
echo   4. Commit and push a unique release trigger to main.
echo   5. Move the RC9 tag to the fixed commit when GitHub permits it.
echo   6. GitHub Actions rebuilds all platforms and overwrites release assets.
echo   7. Wait for the exact workflow run and verify EXE, APK, Linux and macOS.
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
if not exist "docs\releases\v1.9.0-rc.9.md" (
    echo [ERROR] Release notes were not found:
    echo         docs\releases\v1.9.0-rc.9.md
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

echo [2/7] Checking the current RC9 tag and release state...
git ls-remote --exit-code --tags origin "refs/tags/%TAG%" >nul 2>&1
if not errorlevel 1 set "REMOTE_TAG_EXISTS=1"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "try { $r = Invoke-WebRequest -Uri 'https://github.com/%REPO%/releases/tag/%TAG%' -Method Head -MaximumRedirection 5 -UseBasicParsing -TimeoutSec 20; if ([int]$r.StatusCode -eq 200) { exit 0 } } catch { }; exit 1"
if not errorlevel 1 set "RELEASE_EXISTS=1"

if defined RELEASE_EXISTS (
    echo [RECOVERY] A GitHub release already exists for %TAG%.
    echo [RECOVERY] It will NOT block deployment and will be updated in place.
    echo [RECOVERY] Existing assets with matching names will be overwritten.
) else if defined REMOTE_TAG_EXISTS (
    echo [RECOVERY] The tag exists but no visible release is available yet.
    echo [RECOVERY] The tag will be moved to the fixed commit.
) else (
    echo The RC9 tag and release slot are available.
)
popd

echo [3/7] Copying the fixed RC9 source into the clean repository clone...
robocopy "%SOURCE_DIR%" "%STAGE_DIR%" /MIR /R:2 /W:1 /NFL /NDL /NJH /NJS /NP ^
 /XD ".git" ".venv" "venv" "build" "dist" "release" ".pytest_cache" "__pycache__" ".gradle" ".idea" ".kotlin" ".cxx" ".externalNativeBuild" ^
 /XF "*.jks" "*.keystore" "*.p12" "*.pfx" "*.pem" "*.key" "*.apk" "*.aab" "*.aar" "local.properties" "*.log"
set "ROBOCOPY_CODE=!ERRORLEVEL!"
if !ROBOCOPY_CODE! GEQ 8 (
    echo [ERROR] Robocopy failed with exit code !ROBOCOPY_CODE!.
    goto :failed
)

rem Remove the historical common-source controller that collides with flavors.
set "STALE_ANDROID_CONTROLLER=%STAGE_DIR%\dicodePing_android\app\src\main\java\ir\dicode\ping\vpn\AndroidTetheringController.kt"
if exist "!STALE_ANDROID_CONTROLLER!" (
    echo [FIX] Removing stale AndroidTetheringController from the main source set...
    del /f /q "!STALE_ANDROID_CONTROLLER!"
    if exist "!STALE_ANDROID_CONTROLLER!" (
        echo [ERROR] The stale Android controller could not be removed.
        goto :failed
    )
)

rem Change a dedicated trigger file on every run. The workflow listens only to this file.
if not exist "%STAGE_DIR%\.github\release-triggers" mkdir "%STAGE_DIR%\.github\release-triggers"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$lines = @('tag=%TAG%', 'mode=replace-existing-release', ('requested_at_utc=' + [DateTime]::UtcNow.ToString('o')), ('nonce=' + [Guid]::NewGuid().ToString('N'))); [IO.File]::WriteAllLines('%STAGE_DIR%\%TRIGGER_REL%', $lines, [Text.UTF8Encoding]::new($false))"
if errorlevel 1 (
    echo [ERROR] Could not update the release trigger file.
    goto :failed
)

pushd "%STAGE_DIR%"
if errorlevel 1 goto :failed

echo [4/7] Validating Android source sets and preparing the Git commit...
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is required for the Android preflight validator.
    popd
    goto :failed
)
python tools\validate_android_gradle_kts.py
if errorlevel 1 (
    echo [ERROR] Android Gradle Kotlin DSL validation failed before push.
    popd
    goto :failed
)
python dicodePing_android\tools\validate_project.py
if errorlevel 1 (
    echo [ERROR] Android source validation failed before push.
    popd
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
    if errorlevel 1 (
        popd
        goto :failed
    )
) else (
    popd
    echo [ERROR] No deploy changes were detected. The release trigger should always change.
    goto :failed
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

echo [6/7] Pointing %TAG% at the fixed RC9 commit...
git tag -d "%TAG%" >nul 2>&1
git tag -a "%TAG%" -m "dicodePing %TAG% pre-release recovery" "%HEAD_SHA%"
if errorlevel 1 (
    popd
    echo [ERROR] The local release tag could not be created.
    goto :failed
)

if defined REMOTE_TAG_EXISTS (
    git push --force origin "refs/tags/%TAG%:refs/tags/%TAG%"
    if not errorlevel 1 set "TAG_UPDATED=1"
    if not defined TAG_UPDATED (
        echo [WARNING] Force-updating the tag failed. Trying delete and recreate...
        git push origin ":refs/tags/%TAG%" >nul 2>&1
        if not errorlevel 1 (
            git push origin "refs/tags/%TAG%:refs/tags/%TAG%"
            if not errorlevel 1 set "TAG_UPDATED=1"
        )
    )
) else (
    git push origin "refs/tags/%TAG%:refs/tags/%TAG%"
    if not errorlevel 1 set "TAG_UPDATED=1"
)

if not defined TAG_UPDATED (
    echo [WARNING] The source was pushed, but GitHub did not allow moving the existing tag.
    echo [WARNING] The workflow will still rebuild and replace release assets from commit %HEAD_SHA%.
    echo [WARNING] If the release is immutable, GitHub may reject asset replacement.
)
popd

echo.
echo GitHub Actions was triggered by the release trigger commit.
echo Actions: https://github.com/%REPO%/actions/workflows/%WORKFLOW%
start "" "https://github.com/%REPO%/actions/workflows/%WORKFLOW%"
echo.
echo [7/7] Waiting for the exact workflow run and complete release assets...
echo The multi-platform build can take 15 to 45 minutes.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%WAIT_SCRIPT%" -Repository "%REPO%" -Tag "%TAG%" -WorkflowFile "%WORKFLOW%" -CommitSha "%HEAD_SHA%" -Branch "%BRANCH%" -TimeoutMinutes 90
set "WAIT_CODE=%ERRORLEVEL%"

if "%WAIT_CODE%"=="0" (
    echo.
    echo ================================================================
    echo                  PRE-RELEASE UPDATED SUCCESSFULLY
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
    echo [WARNING] The source was pushed successfully, but the workflow did not
    echo finish before the local wait timeout expired. It may still be running.
    start "" "https://github.com/%REPO%/actions/workflows/%WORKFLOW%"
    goto :success
)

if "%WAIT_CODE%"=="3" (
    echo.
    echo [ERROR] The exact GitHub Actions release run finished unsuccessfully
    echo or the final release was missing one or more required assets.
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
