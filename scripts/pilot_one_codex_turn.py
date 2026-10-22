"""A single, explicit local Codex test prompt; never retried automatically."""
from __future__ import annotations

import argparse
import json

from chatgpt_web2api.orchestrator.local_codex_pilot import run_one_local_pilot


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
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--thread-params-schema", required=True)
    parser.add_argument("--thread-result-schema", required=True)
    parser.add_argument("--turn-params-schema", required=True)
    parser.add_argument("--turn-result-schema", required=True)
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
        allow_one_turn=args.allow_one_turn, timeout=args.timeout,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if (
        result["turn_terminal_status"] == "completed"
        and result["assistant_output_matches_expected"] is True
    ) else 2


if __name__ == "__main__":
    raise SystemExit(main())
