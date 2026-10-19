# PR-28 — Repair the four verified CI test failures

Date: 2026-10-19. Stacked on Draft PR #29. This PR changes one mock-review error branch and tests; no live transport, finalizer, GitHub merge or provider write.

## Evidence-based review

Actions run [39328543846](https://github.com/MartinezS8/chatgpt-web2api/actions/runs/39328543846) checked out exactly `497e13cb586364cbe10195de0815dcc6fc05ca1e`. On Linux/macOS Python 3.11/3.12, complete offline pytest finished with **1048 passed, 3 failed, 20 subtests passed**. Windows/Python 3.11 had **1047 passed, 4 failed, 20 subtests passed**. Ruff failed with **115 violations** across source/tests; the package-build job was skipped because the matrix failed.

### Failures and fixes

1. **Branch CI contract false negative:** The contract test expected the literal `--full --strict --expected-sha` substring, but a deliberately enabled `--diagnostics` flag sat between `--strict` and `--expected-sha`. Assert the required parts separately without giving up the pin.
2. **Disabled reviewer error mismatch:** `ReviewLedger.record_mock` was already fail-closed for disabled mock workers, but its generic identity message broke the intended assertion. Split out an explicit enabled-worker guard, also test a disabled implementer, and assert no decision is saved.
3. **Rotated upload claim error mismatch:** The durable upload-intent ledger correctly rejected the replay with `upload preflight is not ready for this fenced claim`; the regression expected a different old message. Assert the current fail-closed diagnostic, verify no additional uploader invocation, and preserve the previous receipt.
4. **Windows SQLite lock:** In the legacy migration test, `with sqlite3.connect(...)` committed the transaction but did not close its SQLite handle. Use `contextlib.closing` in addition to transaction scope; prevents Windows temporary-directory cleanup from racing the open file.

## Verification scope

Fixes were derived from **real completed GitHub Actions logs**, but have not been confirmed by completed Actions on this new PR head at authoring time. Never claim green CI or successful packaged artifacts until the exact commit has six successful matrix cells plus the build job.

Ruff's 115 findings were present in the previous branch. They are **not suppressed** here. They still block `local_gate_complete` and the build.

All provider automations and the task finalizer remain disabled. The developer branch workflow is self-editable and diagnostic-only: it cannot become trusted protected CI by passing this test suite.

## Next steps

Inspect exact commit CI and isolate any new failures, then triage Ruff findings on the same codebase and fix them without modifying safety behavior. Independently review owner-protected CI source and runtime dependency provenance before production authority.
