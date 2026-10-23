# PR #80 — Sanitize and prepare local MCP provenance without secrets

Parent Draft PR #79 exact `d51723733cc92d04405322556fbfa083cf397ec1`.

The manually authored `--mcp-source-map` from #78 is now easier to generate
using `scripts/prepare_codex_mcp_source_map.py`. It invokes only a config
metadata `mcp list --json` probe, reads only **table keys** from optional
user/project TOML files, and writes a local exclusive metadata JSON file
containing names and source classifications. Neither transport settings,
commands, URLs, environment values nor credentials are copied.

An MCP name found in exactly one config layer is classified as
`user_config` or `project_config`. Names missing from both layers, or
present in both, stay `unknown` and are rejected by the strict guard.
Codex must inspect **locally** which source (CLI, plugin, managed bundle)
produced the outstanding server and amend this metadata map; plugin entries
must include their exact `plugin_id`. Do NOT invent plugin origins.

Example:
```powershell
py -3.12 scripts/prepare_codex_mcp_source_map.py --codex-exe "<ABS_NATIVE_EXE>" --cwd "<SCRATCH>" --output-map "<NEW_LOCAL_JSON>"
py -3.12 scripts/audit_codex_mcp_config.py --codex-exe "<ABS_NATIVE_EXE>" --cwd "<SCRATCH>" --mcp-source-map "<LOCAL_JSON>"
```
The helper returns exit code 2 while origins remain unresolved. Never commit
local source maps. User config and GitHub master are not mutated. There are
no account calls, MCP-server starts or real provider actions in this PR.
