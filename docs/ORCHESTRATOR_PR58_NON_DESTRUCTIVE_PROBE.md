# PR-58: Non-destructive synthetic Windows isolation probe

Parent Draft PR #57 at `60a9b907b072b0955a37c9f181fa5be7f8c0ec7c`. The existing PR #52 probe performed
append, rename and delete against the same primary sentinel used for external
attestation. If a restricted account unexpectedly had access, the primary
marker could be changed or deleted, weakening the post-test independent
fingerprint check.

Prepare now writes four small synthetic markers (read, append, rename, delete).
The probe operates on separate marker paths. Unexpectedly allowed access is
still a FAIL, but the primary read marker stays unchanged even when ALL five
operations are allowed. Create remains a scratch-only operation. Receipt
includes checksums of the extra operation markers; existing primary
`synthetic_marker_sha256` remains intact for backwards reporting. New Windows
unit tests exercise permissive access and missing-marker fail-closed behavior.
The older one-sentinel workspaces are NOT accepted as complete test evidence.

No Windows account, permission, credential, elevation or production directory
is modified by this code in CI; all simulated tests are synthetic and under
pytest tmp_path. Running on user's laptop still requires an existing authorized
second identity and explicit owner action. Hostile same-SID TOCTOU FAIL.
Do not use diagnostic outcome to authorize workers or any live send.
