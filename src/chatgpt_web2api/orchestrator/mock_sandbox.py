"""Fixed synthetic DAG; receipts never release production locks or finalize tasks.

Only cooperating controller code in a validated private workspace is supported.
This module has no network/browser adapter and no real send permission.
"""
from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor

from .callback_inbox import CallbackInbox
from .evidence import EvidenceLedger
from .outbox import DispatchOutbox
from .planner import Planner
from .review_policy import ReviewLedger
from .scheduler import Scheduler
from .store import Store, TaskSpec, TaskState
from .task_packages import TaskPackages
from .upload_preflight import UploadPreflight
from .worker_registry import WorkerRegistry, WorkerSpec

PROJECT = "offline-demo"
HEAD = "a" * 40
TASKS = (
    ("01-a", "implement", (), ("github:repo/1/demo/a",), None),
    ("02-b", "implement", (), ("github:repo/1/demo/b",), None),
    ("03-review-a", "review", ("01-a",), (), "01-a"),
    ("04-review-b", "review", ("02-b",), (), "02-b"),
    ("05-summary", "planning", ("03-review-a", "04-review-b"), (), None),
)


def prompt_for(task_id):
    return f"OFFLINE SYNTHETIC DEMO ONLY: {task_id}. No provider actions or approval."


class _FakeAdapters:
    def snapshot(self, worker_id, task_id):
        return {"worker_id": worker_id, "transport": "mock", "model": "fake-model",
                "effort": "fake-effort", "available_apps": [],
                "selected_apps_this_message": [], "user_approval_pending": False,
                "upload_supported": True}

    def upload(self, attachment, blob_path):
        return {key: attachment[key] for key in ("sha256", "size", "media_type")} | {
            "remote_id": "fake:" + attachment["sha256"]}

    def inspect_pr(self, repository_id, pr_number):
        return {"repository_id": repository_id, "number": pr_number,
                "head_sha": HEAD, "state": "open"}

    def inspect_run(self, repository_id, run_id):
        return {"repository_id": repository_id, "id": run_id, "head_sha": HEAD,
                "status": "completed", "conclusion": "success"}


class MockSandbox:
    """Explicit fixed-demo authority; generic schedulers never consume its receipts."""

    def __init__(self, store: Store, packages: TaskPackages, *, nonce: str, create=False):
        if store.storage_policy is None or packages.store is not store:
            raise ValueError("demo requires one protected Store and policy-bound packages")
        store.storage_policy.check()
        self.store, self.packages, self.nonce = store, packages, nonce
        with store._connect() as db:
            if create:
                db.execute("BEGIN IMMEDIATE")
                if db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]:
                    raise ValueError("demo cannot adopt existing tasks")
                db.execute("CREATE TABLE orchestrator_demo_identity (nonce TEXT PRIMARY KEY)")
                db.execute("INSERT INTO orchestrator_demo_identity VALUES(?)", (nonce,))
                db.execute("""CREATE TABLE orchestrator_demo_completed (
                    task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),
                    attempt_id TEXT NOT NULL UNIQUE, package_sha256 TEXT NOT NULL,
                    worker_id TEXT NOT NULL UNIQUE, result_ref TEXT NOT NULL,
                    assurance TEXT NOT NULL CHECK(assurance='offline_demo_only'), at REAL NOT NULL,
                    claim_version INTEGER NOT NULL, claim_token_hash TEXT NOT NULL,
                    assignment_claim_version INTEGER NOT NULL, session_sha256 TEXT NOT NULL
                )""")
            identity = db.execute("SELECT nonce FROM orchestrator_demo_identity").fetchall()
            if len(identity) != 1 or identity[0][0] != nonce:
                raise ValueError("demo nonce mismatch")
        self.workers = WorkerRegistry(store)
        self.outbox = DispatchOutbox(store, packages)
        self.callbacks = CallbackInbox(store, self.outbox)
        self.evidence = EvidenceLedger(store)
        self.reviews = ReviewLedger(store)
        self.preflight = UploadPreflight(store, packages)
        Planner(store)  # Empty proposal schema allows every observer tool to read.

    def initialize(self):
        """Only fixed synthetic files/tasks; reopen never overwrites changed inputs."""
        root = self.store.storage_policy.check().root
        for task_id, role, deps, scopes, review_of in TASKS:
            text = prompt_for(task_id)
            source = root / f"{task_id}.txt"
            self.store.storage_policy.check()
            if not source.exists():
                with source.open("x", encoding="utf-8", newline="") as stream:
                    stream.write(text)
            self.store.storage_policy.source(source)
            if source.read_text(encoding="utf-8") != text:
                raise ValueError("synthetic demo source changed; use a new workspace")
            self.store.create(TaskSpec(task_id, PROJECT, role, text, deps, scopes, HEAD, review_of))
            self.packages.seal(task_id, source.read_text(encoding="utf-8"), [source],
                               allowed_root=root)
        for number, role in enumerate(("implement", "implement", "review", "review", "planning"), 1):
            self.workers.register(WorkerSpec(f"mock-{number}", PROJECT, PROJECT,
                                              role, "mock", f"fake:demo-{number}"))

    def completed_locked(self, db, project_id):
        if project_id != PROJECT:
            raise ValueError("sandbox project mismatch")
        identity = db.execute("SELECT nonce FROM orchestrator_demo_identity").fetchall()
        if len(identity) != 1 or identity[0][0] != self.nonce:
            raise ValueError("demo nonce mismatch")
        rows = db.execute("SELECT task_id,project_id,role,prompt_sha,dependencies,write_scopes,review_of,baseline_sha FROM tasks").fetchall()
        expected = {task_id: (role, deps, scopes, review_of)
                    for task_id, role, deps, scopes, review_of in TASKS}
        if {row["task_id"] for row in rows} != set(expected):
            raise ValueError("sandbox contains unexpected or missing tasks")
        for row in rows:
            role, deps, scopes, review_of = expected[row["task_id"]]
            if (row["project_id"] != PROJECT or row["role"] != role or row["baseline_sha"] != HEAD
                    or json.loads(row["dependencies"]) != list(deps)
                    or json.loads(row["write_scopes"]) != list(scopes)
                    or row["review_of"] != review_of
                    or row["prompt_sha"] != hashlib.sha256(prompt_for(row["task_id"]).encode()).hexdigest()):
                raise ValueError("sandbox task definition changed")
        receipts = db.execute("""SELECT c.task_id,t.claim_token,c.claim_token_hash,
            w.session_key,c.session_sha256 FROM orchestrator_demo_completed c
            JOIN tasks t ON t.task_id=c.task_id
            JOIN orchestrator_dispatch_attempts a ON a.attempt_id=c.attempt_id AND a.task_id=c.task_id
            JOIN orchestrator_task_packages p ON p.task_id=c.task_id
            JOIN orchestrator_worker_assignments wa ON wa.task_id=c.task_id AND wa.worker_id=c.worker_id
            JOIN orchestrator_workers w ON w.worker_id=c.worker_id
            WHERE c.assurance='offline_demo_only' AND t.state='verified'
            AND t.claim_version=c.claim_version AND a.claim_token_hash=c.claim_token_hash
            AND a.conversation_id=w.session_key AND t.conversation_id=a.conversation_id
            AND a.delivery_id=t.delivery_id AND a.delivery_id='fake:'||c.task_id
            AND wa.state='active' AND wa.claim_version=c.assignment_claim_version
            AND w.role=t.role AND w.account_id='offline-demo'
            AND a.status='completed' AND a.result_ref=c.result_ref
            AND a.package_sha256=c.package_sha256 AND p.package_sha256=c.package_sha256
            AND w.transport='mock' AND w.enabled=1 AND w.project_id=?""", (PROJECT,)).fetchall()
        return {row["task_id"] for row in receipts if row["claim_token"] and
                hashlib.sha256(row["claim_token"].encode()).hexdigest() == row["claim_token_hash"] and
                hashlib.sha256(row["session_key"].encode()).hexdigest() == row["session_sha256"]}

    def claim_wave(self):
        scheduler = Scheduler(self.store, self.workers, self.packages)
        claims = []
        for _ in range(5):
            claim = scheduler.claim_next(PROJECT, PROJECT, lease_seconds=1800,
                                         mock_sandbox=self)
            if claim is None:
                break
            claims.append(claim)
        return claims

    def prepare_intent(self, claim):
        task_id, worker_id = claim["task"]["task_id"], claim["worker_id"]
        current = self.store.get(task_id)
        worker = self.workers.get(worker_id)
        if (current is None or current != claim["task"] or current["project_id"] != PROJECT
                or worker is None or worker["session_key"] != claim["session_key"]):
            raise ValueError("demo claim/session snapshot changed")
        result = self.preflight.check_mock(
            task_id=task_id, worker_id=worker_id, model="fake-model", effort="fake-effort",
            required_apps=(), capability=_FakeAdapters(), uploader=_FakeAdapters())
        if not result["mock_ready"] or result["live_send_permitted"]:
            raise ValueError("mock upload preflight failed closed")
        return self.outbox.begin_preflighted_mock(
            task_id=task_id, worker_id=worker_id, claim_token=claim["task"]["claim_token"])

    def execute_claim(self, claim):
        task, worker = claim["task"], claim["worker_id"]
        task_id, token = task["task_id"], task["claim_token"]
        intent = self.prepare_intent(claim)
        if not intent["new_send_permit"] or intent["remote_send_permitted"]:
            raise ValueError("no new in-process mock permit; reconcile manually")
        attempt = intent["attempt_id"]
        conversation, delivery = claim["session_key"], "fake:" + task_id
        self.outbox.accept(attempt, token, conversation, delivery)
        correlation = dict(attempt_id=attempt, worker_id=worker,
                           conversation_id=conversation, delivery_id=delivery)
        advisory = dict(**correlation, sequence=1, kind="progress", message="synthetic mock result")
        self.callbacks.progress(**advisory)
        if self.callbacks.progress(**advisory):
            raise ValueError("duplicate callback was reapplied")
        result_ref = "fake:result:" + task_id
        self.callbacks.complete_mock(**correlation, result_ref=result_ref)
        if self.callbacks.complete_mock(**correlation, result_ref=result_ref):
            raise ValueError("duplicate result was reapplied")
        if not self.store.transition(task_id, TaskState.RESULT_RECEIVED, TaskState.VERIFIED,
                                     claim_token=token):
            raise ValueError("mock result ownership changed")
        if task["role"] == "implement":
            self.evidence.inspect_mock(task_id=task_id, repository_id="1", pr_number=1,
                expected_head_sha=HEAD, run_id=1, probe=_FakeAdapters())
        if task["role"] == "review":
            self.reviews.record_mock(target_task_id=task["review_of"], reviewer_task_id=task_id,
                                      decision="approved", head_sha=HEAD)
        package = self.packages.read(task_id)
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            done = self.completed_locked(db, PROJECT)
            if not set(json.loads(task["dependencies"])).issubset(done):
                raise ValueError("synthetic dependencies incomplete")
            # Receipt only: task remains VERIFIED; slot and write locks remain held.
            current = self.store.get_row(db, task_id)
            assigned = db.execute("SELECT claim_version FROM orchestrator_worker_assignments WHERE task_id=?",
                                  (task_id,)).fetchone()
            db.execute("INSERT INTO orchestrator_demo_completed VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (task_id, attempt, package["package_sha256"], worker, result_ref,
                        "offline_demo_only", time.time(), current["claim_version"],
                        hashlib.sha256(current["claim_token"].encode()).hexdigest(), assigned[0],
                        hashlib.sha256(claim["session_key"].encode()).hexdigest()))
        return task_id

    def inspect(self):
        with self.store._connect() as db:
            done = self.completed_locked(db, PROJECT)
            attempts = [dict(row) for row in db.execute("""SELECT task_id,attempt_id,status,
                package_sha256,conversation_id,delivery_id,result_ref FROM orchestrator_dispatch_attempts
                ORDER BY task_id""")]
            cursor = db.execute("SELECT event_id FROM orchestrator_event_cursors WHERE consumer_id=?",
                                (PROJECT,)).fetchone()
            reviews = [dict(row) for row in db.execute("""SELECT target_task_id,reviewer_task_id,
                decision,assurance,implement_worker_id,reviewer_worker_id FROM orchestrator_review_decisions""")]
            packages = [dict(row) for row in db.execute("""SELECT task_id,package_sha256,
                attachments_json FROM orchestrator_task_packages ORDER BY task_id""")]
            uploads = [dict(row) for row in db.execute("""SELECT task_id,attachment_sha256 AS sha256,
                size,media_type,remote_id,state FROM orchestrator_upload_parts ORDER BY task_id,ordinal""")]
            callback_count = db.execute("SELECT COUNT(*) FROM orchestrator_callback_inbox").fetchone()[0]
        tasks = self.store.all(PROJECT)
        workers = self.workers.list(PROJECT)
        blocked = (len(workers) != 5 or any(not worker["enabled"] for worker in workers)
                   or any(task["state"] != "queued" and task["task_id"] not in done for task in tasks))
        public_attempts = [{key: value for key, value in attempt.items() if key != "conversation_id"}
                           | {"session_sha256": hashlib.sha256((attempt["conversation_id"] or "").encode()).hexdigest()}
                           for attempt in attempts]
        return {"status": "demo_complete" if len(done) == 5 else "needs_human" if blocked else "ready",
                "mock_completed": len(done), "workers_used": len({a["conversation_id"] for a in attempts if a["status"] == "completed"}),
                "tasks": [{key: row[key] for key in ("task_id", "state", "dependencies", "slot")}
                          | {"demo_status": "mock_completed" if row["task_id"] in done else "pending"}
                          for row in tasks],
                "workers": [{key: row[key] for key in ("worker_id", "role", "transport", "enabled")}
                            | {"session_sha256": hashlib.sha256(row["session_key"].encode()).hexdigest()}
                            for row in workers],
                "attempts": public_attempts, "reviews": reviews,
                "packages": [{"task_id": row["task_id"], "package_sha256": row["package_sha256"],
                              "attachments": json.loads(row["attachments_json"])} for row in packages],
                "mock_upload_receipts": uploads, "callback_count": callback_count,
                "event_cursor": cursor[0] if cursor else 0,
                "assurance": "offline_demo_only", "production_finalization_permitted": False,
                "remote_send_permitted": False, "production_locks_released": False}

    def run(self, *, crash_after_intent=False):
        for task_id, *_ in TASKS:
            self.packages.read(task_id, verify_blobs=True)
        self.store.recover(PROJECT)
        # A previous process lost its in-memory permit. Never reconstruct it.
        for event in self.outbox.events():
            attempt = self.outbox.get(event["attempt_id"])
            if attempt["status"] == "intent":
                self.outbox.mark_unknown(attempt["attempt_id"], "demo_process_restarted")
        before = self.inspect()
        if before["status"] == "needs_human":
            return before
        for worker in self.workers.list(PROJECT):
            self.workers.heartbeat(worker["worker_id"])
        for _ in range(5):
            wave = self.claim_wave()
            if not wave:
                break
            if crash_after_intent:
                self.prepare_intent(wave[0])
                # Only this explicitly requested synthetic demo child exits.
                import os
                os._exit(17)
            with ThreadPoolExecutor(max_workers=len(wave)) as pool:
                list(pool.map(self.execute_claim, wave))
        for event in self.outbox.consumer_events(PROJECT):
            self.outbox.acknowledge_event(PROJECT, event["id"])
        return self.inspect()
