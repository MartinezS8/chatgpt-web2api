# PR-15 — Durable per-file upload intents (mock-only)

Target branch: `codex/orchestrator-v15-upload-intents`; stack parent PR #16. **No live browser, no ChatGPT upload, no hosted plugin selection or outbound provider calls.**

## Independent review

The existing `UploadPreflight.check_mock()` verifies receipts and tries to store a final record after uploading, but does not first reserve the upload attempt. Two concurrent callers may both perform mock uploads before one succeeds in sealing the preflight record. If an upload times out/crashes after a provider accepted the file, blind replay would risk duplicated remote files.

## Added

`src/chatgpt_web2api/orchestrator/upload_intents.py` provides `UploadIntents` backed by the controller's same SQLite WAL authority:

- `reserve(task_id, worker_id, claim_token)`: immutable **one-intent-per-task** binding to a verified sealed package digest, active mock worker assignment and unexpired fenced reservation. Returns an opaque upload ID but **never a live send permit**.
- `reserve_next(...)`: one **pending → inflight** attachment reservation at a time, in `BEGIN IMMEDIATE`, before any upload side effect. Another concurrent call cannot reserve that file or a second file.
- `acknowledge(...)`: fail-closed **mock-only** receipt check with exact attachment digest, size, MIME type and unique fake remote ID. When all parts have confirmed mock receipts, status becomes `ready_mock` (never production-ready).
- `quarantine(...)`: transitions an ambiguous or failed intent to `unknown` without resetting part states, so crash recovery/retry cannot authorize another upload.
- `get()` / `receipts()` provide redacted local inspection without claim tokens or original file contents.

## Test evidence

Python 3.13 (Linux), using existing V4 `Store` source whose Git blob SHA matches current parent `store.py` (`f4a23c6bed54e3ed7d26ed3bae5b0cd77734f914`):

`PYTHONPATH=src python -m pytest -q tests/test_orchestrator_upload_intents.py`: **10 passed**.

Tests include 16 concurrent reserve requests and 16 concurrent per-file reservations, duplicate/mismatched receipts, stale/disabled worker, no-attachment and crash/restart quarantine, and identical-content checks. `compileall` also passed. Full current-stack tests and Windows CI have not been run.

## Explicitly NOT done and next gate

**This PR introduces the durable ledger but does not wire it into the existing `UploadPreflight.check_mock()`**. That existing function still has a potential simultaneous-upload side effect. Keep the upload preflight mock-only and do not connect a real upload client.

The immediate **PR-16** gate is to wire all calls to `uploader.upload(...)` through `UploadIntents.reserve_next()` before invoking the mock uploader; require receipt ACK before moving on; quarantine on any ambiguous return/exception; preserve previous preflight idempotency and the existing 2-file tests; add a concurrent end-to-end preflight test. The existing test fixture currently creates a fake reserved task without an actual claim token; update it to use a fenced `Store.claim` before this integration.

Before any **real** ChatGPT upload, add an authorized transport-specific remote file-ID and completion proof, quota/permission checks, account capability discovery, explicit approval if required, identity binding, secure Windows blob storage, and unknown-delivery reconciliation. No fake receipt or preflight proves a Plus account feature exists.

## Remaining wider roadmap

- Provider-authenticated current GitHub PR + CI check evidence and independent review bound to exact SHA; replace the permanently blocked legacy finalizer with a trusted service.
- Single supported authorized dispatch path; model GPT-6 High strictly verified when available; no direct legacy controller use.
- Authenticated callbacks and replay for authorized Codex app-server threads; no assumption that hosted ChatGPT apps can be used by Codex's separate transport.
- Full Python 3.11/3.12, Windows, Ruff, upstream suite and security review before merges.

GitHub Actions and Issues are optional for current implementation work, per repository owner; Markdown tracker remains authoritative. `master` is unchanged.
