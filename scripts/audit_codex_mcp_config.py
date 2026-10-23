"""Sanitized read-only two-pass Codex MCP config gate: no app-server/turn."""
from __future__ import annotations

import argparse
import json

from chatgpt_web2api.orchestrator.mcp_process_guard import verify_mcp_disabled


def main() -> int:
    p = argparse.ArgumentParser(description=(
        "Check pinned Codex's process-scoped MCP flags without starting a server or turn"
    ))
    p.add_argument("--codex-exe", required=True)
    p.add_argument("--cwd", required=True)
    p.add_argument("--mcp-source-map", required=True)
    args = p.parse_args()
    report = verify_mcp_disabled(args.codex_exe, args.cwd, args.mcp_source_map)
    print(json.dumps(report.sanitized(), sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
