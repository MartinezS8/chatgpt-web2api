# PR-02B — Stable resource identities (operator-asserted, write-deny by default)

Parent: `codex/orchestrator-v4-p0-invariants` (PR #2). This extension adds a DB-backed mapping from human-readable resource aliases to stable canonical lock scopes; it does NOT grant GitHub/Supabase/Vercel write permissions.

## Contract
- GitHub lock root: `github:repo/<numeric repository id>`; optional slash-delimited subpath for subtree conflicts.
- Supabase lock: `supabase:project/<project ref>/env/<environment>`; production/staging are distinct only when the environment is explicitly distinct.
- Vercel lock: `vercel:project/<project id>/env/<environment>`.
- Operator aliases: two aliases pointing at the same canonical identity map to one lock; alias reassignment is forbidden rather than silently changing task scope.
- `ResourceRegistry.provider_write_authorized()` always returns **false**. The registry records operator assertion, never provider-backed authorization.
- Legacy `--write-scope` remains for existing offline tests, but use `--resource-alias` for new provider-scoped jobs. Production dispatch must eventually enforce provider-verified identity plus credential-bound permission checks.
- Reservations across separate controller database files **do not coordinate**. Use one shared authority or introduce an external distributed lock authority before scaling beyond one controller.

## CLI (local; no network action)
```powershell
python -m chatgpt_web2api.orchestrator --db .\controller.sqlite --json register-resource --alias gh:my/repo --provider github --provider-id 12345 --operator me
python -m chatgpt_web2api.orchestrator --db .\controller.sqlite --json resolve-resource --alias gh:my/repo --path src
python -m chatgpt_web2api.orchestrator --db .\controller.sqlite --json list-resources
python -m chatgpt_web2api.orchestrator --db .\controller.sqlite --json create-task --id task1 --project demo --role implement --prompt-file .\task.md --resource-alias gh:my/repo
```

## Gates for real writes (not implemented)
1. Resolve the repository/project ID directly from an authenticated provider connector and bind the result to its credential scope and account/installation.
2. Check requested operation + environment + branch against explicit allowlist; require production/write approvals.
3. Revalidate identity before applying a write; deny aliases with disputed provenance.
4. Never treat a local name, self-asserted `provider_verified` string, or a lock reservation as permission to modify an external service.

## Test evidence
Offline tests for alias reconciliation, global writer exclusion, rejection of alias rebinding, path traversal, provider self-attestation, and CLI registration. No live provider or Windows tests were performed.