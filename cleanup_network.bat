@echo off
chcp 65001 >nul
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -Verb RunAs -FilePath '%~f0'"
  exit /b
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p=Join-Path $env:APPDATA 'dicodePing\runtime\xray-owned.json';" ^
  "if(Test-Path $p){try{$j=Get-Content $p -Raw|ConvertFrom-Json;$proc=Get-CimInstance Win32_Process -Filter ('ProcessId='+[int]$j.pid);if($proc.CommandLine -like ('*'+$j.config_path+'*') -and $proc.Name -like 'xray*'){Stop-Process -Id $j.pid -Force};foreach($ip in @($j.direct_routes)){Get-NetRoute -AddressFamily IPv4 -DestinationPrefix ($ip+'/32') -PolicyStore ActiveStore -ErrorAction SilentlyContinue|Remove-NetRoute -Confirm:$false};Remove-Item $p -Force}catch{}};" ^
  "Get-NetRoute -InterfaceAlias 'dicodePing-TUN' -ErrorAction SilentlyContinue|Remove-NetRoute -Confirm:$false;" ^
  "ipconfig /flushdns | Out-Null"

echo وضعیت شبکه متعلق به dicodePing پاک‌سازی شد.
pause
