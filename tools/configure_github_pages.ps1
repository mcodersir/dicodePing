[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[^/]+/[^/]+$')]
    [string]$Repository,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$Branch,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$CommitSha,

    [string]$WorkflowFile = 'docs.yml',

    [ValidateRange(1, 60)]
    [int]$TimeoutMinutes = 30
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$apiVersion = '2026-03-10'
$startedAt = Get-Date
$deadline = $startedAt.AddMinutes($TimeoutMinutes)

function Invoke-Gh {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [switch]$AllowFailure
    )

    $output = & gh @Arguments 2>&1
    $code = $LASTEXITCODE
    if ($code -ne 0 -and -not $AllowFailure) {
        throw "gh $($Arguments -join ' ') failed with exit code $code`n$output"
    }
    [pscustomobject]@{ ExitCode = $code; Output = ($output -join "`n") }
}

function Invoke-GhJson {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [switch]$AllowFailure
    )

    $result = Invoke-Gh -Arguments $Arguments -AllowFailure:$AllowFailure
    if ($result.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($result.Output)) {
        return $null
    }
    return $result.Output | ConvertFrom-Json
}

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw 'GitHub CLI (gh) is required for Pages setup and workflow monitoring.'
}

$auth = Invoke-Gh -Arguments @('auth', 'status', '--hostname', 'github.com') -AllowFailure
if ($auth.ExitCode -ne 0) {
    throw "GitHub CLI is not authenticated. Run: gh auth login --hostname github.com --git-protocol https --web"
}

Write-Host '[PAGES] Cancelling old queued/in-progress Documentation workflow runs...'
$runs = Invoke-GhJson -Arguments @(
    'run', 'list', '--repo', $Repository, '--workflow', $WorkflowFile,
    '--limit', '30', '--json', 'databaseId,status,conclusion,headSha,createdAt'
) -AllowFailure
if ($null -ne $runs) {
    foreach ($run in @($runs)) {
        if ($run.status -in @('queued', 'in_progress', 'waiting', 'pending', 'requested')) {
            Write-Host "[PAGES] Cancelling workflow run $($run.databaseId) ($($run.status))"
            [void](Invoke-Gh -Arguments @('run', 'cancel', [string]$run.databaseId, '--repo', $Repository) -AllowFailure)
        }
    }
}

Write-Host '[PAGES] Cancelling stale github-pages deployments when GitHub still reports them as active...'
$deployments = Invoke-GhJson -Arguments @(
    'api', '--header', 'Accept: application/vnd.github+json',
    '--header', "X-GitHub-Api-Version: $apiVersion",
    "repos/$Repository/deployments?environment=github-pages&per_page=30"
) -AllowFailure
if ($null -ne $deployments) {
    foreach ($deployment in @($deployments)) {
        $statuses = Invoke-GhJson -Arguments @(
            'api', '--header', 'Accept: application/vnd.github+json',
            '--header', "X-GitHub-Api-Version: $apiVersion",
            "repos/$Repository/deployments/$($deployment.id)/statuses?per_page=1"
        ) -AllowFailure
        $state = if ($null -ne $statuses -and @($statuses).Count -gt 0) { @($statuses)[0].state } else { $null }
        if ($state -in @('queued', 'pending', 'in_progress', 'waiting')) {
            Write-Host "[PAGES] Cancelling stale deployment for $($deployment.sha) ($state)"
            [void](Invoke-Gh -Arguments @(
                'api', '--method', 'POST',
                '--header', 'Accept: application/vnd.github+json',
                '--header', "X-GitHub-Api-Version: $apiVersion",
                "repos/$Repository/pages/deployments/$($deployment.sha)/cancel"
            ) -AllowFailure)
        }
    }
}

Write-Host '[PAGES] Enabling GitHub Actions as the Pages publishing source...'
$site = Invoke-Gh -Arguments @(
    'api', '--header', 'Accept: application/vnd.github+json',
    '--header', "X-GitHub-Api-Version: $apiVersion",
    "repos/$Repository/pages"
) -AllowFailure

if ($site.ExitCode -eq 0) {
    [void](Invoke-Gh -Arguments @(
        'api', '--method', 'PUT',
        '--header', 'Accept: application/vnd.github+json',
        '--header', "X-GitHub-Api-Version: $apiVersion",
        "repos/$Repository/pages", '-f', 'build_type=workflow'
    ))
} else {
    [void](Invoke-Gh -Arguments @(
        'api', '--method', 'POST',
        '--header', 'Accept: application/vnd.github+json',
        '--header', "X-GitHub-Api-Version: $apiVersion",
        "repos/$Repository/pages", '-f', 'build_type=workflow'
    ))
}

Write-Host "[PAGES] Dispatching $WorkflowFile on $Branch..."
[void](Invoke-Gh -Arguments @('workflow', 'run', $WorkflowFile, '--repo', $Repository, '--ref', $Branch))

$runId = $null
while ((Get-Date) -lt $deadline -and $null -eq $runId) {
    Start-Sleep -Seconds 5
    $candidateRuns = Invoke-GhJson -Arguments @(
        'run', 'list', '--repo', $Repository, '--workflow', $WorkflowFile,
        '--branch', $Branch, '--limit', '20',
        '--json', 'databaseId,status,conclusion,headSha,event,createdAt,url'
    ) -AllowFailure
    if ($null -eq $candidateRuns) {
        continue
    }

    $candidate = @($candidateRuns) |
        Where-Object { $_.headSha -eq $CommitSha -and $_.event -in @('workflow_dispatch', 'push') } |
        Sort-Object createdAt -Descending |
        Select-Object -First 1
    if ($null -ne $candidate) {
        $runId = [string]$candidate.databaseId
        Write-Host "[PAGES] Monitoring Documentation run $runId - $($candidate.url)"
    }
}

if ($null -eq $runId) {
    throw "Documentation workflow run for commit $CommitSha did not appear within $TimeoutMinutes minutes."
}

& gh run watch $runId --repo $Repository --exit-status --interval 10
if ($LASTEXITCODE -ne 0) {
    throw "GitHub Pages workflow failed. Open: https://github.com/$Repository/actions/workflows/$WorkflowFile"
}

$page = Invoke-GhJson -Arguments @(
    'api', '--header', 'Accept: application/vnd.github+json',
    '--header', "X-GitHub-Api-Version: $apiVersion",
    "repos/$Repository/pages"
)
if ($null -ne $page -and $page.html_url) {
    Write-Host "[OK] GitHub Pages deployed: $($page.html_url)"
} else {
    Write-Host "[OK] GitHub Pages workflow completed successfully."
}
