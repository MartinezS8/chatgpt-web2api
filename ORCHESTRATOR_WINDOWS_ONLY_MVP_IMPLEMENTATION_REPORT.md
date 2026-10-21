# Windows-only orchestrator implementation report

## Authority and scope

Specification: `CODEX_SOL61_WINDOWS_ONLY_PY312_UEBERGABE.md`, read in full.
Start: Draft PR [45](https://github.com/MartinezS8/chatgpt-web2api/pull/45),
`3a7c0b875e676eff4259ea9c62dcbcb4dd5b852e`, independently refreshed.
Its base is PR 44 / `codex/orchestrator-v40-windows-handle-security`.
Historical PR45 workflow 39677987266 concluded **failure** (five successful
matrix jobs, cancelled macOS/3.11, skipped build); it is not a successful gate.
`master` observed at `497527dceabfa3f95961e23c291e618c5570f1ac`.

## Phase 46 — implementation, verification pending

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
Runner Windows version and exact test/build receipts will be recorded after
the new SHA is tested; Windows-latest is not a Windows 11 laptop attestation.

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

## Phase 47 — pending successful Phase 46

The existing scheduler requires production `finished` dependencies while the
production finalizer is disabled. The demo must use an explicitly separate
synthetic completion path, with no asserted human approval or production
authorization. Existing component unit tests do not prove an installed demo.

## Security gates

| Gate | Status | Scope |
| --- | --- | --- |
| Windows/Python 3.12 CI | NOT TESTED | New exact-SHA receipts pending |
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

This report is an implementation record, not production approval. Pending
results must be replaced by observed evidence before declaring completion.
