# PR-04 — Correlated callbacks, immutable evidence, independent review observations

**Scope:** Additive Python 3.11 stdlib components over PR #5. **Offline/mock-only.** The new modules never connect to ChatGPT, Codex app-server, GitHub/Supabase, MCP servers, browsers, uploads, apps/plugins or model APIs. This is NOT an authenticated remote callback transport.

## Implemented

- **`events.py` — CallbackInbox / CallbackEnvelope:** An authorized *local adapter* signs a minimal envelope via HMAC-SHA256 (shared secret ≥32 bytes). The receiver checks that signature, then verifies `attempt_id`, exact `conversation_id` and `delivery_id` against an **already accepted** PR-02C outbox attempt. Event IDs are globally unique and idempotent only for exactly matching payloads. Progress can be lost, duplicated or delayed without advancing task state. A correlated `completed` event moves `in_progress → result_received` atomically with its local receipt; never directly to `verified` or `finished`. An adapter signature proves adapter secret possession, NOT that an outside provider really sent the event.
- **`evidence.py` — EvidenceGate:** Dependency-injected, read-only `TrustedGitHubReader` protocol. The algorithm requires a numeric GitHub repository ID declared in the task's canonical PR-02B write scopes, the exact immutable result reference `github:<repo_id>/pull/<PR>@<40-hex-SHA>`, a matching existing commit, an open PR with that exact HEAD and uniquely identified successful required checks. Historical or duplicate check names fail closed. Only after this can a task become `verified`. `is_current` re-reads remote PR/CI state; any meaningful release gate must perform its own immediately-fresh check again.
- **`review_policy.py` — ReviewPolicy:** Stores an *untrusted* observation from a separate assigned read-only review task and registered reviewer worker. Requires the review task's correlated completion and SHA matching the target's saved verified proof. Self-review, mismatched source, non-read-only roles or duplicate conflicting observations fail. No review observation calls `Store.finalize_verified` or approves a merge. `approved_for_release()` intentionally returns `False` until provider-authenticated review identity, policy and explicit operator/user approval are implemented.
- **`planner.py` — RepairPlanner:** A negative review observation can create a durable, immutable repair **proposal**; default limit is two cycles. Proposals cannot automatically enter the runnable queue, free task scopes, alter branches or make external calls.
- **`review_commands.py`:** Read-only local CLI commands `callback-receipts --attempt`, `evidence-snapshot --task`, `review-observations --task`, `repair-proposals --task`. The output omits raw review feedback, repair prompt contents, callback signatures and claim tokens. `authoritative_live_check=false` and `release_approved=false` are explicit.

## Key safety invariants

1. **Two kinds of completion:** A correlated local callback only means the adapter reported a finished turn; actual code/CI verification is a separate step. A green provider check is not the same thing as an independent reviewer.
2. **No remote exactly-once guarantee:** An unacknowledged send must remain unknown rather than be resent blindly. Callback deduplication prevents double processing locally, not duplicate effects remotely.
3. **Immutable source binding:** Commit SHA and PR head must match the original GitHub repository resource ID and result reference. A successful CI run from another SHA or repository cannot substitute.
4. **Untrusted reviews cannot release locks or merge:** Actual reviewer identities, CI freshness, human permissions and approval provenance are missing; this PR deliberately cannot finalize work.
5. **Repair proposal ≠ actionable task:** Reviewing and planning do not silently execute unapproved tasks, override quarantine or produce an unbounded review/fix cycle.
6. **No web or plus-account feature parity:** Five local logical workers are not five proven simultaneous GPT-6 High ChatGPT website generations. No file uploads, hosted app selection, code execution, model selection or live callbacks are claimed.

## Verification evidence

On the locally available V4 store/controller test fixtures plus a schema-compatible **simulated** PR-02C dispatch/outbox fixture:

```bash
PYTHONPATH=src python -m pytest -q tests/test_orchestrator_pr04.py tests/test_orchestrator_pr04_read_commands.py tests/test_orchestrator.py
# 53 passed, 8 subtests (Python 3.13/Linux local test run)
python -m compileall -q src
```

**Scope of this evidence:** The five new production modules were transferred with byte-for-byte matching Git blob hashes from the local test files. Full PR #5/PR #4 integration, full upstream suite, Ruff, GitHub Actions and Windows test runs are not established. GitHub Actions/Issues are not blockers at the user's request; Codex can run them later. Re-run all PR04 tests with the *real* PR-02C outbox and PR-03 WorkerRegistry, not only the test doubles.

## Required next gates

- **PR-04B / provider verification:** actual authorized GitHub **read-only** provider adapter with authenticated repo/PR/commit/checks, correct latest-run behavior, token-scoped permissions and independent review identity. Never interpret user-submitted strings as verified evidence.
- **PR-05:** Typed low-token Codex CLI/MCP action surface over one canonical SQLite authority, stable event cursors, bounded polls, explicit approval gates, no leaks.
- **PR-06:** Approved transport capability negotiation for attachments/app selection, upload receipts and explicit user consent; unsupported controls fail closed.
- **PR-07:** Supported transport selection, strict model and reasoning-effort gate (no fallback), authoritative callback source, 1-worker opt-in integration first, no blind rate-limit retry.
- **PR-08:** Windows ACL and secret storage, schema migrations/backups, supervisor, full cross-platform CI and soak tests.

**Do not merge to `master` or enable live dispatch based on local fake-provider checks.**
