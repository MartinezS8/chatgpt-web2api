"""Read a saved one-turn receipt; never sends, restarts or releases a turn."""
from __future__ import annotations

import argparse
import json

from chatgpt_web2api.orchestrator.local_pilot_receipt import inspect_local_pilot_receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=(
        "Read-only Codex pilot receipt inspector (no login, no provider, no retry)"
    ))
    parser.add_argument("--receipt-dir", required=True,
                        help="Existing absolute receipt directory to inspect")
    args = parser.parse_args()
    report = inspect_local_pilot_receipt(args.receipt_dir)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["classification"] == "TERMINAL_OUTPUT_MATCHED_UNREVIEWED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
