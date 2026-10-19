"""Read-only CLI diagnostics for PR-04 evidence/review/repair lifecycle."""
from __future__ import annotations

from .store import Store

READ_COMMANDS = frozenset({
    "callback-receipts", "evidence-snapshot", "review-observations", "repair-proposals",
})


def configure_review_commands(parsers) -> None:
    for command, description, argument in (
        ("callback-receipts", "List correlated local callback receipts", "--attempt"),
        ("evidence-snapshot", "Inspect locally verified GitHub proof (not a live CI check)", "--task"),
        ("review-observations", "Read untrusted review observations (NOT authorization)", "--task"),
        ("repair-proposals", "Read proposed fix metadata; never enqueue automatically", "--task"),
    ):
        sub = parsers.add_parser(command, help=description)
        sub.add_argument(argument, required=True)


def execute_review_command(args, store: Store) -> dict:
    if args.command not in READ_COMMANDS:
        raise ValueError("unknown PR-04 read command")
    if args.command == "callback-receipts":
        table = "orchestrator_callback_receipts"
        sql = "SELECT event_id,attempt_id,kind,received_at FROM " + table + " WHERE attempt_id=? ORDER BY received_at,event_id"
        ident = args.attempt
    elif args.command == "evidence-snapshot":
        table = "orchestrator_verified_evidence"
        sql = "SELECT task_id,repository_id,pr_number,head_sha,required_checks,verified_at FROM " + table + " WHERE task_id=?"
        ident = args.task
    elif args.command == "review-observations":
        table = "orchestrator_review_observations"
        sql = "SELECT review_task_id,target_task_id,reviewer_worker_id,commit_sha,decision,authorization,observed_at FROM " + table + " WHERE target_task_id=? ORDER BY observed_at"
        ident = args.task
    else:
        table = "orchestrator_repair_proposals"
        sql = "SELECT proposal_id,target_task_id,review_task_id,iteration,source_head_sha,prompt_sha256,state,created_at FROM " + table + " WHERE target_task_id=? ORDER BY iteration"
        ident = args.task
    with store._connect() as db:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        if not exists:
            raise ValueError(f"{table} not initialized; no PR-04 data exists")
        rows = [dict(r) for r in db.execute(sql, (ident,))]
    return {"records": rows, "authoritative_live_check": False, "release_approved": False}
