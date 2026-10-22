# Local validation repairs after PR #58

Base: Draft PR #58, exact SHA 00f8d4f5c9c9faa004497a07f22932df70ccb4db.
Windows 11, CPython 3.12.10; all account-backed E2E tests remain disabled.

## Reproduced defects

1. The missing-marker test failed locally and in PR #58 CI run 39830386227
   (1 failed, 1444 passed, 2 skipped, 20 subtests passed). Opening the append
   marker with `ab` created a missing marker and returned ALLOWED. The probe
   now opens with O_WRONLY/O_APPEND/O_BINARY without O_CREAT. Its regression
   additionally asserts that no missing marker was created. The primary
   attestation marker remains untouched.
2. Local native Codex CLI 0.163.0-alpha.11 generated 318 JSON schema files,
   totalling 3,629,800 bytes, exceeding the arbitrary 300-file cap. The
   diagnostic now permits at most 1024 files with a 64 MiB aggregate cap;
   the existing 25,000,000-byte per-file cap remains. Regression coverage
   accepts 318 synthetic schemas, rejects 1025 and rejects excessive total
   size without publishing a successful readiness receipt.

## Local evidence

The 21 focused schema/isolation tests passed, and Ruff passed. The corrected
native schema diagnostic succeeded with an explicit absolute executable path
and exact expected version. Receipt and schemas remain outside the repository
under LOCALAPPDATA/w2a-validation-phase58/schema-fixed-20261022.
Independent read-only review identified eager path collection before checking
the count cap. Enumeration now stops at the first excessive JSON path before
sorting. Tests additionally cover exactly 1024 files, early enumeration stop
and cumulative overflow across two files. The intermediate strict run on
e515c38 was deliberately stopped to incorporate this change, not counted as PASS.
Only `--version` and `app-server generate-json-schema` were executed. No
authentication, model/list, thread/start, turn/start or provider operation ran.
The executable version is an alpha version: schema generation is not proof of
runtime model availability or protocol interoperability.

## Final local runtime evidence

Exact implementation SHA e914de26569c00956d2a2bd8336f1d105dd7c9f2 passed
the full strict verifier: 1450 passed, 3 skipped, 20 subtests; compileall and
Ruff exit 0; exact SHA matched; clean worktree before and after. E2E was disabled.
Wheel/sdist build and fresh installed-wheel CLI, five-worker synthetic DAG,
idempotence, crash quarantine/no replay and read-only MCP smoke passed. Receipt:
LOCALAPPDATA/w2a-validation-phase58/reviewed-wheel-smoke.json. Strict diagnostic
receipt: LOCALAPPDATA/w2a-validation-phase58/strict-diagnostics.log.

The earlier complete run on 1ebce17 had pytest exit 1 with only an output hash
retained. Its individual failure cannot be reconstructed or attributed to a
fix. It did not recur in the final diagnostic run; this is an unresolved
historical failure, not proof that a specific cause was repaired. Intermediate
runs deliberately stopped for review changes do not count as PASS.

Offline JSON Schema comparison of seven fixture request/response structures
against the generated 0.163.0-alpha.11 schema found the synthetic 0.157
thread/start response incompatible at approvalsReviewer, sandbox and
thread.source. The other six structures validated. This is NOT a supported
live adapter for 0.163.0-alpha.11. Schema capture does not attest entitlement,
models/efforts, runtime behavior or sandboxing. Detailed local comparison:
LOCALAPPDATA/w2a-validation-phase58/fixture-schema-comparison.json.

GitHub run [39835778013](https://github.com/MartinezS8/chatgpt-web2api/actions/runs/39835778013)
completed successfully on exact PR #59 head
e52af8ec9a97db1bc924fb5fa243e051e592b881: full-history Gitleaks, strict
Windows/Python 3.12 and dependent wheel/sdist/installed CLI/mock/crash/MCP jobs.
The actual strict log reports 1451 passed, 2 skipped, 20 subtests; SHA matched
before and after, and both worktree checks passed. Package logs confirm the
idempotent demo and unknown-delivery quarantine after the synthetic crash.
This documentation-only follow-up does not change the tested executable code;
its own branch checks remain separately observable on the PR.

No real worker is authorized. Hostile same-user TOCTOU remains FAIL; effective
second-user denial and network confinement remain NOT TESTED. The process-SID
audit gate remains inert and is not trusted IPC, independent evidence,
quarantine release, retry permission or finalization.

## Laptop capability and operator constraint

A focused repeat of the dynamic capability tests passed four symlink checks
and skipped the Windows long-path probe with WinError 206. The laptop's native
long-path support is therefore not demonstrated; skipped is not PASS. Receipt:
LOCALAPPDATA/w2a-validation-phase58/capability-skips.log. The two statically
Windows-skipped POSIX tests are separate from this capability probe.

The operator explicitly confirmed that no existing authorized restricted test
context is available and instructed that the live gate remain blocked. No
second-user probe was executed, no account was created, and no credentials
were requested. Genuine OS isolation, account model discovery and a single
real turn remain separate blocked/unexecuted gates. A mock receipt, local
TokenUser match or successful CI cannot replace those requirements.
