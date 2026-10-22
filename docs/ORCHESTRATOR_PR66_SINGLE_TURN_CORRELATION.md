# PR #66 — Manual single-turn correlation and receipt clarity

Parent Draft PR #65 exact `acba745bcf76c8545217e8d3a4bb2c10470a010a`.

The original pilot records all errors as if a provider turn might already
have been sent. It is conservative, but it prevents the operator from
distinguishing an RPC/schema failure **before** any `turn/start` from an
ambiguous status **after** a `turn/start` write attempt.

The catch path now includes `turn_start_may_have_been_sent`. It is derived
only from the actual `_OneTurnWire` send-attempt counter, never user input,
and records `pre_turn_failure_no_turn_start_attempted` versus
`needs_human_unknown_or_unverified_delivery`. No new auto-retry authority
is inferred: receipt paths remain one-use and all failures have
`retry_permitted: false`.

While waiting for the next RPC ACK, a `turn/` or `item/` notification
appearing **before any `turn/start`** is rejected. A premature
`thread/` event before initialization is rejected. At terminal handling,
nested `turn.id` in progress notifications must match the acknowledged turn,
not just an optional top-level `turnId`; foreign subturn events fail closed.

Synthetic tests cover all these cases, including lost ACK after one
outbound turn. No real Codex executable/provider interaction is performed
by this PR. The existing real-version wire-schema selectors are still
mandatory for any explicit later manual live trial.

## What this does not solve

No native Windows account isolation, no canonical scheduler/outbox
integration, no live model validation on this host and no replay/recovery of
an actually sent provider turn. For hobby use, an empty scratch worktree is
a pragmatic default; do not claim a Windows read-only sandbox denies all
same-user file access.
