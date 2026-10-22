# PR-55 Windows token-bound offline quarantine decision journal

Parent: Draft PR #54 (integrated non-authorizing triage).
This is an internal security COMPONENT, not an exposed CLI, endpoint or service.

## Implemented
- Windows native process TokenUser SID from OpenProcessToken/GetTokenInformation;
  no caller-supplied operator_ref, whoami output, environment variable, or SID
  argument can substitute for this OS token.
- Requires an explicit frozen allowlist provisioned by a TRUSTED controller,
  not by an operator-supplied request.
- Durable cryptographic random challenge; only SHA-256 of nonce stored;
  SID- and attempt-bound, short-lived, monotonically versioned.
- BEGIN IMMEDIATE SQLite transaction with nonce hash, version, actor SID,
  attempt updated_at and single-use CAS, plus UNIQUE attempt decision.
- Authenticated decisions are append-only (SQLite no-UPDATE/no-DELETE triggers).
- Only "delivery_unresolved" can be recorded. It preserves the original attempt,
  outbox and task state. No independent delivery verifier exists yet, so a claim
  of delivery or non-delivery is REJECTED rather than treated as proof.
- No live send, retry, task evidence, release, finalization or merge capability.

## Explicit limitations (security BLOCKED)
This checks the LOCAL PROCESS token. It is not the identity of a remote operator
calling a service. A controller IPC boundary must impersonate and verify peer
tokens, enforce authenticated human intent and load immutable allowlists from a
trusted OS-protected configuration. A caller running code under the same
controller Windows SID can change local code or unprotected SQLite state: hostile
same-SID TOCTOU remains FAIL. A Git worktree is not a security boundary.
Effective second-user ACL access denial remains NOT TESTED until the authorized
Windows laptop runs the separate PR #52 procedure.

No controller service, local operator challenge UI, policy bootstrap, sealed
audit export, externally verified delivery evidence, or real Codex transport is
asserted. The existing legacy caller-supplied operator annotation remains
UNAUTHENTICATED and non-authorizing, and is never promoted to this journal.

## Acceptance / follow-up
1. Exact-HEAD CI: Windows 11 / CPython 3.12 Strict, Ruff, compileall,
   full-history Gitleaks, wheel/sdist, installed CLI/MCP/offline smokes.
2. Test Windows native TokenUser retrieval with a real process; a hosted CI
   process SID test cannot establish a second-user access boundary.
3. Build a dedicated controller IPC peer-impersonation boundary with trusted
   Windows account provisioning and ACL verification, as a separate reviewed PR.
4. Add cryptographically verifiable independent delivery receipt verifier,
   then permit *recording* reviewed delivery evidence. Do not unlock retries.
5. Only after native isolation and an explicit new user approval, plan ONE
   harmless real Codex inference against its actual installed schema.

Developer CI and this Draft PR are NOT production approval.