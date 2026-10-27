## 2026-10-27 – PR #87 Audit-v2-Follow-up (cumulative Draft, no live test)

This update is planned against PR #86 HEAD `1d31fd8d2df6bce1c8bf2e9ba14bb2782499b344`. It addresses review
findings about duplicate/incomplete item lifecycles, mismatched terminal items,
uncorrelated safe notifications and notifications observed after the terminal
event. It adds a versioned audit consistency flag and synthetic negative
regression cases, without claiming a real app-server or Windows isolation
test. PR #86 HEAD and its verified hosted CI run 40497336431 are historical
evidence for that precise SHA only. A new exact-head hosted CI is required
before declaring this descendant green. `master` is unchanged; no merge,
live provider call, reauthorization, real turn or finalization is implied.

# Current assessment – PR #86 / Phase 48b follow-up (2026-10-27)

This section supersedes earlier readiness snapshots below where they describe an older PR, Codex version, schema bundle, or test count. Historical entries remain for audit context and must not be read as current evidence.

## Current Git and hosted evidence

- Repository: `MartinezS8/chatgpt-web2api`.
- Implementation branch: `codex/orchestrator-v83-tool-event-audit`.
- PR #86: [open Draft PR](https://github.com/MartinezS8/chatgpt-web2api/pull/86), stacked on PR #85 / base branch `codex/orchestrator-v82-mcp-provenance-refresh`.
- PR #86 base SHA at review: `b5e1121e0fe667a64bed965221c858c9b2bb203a`.
- Code SHA tested by local validation and the first exact-head hosted run: `ed38ac62e33870fc6b2cd3699bb3f1278eb3b680`.
- PR #86 was open, draft, and pointed at that exact head when checked. PR #85 was also open and draft at the same head. No merge was performed.
- Exact-head Actions run [40485598322](https://github.com/MartinezS8/chatgpt-web2api/actions/runs/40485598322) completed with all three jobs successful: Windows/Python 3.12 strict offline verifier, full-history Gitleaks, and wheel/sdist build plus fresh-installed-wheel CLI and offline integration smoke. The strict job reported **1,666 passed, 2 skipped, 20 subtests passed**, and 31 live E2E tests deselected. The distribution job built both artifacts, installed the wheel in a fresh Python 3.12 environment, and passed CLI, synthetic five-worker, crash-recovery, and read-only MCP checks. These are developer/CI results, not live-provider or production evidence.

## Phase 48b implementation and version-matched schema review

PR #86 adds a versioned, fail-closed audit of observed app-server item and notification events to the one-turn pilot path. Tool/action/approval/hook/unknown event types, malformed or contradictory receipts, and duplicate terminal events cannot be represented as a clean tool-free pilot. Receipts store fixed categories, counts and correlation metadata; they do not retain raw event payloads or unexpected model output. The send remains single-shot, and uncertainty is quarantined without retry.

The separate JSONL fake subprocess is synthetic and pins its fixtures to Codex `0.157.0` (`offline-fake-model-0.157`). The fresh installed local binary reported `codex-cli 0.164.0-alpha.11.1`, SHA-256 `1103e9e09c71fa2cd0afd6d8f3b9a2d63174fe8efd7cb5bd09f1cb14ef58a098`. A new local bundle was generated for that exact binary without starting a turn or using account credentials. It contained 320 schema files. The prior bundle and newly generated bundle had the same 320 paths and identical per-file hashes, but were bound to different executable hashes; the old bundle was correctly rejected for the new executable.

A synthetic fixture audit against the current generated schemas accepted `ThreadStartParams`, `TurnStartParams`, `TurnStartResponse`, and the model-list response. The Phase-48a minimal `thread/start` response fixture did **not** validate as `ThreadStartResponse` for Codex 0.164 (14 schema errors, including the `approvalsReviewer`, `sandbox`, and `thread` structures). The fake child still explicitly models the older 0.157 response shape. Therefore:

- The installed-wheel fake-process roundtrip is evidence for the synthetic, 0.157-style offline harness only; it is not evidence that a real 0.164 app-server exchange works.
- The real-pilot implementation loads four explicitly selected schemas from the locally hash-verified bundle and checks that their version equals the pinned executable's version. It validates outgoing thread parameters before `thread/start`, then validates the returned thread response before it can emit `turn/start`. A schema mismatch therefore fails closed before a model turn, but it can be discovered only after `thread/start` has already been sent; a future explicitly approved attempt could create an empty thread before aborting. No such request was sent in this validation.
- This mismatch is a documented simulation/compatibility gap. The synthetic harness remains suitable for its bounded offline protocol tests, but the current Codex-version transport behavior remains **NOT TESTED**. Do not claim the fake is version-matched to the installed 0.164 binary.

## Actual no-turn local preflight

The preflight used the native binary above and a freshly generated bundle and configuration-only MCP source map in temporary locations. It performed only `--version`, schema generation, configuration/source inspection, process startup and the explicitly authorized read-only account/model discovery described here. It did not open a browser, start a thread or turn, run inference, or access personal conversations/projects.

- Source inventory: 7 effective MCP configuration sources (5 user-config, 0 project-config, 2 plugin-manifest); 0 unresolved sources. One plugin candidate was conservatively rejected. Runtime process-local overrides disabled all 6 initially enabled MCP entries; Apps were disabled. The config snapshot was verified against the current executable, CWD, inventory and relevant configuration hashes.
- A no-account startup probe exited cleanly. It observed 16 installed Apps, all disabled/non-callable. Six MCP status records had zero callable MCP tools/resources and inactive status. The probe did **not** prove built-in tools absent: `strict_zero_tools_verified=false`, `built_in_tools_absent_verified=false`, and `readonly_builtin_tool_risk_remains=true`.
- A separately authorized, no-inference read-only discovery found an account in `chatgpt` mode and eight model records; the exact `gpt-6-luna` / `max` selection was present. No email or raw account payload was retained in this report. This confirms catalog availability at that point only; it does not authorize or prove a turn.
- The fixed MXC child probe used a process-only read-only permission profile with network disabled and verified its fixed CWD. It proves only that narrow probe, not hostile same-user isolation, full scratch-only file access, or equivalence with the live pilot's RPC path.

## Local and installed-wheel test evidence

All accepted local validation used Windows 11 and CPython 3.12.10 x64. The system Python currently on PATH is 3.13.6 and was not used as acceptance evidence. A preliminary 3.13 collection attempt lacked the configured project dependencies and ran no tests; it is not counted as a test result.

| Check | Exact procedure / revision | Result |
|---|---|---|
| Focused pilot regression tests | Pilot tool-audit, CLI and receipt tests on `ed38ac62e33870fc6b2cd3699bb3f1278eb3b680` | PASS – 105 passed |
| Ruff | `python -m ruff check src/ tests/ scripts/pilot_one_codex_turn.py` in the external 3.12.10 environment | PASS |
| Bytecode compilation | `compileall` with a short external cache prefix (the default long prefix first hit Windows path-length limits) | PASS after using the bounded external prefix; no repository test artifacts left behind |
| Full strict offline verifier | `W2A_E2E_RUN=0`; `python scripts/verify_orchestrator.py --full --strict --expected-sha ed38ac62e33870fc6b2cd3699bb3f1278eb3b680 --timeout 1200` | PASS – exit 0; **1,665 passed, 3 skipped, 20 subtests passed**, 31 E2E deselected; exact SHA and clean worktree before/after |
| Report-head strict offline verifier | `W2A_E2E_RUN=0`; exact SHA `77d65e99360cd3bbe6edb4690ed04a3239040edf`; same full strict command, local loopback available | PASS – exit 0; compileall 0.28 s, pytest exit 0 in 671.84 s, Ruff exit 0 in 1.78 s; exact SHA and clean worktree before/after; strict gate complete. Test count was not retained because diagnostics were disabled; no count is inferred. The verifier still records `network_isolation_verified=false`. |
| Local loopback / focused rerun | Bounded `socket.socketpair()` probe, then the three pilot/receipt/audit modules on `77d65e9` with correct `PYTHONPATH` | PASS – loopback probe passed; 105 tests passed in 7.72 s. An initial direct invocation without `PYTHONPATH` failed collection and was immediately corrected. |
| Fresh wheel fake-process smoke | Built wheel/sdist from `git archive` of the exact code SHA outside the checkout; installed wheel into fresh Python 3.12.10 venv; ran isolated module/child smoke | PASS – module loaded from installed wheel, synthetic JSONL child exited 0, model mismatch blocked before thread/turn, timeout emitted one `turn/start`, replay emitted none; no provider or real Codex child |
| Exact-head GitHub CI | Run `40485598322`, commit `ed38ac62e33870fc6b2cd3699bb3f1278eb3b680` | PASS – strict Windows/Python 3.12, full-history Gitleaks, wheel/sdist and installed CLI/offline integration jobs |
| PR #86 report-head exact CI | Run `40495104439`, SHA `5c6f7bd8f690a2fa1fb704fed2c5aa5127b19ae4` | PASS – strict Windows/Python 3.12: 1,666 passed, 2 skipped, 20 subtests; 31 E2E deselected; exact SHA/clean worktree, compileall and Ruff passed. Full-history Gitleaks passed. Wheel and sdist built; fresh Python 3.12 install, CLI help/capabilities, synthetic five-worker offline, crash-recovery and read-only MCP smokes passed. Only non-blocking Node 20 deprecation warnings. |

The differing local/hosted pytest totals (1,665/3 skipped locally versus 1,666/2 skipped in hosted Windows CI) are preserved as separate receipts; they are not normalized or conflated. The earlier exploratory Ruff invocation across every legacy script directory found unrelated existing findings outside the required target; the required source/tests/pilot-script invocation and strict verifier passed.

## Follow-up strict run and Windows loopback restriction

A standard-sandbox run on report-only SHA `34a50a432d5eff94bad5d7a40183b1c75aa9993b` timed out at 1,200.05 seconds in pytest (exit 124); compileall and Ruff passed, and strict SHA/clean-worktree preflight and postflight passed. A focused faulthandler trace isolated the hang to Python 3.12's Windows Proactor event-loop setup in `socket._fallback_socketpair()` at the local listener `accept()`. A bounded probe using `socket.setdefaulttimeout(1.0); socket.socketpair()` independently timed out. This was a sandbox restriction on local loopback, not a test assertion failure.

With an execution allowance for local loopback only, the socketpair probe passed and the focused pilot/receipt/event-audit tests passed (105 in 7.72 s). The full strict verifier then passed on report-only descendant SHA `77d65e99360cd3bbe6edb4690ed04a3239040edf` with `W2A_E2E_RUN=0` and `--timeout 1200`: compileall exit 0 (0.28 s), pytest exit 0 (671.84 s), Ruff exit 0 (1.78 s), `local_gate_complete=true`, exact SHA matched, and clean worktree at start and end. The strict receipt intentionally omitted raw stdout; therefore this run's test count is not claimed. `network_isolation_verified=false` remains recorded; the local permission is not evidence of OS-level egress isolation.

An earlier standalone focused invocation omitted the verifier's `PYTHONPATH` (`src/` plus `tests/`) and failed during collection with `ModuleNotFoundError`. The corrected invocation passed as described above. No code change was needed for either environment issue. The hosted run `40485598322` remains the separate exact-head CI receipt for code SHA `ed38ac62e33870fc6b2cd3699bb3f1278eb3b680`; run `40495104439` independently confirms all three jobs on report-head SHA `5c6f7bd8f690a2fa1fb704fed2c5aa5127b19ae4`.
## Current readiness matrix

| Gate | Status | Evidence and limit |
|---|---|---|
| Phase 48b bounded fake JSONL subprocess | PASS | Adversarial synthetic protocol tests and fresh installed-wheel child smoke; fixture is 0.157-style |
| Installed Codex 0.164 schema capture/pinning | PASS | 320 local schema files tied to the exact binary hash; no live turn |
| Phase-48a fixture compatibility with installed Codex 0.164 | PARTIAL | Params/results tested synthetically, but the old `thread/start` response fixture fails the current response schema; fake remains 0.157-style |
| Tool-event audit / fail-closed receipt | PASS for observed events | Exact-head local/CI tests; audit is retrospective and depends on emitted events, so it cannot prevent an action or attest a complete stream |
| Phase 48c durable reconciliation | PARTIAL | Existing ledger/outbox evidence remains synthetic; authenticated operator reconciliation/override is not complete |
| Read-only MCP observer | PASS for tested boundary | Tools/arguments/output are bounded and redacted; this is not worker authority or a guarantee that built-in Codex tools do not exist |
| Hostile same-user Windows TOCTOU isolation | FAIL | Same Windows identity can reach the controller user's objects; path/child-process checks do not prove OS isolation |
| Effective second-user ACL denial | NOT TESTED | No authorized restricted account/context is available; none was created |
| Phase 48d real worker | BLOCKED / NOT TESTED | No separate authorization for a live turn and no demonstrated worker isolation boundary; no thread or turn started |
| Gates 49–51 / two or five real workers | NOT TESTED | Mock DAG/worker evidence is not concurrent live-session evidence |
| Production Ready | FAIL | No production authorization, supported live transport evidence, effective isolation proof, or operational release controls |

## Next action and minimum prerequisites

Continue offline only. First keep the 0.157 fake scope explicit and add a version-specific synthetic fixture for the currently installed schema if the fake is intended to claim current-version compatibility. Otherwise leave the protocol fake version-labelled and make a separately reviewed current-schema fixture test the gate before any transport attempt. Preserve the rule that a thread response mismatch aborts before `turn/start`; account for the possibility that `thread/start` itself may create a remote thread.

The operator previously stated: “Kein Testkontext vorhanden – Live-Gate blockiert lassen.” That remains controlling. Before any live pilot, a separately authorized Windows isolation boundary must be demonstrated and the user must freshly approve the exact single prompt, model/effort, scratch path, outbound data scope, sandbox and one-attempt limit. Neither this report, a fake receipt, a matching expected output, account/model availability, nor a green CI check supplies that authorization. No automatic retry, task finalization, review approval, publication or deployment is implied.

# Orchestrator Phase 48b–48c Readiness Report

## Supplemental readiness update after PR #76 (2026-10-23)

### PR #77 local doctor correction

The local branch `codex/orchestrator-v74-pilot-doctor-account-mode` is based directly on the confirmed PR #76 head `f757c639de3ddac8de792a1c0e9f9b1feefce110`. Its code commit is `efc9c5b2f125c79ee0648fddf1b8965fd5dcfc66` (`fix: expose sanitized Codex account mode`). It is published as open Draft [PR #77](https://github.com/MartinezS8/chatgpt-web2api/pull/77), stacked on PR #76; the PR head at the first CI run was `cb5ec768ed2cd13f05a43b5490912fab74544edc`.

The pilot doctor now exposes only the validated `account_mode` enum alongside the existing presence flag. It rejects malformed or inconsistent account presence/mode data, including missing values, unsupported modes, and `account_present`/mode mismatches. It does not return account payloads, credentials, identifiers, or protocol frames. The regression test first failed on the missing field, then the focused suite passed: **12 passed**; Ruff passed on both changed Python files.

The exact committed code SHA passed the local Windows/CPython 3.12.10 strict verifier with `W2A_E2E_RUN=0`:

```text
python scripts/verify_orchestrator.py --full --strict --expected-sha efc9c5b2f125c79ee0648fddf1b8965fd5dcfc66 --timeout 1200
exit=0; compileall=0 (1.58s); pytest=0 (769.92s); ruff=0 (0.58s)
strict_preflight=true; sha_matched=true; postflight_ok=true
worktree_clean_at_start=true; worktree_clean_at_end=true
```

The verifier was run without `--diagnostics`, so its receipt does not expose the aggregate pytest count; no count is inferred here. It records `mode=full-non-e2e`, `skipped_checks=[]`, `network_isolation_verified=false`, and `live_provider_capabilities_verified=false`. This is a local, unattested result, not hosted CI or evidence of live provider use.

On this corrected source, the read-only local doctor reported `account_present=true`, `account_mode=chatgpt`, seven visible models, and verified the exact catalog entry `gpt-6-luna` with effort `max`. The local schema bundle contained 318 files and passed its audit. No thread or turn was started and no inference occurred. Account details and raw app-server responses are intentionally omitted.

The parent PR #76 remains Draft at exact head `f757c639de3ddac8de792a1c0e9f9b1feefce110`, based on `ffcbfb874cc6cac097c51ff69df1d89b1e87b85c`. Its exact-head GitHub run [39915028322](https://github.com/MartinezS8/chatgpt-web2api/actions/runs/39915028322) completed successfully: full-history Gitleaks, strict Windows/Python 3.12, and external distribution build plus installed CLI/MCP/mock/recovery smokes all passed. Earlier intermediate stack heads had failed or cancelled checks; they are not represented as individually green. The cumulative #76 head is the confirmed green parent.

### PR #77 exact-head CI

GitHub run [39919316978](https://github.com/MartinezS8/chatgpt-web2api/actions/runs/39919316978) passed all three jobs on PR #77 head `cb5ec768ed2cd13f05a43b5490912fab74544edc`:

- Full-history Gitleaks 8.21.2 passed; the receipt identifies the exact head and verified scan archive.
- Strict Windows/Python 3.12.10 passed in 18m44s: 1,545 passed, 2 skipped, 20 subtests passed; 31 live E2E tests were deselected. Compileall, Ruff, exact SHA, clean pre/post worktree, and strict pre/postflight checks passed.
- External distribution job passed: wheel and sdist built, the wheel installed in a fresh environment, installed CLI/MCP help and capabilities ran, and the installed-wheel five-worker synthetic demo plus crash-recovery and read-only MCP checks completed successfully.

These receipts are for the code and report commit `cb5ec768...`; a subsequent report-only correction is tracked separately and must be checked at its resulting head. Hosted CI remains Windows/Python 3.12 diagnostic evidence, not Linux/macOS coverage, a live provider test, or a production approval.

The operator has no authorized restricted Windows test context and directed that the live gate remain blocked. Same-user hostile TOCTOU remains `FAIL`; effective second-user ACL denial remains `NOT TESTED`. No real worker operation is authorized or technically cleared by the doctor change. Phase 48c remains `PARTIAL`, Phase 48d remains `BLOCKED`, and Gates 49–51 remain unproven.

## Prior readiness snapshot before PR #76 report-only revision (2026-10-23)

The latest checked stack is open and Draft: [PR #76](https://github.com/MartinezS8/chatgpt-web2api/pull/76), branch `codex/orchestrator-v73-ci-ruff-repair`, exact head `c931addcada718d9815d5280d1650d2a987fd0df`, based on PR #75 head `ffcbfb874cc6cac097c51ff69df1d89b1e87b85c`. This is a Ruff/test-fixture repair stacked after the prior fake app-server and durable-ledger work; it does not add live transport authorization.

The exact-head Windows/Python 3.12 workflow [39875312027](https://github.com/MartinezS8/chatgpt-web2api/actions/runs/39875312027) completed successfully: full-history Gitleaks, strict offline verification (1,539 passed, 2 skipped, 20 subtests passed; 31 E2E tests deselected), Ruff, compileall, exact SHA and clean-worktree checks, plus wheel/sdist build, fresh wheel install, CLI smokes, five-worker mock demo, crash recovery and read-only MCP smoke. CI is developer evidence only. Its strict-verifier receipt explicitly records `network_isolation_verified=false` and `live_provider_capabilities_verified=false`.

Local discovery used the native, Authenticode-valid Codex CLI `0.163.0-alpha.11.1` whose SHA-256 was pinned to the locally generated 318-file schema bundle. Only the read-only `account/read` and `model/list` calls were made after app-server initialization. The account was present; seven visible models were returned; the exact `gpt-6-luna` entry supports text and offers `max`. The doctor verified `gpt-6-luna` plus `max`. No email, token, session key, raw protocol frame or account payload was emitted into the report. No thread or turn was started, and no provider inference occurred.

Using synthetic data only, the locally installed CLI's four selected request/response schemas (`ThreadStartParams`, `ThreadStartResponse`, `TurnStartParams`, `TurnStartResponse`) and four current event schemas (`TurnStartedNotification`, `ItemCompletedNotification`, `TurnCompletedNotification`, `ModelReroutedNotification`) accepted representative fixtures. The synthetic effective-thread gate accepted the exact model, scratch CWD, `approvalPolicy=never`, and read-only sandbox with network disabled. This validates schema and guard compatibility, not a real app-server thread/turn exchange.

The operator has confirmed that no authorized restricted Windows test context is available and asked to keep the live gate blocked. Therefore no real turn was authorized or started. Proposed harmless approval profile, for a later separately approved test only:

- Model / effort: `gpt-6-luna` / `max` (exact catalog values just verified).
- Scratch: a new, empty `scratch` directory under the external LocalAppData test root; no repository, user files, credentials, or database are in scope.
- Exact prompt: `Output exactly ORCH_TEST_OK. Do not use tools.`
- Requested behavior if eventually approved: one turn maximum, read-only sandbox, no tools, no retry on an uncertain send; a completed transport turn would remain unreviewed and would not finalize any task.

Because the worker would run as the same Windows user and no separately authorized restricted context exists, this profile is not sufficient to establish OS isolation. A new explicit approval alone would not clear that isolation blocker. Same-user hostile TOCTOU remains `FAIL`; effective second-user ACL denial remains `NOT TESTED`. Phase 48b offline fake transport is `PASS`; Phase 48c is `PARTIAL`; Phase 48d is `BLOCKED`; real worker, Gates 49–51 and production readiness are not established.

**Current assessment date:** 2026-10-23

---

## Follow-up assessment after PR #58 (2026-10-22)

The historical assessment below is supplemented by the current validation of
the stack through PR #58 (00f8d4f5c9c9faa004497a07f22932df70ccb4db).
New local fixes prevent creation of missing append-probe markers and support
the actual 318-schema installed Codex bundle with bounded enumeration and
aggregate bytes. Exact implementation e914de26569c00956d2a2bd8336f1d105dd7c9f2
passed Windows/CPython 3.12 full strict verification: 1450 passed, 3 skipped,
20 subtests; Ruff/compileall passed; exact SHA and clean tree before/after.
Build and fresh installed-wheel CLI/mock/crash/MCP smoke passed. Exact PR #59
head e52af8ec9a97db1bc924fb5fa243e051e592b881 also passed all three jobs in
[GitHub run 39835778013](https://github.com/MartinezS8/chatgpt-web2api/actions/runs/39835778013):
full-history Gitleaks; strict Windows/Python 3.12 (1451 passed, 2 skipped,
20 subtests, exact SHA and clean tree before/after); dependent wheel/sdist and
installed CLI/mock/crash/MCP smoke. This follow-up only updates Markdown;
new-head diagnostics remain a separate PR check.

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

The operator confirmed that no authorized restricted Windows test context is
available and explicitly kept the live gate blocked. A focused capability
repeat also reproduced WinError 206 in the native long-path probe (skipped,
not PASS), while four symlink checks passed. No long-path or second-user
isolation guarantee is inferred from the full suite's successful exit.

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

