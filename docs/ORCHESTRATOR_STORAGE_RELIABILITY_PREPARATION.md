# Phase C isolated preparation — not accepted

Local candidate on Phase B implementation `7fc09748c07e5678dda24c0f9b42d22e476583b4`.
Phase B's security acceptance remains partial. This branch is intentionally
local and is not a claim of an accepted Phase C or real-worker readiness.

The isolated eight-process initialization probe reproduced two Python 3.12
failures at `PRAGMA journal_mode=WAL` with SQLite BUSY, after migration had
committed. Integrity remained ok. The normal SQLite busy handler does not
prevent every journal-mode promotion race.

Candidate fix retries only native SQLite BUSY/LOCKED result codes (including
extended codes), with a monotonic ten-second retry budget. Corruption, I/O
errors and a refused WAL mode fail closed. Existing connection busy timeouts
still apply independently. Unknown schema/integrity checks and migration
quarantine run before WAL promotion as before.

Regression tests exercise transient retries, extended codes, deadline,
nonlock/unknown errors and refused journal mode. Parallel process probes and
full local strict gates must validate this candidate; hosted cross-platform
evidence is deliberately not claimed. Publication/integration waits for the
Phase B gate or an explicitly revised development plan.
