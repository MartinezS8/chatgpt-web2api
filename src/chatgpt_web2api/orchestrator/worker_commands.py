"""Optional CLI command group for PR-03; no web actions are exposed."""
from __future__ import annotations

from .capabilities import capabilities
from .scheduler import Scheduler
from .supervisor import Supervisor
from .worker_registry import WorkerRegistry, WorkerSpec

WORKER_COMMANDS = frozenset({
    "worker-capabilities", "register-worker", "list-workers",
    "worker-assignments", "worker-heartbeat", "worker-claim",
    "pause-workers", "resume-workers", "throttle-workers",
    "scan-workers", "worker-alerts", "enable-worker", "disable-worker",
})
WORKER_READ_COMMANDS = frozenset({"list-workers", "worker-assignments", "worker-alerts"})


def configure_worker_commands(commands):
    commands.add_parser("worker-capabilities", help="Explicit offline-only worker capabilities")
    p = commands.add_parser("register-worker", help="Register a logical worker (real transport disabled)")
    for name in ("id", "account", "project", "session-key"):
        p.add_argument("--" + name, required=True)
    p.add_argument("--role", choices=("implement", "review", "planning"), required=True)
    p.add_argument("--transport", choices=("mock", "codex_app_server", "chatgpt_ui"),
                   default="mock")
    p.add_argument("--disabled", action="store_true",
                   help="Required for unverified non-mock transport identities")
    for name in ("list-workers", "worker-assignments", "pause-workers", "resume-workers",
                 "worker-alerts", "scan-workers", "throttle-workers"):
        p = commands.add_parser(name)
        p.add_argument("--account", required=True)
        if name == "scan-workers":
            p.add_argument("--stale-after", type=int, default=300)
        if name == "throttle-workers":
            p.add_argument("--seconds", type=float, required=True)
    for name in ("enable-worker", "disable-worker"):
        p = commands.add_parser(name, help="Enable or disable one logical worker; never sends")
        p.add_argument("--id", required=True)
    p = commands.add_parser("worker-heartbeat")
    p.add_argument("--id", required=True)
    p = commands.add_parser("worker-claim", help="Atomically reserve a sealed mock task; NEVER sends")
    p.add_argument("--account", required=True)
    p.add_argument("--project", required=True)
    p.add_argument("--blob-root", required=True)
    p.add_argument("--max-slots", type=int, default=5)


def execute_worker_command(args, store):
    if args.command == "worker-capabilities":
        return capabilities()
    registry = WorkerRegistry(store)
    if args.command == "register-worker":
        created = registry.register(WorkerSpec(args.id, args.account, args.project,
                              args.role, args.transport, args.session_key,
                              enabled=not args.disabled))
        return {"worker_id": args.id, "created": created, "external_actions": False}
    if args.command == "list-workers":
        workers = registry.list(args.account)
        return {"account": args.account, "workers": [
            {key: value for key, value in worker.items() if key != "session_key"}
            for worker in workers
        ]}
    if args.command == "worker-assignments":
        return {"account": args.account, "assignments": registry.assignments(args.account)}
    if args.command == "worker-heartbeat":
        return {"worker_id": args.id, "found": registry.heartbeat(args.id)}
    if args.command in {"enable-worker", "disable-worker"}:
        enabled = args.command == "enable-worker"
        changed = registry.set_enabled(args.id, enabled)
        worker = registry.get(args.id)
        return {
            "worker_id": args.id,
            "found": worker is not None,
            "enabled": bool(worker["enabled"]) if worker is not None else None,
            "changed": changed,
            "external_actions": False,
        }
    supervisor = Supervisor(store,registry)
    if args.command == "pause-workers":
        return supervisor.pause(args.account)
    if args.command == "resume-workers":
        return supervisor.resume(args.account)
    if args.command == "throttle-workers":
        return supervisor.throttle(args.account,args.seconds)
    if args.command == "scan-workers":
        return {"stale": supervisor.scan(args.account,stale_after=args.stale_after),
                "automatic_resend": False}
    if args.command == "worker-alerts":
        return {"alerts": supervisor.alerts(args.account)}
    if args.command == "worker-claim":
        from .task_packages import TaskPackages
        packages = TaskPackages(store,args.blob_root)
        claim = Scheduler(store,registry,packages).claim_next(args.account,args.project,
                                                            max_slots=args.max_slots)
        if claim is None:
            return {"reserved": None, "remote_send_permitted": False}
        public = dict(claim["task"])
        public.pop("claim_token",None)
        # Only controller code may access fencing tokens; CLI is observational.
        return {"reserved": public, "worker_id": claim["worker_id"],
                "remote_send_permitted": False}
    raise ValueError("unknown worker command")
