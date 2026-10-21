# Protected storage boundary

Base: PR42 `196e096c66b7628df236f3c7172d87e3f1e48a26`.

## Contract

`PrivateStoragePolicy.open(label)` is an explicit native Windows policy.
`Store(policy.context.database, storage_policy=policy)` propagates that same
policy to TaskPackages and Store-backed services. Every Store connection
reopens the label through the native workspace loader before SQLite opens.
The factory result is not a bearer credential: even freely constructed policy
objects must pass native readback and match the original root/DB/blob binding.
The public Store policy cannot be reassigned. Arbitrary Python execution in
the controller process is trusted and is not sandboxed by these classes.

The database is exactly `controller.sqlite3`, blobs exactly `blobs`, inside
the checked root. Existing children, including WAL/SHM, locks and backup files,
receive owner/ACL/type/reparse validation. Arbitrary nested directories are
unsupported. Prompt and attachment inputs must be absolute in-root files.
SQLite temporary tables use memory in protected mode. Missing blob roots are
rejected; provisioning remains explicit. No existing legacy DB is moved.

Packages validate their Store's policy and paths before initialization,
sealing, snapshotting and reading. Scheduler and Outbox reject mixed policies,
even for identical DB strings. Staging checks before lock creation and again
after lock acquisition. Backup validates its fixed DB and guarded parent.
The private CLI propagates policy into these APIs; the read-only MCP entrypoint
also supports `--private-workspace LABEL` and rejects a simultaneous DB/env
override. Native provisioning reopens its result before claiming success.

Omitting policy explicitly selects the historical offline legacy APIs. Legacy
paths are not private-storage evidence. No restore API is introduced: external
manual restores have no protected assurance until the resulting workspace is
reopened and validated. This policy grants no provider/send capability.

## Threat models and unresolved gate

Model 1 is a verified private root with cooperative processes. Point-in-time
native ACL readbacks and shared policy reject configuration/path injection and
revocation observed at operation boundaries. OS access errors propagate.

Model 2 is a hostile process able to rename or replace relevant objects between
checks and use. It remains unsupported. Repeated checks and cooperative locks
do not make path-based sqlite3/open/link/replace/unlink handle-relative.
Holding a Windows identity handle does not bind Python SQLite's independently
opened paths. The protected policy pins main, WAL and SHM names for selected
SQLite sessions. Store migration also pins its rollback journal while using
PERSIST mode for that migration connection. Other journal, ancestor, staging
and publication operations are not bound to a verified directory handle. A
comprehensive solution would require a larger native I/O/VFS design and
adversarial testing; Model 2 remains unsupported.

When Windows startup finds a nonempty regular rollback journal, SQLite first
recovers it while the main database and WAL/SHM names remain pinned but the
journal name is unpinned so DELETE-mode recovery can remove it. The migration
connection then pins the journal before opening SQLite. That recovery preflight
uses a path-based journal check; hostile swaps during that narrow window remain
unsupported.

Protected Store construction is serialized by a SID- and database-path-keyed
named mutex within one Windows session. It is held from before SQLite pins
through migration and WAL promotion. This handles simultaneous initializers
that follow the protected API, including abandoned owners, but is not an ACL or
hostile-process boundary. Raw SQLite/legacy callers, other sessions and
processes that bypass or pre-create the mutex are outside this coordination
guarantee.

Effective denial to a restricted second user remains NOT TESTED without an
already authorized test token. No account/ACL outside disposable test roots
is changed. Protected-boundary CI is developer diagnostics, not acceptance of
hostile TOCTOU resistance, real workers or production.

References:
- https://learn.microsoft.com/en-us/windows/win32/api/fileapi/ns-fileapi-by_handle_file_information
- https://learn.microsoft.com/en-us/windows/win32/fileio/reparse-points-and-file-operations
- https://sqlite.org/c3ref/open.html
- https://sqlite.org/wal.html
