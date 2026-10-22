# Phase 48c: durable offline delivery ledger

This phase adds SQLite correlation and crash recovery for the **bundled offline
fake App Server only**. It does not add a real Codex executable adapter, a
provider send capability, result evidence, review approval, or a task finalizer.

## Durable boundary

`AppServerDeliveryLedger` shares the canonical `Store` database and is bound to
the canonical `DispatchOutbox`. Its versioned schema is initialized under
`BEGIN IMMEDIATE`; unknown schema versions and unversioned partial layouts are
rejected. Each attempt records the immutable controller, worker, account,
project, task and outbox attempt identifiers; mock transport identity hash;
sealed package hash; claim-token hash and claim/assignment versions; prompt
hash; request/notification metadata; and thread/turn identifiers after the
synthetic peer correlates them. It does not persist prompts, request/response
bodies, claim tokens, worker session keys or their hashes in MCP output. Operator
references are hashed before persistence.

For every outgoing JSONL frame, the ledger commits a send intent before the
fake transport writes bytes. It commits `written` only after stdio flush and
commits an acknowledgement only after the protocol contract accepts the
correlated response. The `initialized` notification is also journaled. A
process loss with outstanding or unverified messages is quarantined on
`recover_pending()`; it never recreates a send permit. The existing outbox
attempt remains unique per task, which also prevents this ledger from creating
a second attempt.

The offline fake's terminal event records `transport_completed_unverified`,
marks the outbox `offline_simulated_unverified`, and leaves the task in
`needs_human`. No `result_ref`, `evidence_ref`, approval, or finalization is
created. Reconciliation is read-only. Operator dispositions are append-only
audit annotations and cannot unquarantine, retry, attach evidence, or finalize.
The supplied operator identity is unauthenticated attribution metadata, not an
authorization credential; an authenticated override that resolves delivery is
not implemented in this offline phase.

## Read-only MCP observer

The existing observer has a bounded, fixed-query `app_server_delivery` view and
the stdio server exposes `orchestrator_app_server_delivery`. It returns only
safe identifiers, state, timestamps, hashes that are safe for status reporting,
and bounded request/event metadata. It does not return claim/session material,
prompt hashes, or request/response hashes. The control dispatcher remains an
explicit tool whitelist and rejects extra mutation arguments. The observer does
not migrate the schema or update state.

## State and safety limits

```text
prepared -> running_offline_fake -> transport_completed_unverified
                              \-> unknown_delivery
                              \-> needs_human
prepared --restart-before-message--> not_sent_recovered
```

All terminal states are non-retry states in this ledger. `turn/completed` is
only synthetic transport protocol evidence. It is not task completion, a
review decision, provider evidence, or human approval. Reopening a thread does
not authorize a new turn. There is no real transport or authenticated operator
override that can release the task.

The ledger does not claim protection against a hostile same-user process that
can modify the SQLite database or replace filesystem objects. Windows hostile
same-user TOCTOU remains **FAIL**; effective second-user ACL denial remains
**NOT TESTED**. The bundled fake runs in the local user's Python security
context, and same-user processes are not an OS isolation boundary.

## Local test coverage

The regression tests cover successful synthetic correlation, hashes-only
ledger content, worker/claim/prompt mismatch rejection, restart no-replay,
duplicate and conflicting acknowledgements, observer redaction and mutation
rejection, future-schema rejection, and crash boundaries before write, after
write, before and after acknowledgement persistence, and after terminal event.
All prompts, IDs, packages and receipts in these tests are synthetic. The test
suite does not exercise a real Codex process or provider.

See `ORCHESTRATOR_PHASE48B_REAL_TRANSPORT_READINESS_REPORT.md` for exact
verification receipts, phase status and remaining gates.
