"""Generate a local MCP provenance map; redact all server details in stdout."""
from __future__ import annotations

import argparse
import json

from chatgpt_web2api.orchestrator.mcp_source_inventory import prepare_local_mcp_source_map


def main() -> int:
    parser = argparse.ArgumentParser(description=(
        "Create an exclusive MCP source map from config-only discovery; "
        "unknowns require local review"
    ))
    parser.add_argument("--codex-exe", required=True)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--output-map", required=True)
    parser.add_argument("--user-config")
    parser.add_argument("--project-config")
    args = parser.parse_args()
    result = prepare_local_mcp_source_map(
        args.codex_exe, args.cwd, args.output_map,
        user_config=args.user_config, project_config=args.project_config,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ready_for_live_guard"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
