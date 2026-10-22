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
14. [PR #17](https://github.com/MartinezS8/chatgpt-web2api/pull/17): durable per-file upload intents and persistent unknown-receipt quarantine (mock-only) → PR #16 (Draft).
15. [PR #18](https://github.com/MartinezS8/chatgpt-web2api/pull/18): wire existing mock preflight to atomic upload intents, fence replay and seal to current claim → PR #17 (Draft).
16. [PR #19](https://github.com/MartinezS8/chatgpt-web2api/pull/19): strict read-only GitHub PR/Actions evidence gate, no finalization permissions → PR #18 (Draft).
17. [PR #20](https://github.com/MartinezS8/chatgpt-web2api/pull/20): task/outbox/package-scoped immutable provider observation, with atomic post-GET race check; no state promotion → PR #19 (Draft).
18. [PR #21](https://github.com/MartinezS8/chatgpt-web2api/pull/21): read-only GitHub evidence restricted to trusted push events, same-repository head SHA and explicitly required successful CI jobs → PR #20 (Draft).
19. [PR #22](https://github.com/MartinezS8/chatgpt-web2api/pull/22): independent read-only GitHub reviewer permission/identity and SHA verification, no task finalization → PR #21 (Draft).
20. [PR #23](https://github.com/MartinezS8/chatgpt-web2api/pull/23): bind read-only GitHub reviewer observations to task/dispatch/CI snapshot/package/claim, preserving all locks → PR #22 (Draft).
21. [PR #24](https://github.com/MartinezS8/chatgpt-web2api/pull/24): signed GitHub PR-HEAD commit metadata plus active mock-worker/claim attribution, read-only and not an authenticated remote session → PR #23 (Draft).
22. [PR #25](https://github.com/MartinezS8/chatgpt-web2api/pull/25): operator-pinned workflow file provenance, with exact commit blob SHA, no merge permission → PR #24 (Draft).
23. [PR #26](https://github.com/MartinezS8/chatgpt-web2api/pull/26): persist pinned CI workflow blob in fenced task evidence and transitive review digests; preserve legacy read-only receipts → PR #25 (Draft).
24. [PR #27](https://github.com/MartinezS8/chatgpt-web2api/pull/27): verify local tests against exact clean Git HEAD, fail closed on mismatch, distinguish smoke from complete local verification → PR #26 (Draft).
25. [PR #28](https://github.com/MartinezS8/chatgpt-web2api/pull/28): close post-test checkout TOCTOU and inherited Git/pytest environment override paths → PR #27 (Draft).
26. [PR #29](https://github.com/MartinezS8/chatgpt-web2api/pull/29): read-only feature branch CI with 6 system/Python cells → PR #28 (Draft).
27. [PR #30](https://github.com/MartinezS8/chatgpt-web2api/pull/30): repair CI contract, disabled-worker checks, upload fencing and Windows SQLite cleanup → PR #29 (Draft).
28. [PR #31](https://github.com/MartinezS8/chatgpt-web2api/pull/31): close error-message regression and stage audited Ruff cleanups → PR #30 (Draft).
29. **PR #32 (this branch)**: restore Pytest fixture registrations removed by F401, resolve remaining Ruff errors, and retest matrix → PR #31 (Draft).

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

## PR-15 (P0) — Durable upload intent groundwork

- [x] `UploadIntents.reserve()`: one SQLite-fenced upload attempt per task, sealed package SHA binding and mock worker/claim identity.
- [x] `reserve_next()`: one pending-to-inflight per-file intent at a time, atomically; no concurrent duplicate reservation.
- [x] `acknowledge()`: size, MIME, digest and unique fake remote-ID validation before mock-ready state.
- [x] `quarantine()`: unknown results never become automatic permission to retry or release a task write lock.
- [x] 10 offline unit tests pass on Python 3.13, including 16 concurrent claim and per-file reservation attempts; full assembled suite/CI not run.
- [x] **PR #18:** integration implemented on this descendant: `UploadPreflight.check_mock` uses `UploadIntents.perform_mock`; exact claim-bound replay and final seal checked transactionally. Three integration regression cases added.
- [ ] **Verification:** full assembled integration tests, Ruff and Windows CI not run; do not attach a live provider without authenticated receipt/identity adapter.
- [ ] Live adapters: provider-authenticated file IDs, upload completion/size/hash proof, worker capabilities, quotas, user approval and active message/app selection; all remain unavailable.

See [PR-15 durable upload intents](ORCHESTRATOR_PR15_UPLOAD_INTENTS.md). Keeping GitHub Issues/Actions optional for Codex phase does not waive review and release tests.

### PR-16 (P0) — Mock UploadPreflight integration

- [x] Atomic upload intent before each mock upload side effect, one concurrent uploader per task.
- [x] Unknown receipt → quarantine; repeated preflight never uploads again without provider/manual reconciliation.
- [x] Exact claim and package revalidated on replay and inside final persistence transaction.
- [x] 3 negative/parallel integration tests committed; **not yet executed on entire current PR stack**.
- [ ] Provider-certified remote receipt/approval and real quota checks; keep `live_send_permitted=False`.

See [PR-16 integration details](ORCHESTRATOR_PR16_UPLOAD_INTEGRATION.md).

## PR-17 (P0) — GitHub provider read-only evidence, Draft PR #19

- [x] Implement `github_readonly_evidence.py` with a restricted GitHub REST GET reader (no redirects; no arbitrary paths; bounded response and timeout; optional explicitly injected token).
- [x] Verify canonical repository ID, open/unmerged PR head SHA, trusted workflow ID, completed/successful run and matching run SHA.
- [x] Re-read PR head **after** workflow fetch; reject changed heads instead of treating a stale successful run as current proof.
- [x] 25 isolated Python 3.13 offline tests + Python compile check; Git blob SHAs for committed source/test match exact local test files.
- [x] Independently read current fork API metadata through connected GitHub: numeric repository ID **1424862141**, PR #18 baseline repository ID identical, head **77cbef03b739d6682704701040335112f852b83f** at inspection.
- [ ] Real API execution of the new adapter with valid credentials/allowed workflow; this fork currently has no confirmed successful workflow run and this cannot be claimed as successful CI evidence.
- [ ] Provider-authorized task/evidence binding, trustworthy reviewer attestation and current-SHA revalidation at final CAS; adapter returns `production_finalization_permitted=False` by design.
- [ ] Full stacked suite, Ruff, Python 3.11/3.12 + Windows, upstream integration tests before merge. Ruff not installed in the local creation environment.

See [PR-17 provider adapter design](ORCHESTRATOR_PR17_GITHUB_READONLY_EVIDENCE.md). This feature does **not** send messages to ChatGPT, select apps, upload files or approve merges.

## PR-18 (P0) — Task-bound GitHub provider observations, Draft PR #20

- [x] New `provider_evidence.py` binds the existing PR #19 read-only provider reader to a specific `task_id`, completed `attempt_id`, sealed package SHA, hashed result reference and claimed repository write scope.
- [x] Reject missing/rotated claim, changing task/outbox/package while GitHub is queried, wrong resource, unsuccessful CI, moved PR head, stale receipt or substituted dispatch ID.
- [x] SQLite transactional immutable digest, read-only/unauthorized assurance, no automatic `verified`/`finished` transition, no write-lock release or merge.
- [x] 46 targeted tests plus a local staged V4/PR04 suite totaling **106 passed + 8 subtests** on Python 3.13; committed adapter source/test Git blob SHAs match locally tested originals. This is **not** a complete current GitHub checkout.
- [ ] Run full assembled PR stack / upstream suite / Ruff / Windows; real configured provider adapter with approved workflow and operator credentials remains untested.
- [ ] Restrict allowed workflow triggers and required CI jobs/checks; a green run alone is not user approval or independent reviewer attestation.
- [ ] Build provider-attested independent review and a **separate trusted finalizer** with fresh current SHA, user consent and atomic state transition; current `ProviderEvidenceLedger.production_finalization_permitted()` always returns False.

See [PR-18 task-bound provider design](ORCHESTRATOR_PR18_PROVIDER_EVIDENCE_BINDING.md). Uploads, callbacks, ChatGPT models/apps and any production transport remain distinct unfinished gates.

## PR-19 (P0) — CI workflow trigger, head source and required-job policy (PR #21)

- [x] Mandatory trusted job-name allowlist passed via controller-owned `required_job_names`; reject missing, duplicated, failed, stale and incomplete/paginated jobs.
- [x] Only accept exact `push` event on the reviewed PR's branch SHA, from the same trusted numeric repository ID. `workflow_dispatch` and `pull_request` refuse until separate event-specific provenance verification is implemented.
- [x] GitHub REST reader limited to exact run + latest-attempt jobs endpoint; no arbitrary query parameters, redirects or write actions.
- [x] Recheck PR head after job inspection. Read-only result has **no** finalization or send permissions.
- [x] Local focused and V4/PR04/provider staged regression run: **119 passed, 8 subtests**; Python compile check green. Full stacked checkout/Windows/Ruff/live API are **not** verified.
- [ ] Current `.github/workflows/ci.yml` triggers push on `master` only, and PR against `master` only; no qualifying push job for stacked feature branches. Codex/owner must define a secure branch workflow and validate it rather than relaxing proof.
- [ ] Pin/protect workflow source, required jobs/check policy and workflow permissions; do not infer trust solely from a successful run on agent-modifiable workflow code.
- [ ] Provider-attested reviewer identity + transactional finalizer and actual authorized transport remain separate unimplemented gates.

See [PR-19 GitHub CI hardening](ORCHESTRATOR_PR19_CI_EVENT_AND_JOBS_POLICY.md). The constructor of `GitHubReadOnlyEvidence` now requires `required_job_names`; callers must pass the trusted configured policy.

## PR-20 (P0) — GitHub read-only reviewer identity and commit attestation (PR #22)

- [x] Provider GET-only review observer `github_readonly_reviews.py`; read exact repository, PR, review list and collaborator permission API endpoints.
- [x] Operator-controlled numeric GitHub reviewer ID allowlist and approval threshold; PR author and trusted implementation worker are always ineligible. Reviewer must have current write/admin permission, same immutable user ID.
- [x] Require approved review for the exact current SHA; reject open change requests, dismissed/stale approvals, draft/closed/moved PR, untrusted reviewer or incomplete/100-entry history.
- [x] Recheck PR HEAD after fetching reviews and permissions; **no** production finalization, merge permission, or external action.
- [x] **53 new offline tests**; combined staged V4/PR04/provider/CI/review regression suite **174 tests + 8 subtests**, Python 3.13/Linux. GitHub source and test blobs match exact tested bytes; no full assembled checkout, Ruff or Windows CI claimed.
- [x] Actual GitHub connected read confirmed **zero submitted reviews on PR #21**, so successful live-review assurance is currently unavailable and must not be fabricated.
- [ ] **P0 next:** bind the new read-only review observation to a specific `ProviderEvidenceLedger` task/attempt/package/commit and independently authenticated implementer GitHub identity, then require fresh finalization-bound revalidation.
- [ ] Workflow-source provenance, real provider-backed reviewers and signed/authorized task finalization, full-stack Ruff/Windows/3.11/3.12 tests remain pending.
- [ ] No live ChatGPT Plus plugin/app, file upload, verified GPT-6 High selection or agent transport is implied.

See [PR-20 technical review](ORCHESTRATOR_PR20_READONLY_REVIEW_VERIFICATION.md). As requested, GitHub Issues are not required; Codex can consume this Markdown tracker directly.

## PR-21 (P0) — Task-bound immutable reviewer observations (PR #23)

- [x] New `task_review_evidence.py` records immutable review receipt on the same SQLite authority as tasks/outbox/CI observations, keyed by a specific task and completed attempt, canonical repository ID, current PR SHA, sealed package digest, trusted numeric implementer and GitHub reviewer/review IDs.
- [x] Existing CI observation digest and freshness checked against current task/attempt claim BEFORE remote review; after provider reads a single `BEGIN IMMEDIATE` transaction rechecks task, package, claim and CI proof before recording.
- [x] Reject unrelated attempts, stale/altered CI proof, revoked reviewer permission, duplicate/replayed review, changed PR head, changed task/claim during network reads. Retain existing task state and resource locks.
- [x] **98 local staged offline tests** (24 new task-review cases + 74 existing CI/review adapter tests), Linux/Python 3.13. New code/test/document SHA verified exactly against staged files; full cumulative repo suite/Ruff/Windows CI not run.
- [ ] Authenticate the implementer GitHub identity independently from operator configuration and bind it to the real worker, code author and authorization scope.
- [ ] Verify workflow provenance from protected, trusted CI source and recheck PR SHA/reviewer permissions **at the future finalizer decision**, not from previously saved snapshots.
- [ ] Provider-authorized task finalizer, human consent and single authorized dispatcher remain unimplemented; `production_finalization_permitted=False` by design.
- [ ] Real ChatGPT Plus plugin selection, file upload, GPT-6 High proof and live callback/session transport remain separate unfinished gates.

See [PR-21 task-bound review evidence design](ORCHESTRATOR_PR21_TASK_BOUND_REVIEWS.md).

## PR-22 (P0) — Signed GitHub commit and local mock-worker correlation (PR #24)

- [x] Constrained GET-only GitHub commit endpoint; strict same-repo open PR and HEAD before/after; require trusted numeric author AND committer GitHub IDs and GitHub-verified valid commit signature.
- [x] Durable mock-worker attribution ledger bound to the exact task, completed attempt, fresh CI and review digests, sealed package, current claim token hash and active worker assignment; recheck all local state in a write transaction after GitHub reads.
- [x] Scheduler assignment version is from reservation, while task state transitions advance task version: allow earlier positive assignment version (not zero/future), retain strong attempt/claim/package matching and reject reassignment.
- [x] **129 staged offline tests** including 31 new attribution cases and 98 existing CI/review/provider tests; Python 3.13/Linux; source/test files match locally tested Git blobs. No complete assembled GitHub checkout, Windows CI or Ruff.
- [ ] **Provider-authenticated worker-to-GitHub actor linkage remains unavailable.** The local worker is `mock` and a protected operator mapping is not proof of a real remote Codex/ChatGPT session. Signed commit metadata alone cannot authenticate the real worker. Never enable production finalization from this observation.
- [ ] Protected CI workflow version, verified provider reviewer identity on current SHA, explicit user consent, fresh finalizer-bound CAS and single authorized dispatcher remain P0 release gates.
- [ ] Real attachments, plugins/apps, model High and live callback/session transport remain separate incomplete integrations.

See [PR-22 commit and worker correlation design](ORCHESTRATOR_PR22_IMPLEMENTER_COMMIT_CORRELATION.md). `production_finalization_permitted=False` is invariant.

## PR-23 (P0) — GitHub CI workflow source pin, Draft PR #25

- [x] New workflow-source pin checks run repository/workflow/HEAD, active workflow registration, and the HEAD-specific YAML Git blob SHA against independent controller policy.
- [x] Restricted GET-only endpoints for workflow metadata and exact SHA-pinned workflow file content; recompute Git SHA-1 from decoded source bytes; no arbitrary URL, redirects or writable actions.
- [x] Existing CI reader optionally requires this configured pin, and receipt marks source SHA only when checked. Legacy unpinned receipts report workflow_blob_sha=None; neither kind grants finalization.
- [x] 35 local unit cases passed Python 3.13/Linux for the standalone pin module. Five extra adapter integration tests committed but not run on exact cumulative source.
- [ ] P0: full stacked PR tests/Ruff/Windows and Python 3.11/3.12; do not claim green CI. Current fork has zero workflow runs.
- [ ] P0: branch protection not verified (GitHub protection endpoint 403, rulesets empty). Approved workflow pin must come from trusted owner policy, not an agent-editable branch.
- [ ] P0: mutable actions, external downloads and tested checkout code must be audited; workflow YAML equality alone is not complete supply-chain attestation.
- [ ] P0: persist pin in task CI evidence digest and recheck source, current SHA, review permission and explicit user consent at trusted finalizer action boundary.
- [ ] P1: live supported transport, file uploads, callbacks, app selection and High model verification remain unimplemented.

Details: [PR-23 workflow provenance design](ORCHESTRATOR_PR23_WORKFLOW_SOURCE_PIN.md).

## PR-24 (P0) — Task-bound workflow source pin evidence (Draft PR #26)

- [x] Seal verified workflow source SHA into `orchestrator_provider_observations`, plus task/attempt/package/claim/CI digest; prohibit fake pins from unpinned gates.
- [x] Add `BEGIN IMMEDIATE` protected SQLite additive migration; old unpinned digests preserved, but old receipts cannot satisfy a newly enforced pin policy.
- [x] Bind source SHA into `TaskReviewEvidenceLedger` CI verification and downstream implementer review snapshots; tampered or stale pin fails before external reviewer reads.
- [x] Add offline pinned/migration/review regression tests and scoped design note; **committed, not executed** on the actual stacked checkout.
- [ ] P0: run exact PR #1–#26 stacked checkout tests, Ruff, package build and Windows/Linux/macOS Python 3.11/3.12 checks; GitHub Actions feature-branch run count is unconfirmed and was zero at last check.
- [ ] P0: external CI dependencies remain mutable; an approved protected source plus human approval, authenticated worker and atomic finalizer are still missing.
- [ ] P1: verified live transport and ChatGPT-web model/app/file semantics remain unimplemented; this is audit-only.

See [PR-24 pinned CI evidence ledger](ORCHESTRATOR_PR24_TASK_CI_WORKFLOW_PIN_LEDGER.md). A signed commit, CI success or a mock worker cannot grant live send, merge, task completion or lock-release authority.

## PR-25 (P0) — Reproducible local verification of exact Git HEAD (Draft PR #27)

- [x] Expand `scripts/verify_orchestrator.py` with expected 40-hex SHA, Git-root check, clean tracked/untracked working tree and strict fail-closed preflight before test subprocesses.
- [x] `--full --strict` requires compileall, full non-E2E pytest and Ruff. Development `--skip-lint` is explicitly incomplete, not a successful full gate.
- [x] Force E2E opt-in off in child test process; emit no raw test stdout/stderr unless `--diagnostics` explicitly requested. Report `network_isolation_verified=false` rather than claiming network impossibility.
- [x] Seven isolated local verification tests passed Python 3.13/Linux using temporary Git repositories and mock test processes. Tested source/test Git blob SHAs matched GitHub.
- [ ] P0: run exact stacked HEAD full suite with `--expected-sha`, `--full`, `--strict`; independent Windows/macOS/Linux Python 3.11/3.12 matrix + GitHub checks still unproven (0 workflow runs on fork at review).
- [ ] P0: trusted protected CI policy, independent reviewers and live authenticated worker identity before any task finalizer.
- [ ] P1: only authorized supportable transport; no ChatGPT Plus automated web sends, model/plugin selection or file uploads enabled.

See [PR-25 reproducible verification](ORCHESTRATOR_PR25_REPRODUCIBLE_VERIFICATION.md). `local_gate_complete` is a **local smoke/integration assertion**, never a signed CI or user authorization.

## PR-26 (P0) — Postflight Git identity and pytest environment fencing (Draft PR #28)

- [x] Review finding: prior strict test gate only checked Git HEAD/worktree before execution. A process could change tested files or move HEAD and still receive a green local-gate receipt.
- [x] Re-run Git root, expected HEAD and strict tracked/untracked-clean checks **after** all checks. Postflight failure overrides subprocess zero exit codes with `ok=false`, `local_gate_complete=false`.
- [x] Remove inherited pytest selectors/plugins and unrelated `PYTHONPATH` from test subprocess environment; clear inherited `GIT_*` in Git identity checks. Use no pytest cache provider to minimize repository writes.
- [x] New tests cover source mutation, moved HEAD, Git env override, pytest injection and failed Git postflight, extending local unit suite to twelve test functions. **Not executed in exact stacked checkout in this session.**
- [ ] P0: exact checkout full suite and Ruff, Python 3.11/3.12 × Linux/Windows/macOS; full offline local evidence still unverified.
- [ ] P0: implement eligible but owner-trusted CI branch workflow without trusting agent-editable YAML, mutable action tags or unreviewed runner policy.
- [ ] P0: authenticated worker identity, reviewed current SHA and human-approved transactional finalizer still blocked. No live ChatGPT Plus web automation, plugin control or uploads.

See [PR-26 verifier postflight and environment design](ORCHESTRATOR_PR26_VERIFIER_TOCTOU_ENV_FENCING.md).

## PR-27 (P0) — Stacked-branch CI diagnostics (Draft PR #29)

- [x] Source review: prior `.github/workflows/ci.yml` only targeted `master`; stacked `codex/orchestrator-*` pushes had **zero** workflow runs, making all full test evidence unverified.
- [x] Add separate push-only `.github/workflows/orchestrator-branch-validation.yml` with `contents: read`, no checkout credentials, full Git SHA pins for `actions/checkout@v4.2.2` and `actions/setup-python@v5.6.0`; six OS/Python combinations and a conditional package build.
- [x] GitHub began creating actual feature-branch Actions runs. Initial diagnostic run 39327764123 confirmed real **pytest collection failure (4 unresolved sibling-module imports)** and **Ruff 115 violations** across the current checkout. Do not call matrix green.
- [x] Adjust strict verifier `PYTHONPATH` to pinned `src` **and** `tests` for actual cross-test helper imports; update regression expectation. Add five static workflow safety-contract tests.
- [ ] P0: inspect rerun after the import fix, repair verified test failures; full matrix, Ruff and wheel build remain unsatisfied until GitHub records passing evidence.
- [ ] P0: fix or explicitly baseline repository-wide Ruff debt under reviewed policy; never silently disable lint or claim a passing gate.
- [ ] P0: diagnostics workflow YAML lives on feature branch and can be edited by that branch. It is **not** a protected/approved CI source and must never satisfy task finalizer or operator permission checks.
- [ ] P0: GitHub hosted runner/PyPI dependency provenance, protected workflow pin, reviewer/worker identity, explicit consent and finalizer remain separate blockers.

See [PR-27 branch validation diagnostics](ORCHESTRATOR_PR27_BRANCH_CI_DIAGNOSTICS.md).

## PR-28 (P0) — CI full-suite regressions repaired (Draft PR #30)

- [x] Github Actions exact PR #29 HEAD `497e13cb586364cbe10195de0815dcc6fc05ca1e` reached complete non-E2E pytest on 6 Linux/macOS/Windows + Python 3.11/3.12 runners, showing **1048 passed / 3 failed** on Linux and macOS, **1047 passed / 4 failed** on Windows. 20 additional subtests passed.
- [x] Fix developer workflow contract assertion to allow bounded `--diagnostics` without weakening `--full --strict --expected-sha` requirements.
- [x] Separate disabled reviewer or implementer into explicit fail-closed check, with parameterized negative tests and assurance no decision is persisted.
- [x] Keep claim-token mismatch rejected by durable upload intent; align stale-receipt test to actual assertion and verify no second upload.
- [x] Close SQLite legacy test creation handle explicitly after commit, so Windows temp-file cleanup can succeed.
- [ ] P0: re-run all 6 CI matrix cells on exact latest SHA; no successful suite claimed before results.
- [ ] P0: Ruff still reports 115 violations in baseline; do not disable lint. Audit and fix, then require clean full matrix and artifact build.
- [ ] P0: diagnostics is not protected/owner-trusted workflow evidence and cannot authorize provider actions.

See [PR-28 CI test repairs](ORCHESTRATOR_PR28_CI_TEST_FAILURE_REPAIRS.md).

## PR-29 (P0) — Full offline tests green, Ruff source debt being reduced (Draft PR #31)

- [x] Exact SHA `c044c1348380daed259da4b37d08fac88ba7b848` in diagnostic Actions run [39331259834](https://github.com/MartinezS8/chatgpt-web2api/actions/runs/39331259834): **1052 passed + 20 subtests** on each of Linux/Windows/macOS Python 3.11 and 3.12, postflight clean and expected HEAD matched. No E2E tests (31 deselected).
- [x] Fix remaining regression `test_reviewer_rejects_disabled_or_cross_project_implementer` by checking fail-closed enabled-worker rejection and no saved decision; mock security policy unchanged.
- [x] Run nonmutating Ruff inventory: exactly **115** findings with rule counts E701=45, F811=25, I001=15, F401=14, UP035=6, E702=5, F841=3, UP017=1, UP042=1. `ruff check --fix --diff` showed 23 file patches/28 hunks with 44 proposed safe changes and no unsafe-fix opt-in.
- [x] Against the pinned source, validate each context/delete/add hunk against the original GitHub contents and stage the resulting 23 exact Git blobs in one atomic reviewed PR commit. No CI-driven write or automatic unsafe lint refactor.
- [ ] P0: confirm `pytest`, Ruff and package build on the **new** commit. Remaining E701/F811/E702 and other lint findings must be resolved without disabling rules.
- [ ] P0: this diagnostic workflow remains branch-editable/untrusted, not protected CI or live permission. No merge or provider actions authorized.

See [PR-29 Ruff debt audit](ORCHESTRATOR_PR29_RUFF_SAFE_FIX_AUDIT.md).

## PR-30 (P0) — Fixture recovery and remaining lint cleanup (Draft PR #32)

- [x] Review exact PR #31 HEAD `e28c368375409d3ff4a955fa59bb8c1d1cc8dbef`: [Actions run 39332816766](https://github.com/MartinezS8/chatgpt-web2api/actions/runs/39332816766) had **988 passed, 64 test setup errors and 20 passing subtests** on six OS/Python combinations, with 53 Ruff errors and no artifact build.
- [x] Root cause: Ruff F401 'safe' removal deleted `store` imports acting as Pytest fixture registrations across three test modules. Re-export `store as store` explicitly and add cross-module fixture regression test.
- [x] Rewrite identified 45 E701 and 5 E702 one-line constructs, preserve two F841 side-effect decisions and use Python 3.11 StrEnum for UP042 **while explicitly retaining Enum's previous `__str__` representation**; add JSON/string compatibility regression.
- [ ] P0: **zero success assumed** until GitHub Actions exact new SHA proves all tests, postflight, Ruff and package build; check compat of `str(TaskState)` on released consumers.
- [ ] P0: branch-controlled CI remains only untrusted diagnostics, not operator approval or authenticated live ChatGPT provider capability.

See [PR-30 fixture and lint recovery](ORCHESTRATOR_PR30_FIXTURE_LINT_RECOVERY.md).

## PR-31 (P0) — Windows readiness integration (Draft PR #33)

- [x] Take the **two original Windows commits unchanged** from `codex/local-windows-readiness-2026-10-20`, exact HEAD `c7e9932caeaac383d013f8f821df567d2218d23c`, into a new `codex/orchestrator-v31-windows-readiness` branch stacked on PR #32.
- [x] Local Codex report (not GitHub-attested) states Python 3.11/3.12 **1058 tests and 20 subtests** each, clean Ruff and build, MCP handshake, 14/14 mock scenarios. 31 live account E2E tests intentionally excluded.
- [x] Creating the matching branch triggered developer diagnostics GitHub Actions run [39415583339](https://github.com/MartinezS8/chatgpt-web2api/actions/runs/39415583339).
- [ ] P0: Check **six** OS/Python results, exact commit, strict postflight and dependent wheel build. Workflow is editable and **untrusted**, never an owner-approved CI gate.
- [ ] P0: Independent Windows ACL enforcement, fail-safe SQLite migration/integrity check and crash/partial-write recovery remain unverified; real workers prohibited.

## PR-32 (P0) — Assignment-bound offline mock dispatch (Draft PR #34)

- [x] Add `DispatchOutbox.begin_mock_for_assignment(task_id,worker_id,claim_token)` without changing existing mock-only legacy behavior. A single immediate SQLite transaction checks *active* assignment, matching enabled mock worker, project/role, claim version, sealed package, token and unexpired lease before **one** dispatch intent.
- [x] Refuse wrong/missing, disabled, released, wrong-role, stale-version or expired worker bindings without creating an intent; repeated same-claim invocation never generates a second permit. All receipts explicitly say `remote_send_permitted=False`.
- [ ] P0: Verify full strict matrix and package build on the **new exact SHA**, including the focused negative/race tests.
- [ ] P0: This is strictly mock-only. Any future live dispatcher MUST recheck the worker assignment at the actual provider-send boundary, protect authorization with a trusted transport, and quarantine unknown sends; this method does not make that possible by itself.
- [ ] P0: Versioned SQLite migrations, OS ACLs, after-crash recovery tests, and trusted CI are separate follow-ups.

See [PR-32 assignment-bound mock outbox design](ORCHESTRATOR_PR32_ASSIGNMENT_BOUND_MOCK_OUTBOX.md).

## PR-33 (P0) — Local storage integrity and opt-in Windows ACL setup (Draft PR #35)

- [x] Create a new stacked development branch `codex/local-v33-storage-hardening-no-ci` on PR #34's exact HEAD. The branch is intentionally **outside** the `codex/orchestrator-*` push trigger; no GitHub CI is to be requested or executed for this task.
- [x] Make Store V3→v2 schema upgrades one SQLite `BEGIN IMMEDIATE` transaction; record `orchestrator_schema_versions(task-store=2)`, quarantine ambiguous V3 active reservations and reject unknown future versions.
- [x] Check `PRAGMA quick_check` and `PRAGMA foreign_key_check` before schema writes; recheck FK after migration; rollback the metadata/DDL/quarantine together on error.
- [x] Add explicit `init-private-workspace --label ...` on Windows for **new** empty workspaces only, using current account SID, shell-free `icacls` inheritance removal, private SID + SYSTEM grants and canonical ACL verification. Existing directories are never rewritten.
- [x] Add local no-clobber same-directory SQLite online snapshot/backup CLI and regression tests for interrupted migrations, uncommitted transaction process exit, broken foreign keys, staging file cleanup, backup collisions and ACL command safety.
- [ ] P0: Execute new focused and full offline tests **locally on a trusted Windows host** with Python 3.11/3.12; inspect Ruff and verify actual ACL entries/effective access on Windows. No CI was run by request.
- [ ] P0: An explicit protected-workspace provisioning path is not a blanket guarantee over legacy SQLite/attachment paths; validate permission inheritance, reparse guards, same-volume link capability and backup/restore drill.
- [ ] P0: Future provider transport and finalizer remain disabled; branch-controlled test output cannot authorize remote sends.

See [PR-33 storage hardening design](ORCHESTRATOR_PR33_STORAGE_HARDENING.md).

## PR-34 (P0/P1) — Cooperative crash staging & source identity (Draft PR #36)

- [x] Read PR #35 exact source SHA `757df4a48d148d85bb280013e020c59672127766`; do not treat 1099 local Windows tests as hosted evidence until independently confirmed.
- [x] Add `stage_maintenance` with permanent per-directory cross-process OS lock, V2-only named staging files and default read-only inspection. Cleanup only on explicit request after the exclusive lock; old unknown `.staged-*` / `.sqlite-snapshot-*` files are **never** deleted automatically.
- [x] Update TaskPackages and SQLite online-backup staged writes to hold the cooperative lock for their *entire* staging/publication lifetime and leave no repeated remote operation.
- [x] Reject attachment source replacement after preflight by comparing `fstat` file identity/size/mtime with the initial file stat; retain allow-root/junction checks. This detects common substitutions but **does not claim full Win32 handle-based TOCTOU protection** against a malicious process that can rename trusted directories.
- [x] Add hard-process-exit, active writer, legacy-preservation, concurrency, source swap and local CLI opt-in regression tests. Windows >260-char path diagnostic is a separately reported runner capability; not an unconditional product guarantee.
- [ ] P0: Verify exact HEAD with all six Python/OS strict, non-E2E workflow checks and dependent package build on current feature branch; actual counts and failures must come from CI receipts.
- [ ] P0: A second-account effective Windows ACL read/write/dir-list denial requires a separate native throwaway test user; **NOT TESTED** in this implementation. Win32-native handle-relative open and path invariance also remain separate before any untrusted shared-root use.
- [ ] P0: No live remote transports, app/plugin selection, callback authentication or production finalizer.

See [PR-34 staging recovery and path-race limitations](ORCHESTRATOR_PR34_STAGE_RECOVERY_SECURITY.md).

## PR-08 (P2) — Windows lifecycle and release

- [ ] Per-user Windows install/daemon, protected credential storage, no shared Chrome profile collision.
- [ ] Versioned SQLite migrations, backups and restore drill; secure local attachment storage / ACLs.
- [ ] Safe stop/resume and operator dashboard; log retention / sensitive-data redaction.
- [ ] 1/2/5-worker fault-injection test matrix, independent security/reliability audit.

**Acceptance:** full CI and reproducible Windows demo; no remote actions without user approvals.

## Non-negotiable product constraints

Windows main-file pin follow-up: see
[native lifetime and limitations](ORCHESTRATOR_WINDOWS_DATABASE_PIN.md).
Protected Store, Observer and backup source connections share a native pin
session. Main-file/direct-parent delete denial is separate from the still-open
hostile ancestor/sidecar/publication races and second-user acceptance gates.

Protected storage boundary follow-up: see
[policy contract](ORCHESTRATOR_PROTECTED_STORAGE_BOUNDARY.md). Explicit native
policy now propagates to library Store/Packages, mock services, staging/backup
and the observer MCP route. `Store.storage_mode` distinguishes legacy from
protected-private. Hostile concurrent path replacement and effective
second-user ACL denial remain open acceptance gates; no real-worker readiness
is implied by branch diagnostics.

- Five **logical** slots are not a promise of five simultaneously available Plus webchat generations.
- A registered resource alias is an assertion, not provider permission; never allow a direct external write based on it alone.
- Exactly-once delivery cannot be asserted for a remote UI with no idempotency key; uncertain delivery stays quarantined.
- File snapshotting is not uploading; local receipt events are not ChatGPT hosted callbacks; no live product feature is considered done without provider-confirmed E2E proof.

## Phase 48c — Durable offline App Server delivery (local development branch)

- [x] Add a separately versioned SQLite ledger bound to the existing unique dispatch attempt, recording immutable worker/account/project/task/attempt, package, claim/version, prompt-hash, request, thread and turn correlation.
- [x] Commit send intent before each synthetic JSONL write; persist post-flush writes and contract-validated acknowledgements; include the `initialized` notification in the journal.
- [x] Recover interrupted attempts into no-retry quarantine; successful fake turns remain `transport_completed_unverified` / `offline_simulated_unverified` and leave tasks `needs_human` with no result evidence or approval.
- [x] Add bounded read-only MCP status for delivery metadata and an append-only, non-authorizing operator annotation.
- [x] Add synthetic negative and crash-boundary regressions, including no second `turn/start` after recovery.
- [ ] P0: Exact-head local strict Windows/Python 3.12 run, wheel/sdist build/install smoke and exact-head Draft PR CI receipts.
- [ ] P0: Authenticated operator resolution/release semantics are intentionally not implemented; hostile same-user TOCTOU remains **FAIL** and effective second-user ACL denial remains **NOT TESTED**.
- [ ] P0: No real app-server transport, real worker, or live provider authorization; Phase 48d requires fresh, specific approval and a separately proven sandbox.

See [Phase 48c durable delivery ledger](ORCHESTRATOR_PHASE48C_DURABLE_DELIVERY.md).
