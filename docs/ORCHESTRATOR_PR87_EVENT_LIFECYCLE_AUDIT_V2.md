# PR #87 – No-turn local audit hardening (stacked on PR #86)

Base HEAD: `1d31fd8d2df6bce1c8bf2e9ba14bb2782499b344`. Offline-only code and synthetic fixtures.
No provider, browser, account discovery, thread/start, turn/start, merge
or deployment initiated by this PR.

## Correctness contract

* Each observed `item/started` must have one matching `item/completed`
  with identical bounded ID and type, without duplicates or state reversal.
  Terminal `turn.items` must reconcile to the completed observed item IDs
  and types. Snapshot duplicates, missing entries and open items mark
  `item_lifecycle_consistent=false` / no clean status.
* All notifications after a terminal event (except the separately detected
  duplicate terminal) mark an unsafe post-terminal observation, including
  nominally safe deltas. EOF and successful local process termination are
  still required for a successful local observed-stream drain.
* Safe turn/item/model notifications require matching thread/turn IDs.
  Thread-start notifications are validated by nested thread ID. Item deltas
  require an already observed item ID. Unknown/uncorrelated notifications
  mark the observation unverified without embedding raw payloads.
* Audit receipt version **2** adds an explicit lifecycle-consistency field.
  Old version-1 receipts do not silently qualify for version-2 clean status.
  Output and tool payload remain redacted. A lack of observed tool events
  is **not** an independent absence-of-tools guarantee.
* The old 0.157-style fake remains an offline test stub; synthetic
  lifecycle cases cannot validate the real 0.164 transport or versioned
  generated schema. The app-server result schema is still pinned to the
  actual local executable and checked before issuing a model turn.

## Remaining independent gates

Actual Codex 0.164 generated-schema fixture and native app-server behavior,
MCP status, read-only file access and Windows worker-isolation guarantees are
NOT verified here. Canonical outbox and review ledgers stay mock-only.
Unknown delivery remains quarantined with **no automatic replay**. A real
worker and all productive finalization remain BLOCKED.


Multiple final agent messages are conservatively marked
`ambiguous_final_answer`: a correct **last** message cannot conceal an
earlier unexpected final message and produce a clean pilot receipt.


Terminal `params.turnId` is optional for the pinned protocol shape.
If supplied, it now must agree with the nested `turn.id` and the
acknowledged turn ID. A conflicting top-level identifier results in
quarantine and no retry, even if the nested ID is correct.


The terminal `agentMessage.text` is compared against a transient SHA-256 of
the corresponding completed item, keyed by item ID. Missing or contradictory
terminal text fails the observed lifecycle check even if a previously received
final answer equals `ORCH_TEST_OK`. Neither unexpected output nor its digest
is written to diagnostic receipts.
