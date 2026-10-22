"""Durable correlation and quarantine for the offline app-server fake only.

This ledger records hashes, opaque identifiers and state transitions. It never
stores prompts, app-server payloads, claim tokens or worker session keys. Its
transport entry point accepts only :class:`OfflineFakeAppServer`; it is not a
live Codex/app-server adapter and does not grant send or finalization authority.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import time
from typing import TYPE_CHECKING, Any

from .app_server_fake import UnknownDelivery
from .store import TaskState

if TYPE_CHECKING:
    from .outbox import DispatchOutbox
    from .store import Store

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LEDGER_VERSION = 1
_OUTGOING_METHODS = frozenset({
    "initialize", "initialized", "model/list", "thread/start", "turn/start",
})
_DISPOSITIONS = frozenset({"delivery_unresolved", "delivery_confirmed", "non_delivery_confirmed"})
_REASONS = frozenset({
    "no_external_evidence", "external_evidence_reviewed", "operator_requested_review",
})


def _sha256(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("expected text to hash")
    try:
        return hashlib.sha256(value.encode("utf-8", errors="strict")).hexdigest()
    except UnicodeEncodeError:
        raise ValueError("text is not valid Unicode") from None


def _is_identifier(value: Any) -> bool:
    return isinstance(value, str) and _IDENTIFIER.fullmatch(value) is not None


class AppServerDeliveryLedger:
    """Schema-versioned app-server attempt ledger bound to one dispatch outbox.

    A completed offline fake is recorded as ``transport_completed_unverified``
    and leaves the task in ``needs_human``. Recovery never issues a new attempt.
    Operator dispositions are audit annotations only; they cannot clear a
    quarantine, authorize a send, attach evidence, or finalize a task.
    """

    def __init__(self, outbox: DispatchOutbox):
        from .outbox import DispatchOutbox

        if type(outbox) is not DispatchOutbox:
            raise TypeError("app-server ledger requires the canonical dispatch outbox")
        self.outbox = outbox
        self.store: Store = outbox.store
        self._migrate()

    def _migrate(self) -> None:
        """Create version 1 atomically and reject unknown or partial layouts."""
        tables = {
            "orchestrator_app_server_attempts",
            "orchestrator_app_server_messages",
            "orchestrator_app_server_events",
            "orchestrator_app_server_operator_dispositions",
        }
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            version_row = db.execute(
                "SELECT version FROM orchestrator_schema_versions "
                "WHERE component='app-server-delivery-ledger'"
            ).fetchone()
            existing = {
                row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ) if row[0] in tables
            }
            if version_row is not None:
                if version_row["version"] != _LEDGER_VERSION:
                    raise ValueError("unsupported app-server ledger schema version")
                if existing != tables:
                    raise ValueError("versioned app-server ledger schema is incomplete")
                self._validate_columns(db)
                return
            if existing:
                raise ValueError("unversioned app-server ledger schema is not trusted")

            db.execute("""CREATE TABLE orchestrator_app_server_attempts (
                attempt_id TEXT PRIMARY KEY REFERENCES orchestrator_dispatch_attempts(attempt_id),
                controller_id TEXT NOT NULL,
                worker_id TEXT NOT NULL,
                account_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                transport TEXT NOT NULL CHECK(transport='mock'),
                transport_identity_sha256 TEXT NOT NULL CHECK(length(transport_identity_sha256)=64),
                package_sha256 TEXT NOT NULL CHECK(length(package_sha256)=64),
                claim_token_sha256 TEXT NOT NULL CHECK(length(claim_token_sha256)=64),
                claim_version INTEGER NOT NULL CHECK(claim_version > 0),
                assignment_version INTEGER NOT NULL CHECK(assignment_version > 0),
                prompt_sha256 TEXT NOT NULL CHECK(length(prompt_sha256)=64),
                status TEXT NOT NULL CHECK(status IN (
                    'prepared','running_offline_fake','unknown_delivery','needs_human',
                    'not_sent_recovered','offline_not_sent','transport_completed_unverified'
                )),
                thread_id TEXT,
                turn_id TEXT,
                terminal_seen INTEGER NOT NULL DEFAULT 0 CHECK(terminal_seen IN (0,1)),
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )""")
            db.execute("""CREATE TABLE orchestrator_app_server_messages (
                attempt_id TEXT NOT NULL REFERENCES orchestrator_app_server_attempts(attempt_id),
                message_seq INTEGER NOT NULL CHECK(message_seq > 0),
                message_kind TEXT NOT NULL CHECK(message_kind IN ('request','notification')),
                request_id INTEGER,
                method TEXT NOT NULL,
                message_sha256 TEXT NOT NULL CHECK(length(message_sha256)=64),
                status TEXT NOT NULL CHECK(status IN ('intent','written','acknowledged','unknown')),
                response_sha256 TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY(attempt_id,message_seq),
                UNIQUE(attempt_id,request_id),
                CHECK((message_kind='request' AND request_id IS NOT NULL)
                   OR (message_kind='notification' AND request_id IS NULL))
            )""")
            db.execute("""CREATE TABLE orchestrator_app_server_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attempt_id TEXT NOT NULL REFERENCES orchestrator_app_server_attempts(attempt_id),
                event_key TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL,
                message_seq INTEGER,
                request_id INTEGER,
                code TEXT,
                created_at REAL NOT NULL
            )""")
            db.execute("""CREATE TABLE orchestrator_app_server_operator_dispositions (
                attempt_id TEXT PRIMARY KEY REFERENCES orchestrator_app_server_attempts(attempt_id),
                operator_ref_sha256 TEXT NOT NULL CHECK(length(operator_ref_sha256)=64),
                disposition TEXT NOT NULL CHECK(disposition IN (
                    'delivery_unresolved','delivery_confirmed','non_delivery_confirmed'
                )),
                reason_code TEXT NOT NULL CHECK(reason_code IN (
                    'no_external_evidence','external_evidence_reviewed','operator_requested_review'
                )),
                created_at REAL NOT NULL
            )""")
            db.execute("""CREATE TRIGGER orchestrator_app_server_events_no_update
                BEFORE UPDATE ON orchestrator_app_server_events
                BEGIN SELECT RAISE(ABORT,'app-server audit events are append-only'); END""")
            db.execute("""CREATE TRIGGER orchestrator_app_server_events_no_delete
                BEFORE DELETE ON orchestrator_app_server_events
                BEGIN SELECT RAISE(ABORT,'app-server audit events are append-only'); END""")
            db.execute("""CREATE TRIGGER orchestrator_app_server_dispositions_no_update
                BEFORE UPDATE ON orchestrator_app_server_operator_dispositions
                BEGIN SELECT RAISE(ABORT,'operator dispositions are append-only'); END""")
            db.execute("""CREATE TRIGGER orchestrator_app_server_dispositions_no_delete
                BEFORE DELETE ON orchestrator_app_server_operator_dispositions
                BEGIN SELECT RAISE(ABORT,'operator dispositions are append-only'); END""")
            self._validate_columns(db)
            db.execute(
                "INSERT INTO orchestrator_schema_versions(component,version,updated_at) "
                "VALUES('app-server-delivery-ledger',?,?)",
                (_LEDGER_VERSION, time.time()),
            )

    @staticmethod
    def _validate_columns(db) -> None:
        expected = {
            "orchestrator_app_server_attempts": {
                "attempt_id", "controller_id", "worker_id", "account_id", "project_id",
                "task_id", "transport", "transport_identity_sha256", "package_sha256",
                "claim_token_sha256", "claim_version", "assignment_version", "prompt_sha256",
                "status", "thread_id", "turn_id", "terminal_seen", "created_at", "updated_at",
            },
            "orchestrator_app_server_messages": {
                "attempt_id", "message_seq", "message_kind", "request_id", "method",
                "message_sha256", "status", "response_sha256", "created_at", "updated_at",
            },
            "orchestrator_app_server_events": {
                "id", "attempt_id", "event_key", "kind", "message_seq", "request_id",
                "code", "created_at",
            },
            "orchestrator_app_server_operator_dispositions": {
                "attempt_id", "operator_ref_sha256", "disposition", "reason_code", "created_at",
            },
        }
        for table, columns in expected.items():
            actual = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
            if not columns.issubset(actual):
                raise ValueError("versioned app-server ledger schema is incomplete")
        trigger_names = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        )}
        required_triggers = {
            "orchestrator_app_server_events_no_update",
            "orchestrator_app_server_events_no_delete",
            "orchestrator_app_server_dispositions_no_update",
            "orchestrator_app_server_dispositions_no_delete",
        }
        if not required_triggers.issubset(trigger_names):
            raise ValueError("versioned app-server audit protections are incomplete")

    def _event(self, db, attempt_id: str, kind: str, *, message_seq=None,
               request_id=None, code=None) -> None:
        key = f"{attempt_id}/{kind}/{message_seq if message_seq is not None else ''}"
        db.execute("""INSERT OR IGNORE INTO orchestrator_app_server_events
            (attempt_id,event_key,kind,message_seq,request_id,code,created_at)
            VALUES (?,?,?,?,?,?,?)""",
            (attempt_id, key, kind, message_seq, request_id, code, time.time()))

    def _binding_row(self, db, attempt_id: str):
        return db.execute("""SELECT d.attempt_id,d.task_id,d.package_sha256,d.claim_token_hash,
                d.status AS dispatch_status,t.project_id AS task_project,t.role AS task_role,
                t.prompt_sha,t.state AS task_state,t.claim_token,t.claim_version AS task_claim_version,
                w.worker_id,w.account_id,w.project_id AS worker_project,w.role AS worker_role,
                w.transport,w.session_key,w.enabled,
                a.claim_version AS assignment_version,a.state AS assignment_state
            FROM orchestrator_dispatch_attempts d
            JOIN tasks t ON t.task_id=d.task_id
            JOIN orchestrator_worker_assignments a ON a.task_id=t.task_id
            JOIN orchestrator_workers w ON w.worker_id=a.worker_id
            WHERE d.attempt_id=?""", (attempt_id,)).fetchone()

    def _prepare(self, fake, *, claim_token: str, prompt: str) -> dict:
        binding = fake.binding
        if (not _is_identifier(binding.controller_id) or not _is_identifier(binding.worker_id)
                or not _is_identifier(binding.account_id) or not _is_identifier(binding.project_id)
                or not _is_identifier(binding.task_id) or not _is_identifier(binding.attempt_id)):
            raise ValueError("invalid immutable offline attempt binding")
        if not isinstance(claim_token, str) or not claim_token:
            raise ValueError("current claim is required")
        claim_hash = _sha256(claim_token)
        prompt_hash = _sha256(prompt)
        package = self.outbox.packages.read(binding.task_id, verify_blobs=True)
        now = time.time()
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM orchestrator_app_server_attempts WHERE attempt_id=?",
                (binding.attempt_id,),
            ).fetchone()
            row = self._binding_row(db, binding.attempt_id)
            if row is None:
                raise ValueError("no durable dispatch binding for app-server attempt")
            if row["prompt_sha"] != prompt_hash:
                raise ValueError("prompt hash differs from immutable task specification")
            if (row["task_id"] != binding.task_id or row["worker_id"] != binding.worker_id
                    or row["account_id"] != binding.account_id
                    or row["task_project"] != binding.project_id
                    or row["worker_project"] != binding.project_id):
                raise ValueError("app-server worker binding differs from dispatch assignment")
            immutable = (
                row["task_id"] == binding.task_id
                and row["worker_id"] == binding.worker_id
                and row["account_id"] == binding.account_id
                and row["task_project"] == binding.project_id
                and row["worker_project"] == binding.project_id
                and row["worker_role"] == row["task_role"]
                and row["transport"] == "mock"
                and row["enabled"] == 1
                and row["assignment_state"] == "active"
                and row["session_key"].startswith("fake:")
                and hmac.compare_digest(row["claim_token_hash"], claim_hash)
                and hmac.compare_digest(_sha256(row["claim_token"] or ""), claim_hash)
                and row["package_sha256"] == package["package_sha256"]
            )
            if not immutable:
                raise ValueError("app-server worker, package, claim or prompt binding mismatch")
            transport_identity_hash = _sha256(
                f"{row['transport']}\0{row['account_id']}\0{row['worker_project']}\0{row['session_key']}"
            )
            if existing is not None:
                expected = (
                    binding.controller_id, binding.worker_id, binding.account_id,
                    binding.project_id, binding.task_id, transport_identity_hash,
                    package["package_sha256"], claim_hash, prompt_hash,
                )
                actual = tuple(existing[key] for key in (
                    "controller_id", "worker_id", "account_id", "project_id", "task_id",
                    "transport_identity_sha256", "package_sha256", "claim_token_sha256",
                    "prompt_sha256",
                ))
                if actual != expected:
                    raise ValueError("app-server attempt binding changed")
                return dict(existing)
            if (row["dispatch_status"] != "intent"
                    or row["task_state"] != TaskState.DISPATCHING.value
                    or row["task_claim_version"] != row["assignment_version"] + 1
                    or row["task_role"] != row["worker_role"]):
                raise ValueError("app-server dispatch assignment is stale")
            db.execute("""INSERT INTO orchestrator_app_server_attempts
                (attempt_id,controller_id,worker_id,account_id,project_id,task_id,transport,
                 transport_identity_sha256,package_sha256,claim_token_sha256,claim_version,
                 assignment_version,prompt_sha256,status,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'prepared',?,?)""",
                (binding.attempt_id, binding.controller_id, binding.worker_id,
                 binding.account_id, binding.project_id, binding.task_id, row["transport"],
                 transport_identity_hash, package["package_sha256"], claim_hash,
                 row["task_claim_version"], row["assignment_version"], prompt_hash, now, now))
            self._event(db, binding.attempt_id, "attempt.prepared")
            return dict(db.execute(
                "SELECT * FROM orchestrator_app_server_attempts WHERE attempt_id=?",
                (binding.attempt_id,),
            ).fetchone())

    def run_fake(self, fake, *, claim_token: str, prompt: str, cwd: str) -> dict[str, Any]:
        """Run exactly one fixed offline fake attempt and durably quarantine it."""
        from .app_server_fake import OfflineFakeAppServer, ProtocolRejected, UnknownDelivery

        if type(fake) is not OfflineFakeAppServer:
            raise TypeError("durable app-server ledger accepts only the bundled offline fake")
        binding = fake.binding
        row = self._prepare(fake, claim_token=claim_token, prompt=prompt)
        if row["status"] != "prepared":
            raise UnknownDelivery("app-server attempt already started; reconciliation is required")
        self._start(binding.attempt_id)
        try:
            result = fake._run_with_journal(prompt=prompt, cwd=cwd, journal=self)
        except Exception as exc:
            if isinstance(exc, UnknownDelivery):
                code = "transport_unknown"
            elif isinstance(exc, ProtocolRejected):
                code = "protocol_rejected"
            else:
                code = "local_transport_error"
            self._fail(binding.attempt_id, code=code, unknown=isinstance(exc, UnknownDelivery))
            raise
        if result.get("state") == "transport_completed_unverified":
            if not self._finish_success(binding.attempt_id, result):
                raise UnknownDelivery(
                    "offline fake completion failed its durable binding check"
                )
        else:
            self._finish_needs_human(binding.attempt_id, code="offline_terminal_not_verified")
        return result

    def _start(self, attempt_id: str) -> None:
        stale = False
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM orchestrator_app_server_attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if row is None or row["status"] != "prepared":
                raise UnknownDelivery("app-server attempt already started; no retry is permitted")
            if not self._binding_still_current(db, row):
                self._close_locked(
                    db, row, state="needs_human", outbox_state="needs_human",
                    task_state=TaskState.NEEDS_HUMAN.value,
                    code="stale_binding_before_fake_start",
                )
                stale = True
            else:
                db.execute(
                    "UPDATE orchestrator_app_server_attempts SET "
                    "status='running_offline_fake',updated_at=? "
                    "WHERE attempt_id=? AND status='prepared'",
                    (time.time(), attempt_id),
                )
                self._event(db, attempt_id, "attempt.started")
        if stale:
            raise UnknownDelivery("app-server dispatch binding is stale; no fake process started")

    def _message_intent(self, attempt_id: str, *, message_kind: str, request_id: int | None,
                        method: str, message_sha256: str) -> int:
        if (message_kind not in {"request", "notification"} or method not in _OUTGOING_METHODS
                or (message_kind == "request" and type(request_id) is not int)
                or (message_kind == "notification" and request_id is not None)
                or not _SHA256.fullmatch(message_sha256)):
            raise ValueError("invalid outgoing app-server message metadata")
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            attempt = db.execute(
                "SELECT status FROM orchestrator_app_server_attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if attempt is None or attempt["status"] != "running_offline_fake":
                raise UnknownDelivery("app-server attempt is not in a sendable state")
            next_seq = db.execute(
                "SELECT COALESCE(MAX(message_seq),0)+1 FROM orchestrator_app_server_messages "
                "WHERE attempt_id=?", (attempt_id,),
            ).fetchone()[0]
            if message_kind == "request":
                last_id = db.execute(
                    "SELECT COALESCE(MAX(request_id),0) FROM orchestrator_app_server_messages "
                    "WHERE attempt_id=? AND message_kind='request'", (attempt_id,),
                ).fetchone()[0]
                if request_id != last_id + 1:
                    raise ValueError("app-server request id replay or sequence gap")
            now = time.time()
            db.execute("""INSERT INTO orchestrator_app_server_messages
                (attempt_id,message_seq,message_kind,request_id,method,message_sha256,status,
                 created_at,updated_at) VALUES (?,?,?,?,?,?,'intent',?,?)""",
                (attempt_id, next_seq, message_kind, request_id, method, message_sha256, now, now))
            self._event(db, attempt_id, f"message.{message_kind}.intent",
                        message_seq=next_seq, request_id=request_id)
            return next_seq

    def _message_written(self, attempt_id: str, message_seq: int) -> bool:
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status,request_id,message_kind FROM orchestrator_app_server_messages "
                             "WHERE attempt_id=? AND message_seq=?", (attempt_id, message_seq)).fetchone()
            if row is None:
                raise ValueError("app-server message intent not found")
            if row["status"] == "written" or row["status"] == "acknowledged":
                return False
            if row["status"] != "intent":
                raise ValueError("app-server message cannot be marked written")
            db.execute("UPDATE orchestrator_app_server_messages SET status='written',updated_at=? "
                       "WHERE attempt_id=? AND message_seq=?", (time.time(), attempt_id, message_seq))
            self._event(db, attempt_id, f"message.{row['message_kind']}.written",
                        message_seq=message_seq, request_id=row["request_id"])
            return True

    def _message_acknowledged(self, attempt_id: str, message_seq: int, *, response_sha256: str,
                              thread_id: str | None, turn_id: str | None) -> bool:
        if not _SHA256.fullmatch(response_sha256):
            raise ValueError("invalid app-server response digest")
        for identifier in (thread_id, turn_id):
            if identifier is not None and not _is_identifier(identifier):
                raise ValueError("invalid app-server correlation identifier")
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM orchestrator_app_server_messages "
                             "WHERE attempt_id=? AND message_seq=?", (attempt_id, message_seq)).fetchone()
            attempt = db.execute("SELECT thread_id,turn_id,status FROM orchestrator_app_server_attempts "
                                 "WHERE attempt_id=?", (attempt_id,)).fetchone()
            if row is None or attempt is None or row["message_kind"] != "request":
                raise ValueError("app-server request acknowledgement binding not found")
            if attempt["status"] != "running_offline_fake":
                raise UnknownDelivery("app-server attempt is no longer active")
            if row["status"] == "acknowledged":
                if (row["response_sha256"] != response_sha256
                        or (thread_id is not None and attempt["thread_id"] != thread_id)
                        or (turn_id is not None and attempt["turn_id"] != turn_id)):
                    raise ValueError("conflicting duplicate app-server acknowledgement")
                return False
            if row["status"] != "written":
                raise ValueError("app-server acknowledgement has no durable send intent")
            if thread_id is not None and attempt["thread_id"] not in {None, thread_id}:
                raise ValueError("app-server thread correlation changed")
            if turn_id is not None and attempt["turn_id"] not in {None, turn_id}:
                raise ValueError("app-server turn correlation changed")
            now = time.time()
            db.execute("UPDATE orchestrator_app_server_messages SET status='acknowledged',"
                       "response_sha256=?,updated_at=? WHERE attempt_id=? AND message_seq=?",
                       (response_sha256, now, attempt_id, message_seq))
            db.execute("UPDATE orchestrator_app_server_attempts SET thread_id=COALESCE(?,thread_id),"
                       "turn_id=COALESCE(?,turn_id),updated_at=? WHERE attempt_id=?",
                       (thread_id, turn_id, now, attempt_id))
            self._event(db, attempt_id, "message.request.acknowledged",
                        message_seq=message_seq, request_id=row["request_id"])
            return True

    def _capture_notification(self, attempt_id: str, *, method: str,
                              thread_id: str | None, turn_id: str | None) -> None:
        if method not in {"turn/started", "turn/completed"}:
            return
        for identifier in (thread_id, turn_id):
            if identifier is not None and not _is_identifier(identifier):
                raise ValueError("invalid app-server notification correlation identifier")
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT thread_id,turn_id,status FROM orchestrator_app_server_attempts "
                             "WHERE attempt_id=?", (attempt_id,)).fetchone()
            if row is None or row["status"] != "running_offline_fake":
                raise UnknownDelivery("app-server attempt is no longer active")
            if thread_id is not None and row["thread_id"] not in {None, thread_id}:
                raise ValueError("app-server notification belongs to a different thread")
            if turn_id is not None and row["turn_id"] not in {None, turn_id}:
                raise ValueError("app-server notification belongs to a different turn")
            now = time.time()
            terminal = int(method == "turn/completed")
            db.execute("UPDATE orchestrator_app_server_attempts SET thread_id=COALESCE(?,thread_id),"
                       "turn_id=COALESCE(?,turn_id),terminal_seen=MAX(terminal_seen,?),updated_at=? "
                       "WHERE attempt_id=?", (thread_id, turn_id, terminal, now, attempt_id))
            self._event(db, attempt_id, method.replace("/", "."), code="unverified")

    def _finish_success(self, attempt_id: str, result: dict) -> bool:
        now = time.time()
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM orchestrator_app_server_attempts WHERE attempt_id=?",
                             (attempt_id,)).fetchone()
            if row is None or row["status"] != "running_offline_fake":
                raise UnknownDelivery("app-server attempt cannot be finalized")
            pending = db.execute("SELECT 1 FROM orchestrator_app_server_messages "
                                 "WHERE attempt_id=? AND message_kind='request' "
                                 "AND status!='acknowledged' LIMIT 1", (attempt_id,)).fetchone()
            notification_pending = db.execute("SELECT 1 FROM orchestrator_app_server_messages "
                                 "WHERE attempt_id=? AND message_kind='notification' "
                                 "AND status!='written' LIMIT 1", (attempt_id,)).fetchone()
            binding_ok = self._binding_still_current(db, row)
            ids_match = (row["thread_id"] == result.get("thread_id")
                         and row["turn_id"] == result.get("turn_id"))
            if (pending is not None or notification_pending is not None or not binding_ok
                    or not ids_match or not row["terminal_seen"]):
                self._close_locked(db, row, state="needs_human", outbox_state="needs_human",
                                   task_state=TaskState.NEEDS_HUMAN.value,
                                   code="completion_binding_or_evidence_incomplete")
                return False
            db.execute("UPDATE orchestrator_app_server_attempts SET "
                       "status='transport_completed_unverified',updated_at=? WHERE attempt_id=?",
                       (now, attempt_id))
            db.execute("UPDATE orchestrator_dispatch_attempts SET status='offline_simulated_unverified',"
                       "error_code='offline_fake_only',updated_at=? WHERE attempt_id=? AND status='intent'",
                       (now, attempt_id))
            db.execute("UPDATE tasks SET state=?,error=?,lease_until=NULL,claim_version=claim_version+1,"
                       "updated_at=? WHERE task_id=? AND state=? AND claim_token=?",
                       (TaskState.NEEDS_HUMAN.value,
                        "offline app-server fake completed; no provider result or approval exists",
                        now, row["task_id"], TaskState.DISPATCHING.value,
                        self._claim_for_hash_locked(db, row)))
            self._event(db, attempt_id, "attempt.transport_completed_unverified",
                        code="offline_fake_only")
            self.outbox._event(db, attempt_id, row["task_id"],
                               "offline.fake.completed_unverified", {"assurance": "offline_fake_only"})
            return True

    def _binding_still_current(self, db, ledger_row) -> bool:
        row = self._binding_row(db, ledger_row["attempt_id"])
        return bool(
            row is not None
            and row["dispatch_status"] == "intent"
            and row["task_state"] == TaskState.DISPATCHING.value
            and row["worker_id"] == ledger_row["worker_id"]
            and row["account_id"] == ledger_row["account_id"]
            and row["task_project"] == ledger_row["project_id"]
            and row["worker_project"] == ledger_row["project_id"]
            and row["task_role"] == row["worker_role"]
            and row["transport"] == "mock"
            and row["enabled"] == 1
            and row["assignment_state"] == "active"
            and row["assignment_version"] == ledger_row["assignment_version"]
            and row["task_claim_version"] == ledger_row["claim_version"]
            and row["package_sha256"] == ledger_row["package_sha256"]
            and row["prompt_sha"] == ledger_row["prompt_sha256"]
            and hmac.compare_digest(row["claim_token_hash"], ledger_row["claim_token_sha256"])
            and hmac.compare_digest(_sha256(row["claim_token"] or ""),
                                    ledger_row["claim_token_sha256"])
            and _sha256(
                f"{row['transport']}\0{row['account_id']}\0{row['worker_project']}\0{row['session_key']}"
            ) == ledger_row["transport_identity_sha256"]
        )

    @staticmethod
    def _claim_for_hash_locked(db, ledger_row) -> str:
        row = db.execute("SELECT claim_token FROM tasks WHERE task_id=?",
                         (ledger_row["task_id"],)).fetchone()
        if row is None or not hmac.compare_digest(_sha256(row["claim_token"] or ""),
                                                  ledger_row["claim_token_sha256"]):
            return "\0stale-claim"
        return row["claim_token"]

    def _finish_needs_human(self, attempt_id: str, *, code: str) -> None:
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM orchestrator_app_server_attempts WHERE attempt_id=?",
                             (attempt_id,)).fetchone()
            if row is None or row["status"] != "running_offline_fake":
                raise UnknownDelivery("app-server attempt cannot be reconciled")
            self._close_locked(db, row, state="needs_human", outbox_state="needs_human",
                               task_state=TaskState.NEEDS_HUMAN.value, code=code)

    def _fail(self, attempt_id: str, *, code: str, unknown: bool) -> None:
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM orchestrator_app_server_attempts WHERE attempt_id=?",
                             (attempt_id,)).fetchone()
            if row is None or row["status"] != "running_offline_fake":
                return
            message_count = db.execute("SELECT COUNT(*) FROM orchestrator_app_server_messages "
                                       "WHERE attempt_id=?", (attempt_id,)).fetchone()[0]
            pending = db.execute("SELECT 1 FROM orchestrator_app_server_messages "
                                 "WHERE attempt_id=? AND status IN ('intent','written') LIMIT 1",
                                 (attempt_id,)).fetchone()
            if message_count == 0:
                state, outbox_state, task_state = (
                    "offline_not_sent", "offline_not_sent", TaskState.NEEDS_HUMAN.value
                )
            elif unknown or pending is not None:
                state, outbox_state, task_state = (
                    "unknown_delivery", "unknown", TaskState.UNKNOWN_DELIVERY.value
                )
            else:
                state, outbox_state, task_state = (
                    "needs_human", "needs_human", TaskState.NEEDS_HUMAN.value
                )
            self._close_locked(db, row, state=state, outbox_state=outbox_state,
                               task_state=task_state, code=code)

    def _close_locked(self, db, row, *, state: str, outbox_state: str,
                      task_state: str, code: str) -> None:
        now = time.time()
        db.execute("UPDATE orchestrator_app_server_messages SET status='unknown',updated_at=? "
                   "WHERE attempt_id=? AND status IN ('intent','written')",
                   (now, row["attempt_id"]))
        db.execute("UPDATE orchestrator_app_server_attempts SET status=?,updated_at=? "
                   "WHERE attempt_id=?", (state, now, row["attempt_id"]))
        db.execute("UPDATE orchestrator_dispatch_attempts SET status=?,error_code=?,updated_at=? "
                   "WHERE attempt_id=? AND status='intent'",
                   (outbox_state, code, now, row["attempt_id"]))
        current = db.execute("SELECT state,claim_token FROM tasks WHERE task_id=?",
                             (row["task_id"],)).fetchone()
        if (current is not None and current["state"] == TaskState.DISPATCHING.value
                and hmac.compare_digest(_sha256(current["claim_token"] or ""),
                                        row["claim_token_sha256"])):
            db.execute("UPDATE tasks SET state=?,error=?,lease_until=NULL,"
                       "claim_version=claim_version+1,updated_at=? WHERE task_id=?",
                       (task_state, f"app-server attempt requires manual reconciliation ({code})",
                        now, row["task_id"]))
        self._event(db, row["attempt_id"], f"attempt.{state}", code=code)
        self.outbox._event(db, row["attempt_id"], row["task_id"],
                           f"app_server.{state}", {"code": code})

    def recover_pending(self) -> int:
        """Explicitly quarantine incomplete attempts after restart; never retries."""
        changed = 0
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT * FROM orchestrator_app_server_attempts "
                              "WHERE status IN ('prepared','running_offline_fake') ORDER BY created_at")
            for row in rows.fetchall():
                messages = db.execute("SELECT status FROM orchestrator_app_server_messages "
                                      "WHERE attempt_id=?", (row["attempt_id"],)).fetchall()
                if not messages:
                    state, outbox_state, task_state, code = (
                        "not_sent_recovered", "offline_not_sent", TaskState.NEEDS_HUMAN.value,
                        "recovered_before_any_message_intent",
                    )
                elif row["terminal_seen"]:
                    state, outbox_state, task_state, code = (
                        "needs_human", "needs_human", TaskState.NEEDS_HUMAN.value,
                        "terminal_observed_without_durable_result",
                    )
                else:
                    state, outbox_state, task_state, code = (
                        "unknown_delivery", "unknown", TaskState.UNKNOWN_DELIVERY.value,
                        "process_lost_before_terminal_result",
                    )
                self._close_locked(db, row, state=state, outbox_state=outbox_state,
                                   task_state=task_state, code=code)
                changed += 1
        return changed

    def get(self, attempt_id: str) -> dict | None:
        with self.store._connect() as db:
            row = db.execute("""SELECT attempt_id,controller_id,worker_id,account_id,project_id,
                task_id,transport,package_sha256,claim_version,assignment_version,prompt_sha256,
                status,thread_id,turn_id,terminal_seen,created_at,updated_at
                FROM orchestrator_app_server_attempts WHERE attempt_id=?""", (attempt_id,)).fetchone()
            return dict(row) if row else None

    def messages(self, attempt_id: str) -> list[dict]:
        with self.store._connect() as db:
            return [dict(row) for row in db.execute("""SELECT message_seq,message_kind,request_id,
                method,status,created_at,updated_at FROM orchestrator_app_server_messages
                WHERE attempt_id=? ORDER BY message_seq""", (attempt_id,))]

    def events(self, attempt_id: str) -> list[dict]:
        with self.store._connect() as db:
            return [dict(row) for row in db.execute("""SELECT id,kind,message_seq,request_id,code,created_at
                FROM orchestrator_app_server_events WHERE attempt_id=? ORDER BY id""", (attempt_id,))]

    def reconcile(self, attempt_id: str) -> dict:
        """Read-only status/evidence summary. It does not update any state."""
        with self.store._connect() as db:
            row = db.execute("""SELECT d.status,d.thread_id,d.turn_id,d.terminal_seen,
                o.status AS outbox_status,t.state AS task_state
                FROM orchestrator_app_server_attempts d
                JOIN orchestrator_dispatch_attempts o ON o.attempt_id=d.attempt_id
                JOIN tasks t ON t.task_id=d.task_id WHERE d.attempt_id=?""",
                (attempt_id,)).fetchone()
            if row is None:
                raise ValueError("app-server attempt not found")
            pending = db.execute("SELECT COUNT(*) FROM orchestrator_app_server_messages "
                                 "WHERE attempt_id=? AND status IN ('intent','written','unknown')",
                                 (attempt_id,)).fetchone()[0]
            return {
                "attempt_id": attempt_id,
                "status": row["status"],
                "outbox_status": row["outbox_status"],
                "task_state": row["task_state"],
                "thread_id": row["thread_id"],
                "turn_id": row["turn_id"],
                "terminal_seen_unverified": bool(row["terminal_seen"]),
                "pending_or_uncertain_messages": pending,
                "automatic_retry_permitted": False,
                "finalization_permitted": False,
            }

    def record_operator_disposition(self, attempt_id: str, *, operator_ref: str,
                                    disposition: str, reason_code: str) -> bool:
        """Append one audit annotation; this cannot release or retry an attempt.

        ``operator_ref`` is caller supplied and is not authenticated by this
        offline ledger. It is attribution metadata, never authorization.
        """
        if (not _is_identifier(operator_ref) or disposition not in _DISPOSITIONS
                or reason_code not in _REASONS):
            raise ValueError("invalid operator disposition")
        now = time.time()
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            attempt = db.execute("SELECT status FROM orchestrator_app_server_attempts "
                                 "WHERE attempt_id=?", (attempt_id,)).fetchone()
            if attempt is None:
                raise ValueError("app-server attempt not found")
            old = db.execute("SELECT * FROM orchestrator_app_server_operator_dispositions "
                             "WHERE attempt_id=?", (attempt_id,)).fetchone()
            values = (_sha256(operator_ref), disposition, reason_code)
            if old is not None:
                if tuple(old[key] for key in (
                    "operator_ref_sha256", "disposition", "reason_code"
                )) != values:
                    raise ValueError("conflicting operator disposition already recorded")
                return False
            db.execute("INSERT INTO orchestrator_app_server_operator_dispositions "
                       "(attempt_id,operator_ref_sha256,disposition,reason_code,created_at) "
                       "VALUES (?,?,?,?,?)",
                       (attempt_id, *values, now))
            self._event(db, attempt_id, "operator.disposition", code=disposition)
            return True
