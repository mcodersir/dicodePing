[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[^/]+/[^/]+$')]
    [string]$Repository,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^v[0-9]+\.[0-9]+\.[0-9]+(?:-rc\.[0-9]+)?$')]
    [string]$Tag,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$WorkflowFile,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$CommitSha,

    [ValidateRange(1, 240)]
    [int]$TimeoutMinutes = 90
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$version = $Tag.Substring(1)
$releaseUrl = "https://github.com/$Repository/releases/tag/$Tag"
$encodedWorkflow = [Uri]::EscapeDataString($WorkflowFile)
$runsApiUrl = "https://api.github.com/repos/$Repository/actions/workflows/$encodedWorkflow/runs?per_page=50"
$releaseApiUrl = "https://api.github.com/repos/$Repository/releases/tags/$([Uri]::EscapeDataString($Tag))"
$latestApiUrl = "https://api.github.com/repos/$Repository/releases/latest"
$headers = @{
    'User-Agent' = 'dicodePing-release-waiter'
    'Accept' = 'application/vnd.github+json'
    'X-GitHub-Api-Version' = '2022-11-28'
}
$apiToken = if ($env:GH_TOKEN) { $env:GH_TOKEN } elseif ($env:GITHUB_TOKEN) { $env:GITHUB_TOKEN } else { $null }
if ($apiToken) { $headers['Authorization'] = "Bearer $apiToken" }

$requiredAssets = @(
    "dicodePing-v$version-windows-x64.exe",
    "dicodePing-v$version-linux-x86_64.tar.gz",
    "dicodePing-v$version-macos-arm64.dmg",
    "dicodePing-v$version-macos-x86_64.dmg",
    "dicodePing-v$version-android.apk"
)

$startedAt = Get-Date
$deadline = $startedAt.AddMinutes($TimeoutMinutes)
$lastStatus = $null
$successfulRunSeenAt = $null

Write-Host "[WAIT] Looking for workflow '$WorkflowFile' at commit $CommitSha"
Write-Host "[WAIT] Verifying stable release $Tag and all platform assets."

while ((Get-Date) -lt $deadline) {
    try {
        $runs = Invoke-RestMethod -Uri $runsApiUrl -Headers $headers -TimeoutSec 25
        $run = $runs.workflow_runs |
            Where-Object { $_.head_sha -eq $CommitSha } |
            Sort-Object created_at -Descending |
            Select-Object -First 1

        if ($null -eq $run) {
            Write-Host '[WAIT] Exact release workflow run is not visible yet.'
            Start-Sleep -Seconds 30
            continue
        }

        $statusText = if ($run.status -eq 'completed') { $run.conclusion } else { $run.status }
        if ($statusText -ne $lastStatus) {
            Write-Host "[ACTIONS] $statusText - $($run.html_url)"
            $lastStatus = $statusText
        }

        if ($run.status -eq 'completed' -and $run.conclusion -ne 'success') {
            Write-Error "GitHub Actions finished with conclusion '$($run.conclusion)'. Open: $($run.html_url)"
            exit 3
        }

        if ($run.status -eq 'completed' -and $run.conclusion -eq 'success') {
            if ($null -eq $successfulRunSeenAt) {
                $successfulRunSeenAt = Get-Date
                Write-Host '[OK] Exact release workflow succeeded. Verifying stable publication...'
            }
            try {
                $release = Invoke-RestMethod -Uri $releaseApiUrl -Headers $headers -TimeoutSec 25
                $latest = Invoke-RestMethod -Uri $latestApiUrl -Headers $headers -TimeoutSec 25
                $assetNames = @($release.assets | ForEach-Object { $_.name })
                $missing = @($requiredAssets | Where-Object { $_ -notin $assetNames })
                $publishedStable = ($release.draft -eq $false -and $release.prerelease -eq $false)
                $isLatest = ($latest.tag_name -eq $Tag)

                if ($publishedStable -and $isLatest -and $missing.Count -eq 0) {
                    Write-Host '[OK] Stable GitHub release is published, latest, and complete.'
                    Write-Host "[OK] $releaseUrl"
                    exit 0
                }
                if (-not $publishedStable) { Write-Host '[WAIT] Release exists but is not published as stable yet.' }
                if (-not $isLatest) { Write-Host "[WAIT] Latest release still points to $($latest.tag_name)." }
                if ($missing.Count -gt 0) { Write-Host "[WAIT] Missing assets: $($missing -join ', ')" }
            }
            catch {
                Write-Host "[WAIT] Release API is still propagating: $($_.Exception.Message)"
            }

            if (((Get-Date) - $successfulRunSeenAt).TotalMinutes -ge 10) {
                Write-Error "Workflow succeeded but the stable latest release was not complete after ten minutes: $releaseUrl"
                exit 3
            }
        }
    }
    catch {
        Write-Host "[WAIT] Temporary GitHub status error: $($_.Exception.Message)"
    }

    $elapsed = [Math]::Floor(((Get-Date) - $startedAt).TotalMinutes)
    Write-Host "[WAIT] Release is still in progress - elapsed $elapsed min"
    Start-Sleep -Seconds 45
}

Write-Error 'Timed out waiting for the stable release workflow and assets.'
exit 2
