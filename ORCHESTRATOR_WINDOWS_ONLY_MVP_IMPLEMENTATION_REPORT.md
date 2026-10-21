# Windows-only orchestrator implementation report

## Authority and scope

Specification: `CODEX_SOL61_WINDOWS_ONLY_PY312_UEBERGABE.md`, read in full.
Start: Draft PR [45](https://github.com/MartinezS8/chatgpt-web2api/pull/45),
`3a7c0b875e676eff4259ea9c62dcbcb4dd5b852e`, independently refreshed.
Its base is PR 44 / `codex/orchestrator-v40-windows-handle-security`.
Historical PR45 workflow 39677987266 concluded **failure** (five successful
matrix jobs, cancelled macOS/3.11, skipped build); it is not a successful gate.
`master` observed at `497527dceabfa3f95961e23c291e618c5570f1ac`.

## Phase 46 — PASS on exact commit

Branch: `codex/orchestrator-v42-windows312`, based exactly on the start SHA.
Both workflows retain their original trigger scope, use Windows/Python 3.12,
full offline strict SHA/preflight/postflight checks, a full-history secret scan,
and a dependent Windows wheel/sdist build with fresh-wheel CLI smokes.
Actions use immutable references and read-only repository permissions.
Package metadata accepts `>=3.12,<3.13`; Ruff targets `py312`.
The verifier rejects other interpreter versions before running tests.
The generic retry helper uses Python 3.12 type parameter syntax; behavior
is unchanged and covered by its existing mocked tests.

Local environment: Windows 11 Pro x64, build 26200; CPython 3.12.10;
PowerShell 7.6.5; Git 2.50.1.windows.1. This is the installed interpreter,
not a claim of the newest security release. Existing 3.11/3.13 remain untouched.
Venvs, build artifacts and logs are outside the worktree.
Runner and laptop evidence are recorded separately below;
Windows-latest is not a Windows 11 laptop attestation.

Final Phase46 commit: `5db96767b78a6fd4e01404dfcb6cc30a54cca5bb`,
[Draft PR46](https://github.com/MartinezS8/chatgpt-web2api/pull/46).
[Final CI 39686605617](https://github.com/MartinezS8/chatgpt-web2api/actions/runs/39686605617)
completed **success**, with exactly three Windows/Python3.12 jobs: strict offline,
full-history secret scan and dependent build/install/CLI smokes. Native runner:
Windows Server2025 build26100, Python3.12.10; **1240 passed, 2 skipped,
20 subtests**, compileall/Ruff0, exact SHA, clean pre/postflight.
Local Windows11/Python3.12.10 strict on that exact SHA: **1239 passed, 3 skipped,
20 subtests**, compileall/Ruff0, exact SHA and clean pre/postflight.
Local installed-wheel SDK handshake, all eight observer calls and mutator rejection
passed on a new synthetic private DB. Build and installed-wheel help/capabilities
passed. Wheel SHA256 `e268a8aaa6eb5398482f6b3eadf3487bcae9a3f55553d6b763b35936b1b44be1`;
sdist `c2b93985db759de24ff73b6f5c16109cd2a539fa994a812400dd219f67587c1c`.
Full-history Gitleaks passed locally and hosted on that SHA. Setup rerun and
unmarked-target preservation passed. `ci.yml` retains its master-target triggers;
it was source-reviewed and contract-tested, not separately triggered on this stack.
The branch workflow actually ran the equivalent three checks. No master write.
Pinned older actions emitted a Node20-deprecation/Node24-compatibility annotation;
all jobs completed successfully. This is maintenance work, not a security PASS.

Observed baseline `def0c67e55f46c50af6ad1e1aabf621ab482dd2f`: local strict
**1239 passed, 3 skipped, 20 subtests**, compileall/Ruff exit 0 and clean exact-SHA
pre/postflight (`w2a-v42-strict.json`, external operator evidence). Build and
fresh wheel imports, all three console helps, orchestrator help/capabilities
passed. Gitleaks 8.21.2 passed on that SHA; an incorrect pinned digest was
rejected before execution. Setup creation/rerun and wrong-interpreter/in-repo
negative probes passed. Dependencies: pytest 9.1.1, Ruff 0.17.1, MCP 1.30.0,
build 1.6.1; isolated build resolved hatchling 1.32.4.

CI 39685090470 on this baseline **failed**: 35 native owner checks rejected
Administrators-owned children (1205 passed, 2 skipped, 20 subtests), secret scan
passed, build skipped. Follow-up diagnostic run 39686249672 was cancelled when
superseded. On its same Windows Server 2025 / image 20261018.275.1 runner,
PowerShell TokenOwner differed from TokenUser: new child owners were
Administrators; Git Bash created user-owned children. Native source was
unchanged. Both workflows therefore run strict native tests in Git Bash using
Windows CPython 3.12, with an explicit disposable user-owner preflight. Native
owner/DACL checks remain unchanged. The laptop setup now rejects a default
owner differing from the current user before creating a venv. This is an
environment constraint, not support for elevated group-owned protected storage.
Microsoft documents the default owner rule in
[Owner of a New Object](https://learn.microsoft.com/en-us/windows/win32/secauthz/owner-of-a-new-object).
No token adjustment, new identity, account, elevation or system ACL change is used.

Luna Max handles disjoint setup/docs and workflow/scanner files. Main agent
owns package configuration, regression contracts, integration and review.
No runtime storage security mechanism or fixture reexport is removed.

## Phase 47 — implemented; final installed-wheel acceptance pending

The existing scheduler requires production `finished` dependencies while the
production finalizer is disabled. The demo must use an explicitly separate
synthetic completion path, with no asserted human approval or production
authorization. Existing component unit tests do not prove an installed demo.

Branch `codex/orchestrator-v43-offline-mvp` starts at the verified Phase46 SHA.
`mock_sandbox.py` integrates the existing Store, Scheduler, WorkerRegistry,
TaskPackages, UploadPreflight/UploadIntents, DispatchOutbox, CallbackInbox,
EvidenceLedger, ReviewLedger and Planner schemas. `offline_demo.py` provides
private root provisioning, bounded marker + read-only DB nonce validation before
Store construction, and a cooperative controller lock. `cli.py` exposes demo
init/run/status/doctor with explicit exit codes and rejects DB/environment overrides.

The fixed DAG uses two implementation tasks, two independent read-only reviewers,
then a planning summary: **five identities in waves 2/2/1**, not five simultaneous
live sessions. Prompts and attachment snapshots are synthetic and local. Results
are deterministic fake references, not provider outputs or generated code.
The only new outbox entry checks sealed mock upload readiness in the same write
transaction as intent creation. Unknown intents are quarantined on restart;
no in-memory permit is reconstructed. Duplicate progress/completion callbacks
are checked. The event consumer cursor persists; public output omits prompts,
claim tokens and raw session keys.

Synthetic receipts bind task, attempt, package, claim token hash/version,
assignment version, worker session hash, conversation and delivery. Only an
explicit same-store MockSandbox lets Scheduler use these fixed synthetic DAG
dependencies. Generic Scheduler and Store.claim still require FINISHED.
All demo tasks stay VERIFIED and retain production slots/write locks. The real
finalizer remains disabled. These receipts never grant provider/production actions.

Found and fixed during implementation:

| Severity | Issue | Correction / regression evidence |
| --- | --- | --- |
| P2 compatibility | App filesystem redirection made initial provisioning path differ from revalidated canonical root | All sensitive demo paths now come from policy context; native failure reproduced; canonical-path unit regression added |
| P2 integrity | Initial synthetic completion consumption omitted session/turn correlation | Independent Luna review reproduced session drift retaining completion; three failing regressions added, then fixed session hash + conversation/delivery matching |
| P2 safety | Reopen could create a demo lock before checking marker ownership | Identity is now checked before lock creation and again before Store; negative test confirms no lock/DB mutation without marker |

The first 27 new regression cases pass locally; **75 focused tests** pass including
existing upload/outbox/CI contracts. Independent follow-up verified the session fix
with 18 sandbox/entry tests. Focused contracts use real SQLite
with explicitly stubbed native ACL/pins and therefore are not native security proof.
Native installed-wheel acceptance and the final strict/CI receipts remain pending
at this implementation snapshot. `scripts/smoke_offline_mvp.py` exercises a fresh
installed wheel, full demo/restart/doctor, all eight MCP tools, forbidden mutator,
and a second fresh crash/unknown-delivery scenario without manual SQL. Both CI
build jobs execute it under Windows/Python3.12 with verified user-default ownership.

## Security gates

| Gate | Status | Scope |
| --- | --- | --- |
| Windows/Python 3.12 CI | PASS | Phase46 exact5db9676 receipt; Phase47 rerun pending |
| Installed five-worker offline MVP | NOT TESTED | Phase 47 acceptance pending |
| Private Model 1 storage | PARTIAL | Existing contract; new regression pending |
| Hostile same-user Model 2 / TOCTOU | FAIL | Existing content/journal findings remain |
| Effective second-user ACL denial | NOT TESTED | No authorized second token |
| Real worker transport and callback authentication | NOT TESTED | Not implemented or authorized |
| Real model/effort, app and upload verification | NOT TESTED | No provider calls |
| Production finalization | FAIL | Intentionally disabled pending trusted gate |

## Planned phases 48–51

1. **48:** assess officially supported transport documentation; define worker,
   capability, session and authenticated callback contracts with fakes. Require
   separate explicit approval for the first live send; persist unknown delivery
   and reconcile without blind retries. A Codex worker is not a ChatGPT web
   session with apps/plugins.
2. **49:** bind remote result/attachment IDs, current PR HEAD and verified CI to
   an independently identified reviewer and a separate user approval gate.
   No auto merge or database/provider mutation permission from mock evidence.
3. **50:** progress 1 → 2 → 5 separately addressable sessions only after each
   previous gate; verify locks, correlation, quotas, pause/resume, crash recovery
   and fail-closed model/effort capability selection.
4. **51:** user-level Windows installation/update/start/stop, diagnostics,
   manual backup/restore, secret-free logs and documented operation. Elevated
   services or public endpoints require a separate decision.

Official transport documentation was read for the planning step:
[Codex App Server](https://learn.chatgpt.com/docs/app-server) documents stdio
JSONL, initialization, persistent thread/turn IDs, streaming and approval requests.
[Non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
documents structured CLI JSONL events. Persistent app-server stdio is the
recommended first adapter candidate; this is a design inference, not a tested
entitlement or transport. No Codex/provider process or live turn was started.
Account/model/effort access and ChatGPT web app equivalence remain unverified.

This report is an implementation record, not production approval. Pending
results must be replaced by observed evidence before declaring completion.
