# PR-06A — Fail-closed offline attachment and per-message app selection preflight

## Purpose

Add a deterministic validation gate for the exact immutable task package and the *simulated* capabilities of one active mock worker. The API deliberately does not upload to ChatGPT, select a live app or prove that Plus webchat features are available through this software.

`upload_preflight.py` checks:

1. An already reserved task with a verified `TaskPackages.read(..., verify_blobs=True)` manifest, not original mutable user files.
2. Exact matching enabled **mock** worker currently assigned to that task.
3. Exact model name and reasoning effort. Any missing, different or unverified selection blocks the preflight.
4. Required per-message apps are both listed as available and **selected in the current message**. Historical selection or connected-account state does not suffice. Any user approval prompt blocks until real user action in the future authorized adapter.
5. Every attachment gets one adapter receipt with its declared SHA-256, size, media type and unique `fake:` remote ID. Missing/partial/duplicate/mismatched receipts reject the package. Local snapshots, not original paths, are passed to adapter.
6. After every fake upload it transactionally re-checks that the same task remains reserved by the same worker; a changed reservation blocks the record.
7. One immutable per-task SQLite record, with an explicit `offline_mock_only` assurance level. API replies always set `live_send_permitted=False`.

## Implementation boundaries

The adapter can only report simulated results. It has **no** Chrome, ChatGPT, hosted-app, Codex app-server or GitHub/Supabase connection; no API credentials; no bypass of approval dialogs or quotas. Never expose this mock gate as a live upload or delivery acknowledgment. Verification of actual file bytes, provider attachment IDs, model and app permission proofs must be added to an authorized live transport in PR-06B/PR-07. Existing `TaskPackages` format/limits are reused; this PR does not alter original upload limits.

## Validation

`PYTHONPATH=src python -m pytest -q tests/test_orchestrator_upload_preflight.py`: **11 local offline tests passed**, with V4 Store and test-only package/capability/upload fixtures. `compileall` passed. Stacked/upstream suite, real SDK/API, Windows and Ruff remain untested. No production activity.

## Future gates

- Exact provider file upload acknowledgment and post-upload remote file state; partial uploads must not trigger send.
- Verified account/plan/tool capability matrix, app selection scoped per message, user intervention where required.
- Provider-authenticated model + High confirmation, no silent model fallback.
- Centralized send-entrypoint gating, deduplication and safe unknown-delivery reconciliation.

