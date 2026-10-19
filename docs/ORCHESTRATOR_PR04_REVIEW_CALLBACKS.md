# PR-04 — Offline callbacks, SHA-scoped evidence, independent mock review and bounded replanning

**Target:** `MartinezS8/chatgpt-web2api` fork, stacked on PR #5 `codex/orchestrator-v6-worker-scheduler`.

## Purpose / verified scope

This patch adds transport-agnostic **offline-only** infrastructure. It does **not** add an authenticated callback HTTP server, connect to ChatGPT web tabs, verify live GitHub permissions/CI, upload files, select hosted apps, send requests, or enable production approvals. Neither `Store.finalize_verified` nor its low-level token has been upgraded into provider-verified authorization. No automatic remote resend and no live provider writes.

- `callback_inbox.py`: SQLite-persisted **advisory** `progress` / `heartbeat` signals. The callback is scoped by attempt ID, bound *active worker*, acknowledged conversation ID, acknowledged delivery message ID, and sequence. Conflicting replays/out-of-order signals fail closed. Terminal `complete_mock()` calls the existing DispatchOutbox completion correlation; progress never completes a task. Callback source is only `mock` worker and does not authenticate an external endpoint.
- `evidence.py`: small `GitHubEvidenceProbe` interface and `EvidenceLedger.inspect_mock()`. A fake probe must produce matching numeric repository ID, PR ID, **exact** SHA of the current PR head, and a successful CI run bound to that SHA. Any mismatch is rejected, SHA/run evidence is immutable per task. Assurance is explicitly `offline_mock_only` and `is_production_proof()` always returns `False`.
- `review_policy.py`: `ReviewLedger.record_mock()` requires read-only reviewer task targeted at the implementation task, both tasks in the VERIFIED state, sealed evidence on the *same SHA*, separate active worker IDs and enabled `mock` review worker. A decision cannot be overwritten. `production_approval_granted()` always returns `False`; no user-facing approval or merge granted.
- `planner.py`: `Planner.propose_mock_fix()` stores a unique, bounded, idempotent fix *proposal* based on a sealed `changes_requested` reviewer decision; it does not create an executable task, release scopes or dispatch anything. Followup tasks and escalation gates are intentionally deferred.

## Test evidence

Locally: `PYTHONPATH=src python -m pytest -q tests/test_orchestrator_pr04.py` -> **13 passed** with the **V4 Store implementation and test-only mock schemas/probe** on Python 3.11-compatible code. `python -m compileall -q src` passes.

The full stacked PR #1–#6 tree, Python 3.11/3.12, Ruff, GitHub CI, Windows and all original upstream tests have **not** been executed here. Codex can do that later, as requested. Do not advertise this as production tested.

## Key next gates

1. **PR-04B hardening:** Enforce all completion/approval paths centrally. The legacy `Store.finalize_verified(reviewer_ref, approved_by)` accepts string assertions; it **must not** be exposed for unattended approval. Re-review retention and provider-signed/retrieved evidence have to be validated before any real releases.
2. **Authenticated callback adapter:** Transport-authenticated identities and monotonic attempt events. Distinguish MCP progress (advisory) from supported provider terminal events. Verify provider-authoritative message and turn IDs. Never turn unknown delivery into a blind retry.
3. **Live evidence adapter:** Read-only GitHub API with explicit installation permissions, immutable exact PR head SHA, CI run check, review provenance and atomic recheck just before release. Supabase changes require separate plan/authorization.
4. **PR-05:** CLI/MCP read-only observation, durable event subscriptions, mock workflow integration and bounded polling. Make live send paths inaccessible until capability check.
5. **PR-06/07:** Authenticated file upload acknowledgements, per-message app capability and user approvals, official transport proof and GPT-6 High fail-closed gate. Nothing in this PR proves feature parity with ChatGPT Plus web UI.

## Safety note

Simulated evidence can be helpful for reproducible correctness tests, but it is not external proof. The user does **not** authorize bypassing UI terms, account quotas or permission prompts by virtue of asking for this implementation.

