# PR-03 — Durable logical workers, atomic scheduler and conservative supervisor

Audit date: 2026-10-19. Parent: `codex/orchestrator-v5-task-packages-outbox` (Draft PR #4). The existing V3/V4/V5 work remains unmerged to `master`.

## Status and hard safety boundaries

This PR implements an **offline-only** worker control plane. No ChatGPT sessions, model generations, uploads, hosted apps, GitHub/Supabase writes, callbacks, or actual remote workers are enabled. The registry can record **disabled** future transport identities (`codex_app_server`, `chatgpt_ui`) but only **mock** workers are schedulable. It intentionally cannot enable an unverified real transport. There is no model/plan/entitlement proof. The five-worker limit is **logical capacity**, not five independent ChatGPT generations.

## New modules

- `worker_registry.py`: SQLite-bound immutable worker identity keyed by `worker_id`, `account_id`, `project_id`, role, transport and session key. Unique per-account/transport/session binding; cap five logical workers per account. Durable worker-assignment rows, heartbeat and account pause/throttle controls. `stdio-singleton` never qualifies as an independent remote worker.
- `scheduler.py`: task+mock-worker reservation in **one `BEGIN IMMEDIATE` transaction** under one authority DB. Uses existing `Store` fencing tokens, slot rules, dependency DAG, global scope overlap and sealed TaskPackages validation. Emits `worker.assigned` event. A claim **never calls `Transport.send`** or grants a send permit. A missing or corrupt TaskPackage stays queued rather than silently sending. Uncertain/verified/needs-human tasks continue to own resource locks.
- `supervisor.py`: operator pause/resume, account-wide throttle, persistence of deduplicated stale-heartbeat alerts. A stale worker never frees a possibly live remote job or triggers a resend. `stop/cancel` of live remote jobs is deliberately NOT implemented; account pause only stops new scheduling.
- `capabilities.py`: machine-readable declaration of disabled uploads, plugins, model verification and external access.
- `worker_commands.py`: Codex-friendly JSON CLI command registration; worker details and claim tokens are redacted from CLI outputs.

## CLI examples (PowerShell)

```powershell
$env:CHATGPT_ORCHESTRATOR_DB = "$HOME\.chatgpt-web2api\controller.sqlite"
python -m chatgpt_web2api.orchestrator --json worker-capabilities
python -m chatgpt_web2api.orchestrator --json register-worker --id mock-dev-1 --account personal --project sample --role implement --transport mock --session-key fake:mock-dev-1
python -m chatgpt_web2api.orchestrator --json register-worker --id mock-review --account personal --project sample --role review --transport mock --session-key fake:mock-review
python -m chatgpt_web2api.orchestrator --json list-workers --account personal
python -m chatgpt_web2api.orchestrator --json pause-workers --account personal
python -m chatgpt_web2api.orchestrator --json resume-workers --account personal
python -m chatgpt_web2api.orchestrator --json scan-workers --account personal --stale-after 300
```

A task must be created and its TaskPackage **sealed** using the PR-02C CLI before a mock claim:

```powershell
python -m chatgpt_web2api.orchestrator --json worker-claim --account personal --project sample --blob-root "$HOME\.chatgpt-web2api\blobs"
```

**No external action is triggered by `worker-claim`.** It returns `remote_send_permitted=false` and no fencing token; only trusted future in-process code can pass the token to an authorized outbox transport. The pre-existing low-level `claim` CLI still reserves tasks outside this registry: it is **not** an approved live dispatch path and must be gated or deprecated before PR-07.

## Test matrix

Local Python 3.13 `pytest` using V4 offline test fixtures plus new PR-03 modules: **48 passed, 8 subtests passed**. Included: registration idempotence, duplicate session rejection, disabled real transport, five-worker cap, missing sealed inputs, role matching, global resource conflict, dependencies, pause/throttle, stale worker alerts, restart persistence and `multiprocessing.spawn` concurrent claims. A test seam emulates the existence of sealed packages; the actual V5 `TaskPackages` integration and full upstream suite still require PR-level CI/E2E checks. `python -m compileall` passes.

## Limitations and follow-on gates

1. Registry IDs are locally asserted, **not provider-verified identities or permissions**. No credentials are read or stored.
2. The SQLite DB is a single authority. Multiple separate DB files cannot enforce shared locks. Windows SQLite storage and ACL review remain PR-08 work.
3. `WorkerRegistry.heartbeat()` is a **local liveness hint**, not authenticated evidence of completion. Workers marked stale remain holding slots/locks until manual/provider-backed reconciliation; no remote cancellation is attempted.
4. The `Scheduler` pre-checks content before its atomic claim (the database transaction fences the claim, not the content snapshot); the future outbox/upload transport must re-verify the snapshot immediately before the remote effect.
5. There is no event-driven long-running daemon yet, only durable control-plane primitives and bounded explicit commands. PR-04/05 must add callback adapters, error codes and low-token event subscriptions.
6. Existing V3 `Controller.dispatch` and direct `Store.claim` paths are **not redirected** by this PR. A production transport must be routed exclusively through the authoritative TaskPackages + WorkerRegistry + DispatchOutbox path after gated integration tests.
7. Even after implementation, browser automation needs separate service authorization and must not circumvent account/model limits or approvals. Official Codex app-server sessions and ChatGPT web chats are different product surfaces; do not claim Plus-hosted apps are present in the former.

## Next PR: PR-04

An immutable evidence verifier, per-attempt callback correlation, bounded planner/reviewer DAG, strict approval policy and provider-backed reconciliation; then PR-05 Codex MCP/CLI bindings. Live file upload, app selection and strict GPT-6 High are postponed to PR-06/07 capability checks. All branches remain draft; no deployment.