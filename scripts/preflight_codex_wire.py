"""Offline preview of the exact JSON shapes the one-turn pilot will send."""
from __future__ import annotations

import argparse
import json

from chatgpt_web2api.orchestrator.local_wire_preflight import preview_local_one_turn


def main() -> int:
    parser = argparse.ArgumentParser(description=(
        "Offline Codex RPC shape check: no login, app-server, model/list or turns"
    ))
    parser.add_argument("--schema-root", required=True)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", required=True)
    parser.add_argument("--thread-params-schema", required=True)
    parser.add_argument("--thread-result-schema", required=True)
    parser.add_argument("--turn-params-schema", required=True)
    parser.add_argument("--turn-result-schema", required=True)
    parser.add_argument("--dummy-thread-id", default="thr_local_schema_placeholder")
    args = parser.parse_args()
    report = preview_local_one_turn(
        args.schema_root, args.cwd, args.prompt_file, model=args.model,
        effort=args.effort, simulated_thread_id=args.dummy_thread_id,
        selections={
            "thread_params": args.thread_params_schema,
            "thread_result": args.thread_result_schema,
            "turn_params": args.turn_params_schema,
            "turn_result": args.turn_result_schema,
        },
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
