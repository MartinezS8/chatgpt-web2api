# Codex Orchestrator V5 — Implementation tracker (19 October 2026)

## Branches / upstream authority

This is a **stacked, unmerged** plan. Nothing is in `master` until individually reviewed and merged.

1. [PR #1](https://github.com/MartinezS8/chatgpt-web2api/pull/1): V3 transport-neutral task control plane → `master` (Draft).
2. [PR #2](https://github.com/MartinezS8/chatgpt-web2api/pull/2): V4 fenced lease / resource quarantine → PR #1 (Draft).
3. [PR #3](https://github.com/MartinezS8/chatgpt-web2api/pull/3): PR-02B resource authority → PR #2 (Draft).
4. [PR #4](https://github.com/MartinezS8/chatgpt-web2api/pull/4): PR-02C immutable packages and dispatch outbox → PR #3 (Draft).

**Why no GitHub Issues?** GitHub returned HTTP 410, `Issues has been disabled in this repository`, while attempting to file this roadmap. This document is the canonical repository-side backlog until the repository owner decides to enable Issues. Do not silently turn Issues on.

## Implemented in the current stacked code

- [x] Local SQLite WAL task store with pre-dispatch fencing; conservative unknown-delivery quarantine (PR #2).
- [x] Operator-asserted aliases for canonical GitHub numeric repository IDs, Supabase project references / environment, Vercel project IDs / environment; no provider permissions claimed (PR #3).
- [x] Local sealed prompts and SHA-256 attachment manifests / content-addressed snapshots (PR #4).
- [x] Local atomic dispatch intent and per-attempt event stream with per-consumer cursors; no auto re-send of an unknown attempt (PR #4).
- [x] Local command-line task registration, alias resolution, package seal/inspect, and event cursor operations (PR #4).
- [ ] End-to-end integration with an authorized live transport (not yet implemented).
- [ ] Real ChatGPT file uploads, hosted app/plugin selection, actual GPT-6 High proof, provider-verified permissions, and account-limit enforcement (not implemented).

## Gate 0 (P0) — CI, legal/technical capability and independent audit

**Owner action may be required:** GitHub REST reports zero Actions workflow runs for this fork. The workflow in `.github/workflows/ci.yml` currently triggers pushes to `master` and PRs against `master` only; nested stacked PRs are not covered by that condition. PR #1 also has no reported run, so configuration/permissions must be checked, not guessed.

- [ ] Check fork GitHub Actions settings / explicitly enable Actions if desired.
- [ ] Make workflow runnable against stacked branch PRs without merging; retain Linux/macOS/Windows, Python 3.11/3.12, pytest non-E2E, Ruff, Gitleaks, wheel check.
- [ ] Record exact SHA and URLs of passing workflows for PRs #1–#4.
- [ ] Independently audit P0 changes and the write-deny behavior.
- [ ] Document **authorized** transport route (official Codex app-server vs any separately authorized UI experiment). Do not treat browser automation as preapproved.

**Gate to pass:** provider write calls remain prohibited before authorization, and full test/CI evidence is green.

## PR-03 (P1) — Worker registry and supervisor

Planned modules: `orchestrator/worker_registry.py`, `scheduler.py`, `supervisor.py`, `capabilities.py`.

- [ ] Stable worker IDs independent from slot numbers, browser targets, MCP session IDs and conversation IDs.
- [ ] Bounded global concurrency, account throttling and capability gating; `stdio-singleton` cannot masquerade as 5 independent tabs.
- [ ] Watchdog, heartbeat, pause/resume, stop/cancel and unknown-delivery reconciliation by a supported provider mechanism.
- [ ] Fake transport tests for 1, 2 and 5 logical workers, duplicate claims and process crashes.

**Acceptance:** no claim collision; no unattended re-send; reproducible status after a restart.

## PR-04 (P1) — Callback, verification, independent review, planning

Planned modules: `events.py`, `delivery.py`, `evidence.py`, `review_policy.py`, `planner.py`.

- [ ] Durable `attempt_id` and external turn/message identity correlation from an **authorized** transport.
- [ ] Progress notifications are advisory; lost progress is not confused with completion.
- [ ] Immutable, provider-verified GitHub commit/PR/CI evidence and branch-SHA invalidation.
- [ ] Independent read-only reviewer (cannot self-approve); human approval for consequential database / merge actions.
- [ ] Bounded fix–review loop with explicit budgets and failure exits.

**Acceptance:** duplicate/out-of-order/mismatched callbacks never result in a second completion or unsafe merge.

## PR-05 (P1) — Low-token Codex CLI/MCP

- [ ] Canonical JSON schemas and stable error codes for `submit`, `observe`, `subscribe`, `reconcile`, `pause`, `resume`, `request-review`, `plan`, `approve`.
- [ ] Add minimal MCP tools that call the *same* controller authority as CLI; never create an independent mutable state.
- [ ] Safe dry-run / fake transport, bounded polling, short status, and redaction of claim tokens and personal file paths.

**Acceptance:** a Codex controller can run a fake-agent plan end-to-end without browser/model calls.

## PR-06 (P1) — Authorized attachments, skills and ChatGPT apps/plugins

- [ ] Adapter that uploads the exact `TaskPackages` content-addressed snapshot via a transport that explicitly supports upload.
- [ ] Verify per-file remote attachment IDs, sizes/types, send-time status and quota; block send on partial/mismatched upload.
- [ ] Per-message app availability/permission preflight; handle approval prompts by a real user's explicit action, never auto-confirm.
- [ ] Reject unsupported capabilities and never claim full ChatGPT Plus parity from a generic MCP transport.

**Acceptance:** three-file round trip + corrupted/unsupported/quota/approval negative cases under authorized test account.

## PR-07 (P1) — Supported model/transport integration

- [ ] Integrate official Codex app-server where suitable and entitled, with persisted `turn/completed` notifications.
- [ ] Strict model/effort verification when a provider exposes it. GPT‑6 High must **not** be silently substituted by another model/effort.
- [ ] Explicitly record limitations of Sign in with ChatGPT preview (hosted ChatGPT connectors not automatically available).
- [ ] No blind rate-limit retries, quota bypass, CAPTCHA circumvention or automated consent.

**Acceptance:** capability mismatch yields 0 sends; controlled opt-in one-worker test supports safe recovery.

## PR-08 (P2) — Windows lifecycle and release

- [ ] Per-user Windows install/daemon, protected credential storage, no shared Chrome profile collision.
- [ ] Versioned SQLite migrations, backups and restore drill; secure local attachment storage / ACLs.
- [ ] Safe stop/resume and operator dashboard; log retention / sensitive-data redaction.
- [ ] 1/2/5-worker fault-injection test matrix, independent security/reliability audit.

**Acceptance:** full CI and reproducible Windows demo; no remote actions without user approvals.

## Non-negotiable product constraints

- Five **logical** slots are not a promise of five simultaneously available Plus webchat generations.
- A registered resource alias is an assertion, not provider permission; never allow a direct external write based on it alone.
- Exactly-once delivery cannot be asserted for a remote UI with no idempotency key; uncertain delivery stays quarantined.
- File snapshotting is not uploading; local receipt events are not ChatGPT hosted callbacks; no live product feature is considered done without provider-confirmed E2E proof.