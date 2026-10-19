"""Provider-read-only GitHub review observations; never a merge or task approval.

This module intentionally DOES NOT finalize tasks or confer privileges. Its
allowlist and reviewer IDs must come from trusted operator configuration, not
from an LLM answer. Default-deny on incomplete provider responses.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z")
_BASE = re.compile(r"/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_REVIEWS = re.compile(r"/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pulls/[1-9][0-9]*/reviews\?per_page=100&page=1\Z")
_PR = re.compile(r"/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pulls/[1-9][0-9]*\Z")
_COMMIT = re.compile(r"/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/commits/[0-9a-f]{40}\Z")
_PERMISSION = re.compile(r"/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/collaborators/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/permission\Z")


class ReviewReader(Protocol):
    def __call__(self, path: str) -> dict | list: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("GitHub review read refuses redirects")


class GitHubReviewsHTTP:
    """GET only four explicit GitHub endpoint shapes, with no redirect or leak."""

    def __init__(self, token: str | None = None, *, timeout_seconds: float = 8.0):
        if token is not None and (not isinstance(token, str) or not token.strip()):
            raise ValueError("invalid GitHub credential")
        if not isinstance(timeout_seconds, (int, float)) or not 1 <= timeout_seconds <= 30:
            raise ValueError("invalid timeout")
        self._token = token
        self._timeout = timeout_seconds
        self._opener = build_opener(_NoRedirect())

    def __call__(self, path: str) -> dict | list:
        if not isinstance(path, str) or not any(p.fullmatch(path) for p in (_BASE, _PR, _REVIEWS, _PERMISSION, _COMMIT)):
            raise ValueError("GitHub review endpoint not permitted")
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "OrchestratorReviewReadOnly/1",
        }
        if self._token:
            headers["Authorization"] = "Bearer " + self._token
        req = Request("https://api.github.com" + path, headers=headers, method="GET")
        try:
            with self._opener.open(req, timeout=self._timeout) as response:
                if response.status != 200:
                    raise RuntimeError("GitHub review GET not HTTP 200")
                payload = response.read(1024 * 1024 + 1)
        except (HTTPError, URLError, OSError):
            raise RuntimeError("GitHub review provider read failed") from None
        if len(payload) > 1024 * 1024:
            raise ValueError("GitHub review response too large")
        try:
            result = json.loads(payload)
        except (UnicodeError, ValueError):
            raise ValueError("GitHub review returned invalid JSON") from None
        if not isinstance(result, (dict, list)):
            raise ValueError("GitHub review response must be an object or array")
        return result


@dataclass(frozen=True)
class ReviewObservation:
    repository_id: int
    pr_number: int
    head_sha: str
    reviewer_ids: tuple[int, ...]
    review_ids: tuple[int, ...]
    observed_at: float
    assurance: str = "provider_read_only_review_unfinalized"
    production_finalization_permitted: bool = False
    live_send_permitted: bool = False


class GitHubReadOnlyReviews:
    """Verify independently authorized, SHA-bound approvals without mutating.

    `implementer_user_id` is a trusted controller-side identity; the PR's
    GitHub author is excluded independently. This class is NOT a finalizer:
    a future finalizer must re-read provider state at its decision boundary.
    """

    def __init__(self, *, owner: str, repo: str, repository_id: int,
                 trusted_reviewer_ids: frozenset[int], reader: ReviewReader,
                 required_approvals: int = 1, now: Callable[[], float] = time.time):
        if any(not isinstance(x, str) or not _NAME.fullmatch(x) or x in (".", "..")
               for x in (owner, repo)):
            raise ValueError("invalid repository address")
        if type(repository_id) is not int or repository_id <= 0:
            raise ValueError("trusted repository ID required")
        if (not isinstance(trusted_reviewer_ids, frozenset) or not trusted_reviewer_ids
                or any(type(x) is not int or x < 1 for x in trusted_reviewer_ids)):
            raise ValueError("trusted numeric reviewer IDs required")
        if type(required_approvals) is not int or not 1 <= required_approvals <= len(trusted_reviewer_ids):
            raise ValueError("invalid approval threshold")
        self.owner, self.repo, self.repository_id = owner, repo, repository_id
        self.trusted_reviewer_ids = trusted_reviewer_ids
        self.required_approvals = required_approvals
        self.reader, self.now = reader, now
        self._base = f"/repos/{owner}/{repo}"

    def _pr(self, value: dict | list, pr_number: int, expected_sha: str) -> int:
        if not isinstance(value, dict):
            raise ValueError("malformed GitHub PR")
        base, head, author = value.get("base"), value.get("head"), value.get("user")
        if (type(value.get("number")) is not int or value["number"] != pr_number
                or value.get("state") != "open" or value.get("merged") is not False
                or value.get("draft") is not False
                or not isinstance(base, dict) or not isinstance(base.get("repo"), dict)
                or base["repo"].get("id") != self.repository_id
                or not isinstance(head, dict) or head.get("sha") != expected_sha
                or not isinstance(author, dict) or type(author.get("id")) is not int
                or author["id"] <= 0):
            raise ValueError("GitHub PR head, author or state changed")
        return author["id"]

    @staticmethod
    def _timestamp(value: str) -> datetime:
        if not isinstance(value, str):
            raise ValueError("review submission time missing")
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("malformed review submission time") from None
        if timestamp.tzinfo is None:
            raise ValueError("review submission time missing timezone")
        return timestamp.astimezone(timezone.utc)

    def inspect(self, *, pr_number: int, expected_head_sha: str,
                implementer_user_id: int) -> ReviewObservation:
        if (type(pr_number) is not int or pr_number < 1
                or type(implementer_user_id) is not int or implementer_user_id < 1
                or not isinstance(expected_head_sha, str) or not _SHA.fullmatch(expected_head_sha)):
            raise ValueError("invalid review request")
        base = self._base
        repo = self.reader(base)
        if (not isinstance(repo, dict) or type(repo.get("id")) is not int
                or repo["id"] != self.repository_id
                or str(repo.get("full_name", "")).casefold() !=
                   f"{self.owner}/{self.repo}".casefold()):
            raise ValueError("GitHub repository identity mismatch")
        path = base + f"/pulls/{pr_number}"
        author_id = self._pr(self.reader(path), pr_number, expected_head_sha)
        items = self.reader(path + "/reviews?per_page=100&page=1")
        if not isinstance(items, list) or len(items) >= 100:
            # GitHub returns chronological pages. One full page requires more
            # pages; never mistake an incomplete history for a current approval.
            raise ValueError("review history incomplete or malformed")

        latest: dict[int, dict] = {}
        seen_ids: set[int] = set()
        previous_ts: datetime | None = None
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("user"), dict):
                raise ValueError("malformed GitHub review")
            actor = item["user"]
            uid, login, review_id = actor.get("id"), actor.get("login"), item.get("id")
            state = item.get("state")
            if (type(uid) is not int or uid < 1 or type(review_id) is not int
                    or review_id < 1 or review_id in seen_ids
                    or not isinstance(login, str) or not _NAME.fullmatch(login)):
                raise ValueError("invalid review identity")
            seen_ids.add(review_id)
            if state == "PENDING":
                continue
            if state not in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED", "COMMENTED"):
                raise ValueError("unknown review state")
            when = self._timestamp(item.get("submitted_at"))
            if previous_ts is not None and when < previous_ts:
                raise ValueError("review history order changed")
            previous_ts = when
            if state != "COMMENTED":
                latest[uid] = item

        # Conservative: outstanding change requests are a veto, even if another
        # reviewer has approved. The requesting reviewer must clear their own
        # change request or GitHub must dismiss it explicitly.
        if any(v["state"] == "CHANGES_REQUESTED" for v in latest.values()):
            raise ValueError("unresolved changes requested")

        approvals: list[tuple[int, int]] = []
        for uid, review in latest.items():
            if (uid not in self.trusted_reviewer_ids or uid in (author_id, implementer_user_id)
                    or review["state"] != "APPROVED"
                    or review.get("commit_id") != expected_head_sha):
                continue
            login = review["user"]["login"]
            perm = self.reader(base + f"/collaborators/{login}/permission")
            if (not isinstance(perm, dict) or perm.get("permission") not in ("write", "admin")
                    or not isinstance(perm.get("user"), dict)
                    or type(perm["user"].get("id")) is not int
                    or perm["user"]["id"] != uid):
                raise ValueError("reviewer is not independently authorized")
            approvals.append((uid, review["id"]))
        if len(approvals) < self.required_approvals:
            raise ValueError("insufficient current independent approvals")
        # Re-read head after all reviews/permissions (avoid stale approval).
        self._pr(self.reader(path), pr_number, expected_head_sha)
        approvals.sort()
        return ReviewObservation(
            repository_id=self.repository_id, pr_number=pr_number,
            head_sha=expected_head_sha,
            reviewer_ids=tuple(uid for uid, _ in approvals),
            review_ids=tuple(rid for _, rid in approvals), observed_at=self.now(),
        )
