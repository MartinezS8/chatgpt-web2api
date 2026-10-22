# PR #74 — Conservative same-user/manual duplicate pilot suppression

Parent Draft #73 exact `da112f4e2b4108dde68c820c337b55d8550b841d`. Resolves the *accidental manual repeat*
part of F10: a shared SQLite replay guard under the current Windows
`%LOCALAPPDATA%` atomically records a fingerprint over the trusted Codex
binary hash, effective model slug, effort, exact prompt SHA-256 and resolved
scratch working directory. A later launch with the same parameters but a
DIFFERENT receipt directory fails closed **before Codex subprocess launch**,
and writes a `pre_turn_failure` quarantine with no retry permission.
This keeps the hobby preflight easy, requires no Windows service, and uses
SQLite `BEGIN IMMEDIATE`/UNIQUE to avoid concurrent duplicate reservations.
It is only invoked after explicit `--allow-one-turn`.

The replay registry is *not* a universal provider-side exactly-once guarantee:
changing Windows identity or deleting/moving the registry, using another
scratch directory, or manually changing the fingerprint can evade it. A
timeout, lost ACK, process crash, or completed turn is **never** automatically
retried, regardless of the registry. Live scheduler/outbox/ledger integration
with independent provider receipts is still pending after one authorized
version-correct live pilot. Keep Draft and require exact HEAD CI.

No local account, provider interaction or production permission/merge is
exercised by the GitHub changes themselves.
