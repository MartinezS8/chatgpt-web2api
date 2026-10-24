"""Probe existing CWD/map pairs; stdout contains sanitized receipts only."""
from __future__ import annotations

import argparse
import json

from chatgpt_web2api.orchestrator.codex_start_probe import probe_local_start


def main() -> int:
    parser = argparse.ArgumentParser(description="Local App Server startup; no account/thread/turn")
    parser.add_argument("--codex-exe", required=True)
    parser.add_argument("--schema-root", required=True)
    parser.add_argument("--case", nargs=2, action="append", required=True, metavar=("CWD", "MAP"))
    parser.add_argument("--sandbox-backend", choices=("mxc", "elevated"), default="mxc")
    parser.add_argument("--probe-mxc-command", action="store_true",
                        help="Also run one fixed PowerShell CWD read using MXC, no provider")
    args = parser.parse_args()
    if len(args.case) > 3:
        parser.error("at most three explicit cases")
    if args.probe_mxc_command and args.sandbox_backend != "mxc":
        parser.error("legacy sandbox command setup is excluded")
    receipts = []
    for index, (cwd, source_map) in enumerate(args.case):
        try:
            result = probe_local_start(
                args.codex_exe, args.schema_root, cwd, source_map,
                sandbox_backend=args.sandbox_backend, probe_mxc_command=args.probe_mxc_command,
            )
            ok = (not args.probe_mxc_command or result.get("sandbox_cwd_matches") is True)
            receipts.append({"case": index, "ok": ok, **result})
        except (OSError, RuntimeError, ValueError) as exc:
            # Never copy exception details: CLI stderr/config may contain secrets.
            receipts.append({"case": index, "ok": False, "error_type": type(exc).__name__})
    print(json.dumps({"cases": receipts, "live_turn_authorized": False}, indent=2, sort_keys=True))
    return 0 if all(r["ok"] for r in receipts) else 1


if __name__ == "__main__":
    raise SystemExit(main())
