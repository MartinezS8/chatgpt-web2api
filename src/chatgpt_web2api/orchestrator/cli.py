"""Safe, transport-neutral command line for the local orchestration store.

Deliberately provides NO chat, browser, connector, or production mutation
commands. CLI-Anything-inspired discoverable subcommands; stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

from .store import Store, TaskSpec
from .resource_registry import ResourceRegistry, ResourceIdentity


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="chatgpt-orchestrator",
        description="Manage isolated local orchestration tasks; never sends ChatGPT messages.",
    )
    p.add_argument("--db", default=os.environ.get("CHATGPT_ORCHESTRATOR_DB"),
                   help="Explicit path to the local SQLite database (or CHATGPT_ORCHESTRATOR_DB)")
    p.add_argument("--json", action="store_true", help="Machine-readable JSON response")
    commands = p.add_subparsers(dest="command", required=True)
    commands.add_parser("capabilities", help="Display supported operations and safety boundaries")
    s = commands.add_parser("status", help="Show project task counts and occupied slots")
    s.add_argument("--project", required=True)
    s = commands.add_parser("list-tasks", help="List existing tasks in a project")
    s.add_argument("--project", required=True)
    s = commands.add_parser("task", help="Show a task by ID")
    s.add_argument("--id", required=True)
    s = commands.add_parser("events", help="Display audit events for a task")
    s.add_argument("--id", required=True)
    s = commands.add_parser("create-task", help="Create an idempotent task using a local prompt file")
    s.add_argument("--id", required=True)
    s.add_argument("--project", required=True)
    s.add_argument("--role", required=True, choices=("implement", "review", "planning"))
    s.add_argument("--prompt-file", required=True, help="UTF-8 text; content is hashed, not saved to the DB")
    s.add_argument("--depends-on", action="append", default=[], metavar="TASK_ID")
    s.add_argument("--write-scope", action="append", default=[], metavar="SCOPE")
    s.add_argument("--resource-alias", action="append", default=[], metavar="ALIAS",
                   help="Use registered canonical provider resource aliases; cannot combine with --write-scope")
    s.add_argument("--baseline-sha", default="")
    s.add_argument("--review-of", default=None)
    s = commands.add_parser("register-resource", help="Operator-asserted alias; does NOT grant live writes")
    s.add_argument("--alias", required=True)
    s.add_argument("--provider", required=True, choices=("github", "supabase", "vercel"))
    s.add_argument("--provider-id", required=True, help="GitHub numeric repository ID, Supabase ref or Vercel project ID")
    s.add_argument("--environment", help="Required for Supabase and Vercel")
    s.add_argument("--operator", required=True)
    s = commands.add_parser("resolve-resource", help="Resolve a registered alias to its canonical lock")
    s.add_argument("--alias", required=True)
    s.add_argument("--path", default=None)
    commands.add_parser("list-resources", help="List local operator-asserted resource aliases")
    s = commands.add_parser("claim", help="Atomically reserve one eligible task without sending it")
    s.add_argument("--project", required=True)
    s.add_argument("--max-slots", type=int, default=5)
    s = commands.add_parser("recover", help="Requeue only expired pre-send leases; quarantine uncertain sends")
    s.add_argument("--project", required=True)
    return p


def _capabilities() -> dict:
    return {
        "task_store": "sqlite-wal", "max_worker_slots": 5,
        "commands": ["capabilities", "status", "list-tasks", "task", "events",
                     "create-task", "register-resource", "resolve-resource", "list-resources",
                     "claim", "recover"],
        "automatic_web_dispatch": False,
        "chatgpt_ui_automation": False,
        "supabase_or_github_writes": False,
        "independent_evidence_verification": "required-before-completion",
        "unknown_delivery_retry": "human-reconciliation-only",
        "dispatch_fencing": "claim-token-cas-and-expiring-presend-lease",
        "write_scope_locking": "sqlite-global-conservative",
        "resource_alias_assurance": "operator-asserted-not-provider-verified",
        "review_gate": "verified-state-requires-explicit-finalization",
    }


def _public_task(row: dict | None) -> dict | None:
    """Do not disclose fencing tokens through generic CLI listing commands."""
    if row is None:
        return None
    return {key: value for key, value in row.items() if key != "claim_token"}


def execute(args: argparse.Namespace) -> dict:
    if args.command == "capabilities":
        return _capabilities()
    if not args.db:
        raise ValueError("--db or CHATGPT_ORCHESTRATOR_DB must be set")
    db_path = Path(args.db).expanduser().resolve()
    # Reads must not accidentally create a blank DB and conceal configuration errors.
    if args.command in {"status", "list-tasks", "task", "events", "resolve-resource", "list-resources"} and not db_path.is_file():
        raise FileNotFoundError(f"database does not exist: {db_path}")
    if args.command in {"create-task", "claim", "recover", "register-resource"}:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    store = Store(db_path)
    if args.command in {"register-resource", "resolve-resource", "list-resources"}:
        registry = ResourceRegistry(store)
        if args.command == "register-resource":
            key = registry.register(args.alias, ResourceIdentity(args.provider, args.provider_id,
                                   args.environment), operator=args.operator)
            return {"alias": args.alias, "canonical_id": key,
                    "provider_write_authorized": False, "assurance": "operator_assertion"}
        if args.command == "resolve-resource":
            return {"canonical_scope": registry.resolve(args.alias, args.path),
                    "provider_write_authorized": False}
        return {"bindings": registry.list_bindings(), "provider_write_authorized": False}
    if args.command == "status":
        rows = store.all(args.project)
        return {"project": args.project, "total": len(rows),
                "states": dict(Counter(t["state"] for t in rows)),
                "occupied_slots": sorted(t["slot"] for t in rows if t["slot"] is not None)}
    if args.command == "list-tasks":
        return {"project": args.project, "tasks": [_public_task(r) for r in store.all(args.project)]}
    if args.command == "task":
        row = store.get(args.id)
        if row is None:
            raise ValueError(f"unknown task: {args.id}")
        return _public_task(row)
    if args.command == "events":
        if store.get(args.id) is None:
            raise ValueError(f"unknown task: {args.id}")
        return {"task_id": args.id, "events": store.events(args.id)}
    if args.command == "create-task":
        file = Path(args.prompt_file).expanduser().resolve(strict=True)
        if not file.is_file():
            raise ValueError("--prompt-file must be a regular file")
        if file.stat().st_size > 1024 * 1024:
            raise ValueError("prompt file exceeds the 1 MiB local safety limit")
        prompt = file.read_text(encoding="utf-8")
        spec = TaskSpec(task_id=args.id, project_id=args.project, role=args.role,
                        prompt=prompt, dependencies=tuple(args.depends_on),
                        write_scopes=tuple(args.write_scope),
                        baseline_sha=args.baseline_sha, review_of=args.review_of)
        if args.resource_alias:
            spec = ResourceRegistry(store).task_with_resolved_scopes(
                spec, tuple((alias, None) for alias in args.resource_alias))
        created = store.create(spec)
        return {"task_id": args.id, "created": created, "state": "queued",
                "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                "prompt_stored": False}
    if args.command == "claim":
        return {"project": args.project, "reserved": _public_task(store.claim(args.project, max_slots=args.max_slots))}
    if args.command == "recover":
        return {"project": args.project, "uncertain_dispatches": store.recover(args.project),
                "automatic_resend": False}
    raise ValueError("unknown command")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = execute(args)
    except (OSError, ValueError, UnicodeError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}},
                             ensure_ascii=False))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"ok": True, "data": result}, ensure_ascii=False, sort_keys=True))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())