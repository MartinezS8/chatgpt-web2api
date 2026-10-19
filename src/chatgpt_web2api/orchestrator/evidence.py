"""PR-04 SHA-bound evidence checks with mandatory offline-only assurance.

A caller-provided mapping is NOT provider evidence. In this PR probes are
fake/test probes only; real GitHub/Supabase authentication is a separate gate.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Protocol

from .store import Store

_SHA = re.compile(r"^[0-9a-f]{40}$")


class GitHubEvidenceProbe(Protocol):
    def inspect_pr(self, repository_id: str, pr_number: int) -> dict: ...
    def inspect_run(self, repository_id: str, run_id: int) -> dict: ...


def _digest(x: dict) -> str:
    return hashlib.sha256(json.dumps(x, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class EvidenceLedger:
    def __init__(self, store: Store):
        self.store = store
        with store._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS orchestrator_evidence (
                task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),
                repository_id TEXT NOT NULL, pr_number INTEGER NOT NULL,
                head_sha TEXT NOT NULL, run_id INTEGER NOT NULL,
                digest TEXT NOT NULL, assurance TEXT NOT NULL,
                recorded_at REAL NOT NULL
            )""")

    def inspect_mock(self, *, task_id: str, repository_id: str, pr_number: int,
                     expected_head_sha: str, run_id: int, probe: GitHubEvidenceProbe) -> dict:
        """Verify simulated repository snapshots, never produce live attestation."""
        if (not isinstance(repository_id, str) or not repository_id.isdecimal()
                or int(repository_id) < 1 or not isinstance(pr_number, int) or pr_number < 1
                or not isinstance(run_id, int) or run_id < 1 or not _SHA.fullmatch(expected_head_sha)):
            raise ValueError("malformed SHA-bound evidence request")
        task = self.store.get(task_id)
        if task is None or task["role"] != "implement":
            raise ValueError("evidence must reference an implementation task")
        pr = probe.inspect_pr(repository_id, pr_number)
        run = probe.inspect_run(repository_id, run_id)
        if (pr.get("repository_id") != repository_id or pr.get("number") != pr_number
                or pr.get("head_sha") != expected_head_sha or pr.get("state") != "open"):
            raise ValueError("PR head changed or repository/PR identity mismatch")
        if (run.get("repository_id") != repository_id or run.get("head_sha") != expected_head_sha
                or run.get("conclusion") != "success" or run.get("id") != run_id):
            raise ValueError("CI is missing, stale, or not green for exact head SHA")
        payload = {"task_id": task_id, "repository_id": repository_id,
                   "pr_number": pr_number, "head_sha": expected_head_sha,
                   "run_id": run_id, "assurance": "offline_mock_only"}
        digest = _digest(payload)
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT digest FROM orchestrator_evidence WHERE task_id=?",
                             (task_id,)).fetchone()
            if old:
                if old["digest"] != digest:
                    raise ValueError("evidence is sealed for a different head/run")
                return {**payload, "digest": digest, "new": False}
            db.execute("""INSERT INTO orchestrator_evidence VALUES(?,?,?,?,?,?,?,?)""",
                       (task_id, repository_id, pr_number, expected_head_sha,
                        run_id, digest, "offline_mock_only", time.time()))
        return {**payload, "digest": digest, "new": True}

    def get(self, task_id: str) -> dict | None:
        with self.store._connect() as db:
            row = db.execute("SELECT * FROM orchestrator_evidence WHERE task_id=?", (task_id,)).fetchone()
            return dict(row) if row else None

    def is_production_proof(self, task_id: str) -> bool:
        """No adapter in this PR can ever promote mock evidence to production."""
        return False

