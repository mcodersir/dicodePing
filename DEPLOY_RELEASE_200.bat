@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

set "REPO=mcodersir/dicodePing"
set "REPO_URL=https://github.com/%REPO%.git"
set "BRANCH=main"
set "TAG=v2.0.4"
set "WORKFLOW=release.yml"
set "DOCS_WORKFLOW=docs.yml"
set "CURRENT_DEPLOY=DEPLOY_RELEASE_200.bat"
set "COMMIT_MESSAGE=release: publish dicodePing v2.0.4 stable"
set "SOURCE_DIR=%CD%"
set "STAGE_DIR=%TEMP%\dicodePing-release-v200-%RANDOM%%RANDOM%"
set "SIGNING_SCRIPT=%SOURCE_DIR%\tools\bootstrap_android_signing.ps1"
set "RELEASE_TRIGGER_SCRIPT=%SOURCE_DIR%\tools\publish_release_trigger.ps1"
set "PAGES_SCRIPT=%SOURCE_DIR%\tools\configure_github_pages.ps1"
set "WAIT_SCRIPT=%SOURCE_DIR%\tools\wait_for_github_release.ps1"
set "PYTHON_CMD="
set "HEAD_SHA="

cls
echo ================================================================
echo  dicodePing 2.0.0 STABLE ONE-CLICK RELEASE
echo  VALIDATE + BUILD + LATEST RELEASE + GITHUB PAGES
echo ================================================================
echo.
echo Repository: %REPO%
echo Branch:     %BRANCH%
echo Tag:        %TAG%
echo.
echo This publishes a stable, non-draft, non-prerelease GitHub release.
echo Success is reported only after every platform asset and Pages are ready.
echo.
pause

call :require_command git
if errorlevel 1 goto :failed
call :require_command robocopy
if errorlevel 1 goto :failed
call :require_command powershell
if errorlevel 1 goto :failed
call :ensure_gh
if errorlevel 1 goto :failed
call :find_python
if errorlevel 1 goto :failed

if not exist ".github\workflows\%WORKFLOW%" goto :missing_source
if not exist ".github\workflows\%DOCS_WORKFLOW%" goto :missing_source
if not exist "docs\releases\v2.0.4.md" goto :missing_source
if not exist "docs\site\index.html" goto :missing_source
if not exist "app_v200.py" goto :missing_source
if not exist "tests\test_v204_stable.py" goto :missing_source
if not exist "tools\validate_v204_stable.py" goto :missing_source
if not exist "tools\validate_android_lint_hotfix.py" goto :missing_source
if not exist "tools\validate_workflow_yaml.py" goto :missing_source
if not exist "tools\vendor\pyyaml\yaml\__init__.py" goto :missing_source
if not exist "tools\vendor\pyyaml\LICENSE" goto :missing_source
if not exist "%SIGNING_SCRIPT%" goto :missing_source
if not exist "%RELEASE_TRIGGER_SCRIPT%" goto :missing_source
if not exist "%PAGES_SCRIPT%" goto :missing_source
if not exist "%WAIT_SCRIPT%" goto :missing_source

echo.
echo [SIGNING] Checking Android release-signing configuration...
powershell -NoProfile -ExecutionPolicy Bypass -File "%SIGNING_SCRIPT%" -Repository "%REPO%"
if errorlevel 1 goto :signing_failed

echo.
echo [1/10] Cloning %REPO_URL% with network retry...
call :clone_repository
if errorlevel 1 goto :clone_failed

echo.
echo [2/10] Clearing the cloned working tree...
pushd "%STAGE_DIR%"
git reset --hard HEAD >nul
if errorlevel 1 goto :git_failed
git clean -ffdqx >nul 2>&1
git rm -r -f --ignore-unmatch . >nul
if errorlevel 1 goto :git_failed
popd

echo.
echo [3/10] Copying the clean stable source snapshot...
robocopy "%SOURCE_DIR%" "%STAGE_DIR%" /E /COPY:DAT /DCOPY:DAT /R:2 /W:1 /NFL /NDL /NJH /NJS /NP /XJ ^
 /XD ".git" ".venv" "venv" "build" "dist" "release" "release-assets" "downloaded-artifacts" "artifacts" ".pytest_cache" "__pycache__" ".gradle" ".idea" ".kotlin" ".cxx" ".externalNativeBuild" ^
 /XF "*.jks" "*.keystore" "*.p12" "*.pfx" "*.pem" "*.key" "*.apk" "*.aab" "*.aar" "*.ttf" "*.otf" "local.properties" "*.log" "*.bak"
set "ROBOCOPY_CODE=%ERRORLEVEL%"
if %ROBOCOPY_CODE% GEQ 8 goto :copy_failed

pushd "%STAGE_DIR%"
echo.
echo [4/10] Removing stale release files and overlay leftovers...
call %PYTHON_CMD% tools\purge_stale_release_tests.py
if errorlevel 1 (popd & goto :cleanup_failed)

for /f "delims=" %%F in ('dir /b /a-d "DEPLOY*.bat" 2^>nul') do if /I not "%%F"=="%CURRENT_DEPLOY%" del /f /q "%%F" >nul 2>&1
for /f "delims=" %%F in ('dir /b /a-d "DEPLOY*_README_FA.txt" 2^>nul') do if /I not "%%F"=="DEPLOY_RELEASE_200_README_FA.txt" del /f /q "%%F" >nul 2>&1
for %%P in (
  "BUILD_RELEASE_RC*.bat"
  "BUILD_SIGNED_APK_RC*.bat"
  "RUN_SOURCE_RC*.bat"
  "START_HERE_RC*.txt"
  "VALIDATION_RESULTS_RC*.txt"
  "app_v190_rc*.py"
  "app_v200_rc*.py"
  "RC4_*.txt"
  "RC14_*.md"
  "RC14_*.txt"
  "RC19_*.md"
  "RC19_*.txt"
  "V200_RC*_*.md"
  "V200_RC*_*.txt"
  "V200_STABLE_*_FA.md"
  "V200_STABLE_*_FA.txt"
  "DEPLOY_RC*_*.txt"
  "DEPLOY_RC*_*.md"
  "LOCAL_VALIDATION_RC*.txt"
  "VALIDATION_RC*.txt"
  "build_exe.bat"
  "cleanup_network.bat"
  "run_dev.bat"
  ".source-files.txt"
) do del /f /q "%%~P" >nul 2>&1
if exist ".github\workflows\v1.9.0-rc.*-release.yml" del /f /q ".github\workflows\v1.9.0-rc.*-release.yml" >nul 2>&1
if exist "dicodePing_android\app\src\main\java\ir\dicode\ping\vpn\AndroidTetheringController.kt" del /f /q "dicodePing_android\app\src\main\java\ir\dicode\ping\vpn\AndroidTetheringController.kt" >nul 2>&1

call %PYTHON_CMD% tools\purge_stale_release_tests.py --check
if errorlevel 1 (popd & goto :cleanup_failed)
if not exist "%CURRENT_DEPLOY%" (popd & goto :cleanup_failed)
if not exist "app_v200.py" (popd & goto :cleanup_failed)
if not exist "tests\test_v204_stable.py" (popd & goto :cleanup_failed)
if not exist "tools\validate_v204_stable.py" (popd & goto :cleanup_failed)
findstr /C:"versionCode = 60" "dicodePing_android\app\build.gradle.kts" >nul || (popd & goto :cleanup_failed)
findstr /C:"prerelease: false" ".github\workflows\release.yml" >nul || (popd & goto :cleanup_failed)
findstr /C:"make_latest: true" ".github\workflows\release.yml" >nul || (popd & goto :cleanup_failed)
echo [OK] Stable staged tree is clean.

echo.
echo [5/10] Running strict local preflight...
call %PYTHON_CMD% tools\prepare_build_workspace.py
if errorlevel 1 goto :validation_failed
call %PYTHON_CMD% tools\verify_version.py --tag %TAG%
if errorlevel 1 goto :validation_failed
call %PYTHON_CMD% tools\validate_v204_stable.py
if errorlevel 1 goto :validation_failed
call %PYTHON_CMD% tools\validate_android_gradle_kts.py
if errorlevel 1 goto :validation_failed
call %PYTHON_CMD% tools\validate_android_source_references.py
if errorlevel 1 goto :validation_failed
call %PYTHON_CMD% tools\validate_android_lint_hotfix.py
if errorlevel 1 goto :validation_failed
call %PYTHON_CMD% dicodePing_android\tools\validate_project.py
if errorlevel 1 goto :validation_failed
call %PYTHON_CMD% -m compileall -q app.py app_v200.py dicodeping tools tests
if errorlevel 1 goto :validation_failed
call %PYTHON_CMD% -c "import pytest" >nul 2>&1
if errorlevel 1 (
  echo [INFO] Installing pytest...
  call %PYTHON_CMD% -m pip install --disable-pip-version-check "pytest==8.4.1"
  if errorlevel 1 goto :validation_failed
)
call %PYTHON_CMD% -m pytest -q
if errorlevel 1 goto :validation_failed
call %PYTHON_CMD% tools\quality_gate.py
if errorlevel 1 goto :validation_failed
call %PYTHON_CMD% tools\validate_workflow_yaml.py
if errorlevel 1 goto :validation_failed
echo [OK] Stable preflight passed with no blocking errors.

echo.
echo [6/10] Committing the stable snapshot...
git config --get user.name >nul 2>&1 || git config user.name "mcodersir"
git config --get user.email >nul 2>&1 || git config user.email "mcodersir@users.noreply.github.com"
git add -A
if errorlevel 1 goto :git_failed
git diff --cached --quiet
if errorlevel 1 (git commit -m "%COMMIT_MESSAGE%") else (git commit --allow-empty -m "%COMMIT_MESSAGE%")
if errorlevel 1 goto :git_failed
for /f "delims=" %%H in ('git rev-parse HEAD') do set "HEAD_SHA=%%H"
if not defined HEAD_SHA goto :git_failed

echo.
echo [7/10] Pushing commit %HEAD_SHA% to %BRANCH%...
call :push_main_with_retry
if errorlevel 1 goto :push_failed

echo.
echo [8/10] Recreating %TAG% and dispatching the stable release workflow...
powershell -NoProfile -ExecutionPolicy Bypass -File "%RELEASE_TRIGGER_SCRIPT%" -Repository "%REPO%" -Tag "%TAG%" -CommitSha "%HEAD_SHA%" -WorkflowFile "%WORKFLOW%" -MaxAttempts 8
if errorlevel 1 goto :release_failed
popd

echo.
echo [9/10] Deploying and verifying GitHub Pages...
powershell -NoProfile -ExecutionPolicy Bypass -File "%PAGES_SCRIPT%" -Repository "%REPO%" -Branch "%BRANCH%" -CommitSha "%HEAD_SHA%" -WorkflowFile "%DOCS_WORKFLOW%" -TimeoutMinutes 30
if errorlevel 1 goto :pages_failed

echo.
echo [10/10] Waiting for the stable Latest Release and every platform asset...
powershell -NoProfile -ExecutionPolicy Bypass -File "%WAIT_SCRIPT%" -Repository "%REPO%" -Tag "%TAG%" -WorkflowFile "%WORKFLOW%" -CommitSha "%HEAD_SHA%" -TimeoutMinutes 120
if errorlevel 1 goto :wait_failed

if exist "%STAGE_DIR%" rmdir /s /q "%STAGE_DIR%" >nul 2>&1
echo.
echo ================================================================
echo  SUCCESS: dicodePing 2.0.0 STABLE IS PUBLISHED AS LATEST
echo ================================================================
echo https://github.com/%REPO%/releases/tag/%TAG%
echo https://github.com/%REPO%/actions
start "" "https://github.com/%REPO%/releases/tag/%TAG%"
pause
exit /b 0

:clone_repository
if exist "%STAGE_DIR%" rmdir /s /q "%STAGE_DIR%" >nul 2>&1
for /L %%A in (1,1,5) do (
  git -c credential.interactive=always clone --branch "%BRANCH%" --single-branch "%REPO_URL%" "%STAGE_DIR%"
  if not errorlevel 1 exit /b 0
  echo [RETRY] Clone failed on attempt %%A/5.
  if exist "%STAGE_DIR%" rmdir /s /q "%STAGE_DIR%" >nul 2>&1
  gh auth setup-git >nul 2>&1
  if %%A LSS 5 timeout /t 8 /nobreak >nul
)
exit /b 1

:push_main_with_retry
for /L %%A in (1,1,8) do (
  git push origin "HEAD:%BRANCH%"
  if not errorlevel 1 exit /b 0
  echo [RETRY] Push failed on attempt %%A/8.
  gh auth setup-git >nul 2>&1
  if %%A LSS 8 timeout /t 8 /nobreak >nul
)
exit /b 1

:require_command
where %~1 >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Required command not found: %~1
  exit /b 1
)
exit /b 0

:ensure_gh
set "PATH=%PATH%;C:\Program Files\GitHub CLI"
where gh >nul 2>&1
if errorlevel 1 (
  echo [INFO] GitHub CLI is missing. Installing through winget...
  where winget >nul 2>&1 || exit /b 1
  winget install --id GitHub.cli --exact --source winget --accept-package-agreements --accept-source-agreements
  set "PATH=%PATH%;C:\Program Files\GitHub CLI"
  where gh >nul 2>&1 || exit /b 1
)
gh auth status --hostname github.com >nul 2>&1
if errorlevel 1 (
  echo [INFO] Sign in to GitHub in the browser...
  gh auth login --hostname github.com --git-protocol https --web
  if errorlevel 1 exit /b 1
)
gh auth setup-git >nul 2>&1
if errorlevel 1 exit /b 1
echo [OK] GitHub CLI authenticated.
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
  echo [OK] Python found.
  exit /b 0
)
echo [ERROR] Python 3 was not found.
exit /b 1

:missing_source
echo [ERROR] Stable source package is incomplete. Extract the full ZIP into a new folder.
goto :failed
:signing_failed
echo [ERROR] Android signing bootstrap failed. Nothing was pushed.
goto :failed
:clone_failed
echo [ERROR] Repository clone failed after retries.
goto :failed
:copy_failed
echo [ERROR] Source copy failed with Robocopy exit code %ROBOCOPY_CODE%.
goto :failed
:cleanup_failed
echo [ERROR] Stale release cleanup or staged-tree verification failed.
goto :failed
:validation_failed
popd
echo [ERROR] Strict local validation failed. Nothing was tagged or released.
goto :failed
:git_failed
popd
echo [ERROR] Git staging or commit failed.
goto :failed
:push_failed
popd
echo [ERROR] Push to main failed after retries.
goto :failed
:release_failed
popd
echo [ERROR] Stable tag or release workflow dispatch failed.
goto :failed
:pages_failed
echo [ERROR] GitHub Pages did not deploy successfully. Stable release verification stopped.
goto :failed
:wait_failed
echo [ERROR] GitHub Actions failed or the stable Latest Release is incomplete.
goto :failed
:failed
if exist "%STAGE_DIR%" rmdir /s /q "%STAGE_DIR%" >nul 2>&1
echo.
echo Stable deployment was not completed. Read the first error above.
pause
exit /b 1
