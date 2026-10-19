"""Exercise the existing CI gate with a controller-pinned source.

These integration cases require the full stacked checkout.
"""
import base64
import hashlib
import pytest
from chatgpt_web2api.orchestrator.github_readonly_evidence import GitHubReadOnlyEvidence
from chatgpt_web2api.orchestrator.workflow_source_pin import WorkflowSourcePin
from test_orchestrator_github_readonly_evidence import FakeGitHubReader, SHA

PATH = ".github/workflows/ci.yml"
BODY = b"name: CI\non: push\njobs:\n  lint:\n    runs-on: ubuntu-latest\n"
BLOB = hashlib.sha1(b"blob " + str(len(BODY)).encode() + b"\0" + BODY).hexdigest()


class PinnedReader(FakeGitHubReader):
    def __init__(self, *, altered=False, changed_path=False):
        super().__init__()
        self.altered = altered
        self.changed_path = changed_path

    def __call__(self, path):
        if path == "/repos/Acme/repo/actions/workflows/51":
            self.paths.append(path)
            return {"id": 51, "path": PATH, "state": "active"}
        if path == f"/repos/Acme/repo/contents/{PATH}?ref={SHA}":
            self.paths.append(path)
            raw = b"evil: true\n" if self.altered else BODY
            return {"type": "file", "name": "ci.yml", "path": PATH,
                    "encoding": "base64", "size": len(raw), "sha": BLOB,
                    "content": base64.b64encode(raw).decode()}
        value = super().__call__(path)
        if path == "/repos/Acme/repo/actions/runs/99":
            return {**value, "path": ".github/workflows/evil.yml"
                    if self.changed_path else PATH}
        return value


def gate(reader):
    source = WorkflowSourcePin(owner="Acme", repo="repo", repository_id=137,
        workflow_id=51, workflow_path=PATH, trusted_blob_sha=BLOB, reader=reader)
    return GitHubReadOnlyEvidence(owner="Acme", repo="repo", repository_id=137,
        trusted_workflow_ids=frozenset({51}), required_job_names=frozenset({"lint", "unit"}),
        reader=reader, workflow_source_pin=source)


def test_workflow_pin_reaches_final_read_only_receipt():
    receipt = gate(PinnedReader()).inspect(pr_number=7, expected_head_sha=SHA, run_id=99)
    assert receipt.workflow_blob_sha == BLOB
    assert not receipt.production_finalization_permitted
    assert not receipt.live_send_permitted


def test_changed_contents_fail_even_if_ci_is_green():
    with pytest.raises(ValueError, match="workflow source body"):
        gate(PinnedReader(altered=True)).inspect(
            pr_number=7, expected_head_sha=SHA, run_id=99)


def test_changed_run_workflow_path_fail_even_if_ci_is_green():
    with pytest.raises(ValueError, match="workflow run"):
        gate(PinnedReader(changed_path=True)).inspect(
            pr_number=7, expected_head_sha=SHA, run_id=99)


def test_source_policy_must_share_same_trusted_reader_and_repo():
    reader = PinnedReader()
    other = WorkflowSourcePin(owner="Acme", repo="repo", repository_id=138,
        workflow_id=51, workflow_path=PATH, trusted_blob_sha=BLOB, reader=reader)
    with pytest.raises(ValueError, match="trusted workflow pin"):
        GitHubReadOnlyEvidence(owner="Acme", repo="repo", repository_id=137,
            trusted_workflow_ids=frozenset({51}), required_job_names=frozenset({"lint"}),
            reader=reader, workflow_source_pin=other)


def test_unpinned_legacy_receipt_reports_missing_source_provenance():
    reader = FakeGitHubReader()
    original = GitHubReadOnlyEvidence(owner="Acme", repo="repo", repository_id=137,
        trusted_workflow_ids=frozenset({51}), required_job_names=frozenset({"lint", "unit"}),
        reader=reader)
    receipt = original.inspect(pr_number=7, expected_head_sha=SHA, run_id=99)
    assert receipt.workflow_blob_sha is None
    assert not receipt.production_finalization_permitted
