# Windows 11 x64 local setup (CPython 3.12.x)

This document covers the supported local developer setup for the offline
orchestrator stack. The setup script requires a Windows 11 x64 workstation and
64-bit CPython 3.12.x. Windows Server, Windows 10, ARM64, other Python versions,
Linux and macOS are outside this setup contract.
Use a normal non-elevated user shell. The setup refuses a default object owner
different from the current user. Hosted Windows PowerShell was observed creating
Administrators-owned children; CI therefore verifies user ownership in Git Bash
before running the native Windows Python tests. No owner allowlist is relaxed.

The setup is developer tooling only. It creates a virtual environment outside
the checkout and installs the editable development package plus `build`. It
does not start Chrome, the API server, an MCP server, a worker, or any ChatGPT
provider operation. `pip` may access the configured Python package index to
install dependencies; this is not a provider call. Dependency versions are
resolved from the project declarations and configured package index, not from
a committed lockfile or a supply-chain attestation.

## Create the development environment

Use an absolute path to the exact 64-bit CPython 3.12 `python.exe` and an
absolute venv path outside the repository. To discover a candidate interpreter,
the Python launcher can print its executable path; the setup script then
receives and validates that explicit path:

```powershell
py -0p
$pythonPath = (& py -3.12 -c 'import sys; print(sys.executable)').Trim()
if ($LASTEXITCODE -ne 0 -or -not $pythonPath) { throw 'Could not locate CPython 3.12.' }
$venvPath = Join-Path $env:LOCALAPPDATA 'venvs\chatgpt-web2api-py312'
& .\scripts\setup_windows.ps1 -PythonPath $pythonPath -VenvPath $venvPath
```

The script validates the Windows edition/build, OS architecture, interpreter
implementation/version/bitness and venv base interpreter. It refuses a venv
inside the repository. For a new target, it creates the directory, runs
`python -m venv`, then installs `.[dev]` and `build` with that venv's explicit
`Scripts\python.exe`.

The script does not delete or replace an existing path. An existing environment
is reused only when it has the script's `.w2a-windows-setup.json` marker and its
recorded repository, interpreter and base prefix match. An unmarked directory,
an environment from a different interpreter or a partial environment is left
untouched; select a new path for setup rather than deleting or repurposing it
blindly. The marker supports safe reruns for ordinary use, but is not a security
boundary against another process with the same Windows user's file access.

## Exact-SHA local verification

Run this gate only from a clean checkout of the independently reviewed commit.
Copy the full lowercase SHA from that review and record it separately; do not
derive the expected value from the checkout being verified:

```powershell
$expectedSha = '<FULL_40_CHARACTER_REVIEWED_COMMIT_SHA>'
if ($expectedSha -notmatch '^[0-9a-f]{40}$') { throw 'Supply the reviewed 40-character commit SHA.' }
$env:W2A_E2E_RUN = '0'
$venvPython = Join-Path $venvPath 'Scripts\python.exe'
$runStamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ', [Globalization.CultureInfo]::InvariantCulture)
$evidenceRoot = Join-Path $env:LOCALAPPDATA "chatgpt-web2api\evidence\$expectedSha\$runStamp"
New-Item -ItemType Directory -Path $evidenceRoot -ErrorAction Stop | Out-Null
$gateJson = Join-Path $evidenceRoot 'strict-verifier.json'
& $venvPython .\scripts\verify_orchestrator.py --full --strict --expected-sha $expectedSha --timeout 1200 |
    Tee-Object -FilePath $gateJson
$verifyExitCode = $LASTEXITCODE
if ($verifyExitCode -ne 0) { throw "Strict verification failed with exit code $verifyExitCode." }
```

`--strict` requires the exact expected `HEAD`, a clean tree including untracked
files, and Ruff. `--full` runs compileall and the complete non-E2E pytest suite.
The verifier sets `W2A_E2E_RUN=0` in its child environment and excludes tests
marked `e2e`; set the same value in the calling shell as shown above. Do not use
`--diagnostics` for routine evidence because it includes raw output tails.

The verifier rechecks the SHA and clean tree after the commands finish. This
narrows a time-of-check/time-of-use window but does not close it: a privileged
or same-user process could change and restore files between observations. The
run is local, unattested evidence, not network isolation, trusted CI, a provider
session check or a release approval. Tests and installed dependencies can access
the network.

## Store evidence and build the installed wheel outside the checkout

The command above records the verifier's JSON outside the Git tree without
enabling raw diagnostics. Only after the strict gate succeeds on that same
commit, build a wheel to an external directory and install that exact wheel into a fresh wheel-check venv.
This checks packaging and entry-point imports; it does not run provider flows.

```powershell
$wheelDir = Join-Path $evidenceRoot 'wheel'
New-Item -ItemType Directory -Path $wheelDir -ErrorAction Stop | Out-Null
& $venvPython -m build --sdist --wheel --outdir $wheelDir
if ($LASTEXITCODE -ne 0) { throw 'Wheel build failed.' }

$wheels = @(Get-ChildItem -LiteralPath $wheelDir -Filter 'chatgpt_web2api-*.whl' -File)
if ($wheels.Count -ne 1) { throw "Expected one project wheel, found $($wheels.Count)." }
$wheelPath = $wheels[0].FullName
$wheelEnv = Join-Path $evidenceRoot 'wheel-env'
if (Test-Path -LiteralPath $wheelEnv) { throw 'Use a fresh wheel-env path; existing contents were left untouched.' }
& $pythonPath -m venv $wheelEnv
if ($LASTEXITCODE -ne 0) { throw 'Creating the wheel-check venv failed.' }
$wheelPython = Join-Path $wheelEnv 'Scripts\python.exe'
& $wheelPython -m pip install --disable-pip-version-check --no-input $wheelPath
if ($LASTEXITCODE -ne 0) { throw 'Installing the built wheel failed.' }
```

Run only the installed entry points' help screens, from a directory outside the
repository. These commands exit before starting the proxy or MCP server:

```powershell
$smokeDir = Join-Path $evidenceRoot 'smoke-cwd'
New-Item -ItemType Directory -Path $smokeDir -ErrorAction Stop | Out-Null
$priorPythonPath = $env:PYTHONPATH
$priorE2eRun = $env:W2A_E2E_RUN
$didPushLocation = $false
try {
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    $env:W2A_E2E_RUN = '0'
    Push-Location -LiteralPath $smokeDir
    $didPushLocation = $true
    & (Join-Path $wheelEnv 'Scripts\chatgpt-web2api.exe') --help
    if ($LASTEXITCODE -ne 0) { throw 'chatgpt-web2api --help failed.' }
    & (Join-Path $wheelEnv 'Scripts\chatgpt-web2api-mcp.exe') --help
    if ($LASTEXITCODE -ne 0) { throw 'chatgpt-web2api-mcp --help failed.' }
    & (Join-Path $wheelEnv 'Scripts\chatgpt-orchestrator-observer-mcp.exe') --help
    if ($LASTEXITCODE -ne 0) { throw 'chatgpt-orchestrator-observer-mcp --help failed.' }
} finally {
    if ($didPushLocation) { Pop-Location }
    if ($null -eq $priorPythonPath) {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    } else {
        $env:PYTHONPATH = $priorPythonPath
    }
    if ($null -eq $priorE2eRun) {
        Remove-Item Env:W2A_E2E_RUN -ErrorAction SilentlyContinue
    } else {
        $env:W2A_E2E_RUN = $priorE2eRun
    }
}
```

Do not use a bare `chatgpt-web2api` invocation for this smoke check: that starts
the browser proxy. Cookie injection, `ensure`, live doctor verification and
worker/dispatch commands are also outside the offline setup check.

## Support and security limits

- The supported offline orchestration model is Model 1: cooperating processes
  in a validated private workspace. This setup script does not provision that
  workspace or establish effective access denial for a second Windows user.
- Model 2, hostile same-user filesystem swaps and general Windows TOCTOU
  resistance remain **FAIL / unsupported**. Script path checks and its marker
  are setup safeguards, not a handle-based filesystem security boundary.
- The local verifier's postflight check still has the documented
  change-and-restore TOCTOU limitation. A green local result is not authenticated
  CI, hosted-provider evidence, a live ChatGPT model/app check, or production
  authorization.
- The wheel and help smokes prove only that the built wheel installs and its
  three declared console entry points can render help in a fresh CPython 3.12
  environment. They do not prove browser connectivity, account state, message
  delivery, remote worker behavior or production readiness.
