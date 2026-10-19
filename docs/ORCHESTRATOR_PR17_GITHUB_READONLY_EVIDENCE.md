# PR-17: Read-only GitHub PR/CI evidence adapter

## Scope and independent review

Based on the stacked `codex/orchestrator-v16-mock-upload-outbox-integration` development branch (GitHub Draft PR #18), this step adds a **read-only GitHub evidence adapter**. It is not a trusted finalizer, approval authority, or GitHub write tool. No user repository is modified by running this module's inspections.

The previous `EvidenceLedger.inspect_mock` only handled synthetic snapshots and deliberately set `assurance=offline_mock_only`; it cannot prove a real remote commit. The new `GitHubReadOnlyEvidence` verifies the relevant GitHub REST response shapes independently, without silently promoting mock evidence or calling `Store.finalize_verified`.

## Verification contract

- Caller supplies an **independently configured** numeric GitHub repository ID, exact owner/repository name, required SHA and an allowlist of trustworthy workflow IDs. Values from an untrusted agent's text must **not** configure this allowlist or authoritative repository ID.
- Repository `id` and canonical `full_name` must match; for PRs, the **base** repository ID must match even if the head branch originates from a fork.
- PR must remain open/unmerged and have the required 40-character lowercase head SHA, verified once before and once **after** the workflow request. Any head change, including an ABA race that is not observable at the two samples, is a remaining caveat and requires final revalidation at the external action boundary.
- Workflow run must belong to this repository and have a configured `workflow_id`, `head_sha` equal to current PR head, `status=completed`, `conclusion=success` and a valid attempt number.
- Result always records `assurance=provider_read_only_unreviewed`, `live_send_permitted=False`, and `production_finalization_permitted=False`. There is no automatic transition of a task or removal of a write lock.
- Optional `GitHubReadOnlyHTTP` can make actual **GET-only** requests to `api.github.com` with an explicitly provided credential. No automatic environment-token discovery, no redirects, no arbitrary URLs, no access-token logging, a bounded response and timeout. In the test suite all responses are synthetic; **live GitHub API execution of this module is not yet tested**.

GitHub REST primary references:
- [Get a pull request](https://docs.github.com/en/rest/pulls/pulls#get-a-pull-request)
- [Get a workflow run](https://docs.github.com/en/rest/actions/workflow-runs#get-a-workflow-run)

### Local usage (read-only; requires preconfigured authorized client)

```python
from chatgpt_web2api.orchestrator.github_readonly_evidence import (
    GitHubReadOnlyEvidence, GitHubReadOnlyHTTP,
)

probe = GitHubReadOnlyEvidence(
    owner="OWNER", repo="REPO", repository_id=123456,
    trusted_workflow_ids=frozenset({12345678}),
    reader=GitHubReadOnlyHTTP(token=token_from_authorized_secret_store),
)
receipt = probe.inspect(pr_number=1, expected_head_sha="a" * 40, run_id=1234)
# receipt.production_finalization_permitted is always False
```

These are placeholders, not repo-specific credentials or verified workflow IDs. Do not copy them as real configuration.

## Test evidence

`PYTHONPATH=src python -m pytest -q tests/test_orchestrator_github_readonly_evidence.py` → **25 passed** (Python 3.13, offline synthetic provider responses). `python -m compileall` also passed.

`ruff` was **not installed** in this runtime. Full repository, Windows, Python 3.11/3.12, and a live API read smoke test have **not** been run. Keep Draft and no automatic merge.

## Follow-up gates

1. Connect the read-only inspector to *non-mutating* task-specific evidence intake, binding configured authority to `github:repo/<numeric-id>` resource scope, task ID, sealed package SHA, attempt ID, PR number and CI run. Ensure no ability for model text to choose trusted repository or workflow IDs.
2. Add authenticated independent reviewer provenance and invalidation of approvals on HEAD movement. Verify current PR state and CI from the provider **again at the finalization boundary**.
3. Build an explicit, authorized, transactional finalization service (human confirmation where required) to replace the disabled legacy `Store.finalize_verified()`. Do not allow the read-only receipt to call it directly.
4. Keep the legacy `Controller.dispatch` disabled for live use. An approved, bounded transport adapter must use the durable TaskPackages/WorkerRegistry/DispatchOutbox path; mock upload receipts and capabilities cannot be promoted to production.
5. After full-stack integration tests and approval, test only a single authorized external worker. Five logical slots do not prove five simultaneously available GPT-6 High Plus web sessions.
