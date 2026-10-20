# Phase B: Windows filesystem security — partial gate

Base: Phase A `4c37532aaed2e6ea110829d0c30408f643dbef21`, exact-SHA
CI run 39483369869: six matrix jobs and package build succeeded.

## Implemented scope

New workspace provisioning explicitly sets its new empty root's owner to the
current SID. Native readback via GetNamedSecurityInfoW, GetAce and
GetSecurityDescriptorControl then requires that owner, a protected DACL and
exactly the current SID and SYSTEM with inheritable full-control allow ACEs.
Null DACL, unknown ACE layouts, extra trustees, inherited ACEs, incomplete
rights and an unexpected owner fail closed. Only a new empty workspace is
modified. Errors still invoke the existing cleanup path; no legacy ACL repair.

The staging directory check now rejects Windows ancestor reparse points,
not merely a junction at the final root. Lockfile preflight rejects nonregular
files. These checks are observations, not atomic bindings of later path I/O.

| Threat / guarantee | State | Boundary |
|---|---|---|
| Exact newly provisioned owner/DACL readback | Tested locally | Current Windows process, new disposable workspace |
| Extra trustee / unprotected DACL | Rejected | Exact descriptor policy; no heuristic fallback |
| Legacy ACL modification | Prohibited | Provisioning refuses an existing workspace |
| Existing ancestor junction | Rejected | Point-in-time preflight |
| Cooperative V2 writer versus cleanup | Phase A tested | Trusted private directory, shared lifetime lock |
| Effective denial to another Windows user | NOT TESTED | No authorized token or login available; no account created |
| Hostile concurrent ancestor replacement | NOT GUARANTEED | Native handle-relative publish/link/unlink not implemented |
| Arbitrary untrusted writable root | UNSUPPORTED | Must not be treated as a secure storage boundary |
| Full >260 path workflow | Open native validation | No registry or manifest changes; skipped tests are not PASS |
| Power loss / NTFS durability | NOT TESTED | Process crashes are distinct |

## Native API evaluation

CreateFileW with FILE_FLAG_OPEN_REPARSE_POINT does not itself establish
ownership of every ancestor. GetFinalPathNameByHandleW reports the resolved
path of an opened object; a string comparison does not pin future publication
or removal. GetSecurityInfo could inspect a pinned handle, but the rest of
Python path-based SQLite/blob operations would still need an audited
handle-relative design. No universal race-free wrapper is claimed here.

References: [CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew),
[GetFinalPathNameByHandleW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfinalpathnamebyhandlew),
[GetSecurityInfo](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-getsecurityinfo),
[GetAce](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-getace).

## Abnahme blockers

Phase B must remain PARTIAL even if its diagnostic CI passes. DACL readback
does not replace a second-user read/write/delete attempt. Existing storage
entry points still support explicit legacy paths and do not globally enforce
private-root provenance. Using untrusted roots remains blocked, pending an
audited enforcement/handle-relative design and native hostile-race tests.
Phase C may therefore be prepared and tested only in isolation, not accepted
as a complete storage-integration gate. No real workers or production release.
