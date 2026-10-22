# Orchestrator Phase 48b–48c Readiness Report

## Follow-up assessment after PR #58 (2026-10-22)

The historical assessment below is supplemented by the current validation of
the stack through PR #58 (00f8d4f5c9c9faa004497a07f22932df70ccb4db).
New local fixes prevent creation of missing append-probe markers and support
the actual 318-schema installed Codex bundle with bounded enumeration and
aggregate bytes. Exact implementation e914de26569c00956d2a2bd8336f1d105dd7c9f2
passed Windows/CPython 3.12 full strict verification: 1450 passed, 3 skipped,
20 subtests; Ruff/compileall passed; exact SHA and clean tree before/after.
Build and fresh installed-wheel CLI/mock/crash/MCP smoke passed. New-branch
GitHub CI remains a separate required receipt.

Actual local Codex is 0.163.0-alpha.11. Offline schema generation passed, but
the old synthetic thread/start response does not validate against this CLI's
schema (approvalsReviewer, sandbox and thread.source). No live compatibility,
account model/effort availability or provider inference is established.

The newer Windows TokenUser-bound challenge journal records only unresolved
audit decisions. It does not implement trusted IPC, independent delivery
evidence, release, retry or finalization. Phase 48c remains PARTIAL; Phase 48d
remains BLOCKED by missing proven isolation and specific live permission.
Same-user hostile TOCTOU remains FAIL and effective second-user ACL denial
remains NOT TESTED. Gates 49–51 real-worker acceptance remains NOT TESTED.

See [local validation repairs and receipts](docs/ORCHESTRATOR_PR59_LOCAL_VALIDATION_REPAIRS.md),
including the unresolved earlier local pytest failure and skipped evidence.

**Assessment date:** 2026-10-22

**Status:** Phase 48b PASS for the offline fake; Phase 48c PARTIAL; Phase 48d BLOCKED pending a separate, specific live-operation authorization and a demonstrable Windows worker boundary.

**Repository:** MartinezS8/chatgpt-web2api

**Current code-validation revision:** 4796ebabd9bebdf9a3733a396f3b1f9fa3137b68

**Current work branch:** codex/orchestrator-v48c-durable-app-server-delivery
**Draft PR:** [#50](https://github.com/MartinezS8/chatgpt-web2api/pull/50), stacked on Draft PR [#49](https://github.com/MartinezS8/chatgpt-web2api/pull/49)

This report distinguishes implemented code, local test evidence, GitHub CI evidence, actual provider use, and production approval. The app-server implementation described here is an offline synthetic transport only. No real Codex executable was launched, no account or browser was accessed, and no provider turn was started.

## 1. Source and Git evidence

| Point | Evidence |
|---|---|
| PR #48 parent / Phase 48a | Draft branch head 410479a1d433694b33ec9e4e3fe49b1f9ef905bd |
| PR #49 / Phase 48b parent | Draft branch codex/orchestrator-v45-app-server-fake-jsonl, head 10408f000126da3b44be20e74bf78a5f72578af2; its base is PR #48 at 410479a1d433694b33ec9e4e3fe49b1f9ef905bd |
| PR #50 / Phase 48c | Draft branch codex/orchestrator-v48c-durable-app-server-delivery, code-validation head 4796ebabd9bebdf9a3733a396f3b1f9fa3137b68; base is PR #49 at 10408f000126da3b44be20e74bf78a5f72578af2 |
| Local worktree | Branch tracked origin at the code-validation head; worktree was clean before this report was added |
| Local implementation commits | 605d9303983737f3c51bbf239225b24a53a94d9e and 4796ebabd9bebdf9a3733a396f3b1f9fa3137b68 |

The requested comparison was performed against live PR metadata and the origin branch ref. PR #50 remains open and draft. No master change, merge, force push, deployment, or production action was performed. The final report-only commit is recorded in the branch history; the implementation validation results below apply to code SHA 4796eba, before that documentation-only commit.

## 2. Architecture and implementation

### Phase 48b — synthetic JSONL App Server

The fake stdio peer is launched only as the repository's bundled Python module through the current Python interpreter. The harness has no arbitrary executable, command, provider, credential, or environment override. It exercises initialization, initialized notification, model discovery, thread start, turn start, item/progress/terminal events, and bounded EOF shutdown over newline-delimited JSON. The harness is offline and reports a completed turn as unverified transport protocol evidence.

The local protocol notes record that Codex CLI 0.157.0 generated JSON Schemas using the documented schema-generation command, without starting the Codex app-server, signing in, or starting a turn. The recorded fixture comparison notes differences for sandbox fields, initialize/model/thread/turn result fields, omitted JSON-RPC markers, and shutdown-by-EOF. The generated schemas were kept outside the repository. This check is version-specific and does not prove live CLI compatibility or model entitlement. See [Phase 48b implementation notes](docs/ORCHESTRATOR_PHASE48B_FAKE_APP_SERVER.md) and the [official App Server documentation](https://learn.chatgpt.com/docs/app-server).

The fake transport handles bounded and fragmented frames, interleaved/early events, malformed or truncated JSON, duplicate keys, oversized frames/queues, unexpected request IDs, foreign thread/turn IDs, duplicate terminal messages, server-initiated approval requests, broken pipes, process death, timeouts, and interruption. Exact synthetic model and reasoning-effort values are required; there is no fallback. A partial client frame is classified as uncertain delivery.

### Phase 48c — durable offline delivery ledger

The new AppServerDeliveryLedger shares the canonical Store database and DispatchOutbox. Its schema is versioned and initialized transactionally. An attempt is bound to the canonical controller/worker/account/project/task/outbox attempt, package digest, claim-token digest and versions, prompt digest, and synthetic thread/turn identifiers. Prompt bodies, protocol payloads, claim tokens, worker session keys, and their MCP-visible forms are not persisted or returned by the observer.

Each outgoing request/notification has a committed intent before the fake stdio write. A written state is persisted after the flush, and acknowledgement state is persisted only after the protocol contract accepts the correlated reply. Recovery quarantines unresolved sends and does not issue a replacement attempt. The fake terminal event records transport_completed_unverified, leaves the task at needs_human, and creates no result evidence, reviewer approval, or finalization.

The observer exposes a fixed-query, read-only MCP view. It redacts sensitive digests and identifiers, rejects mutation arguments, and does not perform migration or state changes. Operator dispositions are append-only audit annotations, but the current implementation does not authenticate the operator and cannot resolve quarantine or grant permission to retry/finalize. This is deliberate and means Phase 48c is PARTIAL against the requested authenticated operator override/reconciliation acceptance criterion. A mock or caller-supplied operator reference is not an authorization credential.

### Security model and explicit limits

| Threat model / property | Assessment |
|---|---|
| Cooperative processes using the same private workspace and canonical outbox | PASS for tested transaction, claim/binding, correlation, and no-replay behavior |
| Unresolved write, lost acknowledgement, restart, or partial client frame | PASS for fake ledger quarantine and no second turn emission in the exercised paths |
| Hostile process under the same Windows user that can edit/replace workspace objects | FAIL; a Python process or path check under the same identity is not an OS isolation boundary; hostile TOCTOU is not claimed to be prevented |
| Effective read/write/delete denial from a second Windows user | NOT TESTED; no explicitly authorized second test account was available or created |
| OS-level network isolation of the local verifier/test process | NOT TESTED; verifier receipt has network_isolation_verified=false. Tests used fake/local subprocesses; no full OS egress-control proof was produced |
| Read-only observer authorization | PASS for tool allowlist, argument rejection and output redaction tests; this is not operator authentication |
| Operator override for real unknown delivery | NOT IMPLEMENTED; current audit dispositions do not release or retry a task |

## 3. Environment

| Item | Result |
|---|---|
| OS | Microsoft Windows 11 Pro, 10.0.26200, x64 |
| Python | CPython 3.12.10, 64-bit; only the user-required 3.12 environment was used |
| Git | 2.50.1.windows.1 |
| Filesystem | C: reported NTFS by local volume metadata; fsutil detailed volume query was access-denied, so no stronger filesystem claim is made |
| Validation environment | External venv at C:\Users\xxx\AppData\Local\w2a-validation-phase48b\venv |
| Selected tool versions | pytest 9.1.1; Ruff 0.17.1; MCP SDK 1.30.0; build 1.6.1; Hatchling 1.32.4 |
| E2E setting | W2A_E2E_RUN=0; all 31 account-backed E2E tests were deselected |

## 4. Executed verification

### Local Windows evidence

| Check | Procedure / revision | Result |
|---|---|---|
| Focused regression suite | Six delivery/fake/contract/observer/outbox/binding test modules on 4796eba | PASS — 118 passed in 20.35 s |
| Focused partial-frame subset | Delivery-ledger and fake-stdio tests after adding partial-write scenario | PASS — 60 passed |
| Test collection | Non-E2E collection on 4796eba | PASS — 1,397 collected; collection only, not counted as execution |
| Strict offline verifier | scripts/verify_orchestrator.py --full --strict --expected-sha 4796ebabd9bebdf9a3733a396f3b1f9fa3137b68 --timeout 1200 | PASS — exit 0; compileall, Ruff and pytest exit 0; 1,364 passed, 2 skipped, 20 subtests passed; 31 E2E tests deselected; exact SHA matched; clean worktree at start and end |
| Ruff | python -m ruff check src/ tests/ | PASS — All checks passed |
| Bytecode compilation | Included in strict verifier | PASS — exit 0 |
| Wheel and source distribution | python -m build outside the repository on 4796eba | PASS — one wheel and one sdist built |
| Fresh isolated wheel install | Separate external Python 3.12 venv | PASS — module imports, CLI help/capabilities, five-worker synthetic smoke, crash recovery and read-only MCP smoke |
| Installed-wheel partial-frame test | Synthetic attempt through installed wheel and bundled fake child | PASS — attempt quarantined as unknown_delivery, one turn/start request only, replay emitted zero turn/start requests, MCP redaction and mutation rejection passed |
| Provider actions | Process/command review and synthetic fixture boundary | PASS for the constraint: no Codex executable, live account, real prompt, provider call, browser, upload, or plugin action was used |

The strict verifier receipt is outside the worktree at C:\Users\xxx\AppData\Local\w2a-validation-phase48c-wheel\receipts\strict-4796eba.log. The installed-wheel smoke receipt is outside the worktree at C:\Users\xxx\AppData\Local\w2a-validation-phase48c-wheel-4796eba\receipts\wheel-smoke-4796eba.json. These receipts are local evidence and are not signed or independently attested.

### GitHub CI evidence

Only the required Windows/Python 3.12 branch-validation workflow was used; no matrix expansion or self-hosted CI was started.

| Revision | Workflow / jobs | Result |
|---|---|---|
| PR #49 Phase 48b head 10408f000126da3b44be20e74bf78a5f72578af2; run 39784244535 | Full-history Gitleaks, strict Windows/Python 3.12, wheel/sdist plus installed CLI/five-worker/crash-recovery/read-only-MCP smoke | PASS — all three jobs completed success. Strict job: 1,342 passed, 2 skipped, 20 subtests passed; 31 E2E deselected; exact SHA and clean worktree checks passed |
| PR #50 code head 4796ebabd9bebdf9a3733a396f3b1f9fa3137b68; run 39791362437 | Full-history Gitleaks | PASS — job completed success |
| PR #50 code head 4796ebabd9bebdf9a3733a396f3b1f9fa3137b68; run 39791362437 | Strict Windows/Python 3.12 | PASS — job completed success; 1,364 passed, 2 skipped, 20 subtests passed; 31 E2E deselected; exact SHA/strict verifier passed |
| PR #50 code head 4796ebabd9bebdf9a3733a396f3b1f9fa3137b68; run 39791362437 | Distribution build and installed CLI/five-worker/crash-recovery/read-only-MCP | PARTIAL at report capture — all substantive build/install/smoke steps and cleanup steps report success, but GitHub still reports the job/check itself as in_progress/pending with completed_at=null. The workflow run aggregate reports success, which conflicts with the job-level API/check state. Do not call the package CI gate PASS until the check reaches a terminal success state on an exact head. |

Receipts: [PR #49 run](https://github.com/MartinezS8/chatgpt-web2api/actions/runs/39784244535) and [PR #50 run](https://github.com/MartinezS8/chatgpt-web2api/actions/runs/39791362437). The report-only commit creates a new exact PR head and requires its own CI result. Local build/install evidence is successful but does not replace the pending GitHub package-job check.

## 5. Findings and fixes

| Severity | Finding | Cause / location | Correction and regression evidence | Residual risk |
|---|---|---|---|---|
| P1 | Stale fake attempt could progress if its durable outbox/task binding changed after preparation but before the offline child began | Delivery start and durable binding validation in app_server_delivery.py | Revalidated binding and outbox/task fencing inside the same immediate SQLite transaction used to move prepared to running; regression test verifies stale attempt does not start | Protects cooperative durable state; same-user tampering of the database remains outside the guarantee |
| P2 | Partial JSONL frame write could otherwise be mistaken for a clean non-send and retried | app_server_fake.py and app_server_delivery.py | Added synthetic partial-write scenario and durable unknown state; test proves one initial turn/start and zero replay turn/start | This is fake-transport evidence; real Codex pipe write/ack semantics remain untested |
| P3 | Model/effort configuration accepted oversized strings before transport/journaling | app_server_fake.py | Added explicit length bounds; regression parametrization rejects before request emission | Exact live model availability still unverified |
| P3 | A fake terminal result could be returned after the worker binding changed between fake completion and final binding check | app_server_delivery.py | Result is withheld and attempt remains needs_human on failed post-terminal binding check; regression test added | Does not resolve operator authorization |
| Open / acceptance gap | No authenticated human reconciliation/override path can resolve unknown delivery | No authenticated operator identity/authorization primitive exists in this offline boundary | Kept dispositions append-only, non-authorizing and unable to retry/finalize; did not invent an environment flag or synthetic permission | Phase 48c PARTIAL; implement and threat-review a real authorization model before any live transport |

## 6. Independent review and ownership

One Luna Max subagent performed a bounded read-only review of the Phase 48c diff and negative-test surface. It reported stale-binding and result-consistency risks. Sol 6.1 independently inspected and fixed those cases, added regression coverage, reviewed the final implementation, ran the strict suite, and made all architecture and security gate decisions. No subagent pushed, merged, or approved anything.

## 7. Readiness gates

Statuses use only PASS, PARTIAL, FAIL, and NOT TESTED.

| Gate | Status | Basis |
|---|---|---|
| Phase 48b fake JSONL subprocess | PASS | Synthetic stdio protocol, adversarial tests, Windows/Python 3.12 strict CI at Phase 48b exact head and fresh installed-wheel fake test |
| Durable correlation and no blind replay | PASS for tested offline paths | Atomic intent/write/ack ledger, restart recovery, stale binding, partial-frame quarantine, replay tests and strict suite |
| Phase 48c overall acceptance | PARTIAL | Authenticated operator override/reconciliation is not implemented; current annotations cannot release an attempt |
| Read-only MCP observer | PASS for tested tool boundary | Fixed-query tool, redaction, read-only argument rejection and stdio/wheel smoke |
| Windows hostile same-user TOCTOU protection | FAIL | Same user can alter the private workspace or SQLite objects; current design does not pin all operations to trusted handles |
| Effective second-user ACL denial | NOT TESTED | No authorized second-user test context was available; no account or ACL changes were made |
| Phase 48d real worker transport | NOT TESTED; BLOCKED | No separate specific approval for a real prompt, no demonstrated native isolation boundary, and no live transport implemented |
| Gate 49 evidence/review | NOT TESTED | Requires exact live-worker evidence plus independent identity and review; fake turn is not evidence |
| Gate 50 two/five real workers | NOT TESTED | No proof of simultaneous real sessions, isolation or cross-worker rejection |
| Gate 51 laptop operations | NOT TESTED for the new real-worker service | Existing offline CLI smoke does not validate installing, supervising, upgrading or recovering a live worker service |
| Real Worker Ready | FAIL | No supported and authorized real worker adapter or safe Windows isolation proof |
| Production Ready | FAIL | No production transport, permission review, operational security proof, or user authorization exists |

## 8. Next gates and minimum pilot prerequisites

### P0 — Complete Phase 48c without enabling a live send

1. Design an authenticated operator decision mechanism that is separate from worker/test flags, environment variables, fake receipts, and unauthenticated caller-supplied identity strings. It must be auditable, replay-safe, and incapable of implicitly creating a new turn.
2. Specify the exact unknown-delivery outcomes: unresolved, independently confirmed delivered, or independently confirmed not delivered. Keep a confirmed-delivered attempt non-retryable; any new attempt must require a distinct authorized task/attempt policy and audit record.
3. Add crash/race/replay tests proving the operator action cannot attach evidence, finalize, approve, or dispatch unless a separately reviewed permission expressly allows that operation.
4. Close or explicitly retain the package-check status ambiguity and obtain terminal exact-head CI receipts.

### P0 — Before any single real worker test

1. Obtain fresh, specific user permission for the exact harmless prompt, repository, outbound data and single bounded attempt. This task contains no such permission.
2. Prove Windows isolation. A disposable Git worktree alone is not sufficient when controller and worker share the same Windows user. The worker must not be able to read controller databases, session credentials, unrelated user files, or modify controller/outbox state. If the OS boundary cannot be demonstrated, do not start the pilot.
3. Verify entitlement and exact model/reasoning-effort availability without fallback, inspect the precise sandbox/command/network policy, and record the permitted cwd, files, network scope and stop procedure.
4. Execute at most one authorized attempt. Preserve request/thread/turn correlation and unknown-send quarantine. Do not enable app/plugin actions, uploads, broad network access, branch push, PR publication, merge or deployment by implication.
5. Reconcile independent evidence and reviewer identity. A completed transport turn is not a result, review, or finalization.

### P1 — Gate 49, then Gate 50

Gate 49 should verify exact repository/PR/HEAD/CI provenance, an independent reviewer identity, evidence integrity, duplicate callbacks and head changes. Finalization must remain behind an explicit human gate. Only after passing it should the system test two real workers with separate sessions and isolated worktrees, then five simultaneous workers. Each scale step needs quotas, resource fences, pause/kill/recovery proofs and cross-worker rejection. The existing synthetic five-worker DAG does not prove concurrent provider sessions.

### P2 — Gate 51 operations

Add least-privilege non-elevated install/start/stop/status/doctor operations, authenticated operator actions, backup/restore rehearsal, upgrade rollback, redacted audit logs, recovery of unknown sends and explicit confirmations. A GUI is not required for the first supported operation.

## 9. Recommendation and explicit missing approvals

The code is ready for continued offline development and review. It is not ready for a real worker test. Continue with the authenticated reconciliation/override design and the exact-head CI receipt issue first. Do not start Phase 48d until a Windows isolation boundary is demonstrated and the user gives fresh, specific approval for a particular harmless test task. Approval for a future pilot would not authorize plugins/apps, file uploads, wider network access, additional tasks, second/five workers, pushes, PR publication, merge, or deployment.

The implementation supports Codex App Server stdio as a distinct protocol target. It does not establish equivalence with ChatGPT Web UI, GPTs, plugins/apps, or any model's product-specific capabilities. No live model/effort entitlement or provider behavior has been verified.

