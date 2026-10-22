# PR #70 — Shared prompt path validation and KeyboardInterrupt receipts

Parent Draft #69 SHA `c1ba9f4afe996fd874828040c21621cd9a201a63`. Resolves findings F03/F06.

- The real pilot and no-provider preflight now use the **same**
  `read_pilot_prompt()` function, requiring an absolute, regular, non-reparse,
  small UTF-8 file, with a common size and length limit. The real pilot also
  validates its scratch CWD and rejects reparse paths before account discovery.
- Graceful `KeyboardInterrupt` and `SystemExit` now write the existing
  `quarantine.json` under `except BaseException`, accurately recording
  whether a turn/start *may* have been sent and never permitting a retry.
  The original exception is re-raised.
- A hard OS kill/power loss cannot invoke Python; the existing fsynced
  `intent.json` and read-only receipt doctor deliberately classify this as
  `INCOMPLETE_OR_INTERRUPTED`, **not** known non-delivery. No automatic
  resubmission occurs. Python `terminate()` does not guarantee all spawned
  descendant processes stopped; future Windows pilot integration should
  exercise Job Objects/process-tree shutdown on the owner's laptop.
- New tests cover a synthetic Ctrl+C before/after the send and the shared
  prompt-file guard.

No actual provider/network, account action, OS user, permission or merge is
involved. Require Windows/Python 3.12 terminal strict, Ruff, Gitleaks, wheel
and installed mock/MCP tests before calling CI PASS.
