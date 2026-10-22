# PR-57: Snapshot-bound operator challenges (offline, non-authorizing)

Stacked on PR #56 exact parent `66b2d9b20798f4c4e90f0d5c9ed8a07eb91e2591`. The earlier PR #55 compared
the attempt's updated_at but not the entire joined task/outbox/ledger state.
It could therefore accept a stale challenge after changes within allowable
review states. The new HMAC-SHA256 binds the one-time nonce to a canonical
attempt ID, task ID, statuses, timestamps, claim and assignment versions,
and the prompt/claim hashes inside the same SQLite BEGIN IMMEDIATE transaction.
On commit the snapshot is recomputed under a write lock, before CAS.
Any drift invalidates the nonce without writing a decision.

Outstanding legacy nonce-only digests are rejected and require reissuance.
The persistent column `nonce_sha256` stores a snapshot-bound HMAC now; its
existing name remains for backwards schema compatibility.
Added negative tests for task/outbox/assignment changes and legacy digest.
Only inert `delivery_unresolved` remains supported. No quarantine
release, retry, send, evidence, approval, or finalization.

Not a trusted IPC impersonation layer, nor a remotely authenticated human.
Same-SID hostile TOCTOU remains FAIL; SQLite triggers do not protect against
same-user DB replacement. Effective Windows restricted-user ACL denial,
installed local Codex, account models and live inference are NOT TESTED.

Require terminal Windows Python 3.12 strict tests, Ruff, compileall, Gitleaks,
wheel/sdist and installed CLI/MCP smokes on exact HEAD. Keep Draft, no merge.
