# Codex orchestration control plane — CLI-Anything assessment and implementation (PR-01)

Baseline: fork `MartinezS8/chatgpt-web2api` from `Octo-Lex/ChatGPT-Web2API`, upstream `master` commit `497527dceabfa3f95961e23c291e618c5570f1ac` (checked October 19, 2026).

## Decision

**Use CLI-Anything as a methodology, not as a hard dependency.** `HKUDS/CLI-Anything` (Apache-2.0) creates CLI harnesses and skills for agent control of software; it does not provide the task DAG, immutable result validation, five persistent ChatGPT conversation owners, or a permitted ChatGPT web automation integration that our use case requires. Its `codex-skill/SKILL.md` and `cli-anything-plugin/HARNESS.md` recommend discoverable subcommands, machine-readable JSON, strong backend validation, and meaningful end-to-end tests. Its `browser` harness wraps DOMShell and requires an additional extension; it does not supersede Octo-Lex's owned-tab/session locks.

Original upstream sources, for audit/reference only (no CLI-Anything source copied into this PR):
- https://github.com/HKUDS/CLI-Anything/blob/34f519533bc175d2fe287ab8316b0dd99bb9cc43/codex-skill/SKILL.md
- https://github.com/HKUDS/CLI-Anything/blob/34f519533bc175d2fe287ab8316b0dd99bb9cc43/cli-anything-plugin/HARNESS.md
- https://github.com/HKUDS/CLI-Anything/blob/34f519533bc175d2fe287ab8316b0dd99bb9cc43/skills/cli-anything-browser/SKILL.md

## Implemented in this PR

- Transport-independent `Store` with SQLite WAL, immutable task identities (prompt SHA-256), dependency tracking, project-level write-scope locking, up to five reserved slots, recovery, and audit events.
- `Controller` takes a **caller-supplied** `Transport` and `Verifier`; no authenticated browser transport is supplied, and the default verifier rejects unsupported completion claims.
- A compact CLI for Codex. Example from an installed checkout on Windows PowerShell:

```powershell
$env:CHATGPT_ORCHESTRATOR_DB = "$HOME\.chatgpt-web2api\controller.sqlite"
python -m chatgpt_web2api.orchestrator capabilities --help
python -m chatgpt_web2api.orchestrator --json capabilities
'Analyze module A; produce a PR only.' | Set-Content -Path .\task-a.txt -Encoding utf8
python -m chatgpt_web2api.orchestrator --json create-task --id task-a --project app --role implement --prompt-file .\task-a.txt --write-scope repo:src/module-a
python -m chatgpt_web2api.orchestrator --json list-tasks --project app
python -m chatgpt_web2api.orchestrator --json claim --project app
python -m chatgpt_web2api.orchestrator --json status --project app
```

In the above CLI, **`claim` only reserves a slot; it does not send a prompt**. The task's prompt text is not stored in SQLite; retain your approved prompt package separately and verify its SHA-256 before any later transport submission.

Supported CLI commands: `capabilities`, `status`, `list-tasks`, `task`, `events`, `create-task`, `claim`, `recover`. `recover` only requeues tasks still in `reserved` and marks uncertain `dispatching` sends `unknown_delivery`; it never resends automatically.

## Explicit non-goals and blockers

1. No live ChatGPT UI control, model-selection, uploads, credential management, external writes, or parallel account requests in this PR.
2. An Octo-Lex `stdio` session is keyed `stdio-singleton`, so a pool size of five **does not** mean five separately addressable sessions. Explicit worker identity and transport topology are a separate gate.
3. Octo-Lex `do_chat_completion()` currently logs a model-selection failure and continues with the active model. A fail-closed GPT-6/High identity gate must be implemented before accepting live jobs.
4. Shared external resources (e.g. one Supabase environment) need a **global** resource ownership/permission design. Current file locks are per project and are not a production isolation guarantee.
5. The frontend ChatGPT service and its terms/entitlements are independent from technical automation capabilities. No attempt is made to circumvent rate limits, CAPTCHAs, or unsupported automation restrictions.
6. An agent's own completion text is **not proof of a code change**; independent immutable Git SHA, CI evidence and review gates are future work.
7. CLI-Anything promotes REPL mode and dry-run for some generated CLI harnesses; this minimal service CLI intentionally prefers one-shot audited commands and offers **no REPL or UI automation** yet.

## Gate / test commands

```bash
python -m unittest discover -s tests -p 'test_orchestrator*.py' -v
pytest -q -m 'not e2e' tests/test_orchestrator.py tests/test_orchestrator_cli.py
ruff check src/chatgpt_web2api/orchestrator tests/test_orchestrator.py tests/test_orchestrator_cli.py
```

The 20 focused unittest cases passed offline against Python 3.13 in the preparation environment. The entire upstream suite, Windows environment, package installation and GitHub Actions must be independently checked in the fork; no claims of completion are made for them.

## Follow-on work (separate PRs)

- **PR-02** Stable `worker_id` ↔ owned CDP target ↔ conversation identity with reconnection safety and concurrency simulation. No live sends until authorized.
- **PR-03** Fail-closed model and High setting attestation; attachments with explicit allowlist and actual upload verification.
- **PR-04** Optional legitimate execution transport, independently verifiable GitHub/Supabase capability matrix, independent review gates and artifact provenance.
- **PR-05** Hardening: worker stop/pause/resume, terminal UI, audit log retention, schema migrations, global resource locks, Windows launch and CI verification.

## Licensing

The new orchestration files originate from the local V3 design discussed for this project, and are not copied from CLI-Anything. Octo-Lex's original MIT LICENSE remains in the repository. Should future work copy Apache-2.0 CLI-Anything files, retain the applicable copyright/license notices and review any `NOTICE` obligations. The present PR does not vendor external code.