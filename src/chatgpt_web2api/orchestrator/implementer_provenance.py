"""Read-only, SHA-bound GitHub commit ↔ mock-worker correlation.

Does NOT prove a remote worker performed the code changes or authorize a merge,
state transition, message send or release of any write scope.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from .github_readonly_reviews import GitHubReviewsHTTP
from .store import Store
from .task_review_evidence import TaskReviewEvidenceLedger

_SHA = re.compile(r"[0-9a-f]{40}\Z")


def _digest(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class CommitReader(Protocol):
    def __call__(self, path: str) -> dict: ...


@dataclass(frozen=True)
class CommitObservation:
    repository_id: int
    pr_number: int
    head_sha: str
    author_user_id: int
    committer_user_id: int
    observed_at: float
    assurance: str = "signed_commit_account_observed_unattributed"
    production_finalization_permitted: bool = False
    live_send_permitted: bool = False


class GitHubSignedCommitReader:
    """Check SHA, same-repo PR head, linked GitHub actors and verified signature.

    GitHub's `author` and `committer` identities and verification describe
    *GitHub commit metadata*, not proof that a particular web-agent created it.
    """

    def __init__(self, *, owner: str, repo: str, repository_id: int,
                 reader: CommitReader | None = None,
                 now: Callable[[], float] = time.time):
        if (not isinstance(owner, str) or not isinstance(repo, str)
                or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}", owner)
                or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}", repo)
                or owner in (".", "..") or repo in (".", "..")
                or type(repository_id) is not int or repository_id <= 0):
            raise ValueError("trusted GitHub repository identity required")
        self.owner, self.repo, self.repository_id = owner, repo, repository_id
        self.reader = reader if reader is not None else GitHubReviewsHTTP()
        self.now = now
        self._base = f"/repos/{owner}/{repo}"

    def _check_pr(self, pr: dict, number: int, head: str) -> None:
        if (not isinstance(pr, dict) or pr.get("number") != number
                or pr.get("state") != "open" or pr.get("merged") is not False
                or not isinstance(pr.get("base"), dict)
                or not isinstance(pr["base"].get("repo"), dict)
                or pr["base"]["repo"].get("id") != self.repository_id
                or not isinstance(pr.get("head"), dict)
                or pr["head"].get("sha") != head
                or not isinstance(pr["head"].get("repo"), dict)
                or pr["head"]["repo"].get("id") != self.repository_id):
            raise ValueError("PR head changed, is forked, or has different repository")

    def inspect(self, *, pr_number: int, expected_head_sha: str,
                expected_user_id: int) -> CommitObservation:
        if (type(pr_number) is not int or pr_number < 1
                or not isinstance(expected_head_sha, str) or not _SHA.fullmatch(expected_head_sha)
                or type(expected_user_id) is not int or expected_user_id < 1):
            raise ValueError("invalid commit attribution query")
        repo = self.reader(self._base)
        if (not isinstance(repo, dict) or type(repo.get("id")) is not int
                or repo["id"] != self.repository_id
                or str(repo.get("full_name", "")).casefold()
                != f"{self.owner}/{self.repo}".casefold()):
            raise ValueError("repository identity mismatch")
        pr_path = f"{self._base}/pulls/{pr_number}"
        self._check_pr(self.reader(pr_path), pr_number, expected_head_sha)
        commit = self.reader(f"{self._base}/commits/{expected_head_sha}")
        if not isinstance(commit, dict) or commit.get("sha") != expected_head_sha:
            raise ValueError("commit SHA mismatch")
        author, committer = commit.get("author"), commit.get("committer")
        git_commit = commit.get("commit")
        verification = git_commit.get("verification") if isinstance(git_commit, dict) else None
        if (not isinstance(author, dict) or not isinstance(committer, dict)
                or type(author.get("id")) is not int
                or type(committer.get("id")) is not int
                or author["id"] != expected_user_id
                or committer["id"] != expected_user_id
                or not isinstance(verification, dict)
                or verification.get("verified") is not True
                or verification.get("reason") != "valid"):
            raise ValueError("signed GitHub commit identity is unverified or mismatched")
        self._check_pr(self.reader(pr_path), pr_number, expected_head_sha)
        observed = self.now()
        if not isinstance(observed, (int, float)) or not math.isfinite(observed):
            raise ValueError("invalid observation time")
        return CommitObservation(self.repository_id, pr_number, expected_head_sha,
                                 author["id"], committer["id"], float(observed))


class ImplementerProvenanceLedger:
    """Bind GitHub commit metadata to task + local active mock worker assignment.

    This is intentionally NOT provider-authenticated worker identity. Real
    transports must obtain a separately authenticated worker/session binding.
    """

    def __init__(self, store: Store, review: TaskReviewEvidenceLedger,
                 commit: GitHubSignedCommitReader,
                 *, trusted_worker_user_ids: Mapping[str, int],
                 now: Callable[[], float] = time.time,
                 max_age_seconds: int = 120):
        if (not isinstance(store, Store) or not isinstance(review, TaskReviewEvidenceLedger)
                or review.store is not store or not isinstance(commit, GitHubSignedCommitReader)
                or commit.repository_id != review.reviewer.repository_id):
            raise ValueError("matching task, review, commit and repository authorities required")
        if (not isinstance(trusted_worker_user_ids, Mapping)
                or not trusted_worker_user_ids or any(
                    not isinstance(k, str) or not k or len(k) > 128
                    or type(v) is not int or v < 1
                    for k, v in trusted_worker_user_ids.items())):
            raise ValueError("trusted worker to GitHub ID policy required")
        if type(max_age_seconds) is not int or not 5 <= max_age_seconds <= 600:
            raise ValueError("invalid freshness policy")
        self.store, self.review, self.commit = store, review, commit
        self.policy = dict(trusted_worker_user_ids)
        self.now, self.max_age_seconds = now, max_age_seconds
        with store._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS orchestrator_implementer_provenance (
                task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),
                attempt_id TEXT NOT NULL UNIQUE, worker_id TEXT NOT NULL,
                github_user_id INTEGER NOT NULL, repository_id INTEGER NOT NULL,
                pr_number INTEGER NOT NULL, head_sha TEXT NOT NULL,
                package_sha256 TEXT NOT NULL, claim_version INTEGER NOT NULL,
                review_digest TEXT NOT NULL, digest TEXT NOT NULL,
                observed_at REAL NOT NULL,
                assurance TEXT NOT NULL CHECK(assurance='signed_commit_local_mock_worker_correlation')
            )""")

    def _snapshot(self, db, task_id: str, attempt_id: str, timestamp: float) -> dict:
        bound = self.review._snapshot_locked(db, task_id, attempt_id, timestamp)
        review = db.execute("""SELECT * FROM orchestrator_provider_review_observations
            WHERE task_id=? AND attempt_id=?""", (task_id, attempt_id)).fetchone()
        if review is None or review["assurance"] != "provider_read_only_review_unfinalized":
            raise ValueError("existing task-bound read-only review required")
        review = dict(review)
        expected_review_digest = _digest({
            **{k: v for k, v in bound.items() if k != "ci_observed_at"},
            "trusted_implementer_user_id": review["trusted_implementer_user_id"],
            "reviewer_ids": json.loads(review["reviewer_ids_json"]),
            "review_ids": json.loads(review["review_ids_json"]),
            "assurance": review["assurance"]})
        if (review["digest"] != expected_review_digest
                or review["ci_digest"] != bound["ci_digest"]
                or review["head_sha"] != bound["head_sha"]
                or review["repository_id"] != bound["repository_id"]
                or review["claim_version"] != bound["claim_version"]
                or review["package_sha256"] != bound["package_sha256"]
                or not (math.isfinite(review["observed_at"])
                        and -5 <= timestamp-review["observed_at"] <= self.max_age_seconds)):
            raise ValueError("task review receipt corrupted, stale or mismatched")
        assignment = db.execute("""SELECT a.worker_id,a.claim_version,a.state,
            w.enabled,w.role,w.transport,w.project_id AS worker_project,w.account_id,
            w.session_key,t.project_id AS task_project
            FROM orchestrator_worker_assignments a
            JOIN orchestrator_workers w ON w.worker_id=a.worker_id
            JOIN tasks t ON t.task_id=a.task_id
            WHERE a.task_id=?""", (task_id,)).fetchone()
        if (not assignment or assignment["state"] != "active"
                or not 1 <= assignment["claim_version"] <= bound["claim_version"]
                or assignment["enabled"] != 1
                or assignment["role"] != "implement"
                or assignment["transport"] != "mock"
                or not assignment["session_key"].startswith("fake:")
                or assignment["worker_project"] != assignment["task_project"]):
            raise ValueError("active matching mock-worker claim is required")
        worker_id = assignment["worker_id"]
        user_id = self.policy.get(worker_id)
        if user_id is None or user_id != review["trusted_implementer_user_id"]:
            raise ValueError("trusted worker policy conflicts with review implementer ID")
        return {**bound, "review_digest": review["digest"],
                "worker_id": worker_id, "github_user_id": user_id,
                "account_id": assignment["account_id"],
                "session_key_hash": hashlib.sha256(assignment["session_key"].encode()).hexdigest()}

    def inspect_and_record(self, *, task_id: str, attempt_id: str) -> dict:
        current = self.now()
        if not isinstance(current, (int, float)) or not math.isfinite(current):
            raise ValueError("invalid current time")
        with self.store._connect() as db:
            before = self._snapshot(db, task_id, attempt_id, current)
        observed = self.commit.inspect(
            pr_number=before["pr_number"], expected_head_sha=before["head_sha"],
            expected_user_id=before["github_user_id"])
        if (not isinstance(observed, CommitObservation)
                or observed.assurance != "signed_commit_account_observed_unattributed"
                or observed.production_finalization_permitted
                or observed.live_send_permitted
                or observed.repository_id != before["repository_id"]
                or observed.pr_number != before["pr_number"]
                or observed.head_sha != before["head_sha"]
                or observed.author_user_id != before["github_user_id"]
                or observed.committer_user_id != before["github_user_id"]
                or not math.isfinite(observed.observed_at)
                or not -5 <= self.now()-observed.observed_at <= self.max_age_seconds):
            raise ValueError("commit observation does not match task or trusted worker")
        audit = {**before, "assurance": "signed_commit_local_mock_worker_correlation"}
        digest = _digest(audit)
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            after = self._snapshot(db, task_id, attempt_id, self.now())
            if after != before:
                raise ValueError("worker/task/review changed during GitHub query")
            old = db.execute("""SELECT * FROM orchestrator_implementer_provenance
                WHERE task_id=?""", (task_id,)).fetchone()
            if old is not None:
                if old["digest"] != digest or old["attempt_id"] != attempt_id:
                    raise ValueError("implementer observation sealed for different inputs")
                created, at = False, old["observed_at"]
            else:
                at, created = observed.observed_at, True
                db.execute("""INSERT INTO orchestrator_implementer_provenance
                    (task_id,attempt_id,worker_id,github_user_id,repository_id,pr_number,
                    head_sha,package_sha256,claim_version,review_digest,digest,observed_at,assurance)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (task_id,attempt_id,before["worker_id"],before["github_user_id"],
                     before["repository_id"],before["pr_number"],before["head_sha"],
                     before["package_sha256"],before["claim_version"],before["review_digest"],
                     digest,at,"signed_commit_local_mock_worker_correlation"))
                self.store._event(db,task_id,"implementer.provider_observed",
                                  "read_only_mock_worker_correlation; no authorization")
        return {"task_id": task_id, "attempt_id": attempt_id,
                "worker_id": before["worker_id"], "github_user_id": before["github_user_id"],
                "digest": digest,"new":created,"observed_at":at,
                "assurance":"signed_commit_local_mock_worker_correlation",
                "production_finalization_permitted":False,"live_send_permitted":False}

    def get(self, task_id: str) -> dict | None:
        with self.store._connect() as db:
            row = db.execute("SELECT * FROM orchestrator_implementer_provenance WHERE task_id=?",
                             (task_id,)).fetchone()
        return ({**dict(row),"production_finalization_permitted":False,
                 "live_send_permitted":False} if row else None)

    @staticmethod
    def production_finalization_permitted(*_, **__) -> bool:
        return False
