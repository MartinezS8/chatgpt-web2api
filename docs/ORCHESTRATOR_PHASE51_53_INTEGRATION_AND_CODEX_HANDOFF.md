# Windows-only Codex handoff — PR #51–#53 integration, operator authentication and real-worker pilot gates

Date: 2026-10-22. Repository: MartinezS8/chatgpt-web2api.

## Exact current known branches

- Draft PR #50: `0b54a8c2bfdc3ed79463afe3d2f068a18c4a0576` (baseline; full hosted CI green).
- Draft PR #51: `a7b504814e4e6feb80c8b1868e59f6966511807c`, on #50. Read-only operator review board and CLI commands; no authentication.
- Draft PR #52: `ab3c4c412d0e39603799aa16dd879b0ea8ae7bee`, on #51. Disposable Windows second-user isolation probe; not yet independently run under an authorized second SID.
- Draft PR #53: `63668773e24cb27b6d3878af76cb23eb8bd08ebe`, **parallel alternative** to #51, on #50. Read-only `AppServerDeliveryLedger.triage()`; this PR is NOT in the #51 → #52 stack.

**Do not merge #53 and #51 blindly**. Compare APIs and tests; cherry-pick only nonduplicative guards if valuable and explicitly abandon the alternative after reconciliation. Do not retarget #52 without inspecting its full ancestry. `master` remains unchanged.

## Verified external blocker

GitHub Actions run `39806882415` for #52: 1387 pytest passed, 2 skipped, 20 subtests passed, **Ruff I001 failed** because of unsorted multiline import in `tests/test_orchestrator_worker_isolation_audit.py`. Wheel job skipped. A diagnostic comment was posted on PR #52. Fix this first, new exact-head Strict/Gitleaks/build/install/MCP passes required. Never claim a green acceptance gate from a red run.

PR #53 run `39819773483` was in progress at handoff: Gitleaks passed, Windows 3.12 strict was in progress. Verify final exact-SHA receipts and dependent build.

## Highest-priority engineering: finish 48c operator authorization

Current `record_operator_disposition` stores an **unauthenticated** hashed caller-supplied operator label. PR #51 and #53 remain read-only. Neither creates authority.

Codex Sol 6.1 owns architecture:
1. Threat model for local Windows 11 single-user controller with separate restricted worker SID. Decide trusted operator execution boundary and how its Windows token is independently verified; user-entered strings and env flags are NOT authentication.
2. Define immutable decision record (attempt ID, durable version, authenticated operator identity, decision nonce, independent provider evidence digest/source, recorded time, decision status).
3. Read-only preview and one-shot authenticated decision must both reject stale versions/replay; `BEGIN IMMEDIATE` CAS used for atomic state where appropriate. Existing closed attempt is NEVER replayed. `delivery_confirmed` remains non-retryable. `non_delivery_confirmed` can close only a reviewed case; a new attempt requires a separate task policy, explicit approval and audit.
4. All auth operations must refuse unsafe Windows accounts or insufficient ACL proof, not silently fall back to a mock operator label.
5. Negative tests: forged SID/ref, replay nonce, duplicate conflicting disposition, stale claim/version, missing evidence, partial outage, concurrent operators, restart before/after CAS, old attempt cannot send, fabricated terminal cannot finalize or approve.
6. No production dispatch until a separately reviewed gate allows it.

## Windows isolation diagnostic

Before any live task, use a **disposable synthetic workspace** with a pre-existing explicitly authorized restricted Windows user. Do NOT create Windows users, elevate privileges or modify real workspace ACLs without separate owner permission. Confirm effective read/list/append/create/rename/delete denied for the worker against controller DB, token directory and unrelated files; verify own worker worktree operations allowed. Check parent DELETE_CHILD rights, token SID, junctions, path swaps, child-process inheritance, network scope, process kill and no credential leakage. Distinguish restricted second-SID denial from the still-unresolved hostile same-SID TOCTOU case.

## Only then: one Codex App Server transport

- Windows 11 Pro, Python 3.12.x; `codex --version`, `codex app-server generate-json-schema`, compare current schema with synthetic protocol contract; inspect model/effort capabilities without silent fallback.
- No login or actual provider turn is authorized by this handoff. The user must expressly approve one benign test prompt, exact repo/worktree, permitted files, model, effort, network destinations, cost/limit and stop action before starting.
- Run isolated worker with no access to controller secrets. Durable intent and thread/turn correlation before write; if partial pipe write, dropped ack, kill or timeout -> unknown delivery, **no blind retry**. Inspect actual server behaviour carefully, no invented exactly-once.
- Live provider evidence must be segregated from synthetic receipt and from reviewer attestation.

## Gates 49, 50, 51

- 49: provider-attested GitHub repo/PR/HEAD/CI provenance, independent reviewer identity and versioned human finalizer; no self-approval and no auto-merge.
- 50: first two real worker contexts and distinct worktrees, then five; verify authentic per-session identity, isolation, quotas, pause/kill/recovery and cross-task callback rejection; keep actual model/effort confirmed, not asserted.
- 51: per-user Windows install, start/stop/status/doctor, secure credential storage, rollback, backup/restore rehearsal, redacted audit and user approvals; maintain Windows Python 3.12 only.
- ChatGPT Web UI with file uploads/apps/plugins is separate from Codex App Server and requires its own explicit feasibility/permission gate.

## Agent delegation

Sol 6.1: architecture, authenticated Windows identity, token isolation, finalizer, threat-review, integration. Luna Max: small disjoint unit-test fixtures, documentation, lint, exact-head CI receipts; never independently deploy, merge, approve, push or make live sends. No overlapping file edits.

## Required report

For each draft PR capture: base/head SHAs, commits, all files changed, exact Windows/Python 3.12 strict count, Ruff, Gitleaks, wheel/sdist+installed smoke, native restricted-SID denial evidence (if authorized) and unresolved risks. Status only PASS/PARTIAL/FAIL/NOT TESTED. Never merge to master automatically.