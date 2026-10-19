"""Read-only GitHub PR/Actions evidence, never an authorization to finalize.

This adapter does not access browser sessions, approve a review, merge a PR, or
change external resources. An authenticated repository read is not a trusted
human-review attestation or a substitute for a transactional finalization gate.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Callable, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .workflow_source_pin import WorkflowSourcePin

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z")
_JOB_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/() -]{0,127}\Z")
_JOBS_QUERY = "?filter=latest&per_page=100"


class JsonReader(Protocol):
    def __call__(self, path: str) -> dict: ...


class _NeverRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("GitHub evidence read refused an HTTP redirect")


class GitHubReadOnlyHTTP:
    """Strictly allow GET requests to the official GitHub REST endpoint.

    A token is accepted explicitly from a trusted local runtime. It is never
    interpolated into a URL, exception message or persisted record. Redirects
    are disabled to avoid forwarding Authorization outside api.github.com.
    """

    def __init__(self, token: str | None = None, *, timeout_seconds: float = 8.0):
        if token is not None and (not isinstance(token, str) or not token.strip()):
            raise ValueError("invalid GitHub credential")
        if not 1 <= timeout_seconds <= 30:
            raise ValueError("invalid GitHub evidence timeout")
        self._token = token
        self._timeout = timeout_seconds
        self._opener = build_opener(_NeverRedirect())

    def __call__(self, path: str) -> dict:
        allowed_default = re.fullmatch(
            r"/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/pulls/[0-9]+|/actions/runs/[0-9]+(?:/jobs\?filter=latest&per_page=100)?)?", path)
        allowed_workflow = re.fullmatch(
            r"/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/actions/workflows/[0-9]+", path)
        allowed_pinned_content = re.fullmatch(
            r"/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/contents/\.github/workflows/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.(?:yml|yaml)\?ref=[0-9a-f]{40}", path)
        if not (allowed_default or allowed_workflow or allowed_pinned_content):
            raise ValueError("GitHub evidence path is not an allowed read-only endpoint")
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "OrchestratorReadOnlyEvidence/1",
        }
        if self._token:
            headers["Authorization"] = "Bearer " + self._token
        req = Request("https://api.github.com" + path, headers=headers, method="GET")
        try:
            with self._opener.open(req, timeout=self._timeout) as response:
                if response.status != 200:
                    raise RuntimeError("GitHub evidence GET did not return HTTP 200")
                # Reject oversized API responses instead of buffering indefinitely.
                payload = response.read(1024 * 1024 + 1)
        except (HTTPError, URLError, OSError) as exc:
            # Do not expose response bodies, auth headers or potentially
            # sensitive provider diagnostic messages to untrusted observers.
            raise RuntimeError("GitHub evidence read failed") from None
        if len(payload) > 1024 * 1024:
            raise ValueError("GitHub evidence response exceeded size limit")
        try:
            result = json.loads(payload)
        except (ValueError, UnicodeError):
            raise ValueError("GitHub evidence returned invalid JSON") from None
        if not isinstance(result, dict):
            raise ValueError("GitHub evidence must be a JSON object")
        return result


@dataclass(frozen=True)
class ReadOnlyPRRunReceipt:
    repository_id: int
    repository: str
    pr_number: int
    head_sha: str
    run_id: int
    workflow_id: int
    run_attempt: int
    verified_at: float
    event: str
    head_branch: str
    successful_jobs: tuple[str, ...]
    workflow_blob_sha: str | None = None
    assurance: str = "provider_read_only_unreviewed"
    live_send_permitted: bool = False
    production_finalization_permitted: bool = False


class GitHubReadOnlyEvidence:
    """Evaluate a PR's current SHA against an allowlisted successful workflow.

    `reader` may be the real GitHubReadOnlyHTTP or a deterministic fake. The
    caller must supply the trusted numeric repository ID and trusted workflow
    IDs, not values supplied by the implementation agent being evaluated.
    """

    def __init__(self, *, owner: str, repo: str, repository_id: int,
                 trusted_workflow_ids: frozenset[int], reader: JsonReader,
                 required_job_names: frozenset[str],
                 trusted_events: frozenset[str] = frozenset({"push"}),
                 now: Callable[[], float] = time.time,
                 workflow_source_pin: WorkflowSourcePin | None = None):
        if not isinstance(owner, str) or not _SLUG.fullmatch(owner) or owner in (".", ".."):
            raise ValueError("invalid GitHub owner")
        if not isinstance(repo, str) or not _SLUG.fullmatch(repo) or repo in (".", ".."):
            raise ValueError("invalid GitHub repository")
        if type(repository_id) is not int or repository_id <= 0:
            raise ValueError("trusted numeric repository ID is required")
        if (not isinstance(trusted_workflow_ids, frozenset) or not trusted_workflow_ids
                or any(type(i) is not int or i <= 0 for i in trusted_workflow_ids)):
            raise ValueError("at least one trusted numeric workflow ID is required")
        # Explicit, operator-owned CI policy: no empty set and no arbitrary
        # workflow_dispatch / pull_request events treated as branch SHA proof.
        # GitHub pull_request CI often tests a synthetic merge SHA and needs a
        # separate provider-aware proof design before it is accepted here.
        if trusted_events != frozenset({"push"}):
            raise ValueError("only push event with direct head SHA is supported")
        if (not isinstance(required_job_names, frozenset) or not required_job_names or
                len(required_job_names) > 100 or any(
                    not isinstance(name, str) or not _JOB_NAME.fullmatch(name)
                    for name in required_job_names)):
            raise ValueError("explicit required CI job names are mandatory")
        if workflow_source_pin is not None and (
                not isinstance(workflow_source_pin, WorkflowSourcePin)
                or workflow_source_pin.repository_id != repository_id
                or workflow_source_pin.owner.casefold() != owner.casefold()
                or workflow_source_pin.repo.casefold() != repo.casefold()
                or workflow_source_pin.workflow_id not in trusted_workflow_ids
                or workflow_source_pin.reader is not reader):
            raise ValueError("trusted workflow pin must match CI reader and repository")
        self.workflow_source_pin = workflow_source_pin
        self.required_job_names = required_job_names
        self.trusted_events = trusted_events
        self.owner, self.repo = owner, repo
        self.repository_id = repository_id
        self.trusted_workflow_ids = trusted_workflow_ids
        self.reader = reader
        self.now = now
        self._base = f"/repos/{owner}/{repo}"

    def _check_repo(self, repo: dict) -> None:
        if (not isinstance(repo, dict)
                or type(repo.get("id")) is not int or repo["id"] != self.repository_id
                or str(repo.get("full_name", "")).casefold() !=
                    f"{self.owner}/{self.repo}".casefold()):
            raise ValueError("GitHub repository identity mismatch")

    def _check_pr(self, pr: dict, *, pr_number: int, head_sha: str) -> str:
        if not isinstance(pr, dict):
            raise ValueError("malformed GitHub pull request")
        base = pr.get("base") or {}
        if (type(pr.get("number")) is not int or pr["number"] != pr_number
                or pr.get("state") != "open" or pr.get("merged") is not False
                or not isinstance(base, dict)
                or type((base.get("repo") or {}).get("id")) is not int
                or base["repo"]["id"] != self.repository_id
                or (pr.get("head") or {}).get("sha") != head_sha
                or not isinstance((pr.get("head") or {}).get("ref"), str)
                or not (pr.get("head") or {}).get("ref")
                or type(((pr.get("head") or {}).get("repo") or {}).get("id")) is not int
                or pr["head"]["repo"]["id"] != self.repository_id):
            raise ValueError("GitHub PR head, state or repository identity changed")
        return pr["head"]["ref"]

    def inspect(self, *, pr_number: int, expected_head_sha: str,
                run_id: int) -> ReadOnlyPRRunReceipt:
        if (type(pr_number) is not int or pr_number < 1
                or type(run_id) is not int or run_id < 1
                or not isinstance(expected_head_sha, str)
                or not _SHA.fullmatch(expected_head_sha)):
            raise ValueError("invalid GitHub evidence request")
        self._check_repo(self.reader(self._base))
        path = self._base + f"/pulls/{pr_number}"
        branch = self._check_pr(self.reader(path), pr_number=pr_number,
                                head_sha=expected_head_sha)
        run = self.reader(self._base + f"/actions/runs/{run_id}")
        if not isinstance(run, dict):
            raise ValueError("malformed GitHub workflow run")
        run_repo = run.get("repository") or {}
        if (type(run.get("id")) is not int or run["id"] != run_id
                or type(run_repo.get("id")) is not int or run_repo["id"] != self.repository_id
                or type(run.get("workflow_id")) is not int
                or run["workflow_id"] not in self.trusted_workflow_ids
                or run.get("head_sha") != expected_head_sha
                or run.get("event") not in self.trusted_events
                or run.get("head_branch") != branch
                or type((run.get("head_repository") or {}).get("id")) is not int
                or run["head_repository"]["id"] != self.repository_id
                or run.get("status") != "completed"
                or run.get("conclusion") != "success"
                or type(run.get("run_attempt")) is not int or run["run_attempt"] < 1):
            raise ValueError("GitHub workflow evidence not trusted or not successful")
        # The collection MUST be complete: a paginated subset may omit failed
        # jobs, and any missing required job is an explicit refusal.
        jobs_result = self.reader(self._base + f"/actions/runs/{run_id}/jobs" + _JOBS_QUERY)
        if not isinstance(jobs_result, dict):
            raise ValueError("GitHub workflow jobs response malformed")
        jobs = jobs_result.get("jobs")
        total = jobs_result.get("total_count")
        if (type(total) is not int or not 1 <= total <= 100 or
                not isinstance(jobs, list) or len(jobs) != total):
            raise ValueError("GitHub CI job list is incomplete or malformed")
        verified_jobs = {}
        for job in jobs:
            if not isinstance(job, dict) or not isinstance(job.get("name"), str):
                raise ValueError("GitHub CI job has invalid identity")
            name = job["name"]
            if name in verified_jobs:
                raise ValueError("duplicate GitHub CI job identity")
            if (type(job.get("run_id")) is not int or job["run_id"] != run_id
                    or job.get("head_sha") != expected_head_sha
                    or job.get("status") != "completed"
                    or job.get("conclusion") != "success"
                    or ("run_attempt" in job and job["run_attempt"] != run["run_attempt"])):
                raise ValueError("GitHub CI job missing, stale or unsuccessful")
            verified_jobs[name] = True
        if not self.required_job_names.issubset(verified_jobs):
            raise ValueError("required GitHub CI jobs are missing")
        # A green CI run is not trusted workflow provenance: pin the YAML
        # on the PR-head commit against independently configured bytes.
        workflow_blob_sha = None
        if self.workflow_source_pin is not None:
            pinned = self.workflow_source_pin.inspect(
                expected_head_sha=expected_head_sha, run=run)
            workflow_blob_sha = pinned.workflow_blob_sha
        # Reduce the time-of-check/time-of-use window: an updated PR head
        # during the CI fetch must fail, not produce an apparently valid proof.
        final_branch = self._check_pr(self.reader(path), pr_number=pr_number,
                                      head_sha=expected_head_sha)
        if final_branch != branch:
            raise ValueError("GitHub PR branch changed during evidence check")
        return ReadOnlyPRRunReceipt(
            repository_id=self.repository_id,
            repository=f"{self.owner}/{self.repo}",
            pr_number=pr_number,
            head_sha=expected_head_sha,
            run_id=run_id,
            workflow_id=run["workflow_id"],
            run_attempt=run["run_attempt"],
            verified_at=self.now(),
            event=run["event"],
            head_branch=branch,
            successful_jobs=tuple(sorted(verified_jobs)),
            workflow_blob_sha=workflow_blob_sha,
        )
