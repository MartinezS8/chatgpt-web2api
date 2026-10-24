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
    parser.add_argument("--plugin-cache", help="Explicit local plugin cache for manifest provenance")
    parser.add_argument("--bind-snapshot", action="store_true",
                        help="Write v2 map bound to binary, CWD, inventory and reviewed source hashes")
    args = parser.parse_args()
    try:
        result = prepare_local_mcp_source_map(
            args.codex_exe, args.cwd, args.output_map,
            user_config=args.user_config, project_config=args.project_config,
            plugin_cache=args.plugin_cache, bind_snapshot=args.bind_snapshot,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"ready_for_live_guard": False, "error_type": type(exc).__name__}))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ready_for_live_guard"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
