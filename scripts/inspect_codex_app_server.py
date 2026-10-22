"""Explicit Windows Codex --version and schema capture; never performs inference."""
from __future__ import annotations

import argparse
import json

from chatgpt_web2api.orchestrator.codex_readiness import inspect_codex_schema


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Offline installed Codex version/schema diagnostic (no provider actions)",
    )
    parser.add_argument("--codex-exe", required=True,
                        help="Full path to trusted, native Codex .exe; no PATH fallback")
    parser.add_argument("--output-dir", required=True,
                        help="New directory to create for generated schema and fingerprints")
    parser.add_argument("--expected-version",
                        help="Exact codex --version string, if already approved")
    args = parser.parse_args()
    result = inspect_codex_schema(
        args.codex_exe, args.output_dir, expected_version=args.expected_version,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
