# PR-14 — Legacy Controller transport is disabled by default

Date: 2026-10-19. Parent: [PR #15](https://github.com/MartinezS8/chatgpt-web2api/pull/15). This is an incremental P0 safety gate in the unmerged orchestrator stack.

## Independent finding

The original `Controller.dispatch()` directly ran `Store.claim` and `Transport.send`, with no immutable TaskPackages verification, no WorkerRegistry session authorization, no DispatchOutbox intent and no file/app/model preflight. This bypasses the purpose of newer PR-02B/02C/03 safety layers. `Controller.poll()` likewise consulted whichever custom transport the caller injected.

Although no production transport was attached, a future integration could accidentally connect a real ChatGPT/Codex transport to this unguarded legacy path.

## Implementation

- `Controller(..., offline_test_mode=False)`: default mode now **rejects** `dispatch` and `poll` immediately with `PermissionError`, before `Store.claim`, any state mutation or any transport call.
- Existing offline V3/V4 unit fixtures explicitly pass `offline_test_mode=True`. This opt-in exists **only for trusted local tests** and is not remotely authenticated. Anyone who can run arbitrary Python in the controller process can use the flag, so it must **not** be exposed through Codex MCP, UI, CLI or live-provider adapters.
- Added a regression proving that a default controller neither invokes `StubTransport.send` nor changes the queued task or event log.
- There is no new live adapter, no real file upload/app selection and no model/effort proof.

## Verified tests and scope

Local Linux, Python 3.13, tests from the V4 regression package with source/test files whose Git blob SHAs match the committed branch:

```bash
PYTHONPATH=src pytest -q tests/test_orchestrator.py tests/test_orchestrator_cli.py tests/test_orchestrator_multiprocess.py
python -m compileall -q src tests
```

**34 passed + 8 subtests** and compile succeeded. The combined PR #1–#16 upstream test suite, Windows and Ruff are **not claimed** to have passed.

## Remaining P0 gate (implementation sketch)

1. Build **one** authorized dispatch service that accepts only a sealed task/attempt identifier, resolves the authenticated worker/session binding, and validates immutable blob hash, role, current repository scope and capability manifest.
2. Before any external effect, reserve task+worker once; journal upload intent and dispatch intent (no replay after unknown delivery); require exact model/effort and per-message app entitlement preflight; fail closed if unavailable.
3. For a definite confirmed remote submission record provider conversation/user-turn IDs in the durable outbox; use authenticated event correlation and ordered replay to process terminal callbacks. An internal MCP progress notification is advisory, not a completion receipt.
4. On crashes, preserve the write lock if delivery may have happened. Use provider-supported reconciliation; never blind retry nor bypass account limits, approval dialogs or Terms.
5. Implement provider-attested finalization separately as specified in [PR-13](ORCHESTRATOR_PR13_FINALIZATION_GATE.md), with fresh exact PR HEAD, CI and independent review.
6. Only then consider 1-worker authorized E2E; expand to 2/5 logical workers after quotas and actual provider sessions are verified.

**Merge order:** #1 → #2 → #3 → #4 → #5 → #6 → #7 → #8 → #10 → #12 → #14 → #15 → this PR. Keep all Draft until integrated review and the Codex test run. `master` remains unchanged.
