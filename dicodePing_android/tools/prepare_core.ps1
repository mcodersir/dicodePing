param(
    [string]$Source = "$env:USERPROFILE\Downloads\libv2ray.aar"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$targetDir = Join-Path $root "local-maven\ir\dicode\local\libv2ray\26.6.2"
$target = Join-Path $targetDir "libv2ray-26.6.2.aar"

if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
    throw "Core file not found: $Source`nDownload https://github.com/2dust/AndroidLibXrayLite/releases/download/v26.6.2/libv2ray.aar and place it at $target"
}

$expected = "367d6b2f74e62c974c61210c56802127812be4c9410a83a6b8b6cac765a7595e"
$actual = (Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $expected) {
    throw "Android core SHA-256 mismatch. Expected $expected, got $actual"
}

New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
Copy-Item -LiteralPath $Source -Destination $target -Force
Write-Host "Android core verified and installed: $target"
