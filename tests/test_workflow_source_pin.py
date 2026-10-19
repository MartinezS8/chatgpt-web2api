"""Source/identity hardening tests using deterministic GitHub REST replies."""
import base64
import hashlib

import pytest

from chatgpt_web2api.orchestrator.workflow_source_pin import (
    WorkflowSourceObservation,
    WorkflowSourcePin,
)

HEAD = "a" * 40
WORKFLOW = ".github/workflows/ci.yml"
BODY = b"name: CI\non: push\njobs:\n  lint:\n    runs-on: ubuntu-latest\n"
BLOB = hashlib.sha1(b"blob " + str(len(BODY)).encode() + b"\0" + BODY).hexdigest()
BASE = "/repos/Example/build"


class FakeGitHub:
    def __init__(self):
        self.calls = []
        self.workflow = {"id": 55, "path": WORKFLOW, "state": "active"}
        self.source = {"type": "file", "name": "ci.yml", "path": WORKFLOW,
                       "encoding": "base64", "size": len(BODY), "sha": BLOB,
                       "content": base64.b64encode(BODY).decode()}

    def __call__(self, path):
        self.calls.append(path)
        if path == BASE + "/actions/workflows/55":
            return self.workflow
        if path == BASE + f"/contents/{WORKFLOW}?ref={HEAD}":
            return self.source
        raise AssertionError("unexpected GitHub GET: " + path)


def pin(reader=None, **changes):
    args = dict(owner="Example", repo="build", repository_id=77,
                workflow_id=55, workflow_path=WORKFLOW, trusted_blob_sha=BLOB,
                reader=reader or FakeGitHub())
    args.update(changes)
    return WorkflowSourcePin(**args)


def run(**changes):
    base = {"workflow_id": 55, "head_sha": HEAD, "path": WORKFLOW,
            "head_repository": {"id": 77}}
    base.update(changes)
    return base


def test_source_pinned_success_does_not_grant_authority():
    f = FakeGitHub()
    v = pin(f).inspect(expected_head_sha=HEAD, run=run())
    assert isinstance(v, WorkflowSourceObservation)
    assert v.workflow_blob_sha == BLOB and v.head_sha == HEAD
    assert not v.production_finalization_permitted and not v.live_send_permitted
    assert f.calls == [BASE + "/actions/workflows/55",
                       BASE + f"/contents/{WORKFLOW}?ref={HEAD}"]


@pytest.mark.parametrize("changes", [
    {"workflow_id": 54}, {"workflow_id": True},
    {"head_sha": "b" * 40}, {"path": ".github/workflows/evil.yml"},
    {"head_repository": {"id": 78}}, {"head_repository": {"id": "77"}},
    {"head_repository": None},
])
def test_run_mismatch_fails_before_git_fetch(changes):
    f = FakeGitHub()
    with pytest.raises(ValueError):
        pin(f).inspect(expected_head_sha=HEAD, run=run(**changes))
    assert f.calls == []


@pytest.mark.parametrize("changes", [
    {"id": 56}, {"id": "55"}, {"path": ".github/workflows/evil.yml"},
    {"state": "disabled_manually"}, {"state": None},
])
def test_workflow_metadata_mismatch(changes):
    f = FakeGitHub()
    f.workflow.update(changes)
    with pytest.raises(ValueError):
        pin(f).inspect(expected_head_sha=HEAD, run=run())
    assert len(f.calls) == 1


@pytest.mark.parametrize("changes", [
    {"sha": "0" * 40}, {"path": ".github/workflows/evil.yml"},
    {"type": "dir"}, {"encoding": "none"}, {"size": 0},
    {"size": 512 * 1024 + 1}, {"size": len(BODY) + 1},
    {"name": "evil.yml"}, {"content": "!!!!"},
    {"content": base64.b64encode(b"name: Fake CI").decode()},
])
def test_mutated_workflow_content_cannot_match_pin(changes):
    f = FakeGitHub()
    f.source.update(changes)
    with pytest.raises(ValueError):
        pin(f).inspect(expected_head_sha=HEAD, run=run())


@pytest.mark.parametrize("bad", [
    "", "../../../evil", "abc", ".github/workflows/.hidden.yml",
    ".github/workflows/x.yml?ref=main",
])
def test_untrusted_path_is_rejected(bad):
    with pytest.raises(ValueError):
        pin(workflow_path=bad)


@pytest.mark.parametrize("bad", ["0" * 40, "B" * 40, "", None, "notsha"])
def test_invalid_trusted_blob_sha_is_rejected(bad):
    with pytest.raises(ValueError):
        pin(trusted_blob_sha=bad)


def test_wrong_commit_head_fails():
    f = FakeGitHub()
    with pytest.raises(ValueError):
        pin(f).inspect(expected_head_sha="b" * 40, run=run())
    assert f.calls == []


def test_hash_matches_actual_git_blob_content():
    assert pin().inspect(expected_head_sha=HEAD, run=run()).workflow_blob_sha == BLOB
