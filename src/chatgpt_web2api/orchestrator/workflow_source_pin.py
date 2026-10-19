"""Fail-closed pinned GitHub Actions workflow source observation.

Only workflow bytes at the exact PR-HEAD commit matching a trusted Git blob
SHA can pass. This is read-only observation, never release authorization.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import re
from dataclasses import dataclass
from typing import Callable

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\Z")
_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.(?:yml|yaml)\Z")
_MAX_FILE_BYTES = 512 * 1024


@dataclass(frozen=True)
class WorkflowSourceObservation:
    repository_id: int
    workflow_id: int
    head_sha: str
    workflow_path: str
    workflow_blob_sha: str
    assurance: str = "provider_read_only_workflow_source_pinned"
    live_send_permitted: bool = False
    production_finalization_permitted: bool = False


class WorkflowSourcePin:
    """Verify controller-approved workflow bytes at an immutable PR HEAD."""

    def __init__(self, *, owner: str, repo: str, repository_id: int,
                 workflow_id: int, workflow_path: str, trusted_blob_sha: str,
                 reader: Callable[[str], dict]):
        if not isinstance(owner, str) or not _SLUG.fullmatch(owner) or owner in (".", ".."):
            raise ValueError("invalid owner")
        if not isinstance(repo, str) or not _SLUG.fullmatch(repo) or repo in (".", ".."):
            raise ValueError("invalid repository")
        if type(repository_id) is not int or repository_id <= 0:
            raise ValueError("repository ID required")
        if type(workflow_id) is not int or workflow_id <= 0:
            raise ValueError("workflow ID required")
        if (not isinstance(workflow_path, str)
                or not workflow_path.startswith(".github/workflows/")
                or not _FILENAME.fullmatch(workflow_path[len(".github/workflows/"):])):
            raise ValueError("invalid workflow path")
        if (not isinstance(trusted_blob_sha, str) or not _SHA.fullmatch(trusted_blob_sha)
                or trusted_blob_sha == "0" * 40):
            raise ValueError("operator-pinned workflow blob SHA required")
        if not callable(reader):
            raise ValueError("GitHub reader required")
        self.owner, self.repo = owner, repo
        self.repository_id = repository_id
        self.workflow_id, self.workflow_path = workflow_id, workflow_path
        self.trusted_blob_sha = trusted_blob_sha
        self.reader = reader
        self._base = f"/repos/{owner}/{repo}"

    def inspect(self, *, expected_head_sha: str, run: dict) -> WorkflowSourceObservation:
        if not isinstance(expected_head_sha, str) or not _SHA.fullmatch(expected_head_sha):
            raise ValueError("invalid commit SHA")
        if (not isinstance(run, dict)
                or type(run.get("workflow_id")) is not int
                or run["workflow_id"] != self.workflow_id
                or run.get("head_sha") != expected_head_sha
                or run.get("path") != self.workflow_path
                or type((run.get("head_repository") or {}).get("id")) is not int
                or run["head_repository"]["id"] != self.repository_id):
            raise ValueError("workflow run is not bound to pinned workflow")
        workflow = self.reader(self._base + f"/actions/workflows/{self.workflow_id}")
        if (not isinstance(workflow, dict) or type(workflow.get("id")) is not int
                or workflow["id"] != self.workflow_id
                or workflow.get("path") != self.workflow_path
                or workflow.get("state") != "active"):
            raise ValueError("workflow ID or active source path mismatch")
        source = self.reader(
            self._base + f"/contents/{self.workflow_path}?ref={expected_head_sha}")
        if (not isinstance(source, dict)
                or source.get("type") != "file"
                or source.get("path") != self.workflow_path
                or source.get("name") != self.workflow_path.rsplit("/", 1)[-1]
                or source.get("encoding") != "base64"
                or not isinstance(source.get("content"), str)
                or type(source.get("size")) is not int
                or not 1 <= source["size"] <= _MAX_FILE_BYTES
                or source.get("sha") != self.trusted_blob_sha):
            raise ValueError("workflow source metadata differs from trusted pin")
        try:
            raw = base64.b64decode("".join(source["content"].split()), validate=True)
        except (ValueError, binascii.Error):
            raise ValueError("workflow source base64 is invalid") from None
        if len(raw) != source["size"]:
            raise ValueError("workflow source length mismatch")
        git_blob_sha = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii")
                                      + b"\0" + raw).hexdigest()
        if git_blob_sha != self.trusted_blob_sha:
            raise ValueError("workflow source body differs from trusted blob pin")
        return WorkflowSourceObservation(
            repository_id=self.repository_id, workflow_id=self.workflow_id,
            head_sha=expected_head_sha, workflow_path=self.workflow_path,
            workflow_blob_sha=git_blob_sha,
        )
