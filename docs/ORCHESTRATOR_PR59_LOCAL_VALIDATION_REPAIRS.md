# Local validation repairs after PR #58

Base: Draft PR #58, exact SHA 00f8d4f5c9c9faa004497a07f22932df70ccb4db.
Windows 11, CPython 3.12.10; all account-backed E2E tests remain disabled.

## Reproduced defects

1. The missing-marker test failed locally and in PR #58 CI run 39830386227
   (1 failed, 1444 passed, 2 skipped, 20 subtests passed). Opening the append
   marker with `ab` created a missing marker and returned ALLOWED. The probe
   now opens with O_WRONLY/O_APPEND/O_BINARY without O_CREAT. Its regression
   additionally asserts that no missing marker was created. The primary
   attestation marker remains untouched.
2. Local native Codex CLI 0.163.0-alpha.11 generated 318 JSON schema files,
   totalling 3,629,800 bytes, exceeding the arbitrary 300-file cap. The
   diagnostic now permits at most 1024 files with a 64 MiB aggregate cap;
   the existing 25,000,000-byte per-file cap remains. Regression coverage
   accepts 318 synthetic schemas, rejects 1025 and rejects excessive total
   size without publishing a successful readiness receipt.

## Local evidence

The 18 focused schema/isolation tests passed, and Ruff passed. The corrected
native schema diagnostic succeeded with an explicit absolute executable path
and exact expected version. Receipt and schemas remain outside the repository
under LOCALAPPDATA/w2a-validation-phase58/schema-fixed-20261022.
Only `--version` and `app-server generate-json-schema` were executed. No
authentication, model/list, thread/start, turn/start or provider operation ran.
The executable version is an alpha version: schema generation is not proof of
runtime model availability or protocol interoperability.

Full strict offline verification, wheel/sdist installation and exact-head
GitHub checks must be evaluated separately. Focused tests are not full release
evidence. No real worker is authorized. Hostile same-user TOCTOU remains FAIL;
effective second-user denial and network confinement remain NOT TESTED.
