"""Windows-token-bound, one-time OFFLINE quarantine annotations.

This is an internal component for a future trusted controller process.
It never releases quarantines, starts transport, retries, or finalizes tasks.
A process sharing the controller SID can still tamper with unprotected memory
or storage; this module is not by itself a hostile same-user security boundary.
"""
from __future__ import annotations

import ctypes
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from ctypes import wintypes

from .app_server_delivery import AppServerDeliveryLedger

_SID = re.compile(r"S-1-\d+(?:-\d+)+\Z")
_QUARANTINED = frozenset({
    "unknown_delivery", "needs_human", "not_sent_recovered",
    "offline_not_sent", "transport_completed_unverified",
})
_COMPONENT = "windows-operator-quarantine-decisions"
_VERSION = 1


def current_process_token_sid() -> str:
    """Ask Windows for TokenUser via native APIs, never trust a caller label.

    The operating system, not whoami.exe or a command-line argument, supplies
    the identity of the current process. A future controller IPC service must
    instead impersonate each peer before performing this same token check.
    """
    if os.name != "nt":
        raise OSError("Windows token authentication is Windows-only")

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel.LocalFree.restype = wintypes.HLOCAL
    advapi.OpenProcessToken.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi.OpenProcessToken.restype = wintypes.BOOL
    advapi.GetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi.GetTokenInformation.restype = wintypes.BOOL
    advapi.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
    ]
    advapi.ConvertSidToStringSidW.restype = wintypes.BOOL

    class _SidAndAttributes(ctypes.Structure):
        _fields_ = [("sid", ctypes.c_void_p), ("attributes", wintypes.DWORD)]

    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        needed = wintypes.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))
        if ctypes.get_last_error() != 122 or needed.value < ctypes.sizeof(_SidAndAttributes):
            raise OSError("Windows TokenUser size query failed")
        data = ctypes.create_string_buffer(needed.value)
        if not advapi.GetTokenInformation(
            token, 1, data, needed.value, ctypes.byref(needed)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        user = ctypes.cast(data, ctypes.POINTER(_SidAndAttributes)).contents
        if not user.sid:
            raise OSError("Windows TokenUser SID was empty")
        value = ctypes.c_void_p()
        if not advapi.ConvertSidToStringSidW(user.sid, ctypes.byref(value)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            sid = ctypes.wstring_at(value.value)
        finally:
            kernel.LocalFree(value.value)
        if not _SID.fullmatch(sid):
            raise OSError("Windows returned malformed TokenUser SID")
        return sid
    finally:
        kernel.CloseHandle(token)


class WindowsOperatorQuarantineGate:
    """Authenticate local process SID; permit ONE inert, durable decision.

    The allowlist MUST be passed exclusively by a trusted, ACL-isolated
    controller bootstrap. There is deliberately NO user-writable CLI option.
    Independent delivery attestation is not implemented: only an unresolved
    decision can be persisted, and ALL resulting permissions remain false.
    """

    def __init__(
        self, ledger: AppServerDeliveryLedger, *, trusted_operator_sids: frozenset[str]
    ):
        if type(ledger) is not AppServerDeliveryLedger:
            raise TypeError("requires canonical AppServerDeliveryLedger")
        if (type(trusted_operator_sids) is not frozenset
                or not trusted_operator_sids
                or any(type(sid) is not str or not _SID.fullmatch(sid)
                       for sid in trusted_operator_sids)):
            raise ValueError("trusted Windows operator SID allowlist is required")
        self._store = ledger.store
        self._operator_sids = trusted_operator_sids
        self._migrate()

    def _authenticated_sid(self) -> str:
        sid = current_process_token_sid()
        if sid not in self._operator_sids:
            raise PermissionError("current Windows token is not an approved operator")
        return sid

    @staticmethod
    def _attempt(db, attempt_id: str):
        if type(attempt_id) is not str or not 1 <= len(attempt_id) <= 128:
            raise ValueError("invalid attempt ID")
        row = db.execute(
            """SELECT a.attempt_id, a.status, a.updated_at, a.task_id,
                      a.claim_version AS ledger_claim_version,
                      a.assignment_version AS ledger_assignment_version,
                      a.prompt_sha256 AS ledger_prompt_sha256,
                      d.status AS outbox_status, d.updated_at AS outbox_updated_at,
                      d.claim_token_hash AS outbox_claim_token_hash,
                      t.state AS task_state, t.updated_at AS task_updated_at,
                      t.claim_version AS task_claim_version,
                      t.prompt_sha AS task_prompt_sha
               FROM orchestrator_app_server_attempts a
               JOIN orchestrator_dispatch_attempts d ON d.attempt_id=a.attempt_id
               JOIN tasks t ON t.task_id=a.task_id
               WHERE a.attempt_id=?""", (attempt_id,)
        ).fetchone()
        if row is None or row["status"] not in _QUARANTINED:
            raise ValueError("attempt is not in a reviewable offline state")
        if (row["task_state"] not in {"unknown_delivery", "needs_human"}
                or row["outbox_status"] not in {
                    "unknown", "needs_human", "offline_not_sent",
                    "offline_simulated_unverified",
                }):
            raise ValueError("attempt is no longer in a conservative review state")
        return row

    @staticmethod
    def _bound_nonce_digest(nonce: str, row) -> str:
        """HMAC one-time nonce to the complete canonical joined state fence.

        Previously issued nonce-only challenge hashes intentionally fail;
        the operator must explicitly issue a fresh challenge.
        """
        fields = (
            "attempt_id", "task_id", "status", "updated_at",
            "ledger_claim_version", "ledger_assignment_version",
            "ledger_prompt_sha256", "outbox_status", "outbox_updated_at",
            "outbox_claim_token_hash", "task_state", "task_updated_at",
            "task_claim_version", "task_prompt_sha",
        )
        payload = json.dumps(
            [row[field] for field in fields], ensure_ascii=True, separators=(",", ":"),
        ).encode("ascii")
        return hmac.new(nonce.encode("ascii"), payload, hashlib.sha256).hexdigest()

    def _migrate(self) -> None:
        names = {"orchestrator_operator_challenges", "orchestrator_operator_decisions"}
        with self._store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT version FROM orchestrator_schema_versions WHERE component=?",
                (_COMPONENT,),
            ).fetchone()
            found = {r[0] for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ) if r[0] in names}
            if row is not None:
                if row["version"] != _VERSION or found != names:
                    raise ValueError("untrusted operator decision schema version")
                expected = {
                    "orchestrator_operator_challenges": {
                        "attempt_id", "version", "nonce_sha256", "windows_sid",
                        "disposition", "attempt_updated_at", "expires_at", "used",
                    },
                    "orchestrator_operator_decisions": {
                        "attempt_id", "version", "nonce_sha256", "windows_sid",
                        "disposition", "attempt_status", "outbox_status",
                        "task_state", "created_at",
                    },
                }
                for table, required in expected.items():
                    cols = {c[1] for c in db.execute(f"PRAGMA table_info({table})")}
                    if not required.issubset(cols):
                        raise ValueError("incomplete operator decision layout")
                triggers = {r[0] for r in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger'"
                )}
                if not {"operator_decisions_no_update", "operator_decisions_no_delete"}.issubset(triggers):
                    raise ValueError("operator audit triggers missing")
                return
            if found:
                raise ValueError("unversioned operator decision tables are untrusted")
            db.execute("""CREATE TABLE orchestrator_operator_challenges (
                attempt_id TEXT PRIMARY KEY REFERENCES orchestrator_app_server_attempts(attempt_id),
                version INTEGER NOT NULL CHECK(version > 0),
                nonce_sha256 TEXT NOT NULL CHECK(length(nonce_sha256) = 64),
                windows_sid TEXT NOT NULL,
                disposition TEXT NOT NULL CHECK(disposition='delivery_unresolved'),
                attempt_updated_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                used INTEGER NOT NULL DEFAULT 0 CHECK(used IN (0,1))
            )""")
            db.execute("""CREATE TABLE orchestrator_operator_decisions (
                attempt_id TEXT PRIMARY KEY REFERENCES orchestrator_app_server_attempts(attempt_id),
                version INTEGER NOT NULL CHECK(version > 0),
                nonce_sha256 TEXT NOT NULL CHECK(length(nonce_sha256) = 64),
                windows_sid TEXT NOT NULL,
                disposition TEXT NOT NULL CHECK(disposition='delivery_unresolved'),
                attempt_status TEXT NOT NULL,
                outbox_status TEXT NOT NULL,
                task_state TEXT NOT NULL,
                created_at REAL NOT NULL
            )""")
            db.execute("""CREATE TRIGGER operator_decisions_no_update
                BEFORE UPDATE ON orchestrator_operator_decisions
                BEGIN SELECT RAISE(ABORT,'authenticated audit is append-only'); END""")
            db.execute("""CREATE TRIGGER operator_decisions_no_delete
                BEFORE DELETE ON orchestrator_operator_decisions
                BEGIN SELECT RAISE(ABORT,'authenticated audit is append-only'); END""")
            db.execute(
                "INSERT INTO orchestrator_schema_versions(component,version,updated_at) "
                "VALUES(?,?,?)", (_COMPONENT, _VERSION, time.time()),
            )

    def issue_challenge(self, attempt_id: str, *, disposition: str, ttl: int = 120) -> dict:
        """Replace an outstanding nonce; all previous versions are invalid."""
        sid = self._authenticated_sid()
        if disposition != "delivery_unresolved":
            raise PermissionError("independent evidence verifier not integrated; retain quarantine")
        if type(ttl) is not int or not 1 <= ttl <= 300:
            raise ValueError("challenge lifetime must be 1..300 seconds")
        nonce = secrets.token_urlsafe(32)
        with self._store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._attempt(db, attempt_id)
            digest = self._bound_nonce_digest(nonce, row)
            if db.execute(
                "SELECT 1 FROM orchestrator_operator_decisions WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone():
                raise ValueError("operator decision already committed")
            prior = db.execute(
                "SELECT version FROM orchestrator_operator_challenges WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            version = prior["version"] + 1 if prior else 1
            deadline = time.time() + ttl
            db.execute(
                """INSERT INTO orchestrator_operator_challenges
                   (attempt_id,version,nonce_sha256,windows_sid,disposition,
                    attempt_updated_at,expires_at,used)
                   VALUES (?,?,?,?,?,?,?,0)
                   ON CONFLICT(attempt_id) DO UPDATE SET
                     version=excluded.version,nonce_sha256=excluded.nonce_sha256,
                     windows_sid=excluded.windows_sid,disposition=excluded.disposition,
                     attempt_updated_at=excluded.attempt_updated_at,
                     expires_at=excluded.expires_at,used=0""",
                (attempt_id, version, digest, sid, disposition, row["updated_at"], deadline),
            )
        return {"attempt_id": attempt_id, "nonce": nonce, "version": version,
                "expires_at": deadline, "operator_authenticated": True,
                "live_send_permitted": False, "resolution_permitted": False}

    def record_unresolved(self, attempt_id: str, *, nonce: str, version: int) -> dict:
        """Consume a nonce and insert ONE audit row with an atomic SQLite CAS."""
        sid = self._authenticated_sid()
        if type(version) is not int or version < 1:
            raise ValueError("invalid decision version")
        if type(nonce) is not str or not 20 <= len(nonce) <= 128 or not nonce.isascii():
            raise ValueError("invalid challenge nonce")
        with self._store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._attempt(db, attempt_id)
            digest = self._bound_nonce_digest(nonce, row)
            if db.execute(
                "SELECT 1 FROM orchestrator_operator_decisions WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone():
                raise ValueError("operator decision already committed")
            challenge = db.execute(
                """SELECT version,nonce_sha256,windows_sid,attempt_updated_at,
                          expires_at,used FROM orchestrator_operator_challenges
                   WHERE attempt_id=?""", (attempt_id,),
            ).fetchone()
            if (challenge is None or challenge["used"] != 0
                    or challenge["version"] != version
                    or not hmac.compare_digest(challenge["nonce_sha256"], digest)
                    or challenge["windows_sid"] != sid
                    or challenge["expires_at"] <= time.time()
                    or challenge["attempt_updated_at"] != row["updated_at"]):
                raise PermissionError("challenge expired, stale, mismatched or consumed")
            updated = db.execute(
                """UPDATE orchestrator_operator_challenges SET used=1
                   WHERE attempt_id=? AND version=? AND nonce_sha256=?
                     AND windows_sid=? AND used=0""",
                (attempt_id, version, digest, sid),
            ).rowcount
            if updated != 1:
                raise PermissionError("operator decision compare-and-swap failed")
            db.execute(
                """INSERT INTO orchestrator_operator_decisions
                   (attempt_id,version,nonce_sha256,windows_sid,disposition,
                    attempt_status,outbox_status,task_state,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (attempt_id, version, digest, sid, "delivery_unresolved",
                 row["status"], row["outbox_status"], row["task_state"], time.time()),
            )
        return {
            "attempt_id": attempt_id, "disposition": "delivery_unresolved",
            "operator_authenticated": True, "audit_recorded": True,
            "independent_delivery_evidence_verified": False,
            "resolution_permitted": False, "new_attempt_permitted": False,
            "automatic_retry_permitted": False, "live_send_permitted": False,
            "finalization_permitted": False,
        }
