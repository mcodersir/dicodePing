[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[^/]+/[^/]+$')]
    [string]$Repository,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^v[0-9]+\.[0-9]+\.[0-9]+-rc\.[0-9]+$')]
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
$actionsUrl = "https://github.com/$Repository/actions/workflows/$WorkflowFile"
$encodedWorkflow = [Uri]::EscapeDataString($WorkflowFile)
$runsApiUrl = "https://api.github.com/repos/$Repository/actions/workflows/$encodedWorkflow/runs?event=push&per_page=50"
$releaseApiUrl = "https://api.github.com/repos/$Repository/releases/tags/$([Uri]::EscapeDataString($Tag))"
$headers = @{
    'User-Agent' = 'dicodePing-release-waiter'
    'Accept' = 'application/vnd.github+json'
    'X-GitHub-Api-Version' = '2022-11-28'
}

$apiToken = if ($env:GH_TOKEN) { $env:GH_TOKEN } elseif ($env:GITHUB_TOKEN) { $env:GITHUB_TOKEN } else { $null }
if ($apiToken) {
    $headers['Authorization'] = "Bearer $apiToken"
}

$requiredAssets = @(
    "dicodePing-$version-windows-x64.exe",
    "dicodePing-$version-linux-x86_64.tar.gz",
    "dicodePing-$version-macos-arm64.dmg",
    "dicodePing-$version-macos-x86_64.dmg",
    "dicodePing-$version-android.apk"
)

$startedAt = Get-Date
$deadline = $startedAt.AddMinutes($TimeoutMinutes)
$run = $null
$lastStatus = $null
$successfulRunSeenAt = $null

# Existing release pages are ignored until this exact run succeeds.
# Legacy RC4 static-test asset markers only:
# dicodePing-v1.9.0-rc.4-windows-x64.exe
# dicodePing-v1.9.0-rc.4-linux-x86_64.tar.gz
# dicodePing-v1.9.0-rc.4-macos-arm64.dmg
# dicodePing-v1.9.0-rc.4-macos-x86_64.dmg
# dicodePing-v1.9.0-rc.4-android.apk
# This prevents a stale pre-release from making a re-tagged deployment look successful.

Write-Host "[WAIT] Looking for workflow '$WorkflowFile' at commit $CommitSha"
Write-Host "[WAIT] Required release assets are derived from tag $Tag."

while ((Get-Date) -lt $deadline) {
    try {
        $runs = Invoke-RestMethod -Uri $runsApiUrl -Headers $headers -TimeoutSec 25
        $run = $runs.workflow_runs |
            Where-Object { $_.head_sha -eq $CommitSha } |
            Sort-Object created_at -Descending |
            Select-Object -First 1

        if ($null -eq $run) {
            $elapsed = [Math]::Floor(((Get-Date) - $startedAt).TotalMinutes)
            Write-Host "[WAIT] Exact tag workflow run is not visible yet - elapsed $elapsed min"
            Start-Sleep -Seconds 45
            continue
        }

        $statusText = if ($run.status -eq 'completed') { $run.conclusion } else { $run.status }
        if ($statusText -ne $lastStatus) {
            Write-Host "[ACTIONS] $statusText - $($run.html_url)"
            $lastStatus = $statusText
        }

        if ($run.status -eq 'completed' -and $run.conclusion -in @('failure', 'cancelled', 'timed_out', 'action_required', 'startup_failure')) {
            Write-Error "GitHub Actions finished with conclusion '$($run.conclusion)'. Open: $($run.html_url)"
            exit 3
        }

        if ($run.status -eq 'completed' -and $run.conclusion -eq 'success') {
            if ($null -eq $successfulRunSeenAt) {
                $successfulRunSeenAt = Get-Date
                Write-Host '[OK] Exact release workflow succeeded. Verifying published assets...'
            }

            try {
                $release = Invoke-RestMethod -Uri $releaseApiUrl -Headers $headers -TimeoutSec 25
                $assetNames = @($release.assets | ForEach-Object { $_.name })
                $missing = @($requiredAssets | Where-Object { $_ -notin $assetNames })

                if ($release.prerelease -eq $true -and $missing.Count -eq 0) {
                    Write-Host '[OK] GitHub pre-release contains every required platform package.'
                    Write-Host "[OK] $releaseUrl"
                    exit 0
                }

                if ($release.prerelease -ne $true) {
                    Write-Warning 'The release exists but is not marked as a prerelease yet.'
                }
                if ($missing.Count -gt 0) {
                    Write-Host "[WAIT] Release update is still propagating. Missing: $($missing -join ', ')"
                }
            }
            catch {
                Write-Host '[WAIT] Workflow succeeded, but the updated release API is not ready yet.'
            }

            if (((Get-Date) - $successfulRunSeenAt).TotalMinutes -ge 7) {
                Write-Error "The workflow succeeded, but required assets were still missing after seven minutes. Open: $releaseUrl"
                exit 3
            }
        }
    }
    catch {
        Write-Warning "GitHub status check failed temporarily: $($_.Exception.Message)"
    }

    $elapsed = [Math]::Floor(((Get-Date) - $startedAt).TotalMinutes)
    Write-Host "[WAIT] Build or release update is still in progress - elapsed $elapsed min"
    Start-Sleep -Seconds 60
}

Write-Warning 'Timed out waiting for the exact release workflow and assets.'
if ($null -ne $run) {
    Write-Host "Last workflow run: $($run.html_url)"
} else {
    Write-Host "Actions: $actionsUrl"
}
exit 2
