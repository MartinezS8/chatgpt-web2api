# PR-13 — Disable assertion-only task finalization (P0)

Date: 2026-10-19. Stacked on [PR #14](https://github.com/MartinezS8/chatgpt-web2api/pull/14), which itself builds on [PR #12](https://github.com/MartinezS8/chatgpt-web2api/pull/12). **Offline-only; no account/web actions.**

## Independent review findings

1. **Critical legacy approval bypass (fixed here).** `Store.finalize_verified(task_id, claim_token, reviewer_ref, approved_by)` previously accepted any nonempty `reviewer_ref` and `approved_by`, then committed `state=finished`, cleared the claim and slot, and released globally-held write scopes. The mock `ReviewLedger.production_approval_granted()` is always false, but the old method did not consult it. A caller with the task claim token could therefore bypass the independent-review policy using arbitrary strings.
2. **Stale ancestry (reconciled only for this new branch).** The canonical PR #5 worker-scheduler branch had two commits absent from the Git ancestry of #6–#14. This PR includes PR #5's current HEAD as a second parent in a no-content-change merge, after checking that the scheduler and its tests are byte-identical on both sides. Thus **this descendant** contains the correct ancestry, but the existing intermediary PRs still need individual ancestry review before integration.
3. **Legacy transport bypass (not fixed here).** `Controller.dispatch` still accepts an injected `Transport.send` and can call it without passing through TaskPackages, WorkerRegistry, DispatchOutbox, model verification and upload preflight. **Never attach a real transport to that legacy controller.** Design a single allowed dispatcher and deny all other live-send entry points before any authorized transport is enabled.
4. **Incomplete production proof (not fixed here).** `EvidenceLedger`, `CallbackInbox` and `ReviewLedger` currently have mock-only implementations. The current GitHub/CI data is simulated, not authenticated proof. User-facing review or callback success is NOT authorization to merge, pay, place orders or change a database.
5. **Mock upload is not a remote upload.** The attachment receipts and per-message app selection preflight do not upload files to ChatGPT or confirm connector entitlements.

## Patch

- `src/chatgpt_web2api/orchestrator/store.py`: `finalize_verified` retains the old call signature but **always raises `PermissionError`**. It neither changes state nor frees a write lock.
- `tests/test_orchestrator.py`: update legacy completion expectations. Check that arbitrary, empty, or high-privilege-sounding reviewer/approver strings all fail, and that an unresolved `verified` implementation keeps its lock and blocks overlapping tasks.
- No provider calls, account logins, new write tools, website automation or code merges.

### Focused local test evidence

A stage with the **exact GitHub blob contents** of the source and regression test files was executed on Python 3.13/Linux:

```bash
PYTHONPATH=src pytest -q tests/test_orchestrator.py tests/test_orchestrator_cli.py tests/test_orchestrator_multiprocess.py
```

Result: **33 passed, 8 subtests passed**. This verifies the V4 regression contract and the new fail-closed legacy finalizer. It is **not** the full assembled #1–#14 suite, nor Ruff, Windows CI, or a live integration test.

## Required replacement for a real authorization gate

A future **single trusted finalizer service** must:

1. Receive only the durable task/attempt ID; retrieve the matching sealed package and claim through the central SQLite authority, never accept arbitrary "approved" strings as sufficient.
2. Resolve the provider-authenticated GitHub repository ID and current open PR number from the task's canonical locked resource scope and a trusted service credential.
3. Fetch the **current** PR head SHA and required CI check run(s) from the provider; require `status=completed`, `conclusion=success`, exact repository ID and exact current head SHA, with bounded freshness (ideally repeat immediately before the transaction).
4. Require immutable, independently sourced review evidence from a different authorized actor/session and exact SHA; invalidate on *any* head movement. A local mock reviewer decision is never production-proof.
5. Require real user approval for consequential merges, database writes or other permissioned external actions. Never simulate consent.
6. In **one atomic compare-and-swap transaction**, validate task state, existing lock and reviewed evidence digest, set `finished` and release the worker slot/resource locks only for the authorized task. Deny mismatched/stale/nonexistent evidence, missing consent, or retries with changed SHA. The state transition itself must be idempotent.
7. Log a redacted, immutable audit receipt and create next DAG tasks **only** after successful finalization.
8. Keep authorization separated from actual GitHub/Supabase mutation. The finalizer may mark an offline task done; an external merge still requires its own independent approval and backend permission check.

**Critical behavior:** Without the trusted finalizer, tasks in `verified` remain in quarantine and DAG children that depend on `finished` do not advance. This is intentional fail-closed behavior. The mock environment can use isolated fixtures; no production fallback is permitted.

## Next staged work (Codex / GitHub Markdown, no Issues required)

### P0 — before live transport
- [x] Disable the assertion-only finalizer (this PR).
- [x] Reconcile PR #5 ancestry on this new descendant (no tree modifications).
- [ ] Implement a single **provider-attested finalization** authority, with fresh GitHub/CI review evidence and explicit human approval as needed.
- [ ] Gate/deprecate `Controller.dispatch`, `Store.claim` live send usage and Octo-Lex automatic rate-limit resends; all remote effects must use the fenced TaskPackages/Outbox/Worker path.
- [ ] Complete Python 3.11/3.12 + Windows and upstream test suite; validate actual stacked PR merge bases and schemas.
- [ ] Test crash before send, after send before ACK, after upload ACK, and before finish CAS. No blind retry of uncertain messages.

### P1 — controlled integration
- [ ] Provider-specific read-only Github PR/CI evidence adapter, verified permissions.
- [ ] Authorized Codex app-server or equivalent supported transport with provider turn IDs, strict model+High verification and bounded concurrency.
- [ ] Attachment upload intent/receipts with remote file ID and hash, partial failure and unknown receipt reconciliation.
- [ ] Per-message plugin/app availability and consent verification, no asserted full ChatGPT Plus parity.
- [ ] Real callback intake authenticated by account/session/worker/attempt, using durable event cursor and redacted logs.
- [ ] Safe operator CLI/MCP for approve/reject/inspect, no untrusted model direct privileged mutation.

### P2 — reliability
- [ ] Windows ACL protection of token, SQLite DB and content-addressed files; migration/backup/restore tests.
- [ ] Replay/dead-letter observability, controlled supervisor stop/resume, zero duplicate-send fault injection.
- [ ] Independent integrated review and release checklist.

**Repo authority:** [V5 tracker](ORCHESTRATOR_V5_IMPLEMENTATION_TRACKER.md). All PRs remain Draft; `master` unchanged.
