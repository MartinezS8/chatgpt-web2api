# Orchestrator V4 / PR-02A — P0 Correctness Hardening

**Source:** `MartinezS8/chatgpt-web2api`, branch `codex/orchestrator-v3-cli-control-plane` at `5f72e60c2195ac3febade7c3aa824941daf69e20`.

## Purpose and boundary

A transport-neutral Python 3.11 SQLite scheduler that **does not** automate ChatGPT, access GitHub/Supabase, dispatch browser operations, or assert external API permission. This patch addresses five reproduced critical scheduler issues before attaching any live worker transport.

## Implemented correctness rules

1. **Quarantine:** `needs_human`, `unknown_delivery`, `verified` and other unresolved active states retain their write scopes and project slot; no concurrent task can claim conflicting scopes.
2. **Global scope lock:** `claim(project_id)` queries active scopes from the entire SQLite authority, not just from that logical project. Same-database multi-process contenders serialize with `BEGIN IMMEDIATE`. A *single controller database* is required for coordinated exclusion; separate copies of the DB do not coordinate.
3. **Conservative scope canonicalization:** validate namespace and nonempty body, reject `..`, `.`, globs, empty path components, absolute paths, backslashes and suspicious syntax; compare scope segments and casefold conservatively for Windows. `repo:src` is a legacy abstract namespace and does **not** establish an authoritative repository identity: PR-02B must map to canonical provider IDs.
4. **Fenced state transitions:** each claim obtains a cryptographically random `claim_token`, incremented `claim_version` and a bounded pre-send lease. `transition()` is a compare-and-set based on expected state and token. A failed or expired `RESERVED → DISPATCHING` transition returns false and the controller must not call `transport.send`. Tokens are redacted from general CLI task/status/list responses.
5. **Non-destructive recovery:** `recover` only requeues *expired*, proven pre-send `reserved` claims. Expired `dispatching` is quarantined in `unknown_delivery`; no automatic resend. Recovery does not revoke a live lease.
6. **Evidence vs release:** a successful `Verifier` moves `RESULT_RECEIVED → VERIFIED` and keeps locks. `NEEDS_HUMAN → FINISHED` and plain `VERIFIED → FINISHED` are forbidden. A separate `finalize_verified` call requires nonempty reviewer reference, operator identity, claim token and existing evidence. This is a **local operator attestation mechanism**, NOT an independently authenticated reviewer or verified GitHub CI approval. That hardened policy is planned for PR-04 and is required before unattended merges.
7. **Legacy DB migration:** an existing V3 SQLite DB receives new columns without dropping stored tasks. Nonterminal V3 records that lacked fencing tokens are quarantined as `needs_human` rather than being guessed safe to resume or resend. Operators must reconcile them; test data before upgrading. A backup/restore migration system is planned for PR-02C.

## Tests executed

```bash
PYTHONPATH=src python -m pytest -q tests/test_orchestrator.py tests/test_orchestrator_cli.py tests/test_orchestrator_multiprocess.py
# 33 passed, 8 subtests passed (Python 3.13, local Linux test runner)
python -m compileall -q src
```

The test suite includes cross-process SQLite contention using the Windows-safe multiprocessing `spawn` method; both five-slot and globally exclusive DB lock invariants pass. It exercises scope-root rejection, pre-send expiration, stale token fencing, legacy V3 migration, quarantine, approval-gate separation and an injected recovery-vs-dispatch race.

**Not established:** full upstream suite; Ruff; GitHub Actions; Windows CI; production migrations; real browser tabs; user-plan/model/connector entitlement; safe usage authorization; external reviewer provenance.

## Known residual risks / required next PRs

- **PR-02B:** Canonical real provider resources (`github:<owner>/<repo-id>:<path>`, `supabase:<project-ref>:<environment>`), branch/worktree IDs, credential-bound write policy, symlink/case consistency, cross-database advisory coordination when more than one scheduler DB exists.
- **PR-02C:** Durable immutable TaskPackages + append-only dispatch outbox, atomically committed attempt IDs, heartbeats and renewal of long-running dispatch leases, recovery/reconciliation by remote message identity, schema versioning and migration backups, audit retention and atomic backups.
- **PR-03:** Worker registry and distinct transport session/target IDs. One Codex stdio session does not imply five independent ChatGPT conversations.
- **PR-04:** Cryptographically/provider-verifiable evidence and separate review/approval policy tied to immutable commit and CI run IDs; `finalize_verified` currently only asserts strings and is *not* safe for unattended approval.
- **PR-05+:** CLI/MCP adapter, permissions, rate limits, model selection fail-closed, operator UX, account/legal authorization and Windows service supervision.

## Operational warnings

- `claim_token` is a *fencing* token, not a standalone authentication or authorization token. File-system permissions and process identity remain necessary, especially on Windows.
- No exactly-once delivery guarantee to ChatGPT Web is offered. If the external send's acknowledgement is unknown, quarantine and manual/provider-supported reconciliation are mandatory.
- Existing V3 `needs_human` rows with ambiguous effects stay quarantined. Do not clear them just to free capacity.
- This change deliberately does not alter Octo-Lex's browser or MCP logic and does not require CLI-Anything installation.
- Keep it on a separate draft PR and do not merge to `master` until complete CI and review.
