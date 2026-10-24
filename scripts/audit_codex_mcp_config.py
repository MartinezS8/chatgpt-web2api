"""Sanitized read-only two-pass Codex MCP config gate: no app-server/turn."""
from __future__ import annotations

import argparse
import json

from chatgpt_web2api.orchestrator.mcp_process_guard import McpInventoryMismatch, verify_mcp_disabled


def main() -> int:
    p = argparse.ArgumentParser(description=(
        "Check pinned Codex's process-scoped MCP flags without starting a server or turn"
    ))
    p.add_argument("--codex-exe", required=True)
    p.add_argument("--cwd", required=True)
    p.add_argument("--mcp-source-map", required=True)
    args = p.parse_args()
    try:
        report = verify_mcp_disabled(args.codex_exe, args.cwd, args.mcp_source_map)
    except (OSError, RuntimeError, ValueError) as exc:
        result = {"mcp_config_probe_passed": False, "error_type": type(exc).__name__,
                  "live_turn_authorized": False}
        if isinstance(exc, McpInventoryMismatch):
            result["inventory_drift"] = exc.counts
        print(json.dumps(result, sort_keys=True, indent=2))
        return 2
    print(json.dumps(report.sanitized(), sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
