# PR #72 — Relative schema refs and RPC title identity (F05/F11)

Parent #71 exact SHA `e04c143447ef282dac5d2b86f8913950b5f73b3f`.

The previous validator registered each captured schema under its file URI
but validated a *different* unbound root object for files without `$id`.
Relative cross-file `$ref` resolution could fail even when both files were
captured. `build_local_schema_registry()` now injects the original file
URI as `$id` into an **in-memory copy** of each no-id document and
instantiates validators from that copy. The original JSON schema and
sha256 manifest stay unmodified, and network/uncaptured file fallback
remains impossible.

If the local selected file declares a JSON Schema `title`, that title must
match its selected RPC role, for example `ThreadStartParams` for
`thread_params`. The canary tests still reject broadly permissive schema
choices. A schema without `title` cannot be identified independently:
the operator/Codex must inspect the *real* 0.163 generated schema and verify
the four selections before a live pilot. This is not an assertion that the
installed version has been tested.

Adds a synthetic cross-file reference fixture and an explicit wrong-title
regression; no account/provider/Windows action or merge performed.
Terminal exact-HEAD hosted Windows strict and package smoke remain mandatory.
