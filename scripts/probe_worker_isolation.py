"""One-shot disposable access diagnostic. No live worker or provider calls."""
from __future__ import annotations

import argparse
import json

from chatgpt_web2api.orchestrator.worker_isolation_audit import (
    prepare_disposable_probe,
    probe_disposable_root,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Disposable Windows second-user isolation probe; never authorizes workers",
    )
    ops = parser.add_subparsers(dest="action", required=True)
    prepare = ops.add_parser("prepare", help="Create a NEW protected synthetic probe root")
    prepare.add_argument("--label", required=True)
    probe = ops.add_parser("probe", help="Run under an existing authorized OTHER Windows user")
    probe.add_argument("--root", required=True)
    probe.add_argument("--expected-controller-sid", required=True)
    args = parser.parse_args()
    if args.action == "prepare":
        result = prepare_disposable_probe(args.label)
        print(json.dumps(result, sort_keys=True))
        return 0
    result = probe_disposable_root(
        args.root, expected_controller_sid=args.expected_controller_sid,
    )
    print(json.dumps(result, sort_keys=True))
    # Fail the shell status on any inconclusive or permissive result.
    return 0 if result["status"].startswith("OBSERVED_DENIAL_") else 2


if __name__ == "__main__":
    raise SystemExit(main())
