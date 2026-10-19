# PR-23 — GitHub CI workflow source pin

Date: 2026-10-19. Stacked on Draft PR #24. Scope: read-only source provenance, no merge or finalization.

## Review finding

Before this change, a successful push run with a trusted workflow ID and job names could have used weakened YAML changed by an implementation worker on the PR branch. The run's green conclusion alone did not verify its source logic.

## Implementation

- New workflow_source_pin.py checks the run workflow ID, head SHA, repository ID, source path, active workflow metadata, and workflow file at the exact PR commit.
- Trusted workflow file SHA is operator-configured outside the agent-controlled task. The adapter downloads the exact .github/workflows/*.yml or *.yaml file at the reviewed HEAD, verifies base64 size and content against Git's blob SHA-1, rejecting modified or malformed source.
- GitHubReadOnlyHTTP allowlist extended only for numeric workflow metadata and exact HEAD-pinned workflow contents GET endpoints. No redirects or arbitrary contents paths.
- GitHubReadOnlyEvidence accepts an optional matching pin and returns workflow_blob_sha only when the pin passes. Unpinned old receipts explicitly report workflow_blob_sha=None.
- The ordinary read-only assurance remains unchanged. No production finalization, merge, write action, message send or model/plugin authorization is granted.

## Test evidence and limitations

- 35 standalone Python 3.13/Linux mock-provider cases passed locally before GitHub transfer, including wrong workflow ID/path, tampered bytes, bad base64, stale SHA and configuration abuse.
- Five additional integration cases committed for the full stacked checkout but NOT executed against the GitHub branch. Due to an expired file-handoff session, files were transferred through GitHub directly rather than an exact-blob local transfer; the full checkout and Ruff/Windows are still unverified.
- Current master .github/workflows/ci.yml blob is 4695e7cfd56bf459839b6842a6dcc980e27cc154. This is NOT automatically a protected or approved trust anchor.
- Workflow runs: zero. Existing workflow triggers push on master only and pull_request against master; stacked PR push runs cannot be assumed eligible.
- Branch-protection GET was denied with 403; repository rulesets returned []. Branch protection is NOT established.
- Even identical YAML can invoke mutable checkout scripts, actions by tags and externally downloaded tools. Exact source is only one piece of trustworthy CI provenance.

## Next P0 gates

1. Codex tests assembled PR #1–#25 stack on Windows/Linux/macOS with Ruff and full upstream tests.
2. Operator-owned protected source pin, workflow IDs, required job names, runner permissions and immutable external CI dependencies must be independently verified.
3. Persist and digest workflow source evidence with task/attempt/CI observation, then require fresh rechecks and independent human consent before any trusted finalization.
4. Keep previous direct transport and finalizer entry points blocked; live GPT-6 High, ChatGPT Plus plugins, upload and callback integration remain unimplemented.

See ORCHESTRATOR_V5_IMPLEMENTATION_TRACKER.md. GitHub Issues remain optional.
