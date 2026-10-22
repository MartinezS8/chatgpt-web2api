# PR #64 — Real pilot: explicit pinned wire schemas before each step

Parent Draft PR #63 exact commit `f5fa2ea34f2628bdd84761c1c1d3106942c74797`.

The previous pilot verified the Codex binary/schema **manifest**, but did not
enforce that the concrete payloads and responses sent by its live
`thread/start` and `turn/start` RPCs match schemas from that bundle.
The installed alpha version `0.163.0-alpha.11` is known to differ from older
synthetic `0.157` fixtures. That omission is addressed here.

The manual pilot now requires FOUR explicitly selected, distinct paths relative
to the **same captured schema directory**:

- `--thread-params-schema` — schema for the `thread/start` params object
- `--thread-result-schema` — schema for the `thread/start` result object
- `--turn-params-schema` — schema for the `turn/start` params object
- `--turn-result-schema` — schema for the `turn/start` result object

All schema JSON files are re-hashed against the offline-readiness manifest
before a live app-server process starts. Each selected schema is instantiated
from the in-memory pinned resource registry, without remote URI fetching.
The request params are checked **before writing to the pipe**, and the result
is checked **before advancing to the next RPC**. In particular, an incompatible
`thread/start` result cannot trigger `turn/start`. Any mismatch aborts and
leaves `quarantine.json`, without retries.

**Codex local validation:** inspect the generated 0.163 JSON Schema files;
choose the *correct object schemas* for the four fields, not envelope schemas,
not a broad `anyOf` catch-all, and never arbitrary filenames. The generated
files are NOT copied to GitHub. The new synthetic tests cover schema rejection
but DO NOT prove the four selected live files represent exact installed APIs.
Native Windows diagnosis must still confirm actual request shapes, sandbox
behavior and response compatibility before running a provider turn.

Use `py -3.12 scripts/audit_codex_schema_fixture.py --schema-root "..." --list` to enumerate the captured paths. The pilot's previous arguments and
`--allow-one-turn` remain necessary; append the four selectors. Refer to
`docs/ORCHESTRATOR_HOBBY_CODEX_RUNBOOK_DE.md` for the complete runbook.

**Risk level:** local hobby use is supported, but running under the same
Windows user is not a hard OS sandbox. No system users or productive ACLs
are changed; no automatic merge, retry, plugin, or multi-worker functionality.
