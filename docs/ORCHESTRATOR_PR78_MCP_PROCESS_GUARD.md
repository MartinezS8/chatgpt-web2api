# Draft PR #78 — Process-scoped MCP disablement (offline configuration gate)

Parent: PR #77 exact HEAD `e12f0b294ad11100af691b7fffeac9e7799191f8`.

The previous pilot launched `codex app-server` without MCP overrides. A
natural-language prompt ("Do not use tools") does not enforce no-tool policy.
The owner has eight MCP entries, six enabled; five are identifiable in the
user config and one enabled entry requires local source investigation.

`mcp_process_guard.verify_mcp_disabled()` creates process-scoped **leaf**
`-c mcp_servers."<name>".enabled=false` overrides. It never replaces the
entire `mcp_servers` table (that can drop CLI-only command/url fields and
cause `invalid transport`). Plugin bundles instead require their documented
`plugins."<id>".mcp_servers."<name>".enabled=false` policy and disable
the plugin's own `enabled` property. All names are TOML-quoted. This is
the **configuration gate only**, not a proof of effective model tools.

Create a local metadata-only `sources.json` (do NOT commit local server
names or secrets):

```json
{
  "schema_version": 1,
  "servers": [
    {"name": "example", "source": "user_config"},
    {"name": "cli_entry", "source": "cli"},
    {"name": "bundled", "source": "plugin", "plugin_id": "plugin@marketplace"}
  ]
}
```

It must contain **exactly all** entries enumerated by the native Codex
`mcp list --json` command, including disabled entries. Allowed source values
are `user_config`, `cli`, and `plugin`; unknown entries fail closed.
The map is a *manual provenance declaration*, not proof that sources are
correct. After validating it, the guard repeats `mcp list --json` with
the leaf overrides, and rejects any enabled server or unsupported config.
Neither CLI read launches `app-server`, `thread/start` or `turn/start`
from our code. Synthetic subprocess tests verify these constraints.

**Still outstanding before live:** apply the exact verified arguments to
*every* local app-server process used in account discovery and the one-turn
pilot, and query `mcpServerStatus/list` on the very same pilot app-server
before `thread/start`. Enumerate apps/plugin tools and built-in tools
separately; a disabled MCP inventory is not proof of zero callable tools.
If the CLI or app server cannot prove the required scope, gate stays BLOCKED.
Never emit server commands/URLs/tokens. No permanent Codex configuration
changes, new OS account, real provider calls, or merges in this PR.

Relevant upstream context: https://github.com/openai/codex/issues/53087 ;
https://developers.openai.com/plugins/build/plugins ;
https://learn.chatgpt.com/docs/app-server
