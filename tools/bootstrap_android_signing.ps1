[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[^/]+/[^/]+$')]
    [string]$Repository,

    [string]$BackupDirectory = (Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'dicodePing-signing')
)

$ErrorActionPreference = 'Stop'
$requiredSecrets = @(
    'ANDROID_KEYSTORE_BASE64',
    'ANDROID_KEYSTORE_PASSWORD',
    'ANDROID_KEY_ALIAS',
    'ANDROID_KEY_PASSWORD'
)

function Write-Step([string]$Message) {
    Write-Host "[SIGNING] $Message" -ForegroundColor Cyan
}

function Get-RepositorySecretNames {
    $json = & gh secret list --repo $Repository --app actions --json name 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Could not read GitHub Actions secrets for $Repository.`n$json"
    }
    if (-not $json) { return @() }
    return @($json | ConvertFrom-Json | ForEach-Object { $_.name })
}

function Get-RandomAlphaNumeric([int]$Length = 40) {
    $alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'
    $bytes = New-Object byte[] ($Length * 2)
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    }
    finally {
        $rng.Dispose()
    }
    $chars = New-Object System.Collections.Generic.List[char]
    foreach ($byte in $bytes) {
        if ($chars.Count -ge $Length) { break }
        $limit = 256 - (256 % $alphabet.Length)
        if ($byte -lt $limit) {
            $chars.Add($alphabet[$byte % $alphabet.Length])
        }
    }
    if ($chars.Count -lt $Length) {
        return Get-RandomAlphaNumeric -Length $Length
    }
    return -join $chars
}

function Find-Keytool {
    $command = Get-Command keytool.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }

    $candidates = New-Object System.Collections.Generic.List[string]
    if ($env:JAVA_HOME) {
        $candidates.Add((Join-Path $env:JAVA_HOME 'bin\keytool.exe'))
    }
    $candidates.Add((Join-Path $env:ProgramFiles 'Android\Android Studio\jbr\bin\keytool.exe'))
    if (${env:ProgramFiles(x86)}) {
        $candidates.Add((Join-Path ${env:ProgramFiles(x86)} 'Android\Android Studio\jbr\bin\keytool.exe'))
    }

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    foreach ($root in @(
        (Join-Path $env:ProgramFiles 'Eclipse Adoptium'),
        (Join-Path $env:ProgramFiles 'Java'),
        (Join-Path $env:ProgramFiles 'Microsoft')
    )) {
        if (-not (Test-Path -LiteralPath $root -PathType Container)) { continue }
        $match = Get-ChildItem -LiteralPath $root -Filter keytool.exe -File -Recurse -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending |
            Select-Object -First 1
        if ($match) { return $match.FullName }
    }
    return $null
}

function Ensure-Keytool {
    $keytool = Find-Keytool
    if ($keytool) { return $keytool }

    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw 'Java keytool was not found and winget is unavailable. Install JDK 17 or Android Studio, then run the deployer again.'
    }

    Write-Step 'Java keytool was not found. Installing Temurin JDK 17 through winget...'
    & $winget.Source install --id EclipseAdoptium.Temurin.17.JDK --exact --source winget --accept-package-agreements --accept-source-agreements --silent
    if ($LASTEXITCODE -ne 0) {
        throw "Temurin JDK 17 installation failed with exit code $LASTEXITCODE."
    }

    $keytool = Find-Keytool
    if (-not $keytool) {
        throw 'JDK installation finished, but keytool.exe still could not be located. Restart Windows and run the deployer again.'
    }
    return $keytool
}

function Read-SigningBackup([string]$EnvPath, [string]$KeystorePath) {
    if (-not (Test-Path -LiteralPath $EnvPath -PathType Leaf)) { return $null }
    if (-not (Test-Path -LiteralPath $KeystorePath -PathType Leaf)) { return $null }

    $values = @{}
    foreach ($line in Get-Content -LiteralPath $EnvPath -Encoding UTF8) {
        if ([string]::IsNullOrWhiteSpace($line) -or $line.TrimStart().StartsWith('#')) { continue }
        $parts = $line -split '=', 2
        if ($parts.Count -eq 2) { $values[$parts[0].Trim()] = $parts[1] }
    }
    foreach ($name in @('ANDROID_KEYSTORE_PASSWORD', 'ANDROID_KEY_ALIAS', 'ANDROID_KEY_PASSWORD')) {
        if (-not $values.ContainsKey($name) -or [string]::IsNullOrWhiteSpace($values[$name])) {
            return $null
        }
    }
    return $values
}

function Protect-BackupDirectory([string]$Path) {
    try {
        $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        & icacls.exe $Path /inheritance:r /grant:r "${identity}:(OI)(CI)F" /T /C | Out-Null
    }
    catch {
        Write-Warning "Could not restrict NTFS permissions on $Path. Keep this folder private. $($_.Exception.Message)"
    }
}

function New-SigningBackup([string]$KeytoolPath, [string]$KeystorePath, [string]$EnvPath) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $KeystorePath) | Out-Null

    $password = Get-RandomAlphaNumeric 48
    $alias = 'dicodeping'
    $env:DICODEPING_STORE_PASS = $password
    $env:DICODEPING_KEY_PASS = $password
    try {
        $arguments = @(
            '-genkeypair',
            '-v',
            '-keystore', $KeystorePath,
            '-storetype', 'JKS',
            '-storepass:env', 'DICODEPING_STORE_PASS',
            '-keypass:env', 'DICODEPING_KEY_PASS',
            '-alias', $alias,
            '-keyalg', 'RSA',
            '-keysize', '4096',
            '-sigalg', 'SHA256withRSA',
            '-validity', '10000',
            '-dname', 'CN=dicodePing Release, OU=Android, O=mcodersir, L=Warsaw, ST=Mazowieckie, C=PL'
        )
        & $KeytoolPath @arguments
        if ($LASTEXITCODE -ne 0) {
            throw "keytool failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Remove-Item Env:DICODEPING_STORE_PASS -ErrorAction SilentlyContinue
        Remove-Item Env:DICODEPING_KEY_PASS -ErrorAction SilentlyContinue
    }

    if (-not (Test-Path -LiteralPath $KeystorePath -PathType Leaf) -or (Get-Item -LiteralPath $KeystorePath).Length -lt 1000) {
        throw 'The generated Android keystore is missing or incomplete.'
    }

    @(
        '# PRIVATE dicodePing Android signing backup. Never commit or share this file.',
        "ANDROID_KEYSTORE_PASSWORD=$password",
        "ANDROID_KEY_ALIAS=$alias",
        "ANDROID_KEY_PASSWORD=$password"
    ) | Set-Content -LiteralPath $EnvPath -Encoding UTF8

    @(
        'PRIVATE ANDROID SIGNING BACKUP',
        '',
        'Keep release.jks and signing.env together and private.',
        'Deleting or replacing this key prevents future APK updates over builds signed with it.',
        'The one-click deployer can restore missing GitHub Actions secrets from this folder.'
    ) | Set-Content -LiteralPath (Join-Path (Split-Path -Parent $KeystorePath) 'README_PRIVATE.txt') -Encoding UTF8

    Protect-BackupDirectory (Split-Path -Parent $KeystorePath)
    return @{
        ANDROID_KEYSTORE_PASSWORD = $password
        ANDROID_KEY_ALIAS = $alias
        ANDROID_KEY_PASSWORD = $password
    }
}

function Upload-SigningSecrets([hashtable]$Values, [string]$KeystorePath) {
    $keystoreBase64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes($KeystorePath))
    $temporaryEnv = Join-Path $env:TEMP ("dicodePing-signing-secrets-{0}.env" -f [Guid]::NewGuid().ToString('N'))
    try {
        @(
            "ANDROID_KEYSTORE_BASE64=$keystoreBase64",
            "ANDROID_KEYSTORE_PASSWORD=$($Values.ANDROID_KEYSTORE_PASSWORD)",
            "ANDROID_KEY_ALIAS=$($Values.ANDROID_KEY_ALIAS)",
            "ANDROID_KEY_PASSWORD=$($Values.ANDROID_KEY_PASSWORD)"
        ) | Set-Content -LiteralPath $temporaryEnv -Encoding ASCII

        & gh secret set --repo $Repository --app actions --env-file $temporaryEnv
        if ($LASTEXITCODE -ne 0) {
            throw "gh secret set failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Remove-Item -LiteralPath $temporaryEnv -Force -ErrorAction SilentlyContinue
    }
}

$existing = Get-RepositorySecretNames
$missing = @($requiredSecrets | Where-Object { $_ -notin $existing })
if ($missing.Count -eq 0) {
    Write-Host '[OK] Required Android signing secrets are already configured.' -ForegroundColor Green
    exit 0
}

Write-Warning ("Missing Android signing secrets: {0}" -f ($missing -join ', '))
Write-Step 'The deployer will create or restore one persistent signing key and upload all four secrets securely.'

$keystorePath = Join-Path $BackupDirectory 'release.jks'
$envPath = Join-Path $BackupDirectory 'signing.env'
$values = Read-SigningBackup -EnvPath $envPath -KeystorePath $keystorePath

if ($values) {
    Write-Step "Restoring the signing secrets from the private backup: $BackupDirectory"
}
else {
    if (Test-Path -LiteralPath $BackupDirectory) {
        $quarantine = "$BackupDirectory-incomplete-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        Write-Warning "The existing signing backup is incomplete. Moving it to $quarantine"
        Move-Item -LiteralPath $BackupDirectory -Destination $quarantine -Force
    }
    $keytool = Ensure-Keytool
    Write-Step "Generating a new persistent Android release keystore with $keytool"
    $values = New-SigningBackup -KeytoolPath $keytool -KeystorePath $keystorePath -EnvPath $envPath
}

Upload-SigningSecrets -Values $values -KeystorePath $keystorePath
$after = Get-RepositorySecretNames
$stillMissing = @($requiredSecrets | Where-Object { $_ -notin $after })
if ($stillMissing.Count -gt 0) {
    throw "GitHub did not report these secrets after upload: $($stillMissing -join ', ')"
}

Write-Host '[OK] Android signing secrets are configured and internally consistent.' -ForegroundColor Green
Write-Host "[IMPORTANT] Private signing backup: $BackupDirectory" -ForegroundColor Yellow
Write-Host '[IMPORTANT] Keep this folder safe. The same key is required for future APK updates.' -ForegroundColor Yellow
exit 0
