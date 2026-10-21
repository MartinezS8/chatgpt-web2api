# Storage security contract and architecture decision

Base: PR44 `ae3d771d590a89e3e4cc184d07664272b2bc5615`.

## Decision: A for the currently supported offline product

The supported private mode assumes cooperating processes under one Windows
identity in a validated private workspace (Model 1). It rejects observed
configuration/ACL/path violations. It does not isolate a hostile same-user
process or arbitrary Python code inside the controller. No real worker or
production acceptance follows from this decision.

| Alternative | Isolation prerequisite | Cost / deployment | Decision |
| --- | --- | --- | --- |
| A: private workspace, cooperating processes | Caller trusts processes with the owner's file access | Existing Python/SQLite deployment; bounded checks and pins | Supported offline scope only |
| B: separate storage broker | Actually distinct restricted OS identity/container; IPC authorization; clients cannot write broker files | Account/container lifecycle, install and recovery procedures, IPC protocol | Deferred; same-user broker alone is insufficient |
| C: custom SQLite VFS plus file APIs | Full xOpen/xAccess/xDelete, WAL shared memory/locking/recovery, handle identity, blob/staging/backup APIs | Native implementation and ongoing SQLite/Windows compatibility burden | Deferred pending a separately reviewed prototype |

A complete Model-2 product would require B, C, or a demonstrated equivalent.
A VFS alone does not stop an attacker already authorized to write the underlying
file contents. OS identity separation and access policy still matter. No native
wrapper is introduced here as an unsupported isolation claim.

## Diagnostic harness and normative gate

Run outside live worker/provider workflows, using the development Python:

```powershell
python -m chatgpt_web2api.orchestrator.storage_audit > C:\path-outside-repo\audit.json
$LASTEXITCODE
```

The harness creates UUID-labelled disposable private workspaces and separate
synthetic external markers; it accepts no target DB/root argument. Hooks live
only inside the harness's patched SQLite boundary, never in production code.
Each attacker is a separate process under the same user. SHA-256 values record
external marker and selected protected-file content before/after the hook.
Only an observed sharing violation (WinError 32), unchanged markers and no
operation error count as BLOCKED. Other failures are NOT_TESTED. Observed writes
remain REPRODUCED_UNSAFE even if the operation subsequently raises.

The default exit is **1** unless every required surface is BLOCKED. Missing,
duplicate or unknown coverage cannot pass. --diagnostic can return zero for
collection automation but leaves model2_accepted=false in the report. A green
pytest suite tests the fidelity of this diagnostic; it is not a green Model-2
gate. Do not add this intentionally failing security gate to ordinary CI as if
diagnostic success granted confinement.

## Observed Windows result on the PR44 implementation

| Surface/hook | Result |
| --- | --- |
| Main / WAL / SHM / migration journal, before SQLite open | BLOCKED; sharing violation and unchanged synthetic markers |
| Main file content write before SQLite open | REPRODUCED_UNSAFE; file content changed, then SQLite raised DatabaseError |
| Genuine hot-journal recovery, before SQLite open | NOT_TESTED (inconclusive safety); journal replacement succeeded, later ValueError, independent recovery inspection failed |
| Ancestor, root, attachment source, stage lock, blob publish, backup publish | NOT_TESTED; hooks still required |
| Restricted second user | NOT_TESTED; no authorized token |

Hot-recovery setup forces cache spill in a child that exits before commit and
requires the genuine hot-journal signature. A substituted invalid journal and
postflight failure are not labelled protection. The harness records this
inconclusive outcome explicitly; it does not prove external corruption or
successful rollback for that attack.

## Remaining ordered work

1. Add independent hooks for ancestor/root, attachment, lock, blob rename and
   backup link/publication with synthetic before/after markers.
2. Resolve the hot-recovery probe to a decisive rollback/data outcome, retaining
   both journal identity evidence and integrity/FK checks.
3. Execute second-user read/write/create/rename/delete/delete-child/traversal
   only with an existing explicitly authorized restricted token. Do not create
   accounts or elevate privileges to make this gate green.
4. Measure 1/2/5/8/16 cooperative processes and P50/P95/P99 open/close, policy
   inventory and worker latency. Keep pins; document Observer sidecar creation.

The read-only Observer protects SQL task state but native pins can create absent
WAL/SHM files. It is not filesystem-write-free. Effective ACL denial, Model-2
confinement and production readiness remain unaccepted.
