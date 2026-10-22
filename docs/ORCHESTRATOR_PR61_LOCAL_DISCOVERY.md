# PR #61 — Explicit opt-in Codex app-server discovery (no thread or turn)

Parent Draft PR #60 HEAD `5550491a26326a6c7eac865ee0e76ad03a699a37`.

Adds `scripts/discover_local_codex.py` for hobbyist-friendly **local** read-only
account and model discovery. It runs only after the operator supplies the
explicit `--allow-account-discovery` flag. It checks the trusted native
`codex.exe` binary hash and exact version against PR #56's offline schema
capture, then starts that same binary's `app-server` over stdio.

Written protocol methods are hard-coded to `initialize`, `initialized`,
`account/read` with `refreshToken:false`, and paginated `model/list`.
No user-supplied method, `thread/start`, `turn/start`, login/logout,
API-key handling, plugin call or automatic approval. No application session
is created. Stdout is bounded JSONL with duplicate-key detection, response-ID
correlation, timeout and a finite page count. Stderr and full account payloads
are NOT logged. Printed report includes only account type/presence, whether
OpenAI auth is required, selected model names and supported reasoning efforts.
The local command starts the real Codex app-server, which may inspect local
settings and contact account services; this is NOT offline or an inferencing
authorization.

### Laptop sequence (after user consciously allows account discovery)

First follow the PR #56 offline version/schema capture using the exact
installed Codex native `.exe`; audit captured schemas with PR #60.
If not signed in already, the user performs **their own** official Codex login
via the CLI/browser. Never pass tokens, cookies, auth.json or device codes
into ChatGPT or GitHub.

```powershell
py -3.12 scripts/discover_local_codex.py --codex-exe "C:\ABSOLUTE\trusted\codex.exe" --schema-root "$env:LOCALAPPDATA\w2a-validation-phase58\schema-fixed-20261022" --cwd "C:\ABSOLUTE\empty-test-dir" --allow-account-discovery
```

Only these two process commands are ever invoked:
`codex.exe --version` (pin) and `codex.exe app-server` (discovery).
The CLI emits a JSON report without raw account payloads or email.
The operator verifies model names and efforts from this output, not from
examples or guessed defaults. Any malformed response or changed version
fails closed. Model discovery without login might report an empty list or an
account-level error; do not silently start login or a turn.

**Still NOT a worker:** no task ledger integration, live turn permit,
controller-worker IPC, Windows second-user attestations, file sandbox,
independent delivery proof or real inference. Additional user sign-off is
needed for one selected prompt and the OS boundary. Do not claim real-worker
acceptance from this diagnostic.

### Test acceptance
Windows Python 3.12 Strict, Ruff, compileall, Gitleaks full history,
wheel/sdist/installed smokes must pass on exact HEAD. Unit tests use fake
Popen and artificial account/model JSON; no local user account or provider.
