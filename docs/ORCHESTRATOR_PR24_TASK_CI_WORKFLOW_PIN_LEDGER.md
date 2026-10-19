# PR-24 — Bind pinned CI source to task and review evidence

Date: 2026-10-19. Stacked on Draft PR #25. **Read-only** offline control-plane hardening.

## Gap closed

PR #25 verifies that GitHub Actions workflow YAML at an exact PR HEAD has a controller-approved Git blob SHA. But the result previously lived only in a transient `ReadOnlyPRRunReceipt.workflow_blob_sha`. The durable `ProviderEvidenceLedger` omitted this field from SQLite and from its task/dispatch digest. A later review could treat a green-but-unpinned CI receipt as equivalent to a pinned one.

## Changes

- Add nullable `workflow_blob_sha` to `orchestrator_provider_observations` under `BEGIN IMMEDIATE` for race-safe, additive migration of existing V23 SQLite databases.
- Pin-enabled evidence requests **require** the actual `workflow_blob_sha` to equal independently configured `WorkflowSourcePin.trusted_blob_sha`. Unpinned gates must not claim an externally verified pin.
- Hash and store a verified source SHA along with task ID, attempt ID, sealed package, fenced result, claim version, repository, PR HEAD and CI run. Repeat inspections are idempotent; a changed pin cannot overwrite prior evidence.
- Legacy records with `workflow_blob_sha=NULL` preserve their old digest, remain unauthorizing, and **cannot** pass review after a pinned policy is configured. No retroactive upgrade from a source check at a different time.
- `TaskReviewEvidenceLedger` verifies source-pin policy and the new digest before any review API read, includes the verified source identity in the transitive review digest, and passes it through to existing downstream implementer provenance snapshots.
- New `tests/test_orchestrator_workflow_pin_ledger.py` exercises persistence, digest calculation, reopened store, pin spoofing, tampering, review binding, legacy migration and read-only invariants using fake GitHub data.

## Proof / limitations

This PR was authored through GitHub connector file writes. **Its tests have not been executed on the committed, full stacked branch**: this environment cannot clone GitHub over the container network and this repo has no workflow runs for feature-branch stacks. Do not claim a passing CI matrix or exact local code equivalence. It needs a Codex/Windows checkout with Python 3.11/3.12, Ruff, the upstream suite, the new pinned tests, and an external reviewer before merge.

The source pin still does not prove all external CI dependencies are immutable (workflow actions use tags; CI downloads gitleaks). Nor does it authenticate a remote coding worker, turn a successful CI run into human consent, or prove ChatGPT Plus/High model execution. The finalizer remains **absent** and both permission flags stay False.

## Next gates

1. Run `PYTHONPATH=src python -m pytest -q tests/test_orchestrator_workflow_pin_ledger.py tests/test_orchestrator_provider_evidence.py tests/test_orchestrator_task_review_evidence.py tests/test_orchestrator_implementer_provenance.py` and `python -m pytest -q -m "not e2e"` from exact stacked HEAD; run Ruff, matrix and package build.
2. Independently approve protected workflow source and pin all external CI action/tool dependencies; avoid trusting mutable tags or worker-controlled install scripts.
3. Provider-attested worker identity, reviewer permission refresh, current SHA rechecks, explicit human consent and a separate authorized finalizer with atomic compare-and-swap remain release blockers.
4. Do not activate unattended web sends, upload, remote plugin selection or automatic merges from mock evidence.

Refs: `docs/ORCHESTRATOR_PR23_WORKFLOW_SOURCE_PIN.md` and `docs/ORCHESTRATOR_V5_IMPLEMENTATION_TRACKER.md`.
