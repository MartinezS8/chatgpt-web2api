# PR #68 — Read-only single-turn receipt inspector

Parent Draft PR #67 exact `f9534cedba815faeffd49c8b2cfc38b068f8ff10`.

Adds `scripts/inspect_pilot_receipt.py --receipt-dir <ABSOLUTE_PATH>`.
It reads existing `intent.json`, `result.json`, `quarantine.json`
only; it does **not** launch Codex, query accounts, retry a send, inspect
tokens, change a file or authorize completion. JSON parsing is bounded,
rejects duplicate keys, symlinks/reparse paths, malformed fields and
inconsistent result/quarantine combinations.

Interpret the report:
- `TERMINAL_UNREVIEWED`: terminal completed and locally well-formed,
  but no independent model-output or file-change verification.
- `TERMINAL_FAILED_OR_INTERRUPTED`: terminal failed/interrupted.
- `PRE_TURN_FAILURE`: code reported no attempted `turn/start`.
- `UNKNOWN_DELIVERY`: a `turn/start` may have reached the provider.
- `LEGACY_OR_UNCLASSIFIED_QUARANTINE`: earlier format or inconclusive marker.
- `INCOMPLETE_OR_INTERRUPTED`: only durable intent, no final result.
- `INCONSISTENT_RECEIPT`: missing/broken intent, incompatible terminal
  claims, or simultaneous success and quarantine.

Regardless of classification, `automatic_retry_permitted` is always false.
This is a **local diagnostic**: a writable JSON receipt is not proof of
independent delivery or a supported multi-worker recovery process.

The CLI exits 0 only for a structurally consistent terminal completed
receipt, otherwise 2. This is a convenience for the owner's local smoke,
NOT a CI confirmation of real Codex availability or successful task work.

The existing German runbook remains the setup source; the last step after
a manual pilot can be:

```powershell
py -3.12 scripts/inspect_pilot_receipt.py --receipt-dir "$ReceiptDir"
```

No account-backed actions are executed by this PR. Require terminal
exact-HEAD Windows 11/Python 3.12 Strict + Gitleaks + Ruff/compileall +
wheel/sdist + installed CLI/MCP smoke before handing off to Codex.
