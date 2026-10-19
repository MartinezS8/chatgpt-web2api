"""Read-only CLI observer command group; never accepts claim/approval tokens."""
from __future__ import annotations

from .observer import Observer

OBS_COMMANDS = frozenset({"observe-capabilities", "observe-status", "observe-events",
                         "observe-workers", "observe-reviews", "observe-evidence",
                         "observe-proposals", "observe-callbacks"})


def configure_observer_commands(commands):
    commands.add_parser("observe-capabilities", help="List available read-only observer capabilities")
    for name in OBS_COMMANDS - {"observe-capabilities"}:
        p=commands.add_parser(name)
        if name=="observe-status":p.add_argument("--project",required=True)
        if name=="observe-workers":p.add_argument("--account",required=True)
        if name in {"observe-reviews","observe-proposals"}:p.add_argument("--task",required=True)
        if name=="observe-evidence":p.add_argument("--task",required=True)
        if name in {"observe-events","observe-callbacks"}:
            p.add_argument("--after",type=int,default=0)
            p.add_argument("--limit",type=int,default=100)


def execute_observer_command(args, database):
    if args.command=="observe-capabilities":
        return {"mode":"read-only-observer", "live_transport":False,
                "commands":sorted(OBS_COMMANDS)}
    obs=Observer(database)
    if args.command=="observe-status":return obs.status(args.project)
    if args.command=="observe-workers":return obs.workers(args.account)
    if args.command=="observe-reviews":return obs.reviews(args.task)
    if args.command=="observe-proposals":return obs.proposals(args.task)
    if args.command=="observe-evidence":return obs.evidence(args.task)
    if args.command=="observe-events":return obs.events(after=args.after,limit=args.limit)
    if args.command=="observe-callbacks":return obs.callbacks(after=args.after,limit=args.limit)
    raise ValueError("unsupported observer operation")

