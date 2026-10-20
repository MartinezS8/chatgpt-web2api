# Recovery consolidation — Phase A

Base: PR #36 `98aadd26d6e3f0c4f1243e6e83932e8df1dc5113`.
Reference only: PR #37 `9ff52cf84dd100039d83eec87c7b33452281f477`.
Both derive from PR #35 `757df4a48d148d85bb280013e020c59672127766`.

| Capability | PR 36 | PR 37 | Consolidation |
|---|---|---|---|
| Cooperative thread/process lifetime lock | Yes | No | Preserve 36 |
| Strict managed V2 names, explicit locked cleanup | Yes | No | Preserve 36 |
| Legacy stage preservation | Yes | Read-only only | Preserve, add explicit manual-review label |
| Default inventory without DB or filesystem writes | Yes | Yes | One existing `staging-audit --root` interface |
| Size and nanosecond modification time | No | Yes | Add `size_bytes`, `mtime_ns` without absolute paths |
| Nonregular-file handling | Ineligible | Excluded | Explicit `entry_type`; never cleanup nonregular entries |
| Active writer and hard-exit observation | Yes | Yes | Reuse crash tests; add open legacy writer/process tests |
| Source-fd identity validation | Yes | No | Preserve 36 |
| POSIX canonical ancestor aliases | Fixed | Broken on macOS | Preserve 36, do not copy alternate scanner |
| Hostile Windows reparse races | Not guaranteed | Not guaranteed | Remains unverified; Phase B |

Public APIs remain `inspect_stages`, `cleanup_managed_stages`, and
`staging-audit --root`. No `staging_audit.py` or alternate `audit-staging`
command is introduced. Existing DTO fields remain; added fields are additive.
Legacy and nonregular entries are `manual_review_only`; managed regular files
are `cooperative_locked_review`, which is not proof that their writer is dead.

Nonfinite or negative ages and nonfinite clocks fail before lock creation.
Files disappearing during inspection are skipped; permission failures propagate.
Deletion rechecks regular-file identity and current age while holding the lock.
Only cooperating V2 writers in trusted private directories are protected.
Historical stages are never deleted. CLI deletion still requires explicit opt-in
and an age of at least one hour. No live sends or productive finalization.

PR 37 may be recommended as superseded after the new exact-SHA six-job matrix
and package gate pass; this task does not close it. The existing PR 36 run
39438509307 passed all six jobs and build; PR 37 run 39464021523 failed both
macOS jobs and skipped build. Neither result attests this new revision.
