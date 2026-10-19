# PR-19 — GitHub CI event and required-job trust policy

**Date:** 2026-10-19  
**Parent:** PR #20 (`codex/orchestrator-v18-task-bound-provider-evidence`)  
**Scope:** Read-only evidence hardening. No ChatGPT web automation, new upload, provider write, automatic merge, or task finalization.

## Independent code-review finding

PR #19–#20 checked the numeric repository ID, PR head SHA, workflow ID, run SHA and `conclusion=success`. That is **insufficient to prove an expected trusted CI policy ran**: a green manually dispatched workflow or a workflow whose key jobs were omitted could be accepted. The previous read-only observation would then be sealed with a digest that did not attest which jobs completed. Also, checking PR head SHA against a GitHub `pull_request` workflow can be incorrect because that event often tests a generated merge ref rather than the branch head SHA.

## Implemented in this PR

- `GitHubReadOnlyEvidence` now requires a non-empty **operator-configured `required_job_names`** list (frozen set), independently of any implementer-provided text. The list must name the exact GitHub job display names (matrix expansions included), not just the workflow name.
- **Supported event: `push` only**, with exact `run.event`, `run.head_branch == PR.head.ref`, `run.head_repository.id == trusted repository ID`, and `run.head_sha == PR.head.sha`. Workflow dispatch and pull-request events fail closed rather than being wrongly described as equivalent. Fork-to-fork PRs are not yet supported: `PR.head.repo.id` must match the trusted repository ID.
- Read latest-attempt jobs through the narrowly allowlisted GitHub REST GET endpoint `/actions/runs/{run_id}/jobs?filter=latest&per_page=100`. Reject pagination/incomplete lists (up to 100 jobs), duplicate names, missing required jobs, jobs with mismatched run ID or head SHA, and any job not `completed/success`.
- Re-read the PR head **after** both run and job reads. Exact HEAD and branch must remain unchanged throughout the observation window.
- Attach `event`, `head_branch`, and sorted `successful_jobs` to the **ephemeral read-only receipt**. The existing `ProviderEvidenceLedger` still stores an immutable audit observation and never elevates this to merge or task authorization. Provider review provenance and CI policy must be rechecked by a future finalizer.
- The strict HTTP reader now allows exactly the single parameterized `/jobs?filter=latest&per_page=100` endpoint. It does not accept arbitrary query parameters, redirects, or write methods.

## Explicit technical constraints / new incompatibility

1. **Required configuration change** for callers of `GitHubReadOnlyEvidence`: pass `required_job_names=frozenset({...})`. No implicit allow-all or untrusted agent-supplied names. Old callers intentionally fail until upgraded. Existing repo call sites in the changed GitHub/provider tests were updated.
2. Current `.github/workflows/ci.yml` triggers `push` only for `master`, while all agent changes live in stacked feature branches. Consequently **this fork currently has no qualifying CI run on the feature branch**. Add a dedicated trusted push-on-feature-branches workflow, subject to runner/permission security review, before expecting this gate to succeed in production. Do **not** weaken event policy to `workflow_dispatch` to fake CI evidence.
3. GitHub `pull_request` jobs often use synthetic merge SHA. A future PR-event adapter must explicitly verify the merge ref against GitHub's PR merge SHA or refs, not pretend `run.head_sha` matches `PR.head.sha`. This PR intentionally does not implement that alternate proof.
4. Exact required job names must include all security gates relevant to the actual workflow: e.g. `lint`, `secret-scan`, `build`, and all six OS/Python `test` matrix job names. GitHub job names are distinct from job IDs and can change with workflow edits. A workflow editable by untrusted PR code cannot be treated as immutable policy without additional branch/workflow provenance checks.
5. A green run, even with the new checks, **does not verify immutable workflow source**, signed reviewer identity, required approvals, authorization to merge, future live account rights or successful ChatGPT upload. Finalization remains disabled.
6. The run/jobs API is read-only; all jobs must fit in a single 100-item page. More jobs deliberately fail closed; pagination can be added later with bounded GET pages and explicit completeness validation.

## Evidence and tests

Local assembled offline stage on Python 3.13:

```bash
PYTHONPATH=src python -m pytest -q \
  tests/test_orchestrator.py tests/test_orchestrator_cli.py \
  tests/test_orchestrator_pr04.py \
  tests/test_orchestrator_github_readonly_evidence.py \
  tests/test_orchestrator_provider_evidence.py
# 119 passed, 8 subtests passed
python -m compileall -q src tests
```

The unit tests use deterministic fake GitHub provider responses. They cover manual/PR trigger rejection, spoofed branch/repository, required job missing/failed, incomplete pagination, duplicate jobs, wrong job run identity, moved PR, exact request allowlist and task/evidence binding. These are **not live GitHub CI or Windows tests**. No GitHub Actions run has been established for this fork; Ruff and the full upstream suite are still separate merge requirements.

## Next review/implementation gates

- [x] Event, same-origin branch and required CI job checking in the read-only adapter.
- [x] Update deterministic negative tests and explicit caller policy.
- [ ] Trusted GitHub workflow **source** and branch provenance (workflow-file protection / immutable SHA) and required job/check governance.
- [ ] Provider-authenticated GitHub reviewer identity + SHA-bound approval, freshness invalidation, self-review exclusion.
- [ ] A separate finalization authority to check current PR/CI/review/user approval again and release task locks in one compare-and-swap transaction. Do not re-enable legacy `Store.finalize_verified`.
- [ ] Authorized Codex/remote transport and authenticated callbacks, file receipt reconciliation, app entitlements and model-effort verification.
- [ ] Full stacked checkout, Ruff, Python 3.11/3.12, Windows CI, and a real allowed GitHub workflow run.

**Authority:** [`ORCHESTRATOR_V5_IMPLEMENTATION_TRACKER.md`](ORCHESTRATOR_V5_IMPLEMENTATION_TRACKER.md). Keep the PR Draft, do not merge into `master` until the remaining release gates are satisfied.
