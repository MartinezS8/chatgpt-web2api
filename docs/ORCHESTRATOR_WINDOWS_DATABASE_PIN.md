# Windows main-database identity and lifetime

Base: PR43 `0b570c0e44614276ab92ada746ce512635259804`.

## Decision

Protected Store connections, Observer queries and SQLite backup source
connections now use `PrivateStoragePolicy.database_session`. This is a scoped
main-file pin, not a handle-relative SQLite VFS. Legacy APIs are unchanged.

The session validates policy, opens the direct parent and main database using
`CreateFileW` with GENERIC_READ, READ|WRITE sharing and no DELETE sharing, then
revalidates policy before SQLite opens. Store initialization can create an empty
main file; Observer and backup require an existing file. Non-inheritable handles
remain held until SQLite closes, including on failures. Acquisition/inspection
errors fail closed, and partial acquisition closes every acquired handle.

Handle inspection rejects reparse points, wrong types and multiply linked main
files. `GetFileInformationByHandle` supplies volume/file identity of the opened
object; `GetFinalPathNameByHandleW` checks its reported path. Only local drive
paths are supported; UNC/device paths fail before native acquisition. No ACLs
are changed by pinning.

## Evidence and limits

The regression reproduced main-file deletion by a separate process between
policy preflight and SQLite open on the base. With pinning it observes WinError
32. Native tests cover first initialization, parent rename denial, nested pin
identity, exception cleanup, missing read sources, hardlink/symlink rejection,
spaces/Unicode, WAL read/write, backup, and Observer/backup source pinning.

A prototype using only FILE_READ_ATTRIBUTES did NOT block deletion on the
tested Windows runtime. Do not replace the actual read handle with a metadata
handle to avoid permission/sharing errors.

This mitigates one main-file replacement window. Model 2 remains unsupported.
Ancestor replacement, acquisition races, attribute changes, WAL/SHM/journal
names, blobs, staging, backup publication and hostile content writes are not
bound to this handle. A limitation test confirms that an unheld sibling WAL
filename is still deletable while the main database is pinned. SQLite still
opens independent path strings; no complete confinement guarantee is claimed.

A comprehensive native VFS or broker remains a separate design/test gate.
Do not precreate or permanently lock journals without proving SQLite recovery
behavior. WAL sidecar lifetime also differs after crashes/read-only clients.

Native five-Store concurrency exposed a disappearing SHM during the existing
ACL inventory. The loader now restarts the complete native validation at most
three times, only if an exact main-DB WAL/SHM/journal child disappears during
inspection. It never skips a child validation. Persistent instability raises
the original FileNotFoundError; missing sources, ACL denials, reparse/type and
other I/O errors are not retried or ignored. Four additional regression cases
cover successful complete retry, bounded failure, ACL denial and missing source.

| Gate | Status |
| --- | --- |
| Windows handle identity | PARTIAL: main-file observation/lifetime only |
| General Windows TOCTOU protection | FAIL: Model 2 remains open |
| Effective second-user read/write/delete denial | NOT TESTED: no authorized restricted token |
| Real workers / production | NOT TESTED |

## References

- [CreateFileW access and sharing](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)
- [GetFileInformationByHandle](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfileinformationbyhandle)
- [GetFinalPathNameByHandleW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfinalpathnamebyhandlew)
- [SQLite WAL and read-only sidecar requirements](https://sqlite.org/wal.html)
