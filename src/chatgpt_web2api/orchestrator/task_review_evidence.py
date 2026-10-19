"""Persist task-bound GitHub review observations without granting any authority.

This is a conservative read-only observation journal. The GitHub reader and
numeric implementation identity must be supplied by trusted configuration.
No user-facing model output is an authorization or a provider attestation.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from typing import Callable

from .github_readonly_reviews import GitHubReadOnlyReviews, ReviewObservation
from .provider_evidence import ProviderEvidenceLedger
from .store import Store


def _hash(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class TaskReviewEvidenceLedger:
    """Immutable review receipt bound to an existing sealed provider CI record.

    A receipt is *not* authenticated permission to merge or complete a task.
    Rechecking GitHub and user approvals at the eventual action boundary is a
    separate missing P0 requirement.
    """

    def __init__(self, store: Store, ci: ProviderEvidenceLedger,
                 reviewer: GitHubReadOnlyReviews, *, trusted_implementer_user_id: int,
                 now: Callable[[], float] = time.time, max_age_seconds: int = 120):
        if not isinstance(store, Store) or not isinstance(ci, ProviderEvidenceLedger):
            raise TypeError("Store and provider evidence ledger required")
        if not isinstance(reviewer, GitHubReadOnlyReviews) or ci.store is not store:
            raise TypeError("read-only GitHub reviewer and same Store required")
        if (ci.gate.repository_id != reviewer.repository_id or
                ci.gate.owner.casefold() != reviewer.owner.casefold() or
                ci.gate.repo.casefold() != reviewer.repo.casefold()):
            raise ValueError("CI and reviewer must use the same trusted repository")
        if type(trusted_implementer_user_id) is not int or trusted_implementer_user_id < 1:
            raise ValueError("trusted implementation GitHub user ID required")
        if type(max_age_seconds) is not int or not 5 <= max_age_seconds <= 600:
            raise ValueError("invalid review freshness threshold")
        self.store, self.ci, self.reviewer = store, ci, reviewer
        self.trusted_implementer_user_id = trusted_implementer_user_id
        self.now, self.max_age_seconds = now, max_age_seconds
        with self.store._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS orchestrator_provider_review_observations (
                task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),
                attempt_id TEXT NOT NULL UNIQUE,
                repository_id INTEGER NOT NULL, pr_number INTEGER NOT NULL,
                head_sha TEXT NOT NULL, package_sha256 TEXT NOT NULL,
                claim_version INTEGER NOT NULL, ci_digest TEXT NOT NULL,
                trusted_implementer_user_id INTEGER NOT NULL,
                reviewer_ids_json TEXT NOT NULL, review_ids_json TEXT NOT NULL,
                digest TEXT NOT NULL, observed_at REAL NOT NULL,
                assurance TEXT NOT NULL CHECK(assurance='provider_read_only_review_unfinalized')
            )""")

    def _snapshot_locked(self, db, task_id: str, attempt_id: str, current_time: float) -> dict:
        binding = self.ci._binding(db, task_id, attempt_id)
        row = db.execute("""SELECT * FROM orchestrator_provider_observations
            WHERE task_id=? AND attempt_id=?""", (task_id, attempt_id)).fetchone()
        if row is None:
            raise ValueError("matching task-bound CI observation required")
        ci = dict(row)
        if (ci["assurance"] != "provider_read_only_unreviewed" or
                ci["repository_id"] != self.reviewer.repository_id or
                ci["package_sha256"] != binding["package_sha256"] or
                ci["result_sha256"] != binding["result_sha256"] or
                ci["claim_version"] != binding["claim_version"] or
                type(ci["pr_number"]) is not int or ci["pr_number"] < 1 or
                not isinstance(ci["head_sha"], str) or len(ci["head_sha"]) != 40):
            raise ValueError("CI receipt does not match current implementation")
        # Review inherits source provenance via the CI digest. Reopening
        # with a newly required pin must not grandfather unpinned records.
        workflow_blob_sha = ci["workflow_blob_sha"]
        pin = self.ci.gate.workflow_source_pin
        if pin is not None and workflow_blob_sha != pin.trusted_blob_sha:
            raise ValueError("CI observation missing trusted workflow source pin")
        if pin is None and workflow_blob_sha is not None:
            raise ValueError("CI observation pin lacks current controller authority")
        ci_data = {**binding, "repository_id": ci["repository_id"],
            "pr_number": ci["pr_number"], "head_sha": ci["head_sha"],
            "run_id": ci["run_id"], "workflow_id": ci["workflow_id"],
            "run_attempt": ci["run_attempt"], "assurance": ci["assurance"]}
        if workflow_blob_sha is not None:
            ci_data["workflow_blob_sha"] = workflow_blob_sha
        expected_ci_digest = _hash(ci_data)
        if ci["digest"] != expected_ci_digest:
            raise ValueError("CI observation digest invalid")
        if not self._fresh(ci["observed_at"], current_time):
            raise ValueError("CI observation stale or invalid")
        snapshot = {**binding, "repository_id": ci["repository_id"],
                    "pr_number": ci["pr_number"], "head_sha": ci["head_sha"],
                    "ci_digest": ci["digest"], "ci_observed_at": ci["observed_at"]}
        if workflow_blob_sha is not None:
            snapshot["workflow_blob_sha"] = workflow_blob_sha
        return snapshot

    def _fresh(self, observed: float, current: float) -> bool:
        try:
            a, b = float(observed), float(current)
        except (ValueError, TypeError, OverflowError):
            return False
        return (math.isfinite(a) and math.isfinite(b) and
                -5 <= b - a <= self.max_age_seconds)

    def inspect_and_record(self, *, task_id: str, attempt_id: str) -> dict:
        if not isinstance(task_id, str) or not 1 <= len(task_id) <= 128:
            raise ValueError("invalid task ID")
        if not isinstance(attempt_id, str) or not 1 <= len(attempt_id) <= 128:
            raise ValueError("invalid attempt ID")
        now = self.now()
        if not self._fresh(now, now):
            raise ValueError("invalid controller clock")
        with self.store._connect() as db:
            before = self._snapshot_locked(db, task_id, attempt_id, now)

        # External network calls outside any SQLite transaction. This adapter
        # itself re-reads GitHub PR HEAD after checking the reviewer identities.
        observed = self.reviewer.inspect(
            pr_number=before["pr_number"], expected_head_sha=before["head_sha"],
            implementer_user_id=self.trusted_implementer_user_id)
        if (not isinstance(observed, ReviewObservation) or
                not self._fresh(observed.observed_at, self.now()) or
                observed.assurance != "provider_read_only_review_unfinalized" or
                observed.production_finalization_permitted or observed.live_send_permitted or
                observed.repository_id != before["repository_id"] or
                observed.pr_number != before["pr_number"] or
                observed.head_sha != before["head_sha"] or
                len(observed.reviewer_ids) != len(observed.review_ids) or
                len(observed.reviewer_ids) < self.reviewer.required_approvals or
                len(set(observed.reviewer_ids)) != len(observed.reviewer_ids) or
                len(set(observed.review_ids)) != len(observed.review_ids) or
                self.trusted_implementer_user_id in observed.reviewer_ids or
                any(type(x) is not int or x <= 0 for x in
                    (*observed.reviewer_ids, *observed.review_ids))):
            raise ValueError("provider review observation cannot authorize or does not match task")
        data = {**{k:v for k,v in before.items() if k != "ci_observed_at"},
                "trusted_implementer_user_id": self.trusted_implementer_user_id,
                "reviewer_ids": list(observed.reviewer_ids),
                "review_ids": list(observed.review_ids),
                "assurance": "provider_read_only_review_unfinalized"}
        digest = _hash(data)
        with self.store._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            # A stale, replaced or mutated task / package / delivery / CI proof
            # must never seal a review made during the intervening GET calls.
            after = self._snapshot_locked(db, task_id, attempt_id, self.now())
            if after != before:
                raise ValueError("task or CI evidence changed during review query")
            old = db.execute("""SELECT * FROM orchestrator_provider_review_observations
                WHERE task_id=?""", (task_id,)).fetchone()
            if old is None:
                db.execute("""INSERT INTO orchestrator_provider_review_observations
                    (task_id,attempt_id,repository_id,pr_number,head_sha,
                    package_sha256,claim_version,ci_digest,trusted_implementer_user_id,
                    reviewer_ids_json,review_ids_json,digest,observed_at,assurance)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (task_id, attempt_id, before["repository_id"], before["pr_number"],
                     before["head_sha"], before["package_sha256"],before["claim_version"],
                     before["ci_digest"], self.trusted_implementer_user_id,
                     json.dumps(observed.reviewer_ids), json.dumps(observed.review_ids),
                     digest, observed.observed_at, "provider_read_only_review_unfinalized"))
                self.store._event(db, task_id, "review.provider_observed", "read_only; no authorization")
                created, sealed_time = True, observed.observed_at
            else:
                if old["digest"] != digest or old["attempt_id"] != attempt_id:
                    raise ValueError("review observation already sealed for different inputs")
                created, sealed_time = False, old["observed_at"]
        return {"task_id":task_id,"attempt_id":attempt_id,"digest":digest,
                "ci_digest":before["ci_digest"],"repository_id":before["repository_id"],
                "pr_number":before["pr_number"],"head_sha":before["head_sha"],
                "reviewer_ids":list(observed.reviewer_ids),"review_ids":list(observed.review_ids),
                "observed_at":sealed_time,"new":created,
                "assurance":"provider_read_only_review_unfinalized",
                "production_finalization_permitted":False,"live_send_permitted":False}

    def get(self, task_id: str) -> dict | None:
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("task ID required")
        with self.store._connect() as db:
            row = db.execute("""SELECT * FROM orchestrator_provider_review_observations
                WHERE task_id=?""",(task_id,)).fetchone()
        if row is None:
            return None
        out = dict(row)
        out["reviewer_ids"] = json.loads(out.pop("reviewer_ids_json"))
        out["review_ids"] = json.loads(out.pop("review_ids_json"))
        return {**out,"production_finalization_permitted":False,"live_send_permitted":False}

    @staticmethod
    def production_finalization_permitted(*_, **__) -> bool:
        return False
