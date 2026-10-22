# PR #60 — Offline Codex fixture/schema audit

Parent Draft PR #59 HEAD `803069dbe76dee139fe04a2ad85589cb2b9873d5`.

The CLI `scripts/audit_codex_schema_fixture.py` verifies all 318 (or other
version-specific) JSON Schema files against the hashes from the already
captured `offline-readiness.json` receipt. It never starts Codex or contacts
an account. It can list names and validate an **explicit** local request or
response fixture using JSON Schema. No guessed method-to-file mapping and no
silent coercion. Incompatible response returns exit code 2; missing/altered
schemas cause an error.

Use on Windows 11 with the same Python 3.12 environment as the project:

```powershell
py -3.12 scripts/audit_codex_schema_fixture.py --schema-root "$env:LOCALAPPDATA\w2a-validation-phase58\schema-fixed-20261022" --list
py -3.12 scripts/audit_codex_schema_fixture.py --schema-root "<CAPTURED_DIR>" --schema "EXACT_RELATIVE_SCHEMA_FILE_FROM_LIST.json" --fixture "<JSON_FIXTURE_FILE>"
```

Only schema files present in the captured manifest are eligible, and all their
SHA-256 values must match. Relative `$ref` can be resolved from captured
schemas in memory. No remote schema retrieval is permitted.

**Acceptance:** Use the *real generated schema*, and independently capture or
author **redacted, synthetic** 0.163 request/response fixtures with exact
paths. Validate the formerly mismatched `thread/start` response and document
the changes to `approvalsReviewer`, `sandbox`, and `thread.source`.
The regression test in this PR uses a fake small schema to prove the reject
behavior; it is **NOT** proof that current 0.163 schema validates the old mock
adapter. Schemas stay outside GitHub. The existing 0.157 fake is retained and
must not be silently treated as a 0.163 runtime adapter.

No login, model/list, thread/start, turn/start, live Codex process,
automatic retry, approvals, merge or production permission is introduced.
