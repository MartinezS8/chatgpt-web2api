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

Protected policy sessions also obtain the current principal via the existing
shell-free SID parser and inspect each held root/DB handle with GetSecurityInfo.
The root must satisfy the existing exact protected user/SYSTEM contract; the DB
must satisfy the existing inherited-child contract. Both path and handle
readbacks use the same native descriptor parser and validators. A failed
GetSecurityInfo call has no path-based fallback. The reader borrows its handle
and frees only the returned security descriptor/SID strings; the pin owns and
closes the handles after SQLite closes. These are current descriptor checks,
not effective second-user access proofs or permanent authorization leases.

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

A disposable native prototype pinned main/WAL/SHM/journal files simultaneously.
DELETE commit and WAL initialization failed with SQLITE_IOERR_DELETE (2570).
PERSIST commit succeeded but promotion to WAL failed with the same error. All
reopened databases passed integrity_check after releasing the pins. Therefore
blanket sidecar pins are not integrated: they would break the existing commit
and migration/WAL contract. This is evidence against that proposed shortcut,
not a proof that no maintainable VFS/broker design is possible.

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

## Selective WAL/SHM follow-up

A second native prototype omitted the rollback-journal pin. DELETE and PERSIST
commits, PERSIST-to-WAL promotion, and WAL commit/reopen all succeeded. Protected
policy sessions therefore now pin the main DB's WAL and SHM names as well as
the main file and parent, before SQLite opens, through SQLite close. Missing
sidecars are created as empty regular files under the validated root and receive
the same held-handle child ACL/type/link checks. Existing malformed/reparse or
multiply linked sidecars fail closed. Raw `pin_database` defaults to main-only;
the protected policy always explicitly enables WAL/SHM pinning.

Observer SQL stays read-only and cannot create a missing main DB, but its private
session may create SQLite sidecars. A read-only SQL observer is not a filesystem
nonmutation guarantee. No user tables, callbacks, reviews or dispatches are
mutated by observer methods.

The controlled postflight WAL swap now fails at unlink with PermissionError;
the external synthetic file stays unchanged. Store/Observer/backup regression
tests check WAL and SHM delete denial before SQLite open and release after close.
Owned-child crash tests verify rollback before commit and durability after
commit, with integrity/FK checks after reopening.

This introduces a measured Windows cost: in the native probe SQLite close took
about 2.9 seconds with WAL/SHM pins, compared with approximately zero without
them, because its Win32 VFS retries sidecar deletion. No unsafe early pin release
or unsupported access to CPython's SQLite connection memory is used to hide
that cost. Throughput/latency remain an explicit limitation to evaluate.

The unpinned rollback journal, hot-journal recovery, staging/publish names,
ancestor races and hostile content writes still prevent a general Model 2
guarantee. This targeted fix does not relabel Windows TOCTOU as PASS.

## References

- [CreateFileW access and sharing](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)
- [GetFileInformationByHandle](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfileinformationbyhandle)
- [GetFinalPathNameByHandleW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfinalpathnamebyhandlew)
- [SQLite WAL and read-only sidecar requirements](https://sqlite.org/wal.html)
- [GetSecurityInfo: descriptor of a held object](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-getsecurityinfo)
- [NtCreateFile: native user-mode file operations](https://learn.microsoft.com/en-us/windows/win32/api/winternl/nf-winternl-ntcreatefile)
- [SQLite VFS: OS I/O integration layer](https://sqlite.org/vfs.html)
