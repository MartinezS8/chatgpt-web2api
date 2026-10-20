# Phase C candidate — draft review, acceptance blocked

Candidate based on Phase B implementation `7fc09748c07e5678dda24c0f9b42d22e476583b4`.
It is published for draft review at the user's direction while Phase B's
security acceptance remains partial. Draft publication does not accept Phase C
or establish real-worker readiness.

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
nonlock/unknown errors and refused journal mode. The original candidate commit
passed local strict gates on Python 3.11 and 3.12 and five synchronized batches
of eight processes per version. Hosted cross-platform evidence is tracked on
the draft PR. Integration/acceptance remains blocked pending Phase B security
evidence and review of this candidate.
