"""Explicit opt-in local Codex App Server account/model read-only discovery."""
from __future__ import annotations

import argparse
import json

from chatgpt_web2api.orchestrator.local_codex_discovery import discover_local_codex


def main() -> int:
    parser = argparse.ArgumentParser(description=(
        "Launch local Codex only with explicit opt-in; handshake, account/read and "
        "model/list; NEVER creates a thread or sends a turn."
    ))
    parser.add_argument("--codex-exe", required=True, help="Absolute pinned native codex.exe")
    parser.add_argument("--schema-root", required=True, help="Existing trusted schema capture directory")
    parser.add_argument("--cwd", required=True, help="Existing explicit safe local directory")
    parser.add_argument("--allow-account-discovery", action="store_true",
                        help="Consent to start local Codex and read account/model info")
    parser.add_argument("--timeout", type=int, default=15, help="Per-response timeout, 2..60s")
    args = parser.parse_args()
    result = discover_local_codex(
        args.codex_exe, args.schema_root, args.cwd,
        allow_account_discovery=args.allow_account_discovery,
        response_timeout=args.timeout,
    )
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
