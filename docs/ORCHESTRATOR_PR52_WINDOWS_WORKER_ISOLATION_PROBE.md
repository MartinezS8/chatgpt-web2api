# PR-52 – Disposable Windows effective-access probe (diagnostic only)

## Parent / authority

Stack on PR-51. Windows 11 / CPython 3.12, no macOS/Linux CI.

This code adds a **manual, disposable synthetic access diagnostic**. It does NOT
install or launch Codex, log into an account, create Windows users, change an
existing account, elevate permissions, publish a provider prompt or certify a
safe worker. No automatic approval, session send, retry or finalization.

### Safe test procedure on the owner laptop

1. Install the current validated wheel in a Python 3.12 environment.
2. Under the controller Windows identity, explicitly prepare a **new** root:

```powershell
python scripts/probe_worker_isolation.py prepare --label w2a-isolation-probe-abcdef01
```

3. Save the output (root path, controller SID and synthetic sentinel SHA) **outside
   the Git repository**. Confirm the root was newly created. Do not copy private
   controller data into it.
4. Only if an **existing, independently authorized restricted Windows identity**
   is available, run the same installed Python 3.12 script under that identity:

```powershell
python scripts/probe_worker_isolation.py probe --root "<FULL_DISPOSABLE_ROOT>" --expected-controller-sid "<CONTROLLER_SID>"
```

Do not create an account, request passwords in ChatGPT, bypass UAC or change
ACLs on productive data to make the probe pass. Use only the generated synthetic
marker in the disposable `w2a-isolation-probe-*` directory.
5. A same-SID invocation stops immediately with `FAIL_SAME_WINDOWS_IDENTITY`.
   A successful access reports `FAIL_ACCESS_ALLOWED`. Missing paths or I/O
   anomalies are `INCONCLUSIVE`. All denied operations return only
   `OBSERVED_DENIAL_REQUIRES_INDEPENDENT_ATTESTATION`.
6. Independently confirm controller and worker SIDs and verify the same root
   and original sentinel from the controller context. Profile traversal denial
   alone does not prove the particular workspace ACL. Independently check
   controller DB, outbox and credentials are inaccessible to the restricted
   account using disposable placeholders; **never use actual secrets**.
7. After the test, manually inspect and delete **only** the disposable probe
   root, under the controller account. No automatic deletion is offered.

### Test surface

The worker probe attempts reading the primary sentinel, appending to an
independent append-only marker, creating a scratch file, renaming a separate
rename marker and deleting a separate disposable deletion marker. These actions are intentionally
limited to a specially named disposable root. If a check unexpectedly succeeds,
its success is a **failure** of the isolation hypothesis. The script avoids
claiming true attestation or full protection merely because some operations
failed.

The probe does not measure child processes, network egress, process handles,
named pipes, Windows Credential Manager, environment variables or session
cookies. Those are separate prerequisites of a live worker.

### Explicit downstream gates

- Authenticated operator reconciliation under a separately verified trusted
  Windows process identity (PR-51 supplies review only).
- Select and prove a genuine OS-restricted worker context (separate existing
  account, carefully designed AppContainer or hardened VM), with no access to
  controller storage, unrelated user files, GitHub credentials or browser profile.
- Confirm the Codex CLI version and generate its *actual* app-server JSON schema
  without starting a provider turn.
- A fresh, explicit approval specifying the exact harmless prompt, recipient,
  model/effort, one repository/worktree, network scope and one single attempt.
- One pilot turn, durable correlation, no uncertain replay, independent results,
  no arbitrary filesystem writes or merge. Real-worker gate is still BLOCKED.

Same-user hostile TOCTOU remains FAIL; second-user ACL remains NOT TESTED
until independently run; OS-network confinement NOT TESTED.

### Follow-up integrity hardening — PR #58

The prepare command now creates **four synthetically named files** rather than
one. The original `probe-sentinel.bin` is used only for the read attempt; all
potentially mutating checks target their own disposable marker. An unexpected
permissive ACL can report `FAIL_ACCESS_ALLOWED` without destroying or appending
to the original independent attestation marker. The prepare receipt retains
`synthetic_marker_sha256` and additionally includes per-operation marker hashes.
A workspace prepared with the older one-file procedure is NOT equivalent to a
complete new test; create a new disposable workspace for a fresh probe.

This diagnostic still does not attest independent authorization, file system
isolation of actual controller databases, child processes, network boundaries
or credential protection. Do not automatically treat any DENIED outcome as
production authorization.
