# PR-21: Task-bound GitHub reviewer observations (read-only)

**Basis:** Draft PR #22 `codex/orchestrator-v20-github-review-attestation`. 19 October 2026.

## Review finding

`GitHubReadOnlyReviews.inspect()` in PR #22 verifies eligible GitHub reviewers, reviewer permissions and current PR SHA, but returns only a detached, ephemeral `ReviewObservation`. `ProviderEvidenceLedger` in PR #20 separately stores a provider-read-only CI result bound to a task, dispatch attempt, sealed package and canonical repository resource. Without a common task-bound receipt, an automated finalizer could mistakenly reuse a review from the wrong task, version or dispatch attempt.

## Implemented

- New `TaskReviewEvidenceLedger` stores an **immutable, local, read-only** observation linking `task_id`, `attempt_id`, `package_sha256`, task `claim_version`, hashed CI observation digest, canonical repository ID, PR number, current head SHA, trusted operator-supplied numeric implementer GitHub identity, reviewer numeric IDs and GitHub review IDs.
- Requires an existing **fresh** PR #20 CI observation and an exact completed dispatch. Recomputes the CI digest against current task/outbox/package binding, rejecting corrupted rows before asking GitHub for any reviews.
- Uses PR #22's provider review adapter, which independently verifies reviewer permissions and SHA; checks returned identity, proof flags, timestamps and threshold again.
- **No SQLite write lock across network I/O.** Afterwards runs `BEGIN IMMEDIATE` and re-verifies the task, claim version, sealed package, completed dispatch, stored CI digest/observation age and status. Any drift aborts; concurrency-safe unique insert, immutable ID-based idempotency and redacted event.
- Refuses to issue any permission: `production_finalization_permitted=False` and `live_send_permitted=False` irrespective of success. Never marks a task `verified`/`finished`, releases locks, merges a PR or grants a GitHub/Supabase write.
- `trusted_implementer_user_id` and `GitHubReadOnlyReviews.trusted_reviewer_ids` are **operator-controlled configuration**, not agent-generated IDs. Future authenticated binding to actual worker/commit authorship is still required.

## Test evidence

Test environment: Linux / Python 3.13. The isolated stage uses the previous exact GitHub source versions of `store.py`, `provider_evidence.py`, `github_readonly_evidence.py` and `github_readonly_reviews.py`. Executed:

```bash
PYTHONPATH=src python -m pytest -q \
  tests/test_orchestrator_task_review_evidence.py \
  tests/test_orchestrator_provider_evidence.py \
  tests/test_orchestrator_github_readonly_reviews.py
python -m compileall -q src
```

**98 passed** (24 new task-review cases and 74 existing provider/CI/review regression cases). Includes unknown attempt, missing provider CI, wrong repository, stale or changed claim/result/package, manipulated CI digest, changed PR head, revoked reviewer permission, self-review, stale review time and 16 concurrent readers all producing exactly one immutable event. **This is not the full cumulative branch checkout or the complete upstream suite.** Ruff and Windows CI are not run.

## Important remaining gaps / acceptance gates

1. **Authenticity of implementer:** trusted numeric GitHub user ID still comes from trusted operator policy, not cryptographically/externally bound to GitHub commit author and authorized Orchestrator worker. Do not accept model-authored IDs or labels.
2. **Workflow provenance:** PR #21 permits `push` CI on direct matching SHA and required jobs, but a workflow in a changeable agent branch can still be weaker than the protected source. Pin immutable workflow source, job/check policy, protected trusted runner and required checks before trusting CI.
3. **Current-state revalidation:** Stored CI and review observations are snapshots and may become stale seconds later. A trusted finalizer must re-read current HEAD, CI status, review submissions, reviewer permissions and authorization immediately at its own decision boundary.
4. **Actual finalization:** `Store.finalize_verified` remains disabled after PR #15 and legacy `Controller.dispatch` remains default-deny after PR #16. Build a single trusted task completion service using atomic claim + evidence + human consent CAS, without reopening those bypasses.
5. **Real execution:** No authenticated live Codex/ChatGPT callback, remote file upload, app/plugin selection, confirmed GPT-6 High, five real website sessions or approved real transport is implemented by this PR. Account/provider authorization and scope remain separate blockers.
6. **Integration QA:** Run the complete stacked PR #1→#23 tree, Python 3.11 and 3.12, Ruff, Windows, approved offline fault-injection tests and independent review. Do not merge this draft based only on isolated tests.

### Next PR: provider reviewer/finalizer preflight (not an automatic merge)

- Verify authentic GitHub commit provenance and reviewer scope.
- Implement an isolated, read-only **authorization-preflight result** that requires fresh provider SHA, protected workflow version, all required jobs and independent SHA-bound reviewer approval; fail closed if approvals, auth or provider access missing.
- Require explicit user approval when applicable. Keep external writes/merges out of the finalization routine and retain audit receipts.
