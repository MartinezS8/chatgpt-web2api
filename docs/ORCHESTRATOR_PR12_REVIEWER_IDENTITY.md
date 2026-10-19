# PR-12 — Fail-closed reviewer identity, account, project and session checks

Base: Draft PR #12 `codex/orchestrator-v11-evidence-scope-callback-redaction`.

## Independent audit context

A parallel exploratory PR-04 (#13) overlapped canonical PR #6 and was closed unmerged. Its negative tests suggested a precise issue in the canonical `ReviewLedger.record_mock`: different worker IDs alone do not guarantee that implementer and reviewer belong to the same authorized account and project, or that they represent distinct sessions.

This is a **focused incremental patch** to the canonical PR #6→#12 stacked chain. It does not introduce a competing evidence/review schema.

## Changes

- Validate review task's `project_id` matches the implementation task.
- Fetch both assigned workers' `account_id`, `project_id`, `role`, `transport`, `enabled` and `session_key` from the PR-03 registry schema.
- Fail closed unless both belong to the same account and project as the task; reviewer is an enabled `review` mock worker; producer is an enabled `implement` mock worker; and their session keys are **different**.
- Update PR-04 fixture to use these actual PR-03 worker identity columns.
- Add focused negative tests for cross-account, cross-project, duplicate-session, disabled producer and unrelated review-task project scenarios.

## Safety and test status

- **No live authorization is inferred** from local worker registry identity fields: the worker registry is still mock-only.
- `ReviewLedger.record_mock` remains a **local/offline review decision**; it does not authorize a production merge, provider write or remote callback acceptance.
- Current branch changes consist solely of mock review identity rules + tests + documentation.
- Tests are **committed but have not been executed against the fully assembled PR #1→#12 stack in this turn**. Ruff/Windows CI and authenticated evidence/transport also remain pending as permitted for later Codex runs.
- Parent PR #12 and `master` must stay unchanged; this patch is Draft and stacked on PR #12.

## Suggested verification

```bash
python -m pytest -q tests/test_orchestrator_pr04.py
python -m pytest -q -m 'not e2e'
ruff check src/ tests/
```

After this, independently inspect the remaining legacy `Store.finalize_verified` bypass, provider HEAD/CI revalidation and the ancestry alignment of PRs #6–#12 before enabling any real transport.
