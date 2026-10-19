# PR-11 — Canonical evidence locking and callback redaction

**Canonical base:** `codex/orchestrator-v10-preflight-observer-review-fixes` (draft PR #10). This change builds on the active stacked work PR #1 → #2 → #3 → #4 → #5 → #6 → #7 → #8 → #10; it is **not** a replacement for the PR-04 modules in PR #6.

## Why this patch

An independent PR-04 exploration (PR #11) exposed two gaps in the existing canonical chain:

1. **Cross-repository evidence substitution.** `EvidenceLedger.inspect_mock` compared the caller's repository ID to the mock GitHub response, but did not also compare it to the task's locked, canonical PR-02B GitHub repository resource. An unrelated repository could be accepted as simulated proof. The patch checks that the task declares `github:repo/<numeric_id>` or a descendant path for the requested repository ID.
2. **Incomplete CI run accepted by conclusion alone.** Checking `conclusion == success` without `status == completed` is not a sufficient representation of a finished workflow run. A mock run now must explicitly report both conditions.
3. **Untrusted progress message persistence.** `CallbackInbox.progress` accepted a bounded freeform message, and persisted it to SQLite. It could include sensitive prompts or content; now only `[redacted]` is stored, while the replay integrity SHA-256 remains tied to the actual supplied content.

## Changes

- `src/chatgpt_web2api/orchestrator/evidence.py` — bind evidence to declared canonical write scope and require completed CI status.
- `src/chatgpt_web2api/orchestrator/callback_inbox.py` — do not persist raw progress message.
- `tests/test_orchestrator_pr04.py` — update fixture to declare a canonical resource and a completed fake run; add negative tests for wrong repository scope, `in_progress` CI, and progress-message redaction.

## Safety and limitations

- These tests remain **mock-only**, as does the existing `EvidenceLedger`; no authenticated GitHub provider client is implemented by this patch.
- No web calls, ChatGPT account controls, uploads, app selection, model selection, remote permissions or write actions are added.
- Existing PR #6–#10 are still Draft; do not merge without full Linux/Windows CI and independent review.
- This patch is **not yet verified with the full repository test suite** in this chat; GitHub Actions and Ruff can be run later through Codex as requested. In particular, this feature introduces a new required field `status` in the mock CI probe result; all compatible mocks must return it.
- A separate PR #11 implements overlapping experimental APIs (`events.py`, `EvidenceGate`, `ReviewPolicy`, `RepairPlanner`). That parallel exploration should **not** be merged into the canonical sequence due to conflicting `evidence.py`, `review_policy.py` and `planner.py` paths. This PR carries only the narrowly useful correctness fixes.

## Next gates

1. Resolve ancestry drift from PR #5 across #6–#10; perform a complete upstream-safe integration and typed Python 3.11/3.12 test run before merge.
2. Provide a real authenticated read-only GitHub adapter with scope binding, run/check association and current SHA verification.
3. Add a durable, fenced per-task upload *intent* before any real upload action; support unknown/reconcile instead of replaying uploaded files.
4. Build an authorized transport proof-of-capabilities, no model/High fallback, no silent app/plugin assumption and no blind message retry.
