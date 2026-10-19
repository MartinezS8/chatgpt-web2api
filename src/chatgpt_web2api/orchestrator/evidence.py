"""Provider-backed immutable GitHub evidence gate, with an injectable read-only client.

Fake providers are for offline tests ONLY; production implementations must query
an authenticated authoritative GitHub installation and enforce repo permissions.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Protocol

from .store import Store, TaskState

_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class CommitProof:
    repository_id: int
    sha: str
    exists: bool


@dataclass(frozen=True)
class PullProof:
    repository_id: int
    number: int
    head_sha: str
    state: str


@dataclass(frozen=True)
class CheckProof:
    repository_id: int
    head_sha: str
    name: str
    status: str
    conclusion: str


class TrustedGitHubReader(Protocol):
    def commit(self, repository_id: int, sha: str) -> CommitProof: ...
    def pull(self, repository_id: int, number: int) -> PullProof: ...
    def checks(self, repository_id: int, head_sha: str) -> list[CheckProof]: ...


@dataclass(frozen=True)
class EvidenceSpec:
    repository_id: int
    pr_number: int
    commit_sha: str
    required_checks: tuple[str, ...] = ()

    @property
    def result_ref(self) -> str:
        return f"github:{self.repository_id}/pull/{self.pr_number}@{self.commit_sha}"

    def validate(self) -> None:
        if self.repository_id <= 0 or self.pr_number <= 0 or not _SHA.fullmatch(self.commit_sha):
            raise ValueError("invalid immutable GitHub evidence identity")
        if not self.required_checks or len(set(self.required_checks)) != len(self.required_checks):
            raise ValueError("at least one unique CI check required")
        if any(not n or len(n) > 128 for n in self.required_checks):
            raise ValueError("invalid required check")


class EvidenceGate:
    def __init__(self, store: Store, reader: TrustedGitHubReader):
        self.store, self.reader = store, reader
        with store._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS orchestrator_verified_evidence (
                task_id TEXT PRIMARY KEY, repository_id INTEGER NOT NULL,
                pr_number INTEGER NOT NULL, head_sha TEXT NOT NULL,
                required_checks TEXT NOT NULL, verified_at REAL NOT NULL)""")

    def verify(self, task_id: str, spec: EvidenceSpec, *, claim_token: str) -> bool:
        spec.validate()
        # Verify first with trusted read-only provider, then lock and compare
        # all task invariants. The remote PR may move after this read; final
        # release MUST recheck the current head and check suite separately.
        if self.reader.commit(spec.repository_id, spec.commit_sha) != CommitProof(
                spec.repository_id, spec.commit_sha, True):
            raise ValueError("GitHub commit is not verified")
        pr = self.reader.pull(spec.repository_id, spec.pr_number)
        if pr != PullProof(spec.repository_id, spec.pr_number, spec.commit_sha, "open"):
            raise ValueError("PR head differs, repository differs, or PR is not open")
        checks = self.reader.checks(spec.repository_id, spec.commit_sha)
        if not self._checks_are_green(spec, checks):
            raise ValueError("required CI checks are not confirmed successful")
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if task is None or task["state"] != TaskState.RESULT_RECEIVED.value:
                raise ValueError("task not awaiting evidence verification")
            if task["claim_token"] != claim_token or task["evidence_ref"] != spec.result_ref:
                raise ValueError("claim or result reference mismatch")
            # The proof must match a canonical PR-02B repository lock identity,
            # not merely a self-asserted GitHub result URL.
            declared = json.loads(task["write_scopes"])
            repo_scope = f"github:repo/{spec.repository_id}"
            if task["role"] != "implement" or not any(
                    item == repo_scope or item.startswith(repo_scope + "/")
                    for item in declared):
                raise ValueError("GitHub proof repository is not in declared write scope")
            existing = db.execute("SELECT * FROM orchestrator_verified_evidence WHERE task_id=?",
                                  (task_id,)).fetchone()
            if existing is not None:
                raise ValueError("evidence already exists; inspect manually")
            cur = db.execute("UPDATE tasks SET state='verified',claim_version=claim_version+1,updated_at=? "
                             "WHERE task_id=? AND state='result_received' AND claim_token=? AND claim_version=?",
                             (time.time(),task_id,claim_token,task["claim_version"]))
            if cur.rowcount != 1:
                raise ValueError("stale evidence version")
            db.execute("INSERT INTO orchestrator_verified_evidence VALUES (?,?,?,?,?,?)",
                       (task_id,spec.repository_id,spec.pr_number,spec.commit_sha,
                        json.dumps(sorted(spec.required_checks)),time.time()))
            self.store._event(db,task_id,"evidence.verified",spec.commit_sha)
        return True

    @staticmethod
    def _checks_are_green(spec: EvidenceSpec, checks: list[CheckProof]) -> bool:
        # A provider adapter must present one current run per check name.
        # Multiple versions of a required check (even one historical success)
        # are ambiguous: fail closed rather than cherry-pick the green run.
        return all(
            len(matched := [check for check in checks if check.name == required]) == 1
            and matched[0] == CheckProof(spec.repository_id, spec.commit_sha,
                                         required, "completed", "success")
            for required in spec.required_checks
        )

    def is_current(self, task_id: str) -> bool:
        """For release gates re-read provider; never trust a historical green run."""
        with self.store._connect() as db:
            row=db.execute("SELECT * FROM orchestrator_verified_evidence WHERE task_id=?",
                           (task_id,)).fetchone()
        if row is None:
            return False
        spec=EvidenceSpec(row["repository_id"],row["pr_number"],row["head_sha"],
                          tuple(json.loads(row["required_checks"])))
        try:
            pr=self.reader.pull(spec.repository_id,spec.pr_number)
            if pr != PullProof(spec.repository_id,spec.pr_number,spec.commit_sha,"open"):
                return False
            checks=self.reader.checks(spec.repository_id,spec.commit_sha)
            return self._checks_are_green(spec, checks)
        except Exception:
            return False
