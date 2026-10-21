[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$PythonPath,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$VenvPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-NormalizedFullPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $pathRoot = [System.IO.Path]::GetPathRoot($fullPath)
    if ($fullPath.Length -gt $pathRoot.Length) {
        $fullPath = $fullPath.TrimEnd('\', '/')
    }
    return $fullPath
}

function Test-PathIsWithin {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Root
    )

    $normalizedPath = Get-NormalizedFullPath -Path $Path
    $normalizedRoot = Get-NormalizedFullPath -Path $Root
    $rootWithSeparator = if ($normalizedRoot.EndsWith('\')) {
        $normalizedRoot
    } else {
        $normalizedRoot + '\'
    }
    return (
        $normalizedPath.Equals($normalizedRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
        $normalizedPath.StartsWith($rootWithSeparator, [System.StringComparison]::OrdinalIgnoreCase)
    )
}

function Assert-NoReparsePathComponent {
    param([Parameter(Mandatory = $true)][string]$Path)

    $cursor = Get-NormalizedFullPath -Path $Path
    while ($null -ne $cursor -and $cursor.Length -gt 0) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "Path uses a reparse point; choose a direct local path: $Path"
            }
        }

        $parent = [System.IO.Directory]::GetParent($cursor)
        if ($null -eq $parent -or $parent.FullName.Equals($cursor, [System.StringComparison]::OrdinalIgnoreCase)) {
            break
        }
        $cursor = $parent.FullName
    }
}

function Invoke-PythonJson {
    param(
        [Parameter(Mandatory = $true)][string]$Interpreter,
        [Parameter(Mandatory = $true)][string]$Code,
        [Parameter(Mandatory = $true)][string]$Description
    )

    $lines = & $Interpreter -I -c $Code
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "$Description failed with exit code $exitCode."
    }

    $jsonText = ($lines -join [System.Environment]::NewLine).Trim()
    try {
        return $jsonText | ConvertFrom-Json -ErrorAction Stop
    } catch {
        throw "$Description returned invalid interpreter metadata."
    }
}

function Assert-SamePath {
    param(
        [Parameter(Mandatory = $true)][string]$Actual,
        [Parameter(Mandatory = $true)][string]$Expected,
        [Parameter(Mandatory = $true)][string]$Description
    )

    $actualPath = Get-NormalizedFullPath -Path $Actual
    $expectedPath = Get-NormalizedFullPath -Path $Expected
    if (-not $actualPath.Equals($expectedPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Description does not match the requested path."
    }
}

if ($env:OS -ne 'Windows_NT' -or [System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw 'This setup supports Windows 11 x64 only.'
}

$runtimeOsArchitecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
if ($runtimeOsArchitecture -ne 'X64') {
    throw 'This setup supports Windows 11 x64 only; ARM64 and 32-bit Windows are unsupported.'
}

$osVersion = [System.Environment]::OSVersion.Version
if ($osVersion.Major -lt 10 -or ($osVersion.Major -eq 10 -and $osVersion.Build -lt 22000)) {
    throw 'Windows 11 (build 22000 or newer) is required.'
}

try {
    $osProductType = (Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop).ProductType
} catch {
    throw 'Could not verify the Windows workstation edition; refusing setup.'
}
if ($osProductType -ne 1) {
    throw 'This setup supports Windows 11 workstation editions only; Windows Server is unsupported.'
}
$currentIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
if ($currentIdentity.Owner.Value -ne $currentIdentity.User.Value) {
    throw 'Use a non-elevated user shell: default file ownership must match the current user.'
}

if ($PythonPath -notmatch '^[A-Za-z]:\\') {
    throw '-PythonPath must be an explicit absolute local Windows path to python.exe.'
}
if ($VenvPath -notmatch '^[A-Za-z]:\\') {
    throw '-VenvPath must be an explicit absolute local Windows path.'
}

$pythonItem = Get-Item -LiteralPath $PythonPath -ErrorAction Stop
if ($pythonItem.PSIsContainer -or $pythonItem.Name -ine 'python.exe') {
    throw '-PythonPath must name an existing python.exe file.'
}
$pythonExe = Get-NormalizedFullPath -Path $pythonItem.FullName

$repoRoot = Get-NormalizedFullPath -Path (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..') -ErrorAction Stop).Path
if (-not (Test-Path -LiteralPath (Join-Path $repoRoot 'pyproject.toml') -PathType Leaf)) {
    throw 'The setup script is not inside a chatgpt-web2api repository.'
}
Assert-NoReparsePathComponent -Path $repoRoot

$venvFullPath = Get-NormalizedFullPath -Path $VenvPath
if (Test-PathIsWithin -Path $venvFullPath -Root $repoRoot) {
    throw '-VenvPath must be outside the repository; no repository-local venv will be created.'
}
Assert-NoReparsePathComponent -Path $venvFullPath

$pythonInfoCode = 'import json, platform, struct, sys; print(json.dumps({"implementation": sys.implementation.name, "major": sys.version_info.major, "minor": sys.version_info.minor, "micro": sys.version_info.micro, "platform": sys.platform, "machine": platform.machine(), "pointer_bits": struct.calcsize("P") * 8, "base_prefix": sys.base_prefix}))'
$pythonInfo = Invoke-PythonJson -Interpreter $pythonExe -Code $pythonInfoCode -Description 'Selected Python interpreter check'
if ($pythonInfo.implementation -ne 'cpython' -or $pythonInfo.major -ne 3 -or $pythonInfo.minor -ne 12) {
    throw 'The selected interpreter must be CPython 3.12.x.'
}
if ($pythonInfo.platform -ne 'win32' -or $pythonInfo.pointer_bits -ne 64 -or $pythonInfo.machine -notin @('AMD64', 'x86_64')) {
    throw 'The selected interpreter must be 64-bit CPython for Windows x64.'
}
$pythonBasePrefix = Get-NormalizedFullPath -Path ([string]$pythonInfo.base_prefix)

$markerPath = Join-Path $venvFullPath '.w2a-windows-setup.json'
$venvPython = Join-Path $venvFullPath 'Scripts\python.exe'
$venvExists = Test-Path -LiteralPath $venvFullPath
if ($venvExists) {
    $venvItem = Get-Item -LiteralPath $venvFullPath -Force
    if (-not $venvItem.PSIsContainer) {
        throw '-VenvPath already exists as a file; it was left untouched.'
    }
    if (-not (Test-Path -LiteralPath $markerPath -PathType Leaf)) {
        throw "-VenvPath already exists without this setup's ownership marker; it was left untouched: $venvFullPath"
    }

    try {
        $marker = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json -ErrorAction Stop
    } catch {
        throw "The existing setup marker is unreadable; the environment was left untouched: $markerPath"
    }
    if ($marker.schema_version -ne 1) {
        throw 'The existing setup marker has an unsupported version; the environment was left untouched.'
    }
    Assert-SamePath -Actual ([string]$marker.repository_root) -Expected $repoRoot -Description 'Marked repository root'
    Assert-SamePath -Actual ([string]$marker.python_executable) -Expected $pythonExe -Description 'Marked Python interpreter'
    Assert-SamePath -Actual ([string]$marker.python_base_prefix) -Expected $pythonBasePrefix -Description 'Marked Python base prefix'
} else {
    $venvParent = [System.IO.Path]::GetDirectoryName($venvFullPath)
    if ([string]::IsNullOrWhiteSpace($venvParent)) {
        throw 'Could not determine the parent directory for -VenvPath.'
    }
    if (-not (Test-Path -LiteralPath $venvParent -PathType Container)) {
        New-Item -ItemType Directory -Path $venvParent -Force | Out-Null
    }
    Assert-NoReparsePathComponent -Path $venvFullPath
    if (Test-Path -LiteralPath $venvFullPath) {
        throw '-VenvPath appeared during setup; refusing to use or modify it.'
    }

    # Create the exact target ourselves so Python cannot silently reuse an
    # unrelated directory. Never delete or replace a partially-created path.
    New-Item -ItemType Directory -Path $venvFullPath -ErrorAction Stop | Out-Null
    & $pythonExe -I -m venv $venvFullPath
    $venvCreationExitCode = $LASTEXITCODE
    if ($venvCreationExitCode -ne 0) {
        throw "Creating the virtual environment failed with exit code $venvCreationExitCode; the directory was preserved: $venvFullPath"
    }

    $marker = [ordered]@{
        schema_version = 1
        repository_root = $repoRoot
        python_executable = $pythonExe
        python_base_prefix = $pythonBasePrefix
    }
    $markerJson = $marker | ConvertTo-Json -Depth 4
    $markerBytes = [System.Text.Encoding]::UTF8.GetBytes($markerJson + [System.Environment]::NewLine)
    $markerStream = [System.IO.File]::Open(
        $markerPath,
        [System.IO.FileMode]::CreateNew,
        [System.IO.FileAccess]::Write,
        [System.IO.FileShare]::None
    )
    try {
        $markerStream.Write($markerBytes, 0, $markerBytes.Length)
    } finally {
        $markerStream.Dispose()
    }
}

if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    throw "The marked virtual environment has no Scripts\python.exe; it was left untouched: $venvFullPath"
}
$venvInfoCode = 'import json, platform, struct, sys; print(json.dumps({"implementation": sys.implementation.name, "major": sys.version_info.major, "minor": sys.version_info.minor, "platform": sys.platform, "machine": platform.machine(), "pointer_bits": struct.calcsize("P") * 8, "prefix": sys.prefix, "base_prefix": sys.base_prefix}))'
$venvInfo = Invoke-PythonJson -Interpreter $venvPython -Code $venvInfoCode -Description 'Virtual environment check'
if ($venvInfo.implementation -ne 'cpython' -or $venvInfo.major -ne 3 -or $venvInfo.minor -ne 12 -or
    $venvInfo.platform -ne 'win32' -or $venvInfo.pointer_bits -ne 64 -or
    $venvInfo.machine -notin @('AMD64', 'x86_64')) {
    throw 'The existing virtual environment is not 64-bit CPython 3.12.x for Windows x64; it was left untouched.'
}
Assert-SamePath -Actual ([string]$venvInfo.prefix) -Expected $venvFullPath -Description 'Virtual environment prefix'
Assert-SamePath -Actual ([string]$venvInfo.base_prefix) -Expected $pythonBasePrefix -Description 'Virtual environment base interpreter'

Push-Location -LiteralPath $repoRoot
try {
    & $venvPython -I -m pip install --disable-pip-version-check --no-input --editable '.[dev]' 'build'
    $installExitCode = $LASTEXITCODE
    if ($installExitCode -ne 0) {
        throw "Installing the editable development package and build tool failed with exit code $installExitCode."
    }
} finally {
    Pop-Location
}

Write-Output "Windows 11 x64 CPython 3.12 setup is ready."
Write-Output "Repository: $repoRoot"
Write-Output "Interpreter: $pythonExe"
Write-Output "Virtual environment: $venvFullPath"
Write-Output "Virtual environment Python: $venvPython"
