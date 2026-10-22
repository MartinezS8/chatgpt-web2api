# Phase 48b: offline fake App Server JSONL transport

This phase adds a bounded Windows stdio subprocess roundtrip against the package's
synthetic peer. It does **not** execute `codex`, authenticate, contact a provider,
send a real prompt, or produce implementation/review evidence. A completed fake
turn is labeled `transport_completed_unverified`; it cannot finalize a task or
grant live-send permission.

## Local protocol reference

The local machine used CPython 3.12.10 and Codex CLI 0.157.0. The CLI's
`codex app-server generate-json-schema --out <temporary-directory>` command was
run locally without starting `codex app-server`, authenticating, or starting a
turn. The generated files were kept outside the repository. The fixtures in this
branch were compared with those generated schemas and the official
[Codex App Server documentation](https://learn.chatgpt.com/docs/app-server).
Regenerate schemas with the installed CLI before claiming compatibility with a
different version.

Differences and details observed for CLI 0.157.0:

- `thread/start.params.sandbox` uses `read-only`; `turn/start.params.sandboxPolicy`
  uses `{ "type": "readOnly", "networkAccess": false }`.
- The initialize result includes `codexHome`, `platformFamily`, `platformOs`, and
  `userAgent`. Model records include exact model identity, display metadata,
  default effort, and described supported efforts. Thread and turn results also
  have required fields represented in the synthetic fixture.
- The JSONL protocol omits a `jsonrpc` member. The documented stdio lifecycle has
  an `initialized` notification. The docs do not define a shutdown RPC, so this
  harness closes stdin (EOF), waits for process exit, then force-stops only on a
  bounded timeout.
- The fake identifies itself as schema-shaped synthetic data. These fixture
  checks are not a runtime JSON Schema validator and do not attest to a live CLI's
  model availability or behavior.

## Harness boundaries

`OfflineFakeAppServer` accepts a frozen `AttemptBinding` and a closed enum of
synthetic scenarios. It always launches the bundled `_fake_app_server` module
through the current Python interpreter; there is no arbitrary executable,
command, or environment override. The child runs with isolated Python mode,
starts in the temporary directory, inherits only temporary/system-root variables,
and discards stderr. Parent and child retain no prompt in ordinary logs or in the
returned receipt. The harness never returns model output.

Frames are newline-delimited UTF-8 JSON, bounded to 64 KiB, with a bounded queue
of at most 64 frames and request timeouts capped at 60 seconds. The test peer
deliberately fragments valid frames to exercise partial reads. Interleaved
notifications are correlated while waiting for the matching response. Duplicate
JSON keys, malformed/truncated JSON, oversized frames, queue floods, unexpected
IDs, foreign thread/turn events, duplicate terminal events, and server-initiated
requests are rejected without responding to the latter. A lost acknowledgement,
broken pipe, timeout, or process exit after a request attempt becomes
`unknown_delivery`; rerunning the same harness object cannot emit another
`turn/start`.

## Test evidence on the implementation branch

The focused suite covers normal handshake/model discovery/thread and turn start,
early `turn/started` and progress notifications, exact model and effort with no
fallback, request/notification counts, stdin-EOF shutdown, and sanitized results.
Adversarial scenarios cover malformed, truncated, duplicate-key, oversized,
flooded, wrong-ID, approval, foreign-thread, foreign-turn, duplicate-terminal,
interrupted, process-death, timeout, and broken-pipe paths. A separate check rejects
oversized outbound prompts before `turn/start` bytes. These are offline unit and
subprocess tests only; package-install validation and exact-head CI evidence are
reported in `ORCHESTRATOR_PHASE48B_REAL_TRANSPORT_READINESS_REPORT.md`.

## Explicit limitations

- The harness remains in-memory by itself. Phase 48c adds a separate SQLite
  journal around this fixed fake, persisting worker, package, claim, request,
  thread, turn, and prompt-hash binding and recovering interrupted fake attempts
  to a no-retry state. This journal still does not authorize future live turn
  bytes; see [Phase 48c](ORCHESTRATOR_PHASE48C_DURABLE_DELIVERY.md).
- A Python callback or frozen object is not an OS security boundary. The worker
  and controller share the same Windows identity here; hostile same-user TOCTOU
  protection remains **FAIL**. Effective denial to a second Windows user remains
  **NOT TESTED**.
- `turn/completed` only describes a transport event. It is not proof of task
  completion, code provenance, independent review, or authorization to finalize.
- No supported real worker is implemented or authorized. ChatGPT web UI,
  plugins/apps, uploads, entitlement, model/effort availability, and native worker
  isolation are out of scope.
