"""Bind read-only GitHub PR/CI observations to one completed task attempt.

This is an audit-only bridge, **not** an authorization to change a task state,
finish an implementation, release a resource lock, approve/merge a PR or send
anything to ChatGPT. The trusted finalizer remains intentionally absent.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from typing import Callable

from .github_readonly_evidence import GitHubReadOnlyEvidence
from .store import Store, TaskState


def _digest(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class ProviderEvidenceLedger:
    """Immutable, task-bound observations; never promote an untrusted approval.

    The GitHub reader is provided by trusted controller configuration. An
    injected fake reader is useful for deterministic tests, but is NOT an
    external attestation. Even real HTTPS responses prove only a read-only
    provider observation, not an independent human review or authority to act.
    """

    def __init__(self, store: Store, gate: GitHubReadOnlyEvidence, *,
                 now: Callable[[], float] = time.time, max_age_seconds: int = 120):
        if not isinstance(store, Store) or not isinstance(gate, GitHubReadOnlyEvidence):
            raise TypeError("Store and configured GitHubReadOnlyEvidence required")
        if type(max_age_seconds) is not int or not 5 <= max_age_seconds <= 600:
            raise ValueError("invalid provider observation freshness window")
        self.store, self.gate, self.now = store, gate, now
        self.max_age_seconds = max_age_seconds
        with store._connect() as db:
            # Serialize additive schema upgrades across separate processes.
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS orchestrator_provider_observations (
                task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),
                attempt_id TEXT NOT NULL UNIQUE,
                repository_id INTEGER NOT NULL, pr_number INTEGER NOT NULL,
                head_sha TEXT NOT NULL, run_id INTEGER NOT NULL,
                workflow_id INTEGER NOT NULL, run_attempt INTEGER NOT NULL,
                package_sha256 TEXT NOT NULL, result_sha256 TEXT NOT NULL,
                claim_version INTEGER NOT NULL, digest TEXT NOT NULL,
                assurance TEXT NOT NULL CHECK(assurance='provider_read_only_unreviewed'),
                observed_at REAL NOT NULL,
                workflow_blob_sha TEXT
            )""")
            columns = {row["name"] for row in db.execute(
                "PRAGMA table_info(orchestrator_provider_observations)")}
            if "workflow_blob_sha" not in columns:
                db.execute("""ALTER TABLE orchestrator_provider_observations
                    ADD COLUMN workflow_blob_sha TEXT""")

    def _binding(self, db, task_id: str, attempt_id: str) -> dict:
        task = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if (task is None or task["role"] != "implement" or
                task["state"] != TaskState.RESULT_RECEIVED.value or task["slot"] is None):
            raise ValueError("provider observation requires a received, locked implementation")
        scopes = json.loads(task["write_scopes"])
        canonical = f"github:repo/{self.gate.repository_id}"
        if not isinstance(scopes, list) or not any(
                isinstance(scope, str) and
                (scope == canonical or scope.startswith(canonical + "/"))
                for scope in scopes):
            raise ValueError("task has no matching canonical GitHub repository lock")
        attempt = db.execute("""SELECT * FROM orchestrator_dispatch_attempts
            WHERE task_id=? AND attempt_id=?""", (task_id, attempt_id)).fetchone()
        if (attempt is None or attempt["status"] != "completed" or
                not attempt["result_ref"] or attempt["result_ref"] != task["evidence_ref"] or
                not task["claim_token"] or
                attempt["claim_token_hash"] != hashlib.sha256(task["claim_token"].encode()).hexdigest()):
            raise ValueError("result does not belong to this completed fenced dispatch")
        package = db.execute("""SELECT package_sha256 FROM orchestrator_task_packages
            WHERE task_id=?""", (task_id,)).fetchone()
        if package is None or package["package_sha256"] != attempt["package_sha256"]:
            raise ValueError("dispatch package identity mismatch")
        return {"task_id": task_id, "attempt_id": attempt_id,
                "package_sha256": package["package_sha256"],
                "result_sha256": hashlib.sha256(attempt["result_ref"].encode()).hexdigest(),
                "claim_version": task["claim_version"]}

    def inspect_and_record(self, *, task_id: str, attempt_id: str,
                           pr_number: int, expected_head_sha: str,
                           run_id: int) -> dict:
        if not isinstance(task_id, str) or not task_id or len(task_id) > 128:
            raise ValueError("invalid task identity")
        if not isinstance(attempt_id, str) or not attempt_id or len(attempt_id) > 128:
            raise ValueError("invalid dispatch attempt identity")
        # Check local prerequisites before any remote GET. Never hold a SQLite
        # write transaction across potentially slow or unavailable network IO.
        with self.store._connect() as db:
            before = self._binding(db, task_id, attempt_id)

        provider = self.gate.inspect(pr_number=pr_number,
                                     expected_head_sha=expected_head_sha,
                                     run_id=run_id)
        now = self.now()
        if (not math.isfinite(now) or not math.isfinite(provider.verified_at) or
                provider.verified_at > now + 5 or
                now - provider.verified_at > self.max_age_seconds):
            raise ValueError("GitHub observation is stale or has invalid time")
        if (provider.assurance != "provider_read_only_unreviewed" or
                provider.production_finalization_permitted or
                provider.live_send_permitted or
                provider.repository_id != self.gate.repository_id):
            raise ValueError("provider observation cannot be used as permission")

        # This identity is provided by controller policy and checked source
        # bytes, not by a worker-authored report.
        pin = self.gate.workflow_source_pin
        workflow_blob_sha = provider.workflow_blob_sha
        if pin is not None:
            if workflow_blob_sha != pin.trusted_blob_sha:
                raise ValueError("trusted workflow source pin is missing or mismatched")
        elif workflow_blob_sha is not None:
            raise ValueError("unpinned CI gate cannot report verified workflow source")
        data = {**before, "repository_id": provider.repository_id,
                "pr_number": provider.pr_number,
                "head_sha": provider.head_sha,
                "run_id": provider.run_id, "workflow_id": provider.workflow_id,
                "run_attempt": provider.run_attempt,
                "assurance": "provider_read_only_unreviewed"}
        # Preserve legacy unpinned V23 digests; bind any verified source to
        # the immutable task/attempt CI receipt.
        if workflow_blob_sha is not None:
            data["workflow_blob_sha"] = workflow_blob_sha
        digest = _digest(data)
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            # Ensure a concurrent task transition, claim rotation, package
            # replacement or delivery change cannot seal a stale network read.
            after = self._binding(db, task_id, attempt_id)
            if after != before:
                raise ValueError("task or dispatch changed during provider verification")
            old = db.execute("""SELECT * FROM orchestrator_provider_observations
                WHERE task_id=?""", (task_id,)).fetchone()
            if old is not None:
                if (old["digest"] != digest or old["attempt_id"] != attempt_id
                        or old["workflow_blob_sha"] != workflow_blob_sha):
                    raise ValueError("provider evidence already sealed for different inputs")
                recorded_at, created = old["observed_at"], False
            else:
                recorded_at, created = now, True
                db.execute("""INSERT INTO orchestrator_provider_observations
                    (task_id,attempt_id,repository_id,pr_number,head_sha,run_id,
                     workflow_id,run_attempt,package_sha256,result_sha256,
                     claim_version,digest,assurance,observed_at,workflow_blob_sha)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (task_id,attempt_id,provider.repository_id,provider.pr_number,
                     provider.head_sha,provider.run_id,provider.workflow_id,
                     provider.run_attempt,before["package_sha256"],
                     before["result_sha256"],before["claim_version"],digest,
                     "provider_read_only_unreviewed",recorded_at,workflow_blob_sha))
                self.store._event(db,task_id,"evidence.provider_observed",
                                  "read_only; no release/approval")
        return {"task_id": task_id, "attempt_id": attempt_id,
                "repository_id": provider.repository_id, "pr_number": pr_number,
                "head_sha": provider.head_sha, "run_id": run_id,
                "workflow_id": provider.workflow_id,
                "workflow_blob_sha": workflow_blob_sha, "digest": digest,
                "observed_at": recorded_at, "new": created,
                "assurance": "provider_read_only_unreviewed",
                "production_finalization_permitted": False,
                "live_send_permitted": False}

    def get(self, task_id: str) -> dict | None:
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("task ID required")
        with self.store._connect() as db:
            item = db.execute("""SELECT task_id,attempt_id,repository_id,pr_number,
                head_sha,run_id,workflow_id,run_attempt,package_sha256,
                result_sha256,claim_version,digest,assurance,observed_at,
                workflow_blob_sha FROM orchestrator_provider_observations WHERE task_id=?""",
                (task_id,)).fetchone()
            if item is None:
                return None
            return {**dict(item), "production_finalization_permitted": False,
                    "live_send_permitted": False}

    @staticmethod
    def production_finalization_permitted(*_, **__) -> bool:
        """A read-only snapshot can never be a signed approval or consent."""
        return False
