# PR-16 — Wire Mock UploadPreflight to Durable UploadIntents

Parent: [PR #17](https://github.com/MartinezS8/chatgpt-web2api/pull/17). Mock/offline-only; no remote provider actions.

## Code review finding

`UploadPreflight.check_mock` previously invoked the upload adapter before recording a durable exclusive intent. Two concurrent invocations could each upload all files, only then race to seal final receipts. A network timeout after provider acceptance would permit a blind follow-up upload.

## Changes

- `upload_intents.py`: `perform_mock` performs exactly one task-level intent and one atomically reserved `pending → inflight → acked` upload at a time. Lost/mismatched receipts quarantine the entire upload as unknown. An already existing upload attempt never grants a new send permit.
- `assert_ready_locked` checks current active, unexpired claim, enabled mock worker, exact package SHA and successful per-file receipt state in the caller's own SQLite transaction.
- `upload_preflight.py`: replace direct uploader loop with `self.intents.perform_mock`. Both replay of previous preflight and final preflight seal use the current fenced identity/receipt check. No partial upload can become `mock_ready` after crash or assignment rotation.
- `test_orchestrator_upload_preflight.py`: use real `Store.claim` instead of manufacturing `reserved` without a token; add parallel (16 calls), uncertain timeout, stale-claim replay tests.

## Evidence

- Exact GitHub blob-equivalent local `upload_intents.py` stage: **13 standalone tests passed** on Python 3.13/Linux; `compileall` passed.
- Full combined `UploadPreflight` tests (including 3 new cases), Ruff, Windows, upstream non-E2E suite and GitHub Actions: **NOT executed** in this response. Keep Draft until Codex runs the assembled branch.
- `master` remains unchanged; no ChatGPT account/browser action, real upload, or app/plugin use is made.

## Fail-closed limitations and next steps

- `MockAttachmentAdapter.upload` returns fabricated `fake:` receipt IDs. They are not provider-certified ChatGPT file IDs or proof of attachment status.
- This PR intentionally cannot execute authorized real file uploads or message sends. A genuine transport needs its own authenticated remote receipt / response ID, quota/type enforcement, consent, and recovery by provider ID.
- The durable intent is per task, not a guarantee of external exactly-once execution; if a remote ACK is unknown, the task stays blocked until supported manual/provider reconciliation.
- Additional required gates: authenticated GitHub/CI evidence bound to current SHA, trusted finalizer; single supported dispatcher; explicit model/effort + per-message app selection checks; callback signature/session identity; Windows ACL and backups.

Codex checkout commands:

```bash
python -m pytest -q tests/test_orchestrator_upload_intents.py tests/test_orchestrator_upload_preflight.py
python scripts/verify_orchestrator.py --full
```

See [implementation tracker](ORCHESTRATOR_V5_IMPLEMENTATION_TRACKER.md). GitHub Issues/Actions setup can be handled separately as requested; tests remain a prerequisite to merging.
