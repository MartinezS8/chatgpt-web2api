# PR-56 — Offline Codex App Server readiness diagnostic

Parent: Draft PR #55 exact HEAD 01e1b77997c270ea61a80c181efb5fd402f81cb7.

Official Codex App Server docs say each generated schema is specific to
the installed CLI version. The CLI supports:
- codex --version
- codex app-server generate-json-schema --out DIR
- initialized app-server model/list for account-supported models and thinking
  efforts (NOT EXECUTED by this diagnostic; may depend on provider/account).

The new script runs ONLY the first two commands. It requires native Windows,
CPython 3.12 and a deliberate ABSOLUTE path to a trusted native Codex .exe
(no PATH lookup, codex.cmd script shim, shell or silent model fallback).
It refuses existing output, rejects reparse-path ancestors, checks the version,
parses generated JSON schema documents, hashes the binary and schemas and writes
a local, untracked offline-readiness.json receipt in the NEW output directory.

Manual usage on the owner's Windows laptop, after checking the exact trusted
Codex native exe path:

    py -3.12 scripts/inspect_codex_app_server.py --codex-exe "C:\path\to\trusted\codex.exe" --output-dir "C:\path\to\NEW\codex-schema-2026-10-22"

Optionally specify --expected-version "codex-cli VERSION" for an exact pin.
The output MUST remain outside the repo and must not include session credentials.

The installed version, schema and account model list on the owner's laptop are
still NOT TESTED until this exact command is run locally and its receipt reviewed.
No model/list, authentication call, provider request, thread/start, turn/start or
actual inference is attempted. A model list and thinking-effort list MUST be
retrieved from the installed app-server only after the user specifically
approves an account-facing discovery action. Never silently substitute Sol,
Luna, Medium or Max; require exact supported model/effort results.

No real worker is authorized; the first real Codex inference additionally
requires a fresh, specific user sign-off and verified Windows worker isolation.
Windows GitHub CI cannot attest the owner's laptop.
