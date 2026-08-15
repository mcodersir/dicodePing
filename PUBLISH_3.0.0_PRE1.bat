@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

set "VERSION=3.0.0-pre.3"
set "TAG=v3.0.0-pre.3"
set "REPO=mcodersir/dicodePing"
set "REPO_URL=https://github.com/mcodersir/dicodePing.git"
set "WORKFLOW=release-v3.yml"
for %%I in ("%~dp0.") do set "SOURCE=%%~fI"
set "WORK=%TEMP%\dicodePing-v3-publish-%RANDOM%%RANDOM%"

rem If this project is already inside a clone of the target repository, preserve its
rem origin transport (HTTPS/GCM or SSH) instead of forcing another auth mechanism.
set "LOCAL_ORIGIN="
if exist "%SOURCE%\.git" (
  for /f "delims=" %%U in ('git -C "%SOURCE%" remote get-url origin 2^>nul') do set "LOCAL_ORIGIN=%%U"
  if defined LOCAL_ORIGIN (
    echo !LOCAL_ORIGIN! | findstr /I /C:"mcodersir/dicodePing" >nul 2>&1
    if not errorlevel 1 set "REPO_URL=!LOCAL_ORIGIN!"
  )
)

echo ============================================================
echo dicodePing %VERSION% pre-release publisher
echo Repository: https://github.com/%REPO%
echo Source:     %SOURCE%
echo Auth:       installed Git / Windows credential helper or SSH rewrite
echo ============================================================
echo.

where git >nul 2>&1 || (echo [ERROR] git.exe was not found.& exit /b 1)
where py >nul 2>&1 || (echo [ERROR] Python launcher ^(py.exe^) was not found.& exit /b 1)

rem Do NOT require GH_TOKEN. Git for Windows can use its configured credential helper
rem (for example Git Credential Manager), and Git also respects SSH/insteadOf settings.
echo [auth] Using the authentication already configured for git.exe.
for /f "delims=" %%H in ('git config --global credential.helper 2^>nul') do set "GIT_HELPER=%%H"
if defined GIT_HELPER echo [auth] Git credential helper: !GIT_HELPER!

set "DEFAULT_BRANCH=main"
set "DEFAULT_REF="
for /f "tokens=2" %%B in ('git ls-remote --symref "%REPO_URL%" HEAD 2^>nul ^| findstr /B /C:"ref:"') do set "DEFAULT_REF=%%B"
if defined DEFAULT_REF set "DEFAULT_BRANCH=!DEFAULT_REF:refs/heads/=!"
echo [ok] Default branch: !DEFAULT_BRANCH!

rem Existing release tags are recoverable. Record the old target and refresh the
rem exact Version 3 pre-release tag after the validated source commit is pushed.
set "REMOTE_TAG_EXISTS=0"
set "OLD_TAG_OBJECT="
for /f "tokens=1" %%S in ('git ls-remote --tags "%REPO_URL%" "refs/tags/%TAG%" 2^>nul') do (
  set "REMOTE_TAG_EXISTS=1"
  set "OLD_TAG_OBJECT=%%S"
)
if "!REMOTE_TAG_EXISTS!"=="1" (
  echo [info] Existing tag %TAG% found: !OLD_TAG_OBJECT!
  echo [info] It will be refreshed to the validated Version 3 commit and the pre-release workflow will be retriggered.
) else (
  echo [ok] Tag %TAG% does not exist yet; it will be created.
)

if exist "%WORK%" rmdir /s /q "%WORK%"
echo [1/7] Cloning %REPO% using installed Git...
git clone --depth 1 --branch "!DEFAULT_BRANCH!" --single-branch "%REPO_URL%" "%WORK%"
if errorlevel 1 (
  echo [ERROR] git clone failed.
  echo         Fix your normal GitHub Git authentication and run again.
  exit /b 1
)

echo [2/7] Replacing checkout with the manifest-verified Version 3 project...
py -3 "%SOURCE%\tools\sync_release_tree.py" --source "%SOURCE%" --destination "%WORK%"
if errorlevel 1 (
  echo [ERROR] Version 3 source sync failed.
  echo         The cloned repository was not pushed or tagged.
  exit /b 1
)

cd /d "%WORK%"

echo [3/7] Running Version 3 validation...
py -3 tools\validate_v3.py || exit /b 1
py -3 tools\validate_corehost_api_surface.py || exit /b 1
py -3 dicodePing_android\tools\validate_project.py || exit /b 1
py -3 tools\validate_android_source_references.py || exit /b 1
py -3 tools\validate_android_release.py || exit /b 1
py -3 tools\validate_workflow_yaml.py || exit /b 1
py -3 tools\validate_android_gradle_kts.py || exit /b 1
py -3 -m pytest -q tests\test_release.py || exit /b 1
py -3 -m compileall -q app.py dicodeping tools tests || exit /b 1

for /f "delims=" %%I in ('git config user.name 2^>nul') do set "GIT_USER_NAME=%%I"
if not defined GIT_USER_NAME git config user.name "dicodePing Release"
for /f "delims=" %%I in ('git config user.email 2^>nul') do set "GIT_USER_EMAIL=%%I"
if not defined GIT_USER_EMAIL git config user.email "dicodeping-release@users.noreply.github.com"

echo [4/7] Preparing Version 3 commit on !DEFAULT_BRANCH!...
git add -A
git diff --cached --quiet
if errorlevel 1 (
  git commit -m "release: dicodePing %VERSION%"
  if errorlevel 1 exit /b 1
) else (
  if "!REMOTE_TAG_EXISTS!"=="1" (
    echo [info] Source already matches !DEFAULT_BRANCH!; creating an empty release commit so GitHub receives a fresh tag push event.
    git commit --allow-empty -m "release: retrigger dicodePing %VERSION%"
    if errorlevel 1 exit /b 1
  ) else (
    echo [info] Source already matches !DEFAULT_BRANCH!; using the current commit for the new release tag.
  )
)

for /f "delims=" %%C in ('git rev-parse HEAD') do set "SHA=%%C"
echo [ok] Release commit: !SHA!

echo [5/7] Pushing Version 3 to !DEFAULT_BRANCH! using installed Git credentials...
git push origin "HEAD:refs/heads/!DEFAULT_BRANCH!"
if errorlevel 1 (
  echo [ERROR] git push failed.
  echo         No GH_TOKEN is required by this script. Git must already be authenticated
  echo         through Git Credential Manager, another credential helper, or your Git/SSH configuration.
  exit /b 1
)

echo [6/7] Creating or refreshing release tag %TAG%...
git tag -d "%TAG%" >nul 2>&1
git tag -a "%TAG%" -m "dicodePing %VERSION% pre-release"
if errorlevel 1 exit /b 1

if "!REMOTE_TAG_EXISTS!"=="1" (
  echo [info] Updating existing remote tag %TAG% to !SHA! ...
  git push --force origin "refs/tags/%TAG%:refs/tags/%TAG%"
) else (
  git push origin "refs/tags/%TAG%:refs/tags/%TAG%"
)
if errorlevel 1 (
  echo [ERROR] Could not push %TAG%.
  echo         If the repository has a tag protection/ruleset that blocks tag updates,
  echo         allow this exact release tag update for an administrator and run again.
  exit /b 1
)

echo.
echo [ok] Tag %TAG% now points at !SHA!.
echo [ok] .github/workflows/%WORKFLOW% is triggered by this tag push.
echo [ok] The workflow uses the built-in GitHub Actions token to create or update the PRE-RELEASE.
echo.

rem GitHub CLI is optional. If installed and authenticated, wait for the workflow
rem and verify the release. Publishing itself still uses Git + GitHub Actions.
set "HAS_GH=0"
where gh >nul 2>&1
if not errorlevel 1 (
  gh auth status --hostname github.com >nul 2>&1
  if not errorlevel 1 set "HAS_GH=1"
)

if "!HAS_GH!"=="1" (
  echo [7/7] GitHub CLI is available; waiting for release workflow...
  set "RUN_ID="
  for /L %%N in (1,1,48) do (
    if not defined RUN_ID (
      for /f "delims=" %%R in ('gh run list --repo "%REPO%" --workflow "%WORKFLOW%" --commit "!SHA!" --limit 1 --json databaseId --jq ".[0].databaseId // empty" 2^>nul') do set "RUN_ID=%%R"
      if not defined RUN_ID timeout /t 5 /nobreak >nul
    )
  )
  if defined RUN_ID (
    echo [ok] Workflow run: !RUN_ID!
    gh run watch !RUN_ID! --repo "%REPO%" --exit-status
    if errorlevel 1 (
      echo [ERROR] GitHub Actions release workflow failed.
      echo         Inspect: https://github.com/%REPO%/actions/runs/!RUN_ID!
      exit /b 1
    )
    set "IS_PRE="
    for /f "delims=" %%P in ('gh release view "%TAG%" --repo "%REPO%" --json isPrerelease --jq ".isPrerelease" 2^>nul') do set "IS_PRE=%%P"
    if /I not "!IS_PRE!"=="true" (
      echo [ERROR] Release exists but is not marked as a pre-release.
      exit /b 1
    )
    echo [ok] GitHub confirmed %TAG% is a pre-release.
  ) else (
    echo [warn] Could not discover the Actions run with gh.exe.
    echo        The tag was pushed successfully; check the Actions URL below.
  )
) else (
  echo [7/7] gh.exe is missing or not logged in. That is OK; it is not required.
  echo       GitHub Actions will create/update the pre-release on GitHub.
)

echo.
echo ============================================================
echo [OK] Version 3 source and tag were pushed to %REPO%.
echo The tag-triggered GitHub Actions workflow creates or refreshes the pre-release automatically.
echo Actions: https://github.com/%REPO%/actions/workflows/%WORKFLOW%
echo Release: https://github.com/%REPO%/releases/tag/%TAG%
echo ============================================================

if /I "%DICODEPING_KEEP_WORK%"=="1" (
  echo Temporary checkout kept at: %WORK%
) else (
  cd /d "%TEMP%"
  rmdir /s /q "%WORK%" >nul 2>&1
)
exit /b 0
