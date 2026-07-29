param(
    [Parameter(Mandatory = $true)][string]$Repository,
    [Parameter(Mandatory = $true)][string]$Tag,
    [Parameter(Mandatory = $true)][string]$CommitSha,
    [Parameter(Mandatory = $true)][string]$WorkflowFile,
    [int]$MaxAttempts = 8
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$env:GH_PROMPT_DISABLED = "1"
if (Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}

function Invoke-GhRetry {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [string]$Label = "GitHub request",
        [switch]$AllowNotFound
    )

    $lastOutput = ""
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        $previousPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        $lines = & gh @Arguments 2>&1
        $exitCode = $LASTEXITCODE
        $ErrorActionPreference = $previousPreference
        $lastOutput = ($lines | Out-String).Trim()

        if ($exitCode -eq 0) {
            return [pscustomobject]@{
                Success = $true
                NotFound = $false
                Output = $lastOutput
            }
        }

        if ($AllowNotFound -and $lastOutput -match '(?i)(HTTP\s+404|not found|release not found|reference does not exist)') {
            return [pscustomobject]@{
                Success = $false
                NotFound = $true
                Output = $lastOutput
            }
        }

        Write-Warning "$Label failed on attempt $attempt/$MaxAttempts."
        if ($lastOutput) {
            Write-Host ($lastOutput.Substring(0, [Math]::Min($lastOutput.Length, 600)))
        }
        if ($attempt -lt $MaxAttempts) {
            & gh auth setup-git *> $null
            $delay = [Math]::Min(45, 5 * $attempt)
            Write-Host "[RETRY] Waiting $delay seconds before retrying..."
            Start-Sleep -Seconds $delay
        }
    }

    throw "$Label failed after $MaxAttempts attempts. Last output: $lastOutput"
}

Write-Host "[RELEASE] Preparing $Tag at commit $CommitSha"

$commitState = Invoke-GhRetry -Arguments @(
    "api", "repos/$Repository/commits/$CommitSha",
    "--jq", ".sha"
) -Label "Verifying pushed commit"
if ($commitState.Output.Trim() -ne $CommitSha) {
    throw "The pushed commit is not available through the GitHub API."
}
Write-Host "[OK] Pushed commit is visible on GitHub."

$releaseState = Invoke-GhRetry -Arguments @(
    "release", "view", $Tag,
    "--repo", $Repository,
    "--json", "tagName"
) -Label "Checking existing release" -AllowNotFound

if ($releaseState.Success) {
    Write-Host "[RELEASE] Removing the previous release object..."
    Invoke-GhRetry -Arguments @(
        "release", "delete", $Tag,
        "--repo", $Repository,
        "--yes"
    ) -Label "Deleting existing release" | Out-Null
}

Write-Host "[RELEASE] Removing an old remote tag when present..."
$deleteRef = Invoke-GhRetry -Arguments @(
    "api", "-X", "DELETE",
    "repos/$Repository/git/refs/tags/$Tag"
) -Label "Deleting existing tag reference" -AllowNotFound

Write-Host "[RELEASE] Creating the tag through the GitHub Git References API..."
Invoke-GhRetry -Arguments @(
    "api", "-X", "POST",
    "repos/$Repository/git/refs",
    "-f", "ref=refs/tags/$Tag",
    "-f", "sha=$CommitSha"
) -Label "Creating release tag" | Out-Null

$tagState = Invoke-GhRetry -Arguments @(
    "api", "repos/$Repository/git/ref/tags/$Tag",
    "--jq", ".object.sha"
) -Label "Verifying release tag"

$remoteSha = $tagState.Output.Trim()
if ($remoteSha -ne $CommitSha) {
    throw "Remote tag verification failed. Expected $CommitSha but GitHub returned $remoteSha"
}
Write-Host "[OK] Remote tag points to the expected commit."

# Creating a ref through the API is reliable even when git HTTPS is temporarily
# unavailable. Explicit workflow_dispatch guarantees that release.yml starts at
# the tag, independent of whether GitHub emits a push event for the API-created ref.
Write-Host "[RELEASE] Dispatching $WorkflowFile at $Tag..."
Invoke-GhRetry -Arguments @(
    "workflow", "run", $WorkflowFile,
    "--repo", $Repository,
    "--ref", $Tag
) -Label "Dispatching release workflow" | Out-Null

Write-Host "[OK] Release tag and workflow trigger completed."
