@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
title dicodePing RC18 Desktop Xray Recovery + One-Click Release
cd /d "%~dp0"

set "REPO=mcodersir/dicodePing"
set "REPO_URL=https://github.com/%REPO%.git"
set "BRANCH=main"
set "TAG=v1.9.0-rc.18"
set "WORKFLOW=release.yml"
set "DOCS_WORKFLOW=docs.yml"
set "COMMIT_MESSAGE=fix: publish RC18 desktop Xray connection recovery"
set "SOURCE_DIR=%CD%"
set "STAGE_DIR=%TEMP%\dicodePing-deploy-v190-rc18-%RANDOM%%RANDOM%"
set "WAIT_SCRIPT=%SOURCE_DIR%\tools\wait_for_github_release.ps1"
set "PAGES_SCRIPT=%SOURCE_DIR%\tools\configure_github_pages.ps1"
set "SIGNING_SCRIPT=%SOURCE_DIR%\tools\bootstrap_android_signing.ps1"
set "HEAD_SHA="
set "REMOTE_TAG_EXISTS="
set "TAG_PUSHED="
set "PYTHON_CMD="
set "ROBOCOPY_CODE="
set "PAGES_CODE=0"

cls
echo ================================================================
echo  dicodePing RC18 ONE-CLICK: CLONE + PRE-RELEASE + PAGES DEPLOY + TUN HOTFIX
echo ================================================================
echo.
echo This deployer will:
echo   1. Clone the current GitHub repository into a temporary folder.
echo   2. Replace it with a clean RC18 snapshot.
echo   3. Remove stale RC tests and old release files.
echo   4. Validate the complete project before any push.
echo   5. Push main and recreate the v1.9.0-rc.18 tag.
echo   6. Publish the GitHub pre-release and all platform assets.
echo   7. Repair and deploy the GitHub Pages website.
echo.
echo Repository: %REPO%
echo Branch:     %BRANCH%
echo Tag:        %TAG%
echo.
echo Android signing:
echo   Missing GitHub Actions secrets are created or restored automatically.
echo   A persistent private backup is stored in Documents\dicodePing-signing.
echo.
echo No GitHub token or signing key is stored in this source folder or BAT file.
echo.
pause

call :require_command git "Git for Windows"
if errorlevel 1 goto :failed
call :require_command robocopy "Windows Robocopy"
if errorlevel 1 goto :failed
call :require_command powershell "Windows PowerShell"
if errorlevel 1 goto :failed
call :ensure_gh
if errorlevel 1 goto :failed
call :ensure_android_signing
if errorlevel 1 goto :failed
call :find_python
if errorlevel 1 goto :failed

if not exist ".github\workflows\%WORKFLOW%" (
    echo [ERROR] Missing workflow: .github\workflows\%WORKFLOW%
    goto :failed
)
if not exist ".github\workflows\%DOCS_WORKFLOW%" (
    echo [ERROR] Missing workflow: .github\workflows\%DOCS_WORKFLOW%
    goto :failed
)
if not exist "docs\releases\v1.9.0-rc.18.md" (
    echo [ERROR] Missing release notes: docs\releases\v1.9.0-rc.18.md
    goto :failed
)
if not exist "%WAIT_SCRIPT%" (
    echo [ERROR] Missing helper: tools\wait_for_github_release.ps1
    goto :failed
)
if not exist "%PAGES_SCRIPT%" (
    echo [ERROR] Missing helper: tools\configure_github_pages.ps1
    goto :failed
)
if not exist "%SIGNING_SCRIPT%" (
    echo [ERROR] Missing helper: tools\bootstrap_android_signing.ps1
    goto :failed
)
if not exist "tools\purge_stale_release_tests.py" (
    echo [ERROR] Missing helper: tools\purge_stale_release_tests.py
    goto :failed
)
if not exist "tools\bootstrap_android_signing.ps1" (
    echo [ERROR] Missing helper: tools\bootstrap_android_signing.ps1
    goto :failed
)

call :clone_repository
if errorlevel 1 (
    echo.
    echo [INFO] Clone failed. Refreshing GitHub authentication...
    gh auth setup-git >nul 2>&1
    call :clone_repository
    if errorlevel 1 (
        echo [ERROR] Repository clone failed after authentication refresh.
        goto :failed
    )
)

echo.
echo [2/10] Reading the existing remote tag...
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
echo [3/10] Removing every tracked file from the cloned working tree...
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
echo [4/10] Copying the clean RC18 source snapshot...
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
echo [5/10] Purging stale historical release files from the staged tree...
call %PYTHON_CMD% tools\purge_stale_release_tests.py
if errorlevel 1 (
    echo [ERROR] Automatic stale release-test cleanup failed.
    popd
    goto :failed
)

set "STALE_TETHER_CONTROLLER=dicodePing_android\app\src\main\java\ir\dicode\ping\vpn\AndroidTetheringController.kt"
if exist "%STALE_TETHER_CONTROLLER%" (
    echo [INFO] Removing stale main-source AndroidTetheringController...
    del /f /q "%STALE_TETHER_CONTROLLER%" >nul 2>&1
)

if exist ".github\workflows\v1.9.0-rc.*-release.yml" (
    echo [INFO] Removing obsolete version-specific release workflows...
    del /f /q ".github\workflows\v1.9.0-rc.*-release.yml" >nul 2>&1
)

for /f "delims=" %%F in ('dir /b /a-d "DEPLOY_PRERELEASE_RC*.bat" 2^>nul') do (
    if /I not "%%F"=="DEPLOY_PRERELEASE_RC18.bat" (
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
    if /I not "%%F"=="DEPLOY_PRERELEASE_RC18_README_FA.txt" (
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

if exist "tests\test_v*.py" (
    echo [ERROR] Historical test_v files survived cleanup.
    dir /b "tests\test_v*.py"
    popd
    goto :failed
)
call %PYTHON_CMD% tools\purge_stale_release_tests.py --check
if errorlevel 1 (
    echo [ERROR] Stale release tests survived cleanup and would block RC18.
    popd
    goto :failed
)
if exist ".github\workflows\v1.9.0-rc.*-release.yml" (
    echo [ERROR] Obsolete release workflows survived cleanup.
    dir /b ".github\workflows\v1.9.0-rc.*-release.yml"
    popd
    goto :failed
)
if exist "%STALE_TETHER_CONTROLLER%" (
    echo [ERROR] Stale AndroidTetheringController survived cleanup.
    popd
    goto :failed
)
if not exist ".github\workflows\release.yml" (
    echo [ERROR] Current release.yml was not copied.
    popd
    goto :failed
)
if not exist ".github\workflows\docs.yml" (
    echo [ERROR] Current docs.yml was not copied.
    popd
    goto :failed
)
if not exist "tests\test_rc18_regressions.py" (
    echo [ERROR] Current RC18 tests were not copied.
    popd
    goto :failed
)
if not exist "app_v190_rc18.py" (
    echo [ERROR] RC18 runtime wrapper app_v190_rc18.py was not copied.
    popd
    goto :failed
)
findstr /C:"app_v190_rc18.py" "tools\build_windows.py" >nul
if errorlevel 1 (
    echo [ERROR] Windows builder is not using app_v190_rc18.py.
    popd
    goto :failed
)
findstr /C:"app_v190_rc18.py" "tools\build_linux.py" >nul
if errorlevel 1 (
    echo [ERROR] Linux builder is not using app_v190_rc18.py.
    popd
    goto :failed
)
findstr /C:"app_v190_rc18.py" "tools\build_macos.py" >nul
if errorlevel 1 (
    echo [ERROR] macOS builder is not using app_v190_rc18.py.
    popd
    goto :failed
)
findstr /C:"actions/upload-pages-artifact@v4" ".github\workflows\docs.yml" >nul
if errorlevel 1 (
    echo [ERROR] GitHub Pages workflow does not use upload-pages-artifact v4.
    popd
    goto :failed
)
findstr /C:"pages: write" ".github\workflows\docs.yml" >nul
if errorlevel 1 (
    echo [ERROR] GitHub Pages write permission is missing.
    popd
    goto :failed
)
findstr /C:"id-token: write" ".github\workflows\docs.yml" >nul
if errorlevel 1 (
    echo [ERROR] GitHub Pages OIDC permission is missing.
    popd
    goto :failed
)
findstr /C:"normalizedSubscriptionHttpUrl" "dicodePing_android\app\src\main\java\ir\dicode\ping\net\SubscriptionClient.kt" >nul
if errorlevel 1 (
    echo [ERROR] Android subscription URL crash fix is missing.
    popd
    goto :failed
)
findstr /C:"python tools/prepare_bundled_cores.py" "dicodePing_android\build_apk.sh" >nul
if errorlevel 1 (
    echo [ERROR] Android APK build does not prepare Aether and Usque.
    popd
    goto :failed
)
findstr /C:"python tools/verify_apk_cores.py" "dicodePing_android\build_apk.sh" >nul
if errorlevel 1 (
    echo [ERROR] Android APK core verification is missing.
    popd
    goto :failed
)
findstr /C:"versionCode = 53" "dicodePing_android\app\build.gradle.kts" >nul
if errorlevel 1 (
    echo [ERROR] Android versionCode 53 is missing.
    popd
    goto :failed
)
findstr /C:"registrationProcess" "dicodePing_android\app\src\main\java\ir\dicode\ping\core\AndroidExternalCoreProcess.kt" >nul
if errorlevel 1 (
    echo [ERROR] Android external-core cancellation fix is missing.
    popd
    goto :failed
)
findstr /C:"val localServers = servers.value.filter" "dicodePing_android\app\src\main\java\ir\dicode\ping\data\AppRepository.kt" >nul
if errorlevel 1 (
    echo [ERROR] Android scanner persistence fix is missing.
    popd
    goto :failed
)
findstr /C:"SCANNER_TCP_PREFILTER_WORKERS = 16" "dicodePing_android\app\src\main\java\ir\dicode\ping\data\AppRepository.kt" >nul
if errorlevel 1 (
    echo [ERROR] Android scanner prefilter is missing.
    popd
    goto :failed
)
if not exist "tools\bootstrap_android_signing.ps1" (
    echo [ERROR] Android signing bootstrap helper was not copied.
    popd
    goto :failed
)
findstr /C:"gh secret set --repo $Repository --app actions --env-file" "tools\bootstrap_android_signing.ps1" >nul
if errorlevel 1 (
    echo [ERROR] Android signing bootstrap cannot upload repository secrets.
    popd
    goto :failed
)
findstr /C:"RuntimeTuning.detect(context, repo.settings.resourceMode)" "dicodePing_android\app\src\main\java\ir\dicode\ping\scanner\ScannerCoordinator.kt" >nul
if errorlevel 1 (
    echo [ERROR] Android ScannerCoordinator still contains an invalid repository reference.
    popd
    goto :failed
)
findstr /C:"def build_tun_config" "dicodeping\xray.py" >nul
if errorlevel 1 (
    echo [ERROR] Xray TUN configuration builder is missing.
    popd
    goto :failed
)
findstr /C:"\"protocol\": \"tun\"" "dicodeping\xray.py" >nul
if errorlevel 1 (
    echo [ERROR] Desktop Xray is not configured with a TUN inbound.
    popd
    goto :failed
)
findstr /C:"autoSystemRoutingTable" "dicodeping\xray.py" >nul
if errorlevel 1 (
    echo [ERROR] System-wide TUN routing is missing.
    popd
    goto :failed
)
findstr /C:"autoOutboundsInterface" "dicodeping\xray.py" >nul
if errorlevel 1 (
    echo [ERROR] Xray outbound loop protection is missing.
    popd
    goto :failed
)
findstr /C:"_direct_tun_http_probe" "dicodeping\xray.py" >nul
if errorlevel 1 (
    echo [ERROR] Real system TUN verification is missing.
    popd
    goto :failed
)
findstr /C:"install_direct_host_routes" "dicodeping\xray.py" >nul
if errorlevel 1 (
    echo [ERROR] Xray endpoint loop-prevention route is missing.
    popd
    goto :failed
)
findstr /C:"require_wintun=is_windows()" "tools\prepare_core.py" >nul
if errorlevel 1 (
    echo [ERROR] Windows core preparation does not require Wintun.
    popd
    goto :failed
)
findstr /C:"manager.connected_ping(timeout=3.2)" "dicodeping\workers.py" >nul
if errorlevel 1 (
    echo [ERROR] Post-start verification is not checking the active TUN route.
    popd
    goto :failed
)
findstr /C:"relaunch_as_admin()" "app.py" >nul
if errorlevel 1 (
    echo [ERROR] Desktop TUN privilege elevation is missing.
    popd
    goto :failed
)
findstr /C:"--uac-admin" "tools\build_windows.py" >nul
if errorlevel 1 (
    echo [ERROR] Windows package does not request the privileges required by TUN.
    popd
    goto :failed
)
findstr /C:"wintun.dll" "tools\build_windows.py" >nul
if errorlevel 1 (
    echo [ERROR] Windows package does not bundle Wintun.
    popd
    goto :failed
)
echo [OK] Stale files were removed and the RC18 staged tree is clean.

echo.
echo [6/10] Running full local preflight before any push...
call %PYTHON_CMD% tools\prepare_build_workspace.py
if errorlevel 1 goto :validation_failed
call %PYTHON_CMD% tools\verify_version.py --tag %TAG%
if errorlevel 1 goto :validation_failed
call %PYTHON_CMD% tools\validate_android_gradle_kts.py
if errorlevel 1 goto :validation_failed
call %PYTHON_CMD% tools\validate_android_source_references.py
if errorlevel 1 goto :validation_failed
call %PYTHON_CMD% tools\validate_rc18_tun_runtime_hotfix.py
if errorlevel 1 goto :validation_failed
call %PYTHON_CMD% dicodePing_android\tools\validate_project.py
if errorlevel 1 goto :validation_failed
call %PYTHON_CMD% -c "import pytest" >nul 2>&1
if errorlevel 1 (
    echo [INFO] pytest is missing. Installing the test dependency...
    call %PYTHON_CMD% -m pip install --disable-pip-version-check "pytest==8.4.1"
    if errorlevel 1 goto :validation_failed
)
call %PYTHON_CMD% -m pytest -q
if errorlevel 1 goto :validation_failed
call %PYTHON_CMD% tools\quality_gate.py
if errorlevel 1 goto :validation_failed

echo [OK] RC18 preflight passed.

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
    echo [INFO] Main already matches this snapshot. Creating an empty commit to retrigger workflows.
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
echo [7/10] Pushing clean commit %HEAD_SHA% to %BRANCH%...
git push origin "HEAD:%BRANCH%"
if errorlevel 1 (
    popd
    echo [ERROR] Push to %BRANCH% failed. Branch protection or a newer commit may be blocking it.
    goto :failed
)

echo.
echo [8/10] Recreating GitHub pre-release tag %TAG%...
gh release view "%TAG%" --repo "%REPO%" >nul 2>&1
if not errorlevel 1 (
    echo [INFO] Removing the old GitHub release so stale assets cannot survive...
    gh release delete "%TAG%" --repo "%REPO%" --yes
    if errorlevel 1 (
        popd
        echo [ERROR] Existing GitHub release could not be deleted.
        goto :failed
    )
)

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
    echo [ERROR] The RC18 tag could not be published.
    echo [ERROR] Check GitHub tag-protection rules and repository permissions.
    goto :failed
)
popd

echo.
echo [9/10] Repairing GitHub Pages and deploying docs/site...
call :run_pages_attempt 1
if not "%PAGES_CODE%"=="0" (
    echo [PAGES] Transient failure detected. Waiting 15 seconds before retry...
    timeout /t 15 /nobreak >nul
    call :run_pages_attempt 2
)
if not "%PAGES_CODE%"=="0" (
    echo [PAGES] Transient failure detected. Waiting 15 seconds before final retry...
    timeout /t 15 /nobreak >nul
    call :run_pages_attempt 3
)
if not "%PAGES_CODE%"=="0" (
    echo [WARNING] GitHub Pages deployment failed after retries. Release monitoring will continue.
    start "" "https://github.com/%REPO%/actions/workflows/%DOCS_WORKFLOW%"
)

echo.
echo [10/10] Waiting for all pre-release platform assets...
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
    echo          RC18 PRE-RELEASE AND DEPLOY FINISHED
    echo ================================================================
    echo Commit:  %HEAD_SHA%
    echo Release: https://github.com/%REPO%/releases/tag/%TAG%
    if "%PAGES_CODE%"=="0" (
        echo Pages:   https://mcodersir.github.io/dicodePing/
    ) else (
        echo Pages:   FAILED - check Documentation workflow
    )
    start "" "https://github.com/%REPO%/releases/tag/%TAG%"
    if "%PAGES_CODE%"=="0" start "" "https://mcodersir.github.io/dicodePing/"
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
echo [1/10] Cloning %REPO_URL%...
if exist "%STAGE_DIR%" rmdir /s /q "%STAGE_DIR%" >nul 2>&1
git -c credential.interactive=always clone --branch "%BRANCH%" --single-branch "%REPO_URL%" "%STAGE_DIR%"
exit /b %ERRORLEVEL%

:run_pages_attempt
set "PAGES_CODE=1"
echo [PAGES] Full deployment attempt %~1/3...
powershell -NoProfile -ExecutionPolicy Bypass -File "%PAGES_SCRIPT%" -Repository "%REPO%" -Branch "%BRANCH%" -CommitSha "%HEAD_SHA%" -WorkflowFile "%DOCS_WORKFLOW%" -TimeoutMinutes 30
set "PAGES_CODE=%ERRORLEVEL%"
exit /b 0

:ensure_gh
where gh >nul 2>&1
if errorlevel 1 (
    echo [INFO] GitHub CLI is missing. Trying installation through winget...
    where winget >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] GitHub CLI is required for one-click release and Pages deployment.
        start "" "https://cli.github.com/"
        exit /b 1
    )
    winget install --id GitHub.cli --exact --source winget --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        echo [ERROR] GitHub CLI installation failed.
        start "" "https://cli.github.com/"
        exit /b 1
    )
    set "PATH=%PATH%;%ProgramFiles%\GitHub CLI"
)

gh auth status --hostname github.com >nul 2>&1
if errorlevel 1 (
    echo [INFO] Sign in to GitHub in the browser window...
    gh auth login --hostname github.com --git-protocol https --web
    if errorlevel 1 (
        echo [ERROR] GitHub CLI authentication failed.
        exit /b 1
    )
)
gh auth setup-git >nul 2>&1
if errorlevel 1 (
    echo [ERROR] GitHub CLI could not configure Git authentication.
    exit /b 1
)
echo [OK] GitHub CLI authenticated.
exit /b 0


:ensure_android_signing
echo.
echo [SIGNING] Checking Android release-signing configuration...
powershell -NoProfile -ExecutionPolicy Bypass -File "%SIGNING_SCRIPT%" -Repository "%REPO%"
if errorlevel 1 (
    echo [ERROR] Android signing bootstrap failed.
    echo [ERROR] Nothing has been cloned, committed or pushed.
    exit /b 1
)
exit /b 0

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
