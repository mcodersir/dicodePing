@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "TARGET=%CD%\local-maven\ir\dicode\local\libv2ray\26.7.11\libv2ray-26.7.11.aar"
set "SOURCE=%~1"
if not defined SOURCE set "SOURCE=%USERPROFILE%\Downloads\libv2ray.aar"

if not exist "%SOURCE%" (
  echo Core file not found: %SOURCE%
  echo.
  echo Download it manually from:
  echo https://github.com/2dust/AndroidLibXrayLite/releases/download/v26.7.11/libv2ray.aar
  echo.
  echo Then either place it directly at:
  echo %TARGET%
  echo.
  echo Or run:
  echo prepare_core.bat "C:\path\to\libv2ray.aar"
  exit /b 1
)

for /f "usebackq delims=" %%H in (`powershell -NoProfile -Command "(Get-FileHash -LiteralPath '%SOURCE%' -Algorithm SHA256).Hash.ToLowerInvariant()"`) do set "ACTUAL_SHA=%%H"
set "EXPECTED_SHA=0c79bb52dc4329aaa266601e56ce4f0cc756b43f97a43dccd08d4a4bfc9aa352"
if /I not "%ACTUAL_SHA%"=="%EXPECTED_SHA%" (
  echo Android core SHA-256 mismatch.
  echo Expected: %EXPECTED_SHA%
  echo Actual:   %ACTUAL_SHA%
  exit /b 1
)

if not exist "%CD%\local-maven\ir\dicode\local\libv2ray\26.7.11" mkdir "%CD%\local-maven\ir\dicode\local\libv2ray\26.7.11"
copy /y "%SOURCE%" "%TARGET%" >nul
if errorlevel 1 exit /b 1

echo Android core verified and installed:
echo %TARGET%
exit /b 0
