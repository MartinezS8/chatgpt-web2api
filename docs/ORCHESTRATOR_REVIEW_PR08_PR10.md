# Independent integration review — PR #5 through #8 (2026-10-19)

## Decision

Preserve the canonical **stacked** architecture PR #1 → #2 → #3 → #4 → #5 → #6 → #7 → #8. All remain Draft. A parallel PR #9 duplicated PR #6 and was closed **without merge**. Do not enable real browser dispatch or remote writes based on offline fixtures.

### Confirmed findings and PR-10 patches

1. **P0: stale scheduler ancestry.** PR #5 was corrected to conditionally reuse only a released `orchestrator_worker_assignments.task_id` after `Store.recover`, but PR #6–#8 were forked before that fix. On the latest PR-10 tip, synchronise `scheduler.py` and its regression test with reviewed PR #5. The canonical stack's intermediary PR heads still need Codex to reconcile ancestry in order; this PR does not falsely claim they already contain the fix.
2. **Duplicate mock uploads on idempotent retries.** `UploadPreflight.check_mock` previously invoked the mock upload adapter on every call, then compared the sealed preflight database record. Move the existing-record comparison **before** invoking the upload adapter. Exact repeated invocation returns `created=false` without further uploads; changed capability snapshot is rejected. Regression tests assert no second adapter call.
3. **Observer SQLite connections not deterministically closed.** A Python `with sqlite3.connect(...)` performs transaction context management but does not necessarily close the connection. Repeated Codex observer polls could accumulate descriptors/locks. Use `contextlib.closing`; regression test tracks `close()` calls.

## Out-of-scope and remaining high-priority risks

- **Concurrent / crash-unknown mock uploads:** The new early-read deduplicates ordinary sequential retries but does **not** reserve a durable per-upload single-owner intent across concurrent requests or process crashes. PR-06B must acquire an atomic per-task upload attempt and reconcile by provider receipt before any live adapter performs effects. Never automatically re-upload on an uncertain remote acknowledgment.
- **Provider permission and hosted-app selection:** All mock capability claims are local; no proof of Plus-plan app availability, consent, model or reasoning tier.
- **Actual callback and approval:** PR #6's `CallbackInbox` remains mock-only; `EvidenceLedger` and `ReviewLedger` are explicitly `offline_mock_only`. `Store.finalize_verified` still accepts string-only review attestations, so it must be blocked before live use and replaced by fresh provider-referenced SHA-bound review/CI/approval gate.
- **Unreviewed inherited branches:** PR #6–#8 are **behind** reviewed PR #5 and require an ancestry reconciliation. Do not use a merge commit that adopts a parent SHA without actually carrying forward the corresponding file changes.
- **Transport restrictions:** No live model, ChatGPT uploads, plugin UI selection, file permissions, account quotas, or website-automation authorization have been verified.
- **Testing evidence:** This PR adds targeted regressions but does not claim to have run full current GitHub/Windows CI or upstream E2E. Execute the exact pinned branch at Codex integration; retain read-only/dry-run defaults.

## Codex next steps

1. Fetch exact current heads of PR #5–#10 and reconcile sequential ancestry; resolve any file-level conflicts, **preserving** latest reviewed fixes.
2. Run `python scripts/verify_orchestrator.py --full` and `python -m pytest -q tests/test_orchestrator*.py` on the resolved tip. Investigate failures rather than suppressing them.
3. Complete provider-backed evidentiary approval policy, durable upload attempt/idempotency and authenticated callback adapters before any real external dispatch.
4. Keep PRs Draft until independently checked; no automatic merge.
