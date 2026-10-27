# MCP refresh and Windows start readiness — 2026-10-24

## Scope and authority

Parent: open Draft PR #84, branch
`codex/orchestrator-v81-doctor-mcp-source-map`, exact remote SHA
`8f3288995b0ec424081ca1bd3d452c0ddf7cae57`. Its three Windows/Python-3.12
diagnostic jobs in run `40042164781` were rechecked successfully. Worktree
was clean before creating `codex/orchestrator-v82-mcp-provenance-refresh`.
No master edits, merges or account configuration writes are part of this change.

The user's 24 October plan authorizes local config diagnostics, guarded
account/model reads and a same-user hobby preparation. A real turn still
requires specific approval of its model, effort, CWD, prompt and residual
built-in tool exposure. A successful diagnostic never authorizes inference.

## Findings and implementation

1. The stale map contained eight identities; the effective inventory has seven.
   Regeneration left two unknowns, not three: the stale identity was one of the
   old unknown entries. Five current entries match user config; two have unique
   enabled plugin IDs, exact cache/manifest names and declared `.mcp.json`
   references. Server IDs, plugin IDs, transports and config values stay local.
2. The inventory helper can explicitly scan that bounded local plugin cache.
   Multiple cached versions/colliding config layers remain unknown. Redirected
   candidates are counted and never used as provenance; unrelated verifiable
   candidates can still be inspected. One such candidate was rejected locally.
   This is evidence from local metadata, not proof of every effective layer.
3. Source-map drift errors now report only added/removed/unresolved counts.
   An unexpected new identity after overrides, even disabled, is rejected;
   a regular config identity cannot disappear. Disabled plugins may disappear.
4. Optional source-map v2 binds the native executable hash/version, CWD hash,
   effective name/enabled inventory hash, and reviewed local source-file
   hashes. Inputs are rechecked before and after the config guard. These
   snapshots detect drift; an editable local map is not signed authorization.
   Legacy v1 maps remain supported and report `mcp_snapshot_verified=false`.
5. `probe_codex_start_matrix.py` probes up to three explicit CWD/map pairs.
   It initializes an App Server, checks disabled Apps then MCP status and
   closes stdio. It cannot send account, thread or turn requests. Optional
   MXC probing runs only a fixed PowerShell CWD read. No arbitrary command
   argument or native legacy sandbox setup is provided.
6. The installed 0.164 `codex sandbox` requires a named permission profile.
   The first diagnostic invocation without it returned CLI usage exit 2.
   The fixed probe creates a unique process-only profile extending
   `:read-only`, with command network disabled. It does not edit config files.
7. The one-turn adapter previously inherited the user's `elevated` backend,
   while the new successful local probe uses MXC. Its explicit backend
   selection now defaults to MXC and disables automatic fallback. The
   requested backend is written in intent/results; independent effective
   backend verification is explicitly false. Authorization/replay/correlation
   checks remain in force and no real turn was run to test this change.

## Actual local diagnostics

Native `codex-cli 0.164.0-alpha.11.1`, binary SHA-256
`c6144bc19b2705f25a40d8488b3d57d17a223c5df3c5f65e3c58d72601956c1e`.
Schema bundle: 320 pinned JSON schemas. Development interpreter: CPython
3.12.10 in a new virtual environment outside Git. All test data is synthetic.

| Gate | Result | Evidence and limitation |
| --- | --- | --- |
| Fresh current MCP map | PASS | 7 identities, 5 user-config and 2 plugin-manifest matches, 0 unknown |
| Bound v2 config guard | PASS | snapshot checked, 6 initially enabled, 0 enabled after process overrides, Apps false |
| Actual runtime tool fence | PASS | 16 installed Apps disabled/non-callable; 6 MCP status rows, no tools/resources or active/uncertain state |
| Temp App Server lifecycle | PASS | initialize/initialized, tool checks, EOF exit 0; no thread/turn |
| AppData App Server lifecycle | PASS | same checks and clean exit; this does not execute a sandbox child |
| Temp MXC child process | PASS | fixed local PowerShell CWD read returns exact requested CWD, exit 0 |
| AppData MXC child process | FAIL | child exit 0 but actual PowerShell CWD differs; directory identity also differs |
| Elevated child / error 267 | NOT TESTED | no legacy setup/account changes; earlier error is not claimed resolved |
| Current account metadata | PASS | guarded account/read reports account present, mode chatgpt; no email/tokens exported |
| Exact model/effort catalog | PASS | gpt-6-luna/max offered by current model/list; no fallback |
| Model inference | NOT TESTED | no thread/start or turn/start emitted |
| Hostile same-user TOCTOU | FAIL | model-1 cooperation only |
| Effective second-user denial | NOT TESTED | no authorized second context provided |
| Production / real-worker readiness | NOT TESTED | no scheduler live transport, reviewer evidence or parallel real sessions proven |

The current machine's valid hobby route is the verified Temp CWD. The
AppData sandbox CWD mismatch is a distinct negative result and is not
reclassified as a successful alias: `samefile` was false. Its exact internal
cause remains open. Changing a process backend or path does not establish
same-user secret isolation. Read-only built-in tools remain available risks.

Focused synthetic tests cover count-only redaction, disabled extra-identity
drift, plugin version ambiguity/reparse rejection, concurrent config edits,
binary/CWD/inventory/source-file drift, fixed MXC permissions arguments,
false-positive exit 0/CWD mismatch, lifecycle cleanup, callable-App rejection
and the pilot's explicit no-fallback backend. The complete strict verifier,
build/install and CI receipts must be read on the containing final Git head;
earlier #84 evidence does not stand in for this revision's checks.

## Next operator gate

Prepare exactly `Output exactly ORCH_TEST_OK. Do not use tools.` in a local
prompt file outside the empty Temp CWD. Use the pinned binary/bundle, reviewed
v2 map, gpt-6-luna/max, explicit MXC, read-only, approval policy never and a
new receipt path. Recheck all pins immediately before any approved attempt.
The operator must approve the specific single turn and acknowledge that
built-in read-only tool exposure and same-user file access are not excluded.
No automatic retry, finalization, push or merge authority follows from that
turn. Unknown delivery remains quarantined. Only after an actual verified
response should scheduler integration and 2/5 real workers be considered.

## Primary references

- [App Server RPCs and read-only semantics](https://learn.chatgpt.com/docs/app-server)
- [Config, plugin MCP policy and named permissions](https://learn.chatgpt.com/docs/config-file/config-reference)
- [Windows sandbox and explicit MXC](https://learn.chatgpt.com/docs/windows/windows-sandbox)

No raw MCP/config/account response or local source map belongs in Git/CI logs.

## PR #85 follow-up: tool-event audit

The single-turn pilot now audits versioned item and notification categories,
including events buffered before the turn acknowledgement and events drained
after the terminal notification. Action-bearing and unknown categories prevent
`clean_tool_free_pilot`; server-initiated requests are quarantined. The receipt
stores counts from fixed labels, never raw tool payloads or unknown type names.
The CLI and read-only inspector do not treat a matching answer as a clean pilot
when audit evidence is missing, contradictory or reports tool activity.

This observation is retrospective and depends on the events actually emitted
by the local process. It neither prevents tool execution nor independently
attests a complete stream, a sandbox implementation or same-user isolation.
An uncertain send still requires human review and is never automatically retried.

On 27 October 2026 the visible native binary reported the same version string
as the earlier capture but SHA-256
`1103e9e09c71fa2cd0afd6d8f3b9a2d63174fe8eefd7cb5bd09f1cb14ef58a098`;
the earlier schema manifest is bound to `c6144bc19b2705f25a40d8488b3d57d17a223c5df3c5f65e3c58d72601956c1e`.
Version-string equality does not resolve this mismatch. A future preflight must
use a newly captured, verified bundle for the current binary; this observation
does not demonstrate an account, model or live turn on the new binary.
