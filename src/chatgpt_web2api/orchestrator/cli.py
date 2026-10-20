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

from .observer_commands import OBS_COMMANDS, configure_observer_commands, execute_observer_command
from .outbox import DispatchOutbox
from .private_workspace import load_private_workspace
from .resource_registry import ResourceIdentity, ResourceRegistry
from .stage_maintenance import cleanup_managed_stages
from .storage_hardening import create_private_windows_workspace, snapshot_sqlite_same_directory
from .store import Store, TaskSpec
from .task_packages import TaskPackages
from .worker_commands import (
    WORKER_COMMANDS,
    WORKER_READ_COMMANDS,
    configure_worker_commands,
    execute_worker_command,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="chatgpt-orchestrator",
        description="Manage isolated local orchestration tasks; never sends ChatGPT messages.",
    )
    p.add_argument("--db", default=os.environ.get("CHATGPT_ORCHESTRATOR_DB"),
                   help="Explicit path to the local SQLite database (or CHATGPT_ORCHESTRATOR_DB)")
    p.add_argument("--json", action="store_true", help="Machine-readable JSON response")
    p.add_argument("--private-workspace", default=None,
                   help="Reopen existing ACL-verified Windows workspace by label; cannot combine with --db")
    commands = p.add_subparsers(dest="command", required=True)
    commands.add_parser("capabilities", help="Display supported operations and safety boundaries")
    s = commands.add_parser("init-private-workspace",
                            help="Opt-in NEW Windows ACL-protected local SQLite/blob directory")
    s.add_argument("--label", required=True, help="New workspace name; existing paths are refused")
    s = commands.add_parser("backup-local-db",
                            help="Create a no-clobber SQLite backup beside an existing --db")
    s.add_argument("--filename", required=True, help="Simple backup filename ending .sqlite3")
    s = commands.add_parser("staging-audit",
                            help="Inspect staging; optionally clean ONLY locked managed-v2 leftovers")
    s.add_argument("--root", required=True, help="Explicit local staging directory")
    s.add_argument("--older-than-hours", type=float, default=24.0)
    s.add_argument("--delete-managed-v2", action="store_true",
                   help="Explicitly delete only safe managed-v2 leftovers (never legacy)")
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
    s = commands.add_parser("seal-task", help="Persist immutable task prompt and local file snapshots; does not upload")
    s.add_argument("--id", required=True)
    s.add_argument("--prompt-file", required=True)
    s.add_argument("--attachment", action="append", default=[])
    s.add_argument("--allowed-root", default=None, help="Required if attachments are present")
    s = commands.add_parser("task-package", help="Read sealed package manifest without exposing the prompt")
    s.add_argument("--id", required=True)
    s = commands.add_parser("delivery-events", help="Read durable delivery events by ID cursor")
    s.add_argument("--after", type=int, default=0)
    s.add_argument("--limit", type=int, default=100)
    s = commands.add_parser("ack-delivery-event", help="Advance an individual consumer's durable event cursor")
    s.add_argument("--consumer", required=True)
    s.add_argument("--event-id", type=int, required=True)
    s = commands.add_parser("reconcile-dispatch", help="Quarantine aged unconfirmed send intents; never resends")
    s.add_argument("--stale-seconds", type=int, default=300)
    s = commands.add_parser("claim", help="Atomically reserve one eligible task without sending it")
    s.add_argument("--project", required=True)
    s.add_argument("--max-slots", type=int, default=5)
    s = commands.add_parser("recover", help="Requeue only expired pre-send leases; quarantine uncertain sends")
    s.add_argument("--project", required=True)
    configure_worker_commands(commands)
    configure_observer_commands(commands)
    return p


def _capabilities() -> dict:
    return {
        "task_store": "sqlite-wal", "max_worker_slots": 5,
        "private_workspace_cli": "explicit-windows-label-with-dacl-readback",
        "legacy_db_paths_private_assurance": False,
        "commands": ["capabilities", "init-private-workspace", "backup-local-db",
                     "staging-audit",
                     "status", "list-tasks", "task", "events",
                     "create-task", "register-resource", "resolve-resource", "list-resources",
                     "seal-task", "task-package", "delivery-events", "ack-delivery-event",
                     "reconcile-dispatch", "claim", "recover"],
        "automatic_web_dispatch": False,
        "chatgpt_ui_automation": False,
        "supabase_or_github_writes": False,
        "independent_evidence_verification": "required-before-completion",
        "unknown_delivery_retry": "human-reconciliation-only",
        "dispatch_fencing": "claim-token-cas-and-expiring-presend-lease",
        "write_scope_locking": "sqlite-global-conservative",
        "resource_alias_assurance": "operator-asserted-not-provider-verified",
        "immutable_task_packages": True,
        "local_attachment_snapshots": True,
        "remote_file_upload": False,
        "durable_dispatch_outbox": "available-to-internal-code-not-external-transport",
        "durable_event_cursor": True,
        "review_gate": "verified-state-requires-explicit-finalization",
    }


def _public_task(row: dict | None) -> dict | None:
    """Do not disclose fencing tokens through generic CLI listing commands."""
    if row is None:
        return None
    return {key: value for key, value in row.items() if key != "claim_token"}


def execute(args: argparse.Namespace) -> dict:
    if args.command == "observe-capabilities":
        return execute_observer_command(args, None)
    if args.command == "worker-capabilities":
        from .capabilities import capabilities

        return capabilities()
    if args.command == "capabilities":
        return _capabilities()
    private = None
    if getattr(args, "private_workspace", None) is not None:
        if args.db:
            raise ValueError("--private-workspace cannot be combined with --db or CHATGPT_ORCHESTRATOR_DB")
        if args.command == "init-private-workspace":
            raise ValueError("use --label alone when provisioning a new private workspace")
        private = load_private_workspace(args.private_workspace)
    if args.command == "init-private-workspace":
        workspace = create_private_windows_workspace(args.label)
        store = Store(workspace.database)
        TaskPackages(store, workspace.blobs)
        return {"workspace": str(workspace.root),
                "database": str(workspace.database),
                "blobs": str(workspace.blobs),
                "windows_private_acl_provisioned": True,
                "remote_actions_permitted": False}
    if args.command == "staging-audit":
        if not 0 <= args.older_than_hours <= 8760:
            raise ValueError("invalid staging audit age in hours")
        if args.delete_managed_v2 and args.older_than_hours < 1:
            raise ValueError("managed V2 deletion requires minimum age of one hour")
        root = private.require_staging_root(args.root) if private else args.root
        result = cleanup_managed_stages(
            root, min_age_seconds=args.older_than_hours * 3600,
            dry_run=not args.delete_managed_v2
        )
        return {**result, "remote_actions_permitted": False}
    if private is None and not args.db:
        raise ValueError("--db, CHATGPT_ORCHESTRATOR_DB or --private-workspace must be set")
    if args.command == "backup-local-db":
        location = snapshot_sqlite_same_directory(private.database if private else args.db, args.filename)
        return {"backup": str(location), "remote_actions_permitted": False}
    db_path = private.database if private else Path(args.db).expanduser().resolve()
    if private:
        if args.command in {"create-task", "seal-task"}:
            private.require_path(args.prompt_file)
        if args.command == "seal-task":
            for attachment in args.attachment:
                private.require_path(attachment)
            if args.allowed_root is not None:
                private.require_path(args.allowed_root, directory=True)
            elif args.attachment:
                args.allowed_root = str(private.root)
        if args.command == "worker-claim":
            private.require_blob_root(args.blob_root)
    if args.command in OBS_COMMANDS:
        return execute_observer_command(args, db_path)
    if args.command in WORKER_READ_COMMANDS and not db_path.is_file():
        raise FileNotFoundError(f"database does not exist: {db_path}")
    if args.command in WORKER_COMMANDS - WORKER_READ_COMMANDS:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    # Reads must not accidentally create a blank DB and conceal configuration errors.
    if args.command in {"status", "list-tasks", "task", "events", "resolve-resource", "list-resources", "task-package", "delivery-events"} and not db_path.is_file():
        raise FileNotFoundError(f"database does not exist: {db_path}")
    if args.command in {"create-task", "claim", "recover", "register-resource", "seal-task", "ack-delivery-event", "reconcile-dispatch"}:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    store = Store(db_path)
    if args.command in WORKER_COMMANDS:
        return execute_worker_command(args, store)
    if args.command in {"seal-task", "task-package", "delivery-events", "ack-delivery-event", "reconcile-dispatch"}:
        packages = TaskPackages(store, private.blobs if private else db_path.parent / "orchestrator_blobs")
        outbox = DispatchOutbox(store, packages)
        if args.command == "seal-task":
            file = Path(args.prompt_file).expanduser().resolve(strict=True)
            if not file.is_file() or file.stat().st_size > 1024 * 1024:
                raise ValueError("invalid prompt file")
            return packages.seal(args.id, file.read_text(encoding="utf-8"),
                                 args.attachment, allowed_root=args.allowed_root)
        if args.command == "task-package":
            package = packages.read(args.id)
            return {k: v for k, v in package.items() if k != "prompt"}
        if args.command == "delivery-events":
            return {"events": outbox.events(args.after, args.limit)}
        if args.command == "ack-delivery-event":
            return {"acked": outbox.acknowledge_event(args.consumer, args.event_id)}
        return {"quarantined": outbox.reconcile_stale(args.stale_seconds),
                "automatic_resend": False}
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