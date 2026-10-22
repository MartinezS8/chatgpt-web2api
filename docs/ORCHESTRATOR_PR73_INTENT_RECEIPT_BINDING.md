# PR #73 — Tie pilot result/quarantine receipts to original send intent

Parent Draft PR #72, exact `81e6db5b0bf846461862d279574ceca14b438f56`. Adds a SHA-256 link between the
fsynced, creation-exclusive `intent.json` and subsequent `result.json`
or `quarantine.json` records. The read-only inspector verifies this link
when present and returns `INCONSISTENT_RECEIPT` for mismatches, while marking
older receipts without a hash as **not bound**. Future receipts never silently
reuse an existing directory, and `retry_permitted` remains false.

This prevents accidental cross-attempt file mixups but is NOT an
independent provider receipt: a process with the same filesystem access can
change both the intent and the computed digest. The pilot is not yet
integrated into the canonical scheduler/outbox/ledger, and repeated manual
launches using a new receipt path are not globally deduplicated. Do not claim
end-to-end exactly-once or automatic production release. After one genuine
authorized experiment, Codex should integrate validated RPC events into the
canonical persistent store and separately implement trusted delivery evidence
and recovery before two/five real workers.

All new test cases are offline. No account, provider, GitHub merge or
local Windows access has been performed from ChatGPT.
