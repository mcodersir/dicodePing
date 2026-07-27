[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[^/]+/[^/]+$')]
    [string]$Repository,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Tag,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$WorkflowFile,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$CommitSha,

    [ValidateNotNullOrEmpty()]
    [string]$Branch = 'main',

    [ValidateRange(1, 240)]
    [int]$TimeoutMinutes = 90
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$releaseUrl = "https://github.com/$Repository/releases/tag/$Tag"
$actionsUrl = "https://github.com/$Repository/actions/workflows/$WorkflowFile"
$encodedWorkflow = [Uri]::EscapeDataString($WorkflowFile)
$encodedBranch = [Uri]::EscapeDataString($Branch)
$runsApiUrl = "https://api.github.com/repos/$Repository/actions/workflows/$encodedWorkflow/runs?branch=$encodedBranch&event=push&per_page=20"
$releaseApiUrl = "https://api.github.com/repos/$Repository/releases/tags/$([Uri]::EscapeDataString($Tag))"
$headers = @{
    'User-Agent' = 'dicodePing-rc7-release-waiter'
    'Accept' = 'application/vnd.github+json'
    'X-GitHub-Api-Version' = '2022-11-28'
}

$requiredAssets = @(
    'dicodePing-v1.9.0-rc.7-windows-x64.exe',
    'dicodePing-v1.9.0-rc.7-linux-x86_64.tar.gz',
    'dicodePing-v1.9.0-rc.7-macos-arm64.dmg',
    'dicodePing-v1.9.0-rc.7-macos-x86_64.dmg',
    'dicodePing-v1.9.0-rc.7-android.apk'
)

$startedAt = Get-Date
$deadline = $startedAt.AddMinutes($TimeoutMinutes)
$run = $null
$lastStatus = $null
$successfulRunSeenAt = $null

Write-Host "[WAIT] Looking for workflow '$WorkflowFile' at commit $CommitSha"
Write-Host "[WAIT] Existing release pages are ignored until this exact run succeeds."

while ((Get-Date) -lt $deadline) {
    try {
        $runs = Invoke-RestMethod -Uri $runsApiUrl -Headers $headers -TimeoutSec 25
        $run = $runs.workflow_runs |
            Where-Object { $_.head_sha -eq $CommitSha } |
            Sort-Object created_at -Descending |
            Select-Object -First 1

        if ($null -eq $run) {
            $elapsed = [Math]::Floor(((Get-Date) - $startedAt).TotalMinutes)
            Write-Host "[WAIT] Exact workflow run is not visible yet - elapsed $elapsed min"
            Start-Sleep -Seconds 75
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
                Write-Host "[OK] Exact workflow run completed successfully. Verifying release assets..."
            }

            try {
                $release = Invoke-RestMethod -Uri $releaseApiUrl -Headers $headers -TimeoutSec 25
                $assetNames = @($release.assets | ForEach-Object { $_.name })
                $missing = @($requiredAssets | Where-Object { $_ -notin $assetNames })

                if ($release.prerelease -eq $true -and $missing.Count -eq 0) {
                    Write-Host "[OK] GitHub pre-release contains all required platform packages."
                    Write-Host "[OK] $releaseUrl"
                    exit 0
                }

                if ($release.prerelease -ne $true) {
                    Write-Warning "The release exists but is not marked as a prerelease yet."
                }
                if ($missing.Count -gt 0) {
                    Write-Host "[WAIT] Release update is still propagating. Missing assets: $($missing -join ', ')"
                }
            }
            catch {
                Write-Host "[WAIT] The successful workflow is visible, but the updated release API is not ready yet."
            }

            if (((Get-Date) - $successfulRunSeenAt).TotalMinutes -ge 5) {
                Write-Error "The workflow succeeded, but the release did not contain all required assets after five minutes. Open: $releaseUrl"
                exit 3
            }
        }
    }
    catch {
        Write-Warning "GitHub status check failed temporarily: $($_.Exception.Message)"
    }

    $elapsed = [Math]::Floor(((Get-Date) - $startedAt).TotalMinutes)
    Write-Host "[WAIT] Build or release update is still in progress - elapsed $elapsed min"
    Start-Sleep -Seconds 75
}

Write-Warning "Timed out waiting for the exact release workflow and assets."
if ($null -ne $run) {
    Write-Host "Last workflow run: $($run.html_url)"
}
else {
    Write-Host "Actions: $actionsUrl"
}
exit 2
