# PR #79 — Gate the same process before a one-turn send

Parent Draft PR #78 exact `fbe7c7c1f6a46b3b4523670bd63b94b3bccceb4b`. Extend the previous config-only guard
to the App Server `mcpServerStatus/list` and `app/installed` responses. This
is only one *part* of the end-to-end integration: the actual live manual pilot
must use the verified `-c` leaf arguments in **both** local account discovery
and in its eventual single-turn app-server process. A follow-up commit here
makes that mandatory in the Python API and CLI.

`require_external_tools_disabled()` verifies bounded, nonpaginated MCP
status and non-callable installed apps. Absent/unknown flags, an active MCP,
available MCP tools, unknown pagination or callable app fail BEFORE
`thread/start`. The result explicitly says built-in tools are **NOT proven
absent**. A user's separate acceptance of read-only built-in tool exposure is
necessary for the intended same-user hobby pilot; 'Do not use tools' alone
is NOT enforcement.

Config-only command (no app-server, account lookup or model turn):
```powershell
py -3.12 scripts/audit_codex_mcp_config.py --codex-exe "<PINNED_EXE>" --cwd "<EMPTY_SCRATCH>" --mcp-source-map "<SANITIZED_JSON>"
```

See #78 for metadata-only map shape. Never commit local server names, transport
commands, URLs, auth tokens or process environment. This first commit is
offline-only and leaves all real provider operations blocked.
