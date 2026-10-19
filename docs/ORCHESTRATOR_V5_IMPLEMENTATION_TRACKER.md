# Codex Orchestrator V5 — Implementation tracker (19 October 2026)

## Branches / upstream authority

This is a **stacked, unmerged** plan. Nothing is in `master` until individually reviewed and merged.

1. [PR #1](https://github.com/MartinezS8/chatgpt-web2api/pull/1): V3 transport-neutral task control plane → `master` (Draft).
2. [PR #2](https://github.com/MartinezS8/chatgpt-web2api/pull/2): V4 fenced lease / resource quarantine → PR #1 (Draft).
3. [PR #3](https://github.com/MartinezS8/chatgpt-web2api/pull/3): PR-02B resource authority → PR #2 (Draft).
4. [PR #4](https://github.com/MartinezS8/chatgpt-web2api/pull/4): PR-02C immutable packages and dispatch outbox → PR #3 (Draft).
5. [PR #5](https://github.com/MartinezS8/chatgpt-web2api/pull/5): PR-03 mock-only worker registry / bounded scheduler / supervisor → PR #4 (Draft).
6. [PR #6](https://github.com/MartinezS8/chatgpt-web2api/pull/6): offline callback/evidence/review mock ledger → PR #5 (Draft).
7. [PR #7](https://github.com/MartinezS8/chatgpt-web2api/pull/7): read-only Codex CLI/MCP observer → PR #6 (Draft).
8. [PR #8](https://github.com/MartinezS8/chatgpt-web2api/pull/8): sealed-package mock upload receipts and per-message app/model capability gate → PR #7 (Draft).
9. [PR #10](https://github.com/MartinezS8/chatgpt-web2api/pull/10): independent integration hardening for observer, worker recovery and mock upload preflight → PR #8 (Draft).
10. [PR #12](https://github.com/MartinezS8/chatgpt-web2api/pull/12): bind mock GitHub evidence to canonical task repository lock, require completed CI, redact callback messages → PR #10 (Draft).
11. [PR #14](https://github.com/MartinezS8/chatgpt-web2api/pull/14): independent mock reviewer identity, role, account, project and session constraints → PR #12 (Draft).
12. [PR #15](https://github.com/MartinezS8/chatgpt-web2api/pull/15): **disable untrusted assertion-only finalization**, prove unresolved write scopes stay locked; include latest PR #5 ancestry via a no-content-change merge → PR #14 (Draft).
13. [PR #16](https://github.com/MartinezS8/chatgpt-web2api/pull/16): **default-deny legacy Controller.dispatch/poll** unless explicitly called as an offline test, without exposing this testing flag over MCP → PR #15 (Draft).

**De-duplication:** PR #9 and PR #11 were competing PR-04 explorations and are closed without merge. The canonical chain is #1–#8 → #10 → #12. Do not auto-merge alternative callbacks/review implementations from PR #11. GitHub Actions and Issues are *not* blockers for continuing offline implementation; Codex can run the full suite later before merging.

**GitHub Issues are optional.** The owner prefers this Markdown tracker as the canonical backlog. GitHub Issues remain disabled and do not need to be enabled.

## Implemented in the current stacked code

**PR #12 safety patch (mock-only):** GitHub proof must match the task's canonical repository lock, a simulated successful CI run must also have `status=completed`, and local callback progress stores redacted messages. Three negative regression tests were added. Full Codex checkout tests are still required; do not mark these as live provider integrations.


- [x] Local SQLite WAL task store with pre-dispatch fencing; conservative unknown-delivery quarantine (PR #2).
- [x] Operator-asserted aliases for canonical GitHub numeric repository IDs, Supabase project references / environment, Vercel project IDs / environment; no provider permissions claimed (PR #3).
- [x] Local sealed prompts and SHA-256 attachment manifests / content-addressed snapshots (PR #4).
- [x] Local atomic dispatch intent and per-attempt event stream with per-consumer cursors; no auto re-send of an unknown attempt (PR #4).
- [x] Local command-line task registration, alias resolution, package seal/inspect, and event cursor operations (PR #4).
- [ ] End-to-end integration with an authorized live transport (not yet implemented).
- [ ] Real ChatGPT file uploads, hosted app/plugin selection, actual GPT-6 High proof, provider-verified permissions, and account-limit enforcement (not implemented).

## Canonical Codex handoff

[Codex offline validation and next-gates runbook](CODEX_NEXT_GATES_RUNBOOK.md) plus `scripts/verify_orchestrator.py` are the immediate local handoff. GitHub Actions and Issues may be handled by Codex later, per the repository owner's preference. **No live ChatGPT/Plus transport, plugin selection or file upload has been validated.**

## Gate 0 (P0) — CI, legal/technical capability and independent audit

**Owner action may be required:** GitHub REST reports zero Actions workflow runs for this fork. The workflow in `.github/workflows/ci.yml` currently triggers pushes to `master` and PRs against `master` only; nested stacked PRs are not covered by that condition. PR #1 also has no reported run, so configuration/permissions must be checked, not guessed.

- [ ] Check fork GitHub Actions settings / explicitly enable Actions if desired.
- [ ] Make workflow runnable against stacked branch PRs without merging; retain Linux/macOS/Windows, Python 3.11/3.12, pytest non-E2E, Ruff, Gitleaks, wheel check.
- [ ] Record exact SHA and URLs of passing workflows for PRs #1–#4.
- [ ] Independently audit P0 changes and the write-deny behavior.
- [ ] Document **authorized** transport route (official Codex app-server vs any separately authorized UI experiment). Do not treat browser automation as preapproved.

**Gate to pass:** provider write calls remain prohibited before authorization, and full test/CI evidence is green.

## PR-03 (P1) — Offline worker registry, scheduler, supervisor

**Implemented on `codex/orchestrator-v6-worker-scheduler` (Draft; not merged):** See [PR-03 technical notes](ORCHESTRATOR_PR03_WORKERS.md).

- [x] Stable logical worker IDs independent from slot numbers, browser targets, MCP session IDs and conversation IDs.
- [x] Per-account maximum five *registered logical workers*, unique session keys, mock-only enabled transport; a `stdio-singleton` does not become five web conversations.
- [x] Atomic SQLite-backed task/worker claim with project/role matching, dependency and globally shared resource locks; sealed-package preflight, no external dispatch.
- [x] Account scheduling pause/resume and bounded throttle; heartbeat storage and durable deduplicated stale-worker alerts.
- [x] Offline 1/2/5-worker, duplicate claim, multi-process and restart tests; 48 passed + 8 subtests with V4 fixtures.
- [ ] Provider-authenticated worker heartbeat; real session/target bindings and capability confirmation (only offline mock identities work).
- [ ] Supported remote stop/cancel, provider-backed reconciliation and automatic supervisor daemon with safe liveness policy (NOT implemented).
- [ ] Full V5/upstream suite + Windows CI and independently reviewed release gates (deferred for Codex phase).

**Acceptance so far:** no mock-worker claim collision; no unattended re-send; reproducible local worker registry on restart. **Do not describe this as live 5-agent ChatGPT support.**

## PR-04 (P1) — Offline callback, evidence, review and planning framework

**Implemented as a Draft PR stacked on PR #5:** [technical notes](ORCHESTRATOR_PR04_REVIEW_CALLBACKS.md).

- [x] SQLite-backed advisory callback inbox using exact attempt/worker/conversation/delivery/sequence correlation for **mock** workers. Replayed or conflicting progress rejected; only correlated outbox completion can be terminal.
- [x] SHA-bound simulated GitHub PR/CI evidence gate, immutable per task; any stale/wrong CI/run/head rejected. **Assurance: offline_mock_only; no live API call.**
- [x] Read-only review-task relationship checks, separate enabled mock review worker, fixed evidence/head and sealed review decision. **No production approvals.**
- [x] Idempotent and bounded fix *proposals* after 'changes_requested'; no automatic task claim/retry/writes.
- [x] 13 targeted local offline regression tests with V4 Store fixture.
- [ ] Trusted live callback provenance and authenticated external turn correlation; provider-retrieved GitHub commit/PR/CI evidence.
- [ ] Centralized production approval gate: legacy `Store.finalize_verified` still accepts operator assertion strings. Prevent alternate authorization paths before exposing externally.
- [ ] Automatic DAG task creation with reviewed scope handoff, policy checks, escalation and budgets.
- [ ] Full stacked/upstream tests, CI/Windows and independent release review (deferred).

**Acceptance so far:** mock-only duplicate/mismatched signals are rejected; simulated review/fix loop cannot authorize external effects. Real web callbacks/independent GitHub proof remain open.

## PR-05 (P1) — Low-token Codex CLI/MCP

**Partially implemented in [PR #7](https://github.com/MartinezS8/chatgpt-web2api/pull/7):** [observer notes](ORCHESTRATOR_PR05_OBSERVER.md).

- [x] Read-only Codex CLI/MCP state queries: status, bounded event/callback cursors, worker list, evidence, review and proposals. Same SQLite authority, protected read-only URI, prompts/claim tokens/session IDs redacted.
- [x] MCP tools are deliberately **read-only**; no hidden mutation tool in registry. 6 targeted local offline tests.
- [ ] Authenticated remote callback subscription, task submit/observe/reconcile, human-approved plan/merge, mutation tool authorization, stable error schemas.
- [ ] End-to-end mock-agent DAG demonstration with one authoritative control surface.
- [ ] Full MCP 1.26 handshake on real client, packaging, Ruff and Windows CI.

**Acceptance so far:** Codex can inspect fake-worker workflow data without side effects; cannot execute external actions.

## PR-06 (P1) — Attachments, skills and ChatGPT apps/plugins

**PR-06A offline mock readiness implemented as Draft:** [technical notes](ORCHESTRATOR_PR06_UPLOAD_PREFLIGHT.md).

- [x] Sealed `TaskPackages` manifest and content-addressed snapshot passed to a mock upload adapter; SHA/size/media-type + distinct fake receipt IDs checked; changed task reservation rejected after adapter work.
- [x] Explicit per-message app availability **and** selection and exact mock model/effort verified. Pending user approval blocks; mock-only `live_send_permitted=False`.
- [x] 11 targeted local tests, including partial/corrupted receipts, mismatched effort/model, unsupported app, user approval and race.
- [ ] Live authorized upload adapter and provider-acknowledged attachment IDs/hash verification, quotas and file-type handling; existing code is **NOT a ChatGPT upload**.
- [ ] Hosted plugin selection/permissions in a real account, user-mediated consent, skills upload, plan/modality parity testing.
- [ ] Full stacked tests/CI/Windows and real three-file approved E2E round trip.

**Acceptance so far:** simulated partial/mismatched upload cannot mark a task mock-ready; no real account actions.

## PR-07 (P1) — Supported model/transport integration

- [ ] Integrate official Codex app-server where suitable and entitled, with persisted `turn/completed` notifications.
- [ ] Strict model/effort verification when a provider exposes it. GPT‑6 High must **not** be silently substituted by another model/effort.
- [ ] Explicitly record limitations of Sign in with ChatGPT preview (hosted ChatGPT connectors not automatically available).
- [ ] No blind rate-limit retries, quota bypass, CAPTCHA circumvention or automated consent.

**Acceptance:** capability mismatch yields 0 sends; controlled opt-in one-worker test supports safe recovery.

## Independent stacked integration review (2026-10-19)

- [x] Review PR #5 worker pre-send reassignment; safe released-assignment upsert + regression in PR #5.
- [x] Identify and close duplicate PR #9; PR #6's callback/review implementation remains canonical.
- [x] Add follow-on PR-10 regression patches: sequential mock upload idempotency, deterministic Observer SQLite close, carry forward PR #5 scheduler fix on latest tip.
- [ ] Reconcile PR #6–#8 ancestry with latest PR #5 fix before integrated testing; current child branches were created before the fix.
- [ ] Provider-authenticated GitHub/CI/reviewer evidence and disabled legacy direct finalize before live use.
- [ ] Durable concurrent upload intent and unknown-remote-receipt reconciliation before any live upload transport.
- [ ] Execute full lint, integrated tests, Windows and upstream suite on exact final SHA.

See [integration review](ORCHESTRATOR_REVIEW_PR08_PR10.md). Issues and GitHub Actions configuration can be handled by Codex separately, as requested.

### Follow-up independent review identity gate (PR #14)

- [x] [Draft PR #14](https://github.com/MartinezS8/chatgpt-web2api/pull/14) additionally requires same-account, same-project and different-session reviewer/implementer workers, with both roles and enabled state checked.
- [x] Two negative regression cases committed for cross-account, project mismatch, shared session and disabled implementer.
- [ ] Run full stacked PR #1→#14 suite, Ruff and Python 3.11/3.12 Windows matrix. **No fresh CI run is claimed by PR #14.**
- [ ] Actual provider-signed review provenance, GitHub CI/PR HEAD revalidation, removal of legacy finalize bypass and authorized transport preflight remain mandatory.


## P0 follow-up review — fail-closed finalization (PR #15)

- [x] Disable `Store.finalize_verified` assertion-only approval path: it now always raises `PermissionError`, without releasing locks or advancing dependencies. See [PR-13 findings and implementation spec](ORCHESTRATOR_PR13_FINALIZATION_GATE.md).
- [x] Keep legacy tests honest: fake or privileged-sounding reviewer/operator strings no longer finalize; isolated V4 regression run **33 passed + 8 subtests**.
- [x] Synchronize latest PR #5 ancestry **in PR #15 descendant only** after verifying worker scheduler code and tests were blob-identical; PR #6–#14 still need merge-base checks.
- [ ] Build a *single trusted* provider-authenticated finalizer that compares current GitHub PR head, CI SHA/status, independent reviewer identity and required human approval immediately before a fenced SQLite transition. No automatic finish without this gate.
- [x] Guard `Controller.dispatch` and `Controller.poll` by default in PR #16, preserving only an explicit **local test mode**. The test flag is not a trustworthy production authorization mechanism and must never be wired to live MCP.
- [ ] Implement the single authorized, provider-attested dispatcher. Sealed TaskPackages/WorkerRegistry/DispatchOutbox must be the **exclusive** live path; verify no other code route can call a real transport.
- [ ] Full current PR #1→#15 combined tests, Ruff, Windows, Python 3.11/3.12 and upstream tests; current 33 tests are deliberately **not** claimed as complete integration evidence.

### Follow-up legacy dispatcher block (PR #16)

- [x] Default `Controller.dispatch`/`poll` aborts **before** claim/state change or transport call; offline tests explicitly opt in.
- [x] Focused local V4 tests **34 passed + 8 subtests**; Git blob SHAs for both changed files match tested local stage.
- [ ] Replace test-only bypass with a single authorized production command surface and non-replayable durable outbox send permit; do not offer `offline_test_mode` to agents.
- [ ] Full stacked PR #1→#16 CI/Windows/Ruff/real provider verification still not run.

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