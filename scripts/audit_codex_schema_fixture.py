"""Check exact captured Codex JSON Schemas against a chosen offline fixture."""
from __future__ import annotations

import argparse
import json

from chatgpt_web2api.orchestrator.schema_fixture_audit import (
    audit_fixture,
    verified_bundle,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline version-pinned Codex JSON schema audit")
    parser.add_argument("--schema-root", required=True, help="Captured schema directory")
    parser.add_argument("--list", action="store_true", help="List captured schema file names")
    parser.add_argument("--schema", help="Exact relative JSON schema path (from --list)")
    parser.add_argument("--fixture", help="Local JSON response/request fixture to validate")
    args = parser.parse_args()
    if args.list:
        if args.schema or args.fixture:
            parser.error("--list cannot be combined with --schema or --fixture")
        report, documents = verified_bundle(args.schema_root)
        print(json.dumps({
            "codex_version": report["codex_version"],
            "schema_paths": sorted(documents),
            "provider_contacted": False,
        }, sort_keys=True))
        return 0
    if not args.schema or not args.fixture:
        parser.error("--schema and --fixture are required unless --list is used")
    result = audit_fixture(args.schema_root, args.schema, args.fixture)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
