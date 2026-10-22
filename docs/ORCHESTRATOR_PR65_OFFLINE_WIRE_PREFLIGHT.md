# PR #65 — Shared request builders plus offline Codex wire preflight

Parent Draft PR #64 exact `af88bea0fc37c95c94a4d83797680e242ecc23b1`.

The manual pilot and the new **offline** `scripts/preflight_codex_wire.py`
import the same two pure request-builder functions; a schema preview cannot
silently drift away from the payloads ultimately submitted by the real pilot.

Pass the four **actual** selected schema paths from the captured Codex
`0.163.0-alpha.11` bundle (and the intended model/effort, empty scratch
directory and a tiny local prompt). The command validates the current
`thread/start` params and intended `turn/start` params, using a synthetic
thread ID, against those schemas. It checks the two response schema documents
for presence/validity but **cannot validate live responses until received**.
It never starts an app-server, checks account models, logs in, or sends a turn.
The receipt does not expose prompt content.

```powershell
py -3.12 scripts/preflight_codex_wire.py --schema-root "$SchemaDir" --cwd "$Scratch" --prompt-file "$PromptFile" --model "<ACTUAL_MODEL_ID>" --effort "<ACTUAL_EFFORT>" --thread-params-schema "<RELATIVE_SCHEMA>" --thread-result-schema "<RELATIVE_SCHEMA>" --turn-params-schema "<RELATIVE_SCHEMA>" --turn-result-schema "<RELATIVE_SCHEMA>"
```

A PASS proves that the explicitly selected schema documents accept the
request shapes, NOT that the user selected the correct four schemas, NOT a
provider handshake, actual availability, sandbox isolation or turn completion.
Review the four path-to-method mappings manually. An incompatible params
schema is actionable: repair the request builder and rerun this preview
before a live account-backed trial. Any changed schema binary must be
recaptured with the PR #56 offline tool. No automatic fallback.

Hobby local trial remains explicitly opt-in as described in the German
runbook, with no file uploads, merges, repeat sends or five-worker orchestration.
