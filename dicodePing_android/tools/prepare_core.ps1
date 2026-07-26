param(
    [string]$Source = "$env:USERPROFILE\Downloads\libv2ray.aar"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$targetDir = Join-Path $root "local-maven\ir\dicode\local\libv2ray\26.7.11"
$target = Join-Path $targetDir "libv2ray-26.7.11.aar"

if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
    throw "Core file not found: $Source`nDownload https://github.com/2dust/AndroidLibXrayLite/releases/download/v26.7.11/libv2ray.aar and place it at $target"
}

$expected = "0c79bb52dc4329aaa266601e56ce4f0cc756b43f97a43dccd08d4a4bfc9aa352"
$actual = (Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $expected) {
    throw "Android core SHA-256 mismatch. Expected $expected, got $actual"
}

New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
Copy-Item -LiteralPath $Source -Destination $target -Force
Write-Host "Android core verified and installed: $target"
