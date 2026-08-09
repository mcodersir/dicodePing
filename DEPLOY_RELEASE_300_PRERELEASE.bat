@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

set "REPO=mcodersir/dicodePing"
set "REPO_URL=https://github.com/mcodersir/dicodePing.git"
set "BASE_BRANCH=main"
set "RELEASE_BRANCH=release/v3.0.0-pre.1"
set "TAG=v3.0.0-pre.1"
set "WORKFLOW=release-v3.yml"
rem Resolve the BAT directory to an absolute path without a trailing backslash.
for %%I in ("%~dp0.") do set "SOURCE_DIR=%%~fI"
set "STAGE_DIR=%TEMP%\dicodePing-v3.0.0-pre.1-release"
set "PYTHON_CMD="
set "PR_NUMBER="
set "RUN_ID="
set "RELEASE_URL="

cls
echo ================================================================
echo  dicodePing v3.0.0-pre.1 VERIFIED PRERELEASE PUBLISHER
echo  (v2rayN stack migration + modern UI)
echo ================================================================
echo.
echo This script does not contain or request a pasted token.
echo GitHub authentication is handled by GitHub CLI in your browser.
echo Repository: %REPO%
echo Tag:        %TAG%
echo.

call :require_command git || goto :failed
call :require_command robocopy || goto :failed
call :ensure_gh || goto :failed
call :find_python || goto :failed

rem Validate the v3 source structure
if not exist "%SOURCE_DIR%\dicodeping\v2rayN\integration" goto :missing_source
if not exist "%SOURCE_DIR%\dicodeping\v2rayN\integration\ui_v3.py" goto :missing_source
if not exist "%SOURCE_DIR%\dicodeping\v2rayN\integration\xray.py" goto :missing_source
if not exist "%SOURCE_DIR%\dicodeping\v2rayN\integration\net.py" goto :missing_source
if not exist "%SOURCE_DIR%\docs\releases\v3.0.0-pre.1.md" goto :missing_source

for /f "delims=" %%L in ('gh api user --jq .login') do set "GH_LOGIN=%%L"
if not defined GH_LOGIN goto :auth_failed
echo [OK] Authenticated as %GH_LOGIN%.

echo.
echo [1/9] Cloning a clean copy of %BASE_BRANCH%...
if exist "%STAGE_DIR%" rmdir /s /q "%STAGE_DIR%"
git clone --branch "%BASE_BRANCH%" --single-branch "%REPO_URL%" "%STAGE_DIR%" || goto :clone_failed

pushd "%STAGE_DIR%" || goto :failed
git checkout -B "%RELEASE_BRANCH%" "origin/%BASE_BRANCH%" || (popd & goto :git_failed)
git rm -r -f --ignore-unmatch . >nul 2>&1
popd

echo.
echo [2/9] Copying the corrected v3 source snapshot...
echo Source: "%SOURCE_DIR%"
echo Dest:   "%STAGE_DIR%"
if /I "%SOURCE_DIR%"=="%STAGE_DIR%" goto :copy_path_failed
robocopy "%SOURCE_DIR%" "%STAGE_DIR%" /E /COPY:DAT /DCOPY:DAT /R:2 /W:1 /NFL /NDL /NJH /NJS /NP /XJ ^
 /XD ".git" ".venv" "venv" "build" "dist" "release" "release-assets" "artifacts" ".pytest_cache" "__pycache__" ".gradle" ".idea" ".kotlin" ".cxx" ".externalExternalBuild" ^
 /XF "*.jks" "*.keystore" "*.p12" "*.pfx" "*.pem" "*.key" "*.apk" "*.aab" "*.aar" "local.properties" "*.log" "*.bak"
set "ROBOCOPY_CODE=!ERRORLEVEL!"
if !ROBOCOPY_CODE! GEQ 8 goto :copy_failed

pushd "%STAGE_DIR%" || goto :failed

echo.
echo [3/9] Installing v3 build dependencies...
call %PYTHON_CMD% -m pip install --disable-pip-version-check -r requirements-build.txt || goto :validation_failed

echo.
echo [4/9] Running v3 source validation...
call %PYTHON_CMD% tools\verify_version.py --tag %TAG% || goto :validation_failed
call %PYTHON_CMD% tools\validate_v300_prerelease.py || goto :validation_failed
call %PYTHON_CMD% tools\validate_android_gradle_kts.py || goto :validation_failed
call %PYTHON_CMD% dicodePing_android\tools\validate_project.py || goto :validation_failed
call %PYTHON_CMD% -m compileall -q app_v3.py dicodeping tools tests || goto :validation_failed
call %PYTHON_CMD% -m pytest -q || goto :validation_failed
call %PYTHON_CMD% tools\quality_gate.py || goto :validation_failed

echo.
echo [5/9] Committing and pushing the v3 release branch...
git config --get user.name >nul 2>&1 || git config user.name "%GH_LOGIN%"
git config --get user.email >nul 2>&1 || git config user.email "%GH_LOGIN%@users.noreply.github.com"
git add -A || goto :git_failed
git diff --cached --quiet && git commit --allow-empty -m "release: prepare dicodePing v3.0.0-pre.1 (v2rayN stack migration)" || git commit -m "release: prepare dicodePing v3.0.0-pre.1 (v2rayN stack migration)"
if errorlevel 1 goto :git_failed
git push --force -u origin "%RELEASE_BRANCH%" || goto :push_failed

echo.
echo [6/9] Creating or updating the pull request...
for /f "delims=" %%N in ('gh pr list --repo "%REPO%" --head "%RELEASE_BRANCH%" --state open --json number --jq ".[0].number"') do set "PR_NUMBER=%%N"
if not defined PR_NUMBER (
  gh pr create --repo "%REPO%" --base "%BASE_BRANCH%" --head "%RELEASE_BRANCH%" --title "release: dicodePing v3.0.0-pre.1 v2rayN stack migration" --body-file "docs\releases\v3.0.0-pre.1.md" || goto :pr_failed
  for /f "delims=" %%N in ('gh pr list --repo "%REPO%" --head "%RELEASE_BRANCH%" --state open --json number --jq ".[0].number"') do set "PR_NUMBER=%%N"
) else (
  gh pr edit !PR_NUMBER! --repo "%REPO%" --title "release: dicodePing v3.0.0-pre.1 v2rayN stack migration" --body-file "docs\releases\v3.0.0-pre.1.md" || goto :pr_failed
)
if not defined PR_NUMBER goto :pr_failed
echo [OK] Pull request #!PR_NUMBER! is ready.

echo.
echo [7/9] Waiting for CI and merging the pull request...
gh pr ready !PR_NUMBER! --repo "%REPO%" >nul 2>&1
gh pr checks !PR_NUMBER! --repo "%REPO%" --watch --fail-fast || goto :checks_failed
gh pr merge !PR_NUMBER! --repo "%REPO%" --squash --delete-branch || goto :merge_failed

popd

echo.
echo [8/9] Dispatching the four-platform prerelease workflow...
gh release view "%TAG%" --repo "%REPO%" >nul 2>&1 && gh release delete "%TAG%" --repo "%REPO%" --yes --cleanup-tag
gh workflow run "%WORKFLOW%" --repo "%REPO%" --ref "%BASE_BRANCH%" || goto :release_failed
for /L %%A in (1,1,30) do (
  for /f "delims=" %%R in ('gh run list --repo "%REPO%" --workflow "%WORKFLOW%" --branch "%BASE_BRANCH%" --event workflow_dispatch --limit 1 --json databaseId --jq ".[0].databaseId"') do set "RUN_ID=%%R"
  if defined RUN_ID goto :run_found
  timeout /t 2 /nobreak >nul
)
goto :release_failed

:run_found
echo Workflow run: !RUN_ID!
gh run watch !RUN_ID! --repo "%REPO%" --exit-status || goto :release_failed

echo.
echo [9/9] Verifying GitHub marked the release as a prerelease...
for /f "delims=" %%U in ('gh release view "%TAG%" --repo "%REPO%" --json isPrerelease,isDraft,url --jq "select(.isPrerelease == true and .isDraft == false) ^| .url"') do set "RELEASE_URL=%%U"
if not defined RELEASE_URL goto :release_verify_failed

echo.
echo ================================================================
echo  SUCCESS: %TAG% IS PUBLISHED AS A VERIFIED PRERELEASE
echo  (v2rayN stack + modern UI - all 4 platforms)
echo ================================================================
echo !RELEASE_URL!
start "" "!RELEASE_URL!"
if exist "%STAGE_DIR%" rmdir /s /q "%STAGE_DIR%" >nul 2>&1
pause
exit /b 0

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
  echo [INFO] Installing GitHub CLI with winget...
  where winget >nul 2>&1 || exit /b 1
  winget install --id GitHub.cli --exact --source winget --accept-package-agreements --accept-source-agreements || exit /b 1
  set "PATH=%PATH%;C:\Program Files\GitHub CLI"
)
where gh >nul 2>&1 || exit /b 1
gh auth status --hostname github.com >nul 2>&1
if errorlevel 1 (
  echo [INFO] Complete GitHub sign-in in your browser...
  gh auth login --hostname github.com --git-protocol https --web || exit /b 1
)
gh auth setup-git >nul 2>&1
exit /b 0

:find_python
where py >nul 2>&1 && (set "PYTHON_CMD=py -3" & exit /b 0)
where python >nul 2>&1 && (set "PYTHON_CMD=python" & exit /b 0)
echo [ERROR] Python 3 was not found.
exit /b 1

:missing_source
echo [ERROR] Run this BAT from the v3.0.0-pre.1 source folder.
goto :failed
:auth_failed
echo [ERROR] GitHub authentication could not be verified.
goto :failed
:clone_failed
echo [ERROR] Repository clone failed.
goto :failed
:copy_path_failed
echo [ERROR] Source and staging paths unexpectedly resolve to the same directory.
goto :failed
:copy_failed
echo [ERROR] Source copy failed with robocopy code !ROBOCOPY_CODE!.
goto :failed
:validation_failed
echo [ERROR] v3 validation failed. Nothing was pushed or released.
popd >nul 2>&1
goto :failed
:git_failed
echo [ERROR] Git operation failed.
popd >nul 2>&1
goto :failed
:push_failed
echo [ERROR] Branch push failed.
popd >nul 2>&1
goto :failed
:pr_failed
echo [ERROR] Pull request creation/update failed.
popd >nul 2>&1
goto :failed
:checks_failed
echo [ERROR] Pull request checks failed. The PR remains open for inspection.
popd >nul 2>&1
goto :failed
:merge_failed
echo [ERROR] Pull request merge failed.
popd >nul 2>&1
goto :failed
:release_failed
echo [ERROR] Release workflow failed. Inspect GitHub Actions for logs.
goto :failed
:release_verify_failed
echo [ERROR] Workflow finished, but %TAG% is not a non-draft prerelease.
goto :failed
:failed
echo.
echo No successful v3 prerelease was reported.
echo https://github.com/%REPO%/actions
echo.
echo Ensure GH_TOKEN environment variable is set for automated releases.
pause
exit /b 1
