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

## Phase 47 — PASS on implementation commit 0088e1a; CI follow-up on f351109

The existing scheduler requires production `finished` dependencies while the
production finalizer is disabled. The demo must use an explicitly separate
synthetic completion path, with no asserted human approval or production
authorization. Existing component unit tests do not prove an installed demo.

Branch `codex/orchestrator-v43-offline-mvp` starts at the verified Phase46 SHA.
It is the stacked [Draft PR47](https://github.com/MartinezS8/chatgpt-web2api/pull/47),
based on Phase46 / `5db96767b78a6fd4e01404dfcb6cc30a54cca5bb`.
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
| P2 runtime | Protected native SQLite connections were repeatedly opened and closed during each mock operation; the first hosted wheel demo ran for about 9 minutes and returned exit 2 before completing the DAG | Added a thread-local protected connection scope for one controller thread and each mock worker thread. Each Store operation still revalidates the policy and independently commits or rolls back; native SQLite handles remain pinned until scope exit. Added rollback, thread isolation, mode-change, policy-denial, unfinished-transaction, exception cleanup, and native Windows main/WAL/SHM handle tests. The completed local native demo now takes about 57 seconds after initialization. |
| P2 test reliability | Hosted Windows run timed out while generating two synthetic 6,000-row hot rollback journals | Reduced only those fixtures to 64 rows, still beyond a five-page cache; genuine journal header/recovery assertions remain. The focused native modules and both full exact-SHA suites pass. |

The fixes are committed on `codex/orchestrator-v43-offline-mvp`:

- `06f1b52a95d84a6ec80ded0dbf8c5be65a1484f8` — fixed five-worker offline demo.
- `0088e1a6ba10f270395c45d27637998c29c114a1` — protected connection scope and
  regression coverage; initial installed-MVP evidence below.
- `f351109ed3a83206aa00c58998ecc78d65cdb66a` — bounded hot-journal fixtures
  after hosted Windows timeouts; no storage-policy or production gate changed.

Local targeted regression suite: **125 passed** (including protected storage,
packages, upload preflight/outbox, demo, connection-scope and CI contracts).
Native Windows demo on an isolated private workspace: initialization **14.14 s**;
full run **57.46 s**, `demo_complete`, 5 tasks, 5 worker identities, 5 callbacks,
5 mock upload receipts, 2 independent reviews and event cursor 15. All tasks
remain `VERIFIED` with production locks held.

Exact-SHA local strict verification on `0088e1a`, Windows 11 Pro x64 build 26200,
CPython 3.12.10: **1273 passed, 3 skipped, 20 subtests** (pytest 524.25 s);
compileall and Ruff passed, SHA matched at start/end, and the worktree was clean
before and after. `W2A_E2E_RUN=0`; 31 real-account E2E tests were deselected.
The structured receipt is stored outside the checkout at
`C:\Users\xxx\w2a-v43-0088-strict.log`.

Fresh external Windows wheel/sdist build succeeded. Wheel
`chatgpt_web2api-0.2.0-py3-none-any.whl` SHA-256
`6bf7f43d3145c737ee9db84ab710def75498b7cbfea46e4c17dc98f0e5598762`;
sdist SHA-256 `6ae4b8c0e96a1f411e43a4a5dd51e3a22b15e2eabeaed04ddc0bc9f2f4e5de04`.
The wheel installed into a fresh isolated Python 3.12.10 environment. All
supported help/capabilities commands passed. The installed-wheel acceptance
receipt passed 8 steps: `demo_complete`, idempotent rerun and doctor, MCP
initialize/stdio handshake, all eight read-only tools and schemas, rejection of
an unknown mutating tool, DAG event ordering, crash exit 17, restart quarantine
as `needs_human`, and repeat restart without another attempt/cursor advance.
It asserts `provider_calls=false` and `production_approval=false`.

Local full-history Gitleaks 8.21.2 passed on `0088e1a`. Hosted run
[39756391999](https://github.com/MartinezS8/chatgpt-web2api/actions/runs/39756391999)
passed all three Windows/Python 3.12 jobs on that exact SHA: strict offline,
full-history Gitleaks, and dependent wheel/sdist plus fresh install and offline
MVP/MCP smoke. Hosted strict result: **1274 passed, 2 skipped, 20 subtests**
(pytest 620.43 s), compileall/Ruff passed, exact SHA and clean pre/postflight.
The workflow's Gitleaks and build jobs both passed. The separate `ci.yml` retains
its master-target trigger and was not triggered on this stacked PR. Node.js
20-to-24 compatibility/deprecation annotations were non-failing.

### Windows hot-journal validation follow-up

The report-only commit `4158800688ee130bf28fde19d60956845a5d9cb0` exposed two
Windows CI failures in hosted run
[39759763287](https://github.com/MartinezS8/chatgpt-web2api/actions/runs/39759763287):
the child processes used to create a synthetic hot rollback journal exceeded
their 30-second timeout in `test_hot_recovery_path_change_is_reported_despite_late_failure`
and `test_protected_startup_recovers_legacy_delete_hot_journal`. The first
therefore reported `NOT_TESTED`, and the storage-pin test timed out. This was a
test-fixture runtime issue; the CI output does not establish a storage-code
failure or a security pass for the hostile-process model.

Commit `f351109ed3a83206aa00c58998ecc78d65cdb66a` reduces only these two hot-
journal probes from 6,000 rows to 64. The workload still dirties more pages than
the child's five-page cache; both tests assert the genuine SQLite hot-journal
header and verify rollback/recovery state. The change makes no claim against
hostile concurrent path swaps and does not change the protected storage
algorithm. Both full native test modules passed locally: **44 passed in 134.18 s**
(`C:\Users\xxx\w2a-v43-415-hot-journal-focused.log`).

Exact-SHA local strict verification on `f351109`, Windows 11 Pro x64 build
26200, CPython 3.12.10: **1273 passed, 3 skipped, 20 subtests** (pytest 518.43 s);
compileall and Ruff passed, the SHA matched at start/end, and the worktree was
clean before and after (`C:\Users\xxx\w2a-v43-f351109-strict.log`).
Hosted run [39763371611](https://github.com/MartinezS8/chatgpt-web2api/actions/runs/39763371611)
passed on the exact `f351109` SHA: strict Windows/Python 3.12 **1274 passed,
2 skipped, 20 subtests** (pytest 636.06 s), compileall/Ruff, exact SHA and clean
pre/postflight; full-history Gitleaks; and the dependent wheel/sdist build,
fresh installed-wheel and CLI/offline-MVP/MCP smoke. All three jobs passed.
The run is developer validation for this Windows/Python 3.12 branch only.

Luna Max provided disjoint workflow/tests and an independent read-only review of
the connection-scope diff; it reported no concrete defect. Main agent reviewed
transaction boundaries, thread ownership and native handle lifetime. These
receipts prove the offline Windows/Python 3.12 path only; no real provider call,
second-user ACL denial, hostile same-user race, or production authorization was
performed.

## Security gates

| Gate | Status | Scope |
| --- | --- | --- |
| Windows/Python 3.12 CI | PASS | Latest exact-code-SHA run 39763371611 on f351109; the earlier 0088e1a run 39756391999 is historical |
| Installed five-worker offline MVP | PASS | Hosted exact-f351109 build/install/CLI/offline-MVP/MCP smoke; native Windows storage, five mock identities, DAG, callbacks, reviews and crash quarantine |
| Hot-journal crash/recovery regression | PASS | 44 tests across both native Windows modules; local and hosted full suites pass after reducing fixture volume |
| Private Model 1 storage | PARTIAL | Native user-owned workspace and handle lifetime verified for cooperating processes; this is not a hostile-process guarantee |
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

This report is an implementation record, not production approval. The MVP
implementation and successful Windows validation follow-up are pinned to
`f351109ed3a83206aa00c58998ecc78d65cdb66a`; the initial demo implementation
and installed-wheel receipt are pinned to `0088e1a6ba10f270395c45d27637998c29c114a1`.
Any later report-only commit is documentation and does not change those code
receipts. The open security gates and phases 48–51 remain unfinished.
