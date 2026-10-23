"""One-command local Codex preflight: schema pin then opt-in discovery."""
from __future__ import annotations

import argparse
import json

from chatgpt_web2api.orchestrator.local_pilot_doctor import local_pilot_doctor


def main() -> int:
    parser = argparse.ArgumentParser(description=(
        "Check the pinned Codex binary and optional available model/effort; "
        "NO thread or turn can be sent."
    ))
    parser.add_argument("--codex-exe", required=True)
    parser.add_argument("--schema-root", required=True)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--allow-account-discovery", action="store_true",
                        help="Allow starting the local app-server to read account/model data")
    parser.add_argument("--mcp-source-map",
                        help="Operator-reviewed MCP provenance map required for account discovery")
    parser.add_argument("--model", help="Exact model ID, only checked against real discovery")
    parser.add_argument("--effort", help="Exact supported reasoning effort")
    args = parser.parse_args()
    if args.allow_account_discovery and args.mcp_source_map is None:
        parser.error("--mcp-source-map is required with --allow-account-discovery")
    result = local_pilot_doctor(
        args.codex_exe, args.schema_root, args.cwd,
        allow_account_discovery=args.allow_account_discovery,
        mcp_source_map=args.mcp_source_map,
        model=args.model, effort=args.effort,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
