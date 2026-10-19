# PR-22 — Signed GitHub commit observation and local mock-worker correlation

**Base:** Draft PR #23 (`codex/orchestrator-v21-task-bound-review-evidence`), 19 October 2026. All outputs are **read-only observations, not production authorization**.

## Review finding

`TaskReviewEvidenceLedger` currently accepts a numeric `trusted_implementer_user_id` from operator policy, and excludes this user from GitHub reviewer approval. It does not show whether that account is associated with the actual PR HEAD commit, nor whether that identity corresponds to the assigned Orchestrator worker. This leaves a gap between the reviewer-exclusion check and real code provenance. The git commit `author` and `committer` can be different; even a GitHub Verified signature is not cryptographic attestation of a particular ChatGPT/remote Codex **session**.

## Implemented (non-authorizing)

1. New `GitHubSignedCommitReader` uses the existing constrained `GitHubReviewsHTTP` GET-only reader, extending its endpoint allowlist only to `GET /repos/{owner}/{repo}/commits/{exact_40_hex_sha}`. It verifies numeric repository ID/name, open same-repo PR, **exact current HEAD SHA before and after** commit read, associated numeric `author.id` and `committer.id` both matching a trusted controller policy, and GitHub commit signature `commit.verification.verified is True` with `reason == "valid"`.
2. New `ImplementerProvenanceLedger` checks an existing **fresh task-bound CI receipt and sealed reviewer receipt**, a completed dispatch and package, current task claim and canonical GitHub lock via existing ledgers. It checks the active scheduler worker assignment and enabled `implement` **mock** worker in the same project, and a strictly operator-configured `worker_id -> GitHub user ID` mapping that matches the reviewer-exclusion identity.
3. The worker assignment version was recorded **when reserved**, while legitimate dispatch/result transitions increment the task version. Therefore verify `1 <= assignment.claim_version <= current_task_claim_version`, and rely on the stronger already-established task claim-token hash, completed outbox attempt, package and review CI digest checks. A new claim/outbox mismatch still fails closed.
4. Re-check all SQLite rows and policy fields inside `BEGIN IMMEDIATE` after network reads; create one immutable SHA-256 receipt and redacted audit event. Concurrent identical observations are idempotent. Changed inputs fail closed.
5. All results and stored rows mark `production_finalization_permitted=False` and `live_send_permitted=False`. No merges, user approvals, state promotion, write-lock release, or browser sends.

## Evidence and reproducibility

Offline/local Linux with Python 3.13, exact preexisting staged PR #23 code for the store, task review and provider tests:

```bash
PYTHONPATH=src pytest -q tests/
python -m compileall -q src tests
```

**129 tests passed** (31 targeted implementation attribution tests plus 98 existing CI/reviewer/task-regression tests), syntax compilation succeeded. These test doubles simulate GitHub responses and mock-worker rows; there is **no live signed-commit/provider E2E**, no fully assembled GitHub checkout, no Ruff installed, no Windows test matrix.

Negative cases: invalid/unsigned signature, author or committer mismatches, moved/forked PR head, wrong repo, disabled/stale/changed mock worker assignment, wrong project, invalid claim version, changed CI/review digest, remapped worker policy, concurrent observations and in-flight SQLite mutation. The baseline review tests still pass after extending the HTTP endpoint allowlist.

## Critical security boundaries

- The GitHub REST `author.id` identifies the GitHub account associated with commit **author metadata**; `committer.id` identifies the GitHub commit actor. A Verified signature verifies the signing key/content association, but it does **not** verify that a specific LLM web tab or remote worker authored every line. Requiring both IDs match a known account is deliberately restrictive; delegated/bot commits or unsigned commits will be rejected until a separate attested policy exists. Do **not** silently relax this.
- The worker registry is **mock-only**: `session_key=fake:...` and a local `worker_id -> numeric GitHub ID` mapping are **not** independently authenticated worker/session identities. This new ledger must never be wired into a production finalizer as if it were remote session attestation.
- The untrusted remote commit metadata must never specify reviewer allowlists, worker ID policy, workflow IDs, permissions or account approvals. Operator policy must be guarded separately.
- Protected workflow provenance, complete CI checks on the current SHA, independent reviewer permissions, explicit human approval (when required), replay-safe single dispatcher and trusted finalizer are still P0 gates. The old `Store.finalize_verified` and `Controller.dispatch` remain default-deny.
- For real Codex/GitHub integrations, verify the identity and permission of the GitHub App/user that actually created the commit, and cryptographically bind that provider request/turn to a worker and attempt; never infer it from commit metadata alone.

## Next steps

1. Run the **exact stacked PR #1→this PR** unit/integration suite and Ruff on supported Python versions and Windows. Compare SQLite schema against real PR-03 registry, not only the fake fixture.
2. Define a transport-specific **authenticated** worker/attempt-to-provider identity binding. For signed commits by a bot, design explicit trusted bot/installation provenance rather than guessing an author identity.
3. Add a protected-workflow-source gate and a read-only **fresh finalization preflight** combining latest PR HEAD, CI, reviewer and authenticated implementer observations. Keep production completion disabled until a genuine authorization boundary is available.
4. Future remote file upload, Plus apps/plugin selection and exact model/High verification require separate provider-approved capabilities; no ChatGPT Web automation is enabled in this PR.
