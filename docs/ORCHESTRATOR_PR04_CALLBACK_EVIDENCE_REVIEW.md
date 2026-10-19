# PR-04 — Offline callback correlation, provider evidence, independent review and bounded planning

**Repository:** `MartinezS8/chatgpt-web2api`  
**Parent:** `codex/orchestrator-v6-worker-scheduler` / Draft PR #5 (stacked)  
**Date:** 2026-10-19  
**Scope:** Reviewable, **offline-only** control-plane building blocks. **No live transport**, hosted connector, account model selection, file upload, GitHub/Supabase write, external reviewer signature, or unattended merge.

## Compatibility and trust boundaries

The additional modules depend only on the existing `Store` SQLite authority and its V5 `orchestrator_dispatch_attempts` + `orchestrator_delivery_events` schemas, and on PR-03 `orchestrator_workers` / `orchestrator_worker_assignments`. They do **not** start browser sessions or import the Octo-Lex CDP driver.

1. **CallbackBridge (`delivery.py`)**: `mode="mock"` only. A progress callback must identify the exact **accepted** outbox attempt, conversation and user message; sequence numbers are monotonic and event IDs deduplicate. Progress is advisory: it must never complete a task. `complete()` delegates to the existing `DispatchOutbox.complete()` and requires its exact acknowledged remote pair. Replays are idempotent, inconsistent duplicates fail. A live callback receiver, authentication, trusted event source and provider-replay protection still have to be built.
2. **EventReader (`events.py`)**: short, redacted read-only view of the existing append-only outbox stream, with durable per-consumer cursor acknowledgement. Does not claim push-subscription or callback delivery to Codex.
3. **EvidenceLedger (`evidence.py`)**: rejects absent providers by default. The caller injects an independently authenticated `ProviderEvidenceVerifier` adapter, which must fetch GitHub PR HEAD and CI metadata directly from provider authority; tests use explicitly fake providers. Accepts only matching numeric repository ID, PR number, full lower-case SHA, CI run ID, successful CI conclusion, matching CI SHA and fresh snapshot (within 120s). Requires a **completed, correlated V5 outbox attempt**. Promotes `result_received → verified` atomically with a pinned evidence digest; keeps task/write locks. Reverification with different evidence cannot silently rewrite old proof. `assert_fresh()` refetches PR HEAD/CI but does not authorize merging; a race against external branch movement remains until a remote protected/conditional merge is implemented.
4. **ReviewLedger (`review_policy.py`)**: denies any review without a review attestation verifier. Records verdict only for a separately scheduled **read-only**, `review_of`-linked, `verified` review task. Reviewer must be a distinct, enabled, role=`review` worker with a different session and same provider account/project as the implementation worker. Decision pins the exact evidence SHA; stale/mismatched review is denied. Results are immutable and idempotent, marked `authorizes_merge=false`. **No call to `Store.finalize_verified()` or GitHub merge is made.** Attestation authenticity and independent provider review origin remain for a future authorized integration.
5. **BoundedPlanner (`planner.py`)**: creates a read-only review task without a `FINISHED` dependency on its parent (avoids deadlock while original scope is held). May record at most two fix proposals (configurable maximum 1–3) after `changes_requested`; inherits parent scopes and PR HEAD as baseline. **Fix proposals stay blocked** by the unresolved parent lock; operator reconciliation is needed before any execution. No autonomous fix loop or model invocation.

### Important distinction

`ProviderSnapshot` and `ReviewProofVerifier` are *trusted interfaces*, **not** network-backed implementations. Replacing either with code that blindly echoes input would defeat their purpose. The production provider adapter and human/merge policy must be independently reviewed. Existing low-level `Store.finalize_verified()` is still accessible and accepts local operator attestation strings: a live runtime MUST restrict every completion/merge pathway to the stricter policy gate; PR-04 does not yet close that legacy bypass.

## Compatibility with current SQLite authority

New tables (create-only, no existing schema migration):
- `orchestrator_callback_progress`: last observed callback sequence per attempt.
- `orchestrator_verified_evidence`: one immutable verification record per implementation task, bound to its completed V5 outbox attempt and CI/head tuple.
- `orchestrator_review_decisions`: one immutable decision per review task, bound to reviewer worker and evidence SHA.
- `orchestrator_fix_plans`: bounded idempotent proposals per root implementation task and review decision.

The existing `orchestrator_delivery_events` and `orchestrator_event_cursors` remain the **single event authority**. Internal callbacks contain no prompt text, tokens or file bytes. Parent V5 tables are not changed.

## Test evidence and limitations

Local offline test setup reconstructed from V4 store and structurally equivalent V5/PR-03 SQLite table contracts; includes **mock** outbox and provider adapters. Commands:

```bash
PYTHONPATH=src python -m pytest -q \
  tests/test_orchestrator.py tests/test_orchestrator_cli.py \
  tests/test_orchestrator_multiprocess.py tests/test_orchestrator_pr04.py
python -m compileall -q src tests
```

Result: **59 tests + 8 subtests pass** (Python 3.13). Negative scenarios include missing provider, changed PR HEAD, non-success CI, stale CI snapshot, mismatched or replayed callback, progress-only callbacks, changed result reference, disabled/self/cross-account reviewer, missing independent attestation, unverified task, stale review, locked fix and idempotent retry. **Ruff is not installed in this local runtime**; full V5 + PR-03 + upstream suite and Windows CI have not run here. No external GitHub/Supabase/ChatGPT E2E execution has happened.

## Gates before live integration

- **PR-04B (P0):** Implement provider-authenticated evidence adapter using only user-permitted GitHub connector capabilities; validate repository ID + PR head + commit existence + CI run conclusion and provenance. Prevent cached evidence from being substituted for fresh provider response; implement conditional remote merge policy. Review worker must be bound to an independently verifiable output/identity. Do not assume CI is available if its run is absent.
- **PR-04C:** Extend the durable outbox/worker registry with trusted `attempt_id ↔ worker_id ↔ target_id ↔ session_id ↔ delivery_id` bindings and authenticated transport event receipt. Ensure stale/cross-session callbacks are rejected **at ingress**, not merely at completion.
- **PR-05:** Expose typed, capability-gated Codex CLI/MCP tools; remove/deny legacy direct `claim`, `Controller.dispatch` and `Store.finalize_verified` bypasses for production transport. Clear operator reconciliation for a failed review and preserved lock.
- **PR-06:** Actual uploaded attachment receipt verification, per-message app authorization (Plus hosted plugin parity **not guaranteed**).
- **PR-07:** Authorized model/transport with strict fail-closed GPT-6 High validation, no blind send retries.
- **PR-08:** Windows ACL-protected SQLite/artifacts, backups, migrations, full independent tests.

This branch and PR must remain **Draft** and not be merged until above production gates or reviewed separation of offline-only behavior is confirmed.