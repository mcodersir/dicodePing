@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "TARGET=%CD%\local-maven\ir\dicode\local\libv2ray\26.6.2\libv2ray-26.6.2.aar"
set "SOURCE=%~1"
if not defined SOURCE set "SOURCE=%USERPROFILE%\Downloads\libv2ray.aar"

if not exist "%SOURCE%" (
  echo Core file not found: %SOURCE%
  echo.
  echo Download it manually from:
  echo https://github.com/2dust/AndroidLibXrayLite/releases/download/v26.6.2/libv2ray.aar
  echo.
  echo Then either place it directly at:
  echo %TARGET%
  echo.
  echo Or run:
  echo prepare_core.bat "C:\path\to\libv2ray.aar"
  exit /b 1
)

for /f "usebackq delims=" %%H in (`powershell -NoProfile -Command "(Get-FileHash -LiteralPath '%SOURCE%' -Algorithm SHA256).Hash.ToLowerInvariant()"`) do set "ACTUAL_SHA=%%H"
set "EXPECTED_SHA=367d6b2f74e62c974c61210c56802127812be4c9410a83a6b8b6cac765a7595e"
if /I not "%ACTUAL_SHA%"=="%EXPECTED_SHA%" (
  echo Android core SHA-256 mismatch.
  echo Expected: %EXPECTED_SHA%
  echo Actual:   %ACTUAL_SHA%
  exit /b 1
)

if not exist "%CD%\local-maven\ir\dicode\local\libv2ray\26.6.2" mkdir "%CD%\local-maven\ir\dicode\local\libv2ray\26.6.2"
copy /y "%SOURCE%" "%TARGET%" >nul
if errorlevel 1 exit /b 1

echo Android core verified and installed:
echo %TARGET%
exit /b 0
