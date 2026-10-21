[CmdletBinding()]
param(
    [Parameter()]
    [string] $SourcePath = (Get-Location).Path
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$version = '8.21.2'
$assetName = 'gitleaks_8.21.2_windows_x64.zip'
$assetUrl = "https://github.com/gitleaks/gitleaks/releases/download/v$version/$assetName"
$officialChecksumsUrl = "https://github.com/gitleaks/gitleaks/releases/download/v$version/gitleaks_8.21.2_checksums.txt"
# SHA-256 from the official v8.21.2 checksums release asset (Windows x64 ZIP).
$expectedSha256 = 'f238c85e5f47e18fac779ce71ee11091cf70a0a8fb4415f165efba2800eef133'

$sourceItem = Get-Item -LiteralPath $SourcePath -ErrorAction Stop
if (-not $sourceItem.PSIsContainer) {
    throw 'The Gitleaks source path must be a directory.'
}
$sourceRoot = [System.IO.Path]::GetFullPath($sourceItem.FullName)
$gitRootOutput = (& git -C $sourceRoot rev-parse --show-toplevel 2>$null | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($gitRootOutput)) {
    throw 'The Gitleaks source path is not a readable Git worktree.'
}
$gitRoot = [System.IO.Path]::GetFullPath($gitRootOutput)
if (-not $gitRoot.Equals($sourceRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'The Gitleaks source path must be the Git worktree root.'
}
$shallowOutput = (& git -C $sourceRoot rev-parse --is-shallow-repository 2>$null | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $shallowOutput -cne 'false') {
    throw 'Gitleaks requires a complete Git history; refusing to scan a shallow or unknown checkout.'
}
$headSha = (& git -C $sourceRoot rev-parse --verify HEAD 2>$null | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $headSha -cnotmatch '^[0-9a-f]{40}$') {
    throw 'The Gitleaks source checkout did not provide an exact Git HEAD.'
}

if (-not [System.Environment]::Is64BitOperatingSystem) {
    throw 'The pinned Gitleaks release asset is for Windows x64.'
}
$temporaryBase = $env:RUNNER_TEMP
if ([string]::IsNullOrWhiteSpace($temporaryBase)) {
    $temporaryBase = [System.IO.Path]::GetTempPath()
}
$temporaryBase = [System.IO.Path]::GetFullPath($temporaryBase)
if (-not (Test-Path -LiteralPath $temporaryBase -PathType Container)) {
    throw 'The temporary directory is missing; refusing an unverified install path.'
}
$workDirectory = [System.IO.Path]::GetFullPath(
    (Join-Path $temporaryBase "gitleaks-$version-$([guid]::NewGuid().ToString('N'))")
)
$relativeWorkDirectory = [System.IO.Path]::GetRelativePath($temporaryBase, $workDirectory)
if ([System.IO.Path]::IsPathRooted($relativeWorkDirectory) -or
    $relativeWorkDirectory -eq '..' -or
    $relativeWorkDirectory.StartsWith('..' + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::Ordinal)) {
    throw 'The Gitleaks temporary path escaped the configured temporary directory.'
}
New-Item -ItemType Directory -Path $workDirectory -ErrorAction Stop | Out-Null

$preserveRedactedLog = $false
$scanLogPath = Join-Path $workDirectory 'gitleaks-scan-redacted.log'
try {
    $archivePath = Join-Path $workDirectory $assetName
    $gitleaksPath = Join-Path $workDirectory 'gitleaks.exe'

    $checksumText = Invoke-RestMethod -Uri $officialChecksumsUrl -TimeoutSec 60 -ErrorAction Stop
    $checksumPattern = '^(?<sha256>[0-9a-f]{64})\s+' + [System.Text.RegularExpressions.Regex]::Escape($assetName) + '\s*$'
    $checksumLines = @($checksumText -split "`r?`n" | Where-Object { $_ -match $checksumPattern })
    if ($checksumLines.Count -ne 1) {
        throw 'The official Gitleaks checksums asset did not contain exactly one Windows x64 entry.'
    }
    $officialSha256 = [System.Text.RegularExpressions.Regex]::Match(
        $checksumLines[0], $checksumPattern
    ).Groups['sha256'].Value
    if ($officialSha256 -cne $expectedSha256) {
        throw 'The official Gitleaks checksums asset did not match the reviewed pinned SHA-256.'
    }

    Invoke-WebRequest -Uri $assetUrl -OutFile $archivePath -MaximumRedirection 5 -TimeoutSec 120 -ErrorAction Stop
    $actualSha256 = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualSha256 -cne $expectedSha256) {
        throw "Gitleaks archive SHA-256 did not match the pinned value from $officialChecksumsUrl; refusing to execute it."
    }

    Add-Type -AssemblyName System.IO.Compression
    $archive = [System.IO.Compression.ZipFile]::OpenRead($archivePath)
    try {
        $entries = @($archive.Entries | Where-Object { $_.FullName -ceq 'gitleaks.exe' })
        if ($entries.Count -ne 1 -or $entries[0].Length -le 0) {
            throw 'The verified Gitleaks archive did not contain one non-empty gitleaks.exe entry.'
        }
        $inputStream = $entries[0].Open()
        try {
            $outputStream = [System.IO.File]::Open(
                $gitleaksPath,
                [System.IO.FileMode]::CreateNew,
                [System.IO.FileAccess]::Write,
                [System.IO.FileShare]::None
            )
            try {
                $inputStream.CopyTo($outputStream)
            }
            finally {
                $outputStream.Dispose()
            }
        }
        finally {
            $inputStream.Dispose()
        }
    }
    finally {
        $archive.Dispose()
    }

    $versionOutput = (& $gitleaksPath version 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $versionOutput -cne $version) {
        throw 'The verified Gitleaks binary did not report the pinned version.'
    }

    # Keep all scanner output outside the checkout. --redact is still supplied
    # so even the temporary diagnostics do not contain discovered secret values.
    & $gitleaksPath detect --source $sourceRoot --redact --verbose *> $scanLogPath
    $scanExitCode = $LASTEXITCODE
    if ($scanExitCode -ne 0) {
        $preserveRedactedLog = $true
        throw "Gitleaks full-history scan failed with exit code $scanExitCode. Redacted diagnostics are outside the checkout at $scanLogPath."
    }
    if (-not (Test-Path -LiteralPath $scanLogPath -PathType Leaf)) {
        throw 'Gitleaks produced no completion log; refusing to report a successful scan.'
    }
    Write-Output "Gitleaks $version full-history scan passed; HEAD=$headSha; verified archive SHA-256=$actualSha256."
}
finally {
    if ($preserveRedactedLog) {
        Write-Output "Redacted Gitleaks diagnostics retained outside the checkout: $scanLogPath"
    }
    else {
        $resolvedWorkDirectory = [System.IO.Path]::GetFullPath($workDirectory)
        $relativeCheck = [System.IO.Path]::GetRelativePath($temporaryBase, $resolvedWorkDirectory)
        if ([System.IO.Path]::IsPathRooted($relativeCheck) -or
            $relativeCheck -eq '..' -or
            $relativeCheck.StartsWith('..' + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::Ordinal)) {
            throw 'Refusing to remove a Gitleaks temporary path outside the configured temporary directory.'
        }
        Remove-Item -LiteralPath $resolvedWorkDirectory -Recurse -Force -ErrorAction Stop
    }
}
