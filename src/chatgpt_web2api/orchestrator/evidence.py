"""Strict, offline GitHub evidence policy; no provider I/O or remote writes.

Evidence MUST originate from a separately authorized, read-only provider
adapter. A user-supplied dict/agent message is never sufficient proof.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class CheckEvidence:
    name: str
    head_sha: str
    conclusion: str


@dataclass(frozen=True)
class ReviewEvidence:
    reviewer_user_id: int
    state: str
    commit_sha: str


@dataclass(frozen=True)
class PullRequestEvidence:
    repository_id: int
    pull_number: int
    head_sha: str
    author_user_id: int
    state: str
    is_draft: bool
    checks: tuple[CheckEvidence, ...]
    reviews: tuple[ReviewEvidence, ...]


class EvidenceReader(Protocol):
    """Must be bound to an independently authenticated provider connection."""

    def get_pull_request(self, repository_id: int, pull_number: int) -> PullRequestEvidence:
        ...


def github_result_ref(repo_id: int, pr_number: int, head_sha: str) -> str:
    if repo_id <= 0 or pr_number <= 0 or not _SHA.fullmatch(head_sha):
        raise ValueError("invalid GitHub evidence identity")
    return f"github:{repo_id}:pr:{pr_number}:sha:{head_sha}"


@dataclass(frozen=True)
class EvidenceVerdict:
    approved: bool
    reason: str
    head_sha: str
    reviewer_user_id: int | None = None


def verify_github_review(
    source: PullRequestEvidence,
    *,
    repository_id: int,
    pull_number: int,
    expected_sha: str,
    required_checks: tuple[str, ...],
    allowed_reviewers: frozenset[int] | None = None,
) -> EvidenceVerdict:
    """Read-only decision bound to exact provider-sourced PR head and checks.

    A green check from an *older* commit never authorizes a new head.
    Reviewers must approve this very SHA and differ from the PR author.
    """
    fail = lambda reason: EvidenceVerdict(False, reason, expected_sha)
    if not _SHA.fullmatch(expected_sha) or repository_id <= 0 or pull_number <= 0:
        return fail("invalid_requested_identity")
    if source.repository_id != repository_id or source.pull_number != pull_number:
        return fail("repository_or_pr_mismatch")
    if source.head_sha != expected_sha:
        return fail("stale_head_sha")
    if source.state != "open" or source.is_draft:
        return fail("pr_not_ready_for_review")
    if source.author_user_id <= 0:
        return fail("missing_author_identity")
    if not required_checks or len(set(required_checks)) != len(required_checks):
        return fail("required_check_policy_missing")
    passed: set[str] = set()
    for check in source.checks:
        if check.name in required_checks and check.head_sha == expected_sha:
            if check.conclusion != "success":
                return fail("required_check_not_successful")
            passed.add(check.name)
    if not set(required_checks).issubset(passed):
        return fail("required_checks_missing")
    # Review state must be determined by the *latest* vote of each reviewer,
    # not by any historic approval; the adapter must preserve provider order.
    latest_reviews: dict[int, ReviewEvidence] = {}
    for review in source.reviews:
        latest_reviews[review.reviewer_user_id] = review
    if any(review.state == "CHANGES_REQUESTED" for review in latest_reviews.values()):
        return fail("outstanding_changes_requested")
    for reviewer_id, review in latest_reviews.items():
        if reviewer_id == source.author_user_id or reviewer_id <= 0:
            continue
        if allowed_reviewers is not None and reviewer_id not in allowed_reviewers:
            continue
        if review.state == "APPROVED" and review.commit_sha == expected_sha:
            return EvidenceVerdict(True, "provider_evidence_satisfies_policy", expected_sha, reviewer_id)
    return fail("independent_current_sha_approval_missing")