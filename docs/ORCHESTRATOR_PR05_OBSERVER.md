# PR-05A — Read-only Codex observer CLI and MCP server

**Stacked on:** PR #6. No auto-merge. This step intentionally implements observation only, rather than unsafe `submit`, `approve`, `dispatch` or remotely writable MCP tools.

## Architecture

- `Observer` uses SQLite URI `mode=ro`, rejects a missing database (cannot create a blank DB), uses fixed bounded SELECT statements, omits task prompt, claim token, worker session key, callback body and event payload.
- `observer_commands.py` adds machine-readable CLI commands `observe-capabilities`, `observe-status`, `observe-events`, `observe-callbacks`, `observe-workers`, `observe-evidence`, `observe-reviews`, `observe-proposals`.
- `mcp_control.py` exposes an independent **stdio read-only MCP server** using the repository's pinned `mcp>=1.26,<2.0`, with explicit whitelisted tools `orchestrator_capabilities`, `orchestrator_status`, `orchestrator_events`, `orchestrator_callbacks`, `orchestrator_workers`, `orchestrator_evidence`, `orchestrator_reviews`, `orchestrator_proposals`.
- The MCP server does not connect to Chrome, ChatGPT, GitHub or Supabase, does not execute a prompt, and cannot approve or send tasks. No plugin availability, GPT-6 High, real callbacks, live workers or uploads are claimed.

## CLI usage after installing the package

```powershell
$env:CHATGPT_ORCHESTRATOR_DB="$HOME\.chatgpt-web2api\controller.sqlite"
python -m chatgpt_web2api.orchestrator --json observe-status --project project1
python -m chatgpt_web2api.orchestrator --json observe-events --after 0 --limit 20
python -m chatgpt_web2api.orchestrator --json observe-workers --account personal
chatgpt-orchestrator-observer-mcp --db "$env:CHATGPT_ORCHESTRATOR_DB"
```

The official Codex client must be configured to invoke the separate MCP executable **locally**. Do not serve it on a non-loopback interface. Read-only queries do not authenticate OS users; restrict SQLite DB visibility using Windows ACLs.

## Validation

`PYTHONPATH=src pytest -q tests/test_orchestrator_observer.py` → 6 offline tests passed using V4 Store fixtures. `python -m compileall -q src` passes.

**Untested:** full stacked tree, Windows CI, a real MCP 1.26 client/server round-trip, original upstream suite, Ruff, packaging/install executable. Fail the release gate until verified. The next PR-05B may add a bounded mock-only orchestration control interface after the centralized approval policy and authenticated callback gates are complete.

