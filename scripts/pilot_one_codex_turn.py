"""A single, explicit local Codex test prompt; never retried automatically."""
from __future__ import annotations

import argparse
import json

from chatgpt_web2api.orchestrator.local_codex_pilot import run_one_local_pilot
from chatgpt_web2api.orchestrator.local_pilot_tool_audit import result_audit_is_consistent


def main() -> int:
    parser = argparse.ArgumentParser(description=(
        "ONE local Codex app-server thread/turn (experimental). "
        "Choose an empty scratch cwd, no secrets, and a NEW receipt directory."
    ))
    parser.add_argument("--codex-exe", required=True)
    parser.add_argument("--schema-root", required=True)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--receipt-dir", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", required=True)
    parser.add_argument("--windows-sandbox", choices=("mxc", "elevated"), default="mxc",
                        help="Explicit process-only backend; no automatic fallback (default: mxc)")
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--thread-params-schema", required=True)
    parser.add_argument("--thread-result-schema", required=True)
    parser.add_argument("--turn-params-schema", required=True)
    parser.add_argument("--turn-result-schema", required=True)
    parser.add_argument("--mcp-source-map", required=True,
                        help="Operator-reviewed metadata-only MCP provenance map")
    parser.add_argument("--allow-readonly-builtin-tools", action="store_true",
                        help="Acknowledge unproven built-in read-only tool absence")
    parser.add_argument("--allow-one-turn", action="store_true",
                        help="Explicitly authorize exactly one account-backed turn")
    args = parser.parse_args()
    result = run_one_local_pilot(
        args.codex_exe, args.schema_root, args.cwd, args.prompt_file, args.receipt_dir,
        model=args.model, effort=args.effort,
        schema_selectors={
            "thread_params": args.thread_params_schema,
            "thread_result": args.thread_result_schema,
            "turn_params": args.turn_params_schema,
            "turn_result": args.turn_result_schema,
        },
        mcp_source_map=args.mcp_source_map,
        allow_readonly_builtin_tools=args.allow_readonly_builtin_tools,
        allow_one_turn=args.allow_one_turn, timeout=args.timeout,
        windows_sandbox=args.windows_sandbox,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("clean_tool_free_pilot") is True and result_audit_is_consistent(result) else 2


if __name__ == "__main__":
    raise SystemExit(main())
