[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[^/]+/[^/]+$')]
    [string]$Repository,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Tag,

    [ValidateRange(1, 240)]
    [int]$TimeoutMinutes = 90
)

$ErrorActionPreference = 'Stop'
$releaseUrl = "https://github.com/$Repository/releases/tag/$Tag"
$actionsUrl = "https://github.com/$Repository/actions"
$apiUrl = "https://api.github.com/repos/$Repository/actions/runs?event=push&branch=$([Uri]::EscapeDataString($Tag))&per_page=5"
$headers = @{
    'User-Agent' = 'dicodePing-release-waiter'
    'Accept' = 'application/vnd.github+json'
    'X-GitHub-Api-Version' = '2022-11-28'
}
$startedAt = Get-Date
$deadline = $startedAt.AddMinutes($TimeoutMinutes)
$attempt = 0
$runUrl = $null

while ((Get-Date) -lt $deadline) {
    $attempt++

    try {
        $response = Invoke-WebRequest `
            -Uri $releaseUrl `
            -Method Head `
            -MaximumRedirection 5 `
            -UseBasicParsing `
            -TimeoutSec 20 `
            -Headers $headers

        if ([int]$response.StatusCode -eq 200) {
            Write-Host "[OK] GitHub pre-release is available: $releaseUrl"
            exit 0
        }
    }
    catch {
        # GitHub returns 404 until the release job publishes the page.
    }

    # Query Actions only once every 90 seconds to stay below the anonymous API limit.
    if (($attempt % 3) -eq 1) {
        try {
            $runs = Invoke-RestMethod -Uri $apiUrl -Headers $headers -TimeoutSec 20
            $run = $runs.workflow_runs |
                Where-Object { $_.head_branch -eq $Tag -or $_.display_title -like "*$Tag*" } |
                Sort-Object created_at -Descending |
                Select-Object -First 1

            if ($null -ne $run) {
                $runUrl = $run.html_url
                $statusText = if ($run.status -eq 'completed') { $run.conclusion } else { $run.status }
                Write-Host "[ACTIONS] $statusText - $runUrl"

                if ($run.status -eq 'completed' -and $run.conclusion -in @('failure', 'cancelled', 'timed_out', 'action_required', 'startup_failure')) {
                    Write-Error "GitHub Actions finished with conclusion '$($run.conclusion)'. Open: $runUrl"
                    exit 3
                }
            }
        }
        catch {
            # Anonymous API checks are optional. Release-page polling continues.
        }
    }

    $elapsed = [Math]::Floor(((Get-Date) - $startedAt).TotalMinutes)
    Write-Host ("[WAIT] Build is queued or running - elapsed {0} min - check {1}" -f $elapsed, (Get-Date -Format 'HH:mm:ss'))
    Start-Sleep -Seconds 30
}

Write-Warning "Timed out waiting for $releaseUrl"
if ($runUrl) {
    Write-Host "Last workflow run: $runUrl"
}
else {
    Write-Host "Actions: $actionsUrl"
}
exit 2
