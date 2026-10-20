# PR-32 — Assignment-bound offline outbox intent

Date: 2026-10-20. This PR stacks on Windows-readiness Draft PR #33. No source change is made to the PR #33 branch or `master`.

## Problem

The original `DispatchOutbox.begin(task_id, claim_token)` binds the outbox intent to a valid, unexpired task claim but does not prove the current worker assignment. This is sufficient only for internal **mock** tests, not a remotely authorized send path. When a worker is disabled after claiming a task, no new external send should be derivable solely from the old task token.

Existing `UploadIntents._require_binding` does already verify the exact enabled mock worker. The dispatch outbox must not be weaker when integrating the pieces.

## Implementation

- Preserve `begin(task_id, claim_token)` for legacy **offline** tests, without enabling any remote transport.
- Add `begin_mock_for_assignment(task_id, worker_id, claim_token)` which passes a worker binding through `begin(..., worker_id=...)`.
- In the **same** `BEGIN IMMEDIATE` SQLite transaction, check a nonempty worker ID against a live assignment joined to an enabled `mock` worker in the task's project and role.
- For **new** intents only, also require assignment claim-version equality with the reserved task's current claim version, in addition to the pre-existing token, task state, lease and sealed-package checks.
- On idempotent re-reads, only the same still-enabled bound worker with the matching claim may observe the existing attempt; `new_send_permit` remains false.
- The return explicitly has `assurance="offline_mock_only"` and `remote_send_permitted=False`. The `new_send_permit` key is **only a local mock outbox-intent admission**, NEVER permission to call a remote provider.

## Negative and concurrency verification

New tests use a real temporary SQLite database and sealed task package; they cover a successful bound intent, no second permit on replay, wrong or empty worker, disabled worker and preserved assignment, released assignment, role change, stale claim version, expired lease, two concurrent calls and wrong claim visibility.

## Remaining mandatory gates

1. **Exact-SHA GitHub matrix:** Linux/macOS/Windows Python 3.11/3.12 non-E2E test suite, Ruff, clean postflight, conditional wheel build. All 31 real-account E2E tests remain excluded.
2. The existing *unbound* legacy `begin()` is still callable by internal code. No real adapter may be wired to it; the actual production dispatcher is unimplemented. A real send requires an additional narrowly scoped, provider-authenticated send-time CAS and explicit operator authorization.
3. Real ChatGPT/Codex sessions, uploads and app selections are not implemented by this change. User approval, protected CI, authenticated reviewer identity, transactional finalization and account entitlement proof remain separate blockers.
4. Additional Windows ACL, versioned migration, foreign-key integrity, SQLite WAL backup/restore and interrupted-write tests are still pending.

The branch-controlled GitHub Actions workflow is **developer diagnostics**, not trusted authorization for any external effect.
