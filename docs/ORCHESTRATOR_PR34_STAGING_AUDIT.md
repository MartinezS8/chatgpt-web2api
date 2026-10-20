# PR-34 — Read-only staging inventory and crash-recovery boundary

Parent: Draft PR #35, SHA `757df4a48d148d85bb280013e020c59672127766`.

## Delivered
- `inspect_staging_directory(directory)` inventories only direct child regular files
  with `.staged-` or `.sqlite-snapshot-` prefixes, without following symlinks.
- Emits path, byte length, modification timestamp, category and fixed
  `manual_review_only` status. Does not open files for writing, change
  permissions, or delete/rename anything.
- Regression coverage includes active open writers and symlinks.
- Existing blob/SQLite writers are untouched; their `finally` cleanup remains.

## Why no automated orphan cleanup
A hard process termination bypasses `finally`. Age-based deletion is **not
safe**, because a live upload/backup can be paused or slow. Filename age, PID
files and advisory heartbeats alone do not prove that a writer is dead.
The scanner intentionally does not claim that listed candidates are safe to
delete. A future cleanup design needs cross-process writer ownership with
provable non-racy exclusion, no-follow handle-based operations and a carefully
reviewed crash protocol, before any destructive cleanup is enabled.

## Open high-priority gates
1. **Windows TOCTOU:** path-component reparse checks are point-in-time checks.
   A malicious concurrent path replacement remains possible. Require trusted,
   private parent directories and independently reviewed handle-based open
   semantics before making file-system isolation guarantees.
2. **Actual second-user ACL denial:** has not been tested; do not mark PASS.
3. **Windows long paths > 260 characters:** not verified.
4. **Hard-crash scenarios:** current tests do not prove race-free cleanup after
   a real abrupt exit. The scanner deliberately avoids destructive actions.
5. **Real ChatGPT/provider transports:** absent; no authorization implied by CI.

## Verification
Local standalone scanner logic: four narrow Python tests passed against a stub
for the existing reparse-path helper. This is *not* full repository, Windows
or CI evidence. Dedicated repo tests and exact-commit developer diagnostics
must be inspected separately. Feature-branch GitHub Actions are untrusted
diagnostics, not protected deployment/finalization authority.
